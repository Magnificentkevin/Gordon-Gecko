"""Monte Carlo of Gordongecko's evaluation and risk rules (R-multiples; 1R = loss to the -5% stop)."""
import numpy as np, json
rng=np.random.default_rng(3); N=20000
p=0.28                       # SILAS stated win rate band 26-31%
def trades(n, edge, cost=0.0, sims=N, p=p):
    L=1+0.15*np.sqrt(2/np.pi)  # mean loss incl. stop slippage
    b=((1-p)*L+edge+cost)/p   # payoff giving this net expectancy after cost
    w=rng.random((sims,n))<p
    r=np.where(w, b*rng.uniform(0.6,1.4,(sims,n)), -1-np.abs(rng.normal(0,0.15,(sims,n))))  # winners vary, stops slip
    return r - cost
out={}
# 1) promotion rule: 100 live trades with expectancy > 0
for e in (-0.10, 0.0, 0.10, 0.20):
    r=trades(100,e); m=r.mean(1); se=r.std(1)/10
    out[f"promo_edge_{e:+.2f}"]=dict(pass_naive=float((m>0).mean()), pass_t2=float((m/se>2).mean()))
# 2) 30-trade tuning noise: spread of observed win rate when true p=28%
w=(rng.random((N,30))<p).mean(1); out["winrate_30_p5_p95"]=[float(np.percentile(w,5)),float(np.percentile(w,95))]
w=(rng.random((N,100))<p).mean(1); out["winrate_100_p5_p95"]=[float(np.percentile(w,5)),float(np.percentile(w,95))]
# 3) bank stop / tripwire at zero edge
def dd_hit(risk, n, edge=0.0, cost=0.0, halve=True):
    r=trades(n,edge,cost); eq=np.ones(N); trip=np.zeros(N,bool); stop=np.zeros(N,bool)
    for k in range(n):
        size=np.where(trip&halve,risk/2,risk)
        eq=np.where(stop,eq,eq*(1+size*r[:,k])); trip|=eq<=0.90; stop|=eq<=0.80
    return float(trip.mean()), float(stop.mean())
out["bank_1pct_250trades_zero_edge"]=dd_hit(0.01,250)
out["bank_1pct_250trades_cost0.2R"]=dd_hit(0.01,250,0.0,0.2)
out["lightning_fullcash_5pct_risk_40trades"]=dd_hit(0.05,40)     # full cash at -5% stop = 5% of equity per trade
out["lightning_fullcash_40trades_cost0.3R"]=dd_hit(0.05,40,0.0,0.3)
# 4) costs: break-even payoff at 28% win rate
for c in (0.0,0.1,0.2,0.3): out[f"breakeven_payoff_cost{c}R"]=round((1-p+c)/p,2)
print(json.dumps(out,indent=1)); json.dump(out,open("out/stats_mc.json","w"),indent=1)
