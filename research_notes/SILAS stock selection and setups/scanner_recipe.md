# Premarket and Opening Scanner Recipe for SILAS (Robinhood Trading MCP), tested Nov 18, 2026

All Robinhood work below used READ-ONLY tools only: get_scanner_datapoints, get_scanner_filter_specs, preview_scan (4 previews total) and get_earnings_calendar. No scan was created or saved, and no order tool was called. The previews ran at about 10:10–10:20 ET on Wed Nov 18, 2026 (my in-expression clock read 40.6 minutes after the open). External endpoints were tested live with curl at the same time.

Source keys used below:
- [RH-DP] = Robinhood MCP `get_scanner_datapoints` (categories price_volume, price, descriptive), called 2026-11-18
- [RH-FS] = Robinhood MCP `get_scanner_filter_specs`, called 2026-11-18
- [RH-P1]…[RH-P4] = the four `preview_scan` runs described in section 1
- [RH-EC] = Robinhood MCP `get_earnings_calendar(start_date=2026-11-18, days=1)`
- Context files: `_context_watchlist_2026-11-18.json` and `_context_paper_decisions_2026-11-18.jsonl` (same folder)

---

## 1. Which Robinhood scanner expressions work, and what each preview_scan returned

### Takeaway
The connector has everything needed for a reliable gap scan, but not under the names the desk used. The standard "% Change" column is `changeFromPrevDayRatio(session="all")`. That is an extended-hours price against the prior close, so it is valid premarket. The enum **Gap filter is unusable intraday**: it reports the previous finished daily candle's gap, so today's real gappers (BRBR, CUE and others) are missing from it. Today's true opening gap, premarket volume (as "all-session minus regular-session" volume), spread %, float, market cap and a time-of-day-adjusted RVOL can all be built as expressions. Each was checked in preview_scan.

### Cited findings: datapoint catalog
- Relevant price fields: `changeFromPrevDayRatio(session)` ("difference ratio between the latest available price and close price of the previous trading day"); `changeFromCloseAllDayRatio(candlePeriod)` (vs "close price of the latest fully finished candle … in the all day (overnight) session"); `changeFromPostMarketRatio`; `dayOpenPrice(session)`; `dayVwap(session)`; `close(candleCount, candlePeriod, session)`; `tradeAllDay.price` and `tradeAllDay.time` (last trade in the all-day/overnight session); `markPrice(session)`. All ratios are decimals (0.05 = 5%) — [RH-DP]
- Volume fields: `dayVolume` ("resets to 0 when a new trading day starts"), `dayVolume(session)`, `volume(...)`, `volumeAvg(candleCount|timePeriod, candlePeriod, session)`, `volumeAvg10Day`, `volumeAvg10Minutes`, `volumePostMarket`. There is **no dedicated premarket-volume, premarket-change or RVOL-by-time-of-day datapoint**: "Relative-volume screens are built by dividing dayVolume by a volumeAvg call" — [RH-DP]
- Session values are only `"all"` (extended plus overnight) and `"regular"`. There is no `"pre"` session. CandlePeriod values: 1m, 2m, 3m, 4m, 5m, 10m, 15m, 30m, 1h, 2h, 4h, 1d, 1w, 1mo, 1y. TimePeriod values: 1d, 1w, 1mo, 1y only — [RH-DP]
- Descriptive fields: `symbol` (scope with ANY_OF tickers or IN_LIST index codes such as SP500 and Russell2000), `tradingStatus`, `haltStartTime`, `haltEndTime`, `nowYMD`, `daysFromNow()` — [RH-DP]
- Quote category: `quote.spread`, `quote.bidPrice`, `quote.askPrice` and sizes. `quote.spread / tradeAllDay.price` worked as a spread-% expression — [RH-DP], [RH-P2]
- Enum filters relevant to gappers: FILTER_TYPE_PERCENT_CHANGE_FROM_CLOSE, FILTER_TYPE_GAP, FILTER_TYPE_RELATIVE_VOLUME (lengths 1–90; intervals 1m, 1h, 1d, 1w, 1mo), FILTER_TYPE_VOLUME, FILTER_TYPE_SHARES_FLOAT, FILTER_TYPE_SHARES_OUTSTANDING, FILTER_TYPE_MARKET_CAP, FILTER_TYPE_LAST, FILTER_TYPE_EARNINGS_DATE, FILTER_TYPE_INSTRUMENT_TYPE (STOCK/ETF). PERCENTAGE filters take decimals. The specs say that omitting `interval` on a filter that supports one is "the leading cause of an otherwise-valid filter returning no results" — [RH-FS]
- Standard columns "Float" and "Market cap" can be requested by display name alone. They returned values for most names, with blanks for some ADRs, SPACs and new listings (KLAR, ACM, JD, ENR, TCX, BLSH) — [RH-P2], [RH-P3], [RH-P4]

### Cited findings: preview results

**[RH-P1] Symbol-scoped check** (filter `symbol ANY_OF [BRBR, PONY, CUE, CALM, GMM, AKAN, CLRO, NCPL]`). It returned 8 of 8 with test columns:
- The standard "% Change" equals `changeFromPrevDayRatio(session="all")` exactly for every name (for example BRBR 0.189373 for both). It also equals `changeFromCloseAllDayRatio(candlePeriod="1d")` *at 10:15*. So intraday "% Change" uses the latest all-session price.
- `openGapReg = (dayOpenPrice(session="regular") - close(candleCount=1, candlePeriod="1d", session="regular")) / close(...)` returned the true opening gaps: BRBR 19.87%, CUE 19.79%, GMM 22.9%, AKAN 17.1%, CLRO 16.5%, NCPL 15.8%, PONY 9.4%, CALM −0.18%. The prior close from `close(candleCount=1, candlePeriod="1d", session="regular")` was BRBR 11.02 and PONY 3.99 (the watchlist had 11.01 and 3.99).
- `dayVolume` (the standard "Volume") equals `dayVolume(session="all")`. It contains fractional shares (for example CALM 332,556.63), and it is larger than `dayVolume(session="regular")` (CALM 255,357). So the "Volume" column mixes extended-hours and overnight volume with regular-session volume. That probably explains the "mixed/stale volume columns" seen at 09:20.
- `dayVolume / volumeAvg(candleCount=30, candlePeriod="1d", session="all")`, the desk's RVOL, was only 0.81 for BRBR at 10:15 on a +19% earnings gap. It is not time-normalized, so it is structurally near 0 premarket and small early in the session.

**[RH-P2] "Up ≥5% with real volume"** (STOCK; `changeFromPrevDayRatio(session="all") ≥ 0.05`; Last ≥ 2; `dayVolume(session="regular") ≥ 300000`). It returned **45 names**, including PANW, TGT, TJX, MP, CELH, BRBR, CLRO, CUE, AKAN, MPU, NCPL and USAR.
- An in-expression clock worked: `(tradeAllDay.time / 60000 - 300) % 1440 - 570` returned about 40.7 minutes since the open on liquid names. So the `%` modulo operator and arithmetic on `tradeAllDay.time` (epoch ms) are supported. It returned 40.2 on the thin name ABEO because that name's last trade was older.
- A 5-minute-bar RVOL, `volume(candleCount=1, candlePeriod="5m", session="regular") / volumeAvg(candleCount=78, candlePeriod="5m", session="regular")`, evaluated without error (SG 8.7, CLRO 26.6, USAR 7.5).

**[RH-P3] Enum Gap filter** (STOCK; `FILTER_TYPE_GAP interval=1d ≥ 0.04`; Last ≥ 2; Market cap ≥ $100M). It returned **32 names, and none were today's real gappers.** BRBR (19.9% open gap), CUE, CLRO and PONY were absent. Rows had "Gap" values such as SLS 1.478, RCAT 0.277 and LUCK 0.191 next to opening gaps of about 0–2% today. The parsed expression was `gapRatio(candlePeriod="1d", session="regular")`, which evidently measures the last *finished* daily candle (yesterday or earlier). **Do not use FILTER_TYPE_GAP for same-day gaps.** This is the same "1d fields reflect the prior session" failure seen at 07:00.
- In the same preview, the linear time-adjusted RVOL `dayVolume(session="regular") / (volumeAvg(candleCount=20, candlePeriod="1d", session="regular") * minsSinceOpen/390)` gave sensible values on liquid names. It blew up on thin ones (AKO.A 20.4× on 3,160 shares; PNRG 18.4× on 36k). It needs an absolute-volume floor.
- `(dayVolume(session="all") - dayVolume(session="regular")) / volumeAvg(20d, regular)` evaluated (extended-hours volume as a share of average daily volume).
- `tradingStatus` returned "Regular".
- A rolling 15-minute RVOL, `volumeAvg(candleCount=15, candlePeriod="1m", session="regular") / volumeAvg(candleCount=1950, candlePeriod="1m", session="regular")`, evaluated.

**[RH-P4a] Premarket-style recipe run intraday** (STOCK; Last 2–500; `tradeAllDay.price / close(candleCount=1, candlePeriod="1d", session="regular") - 1 ≥ 0.04`; `dayVolume(session="all") - dayVolume(session="regular") ≥ 100000`). It returned **51 names**, and it **caught every morning gapper that is still ≥4% and ≥$2**. Extended-hours volume by name: BRBR 664,709; CUE 2.25M; CLRO 1.82M; AKAN 8.47M; NCPL 2.31M; MPU 403k; TGL 1.15M; OMH 3.04M; WYHG 247k (spread 8%); TJX 1.35M; TGT 1.14M; TTWO 1.43M. PONY was absent because it had faded to +1.75%. GMM was absent because it was under $2. `volumeAvg(candleCount=60, candlePeriod="1m", session="all") * 60` (volume in the last 60 one-minute bars) also evaluated.

**[RH-P4b] Opening "stocks in play" recipe** (STOCK; Last 2–500; open gap ≥ 0.04; `dayVolume(session="regular") ≥ 250000`; time-adjusted RVOL ≥ 2; `quote.spread / tradeAllDay.price ≤ 0.01`). It returned **16 names**: TTWO (gap 4.2%, RVOL 10.9), BE (4.0%, 2.1), TJX (5.5%, 12.0), TXT (4.8%, 4.2), BLSH (10.1%, 7.4), BRBR (19.9%, 11.7), CLRO (16.5%, 8.7), SVRA (4.0%, 4.4), ANGX (6.3%, 4.4), PONY (9.4%, 8.1), CUE (19.8%, 144.6), BORR (7.4%, 5.0), PSIG (5.4%, 2.9), NUAI (4.7%, 2.1), AKAN (17.1%, 22.1) and MPU (25.2%, 27.5). It includes the vetoed shells and dilution names, so the catalyst and dilution vetoes from section 4 still have to run on top.

**[RH-EC] Earnings calendar for 2026-11-18.** It listed BRBR, PONY, TJX, TGT, BLSH, ZIM, GLBE, LOW, JJSF and others as `timing: "am"`, `verified: true`, with actual EPS. **PONY's catalyst ("not confirmed" in the watchlist) was its Q3 report before the open**, which this one call would have confirmed.

### Inferences
- **Why 07:00 failed:** `changeFromCloseAllDayRatio(candlePeriod="1d")` and FILTER_TYPE_GAP both key off the "latest fully finished" daily candle. Premarket, that candle is the prior session (or the all-day overnight candle), not today's. Use `tradeAllDay.price / close(candleCount=1, candlePeriod="1d", session="regular") - 1` for the premarket gap. During the session this read yesterday's 4 pm close (BRBR 11.02), so it should also be correct premarket, when yesterday's regular candle is the latest finished one. It still needs to be confirmed premarket (see Gaps).
- **Why RVOL returned 0 before the open:** both `dayVolume` and the enum RELATIVE_VOLUME compare a just-reset day counter with a full-day average. Premarket, use extended-hours volume against average daily volume (`extVol / ADV`), or simply absolute extended-hours volume. After the open, use time-adjusted RVOL.
- **Premarket volume figures from Robinhood and Nasdaq are not on the same basis.** For BRBR, Robinhood's `dayVolume(all) - dayVolume(regular)` was 664,709, while Nasdaq reported 330,138 "Pre-Market Share Volume" for 04:00–09:30 (section 3). Robinhood's "all" session evidently includes the 20:00–04:00 overnight session and fractional shares. Thresholds must be calibrated to whichever source is used.
- **Time-normalization:** the in-expression clock depends on each symbol's own last-trade time and on a hard-coded UTC offset (300 for EST; it must be 240 after the DST switch on Mar 8, 2027). Stale last trades inflate RVOL. The safer approach is to have SILAS compute the elapsed fraction of normal day volume on its own clock and write it into the expression as a constant at run time (for example `… / (volumeAvg(candleCount=20, candlePeriod="1d", session="regular") * 0.12)`).

### Gaps
- I could not test premarket behavior, because the market was open during this session. Unverified until a premarket run: (a) that `close(candleCount=1, candlePeriod="1d", session="regular")` returns the prior 4 pm close at 07:00; (b) whether `dayVolume(session="regular")` reads 0 (correct) or yesterday's value (which would make extended-hours volume negative) before 09:30; (c) what `changeFromPostMarketRatio` and `volumePostMarket` show at 07:00.
- The catalog says the price category has 64 datapoints and mentions `gap*` functions, but the listing showed only part of them. `gapRatio(candlePeriod, session)` was observed only through the enum echo. A premarket-specific gap function may exist that I did not see.
- The connector's float source and update date are not documented. Some names return a blank float.

---

## 2. The scan recipe (exact filters, columns and run times)

### Takeaway
Run three stages: a premarket gap list (from 07:00, refreshed at 08:30 and 09:15), an opening "in play" confirmation (09:35–09:45), and catalyst and dilution vetoes on every candidate. Every expression below was accepted by preview_scan. The open recipe returned 16 names today, including BRBR and PONY.

### The recipe (expressions as passed to preview_scan / create_scan)

Definitions, all tested:
- `PREV_CLOSE = close(candleCount=1, candlePeriod="1d", session="regular")`
- `GAP_LIVE = tradeAllDay.price / close(candleCount=1, candlePeriod="1d", session="regular") - 1`
- `OPEN_GAP = (dayOpenPrice(session="regular") - PREV_CLOSE) / PREV_CLOSE`
- `EXT_VOL = dayVolume(session="all") - dayVolume(session="regular")`
- `ADV20 = volumeAvg(candleCount=20, candlePeriod="1d", session="regular")`
- `SPREAD_PCT = quote.spread / tradeAllDay.price`
- `RVOL_TOD = dayVolume(session="regular") / (ADV20 * F)`. Here F is the expected fraction of daily volume done by now, supplied by SILAS as a constant. The tested fallback was the linear in-expression version `(((tradeAllDay.time / 60000 - 300) % 1440 - 570) / 390)`.
- `VS_VWAP = tradeAllDay.price / dayVwap(session="regular") - 1`, used intraday.

**Stage A: premarket gap list (07:00, 08:30, 09:15 ET)**
- Filters: `FILTER_TYPE_INSTRUMENT_TYPE = STOCK`; `FILTER_TYPE_LAST BETWEEN [2, 500]`; `GAP_LIVE ≥ 0.04`; `EXT_VOL ≥ 50000` at 07:00 and `≥ 100000` at 09:15. Today the 100k level caught every real gapper ([RH-P4a]).
- Columns: Float, Market cap, `EXT_VOL / ADV20`, SPREAD_PCT, `changeFromPrevDayRatio(session="all")` (as a cross-check), and `tradeAllDay.time` (to reject quotes older than about 15 minutes).
- Do **not** use the "% Change" enum with interval 1d, FILTER_TYPE_GAP, RELATIVE_VOLUME, or `dayVolume / volumeAvg(...)` in this stage.
- Fallback guard: if `dayVolume(session="regular")` is not 0 premarket (to be verified), replace EXT_VOL with `volumeAvg(candleCount=N, candlePeriod="1m", session="all") * N`, where N is the number of minutes since 04:00. Thin names lack bars for some minutes, so this will reach back into the overnight session.
- Rank by `EXT_VOL / ADV20`, then GAP_LIVE. Pull catalysts (section 4) for the top 10–15.

**Stage B: opening confirmation (09:35, 09:45, then every 15 minutes)**
- Filters (exactly as in [RH-P4b]): STOCK; Last 2–500; `OPEN_GAP ≥ 0.04`; `dayVolume(session="regular") ≥ 250000`; `RVOL_TOD ≥ 2`; `SPREAD_PCT ≤ 0.01`.
- Columns: GAP_LIVE, VS_VWAP, EXT_VOL, Float, Market cap.
- Suggested ranking, following the ORB study (section 3): sort by RVOL_TOD and keep the top 20.

**Stage C: vetoes** (section 4): earnings or 8-K catalyst present; no S-3, 424B5, F-1 or ATM filing in the last 90 days, or treat it as a dilution flag; market cap ≥ $50M as a pump guard (CLRO $12M, AKAN $5M, MPU $19M, CUE $24M were all micro-cap).

### Inferences
- Today the open recipe with the vetoes applied leaves roughly TTWO, TJX, BE, TXT, BLSH, BRBR, PONY, SVRA, ANGX, BORR and NUAI. That universe is broader than the 4–25% "day move" band. A 4% open-gap floor with ranking by RVOL matches the "rank by RVOL" note from the 09:51 decision log.
- A self-test each morning: run a symbol-scoped preview on 3 known names and check that GAP_LIVE matches the Nasdaq premarket % (section 3) within about 0.5 percentage points before trusting the scan.

### Gaps
- The intraday volume curve (the F constants) has no sourced values here. Calibrate F from SILAS's own 5-minute history (`get_equity_historicals`) instead of using a linear clock. The linear version overstates RVOL in the first hour, because the open carries a disproportionate share of daily volume. That last point is my inference and was not sourced.

---

## 3. Best practice from practitioner and academic sources

### Takeaway
The best-documented academic-style "stocks in play" filter is Zarattini, Barbon and Aziz's ORB study: price > $5, 14-day ADV ≥ 1M, ATR > $0.50, opening-range relative volume ≥ 100%, then the top 20 by relative volume. Practitioner sources stress real-time data, a several-percent gap, solid premarket volume and a catalyst, but give no consistent numeric thresholds.

### Cited findings
- The stocks-in-play screen, applied daily to all US-listed stocks: opening price above $5; average daily volume of at least 1,000,000 shares over 14 days; 14-day ATR above $0.50; relative volume in the opening-range interval of at least 100% versus the last 14 days; and a top-20 rank by relative volume — [CXO Advisory summary of Zarattini/Barbon/Aziz](https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/)
- Opening range = the first 5 minutes; stop at 10% of ATR; positions exit at the close; 1% risk per trade with 4× leverage cap; sample Jan 2016–Dec 2023; reported 41.6% annualized and Sharpe 2.81 net of $0.0035/share commissions (other metrics paywalled) — [CXO Advisory](https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/); paper listing: [SSRN/RePEc rp2498](https://ideas.repec.org/p/chf/rpseri/rp2498.html), [Concretum Group](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/)
- An independent replication discussion exists on QuantConnect — [QuantConnect research](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/). I did not review its results.
- Practitioner guidance (Trade Ideas, Apr 2026): no exact gap threshold, only "usually several percent"; no numeric minimum for premarket volume ("solid premarket volume"); 07:00–09:30 is "the most important window"; a watchlist of 3–8 names; warnings that thin premarket liquidity moves price sharply, gaps fade without volume confirmation, low floats reverse, delayed data is unreliable, and entries should wait for price to hold after the open — [Trade-Ideas](https://www.trade-ideas.com/2026/04/17/how-traders-use-stock-scanners-for-day-trading-in-a-volatile-premarket/)
- Other practitioner gap-and-go presets surfaced in search but were not reviewed: [Scanz](https://scanz.com/gap-and-go-strategy/), [Tapeboard presets](https://tapeboard.com/manual/scanner-presets)

### Inferences
- For SILAS (a tiny book, liquid names preferred), the ORB filters suggest raising Stage B to price > $5, ADV20 ≥ 1M and ranking by RVOL. That would have excluded CUE, AKAN, MPU, CLRO and PONY (<$5) today, matching the vetoes the desk applied by hand.
- Today's evidence fits the "gaps fade" warning: BRBR (+19.9% gap) lost VWAP and the opening-range low by 10:06, per the decision log, so a gap filter alone is not a signal.

### Gaps
- I found no rigorous public study that sets a minimum *premarket* volume or float cutoff. The commonly quoted small-cap thresholds (float < 10–20M, RVOL 5×) are practitioner folklore, and I did not verify them from a primary source.

---

## 4. Free fallback data, and fast catalyst and dilution checks

### Takeaway
Three free sources worked live on Nov 18: Nasdaq's premarket quote JSON (gives consolidated premarket last, volume, high and low); SEC EDGAR full-text search (confirmed BRBR's same-day 8-K with items 2.02/5.02/7.01/9.01 and listed recent S-3 and F-1 filings for dilution checks); and EDGAR's "latest filings" Atom feed by form type (live 424B5 stream). The connector's `get_earnings_calendar` confirms earnings catalysts.

### Cited findings (live-tested)
- **Nasdaq premarket quote:** `https://api.nasdaq.com/api/quote/BRBR/extended-trading?markettype=pre&assetclass=stocks&time=0` with a browser User-Agent. It returned "Pre-Market Consolidated Last Trade $13.07 +2.06 (+18.71%)", "Pre-Market Share Volume 330,138", high $13.53 (08:55:32), low $10.87 (06:20:26) and previous close $11.01. The page updates 04:00–09:30 ET. Market movers: `https://api.nasdaq.com/api/marketmovers?assetclass=stocks&exchangestatus=premarket&limit=10` returned most-active tables (data as of 09:59 ET). This is an unofficial JSON API and may change — tested 2026-11-18
- **EDGAR full-text search:** the endpoint is `https://efts.sec.gov/LATEST/search-index` with `q`, `forms`, `startdt`, `enddt`, `ciks` and `from`. `/LATEST/` is case-sensitive. A descriptive User-Agent is required (a generic or empty one gets 403). The SEC limit is 10 requests per second — [orthogonal.info](https://orthogonal.info/sec-edgar-full-text-search-api-efts-python/)
  - Live test: `q="BellRing"&forms=8-K&startdt=2026-11-17&enddt=2026-11-18` returned 4 hits, with BRBR 8-K file_date 2026-11-18 and items 2.02, 5.02, 7.01, 9.01 (earnings plus an officer change).
  - Live test: `q="at-the-market"&forms=424B5&startdt=2026-11-17&enddt=2026-11-18` returned 14 hits (the first was NanoViricides, NNVC).
  - Dilution test, CUE: `forms=S-3,424B5,424B3,S-1,EFFECT` over the last 6 months returned 17 hits (S-3 filings on 2026-06-03, 06-18 and 08-12).
  - Dilution test, AKAN: `forms=S-3,424B5,424B3,424B4,S-1,F-1,F-3,6-K` returned 43 hits, including F-1 on 2026-10-01 and F-1/A on 2026-10-19. That is a live registered offering, consistent with the desk's veto.
- **EDGAR latest-filings Atom feed:** `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=424B5&count=10&output=atom` returned a feed timestamped 10:12 EST listing new 424B5 filers (ERP Operating LP, AST SpaceMobile, Insight Molecular Diagnostics, Paramount Gold Nevada, Autozi, Ardent Health, DataMeds AI). Swap `type=8-K` for catalysts — tested 2026-11-18
- **Robinhood `get_earnings_calendar`** for 2026-11-18 returned `am` and verified entries for BRBR, PONY, TJX, TGT, BLSH and others, with actual EPS — [RH-EC]. The connector also offers `get_sec_filing_index` and `get_sec_filing` (not tested here).

### Inferences
- A fast veto pipeline, at about 1–2 seconds per name: (1) check whether the name is on the earnings calendar today with timing "am"; (2) if not, run EFTS 8-K for today and yesterday by company name or CIK; (3) run EFTS dilution forms (S-1, S-3, F-1, F-3, 424B3, 424B4, 424B5, EFFECT) over the last 90 days. Any 424B5 or 424B4 in the last 5 days, or an F-1 or S-1 in progress, is a hard dilution flag. An S-3 shelf by itself is a soft flag. (Choosing these forms reflects common practice: a 424B5 is a shelf takedown prospectus supplement. I did not source this from SEC documentation here.)
- Use the Nasdaq premarket % as an independent cross-check of `GAP_LIVE` in the 07:00 self-test.

### Gaps
- EFTS indexes filings shortly after acceptance, but I did not measure the lag. Nasdaq's API is undocumented and may rate-limit automated use. I did not test EDGAR's company `submissions` JSON (`data.sec.gov`), which is a faster per-CIK lookup.
