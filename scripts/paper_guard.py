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

"""paper_guard.py — HARD GUARD for PAPER MODE (config executionMode="paper"; Kevin 2026-10-23 "Rebuild whole system in one routine. Run
paper test and debug single routine."). Paper mode = NO live Robinhood order of any kind.

Three layers (all fail CLOSED: a missing/unreadable config counts as paper):
 1. CODE GUARD (imported by reconcile.py / shadow_orb.py / desk_clock.py): `assert_writable(path)` refuses (exit 5) any write to the LIVE
    desk data dir (config paperMode.liveStateDir, default /workspace/robinhood-fable-agent/data/equity-paper) outside the paper stateDir,
    and any write to the config file itself, while executionMode is paper. So a paper run can never touch live state.
 2. PROCEDURE GUARD: `python3 paper_guard.py check-procedures [--dir D]` proves the paper procedure files the single routine reads contain
    NO bare Robinhood order/account tool call (every one is rewritten to PAPER.<tool> = paper_broker.py) and NO live state path.
 3. TOOL-CALL GUARD + LIVE TRIPWIRE:
      python3 paper_guard.py check-call --tool <mcp tool name>        exit 0 allowed (read-only market data) | exit 5 FORBIDDEN in paper mode
      python3 paper_guard.py check-log --log <jsonl/json list of tool names or {"tool":..} rows>   every call in a run transcript
      python3 paper_guard.py audit --orders <read-only live get_equity_orders raw> [--since ISO]  any LIVE order created since paper
           mode started (paperMode.startedAt) → exit 6 + "ALERT" line (the routine tells Kevin at once).
Live mode (executionMode "live" AND liveMode.armed true) disables layer 1 and the forbidden list; it is OFF (only Kevin arms it)."""
import os as _os, json, sys, argparse, re
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CONFIG = _os.environ.get("RECONCILE_CONFIG", "/workspace/robinhood-fable-agent/config/equity-morning-session.json")
LIVE_CONFIG = "/workspace/robinhood-fable-agent/config/equity-morning-session.json"
DEFAULT_LIVE_DIR = "/workspace/robinhood-fable-agent/data/equity-paper"
DEFAULT_PAPER_DIR = DEFAULT_LIVE_DIR + "/paper-mode"
# Robinhood MCP tools that place / change / cancel anything, or that would read the LIVE book in place of the paper book.
ORDER_TOOLS = ["place_equity_order", "cancel_equity_order", "review_equity_order", "place_advanced_order", "cancel_advanced_order",
               "review_advanced_order", "place_option_order", "cancel_option_order", "review_option_order", "exercise_option",
               "cancel_option_exercise", "place_crypto_order", "cancel_crypto_order", "preview_crypto_order", "decline_trade_approval",
               "approve_trade", "create_alert", "update_alert", "delete_alert", "mark_alerts_read", "create_scan", "update_scan_filters",
               "update_scan_config", "delete_scan", "create_watchlist", "update_watchlist", "add_to_watchlist", "remove_from_watchlist",
               "add_option_to_watchlist", "remove_option_from_watchlist", "follow_watchlist", "unfollow_watchlist", "add_legend_indicator",
               "remove_legend_indicator", "update_legend_indicator", "set_legend_chart_settings"]
# Account/book reads go to the PAPER broker in paper mode (the live book is not the desk's book). One exception: the tripwire's own
# read-only live get_equity_orders call, made only via `audit` and never fed to reconcile.py.
PAPER_BOOK_TOOLS = ["get_accounts", "get_portfolio", "get_equity_positions", "get_equity_orders", "get_realized_pnl", "get_pnl_trade_history"]
PAPER_BROKER_TOOLS = PAPER_BOOK_TOOLS + ["review_equity_order", "place_equity_order", "cancel_equity_order"]
LIVE_READ_OK = ["get_equity_quotes", "get_equity_historicals", "get_equity_technical_indicators", "preview_scan", "get_equity_tradability",
                "get_equity_fundamentals", "get_sec_filing_index", "get_earnings_calendar", "get_market_hours", "get_top_movers",
                "get_equity_instruments", "search_instruments", "get_news"]

def cfg():
    try: return json.load(open(CONFIG))
    except Exception: return {}
def mode(C=None):
    C = cfg() if C is None else C
    m = C.get("executionMode") or "paper"
    if m == "live" and (C.get("liveMode") or {}).get("armed") is True: return "live"
    return "paper"          # anything else (missing, typo, live-but-not-armed) is treated as paper: fail closed
def dirs(C=None):
    C = cfg() if C is None else C; pm = C.get("paperMode") or {}
    return (_os.path.realpath(pm.get("liveStateDir") or DEFAULT_LIVE_DIR), _os.path.realpath(pm.get("stateDir") or DEFAULT_PAPER_DIR))
def inside(p, d): return p == d or p.startswith(d.rstrip("/") + "/")

class PaperGuardError(Exception): pass
def check_writable(path, C=None):
    """None if writing `path` is allowed now, else the refusal text."""
    C = cfg() if C is None else C
    if mode(C) == "live" or not path: return None
    p = _os.path.realpath(_os.path.abspath(path)); live, paper = dirs(C)
    if p == _os.path.realpath(LIVE_CONFIG):
        return f"PAPER GUARD: {path} is the desk config (read-only in paper mode; the daily revise is propose-only)"
    if inside(p, live) and not inside(p, paper):
        return f"PAPER GUARD: {path} is LIVE desk data ({live}); paper mode writes only under {paper}"
    return None
def assert_writable(*paths, C=None):
    for p in paths:
        why = check_writable(p, C)
        if why:
            print(json.dumps({"ok": False, "refused": why, "guard": "paper_guard", "executionMode": "paper"})); sys.exit(5)

def check_call(tool, C=None):
    """(allowed: bool, why)."""
    C = cfg() if C is None else C
    t = (tool or "").split(".")[-1].split("__")[-1]
    if mode(C) == "live": return True, "live mode armed"
    if t in ORDER_TOOLS: return False, f"{t} is a Robinhood order/write tool: FORBIDDEN in paper mode (use PAPER.{t} → paper_broker.py)" if t in PAPER_BROKER_TOOLS else f"{t}: FORBIDDEN in paper mode"
    if t in PAPER_BOOK_TOOLS: return False, f"{t} must go to the PAPER broker in paper mode (PAPER.{t} → paper_broker.py), not the live account"
    return True, "read-only market data" if t in LIVE_READ_OK else "not a Robinhood order/account tool"

BARE = re.compile(r"(?<![\w.])(" + "|".join(sorted(set(ORDER_TOOLS + PAPER_BOOK_TOOLS), key=len, reverse=True)) + r")\b")
def check_text(text, live_dir=DEFAULT_LIVE_DIR, paper_dir=DEFAULT_PAPER_DIR):
    bad = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in BARE.finditer(line):
            bad.append({"line": i, "what": f"bare tool {m.group(1)} (must be PAPER.{m.group(1)})", "text": line.strip()[:160]})
        for m in re.finditer(re.escape(live_dir.rstrip("/")) + r"(/[\w.<>\-]*)?", line):
            if not (m.group(0) + "/").startswith(paper_dir.rstrip("/") + "/") and not m.group(0) == paper_dir:
                bad.append({"line": i, "what": f"live data path {m.group(0)}", "text": line.strip()[:160]})
    return bad

def cmd_check_procedures(a):
    C = cfg(); pm = C.get("paperMode") or {}
    d = a.dir or pm.get("proceduresDir") or "/workspace/equity-am-desk/live/paper"
    live, paper = (pm.get("liveStateDir") or DEFAULT_LIVE_DIR), (pm.get("stateDir") or DEFAULT_PAPER_DIR)
    files = sorted(x for x in _os.listdir(d) if x.endswith(".md"))
    res = {}
    for fn in files:
        txt = open(_os.path.join(d, fn)).read(); END = "# <<< END PAPER MODE BLOCK >>>"
        if fn != "desk.md" and END not in txt:
            res[fn] = [{"line": 1, "what": "missing the PAPER MODE banner", "text": ""}]; continue
        body = txt.split(END, 1)[1] if END in txt else txt      # the banner names the forbidden tools in prose on purpose
        bad = check_text(body, live, paper)
        if bad: res[fn] = bad
    out = {"ok": not res and bool(files), "dir": d, "files": files, "violations": res}
    print(json.dumps(out, indent=1)); return 0 if out["ok"] else 5

def cmd_check_call(a):
    ok, why = check_call(a.tool); print(json.dumps({"tool": a.tool, "allowed": ok, "why": why, "executionMode": mode()})); return 0 if ok else 5

def load_calls(p):
    t = open(p).read().strip(); rows = []
    try:
        d = json.loads(t); rows = d if isinstance(d, list) else d.get("calls", [])
    except json.JSONDecodeError:
        rows = [json.loads(l) for l in t.splitlines() if l.strip()]
    return [(r if isinstance(r, str) else (r.get("tool") or r.get("name") or "")) for r in rows]
def cmd_check_log(a):
    bad = []
    for t in load_calls(a.log):
        ok, why = check_call(t)
        if not ok: bad.append({"tool": t, "why": why})
    print(json.dumps({"ok": not bad, "forbiddenCalls": bad, "executionMode": mode()})); return 0 if not bad else 5

def pt(s):
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00")); return (d if d.tzinfo else d.replace(tzinfo=ET)).astimezone(ET)
def cmd_audit(a):
    C = cfg(); since = pt(a.since or (C.get("paperMode") or {}).get("startedAt") or "1970-01-01T00:00:00Z")
    t = open(a.orders).read(); i = min([k for k in (t.find("{"), t.find("[")) if k >= 0]); j = max(t.rfind("}"), t.rfind("]"))
    d = json.loads(t[i:j + 1]); d = d.get("data", d) if isinstance(d, dict) else d
    rows = d.get("orders", d.get("results", [])) if isinstance(d, dict) else d
    if any(r.get("paper") for r in rows):
        print(json.dumps({"ok": False, "why": "this file is a PAPER broker snapshot; audit needs the read-only LIVE get_equity_orders output"})); return 2
    hits = [{"id": r.get("id"), "symbol": r.get("symbol"), "side": r.get("side"), "state": r.get("state"), "created_at": r.get("created_at")}
            for r in rows if r.get("created_at") and pt(r["created_at"]) >= since]
    if hits:
        print("ALERT: LIVE Robinhood order(s) created while the desk is in PAPER mode: " + ", ".join(f"{h['symbol']} {h['side']} {h['state']} {h['created_at']}" for h in hits))
        print(json.dumps({"ok": False, "liveOrdersSincePaperStart": hits, "since": since.isoformat()})); return 6
    print(json.dumps({"ok": True, "liveOrdersSincePaperStart": 0, "since": since.isoformat(), "checked": len(rows)})); return 0

def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("check-procedures"); x.add_argument("--dir"); x.set_defaults(fn=cmd_check_procedures)
    x = sp.add_parser("check-call"); x.add_argument("--tool", required=True); x.set_defaults(fn=cmd_check_call)
    x = sp.add_parser("check-log"); x.add_argument("--log", required=True); x.set_defaults(fn=cmd_check_log)
    x = sp.add_parser("audit"); x.add_argument("--orders", required=True); x.add_argument("--since"); x.set_defaults(fn=cmd_audit)
    x = sp.add_parser("mode"); x.set_defaults(fn=lambda a: (print(json.dumps({"executionMode": mode(), "dirs": dirs()})), 0)[1])
    a = ap.parse_args(argv); return a.fn(a)
if __name__ == "__main__":
    sys.exit(main())
