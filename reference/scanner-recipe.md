# Scanner recipe (verified 2026-11-18)

> From `reports/SILAS stock selection and setups.md` (deep research, 2026-11-18). Config: `scannerRecipe2026`. Read-only connector tools only.

## Robinhood can see today's gappers once the expressions are fixed

The 07:00 failure had a mechanical cause. Read-only `preview_scan` tests at about 10:10-10:20 ET on 2026-11-18 showed that **`FILTER_TYPE_GAP` (parsed as `gapRatio(candlePeriod="1d")`) reports the last finished daily candle**. It returned 32 names, and none of them was a real gapper of the day: BRBR, CUE, CLRO and PONY were all missing. `changeFromCloseAllDayRatio(candlePeriod="1d")` keys off the same "latest fully finished" candle. The desk's RVOL, `dayVolume / volumeAvg(30d)`, read only **0.81 for BRBR at 10:15 on a +19% earnings gap**, because the numerator resets each day and the ratio is not normalized for time of day. Before the open it is structurally close to zero. The standard "Volume" column mixes overnight and extended-hours shares with regular-session shares, fractional shares included. That is probably why the 09:20 volume columns looked stale.

These findings come from the desk's own connector tests and have no public URL. The expressions below were accepted and returned sensible values on 2026-11-18.

| Purpose | Expression (verified in preview_scan) | Notes |
|---|---|---|
| Prior close | `close(candleCount=1, candlePeriod="1d", session="regular")` | Returned BRBR 11.02 intraday; unverified premarket |
| Live gap (premarket) | `tradeAllDay.price / PREV_CLOSE - 1` | Not yet run premarket |
| Opening gap | `(dayOpenPrice(session="regular") - PREV_CLOSE) / PREV_CLOSE` | BRBR 19.87%, CUE 19.79%, PONY 9.4% |
| Extended-hours volume | `dayVolume(session="all") - dayVolume(session="regular")` | BRBR 664,709 (includes the overnight session) vs Nasdaq's 330,138 premarket |
| ADV | `volumeAvg(candleCount=20, candlePeriod="1d", session="regular")` | Use 14 to match the paper |
| Spread % | `quote.spread / tradeAllDay.price` | |
| Time-adjusted RVOL | `dayVolume(session="regular") / (ADV20 * F)` | F supplied by SILAS as a constant; linear in-expression clock `((tradeAllDay.time/60000 - 300) % 1440 - 570)/390` works but inflates thin names |
| Last 5-minute bar RVOL | `volume(candleCount=1, candlePeriod="5m", session="regular") / volumeAvg(candleCount=78, candlePeriod="5m", session="regular")` | Approximates, but is not, the paper's 14-day first-5-minute RVOL |
| Distance from VWAP | `tradeAllDay.price / dayVwap(session="regular") - 1` | Intraday only |

The recipe runs in three stages.

**Stage A (07:00, 08:30, 09:15).** Filter for STOCK, last price $2-500, `GAP_LIVE ≥ 0.04`, and extended-hours volume ≥ 50,000 at 07:00 or ≥ 100,000 at 09:15. Run intraday, the 100k version caught every gapper still at least 4% up and at least $2 (51 names). Rank by `EXT_VOL / ADV20`.

**Stage B (09:35, 09:45, then every 15 minutes).** Filter for open gap ≥ 4%, regular-session volume ≥ 250,000, `RVOL_TOD ≥ 2` and spread ≤ 1%. At 10:15 this returned 16 names, including TTWO, TJX, BRBR (RVOL 11.7) and PONY, with shells like CUE (RVOL 144.6) and AKAN mixed in.

**Stage C (vetoes).** The connector's `get_earnings_calendar` confirmed PONY's pre-open earnings, which the watchlist had marked "not confirmed". Free fallbacks also worked live. Nasdaq's premarket quote JSON ([Nasdaq API](https://api.nasdaq.com/api/quote/BRBR/extended-trading?markettype=pre&assetclass=stocks&time=0)) returned BRBR's consolidated premarket last, volume, high and low. SEC EDGAR full-text search found BRBR's same-day 8-K (items 2.02, 5.02, 7.01, 9.01) and AKAN's live F-1 offering. It needs a descriptive User-Agent and allows 10 requests per second ([orthogonal.info guide](https://orthogonal.info/sec-edgar-full-text-search-api-efts-python/)). EDGAR's latest-filings Atom feed streams new 424B5s ([SEC feed](https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=424B5&count=10&output=atom)). Practitioner guidance offers no numeric premarket-volume or float threshold ([Trade Ideas](https://www.trade-ideas.com/2026/04/17/how-traders-use-stock-scanners-for-day-trading-in-a-volatile-premarket/)), so the 50k and 100k levels are calibrations from one day, not evidence.

Several questions remain open before 09:30 tomorrow. Does `PREV_CLOSE` return the prior 4 pm close at 07:00? Does `dayVolume(session="regular")` read 0 premarket, or yesterday's value, which would make extended-hours volume negative? What do `changeFromPostMarketRatio` and `volumePostMarket` show? Does Stage B return any names at 09:35, when 250,000 regular-session shares may be too high a bar five minutes in? And what F matches the real intraday volume curve? The linear 5/390 ≈ 0.013 overstates RVOL early in the session. The paper's actual RVOL needs 14 days of 5-minute history per symbol from `get_equity_historicals`, which is feasible for the top 20 candidates but not for the whole market. Today's IPO-day names fail the 14-day history requirement by construction.


Full scanner notes: `research_notes/SILAS stock selection and setups/scanner_recipe.md`.
