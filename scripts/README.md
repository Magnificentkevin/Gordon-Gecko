# Helper CLI

Python 3.11+ recommended. Set `TZ=America/New_York`. These scripts score,
reconcile, and enforce floors; they do not place live broker orders
themselves (except the local `paper_broker.py` stand-in). The agent calls
the broker MCP, saves the raw JSON to files, and passes those files in.

## Environment

| Variable | Required | Purpose |
|---|---|---|
| `BROKER_ACCOUNT_NUMBER` | Yes, for any account-scoped call | Live account id. Never hardcode it. |
| `DESK_CONFIG` or `RECONCILE_CONFIG` | Recommended | Session config JSON (start from `../config/example-config.json`) |
| `DESK_DATA` | Recommended | State, ledgers, paper books |
| `DESK_ROOT` | Recommended | Procedures (`live/`) and `kb/` |
| `HELPERS_DIR` | Recommended | This directory |
| `KB_DIR` | Optional | `kb-log.md` / `kb-summary.md` |
| `TZ` | Yes | `America/New_York` |

Several helpers still default to the historical `/workspace/...` layout
if an env var is unset. When you install the skill somewhere else, set
the variables or symlink that layout. Run the scripts from a working
directory the agent can write to.

## Commands

### desk_clock.py

```
python3 desk_clock.py next [--now ISO] [--ledger PATH] [--state PATH] [--broker PATH]
python3 desk_clock.py done  --phase PHASE [--note TEXT] [--now ISO]
python3 desk_clock.py failed --phase PHASE [--error TEXT] [--now ISO]
python3 desk_clock.py report-claim --date YYYY-MM-DD [--state PATH] [--now ISO]
python3 desk_clock.py reset-day --date YYYY-MM-DD [--force]
```

`next` is the first call of every fire. It prints phase, mode, paths,
pause/bank-stop flags, and `protectFirst`.

### risk_floors.py

```
python3 risk_floors.py bank-check --portfolio FILE [--apply] [--now ISO]
  # exit 0 ok; exit 9 tripped → flatten and idle
python3 risk_floors.py bank-status
python3 risk_floors.py trade-cap --positions FILE --quotes FILE [--orders FILE]
  # exit 0 ok; exit 8 exit those names now
python3 risk_floors.py bank-flat-done --positions FILE --orders FILE [--now ISO]
  # exit 0 flat; exit 6 not yet
python3 risk_floors.py bank-restart --by "owner words, time ET"
python3 risk_floors.py flow --amount USD --type deposit|withdrawal [--at ISO] [--note TEXT]
```

If `bank-check` says the portfolio file is unreadable, strip wrapper
text around the JSON and re-run. A bad or zero read must not trip.

### reconcile.py

```
python3 reconcile.py sync --state FILE --positions FILE --orders FILE [--apply]
python3 reconcile.py stopargs --json '<place_equity_order kwargs>' [--entry AVG]
  # exit 4 → use returned fixed kwargs; do not send the original
python3 reconcile.py verify-protection --positions FILE --orders FILE --state FILE [--apply]
  # exit 0 protected; exit 7 unprotected or wrong type
python3 reconcile.py reason --state FILE --order-id ID --reason TEXT
python3 reconcile.py annotate --state FILE --buy-order-id ID --json '{...}'
python3 reconcile.py lock|unlock --state FILE --symbol S --routine NAME [--wait 60] [--ttl 120]
python3 reconcile.py fracwatch --state FILE --symbol S --routine NAME ...
python3 reconcile.py statewrite --state FILE --routine NAME --json '{"set":{...}}'
```

`sync` refuses an empty or incomplete orders snapshot. Always pass a
fresh, full `get_equity_orders` dump.

### ta.py

```
python3 ta.py analyze --symbol S --bars 5MIN.json [--bars1 1MIN.json] \
  [--cash USD] [--now ISO] [--config FILE]
```

Prints pass/fail per check, the count vs required (3 of 5), liquidity
floor used, and hard-filter failures (price, RVOL, day-move, spread,
bid-to-stop).

### recovery.py

```
python3 recovery.py score --symbol S --entry E --price BID \
  --bars5 FILE [--bars1 FILE] --spy5 FILE [--sector5 FILE] \
  --catalyst intact|unknown|broken [--now ISO] [--log]
  # exit 10 = EXIT NOW
python3 recovery.py post-exit ...    # label correct|wrong after the session
```

### tp_model.py

```
python3 tp_model.py target --symbol S --fill F --bars FILE [--daily FILE] \
  --catalyst-score 0.0-1.0 [--now ISO] [--out FILE]
python3 tp_model.py trail --fill F --hw H --atr A [--resting R] [--bid B --target T]
```

### discretion.py

```
python3 discretion.py status --state FILE [--quotes FILE] [--now ISO]
python3 discretion.py gate --state FILE --last L [--symbol S] [--day-pct P] [--now ISO]
python3 discretion.py size --state FILE --ask A --buy-limit L [--now ISO]
python3 discretion.py hold --fill F --bid B --vwap V   # historical 11:00 check; all-day session made it moot
```

### desk_learn.py

```
python3 desk_learn.py patterns [--out-dir DIR]
python3 desk_learn.py learn [--apply] [--date YYYY-MM-DD]
python3 desk_learn.py watchlist --date YYYY-MM-DD [--news FILE] [--movers FILE] [--out-dir DIR]
python3 desk_learn.py decision-rate [--date YYYY-MM-DD] [--state FILE] [--baseline] [--paper]
```

Do not `learn --apply` on the guarded profile knobs until at least 6
live trades dated on/after 2026-11-17. See
[Self-learning](../reference/self-learning.md).

### premarket_paper.py / paper_shadow.py / paper_broker.py / paper_guard.py

```
python3 premarket_paper.py init|selftest|tick|summary --date YYYY-MM-DD
python3 paper_shadow.py init --date YYYY-MM-DD [--cash USD]
python3 paper_shadow.py tick --date YYYY-MM-DD --quotes FILE [--bars5 FILE] [--candidates FILE] [--budget-s 20]
python3 paper_shadow.py summary --date YYYY-MM-DD
python3 paper_broker.py ...          # local paper MCP stand-in, same kwargs shape
python3 paper_guard.py mode
python3 paper_guard.py check-call --tool TOOL_NAME
python3 paper_guard.py check-procedures [--dir DIR]
python3 paper_guard.py audit --orders LIVE_ORDERS.json [--since ISO]
```

In paper mode, `paper_guard` must fail any live write tool. The
premarket self-test is the 22-check suite cited in the 09:20 PAPER line.

## Broker call shape

Use the broker MCP (e.g. Robinhood) with `account_number` set from
`BROKER_ACCOUNT_NUMBER`, `market_hours="regular_hours"`, and
`time_in_force="gfd"`. Save raw responses to files. Helpers parse
common wrapper text in some places, but `bank-check` is strict — strip
wrappers yourself if it says unreadable.

Do not ship credentials, cookies, or tokens in this folder, in config,
or in saved fixtures.
