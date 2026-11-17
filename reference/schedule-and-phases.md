# Schedule and phases

All times America/New_York. The desk runs weekdays only. One routine fires
every 5 minutes from 05:30 through 18:15:

```
CRON_TZ=America/New_York */5 5-18 * * 1-5
```

Each fire reads the dispatcher (`${DESK_ROOT}/live/desk.md`) and runs:

```
python3 ${HELPERS_DIR}/desk_clock.py next
```

Honor the JSON it prints: `phase`, `executionMode` (`paper` or `live`),
paths, `paused`, `bank_stop_tripped`, `protectFirst`, and any claim token.
If the phase is idle, exit silently. A stuck claim auto-expires after
`desk.phaseTimeoutMinutes` (defaults: scan 15, manage/default 12, report 8,
kb-refresh 20). Retry on the next fire; max 3 attempts, then escalate.

`executionMode` decides the broker: `live` uses the broker MCP on the live
account; `paper` uses `paper_broker.py` and must never call a live write tool
(`paper_guard.py check-call` / `audit`).

## Clock

| Time (ET) | Phase | Procedure | Notes |
|---|---|---|---|
| 05:30+ | `scan` | `scan.md` | First fire at/after 05:30. Late catch-up after 10:00 if the morning scan was missed. |
| 07:00 | `research` | `research.md` | `desk.researchEt`. Builds or refines the day's watchlist. |
| 07:30–09:29 | `paper-premarket` | `paper-premarket.md` | Every fire in the window. Separate paper book. |
| ~09:20 | `paper-summary` | `paper-summary.md` | Once. Fallback if the 09:20 fire was missed, still before 09:30. |
| 09:30 | live switch | `desk_clock.py` | Automatic when `liveMode.autoSwitchAtOpen` is on, unless `desk.paused` or `liveMode.armed` is false. This switch is not itself an arm/disarm. |
| 09:30–15:45 | `manage` (and `entries`) | `manage.md`, `entries.md` | Manage every fire while the book needs it, including when flat during the buy window. First entries 09:33–10:00 (`entries.md`; retry `entries-backup.md`). After 10:00, only the A+ path inside manage. |
| 15:50 | `flatten` | `flatten.md` | Flatten all, write the scorecard, propose-only revise. |
| 15:55 | `hard-flatten` | `flatten-backup.md` | Safety net if anything is still held or resting. Does not run while flatten still owns the book. |
| 16:00–16:15 | `report` | `report.md` | Once, after the desk is done. Fallback ~16:05. Claim first. |
| 18:00 | `kb-refresh` | `kb-refresh.md` | Friday's run includes the weekly block (no Saturday run). Then `desk_learn.py`. |

`desk.flattenAtEt` is 15:50; `hardFlattenMinutesBeforeClose` is 5 (15:55);
`reportEarliestEt` is 16:00; `newEntryCutoffEt` / `manage.noNewEntriesAfterEt`
is 15:45 (exits only from 15:45 to the flatten). Honor exchange holidays and
early-close maps in `desk.holidays` / `desk.earlyClose` when they are set.

Older procedure text may still mention an 11:00 flatten, a 10:55–11:01
blackout, or a 11:30 late-buy cutoff. Those are superseded by the all-day
session (from 2026-11-10) and by the current profile block at the top of
each file. After 10:00, new live buys follow the A+ path only, until 13:30.

## Phase contracts

### scan (05:30)

- Install a new `sessionDate` through `reconcile.py statewrite` (or the
  scan's locked `--replace`) when the calendar day rolls. Round-trip
  counters reset only on a new session date.
- Pull a fresh universe (US-listed common stocks and ETFs the broker marks
  tradable). Apply hard filters at a coarse level; do not force thin names
  onto the shortlist.
- Prefer watchlist names from last night's `desk_learn.py watchlist` and
  this morning's research.
- If yesterday had unlabeled exits, run `recovery.py post-exit` on
  rest-of-session bars and, if useful, the next-day open.
- Place no orders.

### research (07:00)

- Free sources only. Ignore ads, paid promo, and opinion posts.
- Write `${DESK_ROOT}/kb/watchlist-<YYYY-MM-DD>.json` with scored names
  (catalyst quality, gap quality, news). After 10:00 the A+ path needs
  score ≥ 0.51.
- Event-veto tender-offer, Dutch-auction, and merger-arb names (see
  [Entries and TA](entries-and-ta.md#event-veto)).
- Place no orders.

### paper-premarket (07:30–09:29)

- `premarket_paper.py` init / tick / selftest against a **separate** paper
  book, starting from illustrative or current cash (never mixed with the
  live ledger).
- About 22 checks in the self-test (helpers, stopargs, protect, flatten
  path, paper guard). All must pass before advertising a clean pre-open.
- This session is allowed to "trade" only through `paper_broker.py`.

### paper-summary (~09:20)

- One message to the owner. See [Reporting](reporting.md).
- After sending, the desk stays in paper until the 09:30 switch.

### entries (09:35–10:00) and manage (09:30–15:45)

- Protect first, bank-check, trade-cap, then decide.
- Live first entries: `gap_and_go` and `early_momentum` that pass filters
  and TA 3/5. Size with full cash across free slots (max 2).
- Stop-on-fill in the same tool sequence as the buy fill, before any other
  tool call.
- After 10:00: at most 3 A+ live entries until 13:30, never a re-entry.
- Every live manage fire also runs a short `paper_shadow.py tick` (budget
  ~20s) so the shadow ledger stays current.
- Fractional positions: 1-minute virtual-stop watch inside the fire
  (window ~4.5 minutes).
- Record a reason on every desk buy and sell (`reconcile.py reason`).

### flatten (15:50) and hard-flatten (15:55)

- Cancel resting orders, verify, market-sell every position, re-read, run
  `reconcile.py sync --apply` and `risk_floors.py bank-flat-done`.
- Regular hours only. Never place extended-hours orders.
- Write the day's scorecard under `${DESK_ROOT}/<date>-scorecard.md`.
- Daily revise is propose-only (file proposals; do not silently edit locks
  or hard floors).
- If not flat, the next fire repeats. Escalate `FLATTEN_INCOMPLETE` if it
  still is not flat after retries.

### report (16:00)

- `desk_clock.py report-claim --date <D>` first. If `ok` is false, send
  nothing (already claimed or the desk is not done).
- Build the simple recap from broker cash + the reconciled ledger. Exclude
  owner deposits and withdrawals from P&L.
- In paper mode the only live-account call is a read-only orders audit for
  `paper_guard.py audit`. Never feed that file to `reconcile.py`.

### kb-refresh (18:00)

- Idempotent on a `## Run <date>` evening-refresh heading in `kb-log.md`.
- Research the close, after-hours catalysts, and any broker/rule changes.
  Verify market-moving items with two sources or mark them UNVERIFIED.
- Update `kb-summary.md` only when a durable lesson changes.
- Then self-learn: `desk_learn.py patterns`, `learn --apply`, and a
  watchlist for the next session. Send nothing to the owner.

## Mode switch and pauses

- 07:30–09:29 is always paper, even if `executionMode` will be live later.
- At 09:30, if armed and not paused and the bank stop is not tripped, the
  clock flips to live automatically.
- `desk.paused=true` or `liveMode.armed=false` keeps every later fire idle.
- A tripped bank stop idles every phase, including paper and the recap,
  until the owner restarts. The escalation is the message, once per day,
  until restart.

## Single-routine vs older crons

Early versions used ~11 separate crons (scan, refresh, entries, two manage
streams, several flattens, report checks). That design raced with itself
(stop ↔ take-profit swaps, flatten 403s). The single routine plus
per-symbol `reconcile.py lock` (TTL 120s) replaced it. Do not reintroduce
twin manage crons.
