# Entry setups and timing for long intraday momentum (SILAS entry rules)

Context: today (2026-11-18) both SILAS books logged zero valid entries (`_context_paper_decisions_2026-11-18.jsonl`). Several skips came from the day-move band (v1 25% cap, v2 8-15% band), not from the entry trigger itself. BRBR: open 13.21, OR (09:30-09:35) 12.91-14.01 (range $1.10 = 8.3% of the open), reclaimed VWAP to ~13.79-13.83 by 09:51-09:52, then broke to 12.85 (below the OR low) by 10:05. The prior evaluation (`/home/claude/reports/Gordongecko strategy evaluation.md`) already recommended a $5+/ADV 1M ORB held to the close as the primary paper setup.

Evidence grading used below: **Rigorous** = academic/peer-reviewed or full-paper backtest with stated costs; **Backtest-only** = vendor/author backtest, in-sample, idealized fills; **Practitioner** = blog/forum claims with no audited test.

## Q1. Opening range length: 5 vs 15 vs 30 vs 60 minutes

### Takeaway
The only cross-sectional US-stock test (Zarattini, Barbon & Aziz 2024) finds the edge is concentrated in the **5-minute** range and decays fast with length (Sharpe 2.81 → 1.43 → 0.21 → 0.40 for 5/15/30/60 min), and it exists only on "stocks in play" (opening-range RVOL ≥ 100%). The index-ETF (QQQ) 5-minute ORB reproduces gross but goes to roughly zero net of spread and slippage in an independent replication.

### Cited Findings
- **Stocks-in-play ORB (Zarattini, Barbon & Aziz, 2024; Backtest-only, full paper).** Universe: all NYSE/Nasdaq stocks 2016-2023 (~7,000, delisted names included), opening price > $5, 14-day average volume ≥ 1,000,000 shares, 14-day ATR > $0.50; RVOL = first-5-minute volume ÷ average first-5-minute volume of the prior 14 days; trade top 20 by RVOL with RVOL ≥ 100% — [Paper PDF (Univ. St. Gallen)](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Rules: **direction set by the first 5-minute candle** (bullish candle → only longs; bearish → only shorts; doji → no trade); entry by **stop order at the OR high** (i.e., on touch, not on a bar close); stop = **10% of 14-day ATR** from entry; exit at 16:00 if not stopped; 1% risk per position, max 4x leverage; commission $0.0035/share — [Paper PDF](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Results by OR length (all with RVOL ≥ 100%): 5m IRR 41.6%, Sharpe 2.81, hit ratio 48.4%, MDD 12%; 15m IRR 17.4%, Sharpe 1.43, hit 44.7%; 30m IRR 2.3%, Sharpe 0.21, hit 42.4%, MDD 35%; 60m IRR 4.1%, Sharpe 0.40, hit 42.3%; equal-weight combo Sharpe 1.99 — [Paper PDF, Table 3](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Without the RVOL filter the 5m ORB is near flat: IRR 3.2%, Sharpe 0.48, hit 41.4%. Average net P&L per trade by RVOL bucket: RVOL < 100% → −0.02R; > 100% → +0.08R; > 30x → +0.38R — [Paper PDF, Table 1 / Fig. 4](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- The paper does not report payoff ratio, long-vs-short split, alternative stock counts to top-20, or false-breakout rates — [Paper PDF](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- No slippage modelled; a QuantConnect replication found 17 of 25 parameter sets beat the benchmark Sharpe — [QuantConnect](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/) (as cited in the prior evaluation)
- **QQQ 5-minute ORB (Zarattini & Aziz 2023; Backtest-only).** Trade in direction of first 5-min candle at the start of the second bar, stop at the other side of the first candle, 10R target or exit at close, 1% risk, 4x leverage; 33.2% CAGR vs 14.9% buy-and-hold QQQ, Jan 2016-Feb 2023, 1,795 trades; no spread or slippage modelled — [CXO Advisory](https://www.cxoadvisory.com/technical-trading/day-trading-with-an-opening-range-breakout-strategy); [SSRN](https://papers.ssrn.com/abstract=4416622)
- **Independent replication (Practitioner but transparent):** on NQ/SPX/Dow/DAX/FTSE CFDs 2015-June 2026, gross +0.05 to +0.13R per trade with ~20-23% hit rate (NQ +0.131R, 23.2%, matching the paper's ~24%); **net of spread/slippage, +0.002R on NQ and negative on the other four**; negative in every market 2015-2017; out-of-sample 2021-2026 at most +0.06R on NQ. The first candle's direction beat a random-direction benchmark by ~0.10-0.13R, about the size of round-trip cost — [MQL5 blog replication](https://www.mql5.com/en/blogs/post/776235)
- **Crabel (1990) via Oxford Capital Strategies (Backtest-only, futures):** Crabel's ORB enters on a "stretch" from the open (Stretch = 2 × 10-day average of min(High−Open, Open−Low)). Over 42 futures markets 1980-2019 with costs, breakouts after **narrow-range** days were marginally profitable (profit factor 1.02-1.09, ~30% winners, avg win/avg loss ~2.3-2.5) while breakouts after **wide-range** days lost money (profit factor 0.72-0.74, Sharpe −1.2 to −1.45) — [Oxford Strat, Wide Range pattern](https://oxfordstrat.com/trading-strategies/wide-range-pattern/)

### Inferences
- A 5-minute OR is the evidence-backed choice; going to 15 minutes roughly halves the return and 30-60 minutes removes it. If SILAS wants a second, slower setup, a 15m ORB is the only longer variant with meaningful support.
- The first-candle direction filter is part of the tested rule. SILAS v2 does not use it. BRBR's first 5-minute bar closed below its 13.21 open (the 09:36 log shows 13.13 below VWAP after a spike to 14.01), so under the paper's rule BRBR would have been a **short-only** name that day and no long would have been taken. That matches what happened (break to 12.85).
- The edge is thin (+0.08R average net per trade for RVOL > 100%, before slippage). Spread and slippage on small/mid caps can consume most of it, so RVOL rank and a spread cap matter more than trigger cleverness.
- Crabel-type evidence (futures, daily) suggests ORBs after already-wide ranges perform worse; this is suggestive only for single-stock intraday use.

### Gaps
- No rigorous study found that reports long-only ORB results on US stocks, payoff ratios, or false-breakout frequency by OR length.
- No study found that tests the 1-minute or 2-minute OR on stocks.
- Crabel's original book statistics were not directly accessible; only secondary backtests were found.

## Q2. VWAP-based entries (reclaim, first pullback, VWAP trend)

### Takeaway
VWAP has rigorous-ish support only as a **trend/trailing-stop reference on index ETFs** (QQQ, SPY), not as a stock entry trigger. No quantitative study found tests "VWAP reclaim" or "first pullback to VWAP" on individual momentum stocks.

### Cited Findings
- **Concretum VWAP trend (Backtest-only):** long when QQQ is above VWAP, short below; Jan 2018-Sep 2023, $25k start; QQQ version 671% total return, MDD 9.4%, Sharpe 2.1 vs buy-and-hold 126%, MDD 37%, Sharpe 0.7; claimed "net of commissions" but cost assumptions, bar frequency, trade count and hit rate not given on the summary page — [Concretum Group](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/)
- **"Beat the Market" SPY noise-area study (Zarattini, Aziz & Barbon 2024):** adding VWAP to the trailing stop (long stop = max(upper noise boundary, VWAP)) raised the Sharpe from 0.61 (opposite-boundary stop) to 1.24 — [Paper PDF](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content)
- Prior evaluation: VWAP has backtest support only on QQQ/TQQQ; TA filter results generally suffer from data snooping ([Park & Irwin 2007](https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html)) — [Gordongecko strategy evaluation, local file]

### Inferences
- Treat "price ≥ VWAP" as a **filter and a stop/trail reference**, not as an entry trigger. It is consistent with the tested studies (both ORB and noise-area trades are typically on the VWAP side of the move).
- A VWAP reclaim inside a wide, failing opening range (BRBR 09:51: above VWAP but below the 14.01 OR high and after an 8% OR) is untested by any study found; the BRBR outcome (−6.6% counterfactual by 10:05) is one anecdote consistent with not trading it.

### Gaps
- No quantitative evidence found on VWAP-reclaim or first-pullback-to-VWAP entries for single stocks.
- The Concretum VWAP paper's full cost and trade statistics were not verified (summary page only).

## Q3. Time-of-day effects: which windows have edge for entries?

### Takeaway
Evidence points two ways: (1) for stocks in play, the edge is in the **first 5 minutes' breakout** (the 5m ORB beats longer ranges); (2) for attention/retail-heavy stocks, opening gains tend to **reverse during roughly the first hour**. Index momentum studies avoid the first 30 minutes and find trend-continuation expectancy rising from 10:00 to noon and from 14:00 to the close. Late-morning/midday (after ~10:30) has the weakest expected edge for new momentum entries.

### Cited Findings
- **Gao, Han & Zhou (JFE 2018, "Market intraday momentum"):** SPY 1999-2012, the first half-hour return (9:30-10:00) predicts the last half-hour return; in-sample R² ≈ 0.02 (0.035 combined with the 12th half-hour), out-of-sample up to 0.018; timing the last half-hour gave 6.3% annualized gross vs −0.5% always-in; stronger with high first-half-hour volatility (R² 0.048), in recessions and on some news days; frictions ignored — [CXO Advisory summary](https://cxoadvisory.com/calendar-effects/first-and-last-half-hours-of-trading-linked); [EconPapers (JFE 129(2):394-414)](https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414)
- **"Beat the Market" (Zarattini, Aziz & Barbon 2024):** noise area = 14-day average absolute move from the open at each time of day; enter when SPY leaves the band, only checked at HH:00/HH:30, **first position at 10:00** (9:30-10:00 not traded); trailing stop max(band, VWAP); 2007-early 2024 IRR 19.6%, Sharpe 1.33, MDD 25%, trade hit ratio 37% over 7,668 trades; costs $0.0035/share + $0.001 slippage. Trend-continuation expectancy rises steadily 10:00-noon, pauses at lunch, resumes strongly 14:00-close — [Paper PDF](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content)
- **Berkman, Koch, Tuttle & Zhang (2010):** 3,000 largest US stocks 1996-2008; overnight return ~+0.1% reversed ~−0.07% intraday; in high-retail-attention, low-institutional-ownership stocks, overnight +0.2-0.3% reversed −0.2 to −0.4%; mispricing "statistically strong during about the first hour"; effect weaker after 2001/2005 — [CXO Advisory](https://www.cxoadvisory.com/calendar-effects/the-lure-of-trading-at-the-open/)
- **Barber, Huang, Odean & Schwarz:** in Robinhood herding stocks the mean opening return is ~11%, followed by losses of ~−3.5% over 5 days and nearly −5% over 20, concentrated in stocks under $1B market cap — [SSRN PDF](https://www.smallake.kr/wp-content/uploads/2020/12/SSRN-id3715077.pdf) (as cited in the prior evaluation)
- **Heston, Korajczyk & Sadka (JF 2010):** NYSE 2001-2005, a stock's return in a given half-hour continues at the same half-hour on later days (3.01 bp per half-hour decile spread); the effect is strongest in the opening half-hour (>11 bp) and near the close (>8 bp), ~1.75 bp midday; strategies lose money after the bid-ask spread; volatility is generally high at the start and end of the day — [arXiv version](https://ar5iv.arxiv.org/html/1005.3535)
- **End-of-day reversal (Soebhag, Baltussen & Da, 2024):** stocks that fell earlier in the day tend to rebound in the last half-hour; ~8.8% annualized gross long-short (stocks > $5), 1993-2019 — [CXO Advisory](https://www.cxoadvisory.com/?p=46335)

### Inferences
- For a gapper universe, two windows are defensible: **09:35-~10:00** for a 5m ORB on top-RVOL stocks (the ZBA design, entry by stop order as soon as the OR high trades), and **no new momentum entries after ~10:30-11:00** except a separately tested afternoon trend setup. The current v1 "A+ entries until 13:30" window has no supporting study.
- The first-hour reversal literature implies the failure mode seen today (spike, fade, VWAP reclaim, fail) is the base case for attention names, especially sub-$1B caps. The RVOL ranking and first-candle direction rule are the tested way to separate in-play continuation from retail-fade names.
- The index findings (Gao et al.; noise area) do not transfer directly to single small-cap stocks; use them only for timing intuition (avoid the first 30 minutes for slow trend entries; afternoon continuation is real on SPY).

### Gaps
- No study found that measures first-30-minute reversal rates specifically for earnings-gap stocks in 2020-2026.
- No rigorous study found that maps time-of-day entry profitability for ORB entries on stocks (e.g., breakouts at 09:36 vs 10:15).

## Q4. Confirmation (close vs touch), retest entries, stop placement, wide ORs

### Takeaway
The tested stock ORB uses a **stop order on touch** of the OR high with a **tight ATR-fraction stop (10% of 14-day ATR)**, not a 5-minute close and not the OR low. No rigorous study was found comparing close-confirmation or retest entries with touch entries. Wide ORs have only indirect evidence against them (Crabel wide-range results; tight ATR stops make wide OR-low stops incompatible with the tested risk geometry).

### Cited Findings
- ZBA stock ORB: entry by stop order at the OR high; stop 10% of 14-day ATR; hold to 16:00 — [Paper PDF](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- QQQ ORB uses the **OR low** (other side of the first candle) as the stop with a 10R target; its TQQQ variant used 5% of 14-day ATR as the stop with no target — [CXO Advisory](https://www.cxoadvisory.com/technical-trading/day-trading-with-an-opening-range-breakout-strategy)
- Crabel/Oxford: breakouts after wide-range bars underperform those after narrow-range bars (PF 0.72-0.74 vs 1.02-1.09) — [Oxford Strat](https://oxfordstrat.com/trading-strategies/wide-range-pattern/)
- Stops add value only with positive serial correlation (Kaminski & Lo); tight stops on stocks underperform largely due to costs — [MIT preprint](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf) (via prior evaluation)
- Search for retest/close-confirmation backtests returned only practitioner blogs, TradingView scripts and vendor pages (e.g., [LuxAlgo](https://www.luxalgo.com/blog/opening-range-breakout-orb-trading-strategy-how-it-works/), [TradingView ORB retest script](https://www.tradingview.com/script/muLbjEdA-Casper-SMC-5m-ORB-Retest/)) with no audited out-of-sample statistics — Practitioner only

### Inferences
- SILAS v2's "5-minute **close** above OR high" deviates from the tested rule. It enters later and higher, which widens risk relative to a 10%-ATR stop and may skip fast breakouts. Recommend testing **touch (stop-limit at OR high + small buffer)** as the primary and close-confirmation as a shadow variant.
- **OR-width filter (inference, not tested):** the 10%-ATR stop assumes the OR is small relative to daily ATR. Propose skipping when OR range > ~0.5 × 14-day ATR (or > ~4% of price, matching the desk's 4.5-5% stop cap). BRBR's OR was $1.10 (8.3% of open); this would be skipped on any reasonable ATR. The threshold should be fitted on paper data, not adopted.
- Stop placement: 10% of ATR is the tested default. OR low is the tested QQQ default. On a $120 account the choice is mostly moot because cash, not risk, caps size (see Q5).

### Gaps
- No rigorous evidence found on close-vs-touch confirmation, retest entries, or false-breakout rates for stock ORBs.
- No study found that tests an explicit OR-width / ATR skip filter on single stocks.

## Q5. Minimal, testable rule set for a $120 account (whole shares, 1% risk ≈ $1.20)

### Takeaway
Implement the tested 5m stocks-in-play ORB as closely as possible, long-only, with cash as the binding constraint, and measure over 100+ trades before adding filters.

### Cited Findings
- Tested parameters to copy: price > $5, ADV ≥ 1M, ATR(14) > $0.50, OR RVOL ≥ 100%, top-20 by RVOL, first-candle direction, stop-order entry at OR high, stop 10% ATR, hold to close, 1% risk — [Paper PDF](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Expect a ~45-48% hit rate and thin average R; net edge may be near zero once spread/slippage are charged (index analogue) — [Paper PDF](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content); [MQL5 replication](https://www.mql5.com/en/blogs/post/776235)

### Inferences (proposed rule set; parameters are starting points to test, not proven)
1. **Universe (09:35):** price ≥ $5, ADV ≥ 1M, ATR(14) ≥ $0.50, spread ≤ 0.5%; rank by 5-minute OR RVOL (≥ 1.0, prefer ≥ 2-3); take the top few. Drop the day-move band (8-15% / 25% cap) as a gate: the paper ranks by RVOL, not day move (today's log note says the same).
2. **Direction:** first 5-minute candle must close above its open (bullish); otherwise no long.
3. **Width filter (untested, proposed):** skip if OR range > 0.5 × ATR(14) or > 4% of price.
4. **Trigger:** buy-stop (stop-limit, limit = trigger + ~0.1-0.2%) at OR high + $0.01, valid 09:35-10:30; price ≥ VWAP at trigger. Shadow-log the 5-minute-close variant.
5. **Stop:** entry − max(10% × ATR(14), $0.02), placed at a non-round price; also accept OR-low stop as a shadow variant.
6. **Size:** qty = min(floor(1.20 ÷ risk/share), floor(available cash ÷ price)); skip if qty < 1. Arithmetic: at $5-25/share the cash cap (4-24 shares) usually binds first, so realized risk will often be below 1%.
7. **Exit:** hold to 15:50 flatten; optional trail = max(stop, VWAP) checked on 30-minute marks (the SPY study's tested form). No minute-scale stall exit.
8. **One trade per name per day; at most 1-2 concurrent positions** given cash.
9. **Measure:** win rate, avg win/loss in R, net cost per trade, stop slippage, n ≥ 100 before promoting.

- Applied to today: BRBR fails rule 2 (bearish first candle, likely) and rule 3 (8.3% OR), so the correct output was "no trade"; today's zero entries are consistent with the tested rules, not evidence that they are too strict.

### Gaps
- No study tests ORB economics at $120 account size, whole-share rounding, or Robinhood fill quality on stop-limit orders at the open.
- Whether the BRBR first 5-minute candle actually closed below its open needs checking against 1-minute bars (inferred from the 09:36 log only).
