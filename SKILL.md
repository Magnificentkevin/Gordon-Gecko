---
name: gordongecko
description: Kevin's trading desk with two modes. Trade Planner plans one long stock trade (regime check, chart read, risk sizing, pass/fail gate, ticket, confirmed Robinhood order). SILAS Desk runs, rebuilds, reconciles, recaps or retunes the automated live cash-equity day-trading desk. Use for /gordongecko, "plan a trade on TICKER", or anything about running SILAS.
---

# Gordongecko

"Greed is good" - but only inside a risk limit.

Gordongecko is one skill with two modes that share the same broker connection (Robinhood's official Trading connector) and the same agentic account:

| Mode | Use it for | Who decides each order |
|---|---|---|
| **A. Trade Planner** | One trade idea: "plan a trade on NVDA", "should I buy X here?" | Kevin says **yes** to each order |
| **B. SILAS Desk** | The automated weekday day-trading desk: run a fire, rebuild, reconcile, recap, learn | SILAS, inside the hard floors, once Kevin has armed it |

Pick the mode from the request. If it is unclear, ask in one line.

Educational and process tools, not financial advice.

## Files

```
SKILL.md                     this file
scripts/gecko_regime.py      Mode A: market regime + risk multiplier
scripts/gecko_size.py        Mode A: sizing + pass/fail gate
scripts/*.py (others)        Mode B: SILAS helpers (see scripts/README.md)
reference/trade_plan_template.md   Mode A journal template
reference/*.md (others)      Mode B: SILAS procedures and rules
config/example-config.json   Mode B: sanitized SILAS config
```

If the folder is not present (for example the skill was saved without its files), clone it:

```bash
mkdir -p ~/ext && cd ~/ext && git clone -q --depth 1 https://github.com/Magnificentkevin/Gordon-Gecko.git gordongecko && cd gordongecko
```

Python 3.9+ (3.11+ for SILAS helpers). No API keys.

## Broker connection (both modes)

- Use the Robinhood Trading connector tools (`get_accounts`, `get_portfolio`, `get_equity_quotes`, `get_equity_positions`, `get_equity_orders`, `get_equity_historicals`, `get_earnings_calendar`, `review_equity_order`, `place_equity_order`, `cancel_equity_order`).
- Trade only in the one account the connector marks as tradable by the agent (the "MCP" agentic account). Every other account is read-only. Never hardcode its number in files; read it from `get_accounts` or `BROKER_ACCOUNT_NUMBER`. Mask it to the last 4 digits when shown.
- Always `review_equity_order` before `place_equity_order`, and show the quote disclosure it returns verbatim whenever a price from it is shown.
- Limit and stop orders take whole shares only. Fractional shares only on market orders in regular hours.
- Cash equity longs only in both modes: no options, shorts, margin borrowing or crypto.

**Shared account warning:** while SILAS is armed it flattens every equity position in the account before the close (15:50 ET). A Mode A swing trade meant to be held overnight would be sold. Before placing a Mode A order, check whether SILAS is armed (`desk_clock.py next`, `liveMode.armed`); if it is, tell Kevin and ask whether this is a same-day trade.

---

# Mode A: Trade Planner

Runs one trade idea through a fixed process and produces a trade ticket. Never skips the risk steps, never places an order without Kevin's explicit yes.

## Inputs (ask only for what is missing)
- Ticker
- Account equity (read `get_portfolio` buying power if connected)
- Entry idea and a stop (or let ATR set the stop)
- Target (needed for reward:risk)
- Risk already open, % of equity (default 0; read open positions if connected)
- Optional: weekly chart image

## 1. Market regime
```bash
python3 scripts/gecko_regime.py
```
RISK-ON (x1.0), CONSTRUCTIVE (x0.75), CAUTION (x0.5), DEFENSIVE (x0, no new longs). If the script can't reach the data, fetch https://tradermonty.github.io/market-breadth-analysis/market_breadth_data.csv with WebFetch, save it and pass `--csv`; if that fails too, treat the regime as DEFENSIVE. The market-breadth-analyzer skill can give a deeper read.

## 2. Setup read
- With a chart image: trend, support/resistance, 20/50/200-week MAs, volume, 2-3 scenarios with probabilities (technical-analyst skill if installed).
- Without a chart: `get_equity_quotes` for the price, `get_equity_historicals` or `get_equity_technical_indicators` if useful, and confirm the stop sits below real support, not an arbitrary %.
- `get_earnings_calendar`: flag earnings in the next 7 days.

## 3. Size and gate
```bash
python3 scripts/gecko_size.py --account EQUITY --entry ENTRY --stop STOP --target TARGET \
  --regime-mult MULT --open-risk-pct OPEN [--json]
```
Defaults: 1% base risk, 20% max position, 6% max portfolio heat, 2.0 minimum reward:risk, 2% hard risk ceiling. Use whole shares for limit orders.

The gate FAILS on: reward:risk below minimum, DEFENSIVE regime, heat above cap, risk above 2%, or zero shares. A FAIL means no order; explain each reason and what would fix it.

## 4. Trade ticket

| Field | Value |
|---|---|
| Ticker / side | |
| Order | Limit buy N @ $X (gfd or gtc, session) |
| Stop / target | $S / $T, R:R |
| Dollar risk | $R (x% of account) |
| Regime | label, multiplier |
| Gate | PASS / FAIL and why |
| Notes | earnings, chart scenarios, SILAS armed? |

## 5. Execute (gate PASSED only)
1. `review_equity_order` with the exact order. Show the preview, any `order_checks` alerts verbatim, and the quote disclosure.
2. Ask: "Place this order? (yes/no)". Call `place_equity_order` only after an explicit yes for this order. If the review says `customer_approval_required: true` with empty `order_checks`, follow the connector's own flow (Kevin approves in the Robinhood app).
3. Default to a **limit** order at or below the planned entry. Market orders only if Kevin asks.
4. After placing, read it back with `get_equity_orders` and report the status.
5. Offer the protective stop (`stop_limit` or `stop_market` sell, whole shares) and place it only after another yes.
6. Never place Mode A orders on a schedule or in a loop.

## 6. Journal
Save the ticket and reasoning as `journal/YYYY-MM-DD_TICKER.md` using `reference/trade_plan_template.md`.

## Mode A rules that never bend
1. No stop, no trade.
2. Size comes from risk, never from conviction.
3. DEFENSIVE or UNKNOWN regime means no new longs.
4. Total open risk stays under 6% of equity.
5. No order without an explicit yes.

---

# Mode B: SILAS Desk

The operating manual for the SILAS live cash-equity day-trading desk. All times America/New_York (ET). Refer to the account as **the live account**.

## When to use
- Run a scheduled desk fire (scan, research, premarket paper, live manage, flatten, recap, evening learn).
- Rebuild procedures, config, helpers and the weekday routine after a reset.
- Apply or review a risk-profile change Kevin confirmed.
- Reconcile the book, verify protective stops, or trip/restart the bank stop.
- Write the daily LIVE recap or the pre-open PAPER summary.
- Tune parameters inside published bounds after enough trades.

## Authority
Kevin has delegated trading-procedure decisions to SILAS until he cancels that: inside the hard floors, SILAS decides entries, exits and tuning on evidence, logs each decision, and does not wait for approval on each trade. Material rule changes are reported.

Kevin's direct commands always take effect immediately: pause, disarm, arm, stop, cancel an order, flatten, or restart after a bank stop. Only Kevin can arm, disarm, pause, or restart after a bank stop. The system stops only on Kevin's explicit command or when the 50% bank stop trips. The day kill switch pauses new buys for that day only.

## Hard floors (never auto-tuned)
These override every other line in procedures, config and helpers:

1. **Protective stop** on every whole-share fill: `stop_limit` with trigger `entry × 0.955` (round up) and limit `entry × 0.95` (round down). Verify with `reconcile.py stopargs` before sending and `verify-protection` after.
2. **−5% market-sell backstop** every fire (`risk_floors.py trade-cap`) if the bid is at or below entry × 0.95.
3. **5% max loss per trade** from entry. No stop or limit below entry × 0.95.
4. **50% bank stop.** Baseline = live-account equity at measurement start, plus later deposits, minus withdrawals. Stop line = 50% of baseline. A bad or zero portfolio read never trips. On a trip: flatten, cancel all orders, idle until Kevin restarts (`risk_floors.py bank-restart`).
5. **Flatten before the close** (15:50, 15:55 backup). Nothing overnight.
6. **Cash equity longs only.** No margin, options, shorts or crypto.
7. **Kevin-only** arm, disarm, pause and post-bank-stop restart.
8. **Day kill switch:** 2 consecutive losing stops or a −5% day → no new buys that day; exits only.
9. **Protect first**, every fire 09:30–16:00, from a fresh broker read this fire. If a whole-share position can't be protected after one retry, exit it. No new buys while protection is unverified.
10. **Broker truth.** Positions and open orders come only from this fire's broker reads. The state file is a log.

Details: [Risk rules](reference/risk-rules.md).

## Current risk profile: `higher-risk+15`
Applied 2026-11-17 09:29 ET after Kevin confirmed a 15% wider risk tolerance. Supersedes older −2%/−3% and 4/5–5/5 lines deeper in some procedure files. Hard floors unchanged.

| Knob | Value |
|---|---|
| Recovery decision point | −3.45% (bid ≤ entry × 0.9655 → run `recovery.py score`) |
| Recovery hold threshold | 26 before 10:00, 38 from 10:00 |
| TA | 3 of 5, all day |
| After-10:00 A+ entries | watchlist score ≥ 0.51, TA ≥ 3/5, until 13:30, max 3, never a re-entry |
| Round-trip cap | 9 (max 2 slots) |
| Stall exit | 14 minutes if high-water < +1% |
| Take-profit floor | 5% (trailing lock from +2%) |
| Price floor | $1.00 |
| Sizing | full cash across free slots |
| Re-buy after a losing exit | never, same day (recycling a winner is allowed) |

`desk_learn.py` must not tune the guarded knobs (stall minutes, TA count, recovery threshold) until there are at least **6 live trades dated on/after 2026-11-17** under this profile. The decision point stays Kevin-locked at −3.45%. See [Self-learning](reference/self-learning.md).

Prime directive: **+5 percentage points of decision success** vs baseline 25.8% (goal 30.8%). An entry is correct if the round trip finished green; a loss exit is correct if price did not reclaim entry for the rest of the session. Daily target +5% of start bank is a goal, not a reason to loosen a floor. At ≥ +5%, protect mode locks a +3% floor and allows only A+ adds.

## Daily loop (weekdays)
One routine every 5 minutes, 05:30–18:15 ET (`CRON_TZ=America/New_York */5 5-18 * * 1-5`). Each fire reads the dispatcher (`desk.md`) and runs `desk_clock.py next` for phase, paths and mode (`paper` or `live`). Idle fires are silent.

| When (ET) | Phase | What happens |
|---|---|---|
| 05:30+ | scan | Universe + shortlist; post-exit labels from yesterday |
| 07:00 | research | News + catalysts → `kb/watchlist-<date>.json` |
| 07:30–09:29 | paper-premarket | Separate paper book; self-test the helpers |
| ~09:20 | paper-summary | One PAPER line to Kevin (pass/fail) |
| 09:30 | live switch | Automatic unless Kevin paused or disarmed it |
| 09:30–15:45 | manage (+ entries) | Protect first, bank-check, entries 09:35–10:00, A+ until 13:30, recovery, stall, trail; paper shadow ticks alongside |
| 15:50 / 15:55 | flatten / hard-flatten | Everything out; verify flat |
| 16:00–16:15 | report | One LIVE recap, claimed with `desk_clock.py report-claim` |
| 18:00 | kb-refresh + learn | Append the knowledge log; `desk_learn.py patterns` then `learn --apply` |

Full timetable: [Schedule and phases](reference/schedule-and-phases.md).

## Entries, TA, manage, recovery
- **Live setups** (09:35–10:00): `gap_and_go`, `early_momentum`. After 10:00 only the A+ path.
- **Hard filters:** day-move 8–25% (8–15% ranks first), RVOL ≥ 1.75, time-of-day liquidity, spread, bid-to-stop anchored at ask × 0.98 (`bidToStopPct` −2.0), $1 floor, dilution/offering veto, merger/tender veto, no same-symbol re-buy after a losing exit today.
- **TA (5 checks, need 3):** volume shape, StochRSI, session VWAP, Bollinger 20/2, Fibonacci. Skip if data is incomplete. Prefer price ≥ VWAP; don't chase a first-5-minute peak that already lost the opening-range high or VWAP.
- **On every fill:** place the hard stop in the same tool sequence, then size a dynamic target with `tp_model.py` (floor 5%). Trail from +2%. Never leave a take-profit and a stop resting together.
- **While bid ≤ entry × 0.9655:** `recovery.py score` every fire. Exit on the first score under the threshold (26 / 38). Otherwise hold to the hard stop.
- **Fractional lots** (only when one share costs more than available cash and the name is fractional-eligible): Robinhood rejects resting stop-limits on them, so watch a virtual stop about every 60 seconds; max one fractional position.

See [Entries and TA](reference/entries-and-ta.md) and [Manage and recovery](reference/manage-and-recovery.md).

## Reporting
Quiet except:
1. **One** pre-open paper summary (`PAPER — …`); prefix `ESCALATION: ` if a self-test failed.
2. **One** daily live recap (`LIVE — …`): wins, losses, start $ → final $, net, decisions right vs the 25.8% / 30.8% goal.
3. Unfixable errors, guard trips, bank stop and material rule changes, immediately.

No duplicates; silent on idle fires. Claim the recap with `desk_clock.py report-claim`; if `ok` is false, send nothing. Template: [Reporting](reference/reporting.md).

## Helpers
Command reference: [scripts/README.md](scripts/README.md).

| Helper | Role |
|---|---|
| `desk_clock.py` | Phase, mode, claims, report-claim, 09:30 live switch |
| `risk_floors.py` | `bank-check`, `trade-cap`, `flow`, `bank-restart` |
| `reconcile.py` | Order-id sync, `stopargs`, `verify-protection`, locks, `statewrite`, frac watch |
| `ta.py` | 5-check scorer + hard filters |
| `recovery.py` | Hold/exit score at the decision point; post-exit labels |
| `tp_model.py` | Dynamic target and trail |
| `discretion.py` | Kill switch, protect mode, entry gate, sizing |
| `desk_learn.py` | Patterns, watchlist, bounded `learn --apply`, decision-rate |
| `premarket_paper.py` | Premarket paper session + self-test |
| `paper_shadow.py` | Market-hours paper shadow alongside live |
| `paper_broker.py` | Local paper broker (same order shape as the MCP) |
| `paper_guard.py` | In paper mode, refuse live order tools |

Layout (override with env vars):
```
${DESK_ROOT}/live/     desk.md and phase procedures
${DESK_ROOT}/kb/       watchlists, patterns, day-trader KB
${HELPERS_DIR}/        these scripts
${DESK_CONFIG}         session config (start from config/example-config.json)
${DESK_DATA}/          morning-session state, ledgers, paper books
${KB_DIR}/             kb-log.md, kb-summary.md, catalyst calendar
```
Environment: `BROKER_ACCOUNT_NUMBER` (required for broker calls), `DESK_CONFIG`, `DESK_DATA`, `DESK_ROOT`, `HELPERS_DIR`, `KB_DIR`, `TZ=America/New_York`. Several helpers default to the old `/workspace/...` layout if unset.

Broker writes in live mode only and only when armed: `place_equity_order`, `cancel_equity_order`, with `market_hours="regular_hours"`, `time_in_force="gfd"`. Save each raw response to a file and pass it to the helpers; never invent quotes or positions. In paper mode use `paper_broker.py` instead of any live write (`paper_guard.py` enforces this).

## How to run a fire
1. Set `TZ=America/New_York` and the env vars. Confirm the connector is authenticated and aimed at the live account.
2. `python3 ${HELPERS_DIR}/desk_clock.py next`: honor `executionMode`, `paused`, `bank_stop_tripped` and the phase. If idle, exit silently.
3. Read the dispatcher and the phase procedure. The profile block at the top of each procedure supersedes older conflicting lines lower down.
4. If live and 09:30–16:00: fresh positions, orders and portfolio → `verify-protection --apply` → `risk_floors.py bank-check --portfolio <raw> --apply` (exit 9 → bank-stop procedure in [Risk rules](reference/risk-rules.md)) → `risk_floors.py trade-cap`. If the portfolio file has wrapper text around the JSON, strip it and re-run; "unreadable" is never a trip.
5. Do the phase work. Every manage fire also ticks `paper_shadow.py` when live.
6. Mark the phase done/failed through `desk_clock.py`. Message only when the reporting rules say so.

## How to rebuild
1. Restore from backups, Drive, or this skill. Place no orders during a rebuild.
2. Install helpers from `scripts/`. Copy `config/example-config.json` to `${DESK_CONFIG}`; set the live-account env, the real baseline equity and paths.
3. Recreate procedures under `${DESK_ROOT}/live/` (`desk.md` plus one file per phase). Every file starts with the hard-floor locks and the **current** profile block. Re-apply `higher-risk+15` after any regenerate from old `_build.py` templates.
4. Recreate state from a **fresh** broker portfolio/positions/orders read. Never run `reconcile.py sync` on an empty or placeholder orders file.
5. Schedule the single weekday 5-minute routine pointed at `desk.md`.
6. Confirm `liveMode.armed` and `desk.paused` match Kevin's last instruction. Run a premarket paper self-test before the next open. Tell Kevin the desk is armed, or what is still missing.

## Lessons and context
Known failure modes (stale "book not flat" flags, skipped worker steps, empty watchlists, a usage outage missing manage fires, same-symbol re-buys after a loss going 0/6): [Lessons learned](reference/lessons-learned.md).

SILAS the company is Scheduled Intelligent Logistical Autonomous Services for All Business Cleaning. The SILASGrok Turborepo plan is **paused**; don't start it unless Kevin asks. [SILAS platform](reference/silas-platform.md).
