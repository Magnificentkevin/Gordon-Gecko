#!/usr/bin/env python3
"""Gordongecko position sizer and pre-trade gate.

Sizes a long stock trade from the dollar risk you are willing to take, scales
it by the market regime, caps it by position size and portfolio heat, and
returns a PASS/FAIL verdict with reasons.

Examples:
  python3 gecko_size.py --account 10000 --entry 155 --stop 148.50 --target 170
  python3 gecko_size.py --account 10000 --entry 155 --atr 3.2 --atr-mult 2 \
      --regime-mult 0.75 --open-risk-pct 2.5 --fractional 4 --json

Exit codes: 0 PASS, 2 FAIL (gate said no), 1 bad input.

Standard library only. Educational tool, not financial advice.
"""
import argparse
import json
import math
import sys


def floor_to(value, decimals):
    factor = 10 ** decimals
    return math.floor(value * factor + 1e-9) / factor


def size(args):
    reasons, warnings = [], []

    if args.account <= 0:
        raise ValueError("Account equity must be above zero")
    if args.entry <= 0:
        raise ValueError("Entry must be above zero")
    if not (0 <= args.regime_mult <= 1):
        # gecko_regime.py only ever returns 0-1; anything above 1 would lift risk past the hard ceiling
        raise ValueError(f"--regime-mult must be between 0 and 1 (got {args.regime_mult:g})")

    stop = args.stop
    if stop is None and args.atr:
        stop = round(args.entry - args.atr * args.atr_mult, 2)
    if stop is None:
        raise ValueError("Provide --stop or --atr")
    if not (0 < stop < args.entry):
        raise ValueError("Stop must be positive and below entry (long trades only)")

    risk_per_share = args.entry - stop
    stop_pct = risk_per_share / args.entry * 100
    effective_risk_pct = args.risk_pct * args.regime_mult
    risk_budget = args.account * effective_risk_pct / 100

    decimals = args.fractional or 0
    by_risk = floor_to(risk_budget / risk_per_share, decimals) if risk_budget > 0 else 0
    by_cap = floor_to(args.account * args.max_position_pct / 100 / args.entry, decimals)
    shares = min(by_risk, by_cap)
    binding = "risk budget" if by_risk <= by_cap else f"max position {args.max_position_pct:g}%"

    position_value = shares * args.entry
    dollar_risk = shares * risk_per_share
    risk_pct_actual = dollar_risk / args.account * 100
    heat_after = args.open_risk_pct + risk_pct_actual

    rr = None
    if args.target is not None:
        if args.target <= args.entry:
            reasons.append("Target is not above entry")
        else:
            rr = (args.target - args.entry) / risk_per_share
            if rr < args.min_rr:
                reasons.append(f"Reward:risk {rr:.2f} is below minimum {args.min_rr:g}")
    elif args.allow_no_target:
        warnings.append("No target given, so reward:risk was not checked")
    else:
        reasons.append("No target given: reward:risk can't be checked (pass --target, or --allow-no-target to skip)")

    if args.regime_mult <= 0:
        reasons.append("Market regime is DEFENSIVE/UNKNOWN: no new longs")
    if args.risk_pct > 2:
        reasons.append(f"Base risk {args.risk_pct:g}% exceeds the 2% hard limit")
    if effective_risk_pct > 2 + 1e-9:
        reasons.append(f"Effective risk {effective_risk_pct:g}% (base x regime) exceeds the 2% hard limit")
    if heat_after > args.max_heat_pct:
        reasons.append(f"Portfolio heat would be {heat_after:.2f}%, above {args.max_heat_pct:g}% cap")
    if shares <= 0:
        reasons.append("Position rounds to zero shares (try --fractional or a tighter stop)")
    max_entry = floor_to(stop / (1 - args.max_stop_pct / 100), 2)
    if stop_pct > args.max_stop_pct:
        reasons.append(f"Stop is {stop_pct:.2f}% below entry, over the {args.max_stop_pct:g}% cap: keep the stop, "
                       f"buy at or below ${max_entry:,.2f} instead (stop first, then entry)")

    return {
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "warnings": warnings,
        "entry": args.entry,
        "stop": stop,
        "stop_pct": round(stop_pct, 2),
        "max_entry_for_cap": max_entry,
        "target": args.target,
        "reward_risk": round(rr, 2) if rr is not None else None,
        "base_risk_pct": args.risk_pct,
        "regime_multiplier": args.regime_mult,
        "effective_risk_pct": round(effective_risk_pct, 3),
        "shares": shares,
        "binding_constraint": binding,
        "position_value": round(position_value, 2),
        "position_pct": round(position_value / args.account * 100, 2),
        "dollar_risk": round(dollar_risk, 2),
        "risk_pct_of_account": round(risk_pct_actual, 3),
        "portfolio_heat_after_pct": round(heat_after, 2),
    }


def main():
    p = argparse.ArgumentParser(description="Gordongecko position sizer + pre-trade gate")
    p.add_argument("--account", type=float, required=True, help="Account equity in dollars")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float)
    p.add_argument("--atr", type=float, help="ATR value (used if --stop is omitted)")
    p.add_argument("--atr-mult", type=float, default=2.0)
    p.add_argument("--target", type=float)
    p.add_argument("--risk-pct", type=float, default=1.0, help="Base risk per trade, %% of equity")
    p.add_argument("--regime-mult", type=float, default=1.0, help="From gecko_regime.py")
    p.add_argument("--max-position-pct", type=float, default=20.0)
    p.add_argument("--open-risk-pct", type=float, default=0.0, help="Risk already open, %% of equity")
    p.add_argument("--max-heat-pct", type=float, default=6.0)
    p.add_argument("--min-rr", type=float, default=2.0)
    p.add_argument("--allow-no-target", action="store_true",
                   help="Let the gate pass without a target (reward:risk unchecked). Off by default")
    p.add_argument("--max-stop-pct", type=float, default=5.0,
                   help="Max stop distance %% (default 5, matching the SILAS hard floor). Set the stop first; the entry must fit")
    p.add_argument("--fractional", type=int, default=0, metavar="DECIMALS",
                   help="Allow fractional shares to this many decimals (broker must support it)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    try:
        r = size(args)
    except ValueError as exc:
        print(json.dumps({"verdict": "FAIL", "reasons": [str(exc)]}, indent=2))
        return 1

    code = 0 if r["verdict"] == "PASS" else 2   # exit 2 = gate FAIL, so callers that check the exit code see it
    if args.json:
        print(json.dumps(r, indent=2))
        return code

    print(f"Verdict: {r['verdict']}")
    for reason in r["reasons"]:
        print(f"  x {reason}")
    for w in r["warnings"]:
        print(f"  ! {w}")
    print(f"Buy {r['shares']:g} shares @ ${r['entry']:,.2f}  stop ${r['stop']:,.2f} ({r['stop_pct']}%)"
          + (f"  target ${r['target']:,.2f}  R:R {r['reward_risk']}" if r['target'] else ""))
    print(f"Max entry that keeps the stop within {args.max_stop_pct:g}%: ${r['max_entry_for_cap']:,.2f}")
    print(f"Position ${r['position_value']:,.2f} ({r['position_pct']}% of account), "
          f"limited by {r['binding_constraint']}")
    print(f"Risk ${r['dollar_risk']:,.2f} ({r['risk_pct_of_account']}%), "
          f"regime x{r['regime_multiplier']:g}, heat after trade {r['portfolio_heat_after_pct']}%")
    return code


if __name__ == "__main__":
    sys.exit(main())
