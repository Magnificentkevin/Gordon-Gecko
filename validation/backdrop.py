import pandas as pd, numpy as np, json
d=pd.read_pickle("data/daily_idx.pkl")
names={"^GSPC":"S&P 500","^RUT":"Russell 2000","^IXIC":"Nasdaq","^N225":"Nikkei 225","^HSI":"Hang Seng","000001.SS":"Shanghai","^KS11":"KOSPI","^NSEI":"Nifty 50","^GDAXI":"DAX","^FTSE":"FTSE 100","^STOXX50E":"Euro Stoxx 50","GC=F":"Gold","CL=F":"WTI Oil","DX-Y.NYB":"US Dollar Index","^VIX":"VIX"}
region={"^GSPC":"US","^RUT":"US","^IXIC":"US","^N225":"Asia","^HSI":"Asia","000001.SS":"Asia","^KS11":"Asia","^NSEI":"Asia","^GDAXI":"Europe","^FTSE":"Europe","^STOXX50E":"Europe","GC=F":"Macro","CL=F":"Macro","DX-Y.NYB":"Macro","^VIX":"Macro"}
S,E="2025-11-20","2026-11-20"
rows=[];monthly={}
for t,n in names.items():
    c=d[t]["Close"].dropna(); c=c[c.index>=pd.Timestamp(S)-pd.Timedelta(days=5)]
    c12=c[c.index>=S]; base=c[c.index<=pd.Timestamp(S)].iloc[-1] if (c.index<=pd.Timestamp(S)).any() else c12.iloc[0]
    r=c12/base; dd=(1-c12/c12.cummax()).max(); dr=c12.pct_change().dropna()
    m=c12.resample("ME").last(); mr=m.pct_change(); mr.iloc[0]=m.iloc[0]/base-1
    monthly[n]={k.strftime("%Y-%m"):round(v*100,1) for k,v in mr.items()}
    rows.append(dict(market=n,region=region[t],ret_12m_pct=round((r.iloc[-1]-1)*100,1),max_dd_pct=round(dd*100,1),
        worst_month_pct=round(mr.min()*100,1),best_month_pct=round(mr.max()*100,1),vol_ann_pct=round(dr.std()*np.sqrt(252)*100,1),
        peak_date=str(c12.idxmax().date()),last=round(float(c12.iloc[-1]),2)))
df=pd.DataFrame(rows); print(df.to_string())
mdf=pd.DataFrame(monthly); print(mdf.to_string())
json.dump(dict(rows=rows,monthly=monthly),open("out/backdrop_raw.json","w"))
# shock days: >=2 of 3 Asia/Europe majors down >1.5% on a day
ae=["^N225","^HSI","^GDAXI","^STOXX50E","^KS11"]
R=pd.DataFrame({t:d[t]["Close"].pct_change() for t in ae+["^GSPC","^RUT","^VIX"]}).loc[S:E]
shock=(R[ae]<-0.015).sum(axis=1)>=3
print("global shock days:",shock.sum()); print(R[shock].round(3).to_string())
