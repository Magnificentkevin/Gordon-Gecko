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

"""tp_model.py — dynamic take-profit + trailing profit lock for the Equity AM desk (Kevin rule Fri 2026-10-09 10:51 ET, from Mon 2026-10-12).
NEVER calls the broker. Reads saved MCP outputs and config.tpModel / config.catalystScore.

  target  : python3 tp_model.py target --symbol S --fill F --bars <5m extended bars json> [--bars ...] [--daily <daily bars json>] \
                   --catalyst-score 0.0-1.0 [--catalyst-type fda_accelerated_approval] [--now 2026-10-12T09:41] [--out file]
  trail   : python3 tp_model.py trail --fill F --hw H --atr A [--resting R] [--bid B --target T]

Formulas (also in config.tpModel):
  stop   = fill × (1 + tpModel.stopPct/100) ROUND UP (from 2026-11-11 the HARD stop trigger −4.5%, limit fill × 0.95; −2% = recovery decision point, recovery.py)   floor = fill × 1.02 (reward:risk ≥ 1:1)
  ATR    = Wilder ATR(14) on today's real 5m bars (extended bounds)
  k      = atrMultBase + atrMultPerScore × catalystScore      (default 1.0 + 2.0 × score → 1.0–3.0 ATR)
  T_atr  = fill + k × ATR
  levels = premarket high, prior-day high, today's HOD so far, the next 2 round numbers above floor,
           fib extensions 1.272 / 1.618 of the opening leg (RTH low before HOD → HOD, only if leg ≥ 4%)
  R1     = lowest level > floor
  score < strongCatalystMin (0.7):  target = max(floor, min(T_atr, R1 − 1 tick))   (take profit just under the first wall)
  score ≥ 0.7:                      target = max(floor, T_atr, (lowest level ≥ T_atr) − 1 tick)  (strong news may run through walls)
  NO upper cap. Rounded UP to the next cent (≥ $1) or 0.0001 (< $1).
  Trailing profit lock (once bid ≥ floor): trailStop = max(fill × 1.005, hw − 1.0 × ATR), never lowered, rounded DOWN to tick.
"""
import os as _os, time as _time  # TZ_PIN 2026-10-15: box clock may read UTC
_os.environ["TZ"]="America/New_York"; _time.tzset()
import argparse, json, math, sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CONFIG = "/workspace/robinhood-fable-agent/config/equity-morning-session.json"
DEF = {"stopPct": -2.0, "floorPct": 2.0, "atrPeriod": 14, "atrMultBase": 1.0, "atrMultPerScore": 2.0, "strongCatalystMin": 0.7,
       "fibExtensions": [1.272, 1.618], "minOpeningLegPct": 4.0, "trailAtrMult": 1.0, "trailBreakevenPlusPct": 0.5,
       "trailActivatePct": 2.0, "trailReplaceMinStepPct": 0.25, "tpSwitchWithinPct": 0.5, "tpSwitchBackBelowPct": 1.0}

def cfg():
    try:
        c = json.load(open(CONFIG)).get("tpModel", {})
    except Exception:
        c = {}
    p = dict(DEF); p.update({k: v for k, v in (c.get("params") or {}).items() if k in DEF}); return p

def tick(px): return 0.01 if px >= 1 else 0.0001
def up(px):
    t = tick(px); return round(math.ceil(px / t - 1e-9) * t, 4)
def down(px):
    t = tick(px); return round(math.floor(px / t + 1e-9) * t, 4)
def pt(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))

def _jload(path):
    """FIX 2026-10-17 (weekend mechanics): MCP write_to_file outputs may be wrapped in untrusted-data tag text
    (same root cause as ta.py's 2026-10-16 fix); strip to the JSON body instead of crashing to the +2% floor fallback."""
    txt = open(path).read()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        i = min([x for x in (txt.find("{"), txt.find("[")) if x >= 0], default=-1)
        j = max(txt.rfind("}"), txt.rfind("]"))
        if i < 0 or j <= i:
            raise
        return json.loads(txt[i:j + 1])

def load(paths, sym):
    bars = []
    for p in paths or []:
        d = _jload(p); d = d.get("data", d) if isinstance(d, dict) else d
        rows = d.get("results", []) if isinstance(d, dict) else []
        for r in rows:
            if r.get("symbol", "").upper() == sym:
                bars += [b for b in (r.get("bars") or []) if not b.get("interpolated")]
    seen = {}; [seen.setdefault(b["begins_at"], b) for b in bars]
    return sorted(seen.values(), key=lambda b: b["begins_at"])

def atr(bars, n):
    if len(bars) < n + 1: return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = float(bars[i]["high_price"]), float(bars[i]["low_price"]), float(bars[i - 1]["close_price"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for x in trs[n:]: a = (a * (n - 1) + x) / n
    return a

def rounds(px, floor):
    step = 0.05 if px < 1 else 0.25 if px < 5 else 0.5 if px < 10 else 1.0 if px < 50 else 5.0
    first = math.floor(floor / step + 1) * step
    return [round(first, 4), round(first + step, 4)]

def target(a):
    p = cfg(); sym = a.symbol.upper(); E = a.fill
    now = datetime.fromisoformat(a.now).replace(tzinfo=ET) if a.now else datetime.now(ET)
    day = now.date()
    bars = [b for b in load(a.bars, sym) if pt(b["begins_at"]).astimezone(ET).date() == day and pt(b["begins_at"]) < now.astimezone(timezone.utc)]
    why, lv = [], {}
    stop = up(E * (1 + p["stopPct"] / 100))  # ROUND UP to tick so realized risk never exceeds −2%
    floor = E * (1 + p["floorPct"] / 100)
    A = atr(bars, p["atrPeriod"])
    score = max(0.0, min(1.0, a.catalyst_score))
    k = p["atrMultBase"] + p["atrMultPerScore"] * score
    pm = [b for b in bars if pt(b["begins_at"]).astimezone(ET).strftime("%H:%M") < "09:30"]
    rth = [b for b in bars if pt(b["begins_at"]).astimezone(ET).strftime("%H:%M") >= "09:30"]
    if pm: lv["premarketHigh"] = max(float(b["high_price"]) for b in pm)
    if rth:
        hi_i = max(range(len(rth)), key=lambda i: float(rth[i]["high_price"]))
        H = float(rth[hi_i]["high_price"]); L = min(float(b["low_price"]) for b in rth[:hi_i + 1])
        lv["hodSoFar"] = H
        if L > 0 and (H / L - 1) * 100 >= p["minOpeningLegPct"]:
            for f in p["fibExtensions"]: lv[f"fibExt{f}"] = L + f * (H - L)
            why.append(f"opening leg {L:.4f}->{H:.4f} ({(H/L-1)*100:.1f}%)")
        else:
            why.append("opening leg < %.0f%%: no fib extensions" % p["minOpeningLegPct"])
    if a.daily:
        db = [b for b in load(a.daily, sym) if pt(b["begins_at"]).date() < day]
        if db: lv["priorDayHigh"] = float(db[-1]["high_price"])
    else:
        why.append("no daily file: priorDayHigh unknown")
    for i, r in enumerate(rounds(E, floor)): lv[f"round{i+1}"] = r
    above = {k2: v for k2, v in lv.items() if v > floor}
    T_atr = E + k * A if A else None
    t = tick(E)
    if T_atr is None:
        why.append("ATR unavailable (<15 real 5m bars): ATR leg skipped")
    R1 = min(above.items(), key=lambda kv: kv[1]) if above else None
    if score < p["strongCatalystMin"]:
        cands = [x for x in [T_atr, (R1[1] - t) if R1 else None] if x is not None]
        raw = min(cands) if cands else floor
        rule = "normal catalyst: min(T_atr, first wall − 1 tick)"
    else:
        beyond = sorted(v for v in above.values() if T_atr is not None and v >= T_atr)
        raw = max(T_atr, beyond[0] - t) if beyond else (T_atr if T_atr is not None else (max(above.values()) - t if above else floor))
        rule = "strong catalyst: max(T_atr, first level at/after T_atr − 1 tick)"
    tgt = up(max(floor, raw))
    floored = tgt <= up(floor)
    out = {"symbol": sym, "fill": E, "stop": stop, "floorTP": up(floor), "targetTP": tgt, "targetPct": round((tgt / E - 1) * 100, 2),
           "rewardRisk": round((tgt - E) / (E - stop), 2), "atr14_5m": round(A, 5) if A else None, "atrMult": round(k, 2),
           "T_atr": round(T_atr, 4) if T_atr else None, "catalystScore": score, "catalystType": a.catalyst_type,
           "levels": {k2: round(v, 4) for k2, v in lv.items()}, "firstWall": {"name": R1[0], "px": round(R1[1], 4)} if R1 else None,
           "rule": rule, "flooredAt2pct": floored, "notes": why, "at": now.isoformat(timespec="seconds"), "barsUsed": len(bars),
           "trailPlan": {"activateAtBid": up(E * (1 + p["trailActivatePct"] / 100)), "trailStopFormula": f"max({E}*{1+p['trailBreakevenPlusPct']/100:.3f}, hw - {p['trailAtrMult']}*ATR)",
                         "tpSwitchAtBid": down(tgt * (1 - p["tpSwitchWithinPct"] / 100)), "switchBackBelowBid": down(tgt * (1 - p["tpSwitchBackBelowPct"] / 100))}}
    out["reasoning"] = (f"{sym} fill {E}: ATR14(5m)={out['atr14_5m']}, k={out['atrMult']} (catalystScore {score}) -> T_atr={out['T_atr']}; "
                        f"first wall {out['firstWall']}; {rule} -> targetTP {tgt} (+{out['targetPct']}%, R:R {out['rewardRisk']})" + ("; floored at +2%" if floored else ""))
    s = json.dumps(out, indent=1)
    if a.out: open(a.out, "w").write(s)
    print(s)

def trail(a):
    p = cfg(); E = a.fill
    raw = max(E * (1 + p["trailBreakevenPlusPct"] / 100), a.hw - p["trailAtrMult"] * a.atr)
    ts = down(raw)
    if a.resting is not None: ts = max(ts, a.resting)
    replace = a.resting is None or ts >= a.resting + max(tick(E), E * p["trailReplaceMinStepPct"] / 100)
    o = {"trailStop": ts, "stopLimitLimit": down(ts * 0.97), "replaceResting": bool(replace), "activateAtBid": up(E * (1 + p["trailActivatePct"] / 100))}
    if a.bid is not None and a.target is not None:
        o["mode"] = "tp_limit" if a.bid >= a.target * (1 - p["tpSwitchWithinPct"] / 100) else "trailing_stop_limit"
        o["switchBackToTrailIfBidBelow"] = down(a.target * (1 - p["tpSwitchBackBelowPct"] / 100))
    print(json.dumps(o, indent=1))

ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
t = sp.add_parser("target"); t.add_argument("--symbol", required=True); t.add_argument("--fill", type=float, required=True)
t.add_argument("--bars", action="append", required=True); t.add_argument("--daily", action="append")
t.add_argument("--catalyst-score", type=float, default=0.0); t.add_argument("--catalyst-type"); t.add_argument("--now"); t.add_argument("--out")
r = sp.add_parser("trail"); r.add_argument("--fill", type=float, required=True); r.add_argument("--hw", type=float, required=True)
r.add_argument("--atr", type=float, required=True); r.add_argument("--resting", type=float); r.add_argument("--bid", type=float); r.add_argument("--target", type=float)
a = ap.parse_args(); target(a) if a.cmd == "target" else trail(a)
