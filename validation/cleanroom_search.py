"""Step 1: generate & rank strategies on IN-SAMPLE data only (first 60%)."""
import json, sys, time
import numpy as np
from cleanroom_engine import load, atr, configs, signals, simulate, stats

d = load(sys.argv[1])
N = len(d)
IS_END, WF_END = int(N * 0.6), int(N * 0.8)
A = atr(d).values
cache, rows, t0 = {}, [], time.time()
for cfg in configs():
    key = (cfg["fam"], tuple(cfg["p"].items()), cfg["side"])
    if key not in cache:
        cache[key] = signals(d, cfg)
    tr = simulate(d, cache[key], cfg["sl"], cfg["tp"], cfg["tmax"], A, hi=IS_END)
    st = stats(tr)
    rows.append({**cfg, **st})
rows.sort(key=lambda r: r["score"], reverse=True)
print(f"{len(rows)} configs in {time.time()-t0:.0f}s; bars={N} IS_END={IS_END} ({d.index[IS_END]}) WF_END={WF_END} ({d.index[WF_END]})")
print(f"profitable in-sample: {sum(r['ret']>0 for r in rows)} / {len(rows)}")
for r in rows[:10]:
    print(r["fam"], r["p"], r["side"], f"sl{r['sl']} tp{r['tp']} t{r['tmax']}",
          f"n={r['n']} ret={r['ret']:.1%} dd={r['dd']:.1%} win={r['win']:.0%} pf={r['pf']:.2f} hold={r['hold']:.1f}h")
json.dump(dict(N=N, IS_END=IS_END, WF_END=WF_END, rows=rows), open("out/search.json", "w"), default=str)
