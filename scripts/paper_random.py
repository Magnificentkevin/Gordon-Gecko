#!/usr/bin/env python3
# This copy ships with the silas-equity-desk Claude skill.
# Sanitized: no hardcoded account ids or secrets. Broker layer is a broker MCP (e.g. Robinhood). Times are America/New_York.
"""paper_random.py — v0 RANDOM-ENTRY BASELINE paper book (stress test 2026-11-22).

Why: a strategy can pass backtest, walk-forward and Monte Carlo and still be no better than buying at random from the same
shortlist (QuantBot cleanroom test, 2026-11-22). v0 answers "are the entry rules doing the work, or the scanner?" It trades the SAME
shortlist as v1 with the SAME sizing and exits, but picks WHICH name and WHEN at random. If v1 can't beat v0, the entry rules add nothing.

ISOLATION (hard, same as paper_shadow.py): never calls a broker, never reads or writes live state, P&L, kill switch, RT cap or bank stop;
writes ONLY under config paperRandom.stateDir (refuses any other path). Rows are labeled paper=True, source="paper_random".

  init    --date D [--cash X]
  tick    --date D --quotes <get_equity_quotes raw> --shortlist <json file|json list of symbols> [--bars5 <5m raw>] [--now ISO]
            shortlist = every symbol that passed the scanner's hard filters this fire (the pool v1 chose from), NOT v1's picks.
  summary --date D
  compare --v1 <json file of v1 round trips, each with pnlPct> [--since YYYY-MM-DD]
            v1 vs v0 over the same period: n, mean R, t-stat of the difference, verdict.
  edge    --trades <json file of round trips with pnlPct> [--stop-pct 5]
            the promotion check: mean R, standard error, t-stat, lower 95% bound, trades needed. PROMOTE only if t >= 2.

Exits mirror paper_shadow.py: hard stop (trigger entry×0.955, fill no better than entry×0.95 unless the bid is higher), −2%/decision-point
recovery score when 5m bars are given, stall exit, TP floor (tpModel.floorPct), +2% trailing lock, flatten at paperRandom.flattenEt (15:50).
Sizing mirrors live: qty = floor(equity × riskSizing.riskPct% / (ask − ask×0.95)), capped by cash × cashCapFrac / ask.
Randomness is seeded from the date and the fire's minute, so a session replays identically.
"""
import argparse, hashlib, json, math, os, random, statistics, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.environ.get("RECONCILE_CONFIG") or os.environ.get("DESK_CONFIG") or "/workspace/robinhood-fable-agent/config/equity-morning-session.json"
DEFAULT_DIR = os.path.join(os.environ.get("DESK_DATA") or "/workspace/robinhood-fable-agent/data", "equity-paper", "random-baseline")


def jload(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return d


def num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def cfg():
    return jload(CFG, {}) or {}


def RB(C):
    return C.get("paperRandom") or {}


def base(C):
    return os.path.realpath(RB(C).get("stateDir") or DEFAULT_DIR)


def paths(C, D):
    b = base(C)
    return {"dir": f"{b}/{D}", "book": f"{b}/{D}/book.json", "state": f"{b}/{D}/state.json", "journal": f"{b}/random-decisions.jsonl"}


def safe_save(C, p, obj):
    rp = os.path.realpath(p)
    if not rp.startswith(base(C) + os.sep):
        raise SystemExit(json.dumps({"ok": False, "why": f"paper_random refuses to write outside {base(C)}: {p}"}))
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    t = rp + ".tmp"
    json.dump(obj, open(t, "w"), indent=1)
    os.replace(t, rp)


def journal(C, row):
    rp = os.path.realpath(paths(C, "x")["journal"])
    if not rp.startswith(base(C) + os.sep):
        raise SystemExit("journal outside random-baseline dir")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "a") as fh:
        fh.write(json.dumps(dict(row, paper=True, source="paper_random")) + "\n")


def quotes(raw):
    d = jload(raw, {}) if isinstance(raw, str) else (raw or {})
    d = d.get("data", d) if isinstance(d, dict) else {}
    out = {}
    for r in (d.get("results") or []) if isinstance(d, dict) else []:
        q = r.get("quote", r)
        s = str(q.get("symbol", "")).upper()
        bid = num(q.get("bid_price")) or num(q.get("last_trade_price"))
        ask = num(q.get("ask_price")) or num(q.get("last_trade_price")) or bid
        if s and bid > 0:
            out[s] = {"bid": bid, "ask": ask}
    return out


def shortlist(arg):
    if not arg:
        return []
    v = jload(arg, None)
    if v is None:
        try:
            v = json.loads(arg)
        except Exception:
            v = []
    syms = []
    for x in v if isinstance(v, list) else []:
        s = x.get("symbol") if isinstance(x, dict) else x
        if s:
            syms.append(str(s).upper())
    return sorted(set(syms))


def recovery():
    try:
        import importlib.util as u
        sp = u.spec_from_file_location("recovery", f"{HERE}/recovery.py")
        m = u.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m
    except Exception:
        return None


def init(C, D, cash=None, now=None):
    P = paths(C, D)
    if os.path.exists(P["book"]):
        return jload(P["book"])
    sc = cash if cash is not None else num(RB(C).get("startCashUsd"), num((C.get("paperShadow") or {}).get("startCashUsd"), 100.0))
    book = {"date": D, "startCash": round(sc, 2), "cash": round(sc, 2), "positions": {}, "paper": True, "book": "v0_random",
            "createdAt": (now or datetime.now(ET)).isoformat(timespec="seconds")}
    safe_save(C, P["book"], book)
    safe_save(C, P["state"], {"sessionDate": D, "mode": "paper_random", "roundTrips": [], "losers": []})
    return book


def rng_for(D, now):
    seed = int(hashlib.sha256(f"v0:{D}:{now.strftime('%H:%M')}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def tick(C, D, q, syms, bars5=None, now=None):
    now = now or datetime.now(ET)
    hm = now.strftime("%H:%M")
    R0 = RB(C)
    start, cut, flat = R0.get("entryStartEt") or "09:35", R0.get("noNewBuysAfterEt") or C.get("newEntryCutoffEt") or "15:45", R0.get("flattenEt") or "15:50"
    if not ("09:30" <= hm <= flat):
        return {"ok": True, "skipped": "outside session"}
    P = paths(C, D)
    book = jload(P["book"]) or init(C, D, now=now)
    st = jload(P["state"], {}) or {"sessionDate": D, "roundTrips": [], "losers": []}
    floor = num((C.get("tpModel") or {}).get("floorPct"), 5.0)
    stall_m = num((C.get("stallExit") or {}).get("afterMinutes"), 14)
    REC = recovery() if bars5 else None
    acts = []

    def close(sym, px, why):
        p = book["positions"].pop(sym)
        pnl = (px - p["entry"]) * p["qty"]
        book["cash"] = round(book["cash"] + px * p["qty"], 4)
        rt = {"symbol": sym, "setup": "v0_random", "qty": p["qty"], "entryPrice": p["entry"], "entryAt": p["at"], "exitPrice": round(px, 4),
              "exitAt": now.isoformat(timespec="seconds"), "pnlUsd": round(pnl, 4), "pnlPct": round((px / p["entry"] - 1) * 100, 3),
              "reason": why, "paper": True, "source": "paper_random"}
        st["roundTrips"].append(rt)
        if pnl < 0:
            st.setdefault("losers", []).append(sym)
        acts.append({"exit": sym, "why": why, "pnlUsd": rt["pnlUsd"]})
        journal(C, {"type": "exit", "date": D, **rt})

    # 1. manage held positions: same exits as the other paper books
    for sym in list(book["positions"]):
        p = book["positions"][sym]
        qq = q.get(sym)
        if not qq:
            continue
        bid, e = qq["bid"], p["entry"]
        p["hw"] = max(p["hw"], bid)
        mins = (now - datetime.fromisoformat(p["at"])).total_seconds() / 60
        trail = max(e * 1.005, p["hw"] * 0.98) if p["hw"] >= e * 1.02 else None
        if hm >= flat:
            close(sym, bid, "flatten")
        elif bid <= e * 0.955:
            close(sym, max(min(bid, e * 0.955), e * 0.95) if bid >= e * 0.95 else bid, "hard_stop")
        elif bid >= e * (1 + floor / 100):
            close(sym, bid, "tp_floor")
        elif trail and bid <= trail:
            close(sym, bid, "trail_lock")
        elif mins >= stall_m and p["hw"] < e * 1.01 and bid < e * 1.005:
            close(sym, bid, "stall_exit")
        elif REC and bid <= e * (1 + getattr(REC, "DECISION_PCT", -2.0) / 100):
            try:
                w, T = REC.model(C, hm)
                sc = REC.score(REC.bars_of(bars5, sym), e, bid, spy5=REC.bars_of(bars5, "SPY"), weights=w, threshold=T)
                if sc["decision"] == "exit":
                    close(sym, bid, f"recovery_score_exit {sc['score']}")
            except Exception:
                pass

    # 2. random entry: same pool, sizing, caps and kill switch as live; random name, random timing
    mx = int(R0.get("maxPositions", C.get("maxPositions", 2) or 2))
    max_rt = int(R0.get("maxRoundTrips", 4))
    p_enter = num(R0.get("entryProbPerFire"), 0.25)
    losing_stops = sum(1 for r in st["roundTrips"] if r["reason"] == "hard_stop")
    day_pnl = sum(r["pnlUsd"] for r in st["roundTrips"])
    killed = losing_stops >= 2 or day_pnl <= -0.03 * book["startCash"]
    rnd = rng_for(D, now)
    pool = [s for s in syms if s not in book["positions"] and s not in st.get("losers", []) and s in q and q[s]["ask"] > 0]
    if (start <= hm < cut and not killed and pool and len(book["positions"]) < mx and len(st["roundTrips"]) + len(book["positions"]) < max_rt
            and rnd.random() < p_enter):
        s = rnd.choice(pool)
        ask = q[s]["ask"]
        rs = (C.get("discretion") or {}).get("riskSizing") or C.get("riskSizing") or {}   # live sizing lives under discretion
        rp, cf = num(rs.get("riskPct"), 1.0), num(rs.get("cashCapFrac"), 0.95)
        eq = book["cash"] + sum(v["qty"] * v["entry"] for v in book["positions"].values())
        risk = ask - ask * 0.95
        qty = min(int(math.floor(eq * rp / 100 / risk)), int(math.floor(book["cash"] * cf / ask))) if risk > 0 else 0
        if qty >= 1:
            book["cash"] = round(book["cash"] - qty * ask, 4)
            book["positions"][s] = {"qty": qty, "entry": ask, "at": now.isoformat(timespec="seconds"), "hw": ask}
            acts.append({"buy": s, "qty": qty, "px": ask, "pool": len(pool)})
            journal(C, {"type": "entry", "date": D, "symbol": s, "price": ask, "qty": qty, "pool": len(pool), "at": now.isoformat(timespec="seconds")})
    safe_save(C, P["book"], book)
    safe_save(C, P["state"], st)
    return {"ok": True, "actions": acts, "held": list(book["positions"]), "cash": book["cash"], "killSwitch": killed}


def summary(C, D):
    P = paths(C, D)
    st, book = jload(P["state"], {}) or {}, jload(P["book"], {}) or {}
    rts = st.get("roundTrips") or []
    w = sum(1 for r in rts if r["pnlUsd"] > 0)
    end = book.get("cash", 0) + sum(p["qty"] * p["entry"] for p in (book.get("positions") or {}).values())
    return {"date": D, "wl": [w, len(rts) - w], "startCash": book.get("startCash"), "endCash": round(end, 2),
            "line": f"PAPER v0 RANDOM — {D}: W/L {w}/{len(rts) - w} | paper ${num(book.get('startCash')):.2f} → ${end:.2f}"}


def r_list(rows, stop_pct=5.0, since=None):
    out = []
    for r in rows or []:
        d = str(r.get("date") or r.get("exitAt") or "")[:10]
        if since and d and d < since:
            continue
        if r.get("pnlPct") is not None:
            out.append(num(r["pnlPct"]) / stop_pct)
    return out


def edge(rs):
    n = len(rs)
    if n < 2:
        return {"n": n, "verdict": "NOT ENOUGH TRADES"}
    m, sd = statistics.fmean(rs), statistics.stdev(rs)
    se = sd / math.sqrt(n)
    t = m / se if se > 0 else 0.0
    need = math.ceil((2 * sd / m) ** 2) if m > 0 else None
    return {"n": n, "meanR": round(m, 4), "sdR": round(sd, 4), "seR": round(se, 4), "t": round(t, 2), "lower95R": round(m - 1.96 * se, 4),
            "tradesNeededForT2": need,
            "verdict": "EDGE SHOWN (t >= 2)" if t >= 2 else ("POSITIVE BUT NOT PROVEN" if m > 0 else "NO EDGE")}


def compare(C, v1_rows, since=None, stop_pct=5.0):
    v0_rows = [r for r in (json.loads(l) for l in open(paths(C, "x")["journal"])) if r.get("type") == "exit"] if os.path.exists(paths(C, "x")["journal"]) else []
    a, b = r_list(v1_rows, stop_pct, since), r_list(v0_rows, stop_pct, since)
    out = {"v1": edge(a), "v0_random": edge(b)}
    if len(a) >= 2 and len(b) >= 2:
        diff = statistics.fmean(a) - statistics.fmean(b)
        se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
        t = diff / se if se > 0 else 0.0
        out["v1_minus_v0"] = {"meanR": round(diff, 4), "t": round(t, 2),
                              "verdict": "v1 BEATS RANDOM (t >= 2)" if t >= 2 else ("v1 ahead, not proven" if diff > 0 else "v1 NOT BETTER THAN RANDOM")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="v0 random-entry baseline paper book")
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("init"); x.add_argument("--date", required=True); x.add_argument("--cash", type=float); x.add_argument("--now")
    y = sp.add_parser("tick"); y.add_argument("--date", required=True); y.add_argument("--quotes", required=True)
    y.add_argument("--shortlist", required=True); y.add_argument("--bars5"); y.add_argument("--now")
    z = sp.add_parser("summary"); z.add_argument("--date", required=True)
    c = sp.add_parser("compare"); c.add_argument("--v1", required=True); c.add_argument("--since"); c.add_argument("--stop-pct", type=float, default=5.0)
    e = sp.add_parser("edge"); e.add_argument("--trades", required=True); e.add_argument("--stop-pct", type=float, default=5.0); e.add_argument("--since")
    a = ap.parse_args(argv)
    C = cfg()
    now = datetime.fromisoformat(a.now).astimezone(ET) if getattr(a, "now", None) else datetime.now(ET)
    if a.cmd not in ("edge", "compare") and not RB(C).get("enabled", True):
        print(json.dumps({"ok": True, "skipped": "paperRandom disabled"})); return 0
    if a.cmd == "init":
        print(json.dumps(init(C, a.date, a.cash, now))); return 0
    if a.cmd == "tick":
        bars = jload(a.bars5, None) if a.bars5 else None
        print(json.dumps(tick(C, a.date, quotes(a.quotes), shortlist(a.shortlist), bars, now))); return 0
    if a.cmd == "summary":
        print(json.dumps(summary(C, a.date))); return 0
    if a.cmd == "compare":
        print(json.dumps(compare(C, jload(a.v1, []) or [], a.since, a.stop_pct), indent=1)); return 0
    if a.cmd == "edge":
        print(json.dumps(edge(r_list(jload(a.trades, []) or [], a.stop_pct, a.since)), indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
