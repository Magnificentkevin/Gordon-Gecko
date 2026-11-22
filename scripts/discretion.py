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

"""discretion.py — deterministic calculator for the Equity AM desk DISCRETIONARY SESSION rules (D1, D3, D5, D6).
Kevin 2026-10-17 16:44 / 16:46 ET, from Mon 2026-10-19. NEVER calls the broker; reads the state file + a quotes file.

  status : python3 /workspace/paper/discretion.py status --state <morning-session.json> [--quotes <get_equity_quotes raw>] [--now 2026-10-19T10:05]
           -> dayPnl, kill switch (halt?), consecutive loss stops, target progress, protect mode, lock-floor stops, protect size cap, done?
  hold   : python3 /workspace/paper/discretion.py hold --fill F --bid B --vwap V --resting-stop S [--resting-mode stop|trail|tp] [--fractional-path P]
  size   : python3 /workspace/paper/discretion.py size --state <file> [--quotes q] --ask A --buy-limit L   (protect-mode qty cap)
Prints JSON. Rounding: stops ROUND UP to the tick (>= $1: cent, < $1: 0.0001) exactly like ta.py / tp_model.py.
"""
import os as _os, time as _time
_os.environ["TZ"] = "America/New_York"; _time.tzset()
import argparse, json, math, sys
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
CONFIG = _os.environ.get("DISC_CONFIG", "/workspace/robinhood-fable-agent/config/equity-morning-session.json")
LOSS_STOP = {"resting_stop_limit", "stop_aggressive", "virtual_stop_market", "virtual_stale_exit", "resting_stop_market", "stop_aggressive_inferred"}  # +2 reconcile.py names 2026-10-21 (tightening)
TRAIL = {"trail_stop", "trail_stop_aggressive", "virtual_trail_market", "trail_stop_market"}

def tick(px): return 0.01 if px >= 1 else 0.0001
def up(px):
    t = tick(px); return round(math.ceil(px / t - 1e-9) * t, 4)
def down(px):
    t = tick(px); return round(math.floor(px / t + 1e-9) * t, 4)

def jload(p):
    txt = open(p).read()
    try: return json.loads(txt)
    except json.JSONDecodeError:
        i = min([x for x in (txt.find("{"), txt.find("[")) if x >= 0]); j = max(txt.rfind("}"), txt.rfind("]"))
        return json.loads(txt[i:j + 1])

def quotes(p):
    if not p: return {}
    d = jload(p); d = d.get("data", d) if isinstance(d, dict) else d
    out = {}
    for r in (d.get("results", []) if isinstance(d, dict) else d):
        q = r.get("quote", r); s = (q.get("symbol") or "").upper()
        f = lambda k: float(q[k]) if q.get(k) not in (None, "", "0", 0) else None
        out[s] = {"bid": f("bid_price"), "ask": f("ask_price"), "last": f("last_trade_price"), "state": q.get("state")}
    return out

def cfg():
    try: return json.load(open(CONFIG)).get("discretion", {})
    except Exception: return {}

def num(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def consecutive_loss_stops(rts):
    """Returns (current run, max run today, min cumulative realized, max cumulative realized) in exit-time order.
    FIX 2026-10-17: halt/target are STICKY for the day, so the max run / extremes matter, not just the latest value."""
    n = mx = 0; cum = 0.0; lo = hi = 0.0
    for r in sorted(rts, key=lambda r: r.get("exitAt") or ""):
        reason = r.get("reason") or ""; pnl = num(r.get("pnlUsd"))
        is_loss_stop = reason in LOSS_STOP or (reason in TRAIL and pnl < 0)
        n = n + 1 if is_loss_stop else 0
        mx = max(mx, n); cum += pnl; lo = min(lo, cum); hi = max(hi, cum)
    return n, mx, lo, hi

def buy_window(c, now):
    """-> (lastNewBuy HH:MM, doneWhenFlatFrom HH:MM, overrideActive). Dated todayOverride wins on its date.
    Proposal 7 (Kevin 2026-10-21 10:58 ET, from 2026-10-22): lateBuy.enabled false -> strict 10:00 cutoff, done when flat from 11:00."""
    d = now.strftime("%Y-%m-%d"); ov = c.get("todayOverride") or {}
    if ov.get("date") == d:
        lb = ov.get("lastNewBuy", "11:30"); return lb, lb, True
    late = c.get("lateBuy") or {}
    if late.get("enabled") is False and d >= late.get("disabledFrom", "0000-00-00"):
        sc = c.get("strictCutoff") or {}
        return sc.get("newBuyCutoffEt", c.get("defaultNewBuyCutoffEt", "10:00")), sc.get("doneWhenFlatFromEt", "11:00"), False
    return "11:30", "11:30", False

def full_cfg():
    try: return json.load(open(CONFIG))
    except Exception: return {}

def gate(a):
    """Pre-buy rule gate (owner rules from 2026-10-22: proposals 1, 2, 6, 7). Never calls the broker."""
    C = full_cfg(); c = C.get("discretion", {})
    now = datetime.fromisoformat(a.now).replace(tzinfo=ET) if a.now else datetime.now(ET)
    if a.now and datetime.fromisoformat(a.now).tzinfo: now = datetime.fromisoformat(a.now).astimezone(ET)
    d = now.strftime("%Y-%m-%d"); hhmm = now.strftime("%H:%M")
    ef = dict(C.get("entryFilters", {})); ov = c.get("todayOverride") or {}
    if ov.get("date") == d and isinstance(ov.get("entryFiltersToday"), dict):
        ef.update({k: v for k, v in ov["entryFiltersToday"].items() if k != "note"})
    stop_only = ov.get("date") == d and bool(ov.get("stopOnlyTest"))
    reasons = []; info = []
    mn = num(ef.get("minLastPriceAtEntry"), 0.10)
    if a.last < mn: reasons.append(f"price {a.last} < min {mn}")
    dmin = num(ef.get("minPctChangeAtEntry"), 8.0)
    dmax = num(ef.get("maxPctChangeAtRecycle" if a.mode == "recycle" else "maxPctChangeAtEntry"), 60.0)
    if a.day_pct is not None and not (dmin <= a.day_pct <= dmax): reasons.append(f"dayPct {a.day_pct} outside {dmin}..{dmax}")
    last_buy, _, _ = buy_window(c, now)
    start = c.get("entriesFromEt", "09:35")
    if not (start <= hhmm < last_buy): reasons.append(f"time {hhmm} outside new-buy window {start}-{last_buy}")
    ev = C.get("eventVeto") or {}
    forms = [f.strip().upper() for f in (a.filings or "").split(",") if f.strip()]
    news = (a.news or "").lower()
    ev_hit = None
    if ev.get("enabled") and d >= ev.get("from", "0000-00-00"):
        veto_forms = {"SC TO-I", "SC TO-T", "SC TO-C", "SC 14D9", "SC 14D-9", "DEFM14A", "PREM14A"}
        for f in forms:
            if f in veto_forms or f.replace(" ", "") in {x.replace(" ", "") for x in veto_forms} or f in ("8-K:1.01", "8-K ITEM 1.01", "8-K:1.01:MERGER"):
                ev_hit = f; break
        if not ev_hit:
            for k in ev.get("newsKeywords", []):
                if k.lower() in news: ev_hit = "news:" + k; break
        if ev_hit:
            (info if stop_only else reasons).append(f"event_veto:{ev_hit} (tender/Dutch auction/merger-arb)")
    dil = [f for f in forms if f.startswith("424B") or f in ("S-1", "S-3", "F-1", "F-3", "ATM")]
    if dil: (info if stop_only else reasons).append("dilution:" + ",".join(dil))
    # DESK FIXES 2026-11-10 (Kevin 16:02/16:07 ET): (a) no new buy while any position lacks a verified broker stop (state.protection);
    # (b) no same-symbol re-buy after a LOSING exit today (evidence: 6 such re-buys since 2026-10-06, 0 wins, −$2.65; winners may recycle).
    if getattr(a, "state", None):
        try: st = json.load(open(a.state))
        except Exception: st = {}
        try:
            _bc = (json.load(open(_os.environ.get("DISC_CONFIG") or _os.environ.get("RECONCILE_CONFIG") or "/workspace/robinhood-fable-agent/config/equity-morning-session.json")).get("bankStop") or {})
            _bs = json.load(open(_bc.get("stateFile") or "/workspace/robinhood-fable-agent/data/equity-paper/bank-stop.json")) if _bc.get("enabled", True) else {}
        except Exception: _bs = {}
        if _bs.get("tripped"): reasons.append("bank_stop_tripped: live equity at or below the bankStop line (config thresholdPct of baseline) — SYSTEM STOP, no new trades until Kevin restarts")
        prot = st.get("protection") or {}
        if prot and prot.get("buysAllowed") is False:
            reasons.append("unprotected_position: " + ",".join([u.get("symbol", "?") for u in (prot.get("unprotected") or [])] + [w.get("symbol", "?") for w in (prot.get("wrongType") or [])]) + " — protect first, no new buys")
        if ef.get("noRebuyAfterLossSameDay", True) and a.symbol:
            lost = [r for r in st.get("roundTrips") or [] if str(r.get("symbol", "")).upper() == a.symbol.upper() and str(r.get("exitAt", ""))[:10] == d and num(r.get("pnlUsd")) < 0]
            if lost: reasons.append(f"same_symbol_loss_today: {a.symbol.upper()} closed at a loss today ({len(lost)}x) — no re-buy (entryFilters.noRebuyAfterLossSameDay)")
    # ENTRY PLAYBOOK (desk decision 2026-11-10 16:49 ET under SILAS final authority; 60-trade evidence): live entries are
    # early-session first entries (gap_and_go 09:30–09:45 n20 40% +1.33%; early_momentum 09:45–10:00 n11 36% +$2.15);
    # 10:00+ entries (n28 14% −$5.00) and re-entries (recycle_bounce n31 23% −0.73%) are PAPER-ONLY unless A+ (watchlist catalyst ≥ 0.7, TA 5/5, ≤ 1/day).
    PB = C.get("entryPlaybook") or {}; setup = None; aplus = False
    if PB.get("enabled") and d >= PB.get("effectiveFrom", "0000-00-00") and _os.environ.get("DESK_PAPER_SESSION") != "1":   # paper session tests every setup
        st2 = {}
        if getattr(a, "state", None):
            try: st2 = json.load(open(a.state))
            except Exception: st2 = {}
        sym = (a.symbol or "").upper()
        traded = [r for r in (st2.get("roundTrips") or []) if str(r.get("symbol", "")).upper() == sym and str(r.get("exitAt", ""))[:10] == d] + \
                 [p_ for p_ in (st2.get("positions") or []) if str(p_.get("symbol", "")).upper() == sym]
        win = PB.get("liveWindowEt") or {}; w0, w1 = win.get("from", "09:35"), win.get("to", "10:00")
        setup = getattr(a, "setup", None) or ("recycle_bounce" if (traded or a.mode == "recycle") else ("gap_and_go" if hhmm < "09:45" else ("early_momentum" if hhmm < w1 else "midday_momentum")))
        wl_score = getattr(a, "watchlist_score", None)
        if wl_score is None:
            try:
                W = json.load(open(f"{PB.get('watchlistDir', '/workspace/equity-am-desk/kb')}/watchlist-{d}.json"))
                wl_score = max([num(c_.get("score")) for c_ in W.get("candidates") or [] if str(c_.get("symbol", "")).upper() == sym] or [None]) if any(str(c_.get("symbol", "")).upper() == sym for c_ in W.get("candidates") or []) else None
            except Exception: wl_score = None
        AP = PB.get("aPlus") or {}
        used = sum(1 for r in list(st2.get("roundTrips") or []) + list(st2.get("positions") or []) if str(r.get("entryAt", ""))[:10] == d and r.get("playbookTag") == "aPlus")
        ta_pass = getattr(a, "ta_pass", None)
        aplus = bool(AP.get("enabled")) and wl_score is not None and num(wl_score) >= num(AP.get("minWatchlistScore"), 0.7) and not traded \
                and (ta_pass is None or ta_pass >= int(AP.get("requireTaPass", 5))) and used < int(AP.get("maxPerDay", 1)) and hhmm < AP.get("untilEt", "11:30")
        live = set(PB.get("liveSetups") or ["gap_and_go", "early_momentum"])
        if aplus: info.append(f"playbook A+: watchlist score {wl_score} ≥ {AP.get('minWatchlistScore', 0.7)} (tag playbookTag aPlus)")
        elif setup not in live: reasons.append(f"playbook_paper_only: setup {setup} is paper-only (config entryPlaybook; promoted when the 07:30 paper session shows positive expectancy)")
        elif not (w0 <= hhmm < w1): reasons.append(f"playbook_window: live entries {w0}–{w1} only (after {w1}: A+ watchlist catalyst ≥ {AP.get('minWatchlistScore', 0.7)} + TA {AP.get('requireTaPass', 5)}/5, ≤ {AP.get('maxPerDay', 1)}/day)")
        if wl_score is not None: info.append(f"watchlist score {wl_score}")
    pb = ef.get("preferPctChangeBand") or {}
    pref = None if (a.day_pct is None or not pb) else (num(pb.get("min"), 8) <= a.day_pct <= num(pb.get("max"), 15))
    out = {"symbol": (a.symbol or "").upper(), "now": now.isoformat(timespec="seconds"), "allowed": not reasons, "reasons": reasons, "info": info,
           "movePreferred": pref, "lastNewBuyEt": last_buy, "setup": setup, "aPlus": aplus, "stopOnlyTest": stop_only, "filters": {"minLast": mn, "dayPct": [dmin, dmax]}}
    print(json.dumps(out, indent=1)); return out

def status(a):
    st = jload(a.state); q = quotes(a.quotes); c = cfg()
    ks = c.get("killSwitch", {}); tg = c.get("dailyTarget", {})
    now = datetime.fromisoformat(a.now).replace(tzinfo=ET) if a.now else datetime.now(ET)
    hhmm = now.strftime("%H:%M")
    bank = num(st.get("startBank") or st.get("startCash") or st.get("bankUsd"))
    rts = st.get("roundTrips", []) or []
    realized = num(st.get("realizedPnlUsd"))
    if a.now:  # replay: only round trips closed at/before --now count
        rts = [r for r in rts if r.get("exitAt") and datetime.fromisoformat(r["exitAt"]) <= now]
        realized = sum(num(r.get("pnlUsd")) for r in rts)
    unreal = 0.0; locked_open = 0.0; pos_out = []; missing = []
    for p in st.get("positions", []) or []:
        s = p["symbol"].upper(); qty = num(p.get("qty")); e = num(p.get("entryPrice"))
        bid = (q.get(s) or {}).get("bid")
        if bid is None: missing.append(s); bid = e
        stop = num(p.get("trailStop") or p.get("stop"), e * 0.95)   # hard stop worst case −5% (Kevin 16:28)
        unreal += (bid - e) * qty; locked_open += (stop - e) * qty
        pos_out.append({"symbol": s, "qty": qty, "entry": e, "bid": bid, "stop": stop, "unrealUsd": round((bid - e) * qty, 4)})
    day = realized + unreal
    pct = day / bank * 100 if bank else None
    cs, cs_max, real_lo, real_hi = consecutive_loss_stops(rts)
    disc = st.get("discretion") or {}
    halted = bool(disc.get("halted")); reason = disc.get("haltReason")
    # OWNER KILL-SWITCH RESET (Kevin 2026-10-21 10:05 ET): todayOverride.killSwitchResetAt (on its date only) restarts the
    # consecutive-stop count from that instant; earlier stop-outs no longer count toward 2-in-a-row. Day-loss (-5%) still uses ALL of today's P&L.
    _ov = c.get("todayOverride") or {}
    _rst = _ov.get("killSwitchResetAt") if _ov.get("date") == now.strftime("%Y-%m-%d") else None
    if _rst:
        _rdt = datetime.fromisoformat(_rst)
        cs, cs_max, _, _ = consecutive_loss_stops([r for r in rts if r.get("exitAt") and datetime.fromisoformat(r["exitAt"]) > _rdt])
        if halted and disc.get("haltedAt") and datetime.fromisoformat(disc["haltedAt"]) <= _rdt: halted, reason = False, None
    # STOP-ONLY TEST (Kevin 2026-10-21 10:07 ET): on todayOverride.date with stopOnlyTest, NO kill switch, NO target/protect/floor.
    stop_only = bool(_ov.get("stopOnlyTest")) and _ov.get("date") == now.strftime("%Y-%m-%d")
    if stop_only: halted, reason = False, None
    loss_lim = num(ks.get("dayPnlPctOfStartBank"), -5.0) / 100 * bank
    if stop_only: loss_lim = -1e18
    if not halted and bank and min(day, real_lo) <= loss_lim: halted, reason = True, "daily_loss_5pct"
    if not halted and not stop_only and cs_max >= int(ks.get("consecutiveStopOuts", 2)): halted, reason = True, "two_consecutive_stops"
    target = bank * num(tg.get("pctOfStartBank"), 5.0) / 100
    floor_usd = bank * num(tg.get("lockFloorPct"), 3.0) / 100
    target_hit = (not stop_only) and bool(disc.get("targetHit")) or (not stop_only) and (bank > 0 and max(day, real_hi, num(disc.get("maxDayPnlUsd"), -1e9)) >= target)
    mode = "halted" if halted else ("protect" if target_hit else ("stop_only_test" if stop_only else "normal"))
    locked = realized + locked_open
    floor_breach = target_hit and day <= floor_usd
    if floor_breach and not halted:
        halted, reason, mode = True, "protect_floor_3pct", "halted"
    # lock-floor stop raises (protect mode): raise highest-gain first until locked >= floor
    raises = []
    if mode == "protect" and locked < floor_usd:
        need = floor_usd - locked
        for p in sorted(pos_out, key=lambda x: -(x["bid"] - x["entry"])):
            if need <= 0: break
            max_stop = down(p["bid"] * 0.99)
            want = up(p["stop"] + need / p["qty"]) if p["qty"] else p["stop"]
            new = min(max_stop, want)
            if new > p["stop"]:
                raises.append({"symbol": p["symbol"], "from": p["stop"], "to": new}); need -= (new - p["stop"]) * p["qty"]
        if need > 1e-9:
            raises.append({"cannotSecureFloorBy": round(need, 4), "action": "protect_floor_exit (aggressive exit of the weakest needed position)"})
    flat = not (st.get("positions") or [])
    # DATED OVERRIDE (Kevin 2026-10-20 10:08 ET): config discretion.todayOverride governs only on its date
    ov = c.get("todayOverride") or {}
    last_buy, done_from, ov_on = buy_window(c, now)
    _ad = (c.get("allDaySession") or {}); _ad_on = bool(_ad.get("enabled")) and now.strftime("%Y-%m-%d") >= _ad.get("from", "0000-00-00")
    # ALL-DAY SESSION (Kevin 2026-11-10 08:13 ET): no 10:55-11:01 blackout (no 11:00 flatten); done when flat at/after the flatten time
    blackout = (not _ad_on) and (not (ov_on and ov.get("skipBlackout1055_1101"))) and ("10:55" <= hhmm < "11:01")
    _hard = _ad.get("flattenEt", "15:50") if _ad_on else "15:45"
    done = flat and (halted or hhmm >= done_from or hhmm >= _hard)
    out = {"now": now.isoformat(timespec="seconds"), "startBank": bank, "realizedPnlUsd": round(realized, 4), "unrealizedPnlUsd": round(unreal, 4),
           "dayPnlUsd": round(day, 4), "dayPnlPct": round(pct, 3) if pct is not None else None, "consecutiveLossStops": cs, "maxConsecutiveLossStopsToday": cs_max,
           "halted": halted, "haltReason": reason, "mode": mode, "targetUsd": round(target, 4), "progressPct": round(day / target * 100, 1) if target else None,
           "targetHit": target_hit, "lockFloorUsd": round(floor_usd, 4), "lockedPnlUsd": round(locked, 4), "stopRaisesForFloor": raises,
           "floorBreach": floor_breach, "killSwitchResetAt": _rst, "stopOnlyTest": stop_only, "tradeTag": (_ov.get("tradeTag") if stop_only else None), "newBuysAllowed": (not halted) and hhmm < last_buy and not blackout, "lastNewBuyEt": last_buy, "doneWhenFlatFromEt": done_from, "overrideActive": ov_on, "lateBuysEnabled": last_buy > "10:00", "allDaySession": _ad_on, "flat": flat, "done": done,
           "doneReason": (("halted:" + str(reason)) if halted else (("flat_after_" + _hard.replace(":", "")) if hhmm >= _hard else "past_" + done_from.replace(":", "") + "_flat")) if done else None,
           "positions": pos_out, "quotesMissing": missing}
    print(json.dumps(out, indent=1)); return out

def hold(a):
    be = up(a.fill); why = []
    ok_pct = a.bid >= a.fill * 1.01; why.append(f"bid {a.bid} {'>=' if ok_pct else '<'} fill×1.01 {round(a.fill*1.01,4)}")
    ok_vwap = a.bid > a.vwap; why.append(f"bid {'>' if ok_vwap else '<='} VWAP {a.vwap}")
    frac_ok = a.fractional_path in (None, "", "whole", "broker_stop", "broker_stop_limit")
    if not frac_ok: why.append("desk_monitored fractional: never held")
    stop_ok = a.resting_mode == "trail" or a.resting_stop >= be
    raise_to = None
    if ok_pct and ok_vwap and frac_ok and not stop_ok:
        raise_to = be; why.append(f"resting stop {a.resting_stop} < breakeven {be}: RAISE to {be} (cancel→verify→re-place), hold only if it verifies open")
    hold_ok = ok_pct and ok_vwap and frac_ok and (stop_ok or raise_to is not None)
    print(json.dumps({"hold": hold_ok, "breakeven": be, "raiseStopTo": raise_to, "stopLimitLimit": down((raise_to or a.resting_stop) * 0.97), "why": why}, indent=1))

def size(a):
    st_args = argparse.Namespace(state=a.state, quotes=a.quotes, now=a.now)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): s = status(st_args)
    stop = up(a.buy_limit * 0.95)   # risk to the −5% hard-stop limit (Kevin 16:28)
    risk = a.buy_limit - stop
    if s["mode"] != "protect":
        # RISK-BASED SIZING (Kevin 2026-11-17 20:06 ET, evaluation item 2; replaces full-cash sizing):
        # qty = floor(equity × riskPct / (buy_limit − stop)), capped by cash × 0.95 / buy_limit; skip if 1 share > maxRiskPct of equity.
        rs = cfg().get("riskSizing", {}); rp = num(rs.get("riskPct"), 1.0); mx = num(rs.get("maxRiskPct"), 2.0); cf = num(rs.get("cashCapFrac"), 0.95)
        eq = a.equity if a.equity else num(s.get("startBank"), 0.0); cash = a.cash if a.cash is not None else eq
        # SIZE MULTIPLIER (stress test 2026-11-22): fail closed. A forgotten --size-mult used to mean full size even with the
        # bank tripwire hit. Now: read the tripwire from the bank-stop state file; take the SMALLER of that and --size-mult;
        # clamp to 0-1 (a multiplier can only shrink risk). Pass --size-mult as tripwire × regime multiplier when both apply.
        mult, mult_src = 1.0, "default"
        try:
            _bc = full_cfg().get("bankStop") or {}
            _bs = json.load(open(_bc.get("stateFile") or "/workspace/robinhood-fable-agent/data/equity-paper/bank-stop.json")) if _bc.get("enabled", True) else {}
        except Exception: _bs = {}
        if _bs.get("tripwireActive"): mult, mult_src = 0.5, "bank tripwire (state file)"
        if a.size_mult is not None:
            if a.size_mult < mult: mult_src = "--size-mult"
            mult = min(mult, a.size_mult)
        mult = max(0.0, min(1.0, mult))
        if mult <= 0:
            print(json.dumps({"mode": s["mode"], "skip": True, "skipReason": "size_mult_zero", "sizeMult": mult, "sizeMultSource": mult_src}, indent=1)); return
        if eq <= 0 or risk <= 0:
            print(json.dumps({"mode": s["mode"], "skip": True, "skipReason": "no_equity_or_risk"}, indent=1)); return
        q_risk = int(math.floor(eq * rp / 100 * mult / risk)); q_cash = int(math.floor(cash * cf / a.buy_limit))
        one_share_pct = risk / eq * 100; q = min(q_risk, q_cash)
        skip = one_share_pct > mx or q < 1
        print(json.dumps({"mode": s["mode"], "sizing": "risk", "riskPct": rp * mult, "equityUsd": eq, "cashUsd": cash, "riskPerShare": round(risk, 4),
                          "qtyByRisk": q_risk, "qtyByCash": q_cash, "maxQty": 0 if skip else q, "riskUsd": round((0 if skip else q) * risk, 2),
                          "skip": skip, "skipReason": ("one_share_exceeds_max_risk" if one_share_pct > mx else "rounds_to_zero") if skip else None,
                          "sizeMult": mult, "sizeMultSource": mult_src}, indent=1)); return
    room = s["lockedPnlUsd"] - s["lockFloorUsd"]
    qmax = int(math.floor(room / risk)) if risk > 0 and room > 0 else 0
    print(json.dumps({"mode": "protect", "roomAboveFloorUsd": round(room, 4), "riskPerShare": round(risk, 4), "maxQty": qmax,
                      "skip": qmax < 1, "skipReason": "protect_size" if qmax < 1 else None, "fractionalMaxDollars": round(max(room, 0) / 0.02, 2)}, indent=1))

ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
x = sp.add_parser("status"); x.add_argument("--state", required=True); x.add_argument("--quotes"); x.add_argument("--now")
h = sp.add_parser("hold"); h.add_argument("--fill", type=float, required=True); h.add_argument("--bid", type=float, required=True); h.add_argument("--vwap", type=float, required=True)
h.add_argument("--resting-stop", type=float, required=True); h.add_argument("--resting-mode", default="stop"); h.add_argument("--fractional-path")
z = sp.add_parser("size"); z.add_argument("--state", required=True); z.add_argument("--quotes"); z.add_argument("--now"); z.add_argument("--ask", type=float, required=True); z.add_argument("--buy-limit", type=float, required=True)
z.add_argument("--equity", type=float, help="live total equity (get_portfolio)"); z.add_argument("--cash", type=float, help="live buying power"); z.add_argument("--size-mult", type=float, help="0.5 when the bank tripwire is hit")
g = sp.add_parser("gate"); g.add_argument("--symbol"); g.add_argument("--last", type=float, required=True); g.add_argument("--day-pct", type=float)
g.add_argument("--mode", default="entry", choices=["entry", "recycle"]); g.add_argument("--filings", help="comma list of today's forms, e.g. 'SC TO-I,8-K:1.01,424B5'")
g.add_argument("--setup", help="gap_and_go|early_momentum|orb_breakout|vwap_reclaim|momentum_pullback|recycle_bounce|midday_momentum (default: inferred)"); g.add_argument("--watchlist-score", type=float); g.add_argument("--ta-pass", type=int)
g.add_argument("--news", help="headline / catalyst text"); g.add_argument("--now"); g.add_argument("--state", help="morning-session.json: enforces protection-first + no same-symbol re-buy after a loss today")
a = ap.parse_args()
{"status": status, "hold": hold, "size": size, "gate": gate}[a.cmd](a)
