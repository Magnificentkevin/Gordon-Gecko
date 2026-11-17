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

"""desk_learn.py — DAY-TRADER KNOWLEDGE + SELF-LEARNING for the Equity desk (Kevin 2026-11-10 16:07 ET "Use results for your logic set.
Adjust and improve accordingly ... maximize potential for primary goal of 5% success" + 16:13 ET "Scrape daily reports and market news to
see emerging potential patterns and trades. You're operating as a day trader now. Adjust knowledge base accordingly."). Never calls the broker.

  patterns [--out-dir /workspace/equity-am-desk/kb]   every live round trip since the desk started (+ premarket paper results) →
        per-SETUP / time-slot / catalyst / price-band / hw evidence → kb/patterns.json + kb/day-trader-kb.md (the desk reads both).
  watchlist --date D [--news <research json>] [--movers <scan raw>]   emerging candidates for session D → kb/watchlist-<D>.json
        (ranked: fresh positive catalyst × winning setup evidence; dilution/offering names excluded). Scanner/TA ranking reads it as a
        PRIORITY input (watchlist names are scored first and win ties); it never bypasses a gate.
  learn [--apply] [--date D]   bounded self-tuning (config selfLearning.bounds, ≤ maxChangesPerDay, min trades) from the evidence;
        every change logged to config selfLearningLog[] + improvementsApplied[]. Hard floors are never touched.
SETUPS (tag positions with `setup` via reconcile.py annotate; history is inferred): gap_and_go (09:30–09:45 first entry), orb_breakout (break
of the 09:30–09:35 high, 09:35–10:30), vwap_reclaim (TA vwap reclaim), momentum_pullback (fib/BB pullback in trend), recycle_bounce
(re-entry of a symbol), midday_momentum (other ≥10:30), premarket_paper (paper only)."""
import glob, os as _os, time as _time
_os.environ["TZ"] = "America/New_York"; _time.tzset()
import argparse, glob, json, sys
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CONFIG = _os.environ.get("RECONCILE_CONFIG", "/workspace/robinhood-fable-agent/config/equity-morning-session.json")
DATA = _os.environ.get("DESK_DATA", "/workspace/robinhood-fable-agent/data/equity-paper")
KB = "/workspace/equity-am-desk/kb"
def f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d
def jload(p, d=None):
    try: return json.load(open(p))
    except Exception: return d
def jsave(p, o):
    _os.makedirs(_os.path.dirname(p), exist_ok=True); t = f"{p}.tmp.{_os.getpid()}"; json.dump(o, open(t, "w"), indent=1); _os.replace(t, p)

def history():
    rows, seen = [], set()
    files = sorted(glob.glob(f"{DATA}/morning-session-20*.json")) + [f"{DATA}/morning-session.json"]
    for fp in files:
        b = _os.path.basename(fp)
        if any(x in b for x in ("final", "pre", "archived", "bak")): continue
        s = jload(fp, {}) or {}
        for r in s.get("roundTrips") or []:
            k = r.get("rtKey") or (s.get("sessionDate"), r.get("symbol"), r.get("entryAt"))
            if k in seen: continue
            seen.add(k); r = dict(r); r["_date"] = s.get("sessionDate"); rows.append(r)
    rows.sort(key=lambda r: (r.get("entryAt") or r["_date"] or ""))
    first = {}
    for r in rows:
        key = (r["_date"], r.get("symbol")); r["_reentry"] = key in first; first.setdefault(key, r)
        r["_setup"] = r.get("setup") or infer_setup(r)
    return rows

def infer_setup(r):
    hm = (r.get("entryAt") or "")[11:16]
    if r.get("_reentry") or r.get("source") == "recycle" and hm >= "09:45": return "recycle_bounce"
    if "09:30" <= hm < "09:45": return "gap_and_go"
    if "09:45" <= hm < "10:30": return "orb_breakout"
    if hm: return "midday_momentum"
    return "unknown"

def bucket(rows, key):
    g = {}
    for r in rows:
        k = key(r)
        if k is None: continue
        g.setdefault(k, []).append(r)
    out = {}
    for k, v in g.items():
        p = [f(r.get("pnlPct")) for r in v]; u = [f(r.get("pnlUsd")) for r in v]
        out[str(k)] = {"n": len(v), "wins": sum(1 for x in u if x > 0), "winPct": round(100 * sum(1 for x in u if x > 0) / len(v), 1),
                       "avgPct": round(sum(p) / len(p), 3), "sumUsd": round(sum(u), 2), "avgR": round(sum(p) / len(p) / 2.0, 3)}
    return out

def slot(r):
    hm = (r.get("entryAt") or "")[11:16]
    for a, b in (("09:30", "09:45"), ("09:45", "10:00"), ("10:00", "10:30"), ("10:30", "11:30"), ("11:30", "14:00"), ("14:00", "15:45")):
        if a <= hm < b: return f"{a}-{b}"
    return None

def patterns(out_dir=KB, paper_dir=None):
    rows = history()
    P = {"generatedAt": datetime.now(ET).isoformat(timespec="seconds"), "trades": len(rows),
         "wins": sum(1 for r in rows if f(r.get("pnlUsd")) > 0), "sumUsd": round(sum(f(r.get("pnlUsd")) for r in rows), 2),
         "bySetup": bucket(rows, lambda r: r["_setup"]), "bySlot": bucket(rows, slot),
         "byExit": bucket(rows, lambda r: r.get("reason")),
         "byHighWater": bucket(rows, lambda r: None if r.get("hwPct") is None else ("<0.5%" if r["hwPct"] < 0.5 else "0.5-2%" if r["hwPct"] < 2 else ">=2%")),
         "byCatalyst": bucket(rows, lambda r: None if r.get("catalystScore") is None else ("<0.3" if r["catalystScore"] < 0.3 else "0.3-0.5" if r["catalystScore"] < 0.5 else ">=0.5")),
         "byPrice": bucket(rows, lambda r: None if not r.get("entryPrice") else ("<2" if r["entryPrice"] < 2 else "2-5" if r["entryPrice"] < 5 else "5-20" if r["entryPrice"] < 20 else ">=20")),
         "reentryAfterLoss": bucket([r for r in rows if r["_reentry"]], lambda r: "reentry"),
         "last10": [{"d": r["_date"], "sym": r.get("symbol"), "setup": r["_setup"], "pct": r.get("pnlPct"), "exit": r.get("reason")} for r in rows[-10:]]}
    pp = sorted(glob.glob(f"{paper_dir or DATA + '/premarket-paper'}/premarket-paper-*.json"))
    P["premarketPaper"] = [{"date": (jload(x, {}) or {}).get("date"), "ok": (jload(x, {}) or {}).get("ok"), "w": (jload(x, {}) or {}).get("paperWins"),
                            "l": (jload(x, {}) or {}).get("paperLosses"), "start": (jload(x, {}) or {}).get("paperStartUsd"), "end": (jload(x, {}) or {}).get("paperEndUsd")} for x in pp[-10:]]
    good = sorted([(k, v) for k, v in P["bySetup"].items() if v["n"] >= 3], key=lambda kv: -kv[1]["avgPct"])
    P["setupRanking"] = [k for k, _ in good]
    jsave(f"{out_dir}/patterns.json", P)
    L = ["# DAY-TRADER OPERATING KNOWLEDGE (auto-generated by desk_learn.py patterns; do not hand-edit numbers)",
         f"Generated {P['generatedAt']} from {P['trades']} live round trips (wins {P['wins']}, total ${P['sumUsd']}). Primary goal: +5% of start bank per day.",
         "", "## Setups (evidence per setup; rank = avg % per trade, n ≥ 3)"]
    for k, v in sorted(P["bySetup"].items(), key=lambda kv: -kv[1]["avgPct"]):
        L.append(f"- {k}: n {v['n']}, win {v['winPct']}%, avg {v['avgPct']}% ({v['avgR']} R), ${v['sumUsd']}")
    L += ["", "## Time slots (entry time ET)"] + [f"- {k}: n {v['n']}, win {v['winPct']}%, avg {v['avgPct']}%" for k, v in sorted(P["bySlot"].items())]
    L += ["", "## Exits"] + [f"- {k}: n {v['n']}, win {v['winPct']}%, avg {v['avgPct']}%" for k, v in sorted(P["byExit"].items(), key=lambda kv: -kv[1]["n"])]
    L += ["", "## High-water reached (how far the trade ever went in our favour)"] + [f"- {k}: n {v['n']}, win {v['winPct']}%, avg {v['avgPct']}%" for k, v in P["byHighWater"].items()]
    L += ["", "## Rules the evidence supports (desk applies them; learn.py retunes within bounds)",
          "- The opening drive (09:30–10:00) is where the edge is; later entries need A+ quality (TA 5/5 after 10:00).",
          "- A trade that has not shown +0.5% quickly almost never wins → stall exit (config stallExit.afterMinutes).",
          "- Winners that reach +2% tend to run (avg ≈ +6%) → TP floor high (tpModel.floorPct), trailing lock from +2% protects.",
          "- Never re-buy a symbol that already closed at a loss today (0 wins in the record).",
          "", "## Intraday setup playbook (what each tag means)",
          "- gap_and_go: gapper holding above premarket high/VWAP at the open on heavy volume; enter on the first 1–5 min higher low.",
          "- orb_breakout: break of the 09:30–09:35 (or 5-min) opening range high with volume, above VWAP.",
          "- vwap_reclaim: price reclaims session VWAP on rising volume after a flush; stop under VWAP / −2%.",
          "- momentum_pullback: strong trend, pullback to 23.6–61.8% fib or mid-BB with stoch turning up, then the next green bar.",
          "- recycle_bounce: re-entry of a symbol that closed GREEN today after a pullback (never after a red close).",
          "- midday_momentum: 10:30+ continuation; lowest-quality slot historically — only 5/5 TA with a catalyst.",
          "", "## Premarket paper sessions (07:30–09:29)"] + [f"- {x['date']}: checks ok={x['ok']}, paper W/L {x['w']}/{x['l']}, ${x['start']} → ${x['end']}" for x in P["premarketPaper"]] + [
          "", "## Last 10 trades"] + [f"- {x['d']} {x['sym']} {x['setup']} {x['pct']}% ({x['exit']})" for x in P["last10"]]
    open(f"{out_dir}/day-trader-kb.md", "w").write("\n".join(L) + "\n")
    return P

def watchlist(D, news=None, movers=None, out_dir=KB):
    """news = research JSON the routine saved: {"items":[{symbol, catalystType, headline, source, time, dilution:bool, sentiment}]}."""
    P = jload(f"{out_dir}/patterns.json") or patterns(out_dir)
    C = jload(CONFIG, {}) or {}; w = (C.get("catalystScore") or {}).get("weights") or {}
    items = ((jload(news, {}) or {}).get("items") if news else []) or []
    cand = {}
    for it in items:
        s = str(it.get("symbol") or "").upper()
        if not s: continue
        if it.get("dilution") or str(it.get("catalystType")) in ("offering", "reverse_split_30d"): continue
        sc = f(w.get(it.get("catalystType")), 0.3)
        if str(it.get("sentiment", "")).lower().startswith("neg"): sc -= 0.3
        r = cand.setdefault(s, {"symbol": s, "score": 0.0, "why": []}); r["score"] = max(r["score"], round(sc, 3)); r["why"].append(f"{it.get('catalystType')}: {str(it.get('headline'))[:120]} ({it.get('source')})")
    if movers:
        d = jload(movers, {}) or {}; d = d.get("data", d)
        for row in (d.get("results") or d.get("rows") or []) if isinstance(d, dict) else d:
            s = str(row.get("symbol") or row.get("Symbol") or "").upper()
            if s: r = cand.setdefault(s, {"symbol": s, "score": 0.2, "why": []}); r["why"].append("premarket mover")
    best = (P.get("setupRanking") or ["gap_and_go"])[:2]
    out = {"date": D, "generatedAt": datetime.now(ET).isoformat(timespec="seconds"), "prioritySetups": best,
           "candidates": sorted(cand.values(), key=lambda r: -r["score"])[:15],
           "use": "scan/refresh/manage discovery: score these names FIRST and rank them above equal-scoring non-watchlist names; every gate still applies"}
    jsave(f"{out_dir}/watchlist-{D}.json", out); return out

def setp(c, path, v):
    cur = c; ks = path.split(".")
    for k in ks[:-1]: cur = cur.setdefault(k, {})
    cur[ks[-1]] = v
def getp(c, path):
    cur = c
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur: return None
        cur = cur[k]
    return cur

MAX_TRADE_LOSS_PCT = 5.0
LOCKED_PARAMS = ("tpModel.stopPct", "recoveryModel.decisionPointPct", "recoveryModel.hardStop", "maxTradeLoss", "bankStop", "liveMode", "desk.paused", "premarketPaper", "discretion.killSwitch.enabled")
def learn(apply=False, D=None):
    C = jload(CONFIG, {}) or {}; SL = C.get("selfLearning") or {}
    if not SL.get("enabled"): return {"ok": True, "changes": [], "why": "selfLearning disabled"}
    B = SL.get("bounds") or {}; rows = history()[-int(SL.get("lookbackTrades", 40)):]; D = D or datetime.now(ET).date().isoformat()
    if len(rows) < int(SL.get("minTrades", 8)): return {"ok": True, "changes": [], "why": f"only {len(rows)} trades"}
    ch = []
    def prop(path, new, ev, bkey=None):
        b = B.get(bkey or path) or {}; old = getp(C, path)
        if old is None: return
        new = max(b.get("min", new), min(b.get("max", new), new))
        if abs(f(new) - f(old)) > 1e-9: ch.append({"param": path, "old": old, "new": new, "evidence": ev})
    # 1. TP floor: winners that reached +2% — avg exit % among them
    big = [r for r in rows if f(r.get("hwPct"), -1) >= 2]
    if len(big) >= 4:
        avg = sum(f(r.get("pnlPct")) for r in big) / len(big); cur = f((C.get("tpModel") or {}).get("floorPct"), 2)
        step = (B.get("tpModel.floorPct") or {}).get("step", 1.0)
        if avg > cur + 1.5: prop("tpModel.floorPct", cur + step, f"{len(big)} trades with hw ≥ 2% averaged {avg:.2f}% > floor {cur}% + 1.5")
        elif avg < cur - 0.5: prop("tpModel.floorPct", cur - step, f"{len(big)} trades with hw ≥ 2% averaged {avg:.2f}% < floor {cur}% − 0.5")
    # 2. stall timer: dead trades (hw < 0.5%) that ran longer than the timer
    dead = [r for r in rows if r.get("hwPct") is not None and r["hwPct"] < 0.5 and r.get("mins")]
    cur = f((C.get("stallExit") or {}).get("afterMinutes"), 20); stp = (B.get("stallExit.afterMinutes") or {}).get("step", 2)
    late = [r for r in dead if f(r["mins"]) > cur and f(r.get("pnlPct")) < -1.0]
    stall = [r for r in rows if r.get("reason") == "stall_exit"]
    if len(late) >= 2: prop("stallExit.afterMinutes", cur - stp, f"{len(late)} dead trades (hw<0.5%) held > {cur} min lost >1%")
    elif len(stall) >= 3 and sum(f(r.get("pnlPct")) for r in stall) / len(stall) > -0.2: prop("stallExit.afterMinutes", cur + stp, f"stall exits averaging > −0.2% ({len(stall)}): give trades more time")
    # 3. after-10:00 TA requirement
    late_e = [r for r in rows if (r.get("entryAt") or "")[11:16] >= "10:00"]
    tb = [x for x in (getp(C, "entryFilters.ta.requiredPassCountByTime") or []) if x.get("tag") == "after1000-5of5"]
    if len(late_e) >= 6 and tb:
        wr = sum(1 for r in late_e if f(r.get("pnlUsd")) > 0) / len(late_e); cur = tb[0]["requiredPassCount"]
        new = min(5, cur + 1) if wr < 0.25 else (max(3, cur - 1) if wr >= 0.40 else cur)   # ±1 step from the current value (profile starts at 3), never a jump back to 5
        if new != cur: ch.append({"param": "entryFilters.ta.requiredPassCountByTime[after1000].requiredPassCount", "old": cur, "new": new, "evidence": f"≥10:00 entries win {wr:.0%} over {len(late_e)}", "_tb": True})
    # 4. liquidity bands: per-band average R over its trades (raise if < −0.30R, lower if > +0.30R)
    bands = getp(C, "entryFilters.minAvgSharesPer5MinBarByTime") or []; lb = B.get("liquidityBandShares") or {}
    for i, bnd in enumerate(bands):
        inb = [r for r in rows if bnd.get("fromEt", "") <= (r.get("entryAt") or "")[11:16] < bnd.get("toEt", "")]
        if len(inb) < 3: continue
        aR = sum(f(r.get("R")) for r in inb) / len(inb); new = bnd["shares"]
        if aR < -0.30: new = min(lb.get("max", 200000), bnd["shares"] + lb.get("step", 25000))
        elif aR > 0.30: new = max(lb.get("min", 25000), bnd["shares"] - lb.get("step", 25000))
        if new != bnd["shares"]: ch.append({"param": f"entryFilters.minAvgSharesPer5MinBarByTime[{bnd['fromEt']}-{bnd['toEt']}].shares", "old": bnd["shares"], "new": new, "evidence": f"{len(inb)} trades avg {aR:.2f}R", "_band": i})
    # HARD FLOORS (Kevin 2026-11-10 16:24/16:25 ET): never tune these, whatever the evidence or config bounds say
    ch = [c_ for c_ in ch if not any(str(c_["param"]).startswith(x) for x in LOCKED_PARAMS)]
    # RISK PROFILE GUARD (reset 2026-11-17 higher-risk+15, Kevin 09:27 ET “Widen your risk tolerance by 15% confirm”): params the profile set are tuned only from trades taken under it
    # (≥ riskProfile.minTradesBeforeTune entries on/after effectiveFrom=2026-11-17); then tuning continues from the new values (never a silent revert).
    RP = C.get("riskProfile") or {}
    if RP.get("active"):
        _since = [r for r in rows if str(r.get("entryAt") or "")[:10] >= str(RP.get("effectiveFrom", "9999"))]
        if len(_since) < int(RP.get("minTradesBeforeTune", 6)):
            _guard = tuple(RP.get("guardedParams") or ("stallExit.afterMinutes", "entryFilters.ta.requiredPassCountByTime", "recoveryModel.thresholdPct"))
            ch = [c_ for c_ in ch if not any(str(c_["param"]).startswith(x) for x in _guard)]
    ch = ch[: int(SL.get("maxChangesPerDay", 3))]
    if f((C.get("tpModel") or {}).get("stopPct"), -2.0) < -MAX_TRADE_LOSS_PCT:   # self-heal: a stop wider than −5% is never allowed
        C["tpModel"]["stopPct"] = -4.5; apply and ch.append({"param": "tpModel.stopPct", "old": "< −5", "new": -4.5, "evidence": "hard floor: stop may never be wider than −5% (reset to the −4.5% trigger / −5% limit hard stop)"})
    rch = recovery_tune(C, apply=apply)
    rch += setup_promotion(C, apply=apply)   # separate budget: threshold + one weight pair, bounded, logged (applied into C here)
    if apply and ch:
        at = datetime.now(ET).isoformat(timespec="seconds")
        for c_ in ch:
            if c_.pop("_tb", False): tb[0]["requiredPassCount"] = c_["new"]
            elif "_band" in c_: bands[c_.pop("_band")]["shares"] = c_["new"]
            else: setp(C, c_["param"], c_["new"])
            row = dict(c_, at=at, by="desk_learn.py learn (selfLearning, Kevin 2026-11-10 16:07 ET authority)", sessionDate=D)
            C.setdefault("selfLearningLog", []).append(row); C.setdefault("improvementsApplied", []).append(row)
        tmp = CONFIG + ".tmp-learn"; json.dump(C, open(tmp, "w"), indent=1); json.load(open(tmp)); _os.replace(tmp, CONFIG)
    if apply and rch and not ch:
        tmp = CONFIG + ".tmp-learn"; json.dump(C, open(tmp, "w"), indent=1); json.load(open(tmp)); _os.replace(tmp, CONFIG)
    for c_ in ch: c_.pop("_band", None); c_.pop("_tb", None)
    return {"ok": True, "applied": bool(apply and (ch or rch)), "changes": ch, "recoveryChanges": rch, "trades": len(rows)}


# ---------------- PRIME DIRECTIVE: decision success rate (Kevin 2026-11-10 16:31 ET) + recovery-model tuning (16:28/16:30) ----------------
DECISION_DEFS = {
    "entry": "correct if the round trip closed with pnlUsd > 0",
    "loss_exit": "−2% score sell or −5% hard stop / any losing exit: correct if price did NOT get back to entry for the rest of the session (post-exit tracking)",
    "hold": "hold at the −2% score check: correct if price got back above −2% before touching the −4.5% hard-stop trigger",
    "stall_exit": "correct if price did not rise ≥ 2% above max(entry, exit) for the rest of the session",
    "profit_exit": "take-profit / trailing / profit exit: correct if price did not rise ≥ 2% above the exit price for the rest of the session",
    "blocked": "blocked candidate: correct if it would NOT have reached +2% before −2% (only when outcome data exists; wouldHit null → excluded)",
}
def _recovery():
    import importlib.util as _u
    sp = _u.spec_from_file_location("recovery", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "recovery.py")); m = _u.module_from_spec(sp); sp.loader.exec_module(m); return m
def decision_rate(entries, outcomes, blocked=()):
    by = {}
    def add(k, ok): r = by.setdefault(k, [0, 0]); r[0] += 1 if ok else 0; r[1] += 1
    for e in entries: add("entry", f(e.get("pnlUsd")) > 0)
    for o in outcomes:
        k = o.get("kind"); k = "loss_exit" if k in ("score_exit", "hard_stop", "loss_exit") else k
        if o.get("label") in ("correct", "wrong") and k: add(k, o["label"] == "correct")
    for b in blocked:
        if b.get("label") in ("correct", "wrong"): add("blocked", b["label"] == "correct")
    c = sum(v[0] for v in by.values()); n = sum(v[1] for v in by.values())
    return {"ratePct": round(100 * c / n, 1) if n else None, "correct": c, "n": n, "byType": {k: {"correct": v[0], "n": v[1], "ratePct": round(100 * v[0] / v[1], 1)} for k, v in by.items()}}
def decision_baseline(bars_dir="/workspace/equity-am-desk/kb/backtest-bars"):
    R = _recovery(); H = history(); bt = R.backtest(H, bars_dir)
    return decision_rate(H, bt["postExit"]), bt
def decision_today(D, state_path=None, journal_path=None):
    R = _recovery(); st = jload(state_path or "/workspace/robinhood-fable-agent/data/equity-paper/morning-session.json", {}) or {}
    ents = [r for r in st.get("roundTrips") or [] if str(r.get("exitAt", ""))[:10] == D]
    outs = [o for o in R.read_journal(journal_path) if o.get("type") == "outcome" and str(o.get("exitAt") or o.get("at") or "")[:10] == D]
    return decision_rate(ents, outs)
def recovery_tune(C, apply=False, journal_path=None):
    """Bounded tuning of recoveryModel.thresholdPct (30–70, Kevin 16:30 authorized) and weights from labeled outcomes.
    Never touches the −2% decision point or the −5% hard stop."""
    R = _recovery(); M = C.get("recoveryModel") or {}; J = R.read_journal(journal_path)
    dec = {d["id"]: d for d in J if d.get("type") == "decision"}; outs = [o for o in J if o.get("type") == "outcome" and o.get("label")]
    tb = M.get("thresholdBounds") or {"min": 30, "max": 70, "step": 5}; wb = M.get("weightBounds") or {"min": 0.02, "max": 0.35, "step": 0.02}
    n_min = int(M.get("minLabeled", 6)); ch = []
    _rp = C.get("riskProfile") or {}
    if _rp.get("active"):   # only decisions on/after riskProfile.effectiveFrom (2026-11-17 higher-risk+15, −3.45% point / new thresholds) tune the new threshold
        _ef = str(_rp.get("effectiveFrom", "9999")); outs = [o for o in outs if str(o.get("date") or o.get("exitAt") or o.get("at") or "")[:10] >= _ef]
    exits = [o for o in outs if o.get("kind") in ("score_exit", "hard_stop")]; holds = [o for o in outs if o.get("kind") == "hold"]
    if len(exits) + len(holds) >= n_min:
        down_p = sum(1 for o in exits if o["label"] == "wrong") / len(exits) if exits else 0.0     # exits that recovered → hold more
        up_p = sum(1 for o in holds if o["label"] == "wrong") / len(holds) if holds else 0.0       # holds that ended at −5% → exit more
        T = f(M.get("thresholdPct"), 50); new = T
        if down_p - up_p > 0.15: new = max(tb["min"], T - tb["step"])
        elif up_p - down_p > 0.15: new = min(tb["max"], T + tb["step"])
        if new != T: ch.append({"param": "recoveryModel.thresholdPct", "old": T, "new": new, "evidence": f"exits recovered {down_p:.0%} (n{len(exits)}) vs holds ended at −5% {up_p:.0%} (n{len(holds)})"})
    # weights: separation of each component between 'should have held' and 'should have exited'
    ys = []
    for o in outs:
        d = dec.get(o.get("decisionId"))
        if not d or not d.get("components"): continue
        y = (o["label"] == "wrong") if o.get("kind") in ("score_exit", "hard_stop") else (o["label"] == "correct") if o.get("kind") == "hold" else None
        if y is not None: ys.append((d["components"], y))
    if len(ys) >= max(8, n_min) and any(y for _, y in ys) and any(not y for _, y in ys):
        W = dict(R.DEFAULT_W); W.update(M.get("weights") or {}); sep = {}
        for k in W:
            a = [c.get(k, 0.5) for c, y in ys if y]; b = [c.get(k, 0.5) for c, y in ys if not y]
            sep[k] = sum(a) / len(a) - sum(b) / len(b)
        best = max(sep, key=sep.get); worst = min(sep, key=sep.get)
        if best != worst and sep[best] > 0.05:
            nb = round(min(wb["max"], W[best] + wb["step"]), 3); nw = round(max(wb["min"], W[worst] - wb["step"]), 3)
            if nb != W[best] or nw != W[worst]:
                ch.append({"param": f"recoveryModel.weights.{best}", "old": W[best], "new": nb, "evidence": f"separation {sep[best]:+.2f} over {len(ys)} labeled decisions"})
                ch.append({"param": f"recoveryModel.weights.{worst}", "old": W[worst], "new": nw, "evidence": f"separation {sep[worst]:+.2f} over {len(ys)} labeled decisions"})
    if apply and ch:
        at = datetime.now(ET).isoformat(timespec="seconds"); M = C.setdefault("recoveryModel", {})
        for c_ in ch:
            if c_["param"] == "recoveryModel.thresholdPct": M["thresholdPct"] = c_["new"]
            else: M.setdefault("weights", dict(R.DEFAULT_W))[c_["param"].split(".")[-1]] = c_["new"]
            row = dict(c_, at=at, by="desk_learn.py recovery_tune (Kevin 2026-11-10 16:30 ET authority; threshold bounds 30–70)")
            C.setdefault("selfLearningLog", []).append(row); C.setdefault("improvementsApplied", []).append(row)
    return ch


def setup_promotion(C, apply=False, paper_dir=None):
    """entryPlaybook: promote a paper-only setup to live when the 07:30 premarket paper session shows positive expectancy
    (n ≥ promote.minTrades, win ≥ promote.minWinPct, avg ≥ promote.minAvgPct); demote a live setup when its last demote.lookback
    live trades average < 0 with win < demote.maxWinPct. Logged; never touches the hard floors."""
    PB = C.get("entryPlaybook") or {}
    if not PB.get("enabled"): return []
    pr = PB.get("promote") or {}; dm = PB.get("demote") or {}; ch = []
    base = paper_dir or (C.get("premarketPaper") or {}).get("stateDir") or "/workspace/robinhood-fable-agent/data/equity-paper/premarket-paper"
    paper = {}
    shadow = (C.get("paperShadow") or {}).get("stateDir") or "/workspace/robinhood-fable-agent/data/equity-paper/intraday-shadow"
    for fp in sorted(glob.glob(f"{base}/*/morning-session.json")) + sorted(glob.glob(f"{paper_dir or shadow}/*/state.json")):
        for r in (jload(fp, {}) or {}).get("roundTrips") or []:
            k = r.get("setup") or r.get("_setup")
            if k: paper.setdefault(k, []).append(r)
    live = set(PB.get("liveSetups") or []); po = list(PB.get("paperOnlySetups") or [])
    for k in po:
        rows = paper.get(k, [])
        if len(rows) >= int(pr.get("minTrades", 10)):
            win = sum(1 for r in rows if f(r.get("pnlUsd")) > 0) / len(rows) * 100; avg = sum(f(r.get("pnlPct")) for r in rows) / len(rows)
            if win >= f(pr.get("minWinPct"), 40) and avg >= f(pr.get("minAvgPct"), 0.5):
                ch.append({"param": f"entryPlaybook.liveSetups+{k}", "old": "paper-only", "new": "live", "evidence": f"premarket paper n{len(rows)} win {win:.0f}% avg {avg:+.2f}%"})
    H = history()
    for k in sorted(live):
        rows = [r for r in H if r.get("_setup") == k][-int(dm.get("lookback", 15)):]
        if len(rows) >= int(dm.get("minTrades", 10)):
            win = sum(1 for r in rows if f(r.get("pnlUsd")) > 0) / len(rows) * 100; avg = sum(f(r.get("pnlPct")) for r in rows) / len(rows)
            if avg < 0 and win < f(dm.get("maxWinPct"), 30):
                ch.append({"param": f"entryPlaybook.liveSetups-{k}", "old": "live", "new": "paper-only", "evidence": f"last {len(rows)} live: win {win:.0f}% avg {avg:+.2f}%"})
    if apply and ch:
        at = datetime.now(ET).isoformat(timespec="seconds")
        for c_ in ch:
            k = c_["param"].split("+")[-1].split("-")[-1] if "+" in c_["param"] else c_["param"].split("liveSetups-")[-1]
            L = set(PB.get("liveSetups") or []); P_ = set(PB.get("paperOnlySetups") or [])
            if "+" in c_["param"]: L.add(k); P_.discard(k)
            else: L.discard(k); P_.add(k)
            PB["liveSetups"] = sorted(L); PB["paperOnlySetups"] = sorted(P_)
            row = dict(c_, at=at, by="desk_learn.py setup_promotion (SILAS decision authority, Kevin 2026-11-10 16:49 ET)")
            C.setdefault("selfLearningLog", []).append(row); C.setdefault("improvementsApplied", []).append(row)
    return ch

def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("patterns"); x.add_argument("--out-dir", default=KB)
    y = sp.add_parser("watchlist"); y.add_argument("--date", required=True); y.add_argument("--news"); y.add_argument("--movers"); y.add_argument("--out-dir", default=KB)
    z = sp.add_parser("learn"); z.add_argument("--apply", action="store_true"); z.add_argument("--date")
    z2 = sp.add_parser("decision-rate"); z2.add_argument("--date"); z2.add_argument("--state"); z2.add_argument("--baseline", action="store_true"); z2.add_argument("--paper", action="store_true", help="market-hours paper shadow decisions (labeled paper)")
    a = ap.parse_args(argv)
    if a.cmd == "patterns": P = patterns(a.out_dir); print(json.dumps({"ok": True, "trades": P["trades"], "setupRanking": P["setupRanking"]})); return 0
    if a.cmd == "watchlist": print(json.dumps(watchlist(a.date, a.news, a.movers, a.out_dir))[:2000]); return 0
    if a.cmd == "learn": print(json.dumps(learn(a.apply, a.date))); return 0
    if a.cmd == "decision-rate":
        C = jload(CONFIG, {}) or {}; O = C.get("decisionObjective") or {}
        if a.baseline: r, _ = decision_baseline(); print(json.dumps(r)); return 0
        if a.paper:
            R = _recovery(); sd = (C.get("paperShadow") or {}).get("stateDir") or "/workspace/robinhood-fable-agent/data/equity-paper/intraday-shadow"
            D = a.date; ents = []
            for fp in sorted(glob.glob(f"{sd}/*/state.json")):
                ents += [r for r in (jload(fp, {}) or {}).get("roundTrips") or [] if not D or str(r.get("exitAt", ""))[:10] == D]
            outs = [o for o in R.read_journal(f"{sd}/shadow-decisions.jsonl") if o.get("type") == "outcome" and (not D or o.get("date") == D)]
            r = decision_rate(ents, outs); r["paper"] = True
            r["line"] = f"Paper shadow decisions: {r['ratePct'] if r['ratePct'] is not None else '—'}% correct ({r['correct']}/{r['n']}) [paper, not live]"
            print(json.dumps(r)); return 0
        D = a.date or datetime.now(ET).date().isoformat(); r = decision_today(D, a.state)
        b0, g = O.get("baselinePct"), O.get("goalPct")
        r["line"] = f"Decisions: {r['ratePct'] if r['ratePct'] is not None else '—'}% correct today ({r['correct']}/{r['n']}) | baseline {b0}% → goal {g}%"
        print(json.dumps(r)); return 0
if __name__ == "__main__": sys.exit(main())
