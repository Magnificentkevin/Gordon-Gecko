# Lessons learned

Evidence from live trading and from the 21-session market-wide backtest
(2026-09-22 through 2026-10-20), plus operational incidents on the desk.
Use these to interpret new results; do not treat any one day as a reason
to break a hard floor.

## Trading evidence

### Do not re-buy a loser the same day

Same-symbol re-buys after a losing exit went **0 for 6** in the early
live record (and later still lagged: roughly 20% wins on a larger
re-entry bucket, with negative average R). First entries were the edge.
The rule is standing: never re-buy a symbol that already closed at a
loss today. Recycling a **winner** remains allowed when filters pass,
but `recycle_bounce` as a class has been a weak live setup (about 29%
wins, slightly negative average) and stays off the default live playbook
except for that narrow winner-recycle path.

### The opening drive is where the edge is

Live time slots (approximate, accumulated through mid-November 2026):

- 09:30–09:45: best slot (~43% wins, ~+1.2% average)
- 09:45–10:00: still acceptable (~42% wins, smaller average)
- 10:00–10:30: poor (~10% wins, ~−2.1% average)
- 10:30–11:30 and later: weak; midday continuation is the lowest-quality
  slot historically

That is why live first entries sit in 09:35–10:00 and everything after
10:00 must clear the A+ watchlist path (score ≥ 0.51, TA 3/5, until
13:30, max 3, no re-entry). An empty or low-scoring watchlist means
**no** after-10:00 trade, not a looser gate.

### Setups

- `gap_and_go` is the only clearly positive live setup (about n=22, ~41%
  wins, ~+1.13% average).
- `orb_breakout` and most midday tags have not earned promotion.
- Winners that reach a +2% high-water tend to run (average in the mid-
  single-digit percents) — keep the take-profit floor high (now 5%) and
  trail from +2%.
- Trades that never print a +0.5% high-water almost never win — stall
  exit (now 14 minutes if high-water < +1%) exists for that reason.

### Price, day-move, and structure

- In the 21-session backtest, names under $2 were reliably negative;
  $20–50 was the only band with positive point expectancy, on a small
  sample. Bank size does not create edge; it only changes which names
  are affordable as whole shares.
- Day-move 8–15% is least bad. Moves above 15% were stopped out often
  (about 65–75% in that study). The live gate is 8–25% with a ranking
  preference for 8–15%.
- Median ≥5% gappers faded from 09:35 into the close. If a gapper's high
  prints in the first 5 minutes and price is already below the
  opening-range high or VWAP, do not buy.
- A wider structure stop was a research hypothesis; the live hard stop
  is still −4.5% / −5%. The recovery decision (now −3.45%) is how the
  desk uses more room without moving that floor.

### Events, halts, and costs

- Tender-offer, Dutch-auction, and merger-arb names are pinned; veto
  them (see [Entries and TA](entries-and-ta.md#event-veto)).
- A halt or LULD reopen can fill a marketable limit far from the posted
  price (observed on a take-profit, in the desk's favor, once). The same
  mechanism can gap a stop through its limit — keep GAP GUARD on.
- For a small cash book, commissions and official sell fees are
  effectively zero; the real costs are spread and slippage. Spreads
  widen sharply under $2. Model that, not a commission line.
- Resting stop-limits on whole shares generally filled at or near the
  stop in the early live sample. The residual risk is the unfilled or
  gapped case, which is why `trade-cap` exists.

### Reconcile and fractional lots

- Reconcile by **order id** from a fresh broker read. Symbol-based
  reconcile from old snapshots lost or duplicated trades.
- A broker MCP may show a stop-limit as `type="limit"` + `trigger="stop"`.
- Typical broker rules (e.g. Robinhood) reject resting stop and
  stop-limit orders on fractional quantities. Do not retry them. Use the
  1-minute virtual watch. A 5-minute-only check let a fractional lot
  slip past the intended stop. Max one fractional position.

## Operational incidents (fix these, don't hide them)

### Workers skipping steps

Manage fires have skipped the paper-shadow tick, a fresh portfolio read,
`bank-check`, or a full read of `manage.md`. The contract is: every
manage fire does protect-first, bank-check, trade-cap, recovery scores
for names at or through the decision point, and the paper-shadow tick
when live. If time is short, cut research and new entries, not the
floors.

### Stale "book not flat"

`desk_clock` can flag a stale "book not flat" after the broker book is
already flat. Always re-read positions and orders this fire. Treat the
clock's `book` as a hint. Believe the broker. Repair the state quietly
unless flatten is actually incomplete.

### bank-check wrapper text

`risk_floors.py bank-check` returns unreadable when the saved portfolio
file still has tool wrapper text around the JSON. Strip the wrapper and
re-run. Never treat an unreadable or zero read as a bank-stop trip.

### reconcile refuses an empty orders file

That is intentional. Fetch a complete `get_equity_orders` snapshot
(all pages) before `sync --apply`. Do not invent a placeholder.

### Stale bank-stop line in a report

Some fires quoted an old stop line after a deposit had raised the
baseline. Always recompute from current baseline + recorded cash flows
(`bank-status`) before speaking.

### Empty or weak watchlists

A morning watchlist can come back empty, or with scores well under the
A+ threshold (for example 0.3 vs 0.51). After-10:00 entries then stay
unused. That is correct behavior. Do not loosen the A+ path mid-session
to force a trade. Improve the evening research instead.

### Usage or capacity outages

If the host platform runs out of usage mid-session, manage fires are
missed and stops may go unwatched except for what is already resting at
the broker. Tell the owner as soon as you know, including the missed
window, and point them at their usage or plan settings. The resting
hard stop-limit is the backstop for whole shares; fractional lots are
more exposed because their stops are virtual.

### Rebuild pitfalls

- Regenerating procedures from older `_build.py` or `_build_paper.py`
  can drop the current profile block at the top of each file.
- `desk_clock.py`'s new-week template has in the past written a stale
  `stopLossPct`. After a week roll or a regenerate, confirm the active
  profile is actually in config and in the procedure headers.
- Paper copies under `live/paper/` can lag the live profile. Do not
  run paper against stale locks.

### Race history (already mitigated)

Twin manage crons used to swap a stop and a take-profit or race flatten
(403 "cannot be cancelled" / "not enough shares"). The single 5-minute
routine, the 120-second per-symbol order lock, and the no-retry-on-403
rule are the fix. Do not bring back parallel manage crons.


## 2026-11-17 LUCK paper trade (Mode A): stop at the crowd's level
Bought 5 @ $4.11 with the stop at $3.94, exactly the morning low. An 11:30 dip to $3.91-3.92 swept it (-$0.85, -1R), then LUCK recovered to $4.14. Lesson: place the stop beyond the obvious level (a few ticks or ~0.35 x ATR5 past it, stepped past .00/.50) and derive the entry from it: max buy = stop / 0.95. A stop at $3.89 needed a buy at or below $4.09; moving the stop to $3.89 from a $4.11 entry would have broken the 5% cap (5.35%). Never widen the stop to fit the entry.
