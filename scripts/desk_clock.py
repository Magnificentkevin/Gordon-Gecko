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

"""desk_clock.py — the SINGLE-ROUTINE DISPATCHER CLOCK for the Equity AM desk (2026-10-23; Kevin: "Rebuild whole system in one routine").

One routine fires every 5 min on weekdays 05:30–18:15 ET. On every fire it runs:
    python3 /workspace/paper/desk_clock.py next [--now ISO]
which prints JSON {phases:[{phase, procedure, attempt, why}], idle, idleReason, skipped, escalate, executionMode, paths, forbiddenTools}
and CLAIMS the once-a-day phases it returns (status "running") in the dispatcher ledger, so a duplicate/overlapping fire never runs a
once-a-day phase twice. After each phase the routine records the outcome:
    python3 /workspace/paper/desk_clock.py done   --phase P [--note "..."] [--now ISO]
    python3 /workspace/paper/desk_clock.py failed --phase P --error "..."   [--now ISO]
Other commands: `plan` (same as next, read-only: claims nothing), `status` (today's ledger), `reset-day --date D --force` (tests/replays).

ALL-DAY SESSION from 2026-11-10 (Kevin 08:13 ET "run it all day till 4:00"): cutoff = config manage.noNewEntriesAfterEt (15:45),
flatten = desk.flattenAtEt (15:50), hard-flatten = close − desk.hardFlattenMinutesBeforeClose (15:55), report from desk.reportEarliestEt
(16:00) once done, fallback close + desk.reportFallbackMinutesAfterClose (16:05); manage runs EVERY fire 09:30–cutoff even when flat.
The 10:00/11:00/11:05/15:45/15:52 times in the list below are the pre-2026-11-10 defaults (used only if those config keys are missing).
PHASES (ET; once-a-day phases run exactly once per trading day and CATCH UP on the first fire after their time):
  scan          first fire ≥ 05:30 while no scan today (before 09:10 → scan.md; 09:10–10:00 → refresh.md, whose full-scan path covers a
                missed 05:30; after 10:00 → scan.md as a late catch-up so the day still has a state file — no buys are possible by then)
  refresh       first fire in [09:10, 09:33) after a scan that finished before 09:00 (a scan done ≥ 09:00 is already fresh → skipped)
  entries       first fire in [09:33, 10:00) → entries.md; a FAILED entries run retries on the next fire < 10:00 via entries-backup.md;
                at/after 10:00 never run → recorded skipped "missed_cutoff" (strict 10:00 new-buy cutoff, owner rule P7)
  manage        EVERY fire 09:30–15:59 while the paper book holds positions or open orders, or before 11:05 (buys/shadow P3–P5 window),
                or after the 11:00 flatten until the desk is done (D6 doneAt). Not on the same fire as entries / flatten / hard-flatten
                (those procedures sync + manage themselves). Concurrent fires: a manage claim younger than 240 s blocks a 2nd manage.
  flatten       first fire ≥ 11:00 → flatten.md (Phase A flatten/hold check, B scorecard, C daily revise — propose-only in paper);
                a failed run retries via flatten-backup.md
  hard-flatten  first fire ≥ 15:45 (early-close days: close − 15 min) while the book holds anything → flatten-backup.md (≥15:40 path:
                everything out, reason late_hard_flatten_1545); a flat book → skipped "already_flat"
  report        once, when the desk is done (state doneAt set) and flatten is done, or on the first fire ≥ 15:52 regardless → report.md
                (the ONE daily recap to Kevin)
  kb-refresh    first fire ≥ 18:00 → kb-refresh.md (Friday's run includes the weekly block, so no Saturday run is needed)
  idle          weekends, NYSE holidays, before paperMode.startDate, config desk.paused, nothing due
A phase that fails 3 times is escalated (escalate[]): the routine tells Kevin (unfixable error). A "running" claim older than 20 min
is treated as crashed and may be re-claimed (counts as an attempt).
DESK FIXES 2026-11-10 (Kevin 16:02 ET "Fix mistakes and restart tomorrow"):
  * PHASE AUTO-EXPIRY: a "running" claim older than its timeout (config desk.phaseTimeoutMinutes, default 12 min; manage = manageClaimSeconds)
    is marked failed "auto-expired" by the next `next` call (counts as an attempt; retries via the backup procedure) — no manual
    `failed` needed after a crashed worker (12:25 'Deferred interaction response requested').
  * BOOK = HINT ONLY in live mode: desk_clock cannot read the broker, so `book` comes from the last reconcile and carries
    source/ageS/trusted; openOrders is null (never a stale 0). A live book older than desk.liveBookMaxAgeSeconds (600 s) is treated
    as NOT flat (hard-flatten/manage still run and read the broker). Procedures always decide from get_equity_positions/orders.
  * PROTECT FIRST: every live trading fire 09:30–16:00 carries `protectFirst` (reconcile.py verify-protection before anything).
  * REPORT ONCE: report is skipped when state reportDeliveredFor = D or reportSendAttemptedFor = D; `report-claim` atomically marks
    the send attempt so a WakeParent abort/retry can never re-send a recap (Nov 9).
PREMARKET PAPER + AUTO LIVE SWITCH (LOCKED; Kevin 2026-11-10 16:03 "Run paper on premarket to test", 16:05 "Repeat paper market test as
part of rule set. 7:30 paper start. Test market until open. Switch to live cash at opening bell.", 16:09 "Arm live at 9:30 am without live
confirmation"): every trading day `paper-premarket` (paper-premarket.md) runs on EVERY fire 07:30–09:29 in a SEPARATE paper book/state
(config premarketPaper.stateDir; simulated orders only), `paper-summary` (paper-summary.md) runs once from 09:20 (retry 09:25): it
flattens the paper book, runs premarket_paper.py summary (pass/fail per check + paper trades/P&L) and hands the summary back; a failed
check is an escalation before 09:30. At 09:30 the desk switches to LIVE automatically (no confirmation, no prompt) — unless Kevin has
paused (desk.paused) or disarmed (liveMode.armed false), in which case live stays off. Paper never touches live state, P&L, kill
switch, round-trip counts or the recap.
Mode: config executionMode "paper" (default when missing) → procedures from /workspace/equity-am-desk/live/paper/, broker =
paper_broker.py, forbiddenTools = every Robinhood order/write tool. "live" is implemented but refuses to dispatch unless config
liveMode.armed is true (it is false; only Kevin arms it)."""
import os as _os, time as _time
_os.environ["TZ"] = "America/New_York"; _time.tzset()
import argparse, fcntl, json, sys
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CONFIG = _os.environ.get("RECONCILE_CONFIG", "/workspace/robinhood-fable-agent/config/equity-morning-session.json")
OPEN = {"new", "queued", "confirmed", "unconfirmed", "partially_filled", "pending"}
ONCE = ("scan", "refresh", "entries", "flatten", "hard-flatten", "report", "kb-refresh", "paper-summary", "research")
EVERY = ("manage", "paper-premarket", "bank-stop")
PREMARKET_DIR = "/workspace/robinhood-fable-agent/data/equity-paper/premarket-paper"
HOLIDAYS = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
            "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}
EARLY_CLOSE = {"2026-11-27": "13:00", "2026-12-24": "13:00", "2027-11-26": "13:00"}
# Every Robinhood MCP tool that places, changes or cancels anything (orders, alerts, watchlists, scans, approvals, layouts).
FORBIDDEN_PAPER = ["place_equity_order", "cancel_equity_order", "review_equity_order", "place_advanced_order", "cancel_advanced_order",
                   "review_advanced_order", "place_option_order", "cancel_option_order", "review_option_order", "exercise_option",
                   "cancel_option_exercise", "place_crypto_order", "cancel_crypto_order", "preview_crypto_order", "decline_trade_approval",
                   "create_alert", "update_alert", "delete_alert", "mark_alerts_read", "create_scan", "update_scan_filters", "update_scan_config",
                   "create_watchlist", "update_watchlist", "add_to_watchlist", "remove_from_watchlist", "add_option_to_watchlist",
                   "remove_option_from_watchlist", "follow_watchlist", "unfollow_watchlist", "add_legend_indicator", "remove_legend_indicator",
                   "update_legend_indicator", "set_legend_chart_settings"]
PAPER_BROKER_TOOLS = ["get_accounts", "get_portfolio", "get_equity_positions", "get_equity_orders", "review_equity_order", "place_equity_order",
                      "cancel_equity_order", "get_realized_pnl", "get_pnl_trade_history"]

def f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d
def pt(s):
    if not s: return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=ET)).astimezone(ET)
def iso(d): return d.isoformat(timespec="seconds")
def cfg():
    try: return json.load(open(CONFIG))
    except Exception: return {}

def paths(C):
    pm = C.get("paperMode") or {}
    base = pm.get("stateDir") or "/workspace/robinhood-fable-agent/data/equity-paper/paper-mode"
    mode = C.get("executionMode") or "paper"
    if mode == "live":
        live = "/workspace/robinhood-fable-agent/data/equity-paper"
        return {"mode": "live", "state": f"{live}/morning-session.json", "weekDesk": f"{live}/week-desk.json", "taDir": f"{live}/ta",
                "procedures": "/workspace/equity-am-desk/live", "broker": None, "ledger": f"{live}/desk-phases.json",
                "scorecardDir": "/workspace/equity-am-desk"}
    return {"mode": "paper", "state": f"{base}/morning-session.json", "weekDesk": f"{base}/week-desk.json", "taDir": f"{base}/ta",
            "procedures": pm.get("proceduresDir") or "/workspace/equity-am-desk/live/paper", "broker": pm.get("brokerFile") or f"{base}/broker.json",
            "ledger": pm.get("ledgerFile") or f"{base}/desk-phases.json", "scorecardDir": pm.get("scorecardDir") or "/workspace/equity-am-desk/paper-mode",
            "shadowDayFile": f"{base}/shadow-orb-<D>.json", "shadowLedger": f"{base}/shadow-orb-ledger.json"}

class Locked:
    def __init__(self, p): self.p = p + ".lock"
    def __enter__(self):
        _os.makedirs(_os.path.dirname(self.p) or ".", exist_ok=True)
        self.fh = open(self.p, "a+"); fcntl.flock(self.fh, fcntl.LOCK_EX); return self
    def __exit__(self, *a): fcntl.flock(self.fh, fcntl.LOCK_UN); self.fh.close()
def jload(p, d=None):
    try: return json.load(open(p))
    except (FileNotFoundError, json.JSONDecodeError): return d
def jsave(p, o):
    _os.makedirs(_os.path.dirname(p) or ".", exist_ok=True)
    tmp = f"{p}.tmp.{_os.getpid()}"; json.dump(o, open(tmp, "w"), indent=1); _os.replace(tmp, p)

def book(P, st):
    """(positions, openOrders) from the paper broker file (paper) or the state file (live: last reconciled view)."""
    if P["mode"] == "paper":
        b = jload(P["broker"], {}) or {}
        pos = {s: p.get("quantity") for s, p in (b.get("positions") or {}).items() if f(p.get("quantity")) > 0}
        oo = [o for o in b.get("orders") or [] if o.get("state") in OPEN]
        return pos, oo
    pos = {p["symbol"]: p.get("qty") for p in (st or {}).get("positions") or []}
    return pos, None   # live: openOrders unknown to desk_clock (never report a stale 0; procedures read the broker)

def live_book_meta(st, now, C):
    """How far the live book hint can be trusted (it is the last reconcile, NOT the broker)."""
    at = pt((st or {}).get("reconcileAt") or (st or {}).get("flatVerifiedAt"))
    age = (now - at).total_seconds() if at else None
    mx = f((C.get("desk") or {}).get("liveBookMaxAgeSeconds"), 600)
    return {"source": "state.reconcileAt (last broker reconcile) — HINT ONLY; read get_equity_positions/get_equity_orders",
            "reconcileAt": iso(at) if at else None, "ageS": round(age) if age is not None else None,
            "trusted": age is not None and age <= mx}

def trading_day(d, C):
    hol = set(HOLIDAYS) | set(((C.get("desk") or {}).get("holidays")) or [])
    return d.weekday() < 5 and d.isoformat() not in hol
def close_et(d, C):
    ec = dict(EARLY_CLOSE); ec.update(((C.get("desk") or {}).get("earlyClose")) or {})
    return ec.get(d.isoformat(), "16:00")
def hm_minus(hm, mins):
    h, m = map(int, hm.split(":")); t = h * 60 + m - mins; return f"{t // 60:02d}:{t % 60:02d}"

def phase_timeout_s(p, C):
    desk = C.get("desk") or {}
    if p in EVERY: return f(desk.get("manageClaimSeconds"), 240)
    tm = desk.get("phaseTimeoutMinutes") or {}
    return f(tm.get(p), f(tm.get("default"), f(desk.get("staleRunningMinutes"), 12))) * 60

def expire_stuck(day, now, C):
    """Auto-expire crashed claims so the next fire recovers by itself. Returns the expired rows (for the output)."""
    out = []
    for p, r in list(day.items()):
        if not isinstance(r, dict) or r.get("status") != "running" or not r.get("at"): continue
        age = (now - pt(r["at"])).total_seconds()
        if age < phase_timeout_s(p, C): continue
        r = dict(r)
        if p in EVERY: r.update({"status": "expired", "lastEndAt": iso(now), "lastError": f"auto-expired after {int(age)} s (worker crashed/stuck)"})
        else:
            r.update({"status": "failed", "failedAt": iso(now), "error": f"auto-expired after {int(age // 60)} min (worker crashed/stuck; e.g. pending approval card)", "autoExpired": True})
            r.setdefault("attempts", 1)
        day[p] = r; out.append({"phase": p, "ageS": int(age)})
    return out

def premarket_decide(now, C, ledger_day, PP):
    """07:30–09:29 PAPER session (separate book). Live phases never run here; nothing here can touch live state."""
    out, skipped, esc = [], [], []
    t = now.strftime("%H:%M")
    def row(p): return ledger_day.get(p) or {}
    max_attempts = int(f((C.get("desk") or {}).get("maxAttempts"), 3))
    summ_at = PP.get("summaryAtEt") or "09:20"
    r = row("paper-summary")
    if t >= summ_at:
        if r.get("status") in ("done", "skipped"): pass
        elif r.get("status") == "running" and r.get("at") and (now - pt(r["at"])).total_seconds() < phase_timeout_s("paper-summary", C): pass
        elif int(r.get("attempts", 0)) >= max_attempts:
            esc.append({"phase": "paper-summary", "msg": f"premarket paper summary failed {r.get('attempts')}x ({r.get('error')}) — tell Kevin before 09:30", "notifiedAt": r.get("escalatedAt")})
        else:
            out.append({"phase": "paper-summary", "procedure": "paper-summary.md", "attempt": int(r.get("attempts", 0)) + 1, "why": f"first fire ≥ {summ_at}: flatten paper book + pass/fail summary before the 09:30 live switch", "mode": "paper"})
    if not out:
        m = row("paper-premarket")
        busy = m.get("status") == "running" and m.get("at") and (now - pt(m["at"])).total_seconds() < phase_timeout_s("paper-premarket", C)
        if busy: skipped.append({"phase": "paper-premarket", "why": "previous paper tick still running"})
        else: out.append({"phase": "paper-premarket", "procedure": "paper-premarket.md", "attempt": 1, "why": f"premarket PAPER session {PP.get('startEt') or '07:30'}–09:29 (simulated orders only)", "mode": "paper"})
    idle = None if out else ("escalated" if esc else "nothing_due")
    return out, skipped, esc, idle

def premarket_paths(C, D):
    PP = C.get("premarketPaper") or {}; base = PP.get("stateDir") or PREMARKET_DIR
    return {"mode": "paper-premarket", "dir": f"{base}/{D}", "state": f"{base}/{D}/morning-session.json", "broker": f"{base}/{D}/broker.json",
            "taDir": f"{base}/{D}/ta", "results": f"{base}/premarket-paper-{D}.json", "procedures": "/workspace/equity-am-desk/live",
            "env": {"DESK_PAPER_SESSION": "1", "PAPER_BROKER": f"{base}/{D}/broker.json", "PAPER_PREMARKET_TEST": "1"},
            "helper": "python3 /workspace/paper/premarket_paper.py"}

def bank_stop_rec(C):
    b = C.get("bankStop") or {}
    if b.get("enabled") is False: return {}
    return jload(b.get("stateFile") or "/workspace/robinhood-fable-agent/data/equity-paper/bank-stop.json", {}) or {}

def decide(now, C, ledger_day, st, pos, oo):
    """BANK DRAWDOWN SYSTEM STOP first (Kevin 2026-11-10 16:24 ET): once risk_floors.py bank-check has tripped (live equity ≤ 50% of
    baseline), the ONLY phase ever dispatched is bank-stop.md (cancel all orders + flatten) until it records flattenDone; after that
    every fire idles 'bank_stop_tripped' — no paper session, no 09:30 live switch, no trades — until Kevin runs bank-restart."""
    bs = bank_stop_rec(C)
    if bs.get("tripped"):
        esc = [{"phase": "bank-stop", "msg": bs.get("escalation") or "SYSTEM STOP — bank drawdown ≤ 50% of baseline; automatic mode OFF until Kevin restarts",
                "notifiedAt": (ledger_day.get("bankStopEsc") or {}).get("escalatedAt")}]
        desk = C.get("desk") or {}
        if bs.get("flattenDone") or desk.get("paused") or (C.get("liveMode") or {}).get("armed") is not True or not trading_day(now.date(), C):
            return [], [], esc, "bank_stop_tripped"
        r = ledger_day.get("bank-stop") or {}
        if r.get("status") == "running" and r.get("at") and (now - pt(r["at"])).total_seconds() < 240:
            return [], [{"phase": "bank-stop", "why": "bank-stop claim in flight"}], esc, "bank_stop_tripped"
        return ([{"phase": "bank-stop", "procedure": "bank-stop.md", "attempt": int(r.get("fires", 0)) + 1,
                  "why": "SYSTEM STOP (bank ≤ 50% of baseline): cancel ALL open orders, flatten every position (market sells in regular hours), then risk_floors.py bank-flat-done"}],
                [], esc, None)
    return decide_core(now, C, ledger_day, st, pos, oo)

def decide_core(now, C, ledger_day, st, pos, oo):
    """07:30–09:29 on trading days: the PAPER premarket phases + whatever the live clock has due (only the read-only scan/refresh before
    09:30). desk.paused stops everything (Kevin-only); liveMode.armed false stops only the live part."""
    PP = C.get("premarketPaper") or {}; t0 = now.strftime("%H:%M")
    if PP.get("enabled") and not (C.get("desk") or {}).get("paused") and trading_day(now.date(), C) \
            and (PP.get("startEt") or "07:30") <= t0 < (PP.get("liveSwitchEt") or "09:30"):
        po, ps, pe, _ = premarket_decide(now, C, ledger_day, PP)
        lo, ls, le, lidle = decide_live(now, C, ledger_day, st, pos, oo)
        out = lo + po; esc = le + pe
        return out, ls + ps, esc, (None if out else ("escalated" if esc else (lidle or "nothing_due")))
    return decide_live(now, C, ledger_day, st, pos, oo)

def decide_live(now, C, ledger_day, st, pos, oo):
    """Pure decision: returns (phases[], skipped[], escalate[], idleReason|None). ledger_day = {phase: row}."""
    D = now.date(); t = now.strftime("%H:%M"); out, skipped, esc = [], [], []
    desk = C.get("desk") or {}; pm = C.get("paperMode") or {}
    mode = C.get("executionMode") or "paper"
    if mode not in ("paper", "live"): return [], [], [{"phase": "config", "msg": f"config executionMode {mode!r} is not paper|live", "notifiedAt": None}], "bad_mode"
    if desk.get("paused"): return [], [], [], "paused"
    if mode == "live" and not ((C.get("liveMode") or {}).get("armed") is True):
        return [], [], [], "live_mode_not_armed"
    if mode == "paper" and pm.get("startDate") and D.isoformat() < pm["startDate"]: return [], [], [], "before_paper_start"
    if not trading_day(D, C): return [], [], [], ("weekend" if D.weekday() >= 5 else "holiday")
    close = close_et(D, C)
    # ALL-DAY SESSION (Kevin 2026-11-10 08:13 ET "Maximize your trading speed and run it all day till 4:00" / "In-N-Out Bob and weave"):
    # new buys until cutoff (15:45; close-15 on early-close days), exits only cutoff..flatten, flatten.md at 15:50 (close-10),
    # hard-flatten safety net at 15:55 (close-5) if anything is still held, report from 16:00 (close) once the desk is done, fallback 16:05.
    def cap(hm, mins_before_close): return min(hm, hm_minus(close, mins_before_close))
    cutoff = cap(((C.get("manage") or {}).get("noNewEntriesAfterEt")) or C.get("newEntryCutoffEt") or "10:00", 15)
    flatten_at = cap(desk.get("flattenAtEt") or "11:00", 10)
    hard_at = hm_minus(close, int(f(desk.get("hardFlattenMinutesBeforeClose"), 15)))
    report_earliest = cap(desk.get("reportEarliestEt") or "00:00", 0) if desk.get("reportEarliestEt") else "00:00"
    report_at = hm_minus(close, -int(f(desk.get("reportFallbackMinutesAfterClose"), -8)))
    st_today = st if (st and st.get("sessionDate") == D.isoformat()) else None
    disc = (st_today or {}).get("discretion") or {}
    done_at = (st_today or {}).get("doneAt") or disc.get("doneAt")
    halted = bool(disc.get("halted")) or str((st_today or {}).get("status", "")).startswith("halted")
    flat = not pos and not oo
    if mode == "live" and flat and not live_book_meta(st_today, now, C)["trusted"] and t >= "09:30" and st_today is not None and t < "16:00":
        flat = False   # stale hint: let manage/hard-flatten read the broker themselves
    stale_running = phase_timeout_s("entries", C)
    max_attempts = int(f(desk.get("maxAttempts"), 3))

    def row(p): return ledger_day.get(p) or {}
    def finished(p): return row(p).get("status") in ("done", "skipped")
    def claimable(p):
        r = row(p); s = r.get("status")
        if s in ("done", "skipped"): return False, None
        if s == "running" and r.get("at") and (now - pt(r["at"])).total_seconds() < phase_timeout_s(p, C): return False, "running"
        if int(r.get("attempts", 0)) >= max_attempts:
            esc.append({"phase": p, "msg": f"{p} failed {r.get('attempts')}x (last error: {r.get('error')}) — not retried; tell Kevin",
                        "notifiedAt": r.get("escalatedAt")}); return False, "escalated"
        return True, None
    def add(p, proc, why):
        ok, _ = claimable(p)
        if ok: out.append({"phase": p, "procedure": proc, "attempt": int(row(p).get("attempts", 0)) + 1, "why": why}); return True
        return False
    def is_retry(p): return int(row(p).get("attempts", 0)) >= 1 and row(p).get("status") in ("failed", "running")
    in_fire = lambda p: any(x["phase"] == p for x in out)

    # scan (late catch-up)
    scanned = finished("scan") or (st_today is not None and st_today.get("status") not in (None, "", "stale"))
    if not scanned and t >= "05:30" and t < close:
        if t < "09:10": add("scan", "scan.md", "first fire ≥ 05:30")
        elif t < "10:00": add("scan", "refresh.md", "05:30 scan missed: refresh.md full-scan path")
        else: add("scan", "scan.md", f"late catch-up: fresh state for manage/flatten/report (new buys still allowed until {cutoff})")
    elif scanned and not finished("scan") and not row("scan").get("status"):
        skipped.append({"phase": "scan", "why": "state already scanned for today"})
    scan_now = in_fire("scan")
    # refresh
    if not finished("refresh") and t >= "09:10":
        scan_at = pt(row("scan").get("doneAt")) or pt((st_today or {}).get("scanAt"))
        if scan_now or (scan_at and scan_at.strftime("%H:%M") >= "09:00"): skipped.append({"phase": "refresh", "why": "scan is already fresh (ran ≥ 09:00)"})
        elif t >= "09:33": skipped.append({"phase": "refresh", "why": "refresh window passed (09:10–09:33); entries re-scores live"})
        elif scanned: add("refresh", "refresh.md", "first fire in 09:10–09:33")
    # entries
    if not finished("entries") and t >= "09:33":
        if t >= cutoff: skipped.append({"phase": "entries", "why": f"missed_cutoff (no buys at/after {cutoff})"})
        elif halted and flat: skipped.append({"phase": "entries", "why": "kill switch halted (no new buys)"})
        elif scanned or scan_now:
            add("entries", "entries-backup.md" if is_retry("entries") else "entries.md", f"retry before {cutoff}" if is_retry("entries") else f"first fire in 09:33–{cutoff}")
    # hard flatten (before flatten in the same fire)
    fl_row = row("flatten")
    flatten_running = fl_row.get("status") == "running" and fl_row.get("at") and (now - pt(fl_row["at"])).total_seconds() < stale_running
    if not finished("hard-flatten") and t >= hard_at:
        if flat: skipped.append({"phase": "hard-flatten", "why": "already_flat"})
        elif flatten_running: pass   # flatten.md (claimed at the flatten time) still owns the book; never two flatteners at once
        else: add("hard-flatten", "flatten-backup.md", f"first fire ≥ {hard_at}: hard flatten everything")
    # flatten (11:00; on early-close days still 11:00)
    if not finished("flatten") and t >= flatten_at and (scanned or scan_now) and not in_fire("hard-flatten"):
        add("flatten", "flatten-backup.md" if is_retry("flatten") else "flatten.md", "retry" if is_retry("flatten") else f"first fire ≥ {flatten_at}")
    # manage
    exclusive = any(in_fire(p) for p in ("entries", "flatten", "hard-flatten"))
    mrow = row("manage")
    manage_busy = mrow.get("status") == "running" and mrow.get("at") and (now - pt(mrow["at"])).total_seconds() < f(desk.get("manageClaimSeconds"), 240)
    # an entries / flatten / hard-flatten run from an EARLIER fire that is still working owns the book (it syncs + manages itself)
    excl_running = [p for p in ("entries", "flatten", "hard-flatten") if row(p).get("status") == "running" and row(p).get("at")
                    and (now - pt(row(p)["at"])).total_seconds() < stale_running]
    if "09:30" <= t < close and (scanned or scan_now) and not exclusive and not in_fire("hard-flatten"):
        # all-day: manage every fire through the new-buy window (free slot → fresh scan / recycle), then while anything is held,
        # then post-flatten flat-verify until the desk is done
        need = (not flat) or t < cutoff or (finished("flatten") and not done_at)
        if halted and flat and done_at: need = False
        if need and manage_busy: skipped.append({"phase": "manage", "why": "another manage tick is still running (claim < 240 s)"})
        elif need and excl_running: skipped.append({"phase": "manage", "why": f"{excl_running[0]} (earlier fire) is still running and owns the book"})
        elif need: out.append({"phase": "manage", "procedure": "manage.md", "attempt": 1, "why": "book not flat" if not flat else (f"buy window (scan free slots until {cutoff})" if t < cutoff else "flat-verify / set D6 done")})
    # report
    rep_flag = (st_today or {}).get("reportDeliveredFor") == D.isoformat() or (st_today or {}).get("reportSendAttemptedFor") == D.isoformat()
    if not finished("report") and rep_flag:
        skipped.append({"phase": "report", "why": "recap already delivered/attempted for today (reportDeliveredFor/reportSendAttemptedFor) — never re-send"})
    elif not finished("report") and (scanned or scan_now):
        if t >= report_earliest and ((done_at and finished("flatten")) or t >= report_at):
            if not in_fire("flatten") and not in_fire("hard-flatten"):
                add("report", "report.md", "desk done" if done_at and finished("flatten") else f"≥ {report_at} fallback")
    # premarket research (day-trader prep, Kevin 2026-11-10 16:13 ET): first fire 07:00–09:29, before the 07:30 paper session
    rs_at = desk.get("researchEt") or "07:00"
    if not finished("research") and rs_at <= t < "09:30":
        add("research", "research.md", f"first fire ≥ {rs_at}: news + own reports → kb/watchlist-<D>.json")
    # kb refresh
    if not finished("kb-refresh") and t >= (desk.get("kbRefreshEt") or "18:00"):
        add("kb-refresh", "kb-refresh.md", "first fire ≥ 18:00" + (" (Friday: + weekly block)" if D.weekday() == 4 else ""))
    idle = None if out else ("escalated" if esc else "nothing_due")
    return out, skipped, esc, idle

def procedure_guard(P):
    """Hard guard: refuse to dispatch paper phases if the paper procedure files contain a bare Robinhood order/account tool or a live path."""
    import importlib.util as _iu
    try:
        sp_ = _iu.spec_from_file_location("paper_guard", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "paper_guard.py"))
        g = _iu.module_from_spec(sp_); sp_.loader.exec_module(g)
    except Exception as e: return {"ok": False, "violations": {"paper_guard.py": f"unavailable: {e}"}}
    d = P["procedures"]; bad = {}
    try: files = [x for x in _os.listdir(d) if x.endswith(".md")]
    except FileNotFoundError: return {"ok": False, "violations": {d: "paper procedures dir missing"}}
    END = "# <<< END PAPER MODE BLOCK >>>"
    for fn in files:
        txt = open(_os.path.join(d, fn)).read()
        if END not in txt: bad[fn] = "missing PAPER MODE banner"; continue
        v = g.check_text(txt.split(END, 1)[1])
        if v: bad[fn] = v[:3]
    return {"ok": not bad, "violations": bad}

def ensure_paper(P, C, now):
    """First paper fire: create the paper state dir and a paper week desk (bank = paperMode.startCashUsd). Writes ONLY paper files."""
    if P["mode"] != "paper": return None
    base = _os.path.dirname(P["state"]); _os.makedirs(base, exist_ok=True); _os.makedirs(P["scorecardDir"], exist_ok=True)
    if _os.path.exists(P["weekDesk"]): return None
    cash = f((C.get("paperMode") or {}).get("startCashUsd"), 100.0)  # illustrative default
    b = jload(P["broker"], None) if P.get("broker") else None
    if b: cash = f(b.get("cash"), cash)
    mon = now.date() - timedelta(days=now.weekday())
    wd = {"status": "week_confirmed", "mode": "paper", "paper": True, "accountNumber": ACCOUNT, "weekStart": mon.isoformat(),
          "weekEnd": (mon + timedelta(days=4)).isoformat(), "bankUsd": cash, "bankMode": "full_cash", "weekStartBank": cash,
          "priorWeekEndCash": cash, "maxPositions": 2, "stopLossPct": -2.0, "days": {}, "weekToDate": {}, "revisions": [],
          "deposits": [], "depositsUsdThisWeek": 0.0, "errorsAutoFixed": [], "improvementsApplied": [], "pendingProposals": [],
          "createdBy": "desk_clock.py ensure_paper", "createdAt": iso(now),
          "note": "PAPER-MODE week desk (simulated broker book paper_broker.py). The live week-desk.json is never written in paper mode."}
    jsave(P["weekDesk"], wd); return P["weekDesk"]

def run(a, claim):
    C = cfg(); now = pt(a.now) if a.now else datetime.now(ET); P = paths(C)
    if a.state: P["state"] = a.state
    seeded = None
    ledger_p = a.ledger or P["ledger"]; state_p = a.state or P["state"]
    if a.broker: P["broker"] = a.broker
    st = jload(state_p, None); pos, oo = book(P, st)
    D = now.date().isoformat()
    with Locked(ledger_p):
        L = jload(ledger_p, {}) or {}
        day = L.get(D) or {}
        expired = expire_stuck(day, now, C) if claim else []
        if expired: L[D] = day; jsave(ledger_p, L)
        phases, skipped, esc, idle = decide(now, C, day, st, pos, oo)
        guard = None
        if P["mode"] == "paper" and phases:
            guard = procedure_guard(P)
            if not guard["ok"]:
                esc.append({"phase": "paper-guard", "msg": "PAPER GUARD: paper procedures contain a live tool call or live path; nothing dispatched: "
                            + json.dumps(guard["violations"])[:600], "notifiedAt": (day.get("paperGuard") or {}).get("escalatedAt")})
                phases = []; idle = "paper_guard_tripped"
        new_esc = [e for e in esc if not e.get("notifiedAt")]
        if claim and new_esc:
            for e in new_esc:
                if e["phase"] == "paper-guard": day["paperGuard"] = {"escalatedAt": iso(now)}
                elif e["phase"] == "bank-stop": day["bankStopEsc"] = {"escalatedAt": iso(now)}
                elif e["phase"] in day: day[e["phase"]]["escalatedAt"] = iso(now)
            L[D] = day; jsave(ledger_p, L)
        if claim and phases: seeded = ensure_paper(P, C, now)
        if claim and (phases or skipped):
            for p in phases:
                r = dict(day.get(p["phase"]) or {})
                if p["phase"] in EVERY:
                    r.update({"status": "running", "at": iso(now), "fires": int(r.get("fires", 0)) + 1}); day[p["phase"]] = r; continue
                r.update({"status": "running", "at": iso(now), "attempts": int(r.get("attempts", 0)) + 1, "procedure": p["procedure"]})
                day[p["phase"]] = r
            for s in skipped:
                if s["phase"] in ONCE and not (day.get(s["phase"]) or {}).get("status") in ("done", "skipped", "running"):
                    day[s["phase"]] = {"status": "skipped", "at": iso(now), "why": s["why"]}
            day.setdefault("fires", []).append({"at": iso(now), "phases": [p["phase"] for p in phases]})
            day["fires"] = day["fires"][-400:]
            L[D] = day; L = {k: v for k, v in L.items() if k >= (now.date() - timedelta(days=21)).isoformat()}
            jsave(ledger_p, L)
    out = {"now": iso(now), "date": D, "executionMode": P["mode"], "phases": phases, "skipped": skipped,
           "escalate": [e["msg"] for e in new_esc], "escalatedEarlier": [e["msg"] for e in esc if e.get("notifiedAt")],
           "idle": idle is not None and not phases, "idleReason": idle,
           "book": ({"positions": pos, "openOrders": len(oo)} if oo is not None else dict({"positions": pos, "openOrders": None}, **live_book_meta(st, now, C))),
           "paths": P, "claimed": bool(claim), "seeded": seeded, "autoExpired": expired if claim else []}
    if any(p.get("mode") == "paper" for p in phases):
        out["paperSession"] = premarket_paths(C, D)
        out["paperRule"] = ("PREMARKET PAPER: run these phases with paths from paperSession ONLY, every helper with env DESK_PAPER_SESSION=1 "
                            "PAPER_BROKER=<paperSession.broker> PAPER_PREMARKET_TEST=1; orders via paper_broker.py (PAPER.<tool>); NEVER call a Robinhood "
                            "order/write tool or touch live state. Robinhood market-data reads are fine.")
        out["forbiddenTools"] = FORBIDDEN_PAPER
    t = now.strftime("%H:%M"); PP = C.get("premarketPaper") or {}
    armed = (C.get("liveMode") or {}).get("armed") is True and not (C.get("desk") or {}).get("paused") and P["mode"] == "live"
    out["session"] = ("paper-premarket" if any(p.get("mode") == "paper" for p in phases) else ("live" if armed and t >= (PP.get("liveSwitchEt") or "09:30") else "off"))
    out["liveSwitch"] = {"at": PP.get("liveSwitchEt") or "09:30", "automatic": True, "confirmation": "none (Kevin standing authorization 2026-11-10 16:09 ET)",
                         "willGoLive": bool(armed), "blockedBy": None if armed else ("paused" if (C.get("desk") or {}).get("paused") else "liveMode.armed false / not live")}
    bsr = bank_stop_rec(C)
    if bsr.get("tripped"):
        out["session"] = "stopped"; out["liveSwitch"].update({"willGoLive": False, "blockedBy": "bankStop tripped (equity ≤ 50% of baseline) — Kevin restart only"})
        out["bankStop"] = {"tripped": True, "trippedAt": bsr.get("trippedAt"), "equityUsd": bsr.get("trippedEquityUsd"), "baselineUsd": bsr.get("baselineUsd"),
                           "flattenDone": bool(bsr.get("flattenDone")), "restart": "Kevin only: risk_floors.py bank-restart --by \"Kevin <words, time>\""}
    elif any(p["phase"] in ("scan", "refresh", "manage", "entries", "entries-backup", "flatten", "hard-flatten", "paper-premarket", "paper-summary") for p in phases) and P["mode"] == "live":
        out["riskFloors"] = ("HARD FLOORS every fire: (1) BANK STOP — get_portfolio(account_number=ACCOUNT) → risk_floors.py bank-check --portfolio <raw> --apply; exit 9 → STOP this "
                             "procedure, run bank-stop.md, hand its escalation to the parent at once. (2) 5% TRADE CAP — with fresh positions + quotes + orders → "
                             "risk_floors.py trade-cap; exit 8 → cancel those sells, verify, market-sell NOW before any other decision. Stops: stopargs --entry <avg> "
                             "(never wider than −5%).")
    SHc = C.get("paperShadow") or {}
    if SHc.get("enabled") and P["mode"] == "live" and armed and not bsr.get("tripped") and "09:30" <= t <= (SHc.get("endEt") or "15:45") \
            and any(p["phase"] in ("manage", "entries", "entries-backup") for p in phases):
        out["paperShadow"] = {"run": "LAST, after every live step of this fire, only if this fire has run < %ss" % int(SHc.get("skipIfFireElapsedS", 150)),
                              "cmd": "python3 /workspace/paper/paper_shadow.py tick --date %s --quotes <this fire's quotes file> --bars5 <this fire's 5m bars file> --candidates <playbook-refused candidates json> --budget-s %s" % (D, SHc.get("budgetS", 20)),
                              "rule": "PAPER ONLY: no broker calls, no extra market-data calls beyond what the live fire already fetched, never touches live state/P&L/kill switch/RT cap/bank stop"}
    if P["mode"] == "live" and armed and "09:30" <= t < "16:00" and any(p["phase"] in ("manage", "entries", "flatten", "hard-flatten") for p in phases):
        out["protectFirst"] = ("BEFORE anything else: fresh get_equity_positions + get_equity_orders → reconcile.py verify-protection --apply; exit 7 → rest/replace the "
                               "stop_limit (stopargs-checked) for every unprotected or wrong-type position and re-verify; NO new buys this fire until it exits 0.")
    if P["mode"] == "paper":
        out["forbiddenTools"] = FORBIDDEN_PAPER
        out["paperBrokerTools"] = PAPER_BROKER_TOOLS
        out["rule"] = "PAPER MODE: never call any forbiddenTools on Robinhood; every order/account read goes to paper_broker.py (PAPER.<tool>)."
    print(json.dumps(out, indent=1)); return 0

def mark(a, status):
    C = cfg(); now = pt(a.now) if a.now else datetime.now(ET); P = paths(C); ledger_p = a.ledger or P["ledger"]; D = now.date().isoformat()
    if a.phase not in ONCE + EVERY: print(json.dumps({"ok": False, "why": f"unknown phase {a.phase}"})); return 2
    with Locked(ledger_p):
        L = jload(ledger_p, {}) or {}; day = L.setdefault(D, {}); r = dict(day.get(a.phase) or {})
        if a.phase in EVERY:
            r.update({"status": "idle" if status == "done" else "failed", "lastEndAt": iso(now)})
            if status == "failed": r["lastError"] = a.error
        else:
            if r.get("status") == "done" and status == "done": print(json.dumps({"ok": True, "phase": a.phase, "already": "done"})); return 0
            r.update({"status": status, ("doneAt" if status == "done" else "failedAt"): iso(now)})
            if status == "done": r["note"] = a.note
            else: r["error"] = a.error
            r.setdefault("attempts", 1)
        day[a.phase] = r; jsave(ledger_p, L)
    res = {"ok": True, "phase": a.phase, "status": r["status"], "attempts": r.get("attempts")}
    if status == "failed" and int(r.get("attempts", 1)) >= int(f((C.get("desk") or {}).get("maxAttempts"), 3)): res["escalate"] = True
    print(json.dumps(res)); return 0

def status(a):
    C = cfg(); now = pt(a.now) if a.now else datetime.now(ET); P = paths(C); L = jload(a.ledger or P["ledger"], {}) or {}
    print(json.dumps({"date": now.date().isoformat(), "ledger": L.get(now.date().isoformat(), {})}, indent=1)); return 0
def reset_day(a):
    C = cfg(); P = paths(C); p = a.ledger or P["ledger"]
    if not a.force: print(json.dumps({"ok": False, "why": "pass --force"})); return 4
    with Locked(p):
        L = jload(p, {}) or {}; L.pop(a.date, None); jsave(p, L)
    print(json.dumps({"ok": True, "reset": a.date})); return 0

def report_claim(a):
    """Atomic once-only recap guard: set state.reportSendAttemptedFor = D before handing the recap to the parent.
    ok:false → a recap for D was already delivered or handed off: send NOTHING."""
    C = cfg(); now = pt(a.now) if a.now else datetime.now(ET); P = paths(C); sp_ = a.state or P["state"]; D = a.date or now.date().isoformat()
    with Locked(sp_):
        st = jload(sp_, {}) or {}
        if st.get("reportDeliveredFor") == D or st.get("reportSendAttemptedFor") == D:
            print(json.dumps({"ok": False, "date": D, "why": "recap already delivered/handed off for this date — do not send again",
                              "reportDeliveredFor": st.get("reportDeliveredFor"), "reportSendAttemptedFor": st.get("reportSendAttemptedFor")})); return 3
        st["reportSendAttemptedFor"] = D; st["reportSendAttemptedAt"] = iso(now); jsave(sp_, st)
    print(json.dumps({"ok": True, "date": D, "next": "hand the recap to the parent ONCE, then statewrite reportDeliveredFor"})); return 0

def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    for nm in ("next", "plan", "status"):
        x = sp.add_parser(nm); x.add_argument("--now"); x.add_argument("--ledger"); x.add_argument("--state"); x.add_argument("--broker")
    for nm in ("done", "failed"):
        x = sp.add_parser(nm); x.add_argument("--phase", required=True); x.add_argument("--note"); x.add_argument("--error"); x.add_argument("--now"); x.add_argument("--ledger")
    x = sp.add_parser("report-claim"); x.add_argument("--date"); x.add_argument("--state"); x.add_argument("--now")
    x = sp.add_parser("reset-day"); x.add_argument("--date", required=True); x.add_argument("--force", action="store_true"); x.add_argument("--ledger")
    a = ap.parse_args(argv)
    if a.cmd == "next": return run(a, True)
    if a.cmd == "plan": return run(a, False)
    if a.cmd == "status": return status(a)
    if a.cmd == "done": return mark(a, "done")
    if a.cmd == "failed": return mark(a, "failed")
    if a.cmd == "reset-day": return reset_day(a)
    if a.cmd == "report-claim": return report_claim(a)

if __name__ == "__main__":
    sys.exit(main())
