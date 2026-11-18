# Manage and recovery

> **Evaluation revisions 2026-11-17 20:06 ET (supersede conflicting lines below).** Source: `reports/Gordongecko strategy evaluation.md`; bank stop confirmed by Kevin.
> - **Trail:** v1 activates at +2% (`tpModel.params.trailActivatePct` 2.0, as coded). The '+5% floor' activation written below is now the **v2 paper test** (trail at max(hw − 1.5 × ATR5, VWAP, last higher low)).
> - **Stall exit (v2 test only):** 14 min AND hw < +1% AND (price < VWAP OR below the entry bar's low). v1 unchanged.
> - **Recovery (v2 test only):** a sweep of a known low by < 1% that is reclaimed within 1–2 bars counts as support. The −3.45% decision point stays Kevin-locked.
> - **Stall timing (paper finding 2026-11-18):** after every fill, schedule a manage check at exactly entry + 14 minutes (plus the normal cadence). On 11/18 the stall rule first applied at 11:59 but the 15-minute cadence executed it at 12:02 (BRBR exit +$0.05 instead of about -$0.10).
> - **Approval-required orders** and **60-second near-stop watch**: see risk-rules.md revisions.


Every manage fire (09:30–15:59 ET, including while the book is flat during
the buy window) follows the same order. Skip no step. Budget time so
protection, the bank check, and the −5% backstop always run even if later
work is cut short.

## Order of work

1. **Clock.** `desk_clock.py next`. Idle or paused or bank-stopped → exit
   silently (bank-stop already escalated).
2. **Fresh broker reads** this fire: positions, open orders (all pages),
   portfolio, and quotes for held names. Do not decide from a cached book
   or from `desk_clock`'s `book` hint (`openOrders` may be null). If the
   clock says "book not flat" and the broker is actually flat, believe the
   broker and record the stale flag (see [Lessons learned](lessons-learned.md)).
3. **Protect first.** `reconcile.py verify-protection --apply`. Any
   whole-share position without a verified resting stop-limit gets one
   now, via `stopargs`. One retry, then aggressive exit. No new buys
   while `buysAllowed` is false.
4. **Bank check.** `risk_floors.py bank-check --portfolio <raw> --apply`.
   If the file has wrapper text around the JSON, strip it and re-run.
   Exit 9 → bank-stop flatten, no further trading.
5. **Trade cap.** `risk_floors.py trade-cap` → exit 8 means market-sell
   now (cancel sells, verify, market sell).
6. **Reconcile.** `reconcile.py sync --apply` on the **complete** orders
   snapshot. Never sync an empty or placeholder file. Use the
   per-symbol lock around every order action (`lock` / `unlock`, TTL
   120s). After a cancel that returns 403, do not retry the cancel and
   do not fire an extra sell; re-read after about 5 seconds.
7. **Fractional 1-minute watch** if a fractional lot is held
   (`reconcile.py fracwatch`, about every 60s inside the fire, up to
   ~4.5 minutes). Virtual decision point −3.45%; hard backstop −5%;
   market-sell when the virtual stop or TP hits. Max one fractional
   position. A long gap in the watch (about 6+ minutes without a tick)
   is itself a reason to flatten that lot.
8. **Manage each open position** (recovery, stall, trail, TP) — below.
9. **Entries** if the clock and the gate allow (see
   [Entries and TA](entries-and-ta.md)).
10. **Paper shadow tick** when live: `paper_shadow.py tick` with a short
    budget (~20s).
11. Mark the fire done. Send nothing unless an escalation rule triggers.

Immediately after every **new buy fill**, and before any other tool call,
place and verify the hard stop in the same sequence. Then compute the
take-profit.

## Recovery model

The resting stop-limit is the hard floor, not the first decision. The
desk reviews the chart at the **decision point −3.45%** (bid ≤ entry ×
0.9655) and either exits or holds for the hard stop.

```
python3 ${HELPERS_DIR}/recovery.py score \
  --symbol S --entry E --price BID \
  --bars5 <5m raw> [--bars1 <1m raw>] \
  --spy5 <SPY 5m raw> [--sector5 <sector ETF 5m raw>] \
  --catalyst intact|unknown|broken \
  [--now ISO] [--log]
```

- Exit code 10 = **EXIT NOW**: cancel the stop, verify, market-sell.
- Re-run every fire while the bid is still at or below the decision
  point. The first score under the threshold exits.
- Threshold: **26** before 10:00 ET, **38** from 10:00
  (`recoveryModel.thresholdPct` 38, `earlyThreshold.offset` −12).
- Log every score (`--log`) so `desk_learn` can label it later.

**Score** = 100 × Σ wᵢ·cᵢ / Σ wᵢ, each component cᵢ in [0, 1]
(0.5 = neutral or data missing):

| Component | Weight | Meaning |
|---|---|---|
| `vwap` | 0.20 | 0.5 + 25 × (price/VWAP − 1); +2% above → 1, −2% below → 0 |
| `trend1m` | 0.10 | Slope of last 10 1-minute closes (fallback: last four 5-minute closes) |
| `trend5m` | 0.15 | 0.5 + 50 × (EMA9/EMA20 − 1) on 5-minute closes |
| `dipVolume` | 0.15 | Red-bar ÷ green-bar volume over the last 6 5-minute (or 15 1-minute) bars; 1 at ≤ 0.8, 0 at ≥ 1.5 |
| `support` | 0.15 | Holding within 1.5% of nearest support (opening-range low, session low before the dip, round number) → 1; under the OR low and every support → 0; else ~0.4 |
| `rsi` | 0.05 | RSI14 (1-minute, else 5-minute): <30 rising 1.0; <30 falling 0.4; 30–50 rising 0.7; otherwise lower |
| `market` | 0.10 | SPY / sector tape confirmation |
| `catalyst` | 0.10 | `intact` / `unknown` / `broken` |

Weights may later be nudged inside 0.02–0.35 (step 0.02) once enough
labeled outcomes exist. The decision point itself stays owner-locked.

### Post-exit labels

After every loss exit (score sell or hard stop), stall, profit exit, and
every hold decision, label the call when rest-of-session bars are in:

```
python3 ${HELPERS_DIR}/recovery.py post-exit ...
```

Definitions live in `decisionObjective` and in
[Self-learning](self-learning.md). A loss exit is correct if price did
not get back to entry for the rest of the session. A hold is correct if
price got back above the decision point before touching the −4.5%
trigger.

## Stall exit

If the position has been open for **14 minutes** and high-water is still
< **+1%**, and the resting mode is still the initial stop (not a trail
already locked in profit):

1. Cancel the stop-limit and verify the cancel.
2. Sell a limit at the bid (retry bid × 0.97 if needed). Fractional or
   desk-monitored lots: market sell.
3. Reason: `stall_exit`.

Trades that never print a +0.5% high-water almost never win in the live
record. The 14-minute value is a profile knob (bounds 8–25, step 2).

## Take-profit and trail

```
python3 ${HELPERS_DIR}/tp_model.py target --symbol S --fill F --bars <5m> \
  [--daily <daily>] --catalyst-score 0.0-1.0 --now <ISO>
python3 ${HELPERS_DIR}/tp_model.py trail --fill F --hw H --atr A [--resting R] [--bid B --target T]
```

- Floor is **+5%** (`tpModel.floorPct`), so reward:risk vs the −4.5/−5%
  hard stop stays at least about 1:1. No upper cap.
- ATR = Wilder ATR(14) on today's real 5-minute bars.
- k = 1.0 + 2.0 × catalystScore → 1.0–3.0 ATR. T_atr = fill + k × ATR.
- Candidate levels: premarket high, prior-day high, today's high-of-day,
  the next two round numbers above the floor, fib extensions 1.272 /
  1.618 of a strong opening leg.
- Weaker catalyst (< 0.7): target = max(floor, min(T_atr, first wall − 1
  tick)). Strong catalyst: target = max(floor, T_atr, first wall at or
  above T_atr − 1 tick).
- Once bid ≥ floor, trail: `max(fill × 1.005, high-water − 1.0 × ATR)`,
  never lowered, rounded down. The initial protective stop is replaced
  by the trailing stop-limit; **never** leave a take-profit and a stop
  resting at the same time.
- If high-water has been ≥ +4% and bid then falls under the target,
  exit (one manage tick of grace per config).

A halt or LULD pause can fill a marketable limit at a surprising reopen
price, in either direction. GAP GUARD (the −5% backstop and triggered-but-
unfilled escalation) stays on.

## Flatten

At 15:50 (backup 15:55): cancel every open order, verify, market-sell
every position during regular hours, `sync --apply`,
`bank-flat-done`, write the scorecard. No extended-hours orders. If the
book is not flat, the next fire repeats; escalate `FLATTEN_INCOMPLETE`
after retries.

`discretion.py hold` is historical (the old 11:00 hold check). The
all-day session made it moot; everything is still out by 15:50.

## Reasons and locks

Every desk-initiated buy or sell gets `reconcile.py reason` (so later
sync does not treat it as an "adopted" stray). A fill unrecorded for
more than 360 seconds is a state-lag incident; a normal next-tick fill
is not. State writes go through `reconcile.py statewrite` (locked patch
on a fresh re-read). Do not hand-write `morning-session.json`.
