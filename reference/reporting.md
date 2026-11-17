# Reporting

The desk is quiet. Most fires send nothing. The owner hears from the desk
only in the cases below, each at most once.

## 1. Pre-open paper summary (~09:20 ET)

One line, sent after the premarket paper session's self-test. Then remind
the owner that the desk switches to live at 09:30 ET unless they pause or
disarm it.

Pattern:

```
PAPER — <Weekday Mon DD> pre-open: all <N> checks passed. <What the paper
book did, in plain language>.

The desk switches to live at 9:30 AM ET unless you pause it.
```

If any self-test failed, prefix `ESCALATION: ` and say what failed and
what you did (or could not do). Do not switch the failure into a "passed
with notes" line.

Illustrative examples (not live balances):

```
PAPER — Tue Nov 17 pre-open: all 22 checks passed. The paper book made no
trades and stayed at $100.00, because none of today's watchlist names
passed the chart or price-move checks.

The desk switches to live at 9:30 AM ET unless you pause it.
```

```
ESCALATION: PAPER — Tue Nov 17 pre-open: 2 of 22 checks failed
(verify-protection could not confirm a test stop-limit; bank-check
rejected a wrapped portfolio fixture until the wrapper was stripped).
The paper book did not trade. I will not treat the self-test as green.
The automatic 9:30 AM ET live switch is still scheduled unless you pause
or disarm it.
```

## 2. Daily LIVE recap (16:00 ET, once)

Claim first:

```
python3 ${HELPERS_DIR}/desk_clock.py report-claim --date <YYYY-MM-DD>
```

If `ok` is false, send nothing. After a successful send, mark delivered
with one `reconcile.py statewrite` (`reportDeliveredFor`,
`reportDeliveredAt`, `reportDeliveredBy`). If the send failed, do not
set the flag, so the next fire can retry.

Write the recap in your own words. Keep it to one short stanza:

- Wins and losses
- Start equity → final equity, and the net
- One decision-success line vs baseline 25.8% and goal 30.8%
- Owner deposits or withdrawals are **excluded** from P&L (mention a
  deposit only if it is needed to explain why the bank changed by more
  than the day's trading)
- A no-trade day still gets a recap: 0 wins, 0 losses, unchanged equity,
  and that there were no decisions (the baseline is unchanged)

Illustrative examples:

```
LIVE — Fri Nov 13: 1 win, 0 losses, $100.00 → $101.43 (+$1.43). 1 of 1
decisions were right today (baseline 25.8%, goal 30.8%). The only trade
was a gap-and-go that reached the take-profit. The account is flat, all
cash.
```

```
LIVE — Mon Nov 16: 0 wins, 0 losses, $101.43 → $101.43 (no change). No
trades today means no decisions to score, so the baseline stays 25.8%
and the goal 30.8%. No candidate passed the entry filters, and nothing
on the watchlist reached the 0.51 score needed for an entry after 10:00.
The account is all cash.
```

Extra lines only for escalations (flatten incomplete, a floor that had
to be used, a usage outage that skipped fires, a profile change already
applied). Do not paste scorecards, option chains, or helper JSON into
the recap. Do not include the account number.

In paper mode the recap starts with `PAPER — ` and uses paper fills.
A live-mode recap starts with `LIVE — `.

## 3. Immediate escalations

Send at once, without waiting for 16:00, and only once per event:

- Bank stop tripped (system stop) or flatten-incomplete after retries
- Unfixable broker or helper error (repeated 403s, unable to protect a
  position, unable to flatten in regular hours)
- Guard trip: paper mode almost called a live write tool; `paper_guard`
  audit found a live order in a paper window
- Material rule or profile change the desk just applied
- A usage, auth, or MCP outage that caused missed manage fires — tell
  the owner what window was missed and where to restore capacity
- Stale or conflicting arm/pause state that would keep the desk idle at
  the open when the owner expects it to trade (ask; do not arm yourself)

Do not escalate ordinary "no setup, no trade" fires, a thin watchlist
that correctly blocked A+ entries, or a `desk_clock` "book not flat"
hint that a fresh broker read disproved (fix the state, stay quiet
unless flatten is actually stuck).

## What never goes out

- Idle fire heartbeats
- Duplicate recaps or duplicate paper summaries
- Full account numbers, tokens, or raw portfolio dumps
- Procedure-level "needs your OK" proposal lists — those stay with the
  parent / desk log; the owner is not a rubber stamp on daily revise
- Crypto, options, or research-lab notes mixed into the equity recap

## Numbers

- Cash and equity from this fire's broker portfolio, reconciled against
  the ledger. Prefer fill-math that matches broker cash when flat.
- Decision-rate from `desk_learn.py decision-rate --date <D>`.
- Bank-stop line from `risk_floors.py bank-status` (current baseline +
  cash flows), never from a remembered number in an old recap.
