#!/usr/bin/env python3
"""candle_flow.py - classify recent 1-minute candles as big-buyer vs retail flow.

Robinhood's connector gives OHLCV bars, not trade-by-trade prints, so this is a
candle-based PROXY for who is moving the stock:

  big_buy     volume >= 3x the recent median, green, closes in the top 30% of
              its range, body >= 50% of range (large buyer lifting offers)
  absorption  volume >= 3x median but range <= 0.6x the average range and
              closes in the upper half (large buyer soaking up sellers)
  retail_chase green bar with range >= 2x average on volume < 2x median, or an
              upper wick >= 50% of the range (thin, emotional buying that fades)
  big_sell    volume >= 2x median, red, body >= 60% of range, or volume >= 3x
              median closing in the bottom 30% (distribution)
  churn       volume >= 3x median, body <= 20% of range, near the high of day
              (heavy two-way trading at the top: often a top)

Usage:
  candle_flow.py --bars <get_equity_historicals 1-minute raw json> [--symbol X]
                 [--lookback 20] [--recent 5] [--hod H] [--json]

Output per symbol: last-N labels, flow score (big_buy+absorption minus
big_sell+churn), retail share, and a verdict for the desk:
  ENTER_OK   flow >= 1, last bar not retail_chase or big_sell
  HOLD_RUN   flow >= 0 and no big_sell/churn in the last 2 bars (let it run)
  EXIT       big_sell or churn in the last 2 bars, or flow <= -2

RSI(14) and MACD(12,26,9) on the same 1-minute closes (Kevin 2026-11-19 08:51):
  entry needs MACD histogram > 0 and rising, RSI 50-85;
  winners are held through RSI > 70 (let them run) and exit on a MACD bearish
  cross with RSI < 70, or RSI rolling over from > 80 while the histogram fades.
  MACD needs 35+ bars, so pass extended-hours 1-minute bars for warm-up.
"""
import argparse, json, statistics, sys


def load(path):
    d = json.load(open(path))
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        d = d["data"]
    out = {}
    if isinstance(d, dict) and "results" in d:
        for x in d["results"]:
            out[x["symbol"].upper()] = [b for b in (x.get("bars") or []) if not b.get("interpolated")]
    elif isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list):
                out[k.upper()] = v
    return out


def f(b, k):
    return float(b.get(k + "_price", b.get(k[0], 0)) or 0)


def classify(bars, lookback=20, hod=None):
    labels = []
    for i, b in enumerate(bars):
        o, h, l, c = f(b, "open"), f(b, "high"), f(b, "low"), f(b, "close")
        v = float(b.get("volume") or b.get("v") or 0)
        prior = bars[max(0, i - lookback):i]
        if len(prior) < 3:
            labels.append({"t": b.get("begins_at"), "label": "warmup"}); continue
        medv = statistics.median(float(p.get("volume") or 0) for p in prior) or 1.0
        avgr = statistics.mean(f(p, "high") - f(p, "low") for p in prior) or 1e-9
        rng = max(h - l, 1e-9)
        rv = v / medv
        body = abs(c - o) / rng
        clv = (c - l) / rng
        upw = (h - max(o, c)) / rng
        dayhi = hod if hod else max(f(p, "high") for p in bars[:i + 1])
        near_hod = h >= dayhi * 0.995
        green = c > o
        if rv >= 3 and body <= 0.2 and near_hod:
            lab = "churn"
        elif (rv >= 2 and not green and body >= 0.6) or (rv >= 3 and clv <= 0.3):
            lab = "big_sell"
        elif rv >= 3 and green and clv >= 0.7 and body >= 0.5:
            lab = "big_buy"
        elif rv >= 3 and rng <= 0.6 * avgr and clv >= 0.5:
            lab = "absorption"
        elif green and ((rng >= 2 * avgr and rv < 2) or upw >= 0.5):
            lab = "retail_chase"
        else:
            lab = "neutral"
        labels.append({"t": b.get("begins_at"), "label": lab, "rvol": round(rv, 2), "body": round(body, 2),
                       "clv": round(clv, 2), "rangeVsAvg": round(rng / avgr, 2), "close": c})
    return labels


def ema(xs, n):
    k = 2 / (n + 1); out = []; e = None
    for x in xs:
        e = x if e is None else x * k + e * (1 - k); out.append(e)
    return out


def rsi(closes, n=14):
    if len(closes) <= n:
        return None
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[:n]) / n; al = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def indicators(bars):
    c = [f(b, "close") for b in bars]
    r_now, r_prev = rsi(c), rsi(c[:-1])
    out = {"rsi": round(r_now, 1) if r_now is not None else None,
           "rsiRising": (r_now is not None and r_prev is not None and r_now > r_prev)}
    if len(c) >= 35:
        macd = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
        sig = ema(macd, 9); hist = [m - s for m, s in zip(macd, sig)]
        out.update(macd=round(macd[-1], 5), signal=round(sig[-1], 5), hist=round(hist[-1], 5),
                   histRising=hist[-1] > hist[-2], bullCross=hist[-2] <= 0 < hist[-1], bearCross=hist[-2] >= 0 > hist[-1])
    else:
        out["macd"] = None  # needs 35+ bars: include extended-hours 1-minute bars for warm-up
    return out


def verdict(labels, recent=5, ind=None):
    last = [x for x in labels if x["label"] != "warmup"][-recent:]
    if not last:
        return {"verdict": "NO_DATA"}
    n = lambda *ks: sum(1 for x in last if x["label"] in ks)
    flow = n("big_buy", "absorption") - n("big_sell", "churn")
    retail = round(n("retail_chase") / len(last), 2)
    last2 = [x["label"] for x in last[-2:]]
    if "big_sell" in last2 or "churn" in last2 or flow <= -2:
        v = "EXIT"
    elif flow >= 1 and last[-1]["label"] not in ("retail_chase", "big_sell"):
        v = "ENTER_OK"
    elif flow >= 0:
        v = "HOLD_RUN"
    else:
        v = "WEAK"
    ind = ind or {}
    notes = []
    r, m = ind.get("rsi"), ind.get("macd")
    if m is not None:
        bull = ind["hist"] > 0
        if v == "ENTER_OK" and not (bull and ind["histRising"]):
            v = "HOLD_RUN" if bull else "WEAK"; notes.append("MACD not confirming entry")
        if v in ("HOLD_RUN", "ENTER_OK") and ind.get("bearCross") and r is not None and r < 70:
            v = "EXIT"; notes.append("MACD bearish cross")
    else:
        notes.append("MACD warming up (<35 bars)")
    if r is not None:
        if v == "ENTER_OK" and (r < 50 or r > 85):
            v = "HOLD_RUN"; notes.append("RSI %.0f outside 50-85 entry band" % r)
        if v == "HOLD_RUN" and r > 80 and not ind.get("rsiRising") and m is not None and not ind.get("histRising"):
            v = "EXIT"; notes.append("RSI rolling over above 80 with MACD fading")
    return {"verdict": v, "notes": notes, "indicators": ind, "flow": flow, "retailShare": retail, "recent": [x["label"] for x in last]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--symbol")
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--recent", type=int, default=5)
    ap.add_argument("--hod", type=float)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    data = load(a.bars)
    res = {}
    for s, bars in data.items():
        if a.symbol and s != a.symbol.upper():
            continue
        bars = sorted(bars, key=lambda b: b.get("begins_at", ""))
        labs = classify(bars, a.lookback, a.hod)
        res[s] = dict(verdict(labs, a.recent, indicators(bars)), lastBars=labs[-a.recent:])
    print(json.dumps(res, indent=None if a.json else 1))


if __name__ == "__main__":
    sys.exit(main())
