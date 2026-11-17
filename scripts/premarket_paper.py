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

"""premarket_paper.py — DAILY 07:30–09:29 PREMARKET PAPER SESSION + SELF-TEST (LOCKED rule; Kevin 2026-11-10 16:03 "Run paper on premarket
to test", 16:05 "Repeat paper market test as part of rule set. 7:30 paper start. Test market until open. Switch to live cash at opening
bell.", 16:09 "Arm live at 9:30 am without live confirmation"). NEVER calls the broker (no network code) and NEVER writes live state.

  init     --date D                 create <stateDir>/<D>/ (paper state + paper broker book, cash = live startCash copy). Idempotent.
  selftest --date D [--out F]       deterministic end-to-end checks of the fixed flow on a throw-away temp copy (simulated buy → stopargs →
                                    stop_limit rest + broker-truth verify → stop fill + stall exit recorded by reconcile → append-only
                                    ledger + empty-snapshot refusal + journal heal → protect-first buy block → no re-buy after a loss →
                                    phase auto-expiry → live book never a stale 0 → recap claim once → paper-session write guard →
                                    live files untouched). Results merged into the day's results file.
  summary  --date D [--quotes Q] [--live-orders O]   flatten the paper book (cancel all; sell at the quote bid, else at cost),
                                    compute paper W/L + start→end $, merge selftest + session checks, write <stateDir>/premarket-paper-<D>.json,
                                    print {ok, line, failed[]}. exit 0 all pass | 1 any check failed (→ escalation before 09:30).
  paths    --date D                 print the paper paths/env for the day."""
import os as _os, time as _time
_os.environ["TZ"] = "America/New_York"; _time.tzset()
import argparse, hashlib, json, shutil, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
HERE = _os.path.dirname(_os.path.abspath(__file__))
CONFIG = _os.environ.get("RECONCILE_CONFIG", "/workspace/robinhood-fable-agent/config/equity-morning-session.json")
LIVE_DIR = "/workspace/robinhood-fable-agent/data/equity-paper"
LIVE_FILES = [f"{LIVE_DIR}/morning-session.json", f"{LIVE_DIR}/week-desk.json", f"{LIVE_DIR}/desk-phases.json", f"{LIVE_DIR}/order-locks.json"]

def cfg():
    try: return json.load(open(CONFIG))
    except Exception: return {}
def base_dir(C=None): return ((C or cfg()).get("premarketPaper") or {}).get("stateDir") or f"{LIVE_DIR}/premarket-paper"
def P(D, C=None):
    b = base_dir(C); d = f"{b}/{D}"
    return {"dir": d, "state": f"{d}/morning-session.json", "broker": f"{d}/broker.json", "taDir": f"{d}/ta", "results": f"{b}/premarket-paper-{D}.json",
            "env": {"DESK_PAPER_SESSION": "1", "PAPER_BROKER": f"{d}/broker.json", "PAPER_PREMARKET_TEST": "1"}}
def jload(p, d=None):
    try: return json.load(open(p))
    except Exception: return d
def jsave(p, o):
    _os.makedirs(_os.path.dirname(p), exist_ok=True); tmp = f"{p}.tmp.{_os.getpid()}"; json.dump(o, open(tmp, "w"), indent=1); _os.replace(tmp, p)
def sha(p):
    try: return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except FileNotFoundError: return None
def f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def cmd_init(a):
    C = cfg(); p = P(a.date, C); _os.makedirs(p["taDir"], exist_ok=True)
    live = jload(f"{LIVE_DIR}/morning-session.json", {}) or {}
    cash = a.cash if a.cash is not None else f(live.get("cash") or live.get("startCash") or C.get("bankUsd"), 100.0)
    if not _os.path.exists(p["broker"]):
        env = dict(_os.environ, **p["env"]); subprocess.run([sys.executable, f"{HERE}/paper_broker.py", "reset", "--cash", str(cash)], env=env, capture_output=True, check=True)
    if not _os.path.exists(p["state"]):
        jsave(p["state"], {"sessionDate": a.date, "mode": "paper_premarket", "paper": True, "status": "paper_premarket", "accountNumber": ACCOUNT,
                           "startCash": round(cash, 2), "startBank": round(cash, 2), "cash": round(cash, 2), "positions": [], "closed": [], "orders": [],
                           "roundTrips": [], "roundTripCount": 0, "realizedPnlUsd": 0.0, "maxPositions": 2, "discretion": {"halted": False},
                           "errorsAutoFixed": [], "notes": ["PREMARKET PAPER — simulated orders only; never live"], "buyLock": None})
    print(json.dumps({"ok": True, **p})); return 0

# ------------------------------------------------------------------ self-test
def run(args, env, ok_codes=(0,)):
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, env=env)
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    js = None
    for cand in (r.stdout.strip(), lines[-1] if lines else ""):
        try: js = json.loads(cand); break
        except Exception: pass
    if js is None:
        try: js = json.loads("\n".join(lines[:-1]))
        except Exception: js = {}
    return r.returncode, js, r.stdout + r.stderr

def selftest(D):
    C = cfg(); before = {p: sha(p) for p in LIVE_FILES}
    W = tempfile.mkdtemp(prefix=f"pmpaper_{D}_")
    tc = json.loads(json.dumps(C)); tc.setdefault("premarketPaper", {})["stateDir"] = W
    tc.setdefault("desk", {}).update({"paused": False}); tc["liveMode"] = dict(tc.get("liveMode") or {}, armed=True); tc["executionMode"] = "live"
    tc.setdefault("paperMode", {})["maxQuoteAgeSeconds"] = 120
    cfgp = f"{W}/config.json"; jsave(cfgp, tc)
    st = f"{W}/morning-session.json"; brk = f"{W}/broker.json"; led = f"{W}/desk-phases.json"
    env = dict(_os.environ, RECONCILE_CONFIG=cfgp, DISC_CONFIG=cfgp, PAPER_BROKER=brk, PAPER_PREMARKET_TEST="1", DESK_PAPER_SESSION="1")
    checks = []
    def ok(name, cond, detail=""): checks.append({"check": name, "pass": bool(cond), "detail": str(detail)[:300]})
    T = lambda hm: f"{D}T{hm}:00-05:00"
    def U(hm): return datetime.fromisoformat(T(hm)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    def quotes(hm, sym, bid, ask):
        q = f"{W}/q_{sym}_{hm.replace(':', '')}.json"
        jsave(q, {"data": {"results": [{"quote": {"symbol": sym, "bid_price": str(bid), "ask_price": str(ask), "last_trade_price": str(ask),
                                                   "venue_bid_time": U(hm), "venue_ask_time": U(hm), "updated_at": U(hm), "state": "active"}}]}}); return q
    def broker(tool, kw, hm, q=None):
        a = [f"{HERE}/paper_broker.py", tool, "--json", json.dumps(kw), "--now", T(hm)] + (["--quotes", q] if q else [])
        return run(a, env)
    def snap(hm):
        _, po, _ = broker("get_equity_positions", {"account_number": ACCOUNT}, hm); _, oo, _ = broker("get_equity_orders", {"account_number": ACCOUNT}, hm)
        pf, of = f"{W}/pos_{hm.replace(':', '')}.json", f"{W}/ord_{hm.replace(':', '')}.json"; jsave(pf, po); jsave(of, oo); return pf, of
    def sync(hm, q=None, apply=True):
        pf, of = snap(hm)
        a = [f"{HERE}/reconcile.py", "sync", "--state", st, "--positions", pf, "--orders", of, "--now", T(hm), "--routine", "paper-premarket", "--max-age-s", "100000"]
        if q: a += ["--quotes", q]
        if apply: a.append("--apply")
        rc, _, out = run(a, env); body = json.loads(out[:out.rfind('\n{"summary"')] if '\n{"summary"' in out else "{}") if out.strip().startswith("{") else {}
        return rc, body, pf, of
    try:
        subprocess.run([sys.executable, f"{HERE}/paper_broker.py", "reset", "--cash", "100", "--force"], env=env, capture_output=True, check=True)
        jsave(st, {"sessionDate": D, "mode": "selftest", "startBank": 100.0, "startCash": 100.0, "positions": [], "closed": [], "orders": [], "roundTrips": [],
                   "roundTripCount": 0, "realizedPnlUsd": 0.0, "discretion": {"halted": False}, "errorsAutoFixed": [], "buyLock": None})
        # 1. stopargs: missing type refused, correct stop_limit accepted
        bad = {"account_number": ACCOUNT, "symbol": "TSTA", "side": "sell", "quantity": "10", "stop_price": "4.90", "limit_price": "4.75", "time_in_force": "gfd", "market_hours": "regular_hours"}
        rc1, j1, _ = run([f"{HERE}/reconcile.py", "stopargs", "--json", json.dumps(bad)], env)
        good = dict(bad, type="stop_limit"); rc2, j2, _ = run([f"{HERE}/reconcile.py", "stopargs", "--json", json.dumps(good)], env)
        ok("fix1 stopargs refuses a stop without type stop_limit; accepts stop_limit+stop_price+limit_price", rc1 == 4 and rc2 == 0 and (j1.get("fixed") or {}).get("type") == "stop_limit", [rc1, rc2])
        # 2. simulated buy fills, stop_limit rests, broker-truth verify passes
        q = quotes("10:00", "TSTA", 4.99, 5.00)
        rc, b, _ = broker("place_equity_order", {"account_number": ACCOUNT, "symbol": "TSTA", "side": "buy", "type": "limit", "quantity": "10", "limit_price": "5.07", "time_in_force": "gfd", "market_hours": "regular_hours", "ref_id": "st-buy-1"}, "10:00", q)
        buy_id = ((b.get("data") or {}).get("order") or {}).get("id"); filled = ((b.get("data") or {}).get("order") or {}).get("state") == "filled"
        run([f"{HERE}/reconcile.py", "reason", "--state", st, "--order-id", str(buy_id), "--reason", "recycle"], env)
        ok("flow simulated paper buy fills on the quote", rc == 0 and filled, b)
        rc, pr, pf, of = sync("10:00", q)
        rc_v, v0, _ = run([f"{HERE}/reconcile.py", "verify-protection", "--positions", pf, "--orders", of, "--state", st, "--apply"], env)
        ok("fix2 unprotected position after a buy → verify-protection exit 7, buysAllowed false, rest_stop action", rc_v == 7 and v0.get("buysAllowed") is False and any(x.get("type") == "rest_stop" for x in pr.get("actions", [])), [rc_v, v0])
        rcg, g, _ = run([f"{HERE}/discretion.py", "gate", "--symbol", "OTHR", "--last", "6", "--day-pct", "12", "--state", st, "--now", T("10:01")], env)
        ok("fix2 discretion gate refuses new buys while a position is unprotected", g.get("allowed") is False and any("unprotected" in r for r in g.get("reasons", [])), g.get("reasons"))
        rc, s1, _ = broker("place_equity_order", dict(good, quantity="10", stop_price="4.90", limit_price="4.75", ref_id="st-stop-1"), "10:00", q)
        o = (s1.get("data") or {}).get("order") or {}
        pf, of = snap("10:01")
        rc_v, v1, _ = run([f"{HERE}/reconcile.py", "verify-protection", "--positions", pf, "--orders", of, "--state", st, "--apply"], env)
        ok("fix1 resting order verified at the broker as a real stop-limit (trigger stop + type limit)", o.get("trigger") == "stop" and o.get("type") == "limit" and rc_v == 0 and v1.get("buysAllowed") is True, [o.get("type"), o.get("trigger"), rc_v])
        # wrong-type (plain limit) detection
        jw = f"{W}/ord_wrong.json"; od = jload(of); rows = (od.get("data") or od).get("orders") or (od.get("data") or od).get("results") or []
        for r in rows:
            if r.get("trigger") == "stop": r["trigger"] = "immediate"
        jsave(jw, od)
        rc_w, vw, _ = run([f"{HERE}/reconcile.py", "verify-protection", "--positions", pf, "--orders", jw], env)
        ok("fix1 a plain limit sell is flagged wrongType (not protection)", rc_w == 7 and vw.get("wrongType"), vw.get("wrongType"))
        # 3. stop fill recorded by reconcile (reason resting_stop_limit)
        q2 = quotes("10:04", "TSTA", 4.88, 4.89); broker("mark", {}, "10:04", q2)
        rc, pr, _, _ = sync("10:05", quotes("10:05", "TSTA", 4.88, 4.89))
        s = jload(st); rts = s.get("roundTrips") or []
        ok("flow stop_limit fill recorded by reconcile as resting_stop_limit", len(rts) == 1 and rts[0].get("reason") == "resting_stop_limit", [r.get("reason") for r in rts])
        # 4. stall exit path: buy, desk sell labelled stall_exit
        q3 = quotes("10:10", "TSTB", 3.00, 3.01)
        _, b2, _ = broker("place_equity_order", {"account_number": ACCOUNT, "symbol": "TSTB", "side": "buy", "type": "limit", "quantity": "10", "limit_price": "3.06", "time_in_force": "gfd", "market_hours": "regular_hours", "ref_id": "st-buy-2"}, "10:10", q3)
        bid2 = ((b2.get("data") or {}).get("order") or {}).get("id"); run([f"{HERE}/reconcile.py", "reason", "--state", st, "--order-id", str(bid2), "--reason", "recycle"], env)
        broker("place_equity_order", {"account_number": ACCOUNT, "symbol": "TSTB", "side": "sell", "type": "stop_limit", "quantity": "10", "stop_price": "2.95", "limit_price": "2.86", "time_in_force": "gfd", "market_hours": "regular_hours", "ref_id": "st-stop-2"}, "10:10", q3)
        sync("10:11", quotes("10:11", "TSTB", 3.00, 3.01))
        q4 = quotes("10:23", "TSTB", 2.99, 3.00)
        _, oo, _ = broker("get_equity_orders", {"account_number": ACCOUNT}, "10:23")
        for r in (oo.get("data") or oo).get("orders") or []:
            if r["symbol"] == "TSTB" and r.get("trigger") == "stop" and r["state"] in ("confirmed", "new", "queued"): broker("cancel_equity_order", {"account_number": ACCOUNT, "order_id": r["id"]}, "10:23")
        _, sx, _ = broker("place_equity_order", {"account_number": ACCOUNT, "symbol": "TSTB", "side": "sell", "type": "limit", "quantity": "10", "limit_price": "2.99", "time_in_force": "gfd", "market_hours": "regular_hours", "ref_id": "st-stall-1"}, "10:23", q4)
        run([f"{HERE}/reconcile.py", "reason", "--state", st, "--order-id", str(((sx.get("data") or {}).get("order") or {}).get("id")), "--reason", "stall_exit"], env)
        sync("10:24", quotes("10:24", "TSTB", 2.99, 3.00))
        s = jload(st); rts = s.get("roundTrips") or []
        ok("flow stall exit recorded as stall_exit", any(r.get("reason") == "stall_exit" for r in rts), [r.get("reason") for r in rts])
        realized = s.get("realizedPnlUsd")
        # 5. append-only: empty orders snapshot refused; journal heal restores a reset
        emp = f"{W}/ord_empty.json"; jsave(emp, {"data": {"orders": []}}); pf2 = f"{W}/pos_empty.json"; jsave(pf2, {"data": {"positions": []}})
        rc, _, out = run([f"{HERE}/reconcile.py", "sync", "--state", st, "--positions", pf2, "--orders", emp, "--now", T("10:30"), "--apply", "--max-age-s", "100000"], env)
        s2 = jload(st)
        ok("fix5 sync on an empty orders file is refused; realized P&L unchanged", "empty_orders_snapshot" in out and s2.get("realizedPnlUsd") == realized and len(s2.get("roundTrips") or []) == 2, [realized, s2.get("realizedPnlUsd")])
        s2["roundTrips"] = []; s2["closed"] = []; s2["realizedPnlUsd"] = 0; jsave(st, s2)   # simulate a bad worker zeroing the ledger
        run([f"{HERE}/reconcile.py", "statewrite", "--state", st, "--routine", "selftest", "--json", json.dumps({"set": {"selftestNote": "x"}})], env)
        s3 = jload(st)
        ok("fix5 a zeroed ledger self-heals from the append-only journal", len(s3.get("roundTrips") or []) == 2 and abs(f(s3.get("realizedPnlUsd")) - f(realized)) < 1e-6, [s3.get("realizedPnlUsd"), realized])
        rcz, jz, _ = run([f"{HERE}/reconcile.py", "statewrite", "--state", st, "--routine", "selftest", "--json", json.dumps({"set": {"realizedPnlUsd": 0}})], env)
        ok("fix5 statewrite refuses to set realizedPnlUsd", rcz == 4, jz)
        # 6. no re-buy after a loss today
        rcg, g, _ = run([f"{HERE}/discretion.py", "gate", "--symbol", "TSTA", "--last", "5", "--day-pct", "12", "--state", st, "--now", T("10:40")], env)
        ok("rule no same-symbol re-buy after a losing exit today", g.get("allowed") is False and any("same_symbol_loss_today" in r for r in g.get("reasons", [])), g.get("reasons"))
        # 7. desk_clock: auto-expiry of a stuck phase, live book hint, report once
        jsave(led, {D: {"scan": {"status": "done"}, "entries": {"status": "running", "at": T("10:00"), "attempts": 1, "procedure": "entries.md"}}})
        live_st = f"{W}/live-state.json"; jsave(live_st, {"sessionDate": D, "status": "scanned", "positions": [], "reconcileAt": T("10:14")})
        rc, j, _ = run([f"{HERE}/desk_clock.py", "next", "--now", T("10:15"), "--ledger", led, "--state", live_st], env)
        L = jload(led)[D]
        ok("fix3 stuck 'running' phase auto-expires and the next fire retries it (entries-backup.md)", L["entries"].get("autoExpired") and any(p["phase"] == "entries" and p["procedure"] == "entries-backup.md" for p in j.get("phases", [])), [L["entries"].get("status"), j.get("phases")])
        ok("fix4 live desk_clock book never reports a stale openOrders count (null + source)", (j.get("book") or {}).get("openOrders") is None and "HINT" in str((j.get("book") or {}).get("source")), j.get("book"))
        rc_a, ja, _ = run([f"{HERE}/desk_clock.py", "report-claim", "--date", D, "--state", live_st], env)
        rc_b, jb, _ = run([f"{HERE}/desk_clock.py", "report-claim", "--date", D, "--state", live_st], env)
        rc, j2, _ = run([f"{HERE}/desk_clock.py", "plan", "--now", T("16:06"), "--ledger", led, "--state", live_st], env)
        ok("fix6 recap claim succeeds once, second claim refused, desk_clock never re-dispatches report", rc_a == 0 and rc_b == 3 and not any(p["phase"] == "report" for p in j2.get("phases", [])), [rc_a, rc_b])
        # 8. paper session guard + live switch flag
        outside = tempfile.mkdtemp(prefix="pm_outside_") + "/morning-session.json"; jsave(outside, {"sessionDate": D})
        rcx, jx, _ = run([f"{HERE}/reconcile.py", "statewrite", "--state", outside, "--routine", "paper-premarket", "--json", '{"set":{"x":1}}'], env)
        ok("isolation DESK_PAPER_SESSION=1 refuses any write outside the paper dir (exit 5)", rcx == 5 and "x" not in (jload(outside) or {}), jx)
        rc, j3, _ = run([f"{HERE}/desk_clock.py", "plan", "--now", T("08:00"), "--ledger", led, "--state", live_st], env)
        rc, j4, _ = run([f"{HERE}/desk_clock.py", "plan", "--now", T("09:30"), "--ledger", led, "--state", live_st], env)
        ok("switch 08:00 = paper-premarket session; 09:30 = live automatically (no confirmation)", j3.get("session") == "paper-premarket" and "paper-premarket" in [p["phase"] for p in j3.get("phases", [])] and not {"entries", "manage", "entries-backup", "flatten"} & {p["phase"] for p in j3.get("phases", [])}
           and j4.get("session") == "live" and (j4.get("liveSwitch") or {}).get("confirmation", "").startswith("none"), [j3.get("session"), j4.get("session")])
    except Exception as e:
        ok("selftest harness ran without crashing", False, repr(e))
    after = {p: sha(p) for p in LIVE_FILES}
    ok("isolation live state/ledger files untouched by the paper self-test", before == after, [p for p in LIVE_FILES if before[p] != after[p]])
    shutil.rmtree(W, ignore_errors=True)
    return checks

def merge_results(D, **kw):
    p = P(D)["results"]; r = jload(p, {}) or {"date": D}
    r.update(kw); r["updatedAt"] = datetime.now(ET).isoformat(timespec="seconds"); jsave(p, r); return r

def cmd_selftest(a):
    checks = selftest(a.date); failed = [c["check"] for c in checks if not c["pass"]]
    merge_results(a.date, selftest={"at": datetime.now(ET).isoformat(timespec="seconds"), "checks": checks, "passed": len(checks) - len(failed), "total": len(checks), "failed": failed})
    if a.out: jsave(a.out, checks)
    print(json.dumps({"ok": not failed, "passed": len(checks) - len(failed), "total": len(checks), "failed": failed})); return 0 if not failed else 1

def cmd_summary(a):
    C = cfg(); p = P(a.date, C); env = dict(_os.environ, **p["env"]); now = datetime.now(ET) if not a.now else datetime.fromisoformat(a.now)
    checks = []
    def ok(name, cond, detail=""): checks.append({"check": name, "pass": bool(cond), "detail": str(detail)[:300]})
    book = jload(p["broker"])
    trades, start, end = [], None, None
    if book:
        # flatten the paper book: cancel open orders; sell positions at the quote bid (else at cost)
        qs = {}
        if a.quotes:
            d = jload(a.quotes, {}) or {}; d = d.get("data", d)
            for r in (d.get("results", []) if isinstance(d, dict) else d):
                q = r.get("quote", r); qs[q.get("symbol")] = q
        for o in book["orders"]:
            if o["state"] in ("new", "queued", "confirmed", "unconfirmed", "partially_filled", "pending"): o["state"] = "cancelled"; o["_cancelledBy"] = "paper-summary flatten"
        for s, pos in list(book["positions"].items()):
            px = f((qs.get(s) or {}).get("bid_price")) or f(pos.get("avg")); q_ = f(pos["quantity"])
            pnl = (px - f(pos["avg"])) * q_; book["cash"] = round(book["cash"] + px * q_, 6)
            book["realized"].append({"at": now.isoformat(timespec="seconds"), "symbol": s, "quantity": q_, "price": px, "avgCost": pos["avg"], "pnl": round(pnl, 6), "orderId": "paper-summary-flatten"})
            book["positions"].pop(s)
        jsave(p["broker"], book)
        start, end = f(book.get("startCash")), round(f(book.get("cash")), 2)
        trades = book.get("realized") or []
    ps = jload(p["state"], {}) or {}
    wins = sum(1 for r in trades if f(r.get("pnl")) > 0); losses = sum(1 for r in trades if f(r.get("pnl")) <= 0)
    ok("paper book flat at the summary (no paper positions/orders can reach 09:30)", not book or (not book["positions"] and not any(o["state"] in ("new", "queued", "confirmed", "partially_filled") for o in book["orders"])))
    ok("paper state is the paper file (never the live state)", not ps or (ps.get("mode") == "paper_premarket"), ps.get("mode"))
    led = jload(f"{LIVE_DIR}/desk-phases.json", {}) or {}
    fires = ((led.get(a.date) or {}).get("paper-premarket") or {}).get("fires", 0)
    ok("paper-premarket ticks ran this morning", fires >= 1 or a.allow_no_ticks, f"fires={fires}")
    if a.live_orders:
        d = jload(a.live_orders, {}) or {}; d = d.get("data", d); rows = d.get("orders", d.get("results", [])) if isinstance(d, dict) else d
        lo = [r for r in rows if str(r.get("created_at", ""))[:10] == a.date and r.get("created_at", "") < f"{a.date}T14:30:00Z"]
        ok("no LIVE broker order was created before 09:30 (read-only live check)", not lo, [r.get("id", "")[:8] for r in lo])
    res = jload(p["results"], {}) or {}
    st = res.get("selftest")
    if not st or a.rerun_selftest:
        sc = selftest(a.date); f_ = [c["check"] for c in sc if not c["pass"]]
        st = {"at": datetime.now(ET).isoformat(timespec="seconds"), "checks": sc, "passed": len(sc) - len(f_), "total": len(sc), "failed": f_}
    allc = (st.get("checks") or []) + checks; failed = [c["check"] for c in allc if not c["pass"]]
    D = datetime.fromisoformat(a.date)
    line = (f"PAPER — {D.strftime('%a %b')} {D.day} pre-open: checks {len(allc) - len(failed)}/{len(allc)} pass"
            + (f" | FAILED: {'; '.join(failed)[:200]}" if failed else "") + f" | paper W/L {wins}/{losses}"
            + (f" | paper ${start:.2f} → ${end:.2f}" if start is not None else " | no paper book"))
    merge_results(a.date, selftest=st, sessionChecks=checks, paperTrades=trades, paperWins=wins, paperLosses=losses, paperStartUsd=start, paperEndUsd=end,
                  summaryLine=line, ok=not failed, failed=failed, liveSwitchAt=((C.get("premarketPaper") or {}).get("liveSwitchEt") or "09:30"))
    print(json.dumps({"ok": not failed, "line": line, "failed": failed, "results": p["results"]})); return 0 if not failed else 1

def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    for nm in ("init", "selftest", "summary", "paths"):
        x = sp.add_parser(nm); x.add_argument("--date", default=datetime.now(ET).date().isoformat())
        if nm == "init": x.add_argument("--cash", type=float)
        if nm == "selftest": x.add_argument("--out")
        if nm == "summary":
            x.add_argument("--quotes"); x.add_argument("--live-orders"); x.add_argument("--now"); x.add_argument("--rerun-selftest", action="store_true"); x.add_argument("--allow-no-ticks", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "paths": print(json.dumps(P(a.date))); return 0
    return {"init": cmd_init, "selftest": cmd_selftest, "summary": cmd_summary}[a.cmd](a)
if __name__ == "__main__": sys.exit(main())
