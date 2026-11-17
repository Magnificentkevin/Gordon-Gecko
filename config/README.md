# Example config

`example-config.json` is a sanitized, operational snapshot of the live
desk config at the `higher-risk+15` profile (applied 2026-11-17).

Before use:

1. Copy it to `${DESK_CONFIG}`.
2. Set `accountNumber` from `BROKER_ACCOUNT_NUMBER` (or leave the
   `${BROKER_ACCOUNT_NUMBER}` placeholder and resolve it at runtime).
   Never commit the real id.
3. Replace illustrative money fields. `bankUsd` (100.00) and
   `bankStop.baselineUsd` (100.00) are examples. Set the baseline to
   the live account's equity at the measurement start; record later
   owner deposits and withdrawals with `risk_floors.py flow`. The stop
   line is 50% of that baseline (example: $100 → $50).
4. Point path-like strings (`${DESK_ROOT}`, `${HELPERS_DIR}`,
   `${DESK_DATA}`, `${KB_DIR}`) at this installation.
5. Set `liveMode.armed` and `desk.paused` to the owner's last
   instruction. Leave `executionMode` `paper` until the owner has armed
   live cash and the premarket self-test is green.
6. Confirm the profile block still says `higher-risk+15` and that
   `stopLossPct` is −3.45, recovery thresholds are 26 / 38, the A+
   cutoff is 13:30, the round-trip cap is 9, and stall is 14 minutes.

The file omits revision-history blobs, live cash-flow amounts, and
account identifiers. It is enough to rebuild the desk, not a dump of
the production state file.
