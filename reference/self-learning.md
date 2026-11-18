# Self-learning

> **Evaluation revisions 2026-11-17 20:06 ET (supersede conflicting lines below).** Source: `reports/Gordongecko strategy evaluation.md`; bank stop confirmed by Kevin.
> - Guards raised: `riskProfile.minTradesBeforeTune` 30 (was 6), `selfLearning.minTrades` 30 (was 8), `entryPlaybook.promote/demote.minTrades` 30 (was 10).
> - **Expectancy gate:** scale size or promote a setup only after ≥ 100 live trades with win % > avgLoss/(avgWin+avgLoss) (`config.expectancyGate`). Decision success is a secondary diagnostic.
> - v2 bound change for the paper test: `minLastPriceAtEntry` may reach 5.00.


The desk is allowed to retune a short list of knobs from its own results,
inside published bounds, and only after enough evidence. Hard floors and
the owner-locked decision point never move this way.

## When it runs

During the 18:00 kb-refresh, after the live day and the premarket paper
session are in, and on request when rebuilding the knowledge base:

```
python3 ${HELPERS_DIR}/desk_learn.py patterns
python3 ${HELPERS_DIR}/desk_learn.py learn --apply --date <YYYY-MM-DD>
python3 ${HELPERS_DIR}/desk_learn.py watchlist --date <next-session> --news <evening-research.json>
python3 ${HELPERS_DIR}/desk_learn.py decision-rate --date <YYYY-MM-DD>
```

`patterns` writes `${DESK_ROOT}/kb/patterns.json` and
`day-trader-kb.md` (do not hand-edit the numbers). `learn --apply` is the
only config write this phase may make. `decision-rate` produces the
recap's "N of M decisions were right" line (add `--paper` for the
market-hours shadow).

Cap: at most **3** parameter changes per day. Lookback is about 40
trades, with a general minimum of 8 before ordinary knobs move.

## Current profile guard

For `higher-risk+15`, these **guarded** knobs stay frozen until there
are at least **6 live trades taken on or after 2026-11-17** under this
profile (recovery labels also use only those dates):

- `stallExit.afterMinutes`
- `entryFilters.ta.requiredPassCountByTime` (the all-day count)
- `recoveryModel.thresholdPct` (and its early offset effect)

After that, tune **from the new values**, not from the pre-November-17
ones: TA count ±1 within 3–5, stall ±2 minutes within 8–25, recovery
threshold within 26–70 step 5. `recoveryModel.decisionPointPct` stays
**owner-locked at −3.45%**.

## Bounds (ordinary knobs)

| Parameter | Min | Max | Step |
|---|---|---|---|
| `tpModel.floorPct` | 2.0 | 6.0 | 1.0 |
| `stallExit.afterMinutes` | 8 | 25 | 2 |
| TA required pass count | 3 | 5 | 1 |
| `entryFilters.minLastPriceAtEntry` | 0.50 | 3.00 | 0.50 |
| Liquidity band shares | 25,000 | 200,000 | 25,000 |
| Kill-switch day P&L % of start bank | −7.0 | −3.0 | 1.0 |
| `recoveryModel.thresholdPct` | 26 | 70 | 5 |
| Recovery weights | 0.02 | 0.35 | 0.02 |

The $1 price floor and the 100k/200k-style liquidity bands already in
config are starting points; learning may move them only inside the
table. Prefer a narrow, revertible gate on a losing bucket, with a
logged revert test, over a broad filter change.

## Locked (never learned)

Bank stop, per-trade 5% cap, hard-stop geometry (trigger 0.955 / limit
0.95), recovery decision point, `desk.paused`, `liveMode`, flatten-before-
close, cash-equity-longs-only, owner-only arm/disarm/pause/restart,
broker-truth reconcile, and the premarket-paper session identity.

## Decision success (prime directive)

Baseline **25.8%**, goal **30.8%** (+5 percentage points), from 60 live
round trips (2026-10-05 through 2026-11-10) = 120 labeled decisions
(entry + exit).

| Decision | Correct when |
|---|---|
| Entry | The round trip closed with `pnlUsd > 0` |
| Loss exit (score sell, hard stop, or any losing exit) | Price did **not** get back to entry for the rest of the session |
| Hold at the decision point | Price got back above the decision point before touching the −4.5% trigger |
| Stall exit | Price did not rise ≥ 2% above max(entry, exit) for the rest of the session |
| Profit exit (TP / trail / profit give-back) | Price did not rise ≥ 2% above the exit for the rest of the session |
| Blocked (only if an outcome can be measured) | The blocked name would **not** have reached +2% before the decision-point decline |

Deposits and withdrawals are not P&L and are not decisions. Report the
rolling rate vs goal on the daily recap when there was at least one
decision. A no-trade day does not change the baseline.

## Setup promotion and demotion

Paper-only setups (`recycle_bounce`, `orb_breakout`, `midday_momentum`,
`vwap_reclaim`, `momentum_pullback`) move to live only when paper-session
evidence meets `entryPlaybook.promote` (typically ≥ 10 trades, win rate
≥ 40%, average ≥ +0.5%). Demote a live setup that, over a 15-trade
lookback with at least 10 trades, falls to a 30% or lower win rate —
except that hard floors and the no-rebuy-after-loss rule are not
"demoted."

## Knowledge files

| File | Role |
|---|---|
| `${KB_DIR}/kb-log.md` | Append-only run log. Corrections are appended, never silent edits |
| `${KB_DIR}/kb-summary.md` | Durable, deduped lessons |
| `${KB_DIR}/catalyst-calendar.md` | Dated upcoming events |
| `${DESK_ROOT}/kb/patterns.json` | Machine summary of live (and paper) evidence |
| `${DESK_ROOT}/kb/day-trader-kb.md` | Generated narrative; do not hand-edit numbers |
| `${DESK_ROOT}/kb/watchlist-<date>.json` | Next-session candidates |
| `${DESK_ROOT}/kb/research_evening_<date>.json` | After-hours catalyst feed into the watchlist |

Research uses free sources. Ignore ads, course promos, and prediction-
market content. Cite URLs in the log. Unbacktested indicator claims stay
hypotheses until parameters, timeframe, sample size, out-of-sample
result, and costs are recorded.
