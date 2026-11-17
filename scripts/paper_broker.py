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

"""paper_broker.py — SIMULATED Robinhood broker for the Equity AM desk in PAPER MODE (config executionMode="paper", 2026-10-23).

Kevin 2026-10-23: "Rebuild whole system in one routine. Run paper test and debug single routine." PAPER MODE ONLY: no live Robinhood
order of any kind. This script NEVER talks to Robinhood (it has no network code at all). Prices come from LIVE read-only market data the
routine saves to files (get_equity_quotes / get_equity_historicals) and passes in with --quotes / --bars.

Every trading/account tool the desk procedures use has a subcommand with the SAME NAME and the SAME kwargs (as JSON), and prints the
SAME JSON shape the Robinhood MCP returns, so reconcile.py / discretion.py / shadow_orb.py work unchanged on its output:

  python3 /workspace/paper/paper_broker.py <tool> --json '<kwargs>' [--quotes <get_equity_quotes raw>] [--bars <get_equity_historicals raw>] [--now ISO]
     tool ∈ get_accounts | get_portfolio | get_equity_positions | get_equity_orders | review_equity_order | place_equity_order |
            cancel_equity_order | get_realized_pnl | get_pnl_trade_history
  python3 /workspace/paper/paper_broker.py mark --quotes <raw> [--bars <raw>] [--now ISO]   advance fills from market data only
  python3 /workspace/paper/paper_broker.py status                                            one-line book summary
  python3 /workspace/paper/paper_broker.py reset --cash 100.00 --force                        new paper book (keeps a .bak)

--quotes/--bars on ANY subcommand first MARKS the book (fills resting orders against the data) before answering, so pass the fresh
quote file on every order placement and every order poll.

FILL MODEL (conservative, documented in config paperMode.fillModel):
  quote point (bid/ask at its venue time):  buy limit fills at ASK when ask ≤ limit; buy market (qty or dollar_amount) at ask×(1+slip);
     sell limit at BID when bid ≥ limit; sell market at bid×(1−slip); sell stop triggers when bid ≤ stop → stop_market at bid×(1−slip),
     stop_limit at bid if bid ≥ limit else rests TRIGGERED (gap through the limit, like Robinhood).
  1-minute bars (only bars that START at/after the order's creation minute + 1 and END at/before now): buy limit fills when low ≤ limit at
     min(limit, open); sell limit when high ≥ limit at max(limit, open); stop triggers when low ≤ stop at min(stop, open) (gap → open),
     stop_limit fills there only if ≥ limit else rests triggered and fills later at the limit when a bar's high ≥ limit.
  A quote older than paperMode.maxQuoteAgeSeconds (120) never fills anything (order rests until the next mark).
ROBINHOOD RULES ENFORCED (reject like the broker): the live account only; long-only (sell qty ≤ shares_available_for_sells, no shorts);
  fractional qty or dollar_amount only with type=market + regular_hours; market/stop orders only in regular hours 09:30–16:00 ET;
  buys need buying power (cash − open buy reservations); limit_price required for limit/stop_limit, stop_price for stop_*; equities only.
State: config paperMode.brokerFile (default /workspace/robinhood-fable-agent/data/equity-paper/paper-mode/broker.json), flock-guarded,
  atomic writes. Env PAPER_BROKER overrides the file (tests/replays)."""
import os as _os, time as _time
_os.environ["TZ"] = "America/New_York"; _time.tzset()
import argparse, fcntl, json, math, sys, uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CONFIG = _os.environ.get("RECONCILE_CONFIG", "/workspace/robinhood-fable-agent/config/equity-morning-session.json")
ACCOUNT = _broker_account(required=False)
OPEN = {"new", "queued", "confirmed", "unconfirmed", "partially_filled", "pending"}

def f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d
def pm_cfg():
    try: c = json.load(open(CONFIG))
    except Exception: c = {}
    return c.get("paperMode") or {}
def broker_path():
    return _os.environ.get("PAPER_BROKER") or pm_cfg().get("brokerFile") or "/workspace/robinhood-fable-agent/data/equity-paper/paper-mode/broker.json"
def pt(s):
    if not s: return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=ET)).astimezone(ET)
def z(d):  # Robinhood-style UTC timestamp
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
def s6(x): return f"{x:.6f}"
def raw(p):
    t = open(p).read(); i = min([k for k in (t.find("{"), t.find("[")) if k >= 0]); j = max(t.rfind("}"), t.rfind("]"))
    return json.loads(t[i:j + 1])
def is_frac(q): return abs(q - round(q)) > 1e-9
def rth(now):
    # PREMARKET PAPER TEST (Kevin 2026-11-10 16:05 ET; env PAPER_PREMARKET_TEST=1, paper book only): simulate market/stop orders
    # 07:00–16:00 so the premarket paper session exercises the full stop_limit flow. Real Robinhood would queue them; paper fills on quotes.
    if _os.environ.get("PAPER_PREMARKET_TEST") == "1": return now.weekday() < 5 and "07:00" <= now.strftime("%H:%M") < "16:00"
    return now.weekday() < 5 and "09:30" <= now.strftime("%H:%M") < "16:00"

class Locked:
    def __init__(self, p): self.p = p + ".lock"
    def __enter__(self):
        _os.makedirs(_os.path.dirname(self.p) or ".", exist_ok=True)
        self.fh = open(self.p, "a+"); fcntl.flock(self.fh, fcntl.LOCK_EX); return self
    def __exit__(self, *a): fcntl.flock(self.fh, fcntl.LOCK_UN); self.fh.close()

def new_book(cash, now):
    return {"paper": True, "account_number": ACCOUNT, "createdAt": now.isoformat(timespec="seconds"), "startCash": round(cash, 2),
            "cash": round(cash, 2), "orders": [], "positions": {}, "quotes": {}, "realized": [], "events": []}
def load(p, now):
    try: return json.load(open(p))
    except FileNotFoundError:
        return new_book(f(pm_cfg().get("startCashUsd"), 100.0), now)
def save(p, b):
    _os.makedirs(_os.path.dirname(p) or ".", exist_ok=True)
    tmp = f"{p}.tmp.{_os.getpid()}"; json.dump(b, open(tmp, "w"), indent=1); json.load(open(tmp)); _os.replace(tmp, p)

def slip(): return f(pm_cfg().get("marketSlippagePct"), 0.05) / 100.0
def max_q_age(): return f(pm_cfg().get("maxQuoteAgeSeconds"), 120)

# ---------------------------------------------------------------- book mechanics
def pos_of(b, s): return b["positions"].get(s) or {"quantity": 0.0, "avg": 0.0}
def held_for_sells(b, s, skip=None):
    return sum(f(o["quantity"]) - f(o["cumulative_quantity"]) for o in b["orders"]
               if o["symbol"] == s and o["side"] == "sell" and o["state"] in OPEN and o["id"] != skip)
def buy_reserved(b, skip=None):
    tot = 0.0
    for o in b["orders"]:
        if o["side"] != "buy" or o["state"] not in OPEN or o["id"] == skip: continue
        if o.get("dollar_based_amount"): tot += f(o["dollar_based_amount"]["amount"])
        else: tot += f(o.get("price") or o.get("_refPx")) * (f(o["quantity"]) - f(o["cumulative_quantity"]))
    return tot
def buying_power(b): return round(b["cash"] - buy_reserved(b), 2)

def execute(b, o, px, qty, at, how):
    px = round(px, 6); qty = round(qty, 6); s = o["symbol"]; p = pos_of(b, s)
    if o["side"] == "buy":
        nq = p["quantity"] + qty; p["avg"] = (p["avg"] * p["quantity"] + px * qty) / nq if nq > 0 else 0.0; p["quantity"] = round(nq, 6)
        b["cash"] = round(b["cash"] - px * qty, 6)
    else:
        qty = min(qty, p["quantity"])
        pnl = (px - p["avg"]) * qty
        p["quantity"] = round(p["quantity"] - qty, 6); b["cash"] = round(b["cash"] + px * qty, 6)
        b["realized"].append({"at": at.isoformat(timespec="seconds"), "symbol": s, "quantity": qty, "price": px, "avgCost": round(p["avg"], 6),
                              "pnl": round(pnl, 6), "orderId": o["id"]})
    if p["quantity"] <= 1e-9: b["positions"].pop(s, None)
    else: b["positions"][s] = p
    ex = {"id": str(uuid.uuid4()), "price": s6(px), "quantity": s6(qty), "timestamp": z(at), "fees": "0.000000"}
    o.setdefault("executions", []).append(ex)
    cq = f(o["cumulative_quantity"]) + qty; o["cumulative_quantity"] = s6(cq)
    tot = sum(f(e["price"]) * f(e["quantity"]) for e in o["executions"]); o["average_price"] = s6(tot / cq) if cq else None
    o["state"] = "filled" if cq >= f(o["quantity"]) - 1e-9 else "partially_filled"
    o["last_transaction_at"] = z(at); o["updated_at"] = z(at); o["_fillHow"] = how
    b["events"].append({"at": at.isoformat(timespec="seconds"), "ev": "fill", "id": o["id"], "symbol": s, "side": o["side"], "px": px, "qty": qty, "how": how})

def try_quote(b, o, q, now):
    """Fill/trigger one open order against one quote point. Returns True if it filled."""
    if not q: return False
    qt = pt(q.get("venue_bid_time") or q.get("updated_at")) or now
    if (now - qt).total_seconds() > max_q_age() or q.get("state") not in (None, "", "active"): return False
    if qt < pt(o["created_at"]) - timedelta(seconds=max_q_age()): return False
    bid, ask = f(q.get("bid_price")), f(q.get("ask_price"))
    at = max(now, pt(o["created_at"]))
    rem = f(o["quantity"]) - f(o["cumulative_quantity"])
    if o["side"] == "buy":
        if ask <= 0: return False
        if o["type"] == "market":
            px = ask * (1 + slip())
            if o.get("dollar_based_amount") and f(o["quantity"]) <= 0:
                o["quantity"] = s6(math.floor(f(o["dollar_based_amount"]["amount"]) / px * 1e6) / 1e6); rem = f(o["quantity"])
            execute(b, o, px, rem, at, "quote_market"); return True
        if ask <= f(o["price"]): execute(b, o, ask, rem, at, "quote_limit"); return True
        return False
    if bid <= 0: return False
    if o["trigger"] == "stop":
        if not o.get("_triggeredAt"):
            if bid > f(o["stop_price"]): return False
            o["_triggeredAt"] = at.isoformat(timespec="seconds")
        if o["type"] == "market": execute(b, o, bid * (1 - slip()), rem, at, "quote_stop_market"); return True
        if bid >= f(o["price"]): execute(b, o, bid, rem, at, "quote_stop_limit"); return True
        return False
    if o["type"] == "market": execute(b, o, bid * (1 - slip()), rem, at, "quote_market"); return True
    if bid >= f(o["price"]): execute(b, o, bid, rem, at, "quote_limit"); return True
    return False

def try_bar(b, o, bar):
    O, H, L = f(bar["open_price"]), f(bar["high_price"]), f(bar["low_price"])
    at = pt(bar["begins_at"]) + timedelta(seconds=30)
    rem = f(o["quantity"]) - f(o["cumulative_quantity"])
    if o["side"] == "buy":
        if o["type"] == "market":
            px = O * (1 + slip())
            if o.get("dollar_based_amount") and f(o["quantity"]) <= 0:
                o["quantity"] = s6(math.floor(f(o["dollar_based_amount"]["amount"]) / px * 1e6) / 1e6); rem = f(o["quantity"])
            execute(b, o, px, rem, at, "bar_market"); return True
        lim = f(o["price"])
        if L <= lim: execute(b, o, min(lim, O), rem, at, "bar_limit"); return True
        return False
    if o["trigger"] == "stop":
        st, lim = f(o["stop_price"]), f(o.get("price"))
        if not o.get("_triggeredAt"):
            if L > st: return False
            o["_triggeredAt"] = at.isoformat(timespec="seconds"); cand = min(st, O)
            if o["type"] == "market": execute(b, o, cand * (1 - slip()), rem, at, "bar_stop_market"); return True
            if cand >= lim: execute(b, o, cand, rem, at, "bar_stop_limit"); return True
            return False
        if o["type"] == "market": execute(b, o, O * (1 - slip()), rem, at, "bar_stop_market"); return True
        if H >= lim: execute(b, o, max(lim, O), rem, at, "bar_stop_limit_late"); return True
        return False
    if o["type"] == "market": execute(b, o, O * (1 - slip()), rem, at, "bar_market"); return True
    lim = f(o["price"])
    if H >= lim: execute(b, o, max(lim, O), rem, at, "bar_limit"); return True
    return False

def load_quotes(p):
    if not p: return {}
    d = raw(p); d = d.get("data", d); out = {}
    for r in d.get("results", []) if isinstance(d, dict) else d:
        q = r.get("quote", r)
        if q and q.get("symbol"): out[q["symbol"]] = q
    return out
def load_bars(p):
    if not p: return {}
    d = raw(p); d = d.get("data", d); out = {}
    for r in d.get("results", []) if isinstance(d, dict) else d:
        if r.get("symbol"): out[r["symbol"]] = sorted(r.get("bars") or r.get("historicals") or [], key=lambda x: x["begins_at"])
    return out

def mark(b, quotes, bars, now):
    """Advance the book: bars (chronological, per order since creation) then the quote point. Idempotent per bar."""
    for s, q in quotes.items():
        prev = b["quotes"].get(s)
        if not prev or (pt(q.get("venue_bid_time") or q.get("updated_at")) or now) >= (pt(prev.get("venue_bid_time") or prev.get("updated_at")) or now):
            b["quotes"][s] = {k: q.get(k) for k in ("symbol", "bid_price", "ask_price", "last_trade_price", "venue_bid_time", "state", "previous_close")}
    events = []
    # bars first, in time order across all symbols
    rows = []
    for s, bs in bars.items():
        for bar in bs:
            bt = pt(bar["begins_at"])
            if bt + timedelta(seconds=60) <= now + timedelta(seconds=1): rows.append((bt, s, bar))
    rows.sort(key=lambda r: r[0])
    for bt, s, bar in rows:
        for o in b["orders"]:
            if o["symbol"] != s or o["state"] not in OPEN: continue
            c = pt(o["created_at"]); first = c.replace(second=0, microsecond=0) + timedelta(minutes=1)
            done = pt(o.get("_barsThrough")) if o.get("_barsThrough") else None
            if bt < first or (done and bt <= done): continue
            o["_barsThrough"] = bt.isoformat(timespec="seconds")
            if try_bar(b, o, bar): events.append(o["id"])
    for o in b["orders"]:
        if o["state"] in OPEN and try_quote(b, o, b["quotes"].get(o["symbol"]), now): events.append(o["id"])
    # gfd expiry: open orders from a previous ET day are cancelled at the next mark (Robinhood gfd)
    for o in b["orders"]:
        if o["state"] in OPEN and o.get("time_in_force", "gfd") == "gfd" and pt(o["created_at"]).date() < now.date():
            o["state"] = "cancelled"; o["updated_at"] = z(now); o["_cancelledBy"] = "gfd_expiry"
    b["lastMarkAt"] = now.isoformat(timespec="seconds")
    return events

# ---------------------------------------------------------------- tools
def err(msg, code="rejected"): return {"error": {"code": code, "message": msg}, "paper": True}
def validate(b, k, now):
    if str(k.get("account_number")) != ACCOUNT: return f"account_number {k.get('account_number')!r} is not the Agentic account {ACCOUNT} (paper broker refuses)"
    s = (k.get("symbol") or "").upper(); side = k.get("side"); typ = k.get("type")
    if not s or side not in ("buy", "sell"): return "symbol and side buy|sell are required"
    if typ not in ("market", "limit", "stop_market", "stop_limit"): return f"type {typ!r} must be market|limit|stop_market|stop_limit"
    if "-" in s or s.endswith("USD"): return "equities only (no crypto) in this desk"
    qty, dol = k.get("quantity"), k.get("dollar_amount")
    if (qty is None) == (dol is None): return "provide exactly one of quantity or dollar_amount"
    mh = k.get("market_hours", "regular_hours")
    if dol is not None and typ != "market": return "dollar_amount requires type=market"
    if qty is not None and is_frac(f(qty)) and (typ != "market" or mh != "regular_hours"):
        return "Fractional shares are only supported for market orders during regular hours (stop/limit orders on fractional quantities are rejected)"
    if dol is not None and mh != "regular_hours": return "dollar-based orders only in regular_hours"
    if typ in ("market", "stop_market", "stop_limit") and mh != "regular_hours": return f"{typ} orders are regular_hours-only"
    if typ in ("limit", "stop_limit") and f(k.get("limit_price")) <= 0: return "limit_price required"
    if typ in ("stop_market", "stop_limit") and f(k.get("stop_price")) <= 0: return "stop_price required"
    if typ in ("market", "stop_market", "stop_limit") and not rth(now): return "market/stop orders only during regular hours 09:30–16:00 ET (paper broker does not queue them)"
    if side == "sell":
        if dol is not None: return "dollar_amount sells not used by this desk"
        avail = pos_of(b, s)["quantity"] - held_for_sells(b, s)
        if f(qty) > avail + 1e-9: return f"Not enough shares to sell: requested {qty}, available {round(avail, 6)} (long-only, no shorts)"
    else:
        if typ.startswith("stop"): return "buy stop orders are not used by this desk (long-only entries are limit/market)"
        q = b["quotes"].get(s) or {}; ask = f(q.get("ask_price"))
        cost = f(dol) if dol is not None else f(qty) * (f(k.get("limit_price")) if typ == "limit" else ask * (1 + slip()))
        if cost <= 0: return f"no fresh quote for {s} in the paper book: pass --quotes with a get_equity_quotes file"
        if cost > buying_power(b) + 1e-6: return f"Insufficient buying power: needs {cost:.2f}, have {buying_power(b):.2f}"
    return None

def place(b, k, now, dry=False):
    for o in b["orders"]:
        if k.get("ref_id") and o.get("ref_id") == k["ref_id"]: return {"data": {"order": public(o)}, "paper": True, "idempotent": True}
    e = validate(b, k, now)
    if e: return err(e)
    if dry:
        q = b["quotes"].get(k["symbol"].upper()) or {}
        return {"data": {"quote": q, "order_checks": [], "customer_approval_required": False}, "paper": True, "guide": "PAPER review: no alerts"}
    typ = k["type"]; s = k["symbol"].upper()
    o = {"id": str(uuid.uuid4()), "ref_id": k.get("ref_id") or str(uuid.uuid4()), "account_number": ACCOUNT, "symbol": s, "side": k["side"],
         "type": "market" if typ in ("market", "stop_market") else "limit", "trigger": "stop" if typ.startswith("stop") else "immediate",
         "state": "confirmed", "quantity": s6(f(k["quantity"])) if k.get("quantity") is not None else s6(0),
         "cumulative_quantity": s6(0), "price": k.get("limit_price"), "stop_price": k.get("stop_price"), "average_price": None, "fees": "0.000000",
         "dollar_based_amount": {"amount": f"{f(k['dollar_amount']):.6f}", "currency_code": "USD"} if k.get("dollar_amount") is not None else None,
         "time_in_force": k.get("time_in_force", "gfd"), "market_hours": k.get("market_hours", "regular_hours"),
         "placed_agent": "paper", "agent_initiated": True, "paper": True, "created_at": z(now), "updated_at": z(now), "last_transaction_at": z(now), "executions": []}
    if o["side"] == "buy" and typ == "market":
        q = b["quotes"].get(s) or {}; o["_refPx"] = f(q.get("ask_price")) * (1 + slip())
    if o["price"] is not None: o["price"] = s6(f(o["price"]))
    if o["stop_price"] is not None: o["stop_price"] = s6(f(o["stop_price"]))
    b["orders"].append(o); b["events"].append({"at": now.isoformat(timespec="seconds"), "ev": "place", "id": o["id"], "symbol": s, "side": o["side"], "type": typ})
    try_quote(b, o, b["quotes"].get(s), now)
    return {"data": {"order": public(o)}, "paper": True}

def public(o): return {k: v for k, v in o.items() if not k.startswith("_")}

def cancel(b, k, now):
    oid = k.get("order_id")
    for o in b["orders"]:
        if o["id"] == oid:
            if o["state"] not in OPEN: return err(f"Order cannot be cancelled (state {o['state']})", "not_cancellable")
            o["state"] = "cancelled"; o["updated_at"] = z(now); o["last_transaction_at"] = z(now)
            b["events"].append({"at": now.isoformat(timespec="seconds"), "ev": "cancel", "id": oid, "symbol": o["symbol"]})
            return {"data": {"cancelled": True, "order_id": oid}, "paper": True}
    return err(f"order {oid} not found", "not_found")

def orders_view(b, k, now):
    if k.get("account_number") and str(k["account_number"]) != ACCOUNT: return {"data": {"orders": []}, "paper": True}
    rows = list(b["orders"])
    if k.get("order_id"): rows = [o for o in rows if o["id"] == k["order_id"]]
    if k.get("symbol"): rows = [o for o in rows if o["symbol"] == k["symbol"].upper()]
    if k.get("state"): rows = [o for o in rows if o["state"] == k["state"]]
    if k.get("created_at_gte"):
        g = pt(k["created_at_gte"] if "T" in k["created_at_gte"] else k["created_at_gte"] + "T00:00:00Z")
        rows = [o for o in rows if pt(o["created_at"]) >= g]
    rows.sort(key=lambda o: o["created_at"], reverse=True)
    return {"data": {"orders": [public(o) for o in rows[:100]]}, "paper": True}

def positions_view(b):
    out = []
    for s, p in sorted(b["positions"].items()):
        held = held_for_sells(b, s)
        out.append({"symbol": s, "quantity": s6(p["quantity"]), "average_buy_price": f"{p['avg']:.4f}", "type": "long",
                    "shares_held_for_sells": s6(held), "shares_available_for_sells": s6(max(0.0, p["quantity"] - held)), "account_number": ACCOUNT})
    return {"data": {"positions": out}, "paper": True}

def mkt_value(b):
    v = 0.0
    for s, p in b["positions"].items():
        q = b["quotes"].get(s) or {}; v += p["quantity"] * (f(q.get("bid_price")) or f(q.get("last_trade_price")) or p["avg"])
    return round(v, 2)

def portfolio(b):
    mv = mkt_value(b)
    return {"data": {"account_number": ACCOUNT, "paper": True, "cash": f"{b['cash']:.2f}", "buying_power": f"{buying_power(b):.2f}",
                     "pending_deposits": "0.00", "equity_market_value": f"{mv:.2f}", "total_value": f"{b['cash'] + mv:.2f}",
                     "breakdown": {"equities": f"{mv:.2f}", "cash": f"{b['cash']:.2f}"}}, "paper": True}

def realized(b, k, now, rows_only=False):
    span = k.get("span", "day"); day = now.date()
    if span == "day": keep = [r for r in b["realized"] if pt(r["at"]).date() == day]
    elif span == "week": keep = [r for r in b["realized"] if (day - pt(r["at"]).date()).days < 7 and pt(r["at"]).isocalendar()[1] == now.isocalendar()[1]]
    else: keep = list(b["realized"])
    if rows_only:
        return {"data": {"results": [{"symbol": r["symbol"], "side": "sell", "quantity": s6(r["quantity"]), "price": s6(r["price"]),
                                      "realized_pnl": f"{r['pnl']:.4f}", "closed_at": z(pt(r["at"])), "order_id": r["orderId"], "asset_class": "equity"} for r in keep]}, "paper": True}
    tot = round(sum(r["pnl"] for r in keep), 4); orders = {r["orderId"] for r in keep}
    return {"data": {"account_number": ACCOUNT, "span": span, "total": {"realized_gain": f"{tot:.4f}", "closing_trades": len(orders)},
                     "buckets": [{"date": str(day), "realized_gain": f"{tot:.4f}", "closing_trades": len(orders)}]}, "paper": True}

TOOLS = ("get_accounts", "get_portfolio", "get_equity_positions", "get_equity_orders", "review_equity_order", "place_equity_order",
         "cancel_equity_order", "get_realized_pnl", "get_pnl_trade_history", "mark", "status", "reset")

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("tool", choices=TOOLS); ap.add_argument("--json", default="{}"); ap.add_argument("--quotes"); ap.add_argument("--bars")
    ap.add_argument("--now"); ap.add_argument("--cash", type=float); ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    now = datetime.now(ET) if not a.now else pt(a.now)
    try: k = json.loads(a.json or "{}")
    except Exception as e: print(json.dumps(err(f"--json is not valid JSON: {e}"))); return 2
    p = broker_path()
    with Locked(p):
        b = load(p, now)
        if a.tool == "reset":
            if _os.path.exists(p) and not a.force: print(json.dumps(err("book exists; pass --force (a .bak copy is kept)"))); return 4
            if _os.path.exists(p): _os.replace(p, p + f".bak-{now.strftime('%Y%m%dT%H%M%S')}")
            b = new_book(a.cash if a.cash is not None else f(pm_cfg().get("startCashUsd"), 100.0), now); save(p, b)
            print(json.dumps({"ok": True, "reset": True, "cash": b["cash"], "file": p})); return 0
        ev = mark(b, load_quotes(a.quotes), load_bars(a.bars), now) if (a.quotes or a.bars or a.tool == "mark") else []
        t = a.tool
        if t == "mark": out = {"ok": True, "paper": True, "filled": ev, "open": [o["id"] for o in b["orders"] if o["state"] in OPEN], "cash": round(b["cash"], 4)}
        elif t == "status":
            out = {"paper": True, "cash": round(b["cash"], 4), "buyingPower": buying_power(b), "positions": {s: p_["quantity"] for s, p_ in b["positions"].items()},
                   "open": [f"{o['symbol']} {o['side']} {o['type']}/{o['trigger']} {o['quantity']} @{o.get('stop_price') or ''}/{o.get('price') or ''}" for o in b["orders"] if o["state"] in OPEN],
                   "realizedToday": round(sum(r["pnl"] for r in b["realized"] if pt(r["at"]).date() == now.date()), 4), "lastMarkAt": b.get("lastMarkAt"),
                   "markSymbols": sorted(set(b["positions"]) | {o["symbol"] for o in b["orders"] if o["state"] in OPEN}),
                   "flat": not b["positions"] and not any(o["state"] in OPEN for o in b["orders"])}
        elif t == "get_accounts":
            out = {"data": {"accounts": [{"account_number": ACCOUNT, "nickname": "Agentic (PAPER)", "type": "cash", "agentic_allowed": True, "paper": True,
                                          "cash": f"{b['cash']:.2f}", "buying_power": f"{buying_power(b):.2f}"}]}, "paper": True}
        elif t == "get_portfolio": out = portfolio(b)
        elif t == "get_equity_positions": out = positions_view(b)
        elif t == "get_equity_orders": out = orders_view(b, k, now)
        elif t == "review_equity_order": out = place(b, k, now, dry=True)
        elif t == "place_equity_order": out = place(b, k, now)
        elif t == "cancel_equity_order": out = cancel(b, k, now)
        elif t == "get_realized_pnl": out = realized(b, k, now)
        elif t == "get_pnl_trade_history": out = realized(b, k, now, rows_only=True)
        save(p, b)
    print(json.dumps(out, indent=None))
    return 1 if isinstance(out, dict) and out.get("error") else 0

if __name__ == "__main__":
    sys.exit(main())
