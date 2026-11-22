"""Steps 2-5: walk-forward, holdout, Monte Carlo, random-entry baseline."""
import json, sys
import numpy as np
from cleanroom_engine import load, atr, configs, signals, simulate, stats, COST

d = load(sys.argv[1]); N = len(d); A = atr(d).values
S = json.load(open("out/search.json"))
IS_END, WF_END = S["IS_END"], S["WF_END"]
rng = np.random.default_rng(7)
CFGS = list(configs())
SIGC = {}
def sig(cfg):
    k = (cfg["fam"], tuple(sorted(cfg["p"].items())), cfg["side"])
    if k not in SIGC: SIGC[k] = signals(d, cfg)
    return SIGC[k]
def run(cfg, lo, hi, cost=COST):
    return simulate(d, sig(cfg), cfg["sl"], cfg["tp"], cfg["tmax"], A, cost=cost, lo=lo, hi=hi)
def best(lo, hi):
    sc = [(stats(run(c, lo, hi))["score"], i) for i, c in enumerate(CFGS)]
    return CFGS[max(sc)[1]]
def bh(lo, hi): return float(d.close.iloc[hi] / d.close.iloc[lo] - 1)
def yrs(lo, hi): return (d.index[hi] - d.index[lo]).days / 365.25
def label(c): return f"{c['fam']} {c['p']} {c['side']} SL{c['sl']}xATR TP{c['tp']}xATR max{c['tmax']}h"

R = {}
champ = {k: S["rows"][0][k] for k in ("fam", "p", "sl", "tp", "tmax", "side")}
R["champion"] = label(champ)
periods = {"in_sample": (0, IS_END), "validation": (IS_END, WF_END), "holdout": (WF_END, N - 1)}
R["periods"] = {}
for name, (lo, hi) in periods.items():
    st = stats(run(champ, lo, hi))
    st["ann"] = (1 + st["ret"]) ** (1 / yrs(lo, hi)) - 1
    R["periods"][name] = dict(st, start=str(d.index[lo].date()), end=str(d.index[hi].date()), buyhold=bh(lo, hi))

# ---- walk-forward: re-optimize on all prior data, trade next 10% blind ----
wf, wf_tr = [], []
for a, b in [(0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0)]:
    lo, hi = int(N * a), min(int(N * b), N - 1)
    c = best(0, lo)
    tr = run(c, lo, hi); st = stats(tr); wf_tr.append(tr)
    wf.append(dict(test=f"{d.index[lo].date()}→{d.index[hi].date()}", picked=label(c),
                   n=st["n"], ret=st["ret"], dd=st["dd"], win=st["win"], pf=st["pf"], buyhold=bh(lo, hi),
                   holdout=(a == 0.8)))
R["walkforward"] = wf
allwf = np.vstack(wf_tr); R["wf_stitched"] = stats(allwf)
R["wf_stitched"]["ann"] = (1 + R["wf_stitched"]["ret"]) ** (1 / yrs(int(N * .4), N - 1)) - 1

# ---- does in-sample rank predict out-of-sample? (overfitting check) ----
is_sc = np.array([stats(run(c, 0, IS_END))["ret"] for c in CFGS])
oos = np.array([stats(run(c, IS_END, N - 1))["ret"] for c in CFGS])
from scipy.stats import spearmanr
top = np.argsort(-is_sc)[:100]
R["overfit"] = dict(rank_corr=float(spearmanr(is_sc, oos)[0]),
                    top100_oos_profitable=float((oos[top] > 0).mean()),
                    all_oos_profitable=float((oos > 0).mean()),
                    top100_oos_median=float(np.median(oos[top])))

# ---- Monte Carlo on champion trades before holdout ----
tr = run(champ, 0, WF_END); r = tr[:, 2]
dds, rets = [], []
for _ in range(3000):
    x = rng.choice(r, len(r), replace=True)
    eq = np.cumprod(1 + 0.01 * x); pk = np.maximum.accumulate(np.r_[1, eq])[1:]
    dds.append((1 - eq / pk).max()); rets.append(eq[-1] - 1)
R["montecarlo"] = dict(dd_median=float(np.median(dds)), dd_95=float(np.percentile(dds, 95)),
                      ret_5=float(np.percentile(rets, 5)), ret_median=float(np.median(rets)),
                      p_loss=float((np.array(rets) < 0).mean()))
R["cost_stress"] = {f"{m}x": stats(run(champ, WF_END, N - 1, cost=COST * m))["ret"] for m in (0, 1, 2, 4)}
# parameter jitter: neighbours of champion
jit = []
for c in CFGS:
    if c["fam"] == champ["fam"] and c["side"] == champ["side"]:
        jit.append(stats(run(c, WF_END, N - 1))["ret"])
R["param_neighbours_holdout"] = dict(n=len(jit), profitable=float((np.array(jit) > 0).mean()),
                                     median=float(np.median(jit)))

# ---- random-entry baseline: same exits, same trade count, random bars ----
def rand_runs(lo, hi, side, n_trades, k=400):
    out = []
    for _ in range(k):
        s = np.zeros(N, int)
        idx = rng.choice(np.arange(lo + 1, hi - 1), size=min(n_trades * 3, hi - lo - 3), replace=False)
        s[idx] = 1 if side == "long" else rng.choice([-1, 1], len(idx))
        out.append(stats(simulate(d, s, champ["sl"], champ["tp"], champ["tmax"], A, lo=lo, hi=hi))["ret"])
    return np.array(out)
R["random"] = {}
for name, (lo, hi) in periods.items():
    n = R["periods"][name]["n"]; cr = R["periods"][name]["ret"]
    rl = rand_runs(lo, hi, "long", n)
    R["random"][name] = dict(rand_long_median=float(np.median(rl)), rand_long_p95=float(np.percentile(rl, 95)),
                             champion_pctile=float((rl < cr).mean()))
# equity curves for chart
def curve(lo, hi, cfg):
    t = run(cfg, lo, hi); eq = np.cumprod(1 + 0.01 * t[:, 2]) if len(t) else np.array([1.0])
    return [[str(d.index[int(i)].date()), float(v)] for i, v in zip(t[:, 1], eq)]
R["curve_champion"] = curve(0, N - 1, champ)
R["curve_wf"] = [[str(d.index[int(i)].date()), float(v)] for i, v in zip(allwf[:, 1], np.cumprod(1 + 0.01 * allwf[:, 2]))]
R["gold"] = [[str(t.date()), float(v)] for t, v in d.close.iloc[::24].items()]
R["splits"] = dict(is_end=str(d.index[IS_END].date()), wf_end=str(d.index[WF_END].date()))
json.dump(R, open("out/results.json", "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in R.items() if not k.startswith(("curve", "gold"))}, indent=1, default=float))
