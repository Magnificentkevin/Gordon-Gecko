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

"""MARKET-HOURS PAPER SHADOW SESSION 09:30–15:45 ET (SILAS decision 2026-11-10 16:55 ET under Kevin's 16:49 final-authority grant).

Runs at the END of each live manage fire (live work first; skipped when the fire is running long) and trades ONLY the
paper-only setups (re-entries incl. winner recycle, orb_breakout, midday_momentum, vwap_reclaim, momentum_pullback,
post-10:00 non-A+ candidates) in its OWN paper book. Simulated fills from the live quotes the fire already fetched.
Same exit logic as live: hard stop (trigger entry×0.955, fill at the bid but never better than the limit entry×0.95 unless the bid is higher),
−2% recovery decision (recovery.py score, threshold by time), stall exit (stallExit.afterMinutes, hw < +1%), TP floor
(tpModel.floorPct), +2% trailing lock (stop ≥ entry×1.005, hw×0.98), shadow flatten at 15:45.

ISOLATION (hard): never calls a broker, never imports reconcile/discretion write paths, writes ONLY under config
paperShadow.stateDir (refuses any other path), never reads or writes live state / P&L / kill switch / RT cap / bank stop.
Trades are labeled paper (source "paper_shadow") and feed desk_learn setup promotion + paper decision-success tracking.

  init  --date D [--cash X]
  tick  --date D --quotes <get_equity_quotes raw> [--bars5 <5m raw for held + candidates>] [--candidates <json file|[]>] [--now] [--budget-s 20]
        candidates = [{"symbol","setup","last"?,"dayPct"?}] — the live gate's refusals whose ONLY blocking reasons start with "playbook_"
  summary --date D
"""
import argparse, json, math, os, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.environ.get("RECONCILE_CONFIG") or "/workspace/robinhood-fable-agent/config/equity-morning-session.json"
def jload(p, d=None):
    try: return json.load(open(p))
    except Exception: return d
def num(x, d=0.0):
    try: return float(x)
    except Exception: return d
def cfg(): return jload(CFG, {}) or {}
def base(C): return os.path.realpath((C.get("paperShadow") or {}).get("stateDir") or "/workspace/robinhood-fable-agent/data/equity-paper/intraday-shadow")
def paths(C, D):
    b = base(C); d = f"{b}/{D}"
    return {"dir": d, "book": f"{d}/book.json", "state": f"{d}/state.json", "journal": f"{b}/shadow-decisions.jsonl", "base": b}
def safe_save(C, p, obj):
    rp = os.path.realpath(p)
    if not rp.startswith(base(C) + os.sep): raise SystemExit(json.dumps({"ok": False, "why": f"paper shadow refuses to write outside {base(C)}: {p}"}))
    os.makedirs(os.path.dirname(rp), exist_ok=True); t = rp + ".tmp"; json.dump(obj, open(t, "w"), indent=1); os.replace(t, rp)
def journal(C, row):
    p = paths(C, "x")["journal"]; rp = os.path.realpath(p)
    if not rp.startswith(base(C) + os.sep): raise SystemExit("journal outside shadow dir")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "a") as fh: fh.write(json.dumps(dict(row, paper=True, source="paper_shadow")) + "\n")
def recovery():
    import importlib.util as u
    sp = u.spec_from_file_location("recovery", f"{HERE}/recovery.py"); m = u.module_from_spec(sp); sp.loader.exec_module(m); return m
def quotes(raw):
    d = jload(raw, {}) if isinstance(raw, str) else (raw or {}); d = d.get("data", d) if isinstance(d, dict) else {}; out = {}
    for r in (d.get("results") or []) if isinstance(d, dict) else []:
        q = r.get("quote", r); s = str(q.get("symbol", "")).upper()
        bid = num(q.get("bid_price")) or num(q.get("last_trade_price")); ask = num(q.get("ask_price")) or num(q.get("last_trade_price")) or bid
        if s and bid > 0: out[s] = {"bid": bid, "ask": ask}
    return out
def init(C, D, cash=None, now=None):
    P = paths(C, D)
    if os.path.exists(P["book"]): return jload(P["book"])
    sc = cash if cash is not None else num((C.get("paperShadow") or {}).get("startCashUsd"), 100.0)
    book = {"date": D, "startCash": round(sc, 2), "cash": round(sc, 2), "positions": {}, "createdAt": (now or datetime.now(ET)).isoformat(timespec="seconds"), "paper": True}
    safe_save(C, P["book"], book); safe_save(C, P["state"], {"sessionDate": D, "mode": "paper_shadow", "roundTrips": [], "decisions": []}); return book

def tick(C, D, q, bars5=None, cands=(), now=None, budget_s=20.0):
    t0 = time.monotonic(); now = now or datetime.now(ET); hm = now.strftime("%H:%M"); SH = C.get("paperShadow") or {}
    if not ("09:30" <= hm <= (SH.get("endEt") or "15:45")): return {"ok": True, "skipped": "outside 09:30–15:45"}
    P = paths(C, D); book = jload(P["book"]) or init(C, D, now=now); st = jload(P["state"], {}) or {"sessionDate": D, "roundTrips": [], "decisions": []}
    R = recovery(); floor = num((C.get("tpModel") or {}).get("floorPct"), 6.0); stall_m = num((C.get("stallExit") or {}).get("afterMinutes"), 10)
    acts = []
    def close(sym, px, why):
        p = book["positions"].pop(sym); pnl = (px - p["entry"]) * p["qty"]; book["cash"] = round(book["cash"] + px * p["qty"], 4)
        rt = {"symbol": sym, "setup": p["setup"], "qty": p["qty"], "entryPrice": p["entry"], "entryAt": p["at"], "exitPrice": round(px, 4), "exitAt": now.isoformat(timespec="seconds"),
              "pnlUsd": round(pnl, 4), "pnlPct": round((px / p["entry"] - 1) * 100, 3), "reason": why, "hwPct": round((p["hw"] / p["entry"] - 1) * 100, 3), "paper": True, "source": "paper_shadow"}
        st["roundTrips"].append(rt); acts.append({"exit": sym, "why": why, "pnlUsd": rt["pnlUsd"]})
        journal(C, {"type": "exit", "date": D, **rt})
    # 1. manage held shadow positions (cheap, quotes only; recovery score only when below −2% and bars given)
    for sym in list(book["positions"]):
        p = book["positions"][sym]; qq = q.get(sym)
        if not qq: continue
        bid = qq["bid"]; e = p["entry"]; p["hw"] = max(p["hw"], bid)
        mins = (now - datetime.fromisoformat(p["at"])).total_seconds() / 60
        trail = max(e * 1.005, p["hw"] * 0.98) if p["hw"] >= e * 1.02 else None
        if hm >= (SH.get("endEt") or "15:45"): close(sym, bid, "shadow_flatten_1545")
        elif bid <= e * 0.955: close(sym, max(min(bid, e * 0.955), e * 0.95) if bid >= e * 0.95 else bid, "hard_stop")
        elif bid >= e * (1 + floor / 100): close(sym, bid, "tp_floor")
        elif trail and bid <= trail: close(sym, bid, "trail_lock")
        elif mins >= stall_m and p["hw"] < e * 1.01 and bid < e * 1.005: close(sym, bid, "stall_exit")
        elif bid <= e * (1 + R.DECISION_PCT / 100):   # recovery decision point (−3.45% from 2026-11-17 higher-risk+15)
            if bars5 and time.monotonic() - t0 < budget_s:
                bb = R.bars_of(bars5, sym); spy = R.bars_of(bars5, "SPY")
                w, T = R.model(C, hm); sc = R.score(bb, e, bid, spy5=spy, weights=w, threshold=T)
                dec = {"type": "decision", "date": D, "id": f"shadow:{sym}:{now.isoformat(timespec='seconds')}", "symbol": sym, "entry": e, "price": bid, "at": now.isoformat(timespec="seconds"),
                       "score": sc["score"], "threshold": T, "decision": sc["decision"], "components": sc["components"], "setup": p["setup"]}
                journal(C, dec); st.setdefault("decisions", []).append(dec)
                if sc["decision"] == "exit": close(sym, bid, f"recovery_score_exit {sc['score']}")
                else: p.setdefault("holds", []).append({"at": dec["at"], "price": bid, "score": sc["score"], "id": dec["id"]})
    # 2. entries: paper-only setups only, ≤ paperShadow.maxPositions, buy cutoff, never a symbol already held in the shadow book
    paper_only = set((C.get("entryPlaybook") or {}).get("paperOnlySetups") or []) | {"after1000_non_aplus"}
    mx = int(SH.get("maxPositions", 2)); cut = SH.get("noNewBuysAfterEt") or "15:30"; skipped = []
    for c in cands or []:
        if time.monotonic() - t0 > budget_s: skipped.append("budget"); break
        s = str(c.get("symbol", "")).upper(); setup = c.get("setup") or "after1000_non_aplus"
        if not s or s in book["positions"] or hm >= cut or len(book["positions"]) >= mx: continue
        if setup not in paper_only: continue
        qq = q.get(s)
        if not qq or qq["ask"] <= 0: continue
        free = mx - len(book["positions"]); alloc = book["cash"] / free
        qty = math.floor(alloc / qq["ask"]) or round(alloc / qq["ask"], 6)
        if qty <= 0 or qty * qq["ask"] > book["cash"] + 1e-9: continue
        book["cash"] = round(book["cash"] - qty * qq["ask"], 4)
        book["positions"][s] = {"qty": qty, "entry": qq["ask"], "at": now.isoformat(timespec="seconds"), "hw": qq["ask"], "setup": setup}
        acts.append({"buy": s, "setup": setup, "qty": qty, "px": qq["ask"]}); journal(C, {"type": "entry", "date": D, "symbol": s, "setup": setup, "price": qq["ask"], "qty": qty, "at": now.isoformat(timespec="seconds")})
    safe_save(C, P["book"], book); safe_save(C, P["state"], st)
    return {"ok": True, "actions": acts, "held": list(book["positions"]), "cash": book["cash"], "elapsedS": round(time.monotonic() - t0, 3), "skipped": skipped}

def summary(C, D):
    P = paths(C, D); st = jload(P["state"], {}) or {}; book = jload(P["book"], {}) or {}; rts = st.get("roundTrips") or []
    w = sum(1 for r in rts if r["pnlUsd"] > 0); by = {}
    for r in rts:
        b = by.setdefault(r["setup"], {"n": 0, "wins": 0, "pnlUsd": 0.0}); b["n"] += 1; b["wins"] += r["pnlUsd"] > 0; b["pnlUsd"] = round(b["pnlUsd"] + r["pnlUsd"], 4)
    end = book.get("cash", 0) + sum(p["qty"] * p["entry"] for p in (book.get("positions") or {}).values())
    return {"date": D, "wl": [w, len(rts) - w], "startCash": book.get("startCash"), "endCash": round(end, 2), "bySetup": by,
            "line": f"PAPER SHADOW — {D}: W/L {w}/{len(rts) - w} | paper ${num(book.get('startCash')):.2f} → ${end:.2f}"}

def label(C, D, bars):
    """After the close (report.md / kb-refresh): post-exit tracking of every shadow exit + hold with rest-of-session 5m bars →
    outcome rows (paper=True) in the shadow journal; feeds desk_learn paper decision-success + recovery tuning evidence."""
    R = recovery(); P = paths(C, D); st = jload(P["state"], {}) or {}; out = []
    done = {(o.get("symbol"), o.get("exitAt"), o.get("kind")) for o in R.read_journal(P["journal"]) if o.get("type") == "outcome" and o.get("date") == D}
    for r in st.get("roundTrips") or []:
        why = r["reason"]; kind = "stall_exit" if why == "stall_exit" else ("profit_exit" if r["pnlUsd"] > 0 else ("hard_stop" if why == "hard_stop" else "score_exit" if why.startswith("recovery") else "loss_exit"))
        if (r["symbol"], r["exitAt"], kind) in done: continue
        pe = R.post_exit(r["entryPrice"], r["exitPrice"], r["exitAt"], R.bars_of(bars, r["symbol"]), None, "loss_exit" if kind in ("hard_stop", "score_exit") else kind)
        if pe.get("tracked"):
            row = dict(pe, type="outcome", date=D, symbol=r["symbol"], setup=r["setup"], kind=kind, exitAt=r["exitAt"], entry=r["entryPrice"], exitPrice=r["exitPrice"])
            journal(C, row); out.append(row)
    for d in st.get("decisions") or []:
        if d.get("decision") != "hold" or (d["symbol"], d["at"], "hold") in done: continue
        pe = R.post_exit(d["entry"], d["price"], d["at"], R.bars_of(bars, d["symbol"]), None, "hold")
        if pe.get("tracked"):
            row = dict(pe, type="outcome", date=D, symbol=d["symbol"], setup=d.get("setup"), kind="hold", decisionId=d["id"], exitAt=d["at"], entry=d["entry"], exitPrice=d["price"])
            journal(C, row); out.append(row)
    return {"ok": True, "labeled": len(out), "wrong": sum(1 for o in out if o.get("label") == "wrong")}

def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("init"); x.add_argument("--date", required=True); x.add_argument("--cash", type=float); x.add_argument("--now")
    y = sp.add_parser("tick"); y.add_argument("--date", required=True); y.add_argument("--quotes", required=True); y.add_argument("--bars5"); y.add_argument("--candidates"); y.add_argument("--now"); y.add_argument("--budget-s", type=float, default=20.0)
    z = sp.add_parser("summary"); z.add_argument("--date", required=True)
    w_ = sp.add_parser("label"); w_.add_argument("--date", required=True); w_.add_argument("--bars5", required=True)
    a = ap.parse_args(argv); C = cfg()
    now = datetime.fromisoformat(a.now).astimezone(ET) if getattr(a, "now", None) else datetime.now(ET)
    if not (C.get("paperShadow") or {}).get("enabled", True): print(json.dumps({"ok": True, "skipped": "paperShadow disabled"})); return 0
    if a.cmd == "init": print(json.dumps(init(C, a.date, a.cash, now))); return 0
    if a.cmd == "tick":
        cands = []
        if a.candidates:
            cands = jload(a.candidates, None)
            if cands is None:
                try: cands = json.loads(a.candidates)
                except Exception: cands = []
        bars = jload(a.bars5, None) if a.bars5 else None
        print(json.dumps(tick(C, a.date, quotes(a.quotes), bars, cands, now, a.budget_s))); return 0
    if a.cmd == "summary": print(json.dumps(summary(C, a.date))); return 0
    if a.cmd == "label": print(json.dumps(label(C, a.date, jload(a.bars5, {})))); return 0
if __name__ == "__main__": sys.exit(main())
