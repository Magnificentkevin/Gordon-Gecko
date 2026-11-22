import sys, csv, json, pandas as pd, numpy as np
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")); import gecko_regime as G
rows=list(csv.DictReader(open("data/breadth.csv")))
d=pd.read_pickle("data/daily_idx.pkl"); h=pd.read_pickle("data/hourly_etf.pkl")
S="2025-11-20"
lab={}
for i in range(len(rows)):
    dt=rows[i]["Date"][:10]
    if dt< "2025-11-01": continue
    lab[dt]=G.assess(rows[:i+1], today=pd.Timestamp(dt).date())["regime"]   # score as of that day (else stale -> UNKNOWN)
L=pd.Series(lab); L.index=pd.to_datetime(L.index)
rut=d["^RUT"]; spx=d["^GSPC"]
df=pd.DataFrame({"label":L}).join(pd.DataFrame({"rut_o":rut.Open,"rut_c":rut.Close,"spx_c":spx.Close}),how="inner")
df["prior_label"]=df.label.shift()          # what the desk sees at 09:35 (yesterday's close data)
df["rut_gap"]=df.rut_o/df.rut_c.shift()-1
df["rut_intraday"]=df.rut_c/df.rut_o-1      # SILAS lives open->close
df["rut_fwd5"]=df.rut_c.shift(-5)/df.rut_c-1
df=df.loc[S:]
print("days by label (prior day, what gates the open):"); print(df.prior_label.value_counts())
g=df.groupby("prior_label").agg(days=("rut_intraday","size"),intraday_mean=("rut_intraday","mean"),intraday_hit=("rut_intraday",lambda x:(x>0).mean()),
    gap_mean=("rut_gap","mean"),worst_day=("rut_intraday","min"))
print((g*[1,100,100,100,100]).round(2))
# label switches -> how many days lag behind S&P peaks/troughs
sw=df[df.label!=df.label.shift()][["label","spx_c"]]; print("switches:\n",sw)
# global shock days
ae=["^N225","^HSI","^GDAXI","^STOXX50E","^KS11"]
R=pd.DataFrame({t:d[t]["Close"].pct_change() for t in ae}).loc[S:]
shock=R.index[(R<-0.015).sum(axis=1)>=3]
sd=df.loc[df.index.intersection(shock),["prior_label","rut_gap","rut_intraday"]]
print("shock days: prior label, gap, intraday"); print(sd.round(4))
print("shock days allowed to buy (prior label not DEFENSIVE/UNKNOWN):",(~sd.prior_label.isin(["DEFENSIVE","UNKNOWN"])).sum(),"of",len(sd))
print("mean RUT intraday on shock days", sd.rut_intraday.mean(), "vs all", df.rut_intraday.mean())
df.to_csv("out/regime_daily.csv"); sd.to_csv("out/shock_days.csv")
