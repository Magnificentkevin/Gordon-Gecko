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

"""HARD RISK FLOORS for the live equity desk (the live account). Locked; desk_learn.py / the daily revise can never change them.

1) PER-TRADE 5% MAX LOSS (Kevin 2026-11-10 16:25 ET "Add 5% loss rule on individual trades")
   The normal protective stop_limit stays as tuned (tpModel.stopPct, −2%); no stop may be set wider than −5% from entry
   (reconcile.py stopargs --entry). BACKSTOP every fire: a position whose bid (fallback last) is at or below entry × 0.95
   (gapped through the stop / stop-limit did not fill) → cancel its sell orders, verify, then exit at once with a market sell.
     trade-cap --positions <get_equity_positions raw> --quotes <get_equity_quotes raw> [--orders <get_equity_orders raw>]
       exit 0 = nothing breached; exit 8 = `exits[]` to run NOW (cancel `cancelOrderIds` → verify → place `sell` kwargs).

2) BANK DRAWDOWN SYSTEM STOP (Kevin 2026-11-10 16:24 ET "Only stop automatic mode when total bank losses 50%")
   live total equity (get_portfolio total_value = cash + positions) ≤ 50% of the baseline bank → SYSTEM STOP:
   flatten safely, cancel open orders, no paper→live switch, no new trades, until Kevin explicitly restarts.
   baseline = config bankStop.baselineUsd (set from live-account equity at the measurement start; plus later owner cash flows) + deposits − withdrawals dated on/after baselineDate
   (config deposits[] + week-desk.json deposits[] + bankStop.cashFlows[], same day+amount counted once). The only other system stop is Kevin's own command (desk.paused / liveMode.armed false).
   The daily kill switch is NOT a system stop (day-only buy pause).
     bank-check --portfolio <get_portfolio raw> [--apply] [--now]   exit 0 ok; exit 9 TRIPPED (new or earlier) → run bank-stop.md
     bank-status                                                    the trip record (stateFile)
     bank-flat-done --positions <raw> --orders <raw> [--now]        records the flatten finished (broker flat + zero open orders), exit 0/6
     bank-restart --by "<Kevin's exact words + time>"               ONLY on Kevin's explicit restart command; archives the trip
     flow --amount <usd> --type deposit|withdrawal [--at] [--note]  record a cash flow (raises/lowers the baseline)
"""
import argparse, json, math, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
MAX_TRADE_LOSS_PCT = 5.0          # hard floor, not read from config on purpose
BANK_STOP_PCT = 50.0              # hard floor default (Kevin 16:24); config may only make it tighter (higher), never looser
CFG = os.environ.get("RECONCILE_CONFIG") or "/workspace/robinhood-fable-agent/config/equity-morning-session.json"
def jload(p, d=None):
    try: return json.load(open(p))
    except Exception: return d
def jsave(p, o):
    t = p + ".tmp"; json.dump(o, open(t, "w"), indent=1); os.replace(t, p)
def num(x, d=0.0):
    try: return float(x)
    except Exception: return d
def now_of(a): return datetime.fromisoformat(a.now).astimezone(ET) if getattr(a, "now", None) else datetime.now(ET)
def iso(t): return t.isoformat(timespec="seconds")
def data(o): return (o or {}).get("data", o or {}) if isinstance(o, dict) else {}
def cfg(): return jload(CFG, {}) or {}
def bs_cfg(C): return C.get("bankStop") or {}
def state_file(C): return bs_cfg(C).get("stateFile") or "/workspace/robinhood-fable-agent/data/equity-paper/bank-stop.json"
def excluded_symbols():
    """Symbols walled off from SILAS (Kevin 2026-11-18 19:03 ET: Anthropic share kept separate). Config excludedSymbols + env SILAS_EXCLUDED."""
    import os
    ex = {str(x).upper() for x in (cfg().get("excludedSymbols") or [])}
    ex |= {x.strip().upper() for x in (os.environ.get("SILAS_EXCLUDED") or "").split(",") if x.strip()}
    return ex
def positions_all(raw):
    d = data(jload(raw, {}) if isinstance(raw, str) else raw)
    rows = d.get("positions") or d.get("results") or (d if isinstance(d, list) else [])
    return [r for r in rows if num(r.get("quantity")) > 0]
def positions(raw):
    ex = excluded_symbols()
    return [r for r in positions_all(raw) if str(r.get("symbol", "")).upper() not in ex]
def orders(raw):
    if not raw: return []
    d = data(jload(raw, {}) if isinstance(raw, str) else raw)
    rows = d.get("orders") or d.get("results") or (d if isinstance(d, list) else [])
    ex = excluded_symbols()
    return [o for o in rows if str(o.get("symbol", "")).upper() not in ex]
OPEN = ("queued", "unconfirmed", "confirmed", "partially_filled", "pending", "new")
def quotes(raw):
    d = data(jload(raw, {}) if isinstance(raw, str) else raw); out = {}
    for r in d.get("results") or d.get("quotes") or []:
        q = r.get("quote", r); s = str(q.get("symbol", "")).upper()
        px = num(q.get("bid_price")) or num(q.get("last_trade_price")) or num(q.get("last_extended_hours_trade_price"))
        if s and px > 0: out[s] = px
    return out

# ---------- 1) per-trade 5% cap ----------
def trade_cap(pos, qts, ords):
    exits, checked = [], []
    for p in pos:
        s = str(p.get("symbol", "")).upper(); e = num(p.get("average_buy_price")); q = num(p.get("quantity")); px = qts.get(s)
        if e <= 0 or not px: checked.append({"symbol": s, "status": "no_quote" if not px else "no_entry"}); continue
        loss = (px / e - 1) * 100; row = {"symbol": s, "entry": e, "price": px, "lossPct": round(loss, 3)}
        checked.append(row)
        if loss <= -MAX_TRADE_LOSS_PCT + 1e-9:
            cancel = [o.get("id") for o in ords if str(o.get("symbol", "")).upper() == s and o.get("side") == "sell" and o.get("state") in OPEN]
            whole = abs(q - round(q)) < 1e-6
            sell = {"account_number": ACCOUNT, "symbol": s, "side": "sell", "type": "market", "time_in_force": "gfd", "market_hours": "regular_hours"}
            sell.update({"quantity": str(int(round(q)))} if whole else {"quantity": f"{q:.6f}"})
            exits.append(dict(row, qty=q, why="max_trade_loss_5pct", cancelOrderIds=cancel, sell=sell,
                              steps="lock → cancel_equity_order each cancelOrderIds → re-read orders (verify cancelled; if one FILLED, re-sync instead) → place_equity_order(sell) → verify fill → reconcile.py sync"))
    return exits, checked
def cmd_trade_cap(a):
    ex, ch = trade_cap(positions(a.positions), quotes(a.quotes), orders(a.orders))
    print(json.dumps({"ok": not ex, "maxTradeLossPct": MAX_TRADE_LOSS_PCT, "exits": ex, "checked": ch,
                      "next": "EXIT NOW: run each exits[].steps before any other decision this fire" if ex else "no position at/below −5% from entry"}))
    return 8 if ex else 0

# ---------- 2) bank drawdown system stop ----------
def baseline(C):
    b = bs_cfg(C); base = num(b.get("baselineUsd"), 100.00)  # illustrative default; override from config
    since = b.get("baselineDate") or "2026-11-11"; flows = []
    wk = jload(b.get("weekDeskFile") or "/workspace/robinhood-fable-agent/data/equity-paper/week-desk.json", {}) or {}
    seen = set()
    for r in list(C.get("deposits") or []) + list(wk.get("deposits") or []) + list(b.get("cashFlows") or []):
        day = str(r.get("at") or r.get("date") or "")[:10]
        if not day or day < since: continue
        key = (day, round(abs(num(r.get("amountUsd"))), 2), str(r.get("type", "deposit"))[:8])
        if key in seen: continue   # same flow recorded in config + week-desk → count once
        seen.add(key)
        amt = abs(num(r.get("amountUsd"))); sign = -1 if str(r.get("type", "deposit")).startswith("withdraw") else 1
        flows.append({"at": r.get("at"), "amountUsd": sign * amt}); base += sign * amt
    return round(base, 2), flows
def threshold_pct(C): return max(BANK_STOP_PCT, num(bs_cfg(C).get("thresholdPct"), BANK_STOP_PCT))
def total_equity(raw):
    d = data(jload(raw, {}) if isinstance(raw, str) else raw)
    tv = d.get("total_value") or d.get("total_equity") or d.get("equity")
    if tv not in (None, ""): return num(tv), "total_value"
    if d.get("cash") is not None: return num(d.get("cash")) + num(d.get("equity_value")), "cash+equity_value"
    return None, "unreadable"
def status_of(C): return jload(state_file(C), {}) or {}
def tripped(C):
    s = status_of(C); return bool(s.get("tripped")), s
def cmd_bank_check(a):
    C = cfg(); now = now_of(a); base, flows = baseline(C); pct = threshold_pct(C); eq, src = total_equity(a.portfolio)
    ex = excluded_symbols(); ex_val = 0.0; ex_note = None
    if ex and eq is not None:
        if a.positions:
            qmap = quotes(a.quotes) if a.quotes else {}
            for r in positions_all(a.positions):
                sym = str(r.get("symbol", "")).upper()
                if sym in ex:
                    px = qmap.get(sym) or num(r.get("price")) or num(r.get("average_buy_price"))
                    ex_val += num(r.get("quantity")) * (px or 0)
            eq = round(eq - ex_val, 2); src += f" minus excluded {sorted(ex)} ${ex_val:.2f}"
        else:
            ex_note = f"excludedSymbols {sorted(ex)} configured but --positions not given: equity may include them"
    line = round(base * pct / 100, 2); was, rec = tripped(C)
    out = {"excludedSymbols": sorted(ex), "excludedValueUsd": round(ex_val, 2), "excludedNote": ex_note, "equityUsd": eq, "equitySource": src, "baselineUsd": base, "cashFlows": flows, "thresholdPct": pct, "stopAtOrBelowUsd": line,
           "drawdownPct": (round((eq / base - 1) * 100, 2) if eq is not None and base else None), "alreadyTripped": was}
    if eq is None or eq <= 0:
        out.update(ok=None, why="portfolio unreadable / zero — re-read get_portfolio; do NOT trip on a bad read"); print(json.dumps(out)); return 2
    hit = eq <= line + 1e-9
    rec = dict(rec or {}); rec.update({"lastCheckAt": iso(now), "lastEquityUsd": eq, "baselineUsd": base, "stopAtOrBelowUsd": line})
    if hit and not was:
        rec.update({"tripped": True, "trippedAt": iso(now), "trippedEquityUsd": eq, "flattenDone": False,
                    "escalation": f"SYSTEM STOP — bank drawdown: live equity ${eq:.2f} ≤ {pct:g}% of baseline ${base:.2f} (line ${line:.2f}). "
                                  "Flattening + cancelling all orders now; automatic mode OFF (no paper→live switch, no new trades) until Kevin explicitly restarts.",
                    "escalationNotifiedAt": None})
    # TRIPWIRE (Kevin 2026-11-17 20:06 ET, evaluation item 3): equity ≤ tripwirePct of baseline → alert Kevin, halve size, owner review
    tw = num(bs_cfg(C).get("tripwirePct"), 0.0)
    if tw and eq is not None and not (hit or was):
        tw_line = round(base * tw / 100, 2); tw_hit = eq <= tw_line + 1e-9
        out.update(tripwirePct=tw, tripwireAtOrBelowUsd=tw_line, tripwire=tw_hit, sizeMultiplier=(0.5 if tw_hit else 1.0))
        if tw_hit and not rec.get("tripwireAlertedAt"):
            rec["tripwireAlertedAt"] = iso(now)
            out["tripwireEscalation"] = (f"TRIPWIRE — live equity ${eq:.2f} ≤ {tw:g}% of baseline ${base:.2f} (line ${tw_line:.2f}): "
                                         "size halved until Kevin reviews; system stop at " + f"${line:.2f}.")
    if a.apply: jsave(state_file(C), rec)
    out.update(ok=not (hit or was), tripped=hit or was, newlyTripped=hit and not was, escalation=rec.get("escalation") if (hit or was) else None,
               next=("SYSTEM STOP: run bank-stop.md now (cancel all open orders → flatten every position → bank-flat-done), hand `escalation` to the parent at once"
                     if (hit or was) else "ok — continue"))
    print(json.dumps(out)); return 9 if (hit or was) else 0
def cmd_bank_status(a):
    C = cfg(); base, flows = baseline(C); s = status_of(C)
    print(json.dumps({"tripped": bool(s.get("tripped")), "record": s, "baselineUsd": base, "thresholdPct": threshold_pct(C), "stopAtOrBelowUsd": round(base * threshold_pct(C) / 100, 2)})); return 9 if s.get("tripped") else 0
def cmd_flat_done(a):
    C = cfg(); now = now_of(a); s = status_of(C)
    pos = positions(a.positions); oo = [o for o in orders(a.orders) if o.get("state") in OPEN]
    if pos or oo:
        print(json.dumps({"ok": False, "why": "broker not flat yet", "positions": [p.get("symbol") for p in pos], "openOrders": [o.get("id") for o in oo]})); return 6
    s.update({"flattenDone": True, "flattenDoneAt": iso(now)}); jsave(state_file(C), s)
    print(json.dumps({"ok": True, "flattenDone": True, "systemStopped": bool(s.get("tripped"))})); return 0
def cmd_restart(a):
    C = cfg(); now = now_of(a); s = status_of(C)
    if not a.by or "kevin" not in a.by.lower():
        print(json.dumps({"ok": False, "why": "restart is Kevin-only: pass --by with Kevin's explicit restart words + time"})); return 4
    hist = s.get("history") or []
    if s.get("tripped"): hist.append({k: v for k, v in s.items() if k != "history"} | {"restartedAt": iso(now), "restartedBy": a.by})
    jsave(state_file(C), {"tripped": False, "history": hist, "lastRestartAt": iso(now), "lastRestartBy": a.by})
    print(json.dumps({"ok": True, "tripped": False, "note": "automatic mode resumes on the next desk_clock fire (baseline per config bankStop; Kevin may also set a new baselineUsd)"})); return 0
def cmd_flow(a):
    C = jload(CFG, {}); b = C.setdefault("bankStop", {}); t = a.at or iso(datetime.now(ET))
    b.setdefault("cashFlows", []).append({"at": t, "amountUsd": abs(a.amount), "type": a.type, "note": a.note, "countsAsPnl": False})
    jsave(CFG, C); base, _ = baseline(C); print(json.dumps({"ok": True, "baselineUsd": base})); return 0

def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("trade-cap"); x.add_argument("--positions", required=True); x.add_argument("--quotes", required=True); x.add_argument("--orders"); x.set_defaults(fn=cmd_trade_cap)
    x = sp.add_parser("bank-check"); x.add_argument("--portfolio", required=True); x.add_argument("--positions"); x.add_argument("--quotes"); x.add_argument("--apply", action="store_true"); x.add_argument("--now"); x.set_defaults(fn=cmd_bank_check)
    x = sp.add_parser("bank-status"); x.set_defaults(fn=cmd_bank_status)
    x = sp.add_parser("bank-flat-done"); x.add_argument("--positions", required=True); x.add_argument("--orders", required=True); x.add_argument("--now"); x.set_defaults(fn=cmd_flat_done)
    x = sp.add_parser("bank-restart"); x.add_argument("--by", required=True); x.add_argument("--now"); x.set_defaults(fn=cmd_restart)
    x = sp.add_parser("flow"); x.add_argument("--amount", type=float, required=True); x.add_argument("--type", choices=["deposit", "withdrawal"], required=True); x.add_argument("--at"); x.add_argument("--note"); x.set_defaults(fn=cmd_flow)
    a = ap.parse_args(argv); return a.fn(a)
if __name__ == "__main__": sys.exit(main())
