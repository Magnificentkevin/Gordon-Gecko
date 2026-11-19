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

"""reconcile.py — BROKER-FIRST reconciliation + stop-limit GAP GUARD for the Equity AM desk (added 2026-10-21; live from config
`reconcile.applyFrom`, 2026-10-22). NEVER calls the broker and NEVER places orders: it reads raw tool outputs saved by the routine and
prints a plan (actions the routine must execute with the broker tools) and, with --apply, merges the broker truth into the state file
under an exclusive file lock, keyed by ORDER ID (idempotent: running it twice, or from two routines at once, changes nothing the 2nd time).

  sync : python3 /workspace/paper/reconcile.py sync --state <morning-session.json> --positions <get_equity_positions raw>
           --orders <get_equity_orders raw> [--orders <next page> ...] [--quotes <get_equity_quotes raw>] [--routine manage-a]
           [--now ISO] [--apply] [--force] [--max-age-s 90]
  annotate : python3 /workspace/paper/reconcile.py annotate --state <state> --buy-order-id <uuid> --json '{"targetTP": 2.99, ...}'
           (locked merge of desk metadata into the position with that buyOrderId; use it instead of hand-editing positions[]).
  reason : python3 /workspace/paper/reconcile.py reason --state <state> --order-id <uuid> --reason stall_exit|stop_aggressive|hard_flatten_1100|…
           (BUYS too: --reason entries|entries_backup|recycle right after placing, so the lot is recorded as the desk's own buy, not an "adoption")
           (records WHY the desk placed a sell, so the ledger labels the round trip correctly; locked write to state.orderReasons).
  lock / unlock : python3 /workspace/paper/reconcile.py lock --state <state> --symbol S --routine manage-a [--ttl 120] [--wait 0]
           → exit 0 {"ok":true} = you own every order action on S until unlock/expiry; exit 3 {"ok":false,"heldBy":…} = another routine is
           mid-swap on S: place/cancel NOTHING for S this tick. unlock --symbol S --routine R releases it (only the owner can).
           Added 2026-10-21 after manage-a/manage-b raced the same stop↔TP swap (12:40 BB, 13:21 WULF) and flatten-backup raced manage-b at
           15:45 (403 "cannot be cancelled", TP rejected "not enough shares"). Locks live in <state dir>/order-locks.json (flock-guarded).
  fracwatch : python3 /workspace/paper/reconcile.py fracwatch --state <state> --symbol S --routine manage-a (--quotes <get_equity_quotes raw> | --bid B
           [--bid-time ISO]) [--tick-start ISO] [--stop X] [--tp Y] [--action sold_stop|sold_tp|skipped_lock_busy|…] [--order-id ID] [--now ISO]
           FRACTIONAL 1-MINUTE STOP WATCH (Kevin 2026-10-22; config `fractionalWatch`): Robinhood rejects stop/stop-limit orders on fractional
           quantities, so a fractional position's −2% stop/TP is desk-watched about every 60 s inside the manage tick. One call per watch read:
           decides hold / sell_stop / sell_tp / requote (quote > maxQuoteAgeSeconds or no bid) / halted / no_position from the bid vs the ACTIVE
           stop (trailStop if higher) and targetTP in state, appends {at, routine, symbol, bid, stop, tp, action} to state.fractionalWatch.reads[]
           and sets the position's lastWatchedAt under the state file lock, and prints continueWatch / nextReadInS for the tick's
           windowSeconds (270) from --tick-start. It NEVER calls the broker: the routine takes `lock`, re-reads, market-sells, `unlock`s.
           With fractionalWatch.enabled and retryBrokerStop false, `sync` prints `frac_watch` (not `rest_stop`) for a fractional lot.
  statewrite : python3 /workspace/paper/reconcile.py statewrite --state <state> --routine R (--patch <patch.json> | --json '<patch>') [--now ISO]
           python3 /workspace/paper/reconcile.py statewrite --state <state> --routine scan --replace <fresh state.json> [--force]
           THE ONE WAY routines write morning-session.json (2026-10-22; fixes twin ticks overwriting each other's rows, e.g. the 1-minute
           watch's fractionalWatch reads lost to the other tick's end-of-tick "re-read → temp → mv"). Under the SAME exclusive file lock as
           sync/annotate/reason/fracwatch it re-reads the state, applies a PATCH (never a whole-file copy) and writes atomically:
             {"set": {"dotted.path": value}, "merge": {"path": {k: v}}, "append": {"path": [rows]}, "increment": {"path": n},
              "position": [{"symbol": S, "buyOrderId": id?, "fields": {...}}], "claim": {"key": "buyLock", "staleSeconds": 90},
              "release": {"key": "buyLock"}}
           Order: claim → set → merge → increment → append → position → release. Refused (exit 4, nothing written): any path under
           positions/closed/roundTrips/realizedPnlUsd/roundTripCount/orderReasons/gapGuard/fractionalWatch (owned by sync/annotate/reason/
           fracwatch; position metadata goes through the "position" op), unknown ops, an ambiguous position. claim busy → exit 3, nothing
           written. append skips rows already present (idempotent retry). --replace (new-day scan) refuses a file with the same sessionDate
           unless --force.

DESK FIXES 2026-11-10 (Kevin 16:02 ET "Fix mistakes and restart tomorrow"):
  stopargs : python3 reconcile.py stopargs --json '<place_equity_order kwargs>'  → exit 0 {ok:true} only for a valid PROTECTIVE stop:
           side sell, type EXACTLY "stop_limit", stop_price > 0, limit_price > 0 and < stop_price (≥ stop×0.90), whole-share quantity,
           the live account, regular_hours, gfd. Anything else → exit 4 {ok:false, why, fixed:<corrected kwargs>} and the order MUST NOT
           be sent (fixes the 11:54 LCID stop that went in as a plain limit sell because type was missing).
  verify-protection : python3 reconcile.py verify-protection --positions <raw> --orders <raw> [--state S --apply] [--routine R]
           BROKER TRUTH check after every stop placement and at the start of every fire: each whole-share position must have an OPEN
           sell with trigger "stop" + type "limit" (a real stop-limit) covering the full qty, or an open TP limit ≥ entry×1.02.
           A plain limit sell under entry×1.02 is WRONG TYPE (not protection). Exit 0 all protected | 7 unprotected/wrong type
           (→ protect first, NO new buys). --apply writes state.protection {at, unprotected[], wrongType[], buysAllowed}.
  sync now also prints `protection`/`buysAllowed`, a `replace_wrong_type` action, and is APPEND-ONLY for the ledger:
           roundTrips/closed are never removed, realizedPnlUsd = Σ state roundTrips (never reset to a smaller snapshot), roundTripCount
           never decreases; --apply is REFUSED for an empty/incomplete orders snapshot (a placeholder file zeroed realized P&L at 12:48),
           and every recorded round trip is journaled to <state>.rtjournal.jsonl so a reset/overwritten state self-heals on the next sync/
           statewrite. Reset happens only via statewrite --replace with a NEW sessionDate (new trading day).

Why (2026-10-21 post-mortem): ticks reconciled by SYMBOL presence from a broker snapshot taken minutes before the state write, and the
two manage twins + entries overlapped and overwrote each other (SMCI buy 09:36 logged in orders[] but lost from positions[] → adopted
twice 09:39/09:41; INVE/SMCI/AHT stop fills seen only a tick later; AHT#2 copied into closed[] without exit fields). Robinhood also
returns a stop-limit as type="limit" + trigger="stop" — code that looks for type "stop_limit" sees an UNPROTECTED position.

Ledger rules: today's filled BUY orders are lots; filled SELL orders consume lots FIFO per symbol (exit time order). Round-trip key =
<exitOrderId>:<buyOrderId>. Sell reason: trigger stop → resting_stop_limit (trail_stop when stop_price ≥ entry; stop-market → *_market);
TP order id / limit ≥ entry×1.02 → tp_dynamic; otherwise the reason the desk logged for that order id, else closed_at_broker.
GAP GUARD (needs --quotes): a resting stop-limit whose bid ≤ stop is either filling or skipped. bid < limit → escalate NOW
(gap_through_limit); limit ≤ bid ≤ stop → recheck once after ~10 s (memory in state.gapGuard), escalate if still unfilled; a position with
no resting sell and bid ≤ stop → escalate NOW. Escalation = AGGRESSIVE EXIT (cancel → verify → sell limit bid×0.97, retry bid×0.94;
fractional → market). Quotes older than 60 s never trigger an escalation (re-quote first)."""
import os as _os, time as _time
_os.environ["TZ"] = "America/New_York"; _time.tzset()
import argparse, fcntl, json, math, sys, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CONFIG = _os.environ.get("RECONCILE_CONFIG", "/workspace/robinhood-fable-agent/config/equity-morning-session.json")
OPEN = {"new", "queued", "confirmed", "unconfirmed", "partially_filled", "pending"}

def tick(px): return 0.01 if px >= 1 else 0.0001
def up(px): t = tick(px); return round(math.ceil(px / t - 1e-9) * t, 4)
def down(px): t = tick(px); return round(math.floor(px / t + 1e-9) * t, 4)
def f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d
def raw(p):
    """Load a saved MCP tool output; tolerates wrapper text before/after the JSON."""
    t = open(p).read(); i = min([k for k in (t.find("{"), t.find("[")) if k >= 0]); j = max(t.rfind("}"), t.rfind("]"))
    return json.loads(t[i:j + 1])
def pt(s):
    if not s: return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=ET)).astimezone(ET)
def iso(d): return d.isoformat(timespec="seconds") if d else None
def cfg():
    try: return json.load(open(CONFIG)).get("reconcile") or {}
    except Exception: return {}
FW_DEFAULTS = {"enabled": False, "intervalSeconds": 60, "windowSeconds": 270, "retryBrokerStop": True}
def fw_cfg():
    """config.fractionalWatch (Kevin 2026-10-22). Missing block → legacy behaviour (no watch, broker-stop attempt allowed)."""
    try: c = json.load(open(CONFIG)).get("fractionalWatch") or {}
    except Exception: c = {}
    return {**FW_DEFAULTS, **{k: v for k, v in c.items() if v is not None}}

def load_orders(paths):
    seen = {}
    for p in paths or []:
        d = raw(p); d = d.get("data", d) if isinstance(d, dict) else d
        rows = d.get("orders", d.get("results", [])) if isinstance(d, dict) else d
        for o in rows: seen[o["id"]] = o
    ex = excluded_symbols()
    return [o for o in seen.values() if str(o.get("symbol", "")).upper() not in ex]
def excluded_symbols():
    """Symbols walled off from SILAS (Kevin 2026-11-18 19:03 ET: Anthropic share kept separate). Config excludedSymbols + env SILAS_EXCLUDED."""
    ex = {str(x).upper() for x in ((cfg() or {}).get("excludedSymbols") or [])}
    ex |= {x.strip().upper() for x in (_os.environ.get("SILAS_EXCLUDED") or "").split(",") if x.strip()}
    return ex
def load_positions(p):
    d = raw(p); d = d.get("data", d)
    rows = d.get("positions", d.get("results", [])) if isinstance(d, dict) else d
    ex = excluded_symbols()
    return {r["symbol"]: r for r in rows if f(r.get("quantity")) > 0 and str(r.get("symbol", "")).upper() not in ex}
def load_quotes(p):
    if not p: return {}
    d = raw(p); d = d.get("data", d); out = {}
    for r in d.get("results", []) if isinstance(d, dict) else d:
        q = r.get("quote", r)
        if q and q.get("symbol"): out[q["symbol"]] = q
    return out

def kind(o):
    """Robinhood returns stop-limits as type 'limit' + trigger 'stop' (and stop-market as type 'market' + trigger 'stop')."""
    if o.get("trigger") == "stop": return "stop_limit" if o.get("type") == "limit" else "stop_market"
    return "limit" if o.get("type") == "limit" else "market"
def fill_time(o):
    ex = o.get("executions") or []
    ts = [pt(e["timestamp"]) for e in ex if e.get("timestamp")]
    return (max(ts) if ts else pt(o.get("last_transaction_at"))), (min(ts) if ts else pt(o.get("last_transaction_at")))

def ledger(orders, state, day):
    hints = {}
    for r in (state.get("orders") or []):
        oid = r.get("id") or r.get("orderId")
        if oid and r.get("reason"): hints[oid] = r["reason"]
    hints.update(state.get("orderReasons") or {})
    tp_ids = {p.get("tpOrderId") for p in (state.get("positions") or []) if p.get("tpOrderId")}
    lots, sells = [], []
    for o in orders:
        q = f(o.get("cumulative_quantity"))
        last, first = fill_time(o)
        if q <= 0 or not last or last.strftime("%Y-%m-%d") != day: continue
        row = {"id": o["id"], "symbol": o["symbol"], "qty": q, "avg": f(o.get("average_price")), "at": first if o["side"] == "buy" else last,
               "kind": kind(o), "stop": f(o.get("stop_price"), None), "limit": f(o.get("price"), None)}
        (lots if o["side"] == "buy" else sells).append(row)
    lots.sort(key=lambda r: r["at"]); sells.sort(key=lambda r: r["at"])
    for l in lots: l["left"] = l["qty"]
    carry = {p["symbol"]: p for p in (state.get("positions") or []) if not p.get("buyOrderId")}
    rts, warn = [], []
    for s in sells:
        need = s["qty"]
        for l in [x for x in lots if x["symbol"] == s["symbol"] and x["left"] > 1e-9 and x["at"] <= s["at"]]:
            take = min(need, l["left"]); l["left"] = round(l["left"] - take, 6); need = round(need - take, 6)
            rts.append(mk_rt(s, l["id"], l["avg"], l["at"], take, hints, tp_ids))
            if need <= 1e-9: break
        if need > 1e-9:
            c = carry.get(s["symbol"])
            if c: rts.append(mk_rt(s, None, f(c.get("entryPrice")), pt(c.get("entryAt")), need, hints, tp_ids, carry=True))
            else: warn.append(f"sell {s['id'][:8]} {s['symbol']} {need} sh has no matching buy today or state entry")
    return lots, rts, warn

def mk_rt(s, buy_id, entry, entry_at, qty, hints, tp_ids, carry=False):
    k = s["kind"]
    if k in ("stop_limit", "stop_market"):
        trail = s["stop"] is not None and s["stop"] >= entry
        reason = ("trail_stop" if trail else "resting_stop_limit") if k == "stop_limit" else ("trail_stop_market" if trail else "resting_stop_market")
    elif s["id"] in hints: reason = hints[s["id"]]
    elif s["id"] in tp_ids or (k == "limit" and s["limit"] and s["limit"] >= entry * 1.02 * 0.999): reason = "tp_dynamic"
    elif s["avg"] <= entry * 0.985: reason = "stop_aggressive_inferred"   # unlabeled desk sell ≥1.5% under entry counts as a stop-out (kill switch never under-counts)
    else: reason = "closed_at_broker"
    pnl = round((s["avg"] - entry) * qty, 4); pct = round((s["avg"] / entry - 1) * 100, 3) if entry else None
    rt = {"symbol": s["symbol"], "qty": qty, "entryAt": iso(entry_at), "entryPrice": entry, "exitAt": iso(s["at"]), "exitPrice": s["avg"],
          "pnlUsd": pnl, "pnlPct": pct, "R": round(pct / 2.0, 3) if pct is not None else None, "reason": reason,
          "mins": round((s["at"] - entry_at).total_seconds() / 60, 1) if entry_at else None,
          "buyOrderId": buy_id, "exitOrderId": s["id"], "rtKey": f"{s['id']}:{buy_id}", "source": "carryover" if carry else None}
    if s["stop"] is not None and k.startswith("stop"):
        rt["stop"] = s["stop"]; rt["stopSlippagePct"] = round((s["avg"] / s["stop"] - 1) * 100, 3)
    return rt

def present(rt, state_rts):
    for r in state_rts:
        if r.get("rtKey") == rt["rtKey"] or (r.get("exitOrderId") == rt["exitOrderId"] and r.get("buyOrderId") in (rt["buyOrderId"], None)): return True
        if r.get("symbol") == rt["symbol"] and not r.get("exitOrderId") and r.get("exitAt") and abs(f(r.get("qty")) - rt["qty"]) < 1e-6:
            dt = abs((pt(r["exitAt"]) - pt(rt["exitAt"])).total_seconds())
            if dt <= 90: return True
            # hand-written rows often stamp exitAt with the WRITE time (minutes late): same price within half a cent and ≤ 15 min → same trade
            if dt <= 900 and abs(f(r.get("exitPrice")) - rt["exitPrice"]) <= 0.005: return True
    return False

def plan(state, positions, orders, quotes, now, routine):
    C = cfg(); day = now.strftime("%Y-%m-%d")
    lots, rts, warn = ledger(orders, state, day)
    state_rts = state.get("roundTrips") or []
    add_rts = [r for r in rts if not present(r, state_rts)]
    open_orders = [o for o in orders if o.get("state") in OPEN]
    sells_open = {}
    for o in open_orders:
        if o["side"] == "sell": sells_open.setdefault(o["symbol"], []).append(o)
    actions, adopt, keep, drop, fixes = [], [], [], [], []
    sp = state.get("positions") or []
    open_lots = {}
    for l in lots:
        if l["left"] > 1e-9: open_lots.setdefault(l["symbol"], []).append(l)
    reasons = dict(state.get("orderReasons") or {})
    desk_buys = {(r.get("id") or r.get("orderId")): (r.get("source") or r.get("routine") or "desk") for r in (state.get("orders") or []) if r.get("side") == "buy"}
    desk_buys.update({k: v for k, v in reasons.items() if v in DESK_BUY_SOURCES})
    gg = state.get("gapGuard") or {}; gg_new = {}
    grace = f(C.get("gapRecheckSeconds"), 10); max_q_age = f(C.get("maxQuoteAgeSeconds"), 60)
    for p in sp:   # state positions that the broker no longer holds (or whose lot is closed)
        sym = p["symbol"]; bid_lot = p.get("buyOrderId")
        held = sym in positions
        lot_open = (not bid_lot) or any(l["id"] == bid_lot for l in open_lots.get(sym, [])) or not any(l["id"] == bid_lot for l in lots)
        if not held or not lot_open: drop.append({"symbol": sym, "buyOrderId": bid_lot, "why": "not held at broker" if not held else "lot closed (re-hit)"})
        else: keep.append(p)
    for sym, bp in positions.items():
        qty = f(bp.get("quantity")); mine = [p for p in keep if p["symbol"] == sym]
        lots_s = open_lots.get(sym, [])
        known = {p.get("buyOrderId") for p in mine}
        for l in lots_s:
            if l["id"] not in known and not any(not p.get("buyOrderId") for p in mine):
                adopt.append(adopt_row(sym, l["left"], l["avg"], l["at"], l["id"], sells_open.get(sym, []), quotes.get(sym), desk_buys.get(l["id"])))
        if not lots_s and not mine:
            adopt.append(adopt_row(sym, qty, f(bp.get("average_buy_price")), None, None, sells_open.get(sym, []), quotes.get(sym)))
        mine_qty = sum(f(p.get("qty")) for p in mine) + sum(a["qty"] for a in adopt if a["symbol"] == sym)
        if abs(mine_qty - qty) > 1e-6: fixes.append({"symbol": sym, "what": "qty_mismatch", "state": mine_qty, "broker": qty})
        # protection
        so = sells_open.get(sym, []); kinds = [kind(o) for o in so]
        covered = sum(f(o.get("quantity")) - f(o.get("cumulative_quantity")) for o in so)
        entry = (mine[0].get("entryPrice") if mine else None) or (adopt[-1]["entryPrice"] if adopt and adopt[-1]["symbol"] == sym else f(bp.get("average_buy_price")))
        entry = f(entry); lock_stop = up(entry * HARD_TRIGGER) if entry else None   # HARD STOP (Kevin 16:28): trigger −4.5%, limit −5%
        frac = abs(qty - round(qty)) > 1e-6
        FW = fw_cfg()
        if not so and frac and FW["enabled"] and not FW["retryBrokerStop"]:
            p0 = mine[0] if mine else {}
            act_stop = max([f(x) for x in (p0.get("stop"), p0.get("trailStop")) if x is not None] or [lock_stop or 0]) or lock_stop
            actions.append({"type": "frac_watch", "symbol": sym, "qty": qty, "stop": act_stop, "tp": p0.get("targetTP") or p0.get("tp") or (up(entry * 1.02) if entry else None),
                            "intervalSeconds": FW["intervalSeconds"], "windowSeconds": FW["windowSeconds"],
                            "note": "fractional: place NO broker stop (Robinhood rejects; fractionalWatch.retryBrokerStop false) → FRACTIONAL 1-MINUTE STOP WATCH via reconcile.py fracwatch after the rest of the tick"})
        elif not so:
            actions.append({"type": "rest_stop", "symbol": sym, "qty": qty, "stop": lock_stop, "limit": hard_limit(entry, lock_stop) if lock_stop else None,
                            "note": "fractional: follow FRACTIONAL PROTECTION ORDER" if frac else "no resting sell at broker"})
        elif covered + 1e-6 < qty:
            actions.append({"type": "resize_protection", "symbol": sym, "qty": qty, "covered": covered, "orderIds": [o["id"] for o in so]})
        if "limit" in kinds and any(k.startswith("stop") for k in kinds):
            actions.append({"type": "resolve_both", "symbol": sym, "orderIds": [o["id"] for o in so], "rule": "keep TP only if bid ≥ targetTP×0.995"})
        for o in so:
            if kind(o) == "stop_limit" and lock_stop and f(o.get("stop_price")) + 1e-9 < lock_stop - tick(lock_stop) / 2:
                actions.append({"type": "raise_stop", "symbol": sym, "orderId": o["id"], "stop": f(o.get("stop_price")), "lockStop": lock_stop,
                                "why": "resting stop is looser than the hard stop (trigger −4.5%, limit −5%; locked)"})
        # GAP GUARD
        q = quotes.get(sym)
        if q:
            bid = f(q.get("bid_price")); bt = pt(q.get("venue_bid_time")); age = (now - bt).total_seconds() if bt else None
            stops = [o for o in so if kind(o) in ("stop_limit", "stop_market")]
            st_px = f(stops[0].get("stop_price")) if stops else ((mine[0].get("trailStop") or mine[0].get("stop")) if mine else lock_stop)
            st_px = f(st_px)
            ev = None
            if bid <= 0: ev = {"level": "recheck", "why": "no bid"}
            elif age is not None and age > max_q_age:
                if bid <= st_px * 1.005: ev = {"level": "recheck", "why": f"quote {int(age)} s old; re-quote before acting"}
            elif stops and bid <= st_px:
                o = stops[0]; lim = f(o.get("price"), None)
                if kind(o) == "stop_limit" and lim is not None and bid < lim:
                    ev = {"level": "escalate_now", "why": "gap_through_limit", "orderId": o["id"], "stop": st_px, "limit": lim}
                else:
                    first = (gg.get(o["id"]) or {}).get("firstSeenAt"); gg_new[o["id"]] = {"symbol": sym, "firstSeenAt": first or iso(now), "bid": bid}
                    if first and (now - pt(first)).total_seconds() >= grace:
                        ev = {"level": "escalate_now", "why": "stop_breached_unfilled", "orderId": o["id"], "stop": st_px, "limit": lim, "firstSeenAt": first}
                    else: ev = {"level": "recheck", "why": f"bid {bid} ≤ stop {st_px}, order still open: single-order read + re-quote in ~{int(grace)} s, then sync again", "orderId": o["id"]}
            elif not stops and st_px and bid <= st_px:
                ev = {"level": "escalate_now", "why": "unprotected_below_stop", "stop": st_px}
            elif st_px and bid <= st_px * 1.005: ev = {"level": "watch", "why": f"bid {bid} within 0.5% of stop {st_px}"}
            if ev:
                ev.update({"symbol": sym, "bid": bid, "qty": qty})
                if ev["level"] == "escalate_now":
                    ev.update({"type": "gap_escalate", "steps": "cancel every open sell for the symbol → verify cancelled (filled ⇒ re-sync, stop) → sell",
                               "sell": ({"type": "market", "quantity": str(qty)} if frac else {"type": "limit", "quantity": str(int(round(qty))), "limit_price": down(bid * 0.97)}),
                               "retryAfterS": 15, "retryLimit": None if frac else down(bid * 0.94), "reason": "stop_aggressive"})
                else: ev["type"] = "gap_" + ev["level"]
                actions.append(ev)
    for o in open_orders:
        if o["side"] == "buy":
            age = (now - pt(o["created_at"])).total_seconds()
            if age > 120: actions.append({"type": "cancel_stale_buy", "symbol": o["symbol"], "orderId": o["id"], "ageS": int(age)})
    for sym, so in sells_open.items():
        if sym not in positions: actions.append({"type": "cancel_orphan_sell", "symbol": sym, "orderIds": [o["id"] for o in so]})
    PR = protection(state, positions, orders)
    for w in PR["wrongType"]:
        actions.insert(0, {"type": "replace_wrong_type", "symbol": w["symbol"], "orderIds": w["orderIds"],
                           "steps": "lock S → cancel these non-stop sells → verify cancelled (filled ⇒ re-sync) → place the stop-limit via stopargs → verify-protection"})
    bad_closed = [i for i, r in enumerate(state.get("closed") or []) if r.get("exitPrice") is None or r.get("pnlUsd") is None]
    realized = round(sum(r["pnlUsd"] for r in rts), 4)
    return {"now": iso(now), "routine": routine, "brokerPositions": {k: f(v.get("quantity")) for k, v in positions.items()},
            "openOrders": [{"id": o["id"], "symbol": o["symbol"], "side": o["side"], "kind": kind(o), "stop": f(o.get("stop_price"), None),
                            "limit": f(o.get("price"), None), "qty": f(o.get("quantity")), "state": o.get("state")} for o in open_orders],
            "buyFillsToday": len(lots), "roundTripsBroker": len(rts), "addRoundTrips": add_rts, "adopt": adopt, "drop": drop, "fixes": fixes,
            "actions": actions, "realizedPnlUsdBroker": realized, "realizedPnlUsdState": state.get("realizedPnlUsd"),
            "realizedDiff": round(realized - f(state.get("realizedPnlUsd")), 4), "dataQuality": {"closedRowsMissingExit": bad_closed, "warnings": warn},
            "gapGuard": gg_new, "protection": PR, "buysAllowed": PR["buysAllowed"], "_rts": rts}

DESK_BUY_SOURCES = {"entries", "entries_backup", "recycle", "manage-a", "manage-b", "desk"}
def adopt_row(sym, qty, entry, at, buy_id, so, q, desk_source=None):
    stop = up(entry * HARD_TRIGGER) if entry else None
    stops = [o for o in so if kind(o).startswith("stop")]; tps = [o for o in so if kind(o) == "limit"]
    bid = f((q or {}).get("bid_price"))
    mode = "tp" if tps else ("trail" if stops and f(stops[0].get("stop_price")) >= entry else "stop")
    return {"symbol": sym, "qty": qty, "entryPrice": entry, "entryAt": iso(at), "stop": stop, "targetTP": up(entry * 1.02) if entry else None,
            "tp": up(entry * 1.02) if entry else None, "tpReasoning": "fallback_floor: " + ("recorded" if desk_source else "adopted") + " by reconcile.py (fill × 1.02 rounded up; buyer annotates tp_model target)",
            "trailStop": f(stops[0].get("stop_price")) if mode == "trail" else None, "hw": max(entry or 0, bid), "source": desk_source or "adopted", "deskBuy": bool(desk_source),
            "buyOrderId": buy_id, "stopLimitOrderId": stops[0]["id"] if stops else None, "tpOrderId": tps[0]["id"] if tps else None,
            "restingMode": mode, "catalystScore": 0, "adoptedBy": "reconcile.py"}

ACCOUNT = _broker_account(required=False)
def is_whole(q): return abs(f(q) - round(f(q))) <= 1e-6
def check_stop_args(k):
    """Validate kwargs for a PROTECTIVE stop order. Returns (ok, why, fixed_kwargs)."""
    why = []
    k = dict(k or {})
    if str(k.get("account_number")) != ACCOUNT: why.append("account_number must equal BROKER_ACCOUNT_NUMBER")
    if k.get("side") != "sell": why.append("side must be sell")
    if k.get("type") != "stop_limit": why.append(f"type must be 'stop_limit' (got {k.get('type')!r}); a stop_price without type stop_limit is sent as a PLAIN LIMIT and fills at once")
    sp_, lp = f(k.get("stop_price"), 0), f(k.get("limit_price"), 0)
    if sp_ <= 0: why.append("stop_price required (> 0)")
    if lp <= 0: why.append("limit_price required (> 0)")
    if sp_ > 0 and lp > 0 and not (sp_ * 0.90 - 1e-9 <= lp < sp_): why.append("limit_price must be below stop_price and ≥ stop × 0.90 (desk: stop × 0.97 rounded down)")
    q = f(k.get("quantity"), 0)
    if q <= 0 or not is_whole(q): why.append("quantity must be a whole positive share count (fractional lots use the 1-minute watch, never a broker stop)")
    if "dollar_amount" in k: why.append("dollar_amount not allowed on a stop")
    if (k.get("market_hours") or "regular_hours") != "regular_hours": why.append("market_hours must be regular_hours")
    if (k.get("time_in_force") or "gfd") not in ("gfd", "gtc"): why.append("time_in_force must be gfd")
    fixed = dict(k); fixed.update({"account_number": ACCOUNT, "side": "sell", "type": "stop_limit", "market_hours": "regular_hours", "time_in_force": k.get("time_in_force") or "gfd"})
    if sp_ > 0:
        fixed["stop_price"] = str(sp_)
        if not (sp_ * 0.90 - 1e-9 <= lp < sp_): fixed["limit_price"] = str(down(sp_ * 0.97))
    fixed.pop("dollar_amount", None)
    return (not why), why, fixed

def protection(state, positions, orders):
    """BROKER TRUTH protection map. positions = load_positions(); orders = load_orders()."""
    sells = {}
    for o in orders:
        if o.get("state") in OPEN and o.get("side") == "sell": sells.setdefault(o["symbol"], []).append(o)
    sp = {p["symbol"]: p for p in (state.get("positions") or [])}
    unprot, wrong, frac, ok = [], [], [], []
    for sym, bp in positions.items():
        qty = f(bp.get("quantity"))
        if not is_whole(qty): frac.append(sym); continue
        entry = f((sp.get(sym) or {}).get("entryPrice")) or f(bp.get("average_buy_price"))
        so = sells.get(sym, [])
        stops = [o for o in so if kind(o) == "stop_limit"]
        tps = [o for o in so if kind(o) == "limit" and entry and f(o.get("price")) >= entry * 1.02 * 0.999]
        bad = [o for o in so if kind(o) in ("limit", "market") and o not in tps]
        cover = sum(f(o.get("quantity")) - f(o.get("cumulative_quantity")) for o in stops + tps)
        if bad: wrong.append({"symbol": sym, "orderIds": [o["id"] for o in bad], "kinds": [kind(o) for o in bad], "why": "plain limit/market sell is not a stop"})
        if cover + 1e-6 >= qty and stops + tps: ok.append(sym)
        else: unprot.append({"symbol": sym, "qty": qty, "covered": cover, "entry": entry})
    return {"protected": ok, "unprotected": unprot, "wrongType": wrong, "fractionalWatched": frac,
            "buysAllowed": not unprot and not wrong}

HARD_TRIGGER = 0.955; HARD_LIMIT = 0.95   # resting hard stop: trigger entry×0.955, limit entry×0.95 (Kevin 2026-11-10 16:28 ET); −2% is a recovery DECISION point, not a resting stop
def hard_limit(entry, stop):
    lim = up(f(entry) * HARD_LIMIT) if entry else down(stop * 0.97)
    return lim if lim < stop else down(stop * 0.97)
MAX_TRADE_LOSS_PCT = 5.0   # HARD FLOOR (Kevin 2026-11-10 16:25 ET "Add 5% loss rule on individual trades") — never configurable wider
def cap_stop_to_entry(k, entry, ok, why, fixed):
    """Per-trade 5% cap: stop_price AND limit_price must be ≥ entry × 0.95 (a stop may never be set wider than −5%)."""
    e = f(entry, 0)
    if e <= 0: return ok, why, fixed
    floor = up(e * (1 - MAX_TRADE_LOSS_PCT / 100))
    sp_, lp = f(k.get("stop_price"), 0), f(k.get("limit_price"), 0)
    if sp_ and sp_ < floor - 1e-9: why.append(f"stop_price {sp_} is wider than the −5% per-trade cap (entry {e} → min {floor})")
    if lp and lp < floor - 1e-9: why.append(f"limit_price {lp} is below the −5% per-trade cap (entry {e} → min {floor})")
    if sp_ and (sp_ < floor - 1e-9 or lp < floor - 1e-9):
        ns = max(f(fixed.get("stop_price"), 0), up(e * HARD_TRIGGER) if sp_ < floor - 1e-9 else sp_)
        fixed["stop_price"] = str(ns); fixed["limit_price"] = str(max(floor, down(ns * 0.97)))
        if f(fixed["limit_price"]) >= ns: fixed["limit_price"] = str(floor)
    return (not why), why, fixed

def cmd_stopargs(a):
    try: k = json.loads(a.json)
    except Exception as e: print(json.dumps({"ok": False, "why": [f"bad JSON: {e}"]})); return 4
    entry = a.entry or k.pop("entry", None); k.pop("entry", None)
    ok, why, fixed = check_stop_args(k)
    ok, why, fixed = cap_stop_to_entry(k, entry, ok, why, fixed)
    out = {"ok": ok, "why": why}
    if not ok: out["fixed"] = fixed; out["next"] = "DO NOT send the original order; send `fixed` (re-run stopargs on it first)"
    else: out["next"] = "send exactly these kwargs, then verify-protection with a fresh broker read (resting order must show trigger stop + type limit)"
    print(json.dumps(out)); return 0 if ok else 4

def cmd_verify_protection(a):
    now = now_of(a)
    positions = load_positions(a.positions); orders = load_orders(a.orders)
    st = json.load(open(a.state)) if a.state else {}
    pr = protection(st, positions, orders); pr["at"] = iso(now); pr["routine"] = a.routine
    if a.state and a.apply:
        with Locked(a.state):
            st = json.load(open(a.state)); st["protection"] = pr
            journal_heal(st, a.state); write_json(a.state, st)
        pr["applied"] = True
    print(json.dumps(pr)); return 0 if pr["buysAllowed"] else 7

def journal_path(state_path): return state_path + ".rtjournal.jsonl"
def journal_append(state_path, rows):
    if not rows: return
    with open(journal_path(state_path), "a") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
def journal_heal(st, state_path):
    """Restore round trips of st.sessionDate that the journal has but the state lost (append-only ledger). Returns restored count."""
    D = st.get("sessionDate"); jp = journal_path(state_path)
    if not D or not _os.path.exists(jp): return 0
    have = {r.get("rtKey") for r in st.get("roundTrips") or []}
    add = []
    for line in open(jp):
        try: r = json.loads(line)
        except Exception: continue
        if str(r.get("exitAt", ""))[:10] == D and r.get("rtKey") and r["rtKey"] not in have: add.append(r); have.add(r["rtKey"])
    if add:
        st.setdefault("roundTrips", []).extend(add); st.setdefault("closed", []).extend(dict(x) for x in add)
        st["roundTrips"].sort(key=lambda r: r.get("exitAt") or "")
        st["realizedPnlUsd"] = round(sum(f(r.get("pnlUsd")) for r in st["roundTrips"]), 4)
        st["roundTripCount"] = max(int(f(st.get("roundTripCount"))), len(st["roundTrips"]))
        st.setdefault("errorsAutoFixed", []).append({"at": iso(datetime.now(ET)), "routine": "reconcile.py", "what": f"{len(add)} round trip(s) missing from state (reset/overwrite)",
                                                      "fix": "restored from the append-only journal", "result": "fixed"})
    return len(add)

class Locked:
    def __init__(self, path): self.p = path + ".lock"
    def __enter__(self):
        self.fh = open(self.p, "a+"); fcntl.flock(self.fh, fcntl.LOCK_EX); return self
    def __exit__(self, *a): fcntl.flock(self.fh, fcntl.LOCK_UN); self.fh.close()
def write_json(p, obj):
    tmp = f"{p}.tmp.{_os.getpid()}"; json.dump(obj, open(tmp, "w"), indent=1); json.load(open(tmp)); _os.replace(tmp, p)

def now_of(a):
    if not a.now: return datetime.now(ET)
    d = datetime.fromisoformat(a.now); return d.astimezone(ET) if d.tzinfo else d.replace(tzinfo=ET)

def cmd_sync(a):
    now = now_of(a); C = cfg()
    positions = load_positions(a.positions); orders = load_orders(a.orders); quotes = load_quotes(a.quotes)
    st = json.load(open(a.state))
    P = plan(st, positions, orders, quotes, now, a.routine)
    applied, why_not = False, None
    if a.apply:
        eff = C.get("applyFrom", "9999-12-31")
        age = max(time.time() - _os.path.getmtime(p) for p in [a.positions] + a.orders)
        if now.strftime("%Y-%m-%d") < eff and not a.force: why_not = f"apply_not_effective_until {eff} (plan only)"
        elif age > (a.max_age_s if a.max_age_s is not None else f(C.get("maxSnapshotAgeSeconds"), 90)): why_not = f"stale_snapshot: broker files are {int(age)} s old; re-read positions + orders, then sync again"
        elif snapshot_incomplete(st, orders, positions, now): why_not = snapshot_incomplete(st, orders, positions, now)
        else:
            with Locked(a.state):
                st = json.load(open(a.state))           # re-read INSIDE the lock: never write from a stale copy
                P = plan(st, positions, orders, quotes, now, a.routine)
                journal_heal(st, a.state)
                apply_plan(st, P, now, a.routine); journal_append(a.state, st.pop("_journal_new", [])); write_json(a.state, st); applied = True
    out = {k: v for k, v in P.items() if not k.startswith("_")}; out["applied"] = applied
    if why_not: out["applyRefused"] = why_not
    print(json.dumps(out, indent=1, default=str))
    esc = [x for x in P["actions"] if x["type"] == "gap_escalate"]
    print(json.dumps({"summary": True, "applied": applied, "addRoundTrips": len(P["addRoundTrips"]), "adopt": len(P["adopt"]), "drop": len(P["drop"]),
                      "actions": [x["type"] + ":" + x.get("symbol", "") for x in P["actions"]], "escalateNow": [x["symbol"] for x in esc],
                      "realizedPnlUsdBroker": P["realizedPnlUsdBroker"], "refused": why_not}))
    return 0

def snapshot_incomplete(st, orders, positions, now):
    """APPEND-ONLY guard (2026-11-10 12:48: a sync on an empty placeholder orders file zeroed realizedPnlUsd). Refuse --apply when the
    orders snapshot cannot be today's full broker list: it is empty while state holds today's round trips / desk lots, or it lacks an
    exit order id already recorded today."""
    D = now.strftime("%Y-%m-%d")
    if st.get("sessionDate") not in (None, D): return None
    ids = {o.get("id") for o in orders}
    today_rts = [r for r in st.get("roundTrips") or [] if str(r.get("exitAt", ""))[:10] == D and r.get("exitOrderId")]
    lots = [p for p in st.get("positions") or [] if p.get("buyOrderId")]
    if not orders and (today_rts or lots or positions):
        return "empty_orders_snapshot: the orders file has 0 orders but today already has fills/positions; re-read get_equity_orders (every page) and sync again (ledger is append-only)"
    miss = [r["exitOrderId"][:8] for r in today_rts if r["exitOrderId"] not in ids]
    if miss: return f"orders_snapshot_incomplete: recorded exit orders {miss} are missing from the snapshot; read every page and sync again"
    return None

def apply_plan(st, P, now, routine):
    at = iso(now); tag_of = {}
    for p in st.get("positions") or []:
        if p.get("buyOrderId"): tag_of[p["buyOrderId"]] = p
    by_sym_nobid = {p["symbol"]: p for p in st.get("positions") or [] if not p.get("buyOrderId")}
    st.setdefault("roundTrips", []); st.setdefault("closed", []); st.setdefault("errorsAutoFixed", []); st.setdefault("adopted", [])
    _new_rows = []
    for rt in P["addRoundTrips"]:
        src = tag_of.get(rt["buyOrderId"]) or by_sym_nobid.get(rt["symbol"]) or {}
        row = dict(rt)
        for k in ("tag", "source", "targetTP", "catalystScore", "hw", "trailStop"):
            if src.get(k) is not None and row.get(k) is None: row[k] = src[k]
        if src.get("hw") and rt["entryPrice"]: row["hwPct"] = round((f(src["hw"]) / rt["entryPrice"] - 1) * 100, 3)
        row["reconciledBy"] = f"reconcile.py/{routine}"; row["reconciledAt"] = at
        lag = (now - pt(rt["exitAt"])).total_seconds(); row["recordLagS"] = round(lag)
        st["roundTrips"].append(row); st["closed"].append(dict(row)); _new_rows.append(row)
        # A fill recorded by the next tick is the NORMAL path (not an error). Only a fill that sat unrecorded longer than
        # config reconcile.stateLagSeconds (default 360 s ≈ one missed tick) is a STATE-LAG incident (scorecard metric).
        if lag > f(cfg().get("stateLagSeconds"), 360):
            st.setdefault("stateLagIncidents", []).append({"at": at, "routine": routine, "symbol": rt["symbol"], "exitAt": rt["exitAt"], "lagS": round(lag), "orderId": rt["exitOrderId"]})
            st["errorsAutoFixed"].append({"at": at, "routine": routine, "what": f"state lag: {rt['symbol']} {rt['reason']} fill {rt['exitAt']} @{rt['exitPrice']} unrecorded for {round(lag)} s",
                                          "fix": f"reconcile.py: round trip recorded by order id {rt['exitOrderId'][:8]}", "result": "fixed"})
    drop_keys = {(d["symbol"], d["buyOrderId"]) for d in P["drop"]}
    st["positions"] = [p for p in st.get("positions") or [] if (p["symbol"], p.get("buyOrderId")) not in drop_keys]
    have = {p.get("buyOrderId") for p in st["positions"] if p.get("buyOrderId")}
    for a_ in P["adopt"]:
        if a_["buyOrderId"] and a_["buyOrderId"] in have: continue
        st["positions"].append(dict(a_))
        if a_.get("deskBuy"): continue   # the desk's own buy (logged via `reason --reason <entries|recycle|…>` or orders[]): recorded, not an error
        st["adopted"].append({"at": at, "routine": routine, "symbol": a_["symbol"], "qty": a_["qty"], "entry": a_["entryPrice"], "buyOrderId": a_["buyOrderId"], "by": "reconcile.py"})
        st["errorsAutoFixed"].append({"at": at, "routine": routine, "what": f"{a_['symbol']} {a_['qty']} sh held at broker but missing from state.positions",
                                      "fix": f"reconcile.py adopted lot {str(a_['buyOrderId'])[:8]} (stop {a_['stop']}, resting {a_['restingMode']})", "result": "fixed"})
    oo = {o["symbol"]: [] for o in P["openOrders"]}
    for o in P["openOrders"]: oo[o["symbol"]].append(o)
    for p in st["positions"]:
        bq = P["brokerPositions"].get(p["symbol"])
        same = [x for x in st["positions"] if x["symbol"] == p["symbol"]]
        if bq is not None and len(same) == 1 and abs(f(p.get("qty")) - bq) > 1e-6: p["qty"] = bq
        sells = [o for o in oo.get(p["symbol"], []) if o["side"] == "sell"]
        stops = [o for o in sells if o["kind"].startswith("stop")]; tps = [o for o in sells if o["kind"] == "limit"]
        if stops: p["stopLimitOrderId"] = stops[0]["id"]
        if tps: p["tpOrderId"] = tps[0]["id"]
        if not tps and p.get("tpOrderId"): p["tpOrderId"] = None
        if not stops and p.get("stopLimitOrderId"): p["stopLimitOrderId"] = None
    # APPEND-ONLY LEDGER (2026-11-10): realized = Σ recorded round trips (never replaced by a smaller broker snapshot); count never drops
    st["realizedPnlUsd"] = round(sum(f(r.get("pnlUsd")) for r in st["roundTrips"]), 4)
    st["roundTripCount"] = max(int(f(st.get("roundTripCount"))), P["buyFillsToday"])
    if abs(f(P["realizedPnlUsdBroker"]) - st["realizedPnlUsd"]) > 0.01:
        st.setdefault("reconcileWarnings", []).append({"at": at, "routine": routine, "what": f"broker-ledger realized {P['realizedPnlUsdBroker']} ≠ state Σ roundTrips {st['realizedPnlUsd']} (state kept; append-only)"})
    st["protection"] = dict(P["protection"], at=at, routine=routine)
    st["_journal_new"] = _new_rows
    st["gapGuard"] = P["gapGuard"]
    st.setdefault("brokerReconcileLog", []).append({"at": at, "routine": routine, "by": "reconcile.py", "livePositions": [f"{k} {v:g}" for k, v in P["brokerPositions"].items()],
        "openOrders": [f"{o['symbol']} {o['kind']} {o['stop'] or ''}/{o['limit'] or ''}" for o in P["openOrders"]],
        "adopted": [x["symbol"] for x in P["adopt"]], "dropped": [d["symbol"] for d in P["drop"]], "addedRoundTrips": [r["rtKey"][:17] for r in P["addRoundTrips"]],
        "actions": [x["type"] + ":" + x.get("symbol", "") for x in P["actions"]]})
    st["reconcileAt"] = at

def cmd_annotate(a):
    meta = json.loads(a.json); banned = {"qty", "buyOrderId", "symbol"}
    with Locked(a.state):
        st = json.load(open(a.state)); hit = None
        for p in st.get("positions") or []:
            if p.get("buyOrderId") == a.buy_order_id: hit = p
        if not hit: print(json.dumps({"ok": False, "why": "no position with that buyOrderId (run sync --apply first)"})); return 1
        for k, v in meta.items():
            if k not in banned: hit[k] = v
        write_json(a.state, st)
    print(json.dumps({"ok": True, "symbol": hit["symbol"], "set": sorted(k for k in meta if k not in banned)})); return 0

def cmd_reason(a):
    with Locked(a.state):
        st = json.load(open(a.state)); st.setdefault("orderReasons", {})[a.order_id] = a.reason; write_json(a.state, st)
    print(json.dumps({"ok": True, "orderId": a.order_id, "reason": a.reason})); return 0

def locks_path(a): return a.locks or _os.path.join(_os.path.dirname(_os.path.abspath(a.state)), "order-locks.json")
def cmd_lock(a):
    p = locks_path(a); deadline = time.time() + max(0.0, a.wait)
    while True:
        with Locked(p):
            L = {}
            try: L = json.load(open(p))
            except (FileNotFoundError, json.JSONDecodeError): L = {}
            now = time.time(); cur = L.get(a.symbol)
            if cur and cur["expires"] > now and cur["owner"] != a.routine:
                busy = cur
            else:
                L[a.symbol] = {"owner": a.routine, "since": cur["since"] if cur and cur["owner"] == a.routine and cur["expires"] > now else now,
                               "expires": now + a.ttl, "at": iso(datetime.now(ET)), "purpose": a.purpose}
                L = {k: v for k, v in L.items() if v["expires"] > now}; write_json(p, L)
                print(json.dumps({"ok": True, "symbol": a.symbol, "owner": a.routine, "expiresInS": a.ttl,
                                  "next": "re-read this symbol's orders + position NOW and decide from that fresh read; unlock when the new order verifies open"}))
                return 0
        if time.time() >= deadline:
            print(json.dumps({"ok": False, "symbol": a.symbol, "heldBy": busy["owner"], "purpose": busy.get("purpose"), "since": busy.get("at"),
                              "expiresInS": round(busy["expires"] - time.time(), 1), "next": "place/cancel NOTHING for this symbol this tick; re-read next tick"}))
            return 3
        time.sleep(min(2.0, max(0.05, deadline - time.time())))
def cmd_unlock(a):
    p = locks_path(a)
    with Locked(p):
        try: L = json.load(open(p))
        except (FileNotFoundError, json.JSONDecodeError): L = {}
        cur = L.get(a.symbol)
        if cur and cur["owner"] != a.routine and cur["expires"] > time.time():
            print(json.dumps({"ok": False, "why": f"held by {cur['owner']}"})); return 3
        L.pop(a.symbol, None); write_json(p, L)
    print(json.dumps({"ok": True, "symbol": a.symbol, "released": True})); return 0

def cmd_fracwatch(a):
    """One FRACTIONAL 1-MINUTE STOP WATCH read: decide + log (locked). Never calls the broker."""
    FW = fw_cfg(); C = cfg(); now = now_of(a)
    max_age = f(C.get("maxQuoteAgeSeconds"), 60); interval = f(FW.get("intervalSeconds"), 60); window = f(FW.get("windowSeconds"), 270)
    q = {}
    if a.quotes: q = load_quotes(a.quotes).get(a.symbol) or {}
    bid = f(a.bid) if a.bid is not None else f(q.get("bid_price"))
    bt = pt(a.bid_time) if a.bid_time else (now if a.bid is not None and not q else pt(q.get("venue_bid_time") or q.get("updated_at")))
    age = round((now - bt).total_seconds(), 1) if bt else None
    qstate = q.get("state"); halted = bool(q) and qstate not in (None, "", "active")
    with Locked(a.state):
        st = json.load(open(a.state))
        ps = [p for p in st.get("positions") or [] if p.get("symbol") == a.symbol]
        frac_ps = [p for p in ps if abs(f(p.get("qty")) - round(f(p.get("qty")))) > 1e-6]
        pos = (frac_ps or ps or [None])[0]
        base = f(a.stop, None) if a.stop is not None else (f(pos.get("stop"), None) if pos else None)
        trail = f(pos.get("trailStop"), None) if pos and a.stop is None else None
        stop = max(base, trail) if (base is not None and trail is not None) else (base if base is not None else trail)
        tp = f(a.tp, None) if a.tp is not None else (f(pos.get("targetTP") or pos.get("tp"), None) if pos else None)
        reason = None
        if a.action: action = a.action
        elif pos is None and stop is None: action = "no_position"
        elif bid <= 0: action = "requote"
        elif age is None or age > max_age: action = "requote"
        elif halted: action = "halted"
        elif stop is not None and bid <= stop:
            action = "sell_stop"; reason = "virtual_trail_market" if (trail is not None and base is not None and trail > base) else "virtual_stop_market"
        elif tp is not None and bid >= tp: action = "sell_tp"; reason = "virtual_tp_market"
        else: action = "hold"
        ts = pt(a.tick_start) if a.tick_start else None
        win_end = ts.timestamp() + window if ts else None
        nowt = now.timestamp()
        flatten_now = now.strftime("%H:%M") >= "15:45"
        cont = bool(FW["enabled"]) and action in ("hold", "requote", "halted", "skipped_lock_busy") and win_end is not None \
            and nowt + min(interval, 5.0) <= win_end and not flatten_now
        nxt = 0 if not cont else (0 if action == "requote" else int(max(5, min(interval, win_end - nowt))))
        row = {"at": iso(now), "routine": a.routine, "symbol": a.symbol, "bid": bid if bid > 0 else None, "stop": stop, "tp": tp, "action": action,
               "bidTime": iso(bt), "bidAgeS": age, "tickStart": iso(ts)}
        if reason: row["reason"] = reason
        if a.order_id: row["orderId"] = a.order_id
        if a.note: row["note"] = a.note
        fwst = st.get("fractionalWatch")
        if not isinstance(fwst, dict): fwst = {}
        fwst.setdefault("reads", []).append(row); fwst.setdefault("last", {})[a.symbol] = row
        fwst["config"] = {k: FW[k] for k in ("enabled", "intervalSeconds", "windowSeconds", "retryBrokerStop")}
        st["fractionalWatch"] = fwst
        n_tick = sum(1 for r in fwst["reads"] if r.get("symbol") == a.symbol and r.get("routine") == a.routine and r.get("tickStart") == row["tickStart"])
        if pos is not None and action not in ("requote",) and bid > 0:
            prev = pt(pos.get("lastWatchedAt"))
            if prev: pos["maxWatchGapS"] = max(f(pos.get("maxWatchGapS")), round((now - prev).total_seconds()))
            pos["lastWatchedAt"] = iso(now)
        write_json(a.state, st)
    out = {"ok": True, "symbol": a.symbol, "action": action, "reason": reason, "bid": row["bid"], "stop": stop, "tp": tp, "bidAgeS": age,
           "continueWatch": cont, "nextReadInS": nxt, "windowEndsAt": iso(datetime.fromtimestamp(win_end, ET)) if win_end else None,
           "readsThisTick": n_tick, "watchEnabled": bool(FW["enabled"]), "flattenNow": flatten_now}
    out["next"] = {"sell_stop": "lock S → re-read position → market-sell FULL qty → reason → verify → fracwatch --action sold_stop → unlock → sync --apply",
                   "sell_tp": "lock S → re-read position → market-sell FULL qty → reason virtual_tp_market → verify → fracwatch --action sold_tp → unlock → sync --apply",
                   "requote": "quote is stale or has no bid: get_equity_quotes again now and re-run fracwatch (never sell on a stale quote)",
                   "halted": "quote not active: place nothing; next read",
                   "no_position": "state has no position for S: run sync --apply with fresh positions; if the broker still holds S re-run with --stop/--tp, else end the watch",
                   "hold": "sleep nextReadInS (one shell call), then the next read" if cont else "window over: end the watch"}.get(action, "logged")
    if not FW["enabled"]: out["note"] = "config fractionalWatch.enabled is false: read logged, no watch loop"
    if not ts: out["note"] = "no --tick-start: continueWatch is false (pass the tick's STEP 0 time)"
    print(json.dumps(out)); return 0

OWNED = ("positions", "closed", "roundTrips", "realizedPnlUsd", "roundTripCount", "orderReasons", "gapGuard", "fractionalWatch")
SW_OPS = ("set", "merge", "append", "increment", "position", "claim", "release")
def _path(p): return [k for k in str(p).split(".") if k]
def _get(st, path):
    cur = st
    for k in _path(path):
        if not isinstance(cur, dict) or k not in cur: return None
        cur = cur[k]
    return cur
def _put(st, path, val):
    ks = _path(path); cur = st
    for k in ks[:-1]:
        if not isinstance(cur.get(k), dict): cur[k] = {}
        cur = cur[k]
    cur[ks[-1]] = val
def cmd_statewrite(a):
    now = now_of(a)
    if a.replace:
        new = json.load(open(a.replace))
        with Locked(a.state):
            try: cur = json.load(open(a.state))
            except (FileNotFoundError, json.JSONDecodeError): cur = {}
            if cur.get("sessionDate") and cur.get("sessionDate") == new.get("sessionDate") and not a.force:
                print(json.dumps({"ok": False, "refused": "replace: the state already holds sessionDate " + str(cur.get("sessionDate")) + "; patch it (set/merge/append) or pass --force"})); return 4
            if cur.get("sessionDate") and cur.get("sessionDate") == new.get("sessionDate"):
                # same-day forced replace: the ledger is append-only intraday — carry today's round trips/realized/count over
                for k_ in ("roundTrips", "closed"):
                    have = {r.get("rtKey") for r in new.get(k_) or []}
                    new[k_] = (new.get(k_) or []) + [r for r in cur.get(k_) or [] if r.get("rtKey") not in have]
                new["realizedPnlUsd"] = round(sum(f(r.get("pnlUsd")) for r in new.get("roundTrips") or []), 4)
                new["roundTripCount"] = max(int(f(new.get("roundTripCount"))), int(f(cur.get("roundTripCount"))))
            journal_heal(new, a.state)
            new.setdefault("lastStateWrite", {}); new["lastStateWrite"] = {"at": iso(now), "routine": a.routine, "ops": ["replace"]}
            write_json(a.state, new)
        print(json.dumps({"ok": True, "replaced": True, "sessionDate": new.get("sessionDate")})); return 0
    try: patch = json.load(open(a.patch)) if a.patch else json.loads(a.json or "{}")
    except Exception as e: print(json.dumps({"ok": False, "refused": f"patch is not valid JSON: {e}"})); return 2
    bad = [k for k in patch if k not in SW_OPS]
    if bad: print(json.dumps({"ok": False, "refused": f"unknown op(s) {bad}; allowed {list(SW_OPS)} (never send a whole-state copy)"})); return 4
    owned = []
    for op in ("set", "merge", "append", "increment"):
        for path in (patch.get(op) or {}):
            if _path(path) and _path(path)[0] in OWNED: owned.append(f"{op}:{path}")
    for op in ("claim", "release"):
        if patch.get(op) and _path(patch[op].get("key", ""))[:1] and _path(patch[op]["key"])[0] in OWNED: owned.append(f"{op}:{patch[op]['key']}")
    if owned:
        print(json.dumps({"ok": False, "refused": f"{owned}: owned by reconcile.py sync/annotate/reason/fracwatch (positions → the 'position' op); nothing written"})); return 4
    with Locked(a.state):
        st = json.load(open(a.state))                 # re-read INSIDE the lock: rows another routine wrote a moment ago are kept
        applied, warn = [], []
        c = patch.get("claim")
        if c:
            key = c.get("key", "buyLock"); curv = _get(st, key); stale = f(c.get("staleSeconds"), 90)
            if isinstance(curv, dict) and curv.get("by") not in (None, a.routine) and curv.get("at") and (now - pt(curv["at"])).total_seconds() < stale:
                print(json.dumps({"ok": False, "busy": True, "key": key, "heldBy": curv.get("by"), "since": curv.get("at"), "next": "do not buy this run; nothing written"})); return 3
            _put(st, key, {"by": a.routine, "at": iso(now)}); applied.append(f"claim:{key}")
        for path, v in (patch.get("set") or {}).items(): _put(st, path, v); applied.append(f"set:{path}")
        for path, v in (patch.get("merge") or {}).items():
            base = _get(st, path); base = dict(base) if isinstance(base, dict) else {}
            base.update(v or {}); _put(st, path, base); applied.append(f"merge:{path}")
        for path, n in (patch.get("increment") or {}).items():
            _put(st, path, round(f(_get(st, path)) + f(n), 6) if isinstance(n, float) else int(f(_get(st, path))) + int(n)); applied.append(f"increment:{path}")
        for path, rows in (patch.get("append") or {}).items():
            lst = _get(st, path); lst = list(lst) if isinstance(lst, list) else []
            k = 0
            for r in rows if isinstance(rows, list) else [rows]:
                if r not in lst: lst.append(r); k += 1
            _put(st, path, lst); applied.append(f"append:{path}+{k}")
        banned = {"qty", "buyOrderId", "symbol"}
        for ent in patch.get("position") or []:
            ps = [p for p in st.get("positions") or [] if p.get("symbol") == ent.get("symbol") and (not ent.get("buyOrderId") or p.get("buyOrderId") == ent["buyOrderId"])]
            if not ps: warn.append(f"position {ent.get('symbol')} {ent.get('buyOrderId') or ''} not in state (closed/dropped by sync?): fields skipped"); continue
            if len(ps) > 1:
                print(json.dumps({"ok": False, "refused": f"position {ent.get('symbol')}: {len(ps)} lots; pass buyOrderId; nothing written"})); return 4
            for k_, v in (ent.get("fields") or {}).items():
                if k_ not in banned: ps[0][k_] = v
            applied.append(f"position:{ent.get('symbol')}")
        r_ = patch.get("release")
        if r_:
            key = r_.get("key", "buyLock"); curv = _get(st, key)
            if curv is None or not isinstance(curv, dict) or curv.get("by") in (None, a.routine): _put(st, key, None); applied.append(f"release:{key}")
            else: warn.append(f"release {key}: held by {curv.get('by')}, left as is")
        healed = journal_heal(st, a.state)
        if healed: applied.append(f"journal_heal+{healed}")
        st["lastStateWrite"] = {"at": iso(now), "routine": a.routine, "ops": applied}
        write_json(a.state, st)
        kept = len(((st.get("fractionalWatch") or {}).get("reads")) or [])
    out = {"ok": True, "applied": applied, "fractionalWatchReadsKept": kept}
    if warn: out["warnings"] = warn
    print(json.dumps(out)); return 0

ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
x = sp.add_parser("sync"); x.add_argument("--state", required=True); x.add_argument("--positions", required=True)
x.add_argument("--orders", action="append", required=True); x.add_argument("--quotes"); x.add_argument("--routine", default="manage")
x.add_argument("--now"); x.add_argument("--apply", action="store_true"); x.add_argument("--force", action="store_true")
x.add_argument("--max-age-s", type=float, default=None); x.set_defaults(fn=cmd_sync)
y = sp.add_parser("annotate"); y.add_argument("--state", required=True); y.add_argument("--buy-order-id", required=True); y.add_argument("--json", required=True); y.set_defaults(fn=cmd_annotate)
r_ = sp.add_parser("reason"); r_.add_argument("--state", required=True); r_.add_argument("--order-id", required=True); r_.add_argument("--reason", required=True); r_.set_defaults(fn=cmd_reason)
for nm, fn in (("lock", cmd_lock), ("unlock", cmd_unlock)):
    z = sp.add_parser(nm); z.add_argument("--state", required=True); z.add_argument("--symbol", required=True); z.add_argument("--routine", required=True)
    z.add_argument("--locks"); z.add_argument("--ttl", type=float, default=120.0); z.add_argument("--wait", type=float, default=0.0); z.add_argument("--purpose", default="")
    z.set_defaults(fn=fn)
w_ = sp.add_parser("fracwatch"); w_.add_argument("--state", required=True); w_.add_argument("--symbol", required=True); w_.add_argument("--routine", required=True)
w_.add_argument("--quotes"); w_.add_argument("--bid", type=float); w_.add_argument("--bid-time"); w_.add_argument("--stop", type=float); w_.add_argument("--tp", type=float)
w_.add_argument("--tick-start"); w_.add_argument("--action"); w_.add_argument("--order-id"); w_.add_argument("--note"); w_.add_argument("--now"); w_.set_defaults(fn=cmd_fracwatch)
v_ = sp.add_parser("statewrite"); v_.add_argument("--state", required=True); v_.add_argument("--routine", required=True); v_.add_argument("--patch")
v_.add_argument("--json"); v_.add_argument("--replace"); v_.add_argument("--force", action="store_true"); v_.add_argument("--now"); v_.set_defaults(fn=cmd_statewrite)
q_ = sp.add_parser("stopargs"); q_.add_argument("--json", required=True); q_.add_argument("--entry", help="position average entry price → enforce the −5% per-trade cap"); q_.set_defaults(fn=cmd_stopargs)
u_ = sp.add_parser("verify-protection"); u_.add_argument("--positions", required=True); u_.add_argument("--orders", action="append", required=True)
u_.add_argument("--state"); u_.add_argument("--apply", action="store_true"); u_.add_argument("--routine", default="manage"); u_.add_argument("--now"); u_.set_defaults(fn=cmd_verify_protection)
PREMARKET_DIR = "/workspace/robinhood-fable-agent/data/equity-paper/premarket-paper"
def _premarket_guard(a):
    """PREMARKET PAPER SESSION GUARD (Kevin 2026-11-10 16:05 ET): with env DESK_PAPER_SESSION=1 every write must stay inside the
    premarket paper dir (config premarketPaper.stateDir) — paper can never touch live state. Fail closed (exit 5)."""
    if _os.environ.get("DESK_PAPER_SESSION") != "1": return
    writes = a.cmd in ("annotate", "reason", "lock", "unlock", "fracwatch", "statewrite") or (a.cmd in ("sync", "verify-protection") and getattr(a, "apply", False))
    if not writes: return
    try: d = (json.load(open(CONFIG)).get("premarketPaper") or {}).get("stateDir") or PREMARKET_DIR
    except Exception: d = PREMARKET_DIR
    d = _os.path.realpath(d)
    for p in [getattr(a, "state", None), getattr(a, "locks", None)]:
        if p and not (_os.path.realpath(p) + "/").startswith(d.rstrip("/") + "/"):
            print(json.dumps({"ok": False, "refused": f"PAPER SESSION GUARD: {p} is outside {d}; premarket paper never writes live state"})); sys.exit(5)
def _paper_guard(a):
    """PAPER MODE HARD GUARD (2026-10-23): while config executionMode is paper, refuse any write to LIVE desk data (fail closed)."""
    writes = a.cmd in ("annotate", "reason", "lock", "unlock", "fracwatch", "statewrite") or (a.cmd == "sync" and a.apply)
    if not writes: return
    import importlib.util as _iu
    try:
        sp_ = _iu.spec_from_file_location("paper_guard", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "paper_guard.py"))
        g = _iu.module_from_spec(sp_); sp_.loader.exec_module(g)
    except Exception as e:
        print(json.dumps({"ok": False, "refused": f"paper_guard unavailable ({e}); refusing writes (fail closed)"})); sys.exit(5)
    try: C = json.load(open(CONFIG))
    except Exception: C = {}
    g.assert_writable(a.state, getattr(a, "locks", None) or (locks_path(a) if a.cmd in ("lock", "unlock") else None), C=C)
if __name__ == "__main__":
    a = ap.parse_args(); _premarket_guard(a); _paper_guard(a); sys.exit(a.fn(a))
