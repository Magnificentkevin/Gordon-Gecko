# Risk rules

> **Evaluation revisions 2026-11-17 20:06 ET (supersede conflicting lines below).** Source: `reports/Gordongecko strategy evaluation.md`; bank stop confirmed by Kevin.
> - **Bank stop:** stop at 80% of baseline (20% drawdown), tripwire at 90% (alert Kevin, halve size via `sizeMultiplier` 0.5, owner review). Was 50%. `config.bankStop.thresholdPct` 80, `tripwirePct` 90.
> - **Sizing:** 1% of equity at risk to the −5% stop, 2% max, capped at 95% of buying power (`discretion.riskSizing`, `discretion.py size --equity --cash`). Replaces full-cash sizing.
> - **Day kill:** −3% day (was −5%); 2 consecutive losing stops unchanged. **Round trips:** 4 a day (was 9).
> - **Account:** `limited_margin`, not a cash account. May buy with unsettled sale proceeds; never borrow, never create a debit, never short. Check `get_accounts` type each fire; if not `limited_margin`, no same-day recycling. PDT ended 2026-06-04 (FINRA RN 26-10).
> - **Order checks:** debit / excess obligation / good-faith / freeriding / 90-day / day-trade text = hard stop, escalate.
> - **Stop monitoring:** bid within 1% of trigger or a triggered-unfilled stop → 60-second watch; backstop exit = marketable limit at bid × 0.97 after checking halt/LULD state. Losses can exceed 5% on gaps and halts.
> - **Approval-required orders:** occupy a slot, never duplicated, cancel at next fire if pending (15:50 latest); a pending protective stop = unprotected (floor 9).


Two layers: **hard floors** (owner-locked, never auto-tuned) and the
**adjustable profile** (currently `higher-risk+15`). If a procedure, helper,
or older config line disagrees with a hard floor, the floor wins. If it
disagrees with the active profile, the profile wins.

## Hard floors

### Protective stop-limit

Every whole-share position must have a resting `type="stop_limit"` with both
`stop_price` and `limit_price`:

- trigger = `entry × 0.955`, rounded **up** to the tick (a −4.5% stop)
- limit = `entry × 0.95`, rounded **down** (never worse than −5% if it fills)

Before sending, run:

```
python3 ${HELPERS_DIR}/reconcile.py stopargs --json '<exact place_equity_order kwargs>' --entry <avg>
```

Exit 4 means do not send the original kwargs; send the returned `fixed`
kwargs after re-checking. After sending, re-read orders and positions and
run `verify-protection --apply`. Exit 0 = protected. Exit 7 = unprotected
or wrong type (a plain limit sell is not a stop): cancel, verify, re-place
via `stopargs`, verify again.

A broker MCP may display a stop-limit as `type="limit"` plus
`trigger="stop"`. The helper understands that shape; do not "fix" it by
replacing a good stop-limit with a naked limit.

### −5% market-sell backstop and the 5% per-trade cap

Every fire, after a fresh positions + quotes (+ orders) read:

```
python3 ${HELPERS_DIR}/risk_floors.py trade-cap --positions <pos> --quotes <quotes> --orders <orders>
```

Exit 8 = one or more positions have bid (else last) ≤ entry × 0.95. Cancel
those sells, verify, market-sell immediately. This covers a gap through the
stop or a stop-limit that triggered but never filled (GAP GUARD).

No stop or limit may ever be set below entry × 0.95. `stopargs --entry`
refuses it.

### 50% bank stop

```
python3 ${HELPERS_DIR}/risk_floors.py bank-check --portfolio <get_portfolio raw> --apply
```

- Exit 0: ok.
- Exit 9: tripped (new or already tripped) → run the bank-stop flatten
  below. Automatic mode off.
- A wrapper-text or unreadable portfolio file is **not** a trip. Strip
  non-JSON wrapper text and re-run. A zero or garbage equity read never
  trips.

**Baseline** = equity of the live account at the measurement start, plus
owner deposits, minus withdrawals, recorded with
`risk_floors.py flow --amount <usd> --type deposit|withdrawal`. Deposits
do not count as P&L. **Stop line** = 50% of baseline. Illustrative
example: baseline $100.00 → stop $50.00.

Only the owner can restart: `risk_floors.py bank-restart --by "owner <words>, <time ET>"`.
Never restart because equity recovered, because a timeout passed, or on
the desk's own initiative.

### Bank-stop flatten

1. Escalate to the owner immediately (system stop).
2. Fresh orders → cancel every open order → re-read → confirm none remain
   (if one filled, re-read positions).
3. During regular hours (09:30–15:59): market-sell every position; sync
   with reason `bank_stop_flatten`. Outside regular hours: cancel only and
   leave positions for the next 09:30 fire — no extended-hours orders.
4. `risk_floors.py bank-flat-done --positions <pos> --orders <orders>`
   (exit 0 = flat; exit 6 = repeat next fire).
5. `desk_clock.py done --phase bank-stop`. Every later fire idles. No
   paper session, no live switch, no daily revise, no recap while stopped
   (the escalation is the message, once per trading day, until restart).

### Other floors

- **Flatten before close** at 15:50, backup 15:55. Nothing overnight.
- **Cash equity longs only.** No margin, options, shorts, or crypto.
- **Owner-only** arm (`liveMode.armed`), disarm, pause (`desk.paused`),
  and post-bank-stop restart. The 09:30 auto-switch is not an arm.
- **Day kill switch** (`discretion.py`): 2 consecutive losing stops, or
  day P&L ≤ −5% of start-of-day bank → no new buys for the rest of that
  day; exits only. Sticky until the next session. This is a trading rule,
  not a system stop.
- **Protect first**, every fire 09:30–16:00, from this fire's broker
  reads. If protection cannot be verified for every whole-share position,
  `discretion.py gate` refuses new buys (`state.protection.buysAllowed`
  is false). If a stop cannot be placed after one retry, aggressively
  exit that position.
- **Broker truth and an append-only ledger.** `reconcile.py sync` writes
  round trips, realized P&L, and counts. It refuses an empty or incomplete
  orders snapshot and will not lower realized P&L from a stale snapshot.
  Never sync a placeholder file.

## Profile `higher-risk+15` (adjustable)

Applied 2026-11-17 09:29 ET after the owner confirmed a 15% wider risk
tolerance. It replaced `higher-risk` (2026-11-13), which had replaced the
earlier −2% decision / 40–55 recovery / stricter TA profile.

| Knob | Current | Previous (`higher-risk`) | Notes |
|---|---|---|---|
| Decision point | −3.45% | −3% | Owner-locked. `stopLossPct`, `recoveryModel.decisionPointPct`, fractional virtual decision. |
| Hold threshold | 26 before 10:00, 38 after | 30 / 45 | `thresholdPct` 38, early offset −12. Bounds 26–70, step 5. |
| TA required | 3 of 5 all day | 3 of 5 | `strictMinPassCount` 3. desk_learn may later step ±1 within 3–5. |
| A+ after 10:00 | score ≥ 0.51, until 13:30, max 3, TA 3 | 0.6, 13:00, max 3, TA 3 | Never a re-entry. Tag `playbookTag=aPlus`. |
| Round-trip cap | 9 | 8 | Also `discretion.allDaySession.rtCap`. |
| Stall exit | 14 min, hw < +1% | 12 min | Bounds 8–25, step 2. |
| TP floor | 5% | 5% | Already tuned from 6%. Bounds 2–6%. |

Unchanged by the profile: every hard floor above, full-cash sizing, max 2
slots, no re-buy after a losing exit, $1 price floor, bid-to-stop / spread /
RVOL / liquidity / dilution / merger filters (`bidToStopPct` stays −2.0,
anchored at ask × 0.98), flatten-before-close, 09:30 auto live switch.

Measure new trades dated on/after 2026-11-17 against `higher-risk` and
against the 25.8% decision-success baseline. Do not auto-tune guarded
params until n ≥ 6 under this profile. See
[Self-learning](self-learning.md).

## Sizing

- Max 2 open positions (plus open buy orders count against free slots).
- Per-slot cash = available cash (this fire's broker cash / buying power)
  ÷ free slots (min 1).
- If ask ≤ available cash: **whole shares only**,
  `qty = floor(slot / ask)` (or 1 if that is 0 and one share fits), then
  cut until `qty × buyLimit ≤ cash × 0.99`.
- If ask > available cash: only if the broker marks the name
  fractional-eligible in this same run (`get_equity_tradability`). Dollar
  (or fractional qty) market buy, typically ≤ 50% of cash, max 1
  fractional position. Fractional lots usually cannot hold a resting
  broker stop-limit — they use the 1-minute virtual watch. Weaker
  protection; do not add a second fractional lot.
- Cash account, no margin. Size only from live buying power.

## Daily target and protect mode

Daily target is +5% of start-of-day bank. It is a goal, not a reason to
loosen a floor. If the day reaches +5%, protect mode locks a +3% floor
(raises stops to hold it) and allows only A+ adds sized so a full stop
would still leave the day at or above the floor. A floor breach flattens
and halts new buys.

## What nothing may change

`desk_learn.py`, the daily revise, and any routine must not change:
`bankStop`, `maxTradeLoss`, `recoveryModel.decisionPointPct`,
`recoveryModel.hardStop`, `tpModel.stopPct` (the hard-stop geometry),
`desk.paused`, `liveMode`, or `premarketPaper` session identity. Arming
and the decision point move only when the owner confirms.
