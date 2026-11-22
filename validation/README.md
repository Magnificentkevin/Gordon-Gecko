# Validation lab

Tests a rule change on data before it goes anywhere near the live desk. Built from the QuantBot cleanroom test and the
12-month global stress test (2026-11-22). Research only: nothing here talks to a broker.

## Run

```
cd validation
pip install yfinance pandas scipy
python3 fetch_data.py                    # data/  (Yahoo Finance + public S&P 500 breadth CSV)

# 1. Cleanroom: generate 8,640 strategies on the first 60% of gold hourly bars,
#    then walk-forward, Monte Carlo, random-entry baseline and an untouched 20% holdout
python3 cleanroom_search.py data/GC_F_1h.csv
python3 cleanroom_validate.py data/GC_F_1h.csv

# 2. 12-month global stress test
python3 backdrop.py        # 15 world markets: returns, drawdowns, monthly table, global shock days
python3 regime_test.py     # gecko_regime.py replayed every session vs Russell 2000 open-to-close
python3 features.py        # QuantBot features vs Gordongecko rules on 12 Robinhood-tradable ETFs
python3 stats_mc.py        # Monte Carlo: promotion rule, bank stop, lightning-round sizing
```

Outputs land in `out/`.

## What a rule change must show before going live

1. Run it on data it was not fitted on, with a holdout that no step touched.
2. Beat the random-entry baseline (same pool, same exits, random entry) on that holdout.
3. Show expectancy with t >= 2 (`scripts/paper_random.py edge`), not just "above break-even".
4. Count spread and stop slippage in R. At a 5% stop a 1% spread is 0.2R per round trip.

## Findings this lab produced (2026-11-22)

- The cleanroom gold robot passed backtest, walk-forward (4/4 folds) and Monte Carlo (0.07% chance of loss),
  then lost 4.0% on the holdout and beat only 64% of random-entry runs.
- Closing out every day halved single-market drawdown vs overnight holds; overnight holds lost 52% in Japan (EWJ) on gaps.
- The regime gate sat at DEFENSIVE on 96 of 252 sessions, including the April-May 2026 rally, and allowed buys on
  10 of 14 global sell-off days. Small caps did no worse on DEFENSIVE mornings.
- At a 28% win rate a zero-edge desk passes "100 trades beat break-even" about half the time; full-cash lightning
  sizing hits the -20% bank stop within 40 zero-edge trades about 60% of the time.

Limits: SILAS trades small caps up 8-25% intraday, and 12 months of intraday data for those names wasn't available,
so the tests use the Russell 2000 and liquid ETFs as proxies plus a Monte Carlo at SILAS's stated win rate.
