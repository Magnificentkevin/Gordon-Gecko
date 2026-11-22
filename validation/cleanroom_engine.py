"""Cleanroom backtest engine + strategy generator for a QuantBot-style gold EA.
Built from public descriptions only. No QuantBot code or files used."""
import itertools
import numpy as np
import pandas as pd

COST = 0.50      # $/oz round trip (spread + slippage)
RISK = 0.01      # fraction of equity risked per trade


def load(path):
    d = pd.read_csv(path, header=[0, 1], index_col=0)
    d.columns = [c[0].lower() for c in d.columns]
    d.index = pd.to_datetime(d.index, utc=True)
    d = d[["open", "high", "low", "close"]].dropna()
    return d[(d.high >= d.low) & (d.close > 0)]


def atr(d, n=14):
    pc = d.close.shift()
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    dlt = s.diff()
    up = dlt.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-dlt.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


# ---------- signal families: return +1 long / -1 short / 0 on each bar close ----------
def sig_donchian(d, n, trend):
    hh = d.high.rolling(n).max().shift()
    ll = d.low.rolling(n).min().shift()
    s = np.where(d.close > hh, 1, np.where(d.close < ll, -1, 0))
    return _trend_filter(d, s, trend)


def sig_emacross(d, fast, slow, trend):
    f, sl = ema(d.close, fast), ema(d.close, slow)
    up = (f > sl) & (f.shift() <= sl.shift())
    dn = (f < sl) & (f.shift() >= sl.shift())
    return _trend_filter(d, np.where(up, 1, np.where(dn, -1, 0)), trend)


def sig_bollinger(d, n, k, trend):
    m = d.close.rolling(n).mean()
    sd = d.close.rolling(n).std()
    up = (d.close > m + k * sd) & (d.close.shift() <= (m + k * sd).shift())
    dn = (d.close < m - k * sd) & (d.close.shift() >= (m - k * sd).shift())
    return _trend_filter(d, np.where(up, 1, np.where(dn, -1, 0)), trend)


def sig_pullback(d, rlen, lvl, trend):
    r = rsi(d.close, rlen)
    t = ema(d.close, trend if trend else 200)
    up = (d.close > t) & (r < lvl) & (r.shift() >= lvl)
    dn = (d.close < t) & (r > 100 - lvl) & (r.shift() <= 100 - lvl)
    return np.where(up, 1, np.where(dn, -1, 0))


def _trend_filter(d, s, trend):
    if not trend:
        return s
    t = ema(d.close, trend).values
    c = d.close.values
    return np.where((s == 1) & (c > t), 1, np.where((s == -1) & (c < t), -1, 0))


FAMILIES = {
    "donchian": (sig_donchian, dict(n=[10, 20, 40, 60], trend=[0, 100, 200])),
    "emacross": (sig_emacross, dict(fast=[5, 10, 20], slow=[30, 50, 100], trend=[0, 200])),
    "bollinger": (sig_bollinger, dict(n=[20, 40], k=[1.5, 2.0, 2.5], trend=[0, 200])),
    "pullback": (sig_pullback, dict(rlen=[2, 5, 14], lvl=[10, 20, 30], trend=[100, 200])),
}
EXITS = dict(sl=[1.0, 1.5, 2.0, 3.0], tp=[2.0, 3.0, 4.0, 6.0], tmax=[6, 12, 24])
SIDES = ["both", "long", "short"]


def configs():
    for fam, (_, grid) in FAMILIES.items():
        for vals in itertools.product(*grid.values()):
            for ex in itertools.product(*EXITS.values()):
                for side in SIDES:
                    yield dict(fam=fam, p=dict(zip(grid.keys(), vals)),
                               sl=ex[0], tp=ex[1], tmax=ex[2], side=side)


def signals(d, cfg):
    f = FAMILIES[cfg["fam"]][0]
    s = np.asarray(f(d, **cfg["p"]), dtype=int)
    if cfg["side"] == "long":
        s = np.where(s == 1, 1, 0)
    elif cfg["side"] == "short":
        s = np.where(s == -1, -1, 0)
    return s


def simulate(d, sig, sl, tp, tmax, a=None, cost=COST, lo=0, hi=None):
    """One position at a time. Entry next-bar open. Stop checked before target.
    Returns trades as array of (entry_idx, exit_idx, R multiple after costs)."""
    o, h, l, c = d.open.values, d.high.values, d.low.values, d.close.values
    a = atr(d).values if a is None else a
    hi = len(d) - 1 if hi is None else hi
    out = []
    i = max(lo, 1)
    while i < hi:
        s = sig[i]
        if s == 0 or not np.isfinite(a[i]):
            i += 1
            continue
        e = i + 1
        px = o[e]
        risk = sl * a[i]
        stop = px - s * risk
        tgt = px + s * tp * a[i]
        j, exitpx = e, None
        while j <= min(e + tmax - 1, hi):
            if s == 1:
                if l[j] <= stop: exitpx = min(stop, o[j]) if j > e else stop; break
                if h[j] >= tgt: exitpx = max(tgt, o[j]) if j > e else tgt; break
            else:
                if h[j] >= stop: exitpx = max(stop, o[j]) if j > e else stop; break
                if l[j] <= tgt: exitpx = min(tgt, o[j]) if j > e else tgt; break
            j += 1
        if exitpx is None:
            j = min(e + tmax - 1, hi)
            exitpx = c[j]
        r = (s * (exitpx - px) - cost) / risk
        out.append((e, j, r))
        i = j + 1
    return np.array(out) if out else np.zeros((0, 3))


def stats(tr, bars_per_year=None, nbars=None):
    if len(tr) == 0:
        return dict(n=0, ret=0, dd=0, win=0, pf=0, expR=0, hold=0, score=-9)
    r = tr[:, 2]
    eq = np.cumprod(1 + RISK * r)
    peak = np.maximum.accumulate(np.r_[1, eq])[1:]
    dd = float((1 - eq / peak).max())
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    ret = float(eq[-1] - 1)
    return dict(n=len(r), ret=ret, dd=dd, win=float((r > 0).mean()),
                pf=float(gp / gl) if gl > 0 else 99, expR=float(r.mean()),
                hold=float((tr[:, 1] - tr[:, 0] + 1).mean()),
                score=ret / max(dd, 0.02) if len(r) >= 30 else -9)
