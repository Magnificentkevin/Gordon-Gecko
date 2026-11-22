"""Download the data the validation lab needs into validation/data/ (Yahoo Finance via yfinance + the public breadth CSV).
Run from validation/:  pip install yfinance pandas scipy  &&  python3 fetch_data.py"""
import os, urllib.request
import yfinance as yf
os.makedirs("data", exist_ok=True); os.makedirs("out", exist_ok=True)
IDX = ["^GSPC", "^RUT", "^IXIC", "^N225", "^HSI", "000001.SS", "^KS11", "^NSEI", "^GDAXI", "^FTSE", "^STOXX50E", "GC=F", "CL=F", "DX-Y.NYB", "^VIX"]
ETF = ["SPY", "IWM", "QQQ", "GLD", "EWJ", "EWG", "EWU", "FXI", "INDA", "EWY", "EWZ", "EEM"]
yf.download(IDX, start="2025-10-01", interval="1d", progress=False, auto_adjust=True, group_by="ticker").to_pickle("data/daily_idx.pkl")
yf.download(ETF, period="730d", interval="1h", progress=False, auto_adjust=True, group_by="ticker").to_pickle("data/hourly_etf.pkl")
yf.download("GC=F", period="730d", interval="1h", progress=False, auto_adjust=False).to_csv("data/GC_F_1h.csv")
urllib.request.urlretrieve("https://tradermonty.github.io/market-breadth-analysis/market_breadth_data.csv", "data/breadth.csv")
print("data ready")
