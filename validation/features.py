"""Replay QuantBot features vs Gordongecko rules on 12 months of hourly, Robinhood-tradable ETFs.
Signal fixed in advance (cleanroom gold champion: 20-bar Donchian breakout, long only), so the 12-month
window is fully out-of-sample for every market."""
import json
import numpy as np
import pandas as pd

H = pd.read_pickle("data/hourly_etf.pkl")
REG = pd.read_csv("out/regime_daily.csv", index_col=0, parse_dates=True)["prior_label"]
MULT = {"RISK-ON": 1.0, "CONSTRUCTIVE": 0.75, "CAUTION": 0.5, "DEFENSIVE": 0.0, "UNKNOWN": 0.0}
ETFS = {"SPY": "US large cap", "IWM": "US small cap", "QQQ": "US tech", "GLD": "Gold", "EWJ": "Japan", "EWG": "Germany",
        "EWU": "UK", "FXI": "China", "INDA": "India", "EWY": "Korea", "EWZ": "Brazil", "EEM": "Emerging mkts"}
START, END = pd.Timestamp("2025-11-20", tz="America/New_York"), pd.Timestamp("2026-11-21", tz="America/New_York")
COST = 0.0005   # 0.05% round trip
RISK = 0.01
rng = np.random.default_rng(11)


def bars(t):
    d = H[t][["Open", "High", "Low", "Close"]].dropna().copy()
    d.columns = ["o", "h", "l", "c"]
    pc = d.c.shift()
    d["atr"] = pd.concat([d.h - d.l, (d.h - pc).abs(), (d.l - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    d["sig"] = (d.c > d.h.rolling(20).max().shift()).astype(int)
    day = d.index.tz_convert("America/New_York").normalize().tz_localize(None)
    d["day"] = day
    d["last"] = pd.Series(day, index=d.index).shift(-1).ne(pd.Series(day, index=d.index)).values  # last bar of session
    d["regime"] = pd.Series(day, index=d.index).map(REG).fillna("UNKNOWN").values
    return d


def sim(d, rules, sig=None):
    """rules: stop=('atr',k)|('pct',p); tp=('atr',k)|('pct',p); tmax bars; flatten; regime; be_at pct; killswitch"""
    o, h, l, c, a = (d[k].values for k in ("o", "h", "l", "c", "atr"))
    last, reg, day = d["last"].values, d["regime"].values, d["day"].values
    sig = d["sig"].values if sig is None else sig
    i0, i1 = np.searchsorted(d.index, START), np.searchsorted(d.index, END) - 1
    out, i, losers = [], max(i0, 20), {}
    while i < i1:
        if sig[i] != 1 or not np.isfinite(a[i]) or (rules.get("flatten") and last[i]):
            i += 1; continue
        m = MULT.get(reg[i + 1], 0.0) if rules.get("regime") else 1.0
        if m == 0 or (rules.get("kill") and losers.get(day[i + 1], 0) >= 2):
            i += 1; continue
        e = i + 1; px = o[e]
        st = px - rules["stop"][1] * a[i] if rules["stop"][0] == "atr" else px * (1 - rules["stop"][1])
        tg = px + rules["tp"][1] * a[i] if rules["tp"][0] == "atr" else px * (1 + rules["tp"][1])
        risk = px - st; j = e; ex = None; stopped = False; be = False
        while j <= i1 and j < e + rules["tmax"]:
            if l[j] <= st: ex = min(st, o[j]) if j > e else st; stopped = True; break
            if h[j] >= tg: ex = max(tg, o[j]) if j > e else tg; break
            if rules.get("be_at") and not be and h[j] >= px * (1 + rules["be_at"]): st = max(st, px); be = True
            if rules.get("flatten") and last[j]: ex = c[j]; break
            j += 1
        if ex is None: j = min(j, i1); ex = c[j]
        r = ((ex - px) / px - COST) * px / risk
        if stopped and r < 0: losers[day[e]] = losers.get(day[e], 0) + 1
        out.append((e, j, r * m, (ex - px) / px))
        i = j + 1
    return np.array(out) if out else np.zeros((0, 4))


def stats(tr, nb_days=None):
    if len(tr) == 0: return dict(trades=0, ret=0.0, dd=0.0, win=0.0, pf=0.0, expR=0.0)
    r = tr[:, 2]; eq = np.cumprod(1 + RISK * r); pk = np.maximum.accumulate(np.r_[1, eq])[1:]
    gl = -r[r < 0].sum()
    return dict(trades=len(r), ret=float(eq[-1] - 1), dd=float((1 - eq / pk).max()), win=float((r > 0).mean()),
                pf=float(r[r > 0].sum() / gl) if gl > 0 else 99.0, expR=float(r.mean()))


V = {
    "Q1 QuantBot style (ATR stop/target, holds overnight)": dict(stop=("atr", 1.0), tp=("atr", 6.0), tmax=24),
    "G1 + flatten at close": dict(stop=("atr", 1.0), tp=("atr", 6.0), tmax=24, flatten=True),
    "G2 + Gordongecko 5% stop, 5% target, breakeven at +2%": dict(stop=("pct", 0.05), tp=("pct", 0.05), tmax=24, flatten=True, be_at=0.02),
    "G3 + regime gate": dict(stop=("pct", 0.05), tp=("pct", 0.05), tmax=24, flatten=True, be_at=0.02, regime=True),
    "G4 + day kill switch (full Gordongecko)": dict(stop=("pct", 0.05), tp=("pct", 0.05), tmax=24, flatten=True, be_at=0.02, regime=True, kill=True),
    "H1 hybrid: ATR stop, flatten, regime gate": dict(stop=("atr", 1.0), tp=("atr", 6.0), tmax=24, flatten=True, regime=True, kill=True),
}

B = {t: bars(t) for t in ETFS}
res, lib, rand = [], {}, []
for vn, rules in V.items():
    curves = []
    for t, name in ETFS.items():
        d = B[t]; tr = sim(d, rules); st = stats(tr)
        # random-entry baseline: same rules, same number of entries at random bars in window
        i0, i1 = np.searchsorted(d.index, START), np.searchsorted(d.index, END) - 1
        rr = []
        for _ in range(200):
            s = np.zeros(len(d), int); n = max(st["trades"] * 3, 5)
            s[rng.choice(np.arange(i0, i1 - 1), size=min(n, i1 - i0 - 2), replace=False)] = 1
            rr.append(stats(sim(d, rules, s))["ret"])
        rr = np.array(rr)
        res.append(dict(variant=vn, etf=t, market=name, **st, rand_median=float(np.median(rr)), beats_random=float((rr < st["ret"]).mean())))
        # daily equity for library curve
        eq = pd.Series(1.0, index=d.index[(d.index >= START) & (d.index < END)])
        if len(tr):
            ex_t = d.index[tr[:, 1].astype(int)]; cum = np.cumprod(1 + RISK * tr[:, 2])
            eq = pd.Series(cum, index=ex_t).reindex(eq.index, method="ffill").fillna(1.0)
        curves.append(eq.groupby(eq.index.normalize()).last())
    L = pd.concat(curves, axis=1).ffill().fillna(1.0).mean(axis=1)
    lib[vn] = L
df = pd.DataFrame(res)
pd.set_option("display.width", 250)
summ = df.groupby("variant", sort=False).agg(trades=("trades", "sum"), mean_ret=("ret", "mean"), markets_profitable=("ret", lambda x: (x > 0).sum()),
                                             mean_dd=("dd", "mean"), win=("win", "mean"), beats_random=("beats_random", "mean"))
summ["library_ret"] = [lib[v].iloc[-1] - 1 for v in summ.index]
summ["library_dd"] = [float((1 - lib[v] / lib[v].cummax()).max()) for v in summ.index]
print(summ.round(3).to_string())
print(df[df.variant.str.startswith(("Q1", "G4", "H1"))][["variant", "etf", "trades", "ret", "dd", "win", "pf", "beats_random"]].round(3).to_string())
df.to_csv("out/features_by_etf.csv", index=False); summ.to_csv("out/features_summary.csv")
pd.DataFrame(lib).to_csv("out/library_curves.csv")
