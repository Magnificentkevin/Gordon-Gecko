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

"""Equity AM desk local TA + hard-filter helper (v2, 2026-10-08 evening).

Used by the live procedure files under /workspace/equity-am-desk/live/.
Reads thresholds from the desk config so daily-revise config edits flow through.

USAGE
  # 1) Score candidates (entries / recycle / jump-scan). Inputs are the RAW saved outputs of
  #    get_equity_historicals (interval=5minute, bounds=extended, start 04:00 ET today, <=10 symbols per call)
  #    and get_equity_quotes. Multiple --bars files allowed.
  python3 /workspace/paper/ta.py analyze --bars BARS.json [--bars BARS2.json] --quotes QUOTES.json \
      --daily-cache /workspace/robinhood-fable-agent/data/equity-paper/daily_vol_cache_YYYY-MM-DD.json \
      [--mode entry|recycle] [--now 2026-10-09T09:41] [--out OUT.json]
  # 2) Merge raw daily bars (get_equity_historicals interval=day, ~25 calendar days, regular) into the cache:
  python3 /workspace/paper/ta.py cache --raw DAILY.json --cache /workspace/robinhood-fable-agent/data/equity-paper/daily_vol_cache_YYYY-MM-DD.json

RULES IMPLEMENTED (match config.entryFilters):
  coverage  : >= minBarCoveragePctForTa (80%) of the last 36 5m slots (or since 04:00 ET if fewer) must be real
              (non-interpolated) bars, and >= 31 real bars today (StochRSI(14) warm-up), else taIncomplete.
  RVOL      : RTH volume today / (median of last 15 daily volumes * elapsed RTH fraction). Scanner column ignored.
  avg5m     : mean volume of the last 3 complete RTH 5m bars (flag avg5mBasis if fewer than 3 exist yet).
              Whole-share lane: >= minAvgSharesPer5MinBar (150k). Fractional lane (ask > available cash; --cash or
              config bankUsd): mean volume x close of the same bars >= fractionalLane.liquidity.minAvgDollarPer5MinBar.
  bidToStop : stop = ask*0.98; pass only if bid > stop*(1+skipRecycleIfBidWithinStopPct/100)  (1.0% -> bid > ask*0.9898).
  TA (5)    : volumeShape, stochRsi, vwap, bollinger, fibonacci. Required 4 from config entryFilters.ta.strictFromEt (09:35) onward (was 3 before 10:00 through 2026-11-05).
              HARD VETO: last > upper BB AND StochRSI K >= 80 (chase) -> skip regardless of score.
              Fib passes only if retrace from impulse high >= 23.6% (and price still >= 61.8% level, resuming).
              fibPending (no >=4% impulse): vwap+volumeShape+stochRsi must all pass.
              recycle mode: K turned up from <=40 also passes stoch; break below 61.8% on rising volume = veto.
  The script NEVER calls the broker; catalysts/dilution are checked by the routine, not here.
"""
import os as _os, time as _time  # TZ_PIN 2026-10-15: box clock may read UTC
_os.environ["TZ"]="America/New_York"; _time.tzset()
import argparse, json, math, statistics as st, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CONFIG = "/workspace/robinhood-fable-agent/config/equity-morning-session.json"
INTERVAL_MIN = {"minute": 1, "1minute": 1, "5minute": 5, "10minute": 10, "15minute": 15}

# ---------------------------------------------------------------- parsing
def _jload(path):
    """FIX 2026-10-16: MCP write_to_file outputs may be wrapped in untrusted-data tag text; strip to the JSON body."""
    txt = open(path).read()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        i = min([x for x in (txt.find("{"), txt.find("[")) if x >= 0], default=-1)
        j = max(txt.rfind("}"), txt.rfind("]"))
        if i < 0 or j <= i:
            raise
        return json.loads(txt[i:j + 1])

def _pt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def load_bars(paths):
    out = {}
    for p in paths:
        d = _jload(p)
        if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
            d = d["data"]
        if isinstance(d, dict) and "results" in d:
            for x in d["results"]:
                out[x["symbol"].upper()] = {"interval": x.get("interval", "5minute"), "bounds": x.get("bounds"), "bars": x.get("bars") or []}
        elif isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list):
                    out[k.upper()] = {"interval": "5minute", "bounds": None, "bars": v}
    return out

def load_quotes(path):
    q = {}
    if not path:
        return q
    d = _jload(path)
    if isinstance(d, dict) and "data" in d:
        d = d["data"]
    rows = d.get("results", d) if isinstance(d, dict) else d
    if isinstance(rows, dict):
        rows = [dict(v, symbol=k) for k, v in rows.items()]
    for r in rows:
        qq = r.get("quote", r)
        sym = (qq.get("symbol") or r.get("symbol")).upper()
        f = lambda *ks: next((float(qq[k]) for k in ks if qq.get(k) not in (None, "", "0", 0)), None)
        prev = f("adjusted_previous_close", "previous_close", "prevClose")
        if prev is None and isinstance(r.get("close"), dict) and r["close"].get("price"):
            prev = float(r["close"]["price"])
        q[sym] = {"bid": f("bid_price", "bid"), "ask": f("ask_price", "ask"),
                  "last": f("last_trade_price", "last"), "prevClose": prev,
                  "bidTime": qq.get("venue_bid_time"), "lastTime": qq.get("venue_last_trade_time"),
                  "state": qq.get("state"), "source": "get_equity_quotes"}
    return q

def load_cache(path):
    if not path:
        return {}
    try:
        d = json.load(open(path))
    except FileNotFoundError:
        return {}
    out = {}
    for k, v in d.items():
        if k.startswith("_"):
            continue
        if isinstance(v, list):
            out[k.upper()] = {"vols": v, "closes": [], "dates": []}
        elif isinstance(v, dict):
            out[k.upper()] = v
    return out

# ---------------------------------------------------------------- indicators
def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    g = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    l = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(g[:n]) / n; al = sum(l[:n]) / n
    out[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + g[i - 1]) / n; al = (al * (n - 1) + l[i - 1]) / n
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

def stochrsi_k(closes, n=14, smooth=3):
    r = rsi(closes, n); raw = []
    for i in range(len(r)):
        w = [x for x in r[max(0, i - n + 1):i + 1] if x is not None]
        if r[i] is None or len(w) < n:
            raw.append(None); continue
        hi, lo = max(w), min(w)
        raw.append(50.0 if hi == lo else (r[i] - lo) / (hi - lo) * 100)
    k = []
    for i in range(len(raw)):
        w = raw[max(0, i - smooth + 1):i + 1]
        k.append(None if len(w) < smooth or any(x is None for x in w) else sum(w) / smooth)
    return k

def bucket5(bars, now):
    """Aggregate sub-5m bars into complete, clock-aligned 5m buckets (volume summed, OHLC merged)."""
    out = {}
    for b in bars:
        t = b["_t"]; key = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
        o = out.setdefault(key, {"_t": key, "begins_at": key.isoformat(), "open_price": b["open_price"], "close_price": b["close_price"],
                                 "high_price": b["high_price"], "low_price": b["low_price"], "volume": 0, "session": b.get("session", "reg")})
        o["close_price"] = b["close_price"]
        o["high_price"] = str(max(float(o["high_price"]), float(b["high_price"])))
        o["low_price"] = str(min(float(o["low_price"]), float(b["low_price"])))
        o["volume"] += b.get("volume") or 0
    return [out[k] for k in sorted(out) if k + timedelta(minutes=5) <= now]

# ---------------------------------------------------------------- core
def effective_entry_filters(cfg, now):
    """Top-level entryFilters are the normal-day rules (owner rules from 2026-10-22: price >= $2, move 8-25%).
    A dated discretion.todayOverride.entryFiltersToday overlays them ONLY on its date (2026-10-21 stop-only test)."""
    ef = dict(cfg.get("entryFilters", {}))
    ov = (cfg.get("discretion") or {}).get("todayOverride") or {}
    if ov.get("date") == now.astimezone(ET).date().isoformat() and isinstance(ov.get("entryFiltersToday"), dict):
        ef.update({k: v for k, v in ov["entryFiltersToday"].items() if k != "note"})
    return ef

def analyze_symbol(sym, series, quote, cache, now, cfg, mode):
    ef = effective_entry_filters(cfg, now); ta_cfg = ef.get("ta", {})
    res = {"symbol": sym, "mode": mode}
    reasons = []
    step = INTERVAL_MIN.get(series.get("interval") or "5minute", 5)
    res["interval"] = series.get("interval"); res["bounds"] = series.get("bounds")
    today = now.astimezone(ET).date()
    bars = []
    for b in series["bars"]:
        t = _pt(b["begins_at"])
        if t.astimezone(ET).date() != today:
            continue
        if t + timedelta(minutes=step) > now:   # drop in-progress bar
            continue
        bars.append(dict(b, _t=t))
    bars.sort(key=lambda b: b["_t"])
    real = [b for b in bars if not b.get("interpolated")]
    rth = [b for b in bars if b.get("session", "reg") == "reg"]
    rth_real = [b for b in rth if not b.get("interpolated")]

    # ---- coverage
    day_start = datetime.combine(today, datetime.min.time(), ET).replace(hour=4 if (series.get("bounds") or "extended") != "regular" else 9, minute=0 if (series.get("bounds") or "extended") != "regular" else 30)
    last_slot_end = now.replace(second=0, microsecond=0)
    last_slot_end -= timedelta(minutes=last_slot_end.minute % step)
    slots_since_start = max(0, int((last_slot_end - day_start.astimezone(timezone.utc)).total_seconds() // (step * 60)))
    W = min(36, slots_since_start)
    win_start = last_slot_end - timedelta(minutes=step * W)
    in_win = sum(1 for b in real if win_start <= b["_t"] < last_slot_end)
    cov = (in_win / W * 100) if W else 0.0
    res["coverage"] = {"pct": round(cov, 1), "realBarsInWindow": in_win, "windowSlots": W, "realBarsToday": len(real), "rthBars": len(rth)}
    min_cov = ta_cfg.get("dataSources", {}).get("minBarCoveragePctForTa", 80.0)

    # ---- quote / price
    q = quote or {}
    px = q.get("last") or (float(real[-1]["close_price"]) if real else None)
    bid, ask = q.get("bid"), q.get("ask")
    if not quote:
        res["quoteSource"] = "bar_close_replay (no quote file: bid/ask unknown)"
    prev = q.get("prevClose")
    c_cache = cache.get(sym, {})
    if prev is None and c_cache.get("closes"):
        prev = c_cache["closes"][-1]
    res["last"] = px; res["bid"] = bid; res["ask"] = ask; res["prevClose"] = prev

    # ---- hard filters
    hard = {}
    dayPct = (px / prev - 1) * 100 if (px and prev) else None
    res["dayPct"] = round(dayPct, 2) if dayPct is not None else None
    dmin = ef.get("minPctChangeAtEntry", 8.0)
    dmax = ef.get("maxPctChangeAtRecycle", 40.0) if mode == "recycle" else ef.get("maxPctChangeAtEntry", 60.0)
    hard["dayPct"] = None if dayPct is None else (dmin <= dayPct <= dmax)
    hard["lastMin"] = None if px is None else px >= ef.get("minLastPriceAtEntry", 0.10)
    pb = ef.get("preferPctChangeBand") or {}
    res["movePreferred"] = None if (dayPct is None or not pb) else (pb.get("min", 8.0) <= dayPct <= pb.get("max", 15.0))
    res["filtersApplied"] = {"minLast": ef.get("minLastPriceAtEntry"), "dayPct": [dmin, dmax]}
    if bid and ask:
        spread = (ask - bid) / ((ask + bid) / 2) * 100
        res["spreadPct"] = round(spread, 2)
        cap = ef.get("tightSpreadMaxPct", 3.0) if (px or ask) < ef.get("tightSpreadIfLastBelow", 0.25) else ef.get("skipIfBidAskSpreadPct", 8.0)
        hard["spread"] = spread <= cap
        pct = ef.get("skipRecycleIfBidWithinStopPct", 1.0)
        stop = ask * (1 + ef.get("bidToStopPct", cfg.get("stopLossPct", -2.0)) / 100)   # 2026-11-17: spread-equivalent gate stays at −2% (entryFilters.bidToStopPct) while the soft stop is −3.45%
        # ROUND UP to the cent (≥$1) / 0.0001 (<$1) so the −2% risk gate matches the resting stop
        t = 0.01 if (ask or 0) >= 1 else 0.0001
        stop = round(math.ceil(stop / t - 1e-9) * t, 4)
        need = stop * (1 + pct / 100)
        hard["bidToStop"] = bid > need
        res["bidToStopDetail"] = {"anchor": "ask", "stop": round(stop, 4), "bidMustExceed": round(need, 4), "bid": bid, "gapPct": round((bid - stop) / stop * 100, 2)}
        notional = cfg.get("notionalPerNameUsd")
        hard["wholeShare"] = None if notional is None else ask <= notional
        res["qtyAtAsk"] = int(math.floor(notional / ask)) if notional else None
        # SIZING lock (Kevin 2026-10-09, from config.sizingRule.effectiveFrom): whole vs fractional is decided at buy time
        # (1+ whole share when ask <= available cash; above it only fractional-eligible names), so wholeShare is informational.
        eff = (cfg.get("sizingRule") or {}).get("effectiveFrom")
        if cfg.get("_forceSizingLock") or (eff and now.astimezone(ET).date().isoformat() >= eff):
            res["wholeShareInfo"] = {"askLeNotional": hard.pop("wholeShare"), "note": "sizing decided at buy time (SIZING lock)"}
    else:
        hard["spread"] = hard["bidToStop"] = hard["wholeShare"] = None
    vols15 = [v for v in (c_cache.get("vols") or [])][-15:]
    baseline = st.median(vols15) if len(vols15) >= 5 else None
    rth_min = len(rth) * step
    frac = min(rth_min / 390.0, 1.0) if rth_min else 0
    rth_vol = sum(b.get("volume") or 0 for b in rth)
    rvol = rth_vol / (baseline * frac) if (baseline and frac) else None
    res["rvol"] = round(rvol, 2) if rvol is not None else None
    res["rvolBasis"] = {"method": "median15_tod", "baselineMedian": baseline, "nDays": len(vols15), "rthVol": rth_vol, "elapsedFrac": round(frac, 4)}
    hard["rvol"] = None if rvol is None else rvol >= ef.get("minRelativeVolume", 1.5)
    rth5 = rth if step >= 5 else bucket5(rth, now)
    last3 = rth5[-3:]
    avg3 = sum(b.get("volume") or 0 for b in last3) / len(last3) if last3 else None
    res["avg5mLast3"] = round(avg3) if avg3 is not None else None
    if len(last3) < 3:
        res["avg5mBasis"] = f"only {len(last3)} complete RTH 5m bars"
    # LIQUIDITY: whole-share lane = shares floor (150k/5m). Fractional lane (ask > available cash, Kevin 2026-10-09 11:44 ET)
    # = dollar-volume floor on the same last-3 complete RTH 5m bars (volume x close), from config.fractionalLane.liquidity.
    fl = (cfg.get("fractionalLane") or {}).get("liquidity") or {}
    cash = cfg.get("_availableCash") if cfg.get("_availableCash") is not None else cfg.get("bankUsd")
    px_lane = ask or px
    frac_lane = bool(fl.get("enabled") and cash is not None and px_lane is not None and px_lane > cash)
    res["lane"] = "fractional" if frac_lane else "whole_share"
    dv3 = sum((b.get("volume") or 0) * float(b["close_price"]) for b in last3) / len(last3) if last3 else None
    res["avg5mDollarLast3"] = round(dv3) if dv3 is not None else None
    # TIME-OF-DAY LIQUIDITY FLOOR (all-day session, Kevin 2026-11-10 08:13 ET): config entryFilters.minAvgSharesPer5MinBarByTime
    # [{fromEt,toEt,shares,dollars}] overrides the flat 150k / $1.5M floors inside its band (never below the band's own value).
    sh_floor = ef.get("minAvgSharesPer5MinBar", 150000); dol_floor = fl.get("minAvgDollarPer5MinBar", 1500000)
    _hm = now.astimezone(ET).strftime("%H:%M")
    for _b in ef.get("minAvgSharesPer5MinBarByTime") or []:
        if _b.get("fromEt", "00:00") <= _hm < _b.get("toEt", "24:00"):
            sh_floor = _b.get("shares", sh_floor); dol_floor = _b.get("dollars", dol_floor); break
    if cfg.get("_premarketPaper"):
        # PREMARKET PAPER SESSION (Kevin 2026-11-10 16:05 ET; paper only, never live): thin premarket tape → config premarketPaper.liquidity
        _pl = (cfg.get("premarketPaper") or {}).get("liquidity") or {}
        sh_floor = _pl.get("shares", 5000); dol_floor = _pl.get("dollars", 25000)
        if hard.get("rvol") is None: hard.pop("rvol", None)   # RVOL needs RTH minutes; informational premarket
    res["liqFloor"] = {"shares": sh_floor, "dollars": dol_floor, "at": _hm}
    if frac_lane:
        hard["liqDollar"] = None if dv3 is None else dv3 >= dol_floor
    else:
        hard["liq150k"] = None if avg3 is None else avg3 >= sh_floor
    res["hard"] = hard
    unknown = [k for k, v in hard.items() if v is None]
    failed = [k for k, v in hard.items() if v is False]
    res["hardPass"] = not failed and not unknown
    if failed: reasons.append("hard_fail:" + ",".join(failed))
    if unknown: reasons.append("hard_unknown:" + ",".join(unknown))

    # ---- time rules
    hhmm = now.astimezone(ET).strftime("%H:%M")
    no_new = cfg.get("_paperNoNewAfter") or cfg.get("manage", {}).get("noNewEntriesAfterEt", "10:50")
    window_start = cfg.get("_paperWindowStart") or "09:30"
    req = 3
    for r in ta_cfg.get("requiredPassCountByTime", []) or []:
        if r["fromEt"] <= hhmm < r["toEt"]:
            req = r["requiredPassCount"]
    # Afternoon / post-10:30 bar: require 4/5 (paper PM and live late window)
    strict_from = ta_cfg.get("strictFromEt", "09:35")   # config-driven (4/5 from 09:35 since Thu 2026-11-05 parent)
    if hhmm >= strict_from:
        req = max(req, int(ta_cfg.get("strictMinPassCount", 4)))   # 2026-11-13 higher-risk: config strictMinPassCount 3
    req = max(req, ta_cfg.get("requiredPassCount", 3))
    res["taRequired"] = req
    res["noNewBuys"] = hhmm >= no_new or hhmm < window_start
    if res["noNewBuys"]: reasons.append(f"time_gate:{hhmm} outside {window_start}-{no_new}")

    # ---- TA
    def incomplete(msg):
        res["taIncomplete"] = msg; res["taOk"] = False
        reasons.append("taIncomplete:" + msg)
        res["verdict"] = "SKIP"; res["reasons"] = reasons
        return res
    if W < 31 and len(real) < 31:
        return incomplete(f"only {W} slots since session start")
    if cov < min_cov:
        return incomplete(f"bar coverage {cov:.0f}% < {min_cov:.0f}%")
    if len(real) < 31:
        return incomplete(f"only {len(real)} real bars (<31 for StochRSI14)")
    c = [float(b["close_price"]) for b in real]; h = [float(b["high_price"]) for b in real]
    lo = [float(b["low_price"]) for b in real]; v = [b.get("volume") or 0 for b in real]
    if px is None: px = c[-1]
    if step < 5:   # volumeShape is defined on 5m bars: aggregate 1m series into complete 5m buckets
        b5 = bucket5(real, now)
        if len(b5) >= 4:
            v = [b.get("volume") or 0 for b in b5]
        else:
            return incomplete("fewer than 4 complete 5m buckets for volumeShape")
    prior3 = sum(v[-4:-1]) / 3
    lastGePrior = v[-1] >= v[-2]; collapse = v[-1] < 0.5 * prior3; risingVol = v[-1] >= prior3
    res["volumeShape"] = {"pass": lastGePrior and not collapse, "last": v[-1], "prior": v[-2], "prior3avg": round(prior3), "collapse": collapse, "barBasis": "5m" if step >= 5 else "5m_from_1m"}
    if step < 5:
        v = [b.get("volume") or 0 for b in real]; prior3_raw = sum(v[-4:-1]) / 3
    else:
        prior3_raw = prior3
    # VWAP: RTH-anchored once an RTH bar exists, else premarket-anchored
    vbars = [b for b in real if b.get("session", "reg") == "reg"] or real
    tp = [(float(b["high_price"]) + float(b["low_price"]) + float(b["close_price"])) / 3 for b in vbars]
    vv = [b.get("volume") or 0 for b in vbars]
    vw = sum(t * x for t, x in zip(tp, vv)) / max(sum(vv), 1)
    prevBelow = c[-2] < vw
    reclaim = prevBelow and px >= vw and risingVol
    fading = px < vw * 0.99 and v[-1] < v[-2]
    res["vwap"] = {"pass": px >= vw, "vwap": round(vw, 4), "basis": "rth" if vbars is not real else "premarket", "pctFromVwap": round((px / vw - 1) * 100, 2), "reclaim": reclaim, "fadingBelowOnFallingVol": fading}
    # StochRSI
    k = [x for x in stochrsi_k(c) if x is not None]
    if len(k) < 2:
        return incomplete("stochRSI insufficient bars")
    K, Kp = k[-1], k[-2]; rising = K > Kp
    higherLows = len(lo) >= 6 and min(lo[-3:]) > min(lo[-6:-3])
    ob_exc = K >= 80 and reclaim
    sr = ((Kp <= 30 and rising) or (30 <= K <= 70 and higherLows)) and K < 80
    if mode == "recycle" and Kp <= 40 and rising and K < 80:
        sr = True
    if ob_exc:
        sr = True
    res["stochRsi"] = {"pass": sr, "k": round(K, 1), "kPrev": round(Kp, 1), "rising": rising, "higherLows": higherLows, "overboughtVwapReclaimException": ob_exc}
    # Bollinger 20/2
    w = c[-20:]; mid = sum(w) / 20; sd = st.pstdev(w); up = mid + 2 * sd; dn = mid - 2 * sd
    nearMid = abs(px - mid) <= max((up - mid) * 0.5, 1e-9)
    lowerBounce = min(lo[-3:]) <= dn * 1.005 and rising and px > dn
    chase = px > up and K >= 80
    res["bollinger"] = {"pass": (not chase) and (nearMid or lowerBounce), "mid": round(mid, 4), "upper": round(up, 4), "lower": round(dn, 4), "bandwidthPct": round((up - dn) / mid * 100, 2) if mid else None, "nearMid": nearMid, "lowerBounce": lowerBounce, "chase": chase}
    # Fibonacci on today's impulse (low before high)
    iH = max(range(len(h)), key=lambda i: h[i]); iL = min(range(iH + 1), key=lambda i: lo[i])
    HI, LO = h[iH], lo[iL]
    fib_min = ta_cfg.get("fibonacci", {}).get("passRequiresRetracePctGe", 23.6)
    recycle_veto = False
    if HI <= LO or (HI / LO - 1) < 0.04:
        res["fibonacci"] = {"pass": None, "note": "fibPending: no clear >=4% impulse"}
    else:
        rng = HI - LO; f236 = HI - 0.236 * rng; f382 = HI - 0.382 * rng; f618 = HI - 0.618 * rng
        retr = (HI - px) / rng * 100
        resuming = c[-1] >= c[-2]
        brokeOnSell = px < f618 and v[-1] > prior3_raw and c[-1] < c[-2]
        fp = (retr >= fib_min) and px >= f618 and resuming and not brokeOnSell
        why = None if fp else ("near_high_trivial(<%.1f%% retrace)" % fib_min if retr < fib_min else ("below_61.8" if px < f618 else ("not_resuming" if not resuming else "broke_on_sell")))
        if mode == "recycle" and brokeOnSell:
            recycle_veto = True
        res["fibonacci"] = {"pass": fp, "failReason": why, "impulseLow": LO, "impulseHigh": HI, "retracePct": round(retr, 1), "f236": round(f236, 4), "f382": round(f382, 4), "f618": round(f618, 4), "inZone38_62": f618 <= px <= f382, "brokeBelow618OnRisingVol": brokeOnSell}
    checks = ["volumeShape", "stochRsi", "vwap", "bollinger", "fibonacci"]
    passes = sum(1 for x in checks if res[x].get("pass") is True)
    res["taPass"] = passes
    res["taOf"] = 5 if res["fibonacci"].get("pass") is not None else 4
    res["chaseHardVeto"] = chase
    res["recycleFibVeto"] = recycle_veto
    ok = passes >= req
    if res["fibonacci"].get("pass") is None:
        ok = ok and all(res[x]["pass"] for x in ("vwap", "volumeShape", "stochRsi"))
    if chase and (ta_cfg.get("chaseHardVeto") or {}).get("enabled", True) is not False:  # Kevin 2026-10-21 10:06: chase filter removable via config
        ok = False; reasons.append("chase_hard_veto(last>upperBB & K>=80)")
    if recycle_veto:
        ok = False; reasons.append("recycle_fib_veto(broke 61.8 on rising vol)")
    if passes < req:
        reasons.append(f"ta {passes}/{res['taOf']} < {req}")
    res["taOk"] = ok
    res["taSummary"] = {x: res[x].get("pass") for x in checks}
    res["verdict"] = "PASS" if (ok and res["hardPass"] and not res["noNewBuys"]) else "SKIP"
    res["reasons"] = reasons
    return res

# ---------------------------------------------------------------- CLI
def cmd_analyze(a):
    cfg = json.load(open(a.config))
    if getattr(a, "cash", None) is not None:
        cfg["_availableCash"] = a.cash
    if getattr(a, "no_new_after", None):
        cfg["_paperNoNewAfter"] = a.no_new_after
    if getattr(a, "window_start", None):
        cfg["_paperWindowStart"] = a.window_start
    if getattr(a, "premarket_paper", False):
        cfg["_premarketPaper"] = True; cfg["_paperWindowStart"] = cfg.get("_paperWindowStart") or ((cfg.get("premarketPaper") or {}).get("startEt") or "07:30")
        cfg["_paperNoNewAfter"] = cfg.get("_paperNoNewAfter") or ((cfg.get("premarketPaper") or {}).get("noNewBuysAfterEt") or "09:15")
    if getattr(a, "force_sizing_lock", False):
        cfg["_forceSizingLock"] = True
    now = datetime.now(timezone.utc) if not a.now else datetime.fromisoformat(a.now).replace(tzinfo=None).replace(tzinfo=ET).astimezone(timezone.utc)
    bars = load_bars(a.bars); quotes = load_quotes(a.quotes); cache = load_cache(a.daily_cache)
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else sorted(bars)
    out = {"generatedAt": datetime.now(ET).isoformat(timespec="seconds"), "nowEt": now.astimezone(ET).isoformat(timespec="seconds"),
           "mode": a.mode, "config": a.config, "results": {}}
    for s in syms:
        if s not in bars:
            out["results"][s] = {"symbol": s, "taIncomplete": "no bars returned", "taOk": False, "verdict": "SKIP", "reasons": ["taIncomplete:no bars returned"]}
            continue
        try:
            out["results"][s] = analyze_symbol(s, bars[s], quotes.get(s), cache, now, cfg, a.mode)
        except Exception as e:  # never crash the batch
            out["results"][s] = {"symbol": s, "taIncomplete": f"ta.py error: {e!r}", "taOk": False, "verdict": "SKIP", "reasons": [f"error:{e!r}"]}
    if a.out:
        json.dump(out, open(a.out, "w"), indent=1, default=str)
    for s, r in out["results"].items():
        print(f"{s:6} {r.get('verdict'):4} ta {r.get('taPass','-')}/{r.get('taOf','-')} req {r.get('taRequired','-')} "
              f"day% {r.get('dayPct')} rvol {r.get('rvol')} avg5m {r.get('avg5mLast3')} ${(r.get('avg5mDollarLast3') or 0)/1e6:.2f}M {r.get('lane','')[:4]} cov {r.get('coverage',{}).get('pct')} "
              f"| {'; '.join(r.get('reasons', [])) or 'ok'}")
    return 0

def cmd_cache(a):
    cache = {}
    try:
        cache = json.load(open(a.cache))
    except FileNotFoundError:
        pass
    raw = load_bars([a.raw])
    for s, ser in raw.items():
        bars = sorted([b for b in ser["bars"] if not b.get("interpolated")], key=lambda b: b["begins_at"])
        if a.exclude_date:
            bars = [b for b in bars if not b["begins_at"].startswith(a.exclude_date)]
        cache[s] = {"dates": [b["begins_at"][:10] for b in bars][-25:], "vols": [b.get("volume") or 0 for b in bars][-25:],
                    "closes": [float(b["close_price"]) for b in bars][-25:]}
    cache["_meta"] = {"updatedAt": datetime.now(ET).isoformat(timespec="seconds"), "note": "RTH daily volumes, oldest->newest, today excluded; RVOL baseline = median of last 15"}
    json.dump(cache, open(a.cache, "w"), indent=1)
    print(f"cache {a.cache}: {len([k for k in cache if not k.startswith('_')])} symbols")
    return 0

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    an = sp.add_parser("analyze")
    an.add_argument("--bars", action="append", required=True)
    an.add_argument("--quotes")
    an.add_argument("--daily-cache")
    an.add_argument("--mode", choices=["entry", "recycle"], default="entry")
    an.add_argument("--now", help="ET wall time for replay, e.g. 2026-10-08T09:35")
    an.add_argument("--symbols")
    an.add_argument("--config", default=CONFIG)
    an.add_argument("--out")
    an.add_argument("--cash", type=float, help="available cash (sets whole-share vs fractional lane; default config bankUsd)")
    an.add_argument("--no-new-after", help="override manage.noNewEntriesAfterEt (paper afternoon e.g. 15:35)")
    an.add_argument("--window-start", help="override session start for time_gate (default 09:30)")
    an.add_argument("--premarket-paper", action="store_true", help="PAPER premarket session 07:30–09:29 (config premarketPaper): premarket liquidity floor, RVOL informational, window 07:30–09:15")
    an.add_argument("--force-sizing-lock", action="store_true", help="treat SIZING lock / wholeShare-info as active now (Mon rules paper)")
    an.set_defaults(fn=cmd_analyze)
    ca = sp.add_parser("cache")
    ca.add_argument("--raw", required=True)
    ca.add_argument("--cache", required=True)
    ca.add_argument("--exclude-date", help="YYYY-MM-DD to drop (today's partial bar)")
    ca.set_defaults(fn=cmd_cache)
    a = p.parse_args(argv)
    return a.fn(a)

if __name__ == "__main__":
    sys.exit(main())
