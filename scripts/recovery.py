#!/usr/bin/env python3
# This copy ships with the silas-equity-desk Claude skill.
# Sanitized: no hardcoded account ids or secrets. Set BROKER_ACCOUNT_NUMBER.
# Broker layer is a broker MCP (e.g. Robinhood). Times are America/New_York.


def _broker_account(*, required=False):
    """Live account id from the environment — never hardcode it."""
    import os, sys
    v = (os.environ.get("BROKER_ACCOUNT_NUMBER") or "").strip()
    if required and not v:
        sys.stderr.write("Set BROKER_ACCOUNT_NUMBER to the live account id (never hardcode it).\n")
        sys.exit(2)
    return v
ACCOUNT = _broker_account(required=False)

"""−2% RECOVERY DECISION + POST-EXIT TRACKING + DECISION SUCCESS RATE (Kevin 2026-11-10 16:28 / 16:30 / 16:31 ET).

16:28 "Auto review charts and sell at 2% if likelihood of recovery is less than 50%. Otherwise allow to go to a 5% loss then stop automatically."
  - The resting broker stop_limit is the HARD STOP: trigger entry × 0.955, limit entry × 0.95 (never worse than −5% when it fills);
    risk_floors.py trade-cap market-sells anything at/below −5% (gap through / unfilled stop-limit).
  - DECISION POINT −3.45% from 2026-11-17 (was −3% from 2026-11-13, originally −2%; higher-risk+15, Kevin 09:27 ET “Widen your risk tolerance by 15% confirm”; only Kevin moves it): on every fire while bid ≤ entry × 0.9655 →
      python3 recovery.py score --symbol S --entry E --price BID --bars5 <5m raw> [--bars1 <1m raw>] [--spy5 <SPY 5m raw>]
                                [--sector5 <sector ETF 5m raw>] [--catalyst intact|unknown|broken] [--now] [--log]
    → {score 0-100, threshold, decision exit|hold, components{...}}; exit code 10 = EXIT NOW (cancel stop → verify → market sell).
    Re-run every fire while below −3.45%; the first score under the threshold exits.
  SCORE = 100 × Σ wᵢ·cᵢ / Σ wᵢ, each component cᵢ ∈ [0,1] (0.5 = neutral / data missing):
    vwap      price vs session VWAP:            0.5 + 25 × (price/VWAP − 1)            (+2% above → 1, −2% below → 0)
    trend1m   slope of last 10 1-min closes:    0.5 + slope%/bar ÷ 0.2  (fallback last 4 5-min closes ÷ 0.4)
    trend5m   EMA9 vs EMA20 of 5-min closes:    0.5 + 50 × (EMA9/EMA20 − 1)
    dipVolume red-bar ÷ green-bar volume, last 6 5-min (or 15 1-min) bars: 1 at ≤ 0.8, 0 at ≥ 1.5 (selling volume dominating = 0)
    support   nearest support below (opening-range low, session low before the dip, round number): holding within 1.5% → 1,
              price under the opening-range low and every support → 0, otherwise 0.4
    rsi       RSI14 (1-min, fallback 5-min): <30 rising 1.0 · <30 falling 0.4 · 30–50 rising 0.7 · 30–50 falling 0.3 · ≥50 0.6
    market    SPY (and sector ETF if given) % change over the last 30 min: 0.5 + chg% ÷ 0.6
    catalyst  intact 1 · unknown 0.5 · broken (negative news / dilution / halt) 0
  Weights + threshold live in config recoveryModel (desk_learn tunes them within bounds; the −2% point and −5% stop are fixed).

16:30 "Test that percentage and adjust ... based on the bounce after −5% outs. If chart ends up recovering eventually make corrections."
  post-exit --symbol S --entry E --exit-price X --exit-at T --bars5 <rest-of-session 5m raw> [--target TP] [--kind score_exit|hard_stop|stall_exit|profit_exit|hold] [--log]
    → recoveredToEntry / recoveredToTarget / maxRecoveryPct / label correct|wrong, appended to the journal.
  backtest --bars-dir <dir of <date>.json full-day 5m bars> [--history]   (historical trades, −2% touch → score → hold vs sell)
"""
import argparse, glob, json, math, os, sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CFG = os.environ.get("RECONCILE_CONFIG") or "/workspace/robinhood-fable-agent/config/equity-morning-session.json"
JOURNAL = os.environ.get("RECOVERY_JOURNAL") or "/workspace/robinhood-fable-agent/data/equity-paper/recovery-decisions.jsonl"
DECISION_PCT = -3.45; HARD_TRIGGER_PCT = -4.5; HARD_LIMIT_PCT = -5.0    # fixed (Kevin); never read from config. 2026-11-17 09:29 ET higher-risk+15 (Kevin 09:27 "Widen your risk tolerance by 15% confirm"): −3% → −3.45%
DEFAULT_W = {"vwap": 0.20, "trend1m": 0.10, "trend5m": 0.15, "dipVolume": 0.15, "support": 0.15, "rsi": 0.05, "market": 0.10, "catalyst": 0.10}
def jload(p, d=None):
    try: return json.load(open(p))
    except Exception: return d
def num(x, d=0.0):
    try: return float(x)
    except Exception: return d
def clamp(x): return max(0.0, min(1.0, x))
def pt(s): return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
def model(C=None, hhmm=None):
    """weights, threshold. Early-session dips (decision before earlyThreshold.beforeEt, default 10:00) use thresholdPct + offset
    (default −15, floor 30): backtest 2026-11-10 — touches < 10:00 (n20) did best at 30–40 (hold), ≥ 10:00 (n25) best at 55–60."""
    C = C if C is not None else (jload(CFG, {}) or {}); m = C.get("recoveryModel") or {}
    w = dict(DEFAULT_W); w.update(m.get("weights") or {}); T = num(m.get("thresholdPct"), 50.0)
    et = m.get("earlyThreshold") or {}
    if hhmm and et.get("enabled", True) and hhmm < et.get("beforeEt", "10:00"):
        T = max(num((m.get("thresholdBounds") or {}).get("min"), 30.0), T + num(et.get("offset"), -15.0))
    return w, T
def bars_of(raw, sym=None):
    d = jload(raw, {}) if isinstance(raw, str) else (raw or {})
    d = d.get("data", d) if isinstance(d, dict) else d
    res = d.get("results") if isinstance(d, dict) else d
    if isinstance(res, list):
        for r in res:
            if sym is None or str(r.get("symbol", "")).upper() == sym.upper(): return [b for b in (r.get("bars") or []) if not b.get("interpolated")]
    if isinstance(d, list): return d
    return []
def rth(bars): return [b for b in bars if "09:30" <= pt(b["begins_at"]).astimezone(ET).strftime("%H:%M") < "16:00"]
def ema(xs, n):
    if not xs: return None
    k = 2 / (n + 1); e = xs[0]
    for x in xs[1:]: e = x * k + e * (1 - k)
    return e
def rsi(cl, n=14):
    if len(cl) < n + 2: return None, None
    def r(c):
        g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]; l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
        ag = sum(g[:n]) / n; al = sum(l[:n]) / n
        for i in range(n, len(g)): ag = (ag * (n - 1) + g[i]) / n; al = (al * (n - 1) + l[i]) / n
        return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return r(cl), r(cl[:-1])
def slope_pct(cl):
    n = len(cl)
    if n < 3: return None
    xm = (n - 1) / 2; ym = sum(cl) / n
    s = sum((i - xm) * (c - ym) for i, c in enumerate(cl)) / sum((i - xm) ** 2 for i in range(n))
    return s / ym * 100
def round_below(px):
    step = 0.05 if px < 1 else 0.25 if px < 5 else 0.5 if px < 10 else 1.0 if px < 50 else 5.0
    return math.floor(px / step) * step

def score(bars5, entry, price, bars1=None, spy5=None, sector5=None, catalyst="unknown", weights=None, threshold=50.0):
    w = dict(weights or DEFAULT_W); c, why, miss = {}, {}, []
    b5 = rth(bars5 or []); b1 = rth(bars1 or [])
    # vwap
    tv = sum(num(b["volume"]) for b in b5)
    if tv > 0:
        vw = sum((num(b["high_price"]) + num(b["low_price"]) + num(b["close_price"])) / 3 * num(b["volume"]) for b in b5) / tv
        c["vwap"] = clamp(0.5 + 25 * (price / vw - 1)); why["vwap"] = f"price {price} vs VWAP {vw:.4f}"
    else: c["vwap"] = 0.5; miss.append("vwap")
    # trend 1m (fallback 5m)
    s1 = slope_pct([num(b["close_price"]) for b in b1[-10:]]) if len(b1) >= 5 else None
    if s1 is not None: c["trend1m"] = clamp(0.5 + s1 / 0.2); why["trend1m"] = f"1m slope {s1:.3f}%/bar"
    else:
        s5 = slope_pct([num(b["close_price"]) for b in b5[-4:]]) if len(b5) >= 3 else None
        if s5 is not None: c["trend1m"] = clamp(0.5 + s5 / 0.4); why["trend1m"] = f"5m slope {s5:.3f}%/bar (no 1m bars)"
        else: c["trend1m"] = 0.5; miss.append("trend1m")
    # trend 5m
    cl5 = [num(b["close_price"]) for b in b5]
    if len(cl5) >= 6:
        e9, e20 = ema(cl5, 9), ema(cl5, 20); c["trend5m"] = clamp(0.5 + 50 * (e9 / e20 - 1)); why["trend5m"] = f"EMA9 {e9:.4f} / EMA20 {e20:.4f}"
    else: c["trend5m"] = 0.5; miss.append("trend5m")
    # dip volume
    rb = b1[-15:] if len(b1) >= 10 else b5[-6:]
    red = sum(num(b["volume"]) for b in rb if num(b["close_price"]) < num(b["open_price"])); grn = sum(num(b["volume"]) for b in rb if num(b["close_price"]) >= num(b["open_price"]))
    if red + grn > 0:
        r = red / grn if grn > 0 else 9.9; c["dipVolume"] = clamp((1.5 - r) / 0.7); why["dipVolume"] = f"red/green volume {r:.2f}"
    else: c["dipVolume"] = 0.5; miss.append("dipVolume")
    # support
    if len(b5) >= 3:
        orl = min(num(b["low_price"]) for b in b5[:3]); prior = min(num(b["low_price"]) for b in b5[:-3]) if len(b5) > 3 else orl
        sups = sorted({orl, prior, round_below(price)}, reverse=True); below = [s for s in sups if s <= price * 1.002]
        last_lows = [num(b["low_price"]) for b in b5[-3:]]
        if below and (price - below[0]) / price <= 0.015 and min(last_lows) >= below[0] * 0.998: c["support"] = 1.0; why["support"] = f"holding support {below[0]}"
        elif price < orl and not below: c["support"] = 0.0; why["support"] = f"under opening-range low {orl} and all supports"
        elif price < orl and min(last_lows) < min(sups) * 0.998: c["support"] = 0.0; why["support"] = f"broke opening-range low {orl}"
        else: c["support"] = 0.4; why["support"] = f"supports {sups}"
    else: c["support"] = 0.5; miss.append("support")
    # rsi
    cl = [num(b["close_price"]) for b in (b1 if len(b1) >= 16 else b5)]
    r0, rp = rsi(cl)
    if r0 is None: c["rsi"] = 0.5; miss.append("rsi")
    else:
        up = r0 > rp; c["rsi"] = (1.0 if up else 0.4) if r0 < 30 else ((0.7 if up else 0.3) if r0 < 50 else 0.6); why["rsi"] = f"RSI14 {r0:.1f} ({'rising' if up else 'falling'})"
    # market / sector
    ms = []
    for nm, raw in (("SPY", spy5), ("sector", sector5)):
        bb = rth(raw or [])
        if len(bb) >= 7: ms.append((num(bb[-1]["close_price"]) / num(bb[-7]["close_price"]) - 1) * 100); why.setdefault("market", ""); why["market"] += f"{nm} {ms[-1]:+.2f}% 30m "
    if ms: c["market"] = clamp(0.5 + (sum(ms) / len(ms)) / 0.6)
    else: c["market"] = 0.5; miss.append("market")
    c["catalyst"] = {"intact": 1.0, "unknown": 0.5, "broken": 0.0}.get(catalyst, 0.5); why["catalyst"] = catalyst
    sw = sum(w.get(k, 0) for k in c) or 1
    sc = round(100 * sum(w.get(k, 0) * v for k, v in c.items()) / sw, 1)
    return {"score": sc, "threshold": threshold, "decision": "exit" if sc < threshold else "hold", "components": {k: round(v, 3) for k, v in c.items()},
            "why": why, "missing": miss, "weights": w, "lossPct": round((price / entry - 1) * 100, 3) if entry else None,
            "decisionPointPct": DECISION_PCT, "hardStop": {"triggerPct": HARD_TRIGGER_PCT, "limitPct": HARD_LIMIT_PCT}}

def journal(row, path=None):
    p = path or JOURNAL; os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as fh: fh.write(json.dumps(row) + "\n")
def read_journal(path=None):
    out = []
    try:
        for ln in open(path or JOURNAL):
            ln = ln.strip()
            if ln:
                try: out.append(json.loads(ln))
                except Exception: pass
    except FileNotFoundError: pass
    return out

def post_exit(entry, exit_price, exit_at, bars_after, target=None, kind="score_exit"):
    """Track the rest of the session after an exit (or after a hold decision): did it recover to entry / target, how far."""
    t0 = pt(exit_at); bb = [b for b in rth(bars_after or []) if pt(b["begins_at"]) >= t0.astimezone(timezone.utc).replace(second=0)]
    if not bb: return {"tracked": False, "why": "no bars after exit"}
    hi = max(num(b["high_price"]) for b in bb); lo = min(num(b["low_price"]) for b in bb); last = num(bb[-1]["close_price"])
    rec_e = hi >= entry; rec_t = bool(target) and hi >= target
    hit_hard = lo <= entry * (1 + HARD_TRIGGER_PCT / 100)
    if kind == "hold":   # hold at −2% was correct if it did not end at the −5% hard stop before getting back above −2%
        first_good = next((i for i, b in enumerate(bb) if num(b["high_price"]) >= entry * (1 + DECISION_PCT / 100) * 1.0001), None)
        first_bad = next((i for i, b in enumerate(bb) if num(b["low_price"]) <= entry * (1 + HARD_TRIGGER_PCT / 100)), None)
        good = first_good is not None and (first_bad is None or first_good < first_bad)
        label = "correct" if good else "wrong"
    elif kind == "profit_exit": label = "correct" if hi < exit_price * 1.02 else "wrong"       # left < 2% on the table
    elif kind == "stall_exit": label = "correct" if hi < max(entry, exit_price) * 1.02 else "wrong"
    else: label = "wrong" if rec_e else "correct"                                              # loss exits (score sell / hard stop)
    return {"tracked": True, "kind": kind, "bars": len(bb), "maxHighAfter": hi, "minLowAfter": lo, "lastClose": last,
            "recoveredToEntry": rec_e, "recoveredToTarget": rec_t, "hitHardStopAfter": hit_hard,
            "maxRecoveryPctFromExit": round((hi / exit_price - 1) * 100, 3), "maxPctVsEntry": round((hi / entry - 1) * 100, 3), "label": label}

# ---------------- historical backtest ----------------
def load_day(bdir, D):
    j = jload(f"{bdir}/{D}.json", {}) or {}; out = {}
    for r in (j.get("data", j).get("results") or []): out[str(r.get("symbol", "")).upper()] = [b for b in (r.get("bars") or []) if not b.get("interpolated")]
    return out
def kind_of(r):
    why = str(r.get("reason") or r.get("exitReason") or "").lower()
    if "stall" in why: return "stall_exit"
    return "profit_exit" if num(r.get("pnlUsd")) > 0 else "loss_exit"
def backtest(rows, bdir, weights=None, thresholds=range(30, 75, 5)):
    w = weights or DEFAULT_W; pts = []; postex = []
    for r in rows:
        D = r.get("_date") or str(r.get("entryAt"))[:10]; day = load_day(bdir, D); s = str(r.get("symbol")).upper(); bars = day.get(s)
        if not bars: continue
        e = num(r.get("entryPrice")); t_in = pt(r["entryAt"]); t_out = pt(r["exitAt"]) if r.get("exitAt") else None
        rb = rth(bars); spy = rth(day.get("SPY") or [])
        # post-exit tracking for every historical exit (decision-success baseline)
        if t_out:
            after = [b for b in rb if pt(b["begins_at"]) >= t_out.astimezone(timezone.utc)]
            k = kind_of(r); pe = post_exit(e, num(r.get("exitPrice")), r["exitAt"], after, num(r.get("targetTP")) or None, "loss_exit" if k == "loss_exit" else k)
            postex.append(dict(pe, symbol=s, date=D, kind=k, pnlPct=r.get("pnlPct")))
        # −2% touch after entry
        i0 = next((i for i, b in enumerate(rb) if pt(b["begins_at"]) >= t_in.astimezone(timezone.utc).replace(second=0, microsecond=0) - __import__("datetime").timedelta(minutes=4)), None)
        if i0 is None: continue
        touch = next((i for i in range(i0, len(rb)) if num(rb[i]["low_price"]) <= e * (1 + DECISION_PCT / 100) and pt(rb[i]["begins_at"]).astimezone(ET).strftime("%H:%M") < "15:45"), None)
        if touch is None: continue
        dp = e * (1 + DECISION_PCT / 100); tt = pt(rb[touch]["begins_at"])
        hist = rb[:touch] + [dict(rb[touch], close_price=str(dp), low_price=str(min(num(rb[touch]["low_price"]), dp)))]
        sp_hist = [b for b in spy if pt(b["begins_at"]) <= tt]
        sc = score(hist, e, dp, spy5=sp_hist, weights=w)
        # hold path: after the touch bar, −4.5% trigger → −5.0% (limit), back to −2% or better first → recovered; to entry → 0%
        res = None; rec_entry = False
        for b in rb[touch + 1:]:
            if pt(b["begins_at"]).astimezone(ET).strftime("%H:%M") >= "15:50": res = (num(b["open_price"]) / e - 1) * 100; break
            if num(b["low_price"]) <= e * (1 + HARD_TRIGGER_PCT / 100): res = HARD_LIMIT_PCT; break
            if num(b["high_price"]) >= e: res = 0.0; rec_entry = True; break
        if res is None: res = (num(rb[-1]["close_price"]) / e - 1) * 100
        # bounce after the −5% out (post-exit tracking of the hard stop)
        bounce = None
        if res == HARD_LIMIT_PCT:
            j = next(i for i in range(touch + 1, len(rb)) if num(rb[i]["low_price"]) <= e * (1 + HARD_TRIGGER_PCT / 100))
            rest = rb[j + 1:]
            bounce = {"recoveredToEntry": bool(rest) and max(num(b["high_price"]) for b in rest) >= e,
                      "maxPctVsEntry": round((max(num(b["high_price"]) for b in rest) / e - 1) * 100, 2) if rest else None}
        pts.append({"symbol": s, "date": D, "touchAt": tt.astimezone(ET).strftime("%H:%M"), "score": sc["score"], "components": sc["components"],
                    "sellPct": DECISION_PCT, "holdPct": round(res, 3), "holdBetter": res > DECISION_PCT, "recoveredToEntry": rec_entry, "bounceAfterHardStop": bounce,
                    "actualPnlPct": r.get("pnlPct")})
    grid = []
    for T in thresholds:
        tot = sum(p["holdPct"] if p["score"] >= T else p["sellPct"] for p in pts)
        acc = sum(1 for p in pts if (p["score"] >= T) == p["holdBetter"])
        grid.append({"threshold": T, "sumPct": round(tot, 2), "avgPct": round(tot / len(pts), 3) if pts else None, "accuracy": round(acc / len(pts), 3) if pts else None, "holds": sum(1 for p in pts if p["score"] >= T)})
    return {"n": len(pts), "points": pts, "grid": grid, "alwaysSellPct": round(DECISION_PCT * len(pts), 2), "alwaysHoldPct": round(sum(p["holdPct"] for p in pts), 2),
            "holdBetterCount": sum(1 for p in pts if p["holdBetter"]), "postExit": postex}

def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("score")
    for k in ("--symbol", "--bars5", "--bars1", "--spy5", "--sector5", "--now", "--position-id"): x.add_argument(k)
    x.add_argument("--entry", type=float, required=True); x.add_argument("--price", type=float, required=True); x.add_argument("--catalyst", default="unknown"); x.add_argument("--log", action="store_true")
    y = sp.add_parser("post-exit")
    for k in ("--symbol", "--exit-at", "--bars5", "--decision-id"): y.add_argument(k)
    y.add_argument("--entry", type=float, required=True); y.add_argument("--exit-price", type=float, required=True); y.add_argument("--target", type=float)
    y.add_argument("--kind", default="score_exit", choices=["score_exit", "hard_stop", "loss_exit", "stall_exit", "profit_exit", "hold"]); y.add_argument("--log", action="store_true")
    z = sp.add_parser("backtest"); z.add_argument("--bars-dir", default="/workspace/equity-am-desk/kb/backtest-bars"); z.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "score":
        _now = pt(a.now).astimezone(ET) if a.now else datetime.now(ET)
        w, T = model(hhmm=_now.strftime("%H:%M")); s = a.symbol.upper() if a.symbol else None
        r = score(bars_of(a.bars5, s), a.entry, a.price, bars_of(a.bars1, s) if a.bars1 else None, bars_of(a.spy5, "SPY") if a.spy5 else None,
                  bars_of(a.sector5) if a.sector5 else None, a.catalyst, w, T)
        if r["lossPct"] is not None and r["lossPct"] > DECISION_PCT + 1e-9: r.update(decision="hold", note="above the −3.45% decision point: no decision needed")
        now = a.now or datetime.now(ET).isoformat(timespec="seconds")
        r.update(symbol=s, entry=a.entry, price=a.price, at=now, id=f"{s}:{now}")
        if a.log: journal({"type": "decision", **{k: r[k] for k in ("id", "symbol", "entry", "price", "at", "score", "threshold", "decision", "components", "lossPct")}, "positionId": a.position_id})
        print(json.dumps(r)); return 10 if r["decision"] == "exit" else 0
    if a.cmd == "post-exit":
        r = post_exit(a.entry, a.exit_price, a.exit_at, bars_of(a.bars5, a.symbol), a.target, "loss_exit" if a.kind in ("score_exit", "hard_stop") else a.kind)
        r.update(kind=a.kind, symbol=(a.symbol or "").upper(), decisionId=a.decision_id, exitAt=a.exit_at, entry=a.entry, exitPrice=a.exit_price)
        if a.log and r.get("tracked"): journal({"type": "outcome", **r})
        print(json.dumps(r)); return 0
    if a.cmd == "backtest":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import desk_learn
        w, _ = model(); r = backtest(desk_learn.history(), a.bars_dir, w)
        if a.out: json.dump(r, open(a.out, "w"), indent=1)
        print(json.dumps({k: r[k] for k in ("n", "grid", "alwaysSellPct", "alwaysHoldPct", "holdBetterCount")})); return 0
if __name__ == "__main__": sys.exit(main())
