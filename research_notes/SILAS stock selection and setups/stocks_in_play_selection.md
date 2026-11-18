# Selecting "stocks in play" for intraday long momentum / opening-range trades (SILAS stock-selection fix)

Scope: evidence for which US stocks qualify as "in play" for a long-only 09:35-10:00 ET momentum/ORB entry, and how to rank them, written to fix SILAS's selection rules after the 2026-11-18 paper run (v1 day-move band 8-25%; v2 band 8-15% + $5 floor + 1M ADV; both filtered out every tradable name; BRBR, a $1.2B earnings gapper at +19.8% premarket, was skipped at 09:51 for being +25.2% and then broke its opening-range low 12.91 by 10:05). Inputs read: `_context_paper_decisions_2026-11-18.jsonl`, `_context_watchlist_2026-11-18.json`, `../Gordongecko strategy evaluation/strategy_edge_evidence.md`, `/home/claude/reports/Gordongecko strategy evaluation.md`. Research done 2026-11-18, ~20 tool calls. Rigour labels: **[peer-reviewed]**, **[working paper]**, **[practitioner-academic]** (authors sell related services), **[secondary]** (summary site), **[forum/practitioner]**.

## 1. How the Zarattini-Barbon-Aziz ORB paper (and replications) select stocks, and what it reports

### Takeaway
The only rigorous-ish "stocks in play" ORB study selects on liquidity + volatility + **opening-range relative volume (top 20 by RVOL, RVOL >= 100%)** and uses **no gap or day-move filter at all**. The RVOL filter is almost the whole edge: the same ORB on all stocks earned 3.2%/yr (Sharpe 0.48) vs 41.6%/yr (Sharpe 2.81) on the top-20 RVOL names. Direction is set by the first 5-minute candle, which is what protects against buying a fading gapper.

### Cited Findings
- Paper: Zarattini, Barbon & Aziz, "A Profitable Day Trading Strategy for the U.S. Equity Market" (SSRN, 2024; Univ. St. Gallen / Swiss Finance Institute research paper rp2498) **[working paper / practitioner-academic]**. Sample: all NYSE/Nasdaq stocks, Jan 2016-Dec 2023, ~7,000 names, survivorship-bias-free (CRSP daily, IQFeed intraday) — [Full text, Univ. St. Gallen repository](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content); [IDEAS record](https://ideas.repec.org/p/chf/rpseri/rp2498.html)
- Base filters (known at the open): opening price > $5; 14-day average volume >= 1,000,000 shares; 14-day ATR > $0.50 — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Relative volume definition: opening-range volume on day t divided by the average opening-range volume over the prior 14 days (first 5 minutes for the 5m-ORB). "Stocks in play" = RelVol >= 100%, then the **top 20 by RelVol** each day — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- **No gap-size or day-move filter is used** — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Trade rules: direction set by the first 5-minute candle (bullish → long only, bearish → short only, doji → no trade); stop order at the 5-minute high (long) / low (short); stop loss 10% of 14-day ATR from entry; exit at stop or 16:00 close; risk 1% of capital per position; max leverage 4x; $25k start; $0.0035/share commission; **no slippage modelled** — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Table 2 results (5m-ORB): ORB on all stocks — total 29%, IRR 3.2%, vol 6.6%, Sharpe 0.48, hit ratio 41.4%, MDD 13%. ORB + RelVol top-20 — total 1,637%, IRR 41.6%, vol 14.8%, Sharpe 2.81, hit ratio 48.4%, MDD 12%, worst day −1.61%, beta 0.00. S&P 500 — IRR 14.2%, Sharpe 0.78, hit ratio 54.9%, MDD 34% — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Table 3, opening-range length (all top-20 RelVol): 5m Sharpe 2.81 (IRR 41.6%, hit 48.4%); 15m Sharpe 1.43 (IRR 17.4%, hit 44.7%); 30m Sharpe 0.21 (IRR 2.3%, MDD 35%); 60m Sharpe 0.40 (IRR 4.1%); equal-weight combo Sharpe 1.99 — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- RelVol buckets (Figure 4, text): RelVol < 100% → average −0.02R per trade; RelVol > 100% → +0.08R; RelVol > 30x → +0.38R. Monotone: higher RVOL, higher expectancy — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Not reported in the paper: long vs short split, results by price, market cap, gap size or catalyst, top-N sensitivity, average win/loss — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Best/worst names by cumulative R are mid/large caps (best: DDD 385R with 21% win rate, FSLR, NVDA, SWBI, RCL; worst: CMC −154R with 12% win, TRGP, CSX, CNP, BJ) — [Full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- QuantConnect replication (1,000 most liquid stocks > $5, ATR > $0.50, 5-min RVOL > 1, top 20): 2016 Sharpe 2.40 vs SPY 0.84; 17 of 25 opening-range (5-25 min) × universe-size (500-1,500) combinations beat SPY's Sharpe; ATR threshold $0-$2 gave Sharpe 1.5-2.7; an "ATR >= 1% of price" variant gave Sharpe 2.24 **[forum/practitioner]** — [QuantConnect research thread](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)
- Same thread, commenters: one cites a **17% per-trade win rate** for the algorithm as written; another says the stop triggers on most trades but the profit ratio is high; raising the price floor to $50 and adding momentum filters lowered returns; performance collapsed in the dot-com period; costs are a major drag; slippage never answered **[forum, unverified]** — [QuantConnect research thread](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)
- CXO summary of the same paper (41.6% net, Sharpe 2.81) **[secondary]** — [CXO Advisory](https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/)

### Inferences
- The paper's "hit ratio" of 48.4% sits beside an S&P 500 "hit ratio" of 54.9%, which only makes sense as a share of positive *days*, not trades. The per-trade win rate is probably much lower (the 17% replication figure and the stop = 10% of ATR design both point to a low-win, fat-right-tail profile). SILAS should not expect ~48% trade wins from copying the filter.
- The evidence-based in-play definition is **RVOL-ranked, not move-ranked**. Neither the paper nor the replication caps the day move or gap. The v2 "8-15% band" has no source in this literature.
- The first-5-minute-candle direction rule is the paper's built-in fade filter: a gapper whose first 5-minute bar closes red is not a long. That rule, not a day-move cap, is what would have excluded a fading earnings gap.
- The 5m RVOL needs 14 days of first-5-minute volume history per symbol; the watchlist note ("RVOL-filtered scans return 0 before the open") confirms SILAS currently cannot compute the paper's RVOL premarket. It must be computed at 09:35 from minute bars.

### Gaps
- No top-N sensitivity (top 5/10 vs 20), long-only results, price/cap buckets, or catalyst split in the paper. I found no published replication that reports long-only ORB results on stocks in play.
- Slippage untested; the paper's universe is liquid ($5+, 1M ADV), so results do not transfer to sub-$5 names.

## 2. Earnings-announcement gaps intraday: continuation or fade on day 1? Does gap size predict fade?

### Takeaway
I found **no rigorous study that tests day-1 open-to-close returns of individual-stock earnings gaps by gap size** (e.g., >20% vs 10-20%). The adjacent rigorous evidence says: (a) attention-driven overnight gains tend to reverse intraday, more so in small, low-institutional, hard-to-value stocks; (b) price moves *with* information (analyst coverage, i.e. typical of earnings) drift rather than reverse, while no-information moves reverse; (c) earnings momentum (SUE) earns its premium overnight, not intraday. So the case for a hard 25% day-move cap on an earnings gapper is weak; the case for requiring opening-range confirmation is stronger.

### Cited Findings
- Berkman, Koch, Tuttle & Zhang, "Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open", JFQA 47(4):715-741 (2012) **[peer-reviewed]**: 3,000 largest US stocks 1996-2008. Mean overnight return ~+10 bp/day, mean open-to-close ~−7 bp; opening midquote ~8 bp above prior close then falls during the first hour — [Koch, KU ScholarWorks PDF](https://kuscholarworks.ku.edu/bitstream/1808/10965/1/Koch_Paying%20Attention.pdf); [IDEAS](https://ideas.repec.org/a/cup/jfinqa/v47y2012i04p715-741_00.html)
- Same paper: high-attention stocks (proxied by yesterday's squared return / net retail buying) average +13 bp overnight and −13 bp intraday vs ±3 bp for low attention; high-attention + low-institutional-ownership +17/−17 bp; small high-attention low-IO stocks +29 bp overnight / −19 bp intraday vs large +9/−11 bp; NASDAQ high-attention low-IO −42 bp intraday; most hard-to-value/costly-to-arbitrage stocks −45 bp (main) to −70 bp (NASDAQ) per day; effects more than double in high-sentiment months — [Koch PDF](https://kuscholarworks.ku.edu/bitstream/1808/10965/1/Koch_Paying%20Attention.pdf)
- Same paper does **not** study earnings announcements specifically — [Koch PDF](https://kuscholarworks.ku.edu/bitstream/1808/10965/1/Koch_Paying%20Attention.pdf)
- Lou, Polk & Skouras, "A tug of war: overnight versus intraday expected returns" (JFE 2019; LSE eprint) **[peer-reviewed]**, 1993-2013: earnings momentum (SUE) overnight CAPM alpha 0.56%/month (t=3.20) vs intraday 0.21% (t=0.70, indistinguishable from zero); price momentum overnight 0.98% (t=3.84) vs intraday −0.02%; short-term reversal (STR) overnight +0.93% vs intraday −1.05% (t=−3.25); stocks with high past-month overnight returns earn −3.24%/month (t=−9.34) intraday the next month — [Lou-Polk-Skouras PDF (LSE)](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf); [LSE Research Online](https://eprints.lse.ac.uk/87481)
- Same paper, announcement days: most strategies earn a significant abnormal return on announcement days; BM, MOM and STR earn the announcement premium intraday, ROE/IVOL/accruals overnight; a significant portion of earnings announcements occur outside trading hours — [Lou-Polk-Skouras PDF](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)
- Aboody, Even-Tov, Lehavy & Trueman, "Overnight Returns and Firm-Specific Investor Sentiment", JFQA 53(2):485-505 (2018) **[peer-reviewed]**: overnight returns persist in the short term (stronger in hard-to-value firms), but high-overnight-return stocks underperform over the longer term — consistent with temporary sentiment-driven mispricing (abstract-level; numbers not retrieved) — [IDEAS](https://ideas.repec.org/a/cup/jfinqa/v53y2018i02p485-505_00.html)
- Savor, "Stock returns after major price shocks: the impact of information", JFE 106(3):635-659 (2012) **[peer-reviewed]**: daily abnormal moves beyond ±10%, 1995-2009, 166,470 events. Moves with an analyst report (day −1 to +1) **drift**; moves without one **reverse** (about 9.6% of the shock over 20 days). No-information events outnumber information events ~4:1, and the excess of positive over negative shocks comes entirely from no-information events. Information events are at larger firms (mean ~$3.0bn vs ~$1.0bn). Results hold excluding < $5 and bottom-NYSE-decile stocks. Daily data only, no intraday analysis — [Savor, CORE PDF](https://core.ac.uk/download/132270865.pdf); [EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:635-659)
- Chan, "Stock price reaction to news and no-news: drift and reversal after headlines", JFE 70(2):223-260 (2003) **[peer-reviewed]**: title/known finding — headline-news moves drift, no-news moves reverse (abstract not retrieved; bibliographic record only) — [EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:70:y:2003:i:2:p:223-260)
- Index-level gaps (not single stocks): Plastun, Sibande, Gupta & Wohar, "Price Gap Anomaly in the US Stock Market: The Whole Story" (working paper, 2020): on S&P 500 gap days, open-to-close moves in the gap direction (positive-gap days +1.15% vs +0.02% non-gap days); 2009-2018 buy-the-up-gap: 67% wins, 5.9%/yr before costs; effect gone by next day; ~23% of gaps filled within five days; no returns reported by gap size — [Univ. Pretoria repository PDF](https://repository.up.ac.za/server/api/core/bitstreams/f829a6c1-5762-48b1-89eb-a1ef54125843/content)
- Earnings timing: pre-open announcements keep volatility elevated longer (about four days to stabilise vs post-close), per Lyle, Rigsby, Stephen & Yohn (2017 SSRN working paper) as summarised by Kellogg Insight **[secondary summary of working paper]** — [Kellogg Insight](https://insight.kellogg.northwestern.edu/article/traders-are-surprisingly-slow-to-respond-to-off-hours-earnings-announcements)

### Inferences
- BRBR (fiscal-Q4 earnings + new CEO's first FY27 outlook, pre-open, $1.2B cap) is an *information* event in Savor/Chan terms, which on average drifts rather than reverses at daily horizons. But pre-open announcements carry longer volatility, and the open-to-close leg is where attention-driven overnight gains get given back (Berkman). Both apply to BRBR; neither gives a gap-size threshold.
- BRBR's own tape fits the ORB direction rule better than the cap: high 14.01 at 09:31, 13.13 and below VWAP at 09:36, i.e. a weak first bars sequence. If its first 5-minute candle closed below its open, the paper's rule would have allowed **no long that day**. (Open price not in the log; this needs checking from minute bars.) The 25% cap "saved" the loss by coincidence, not by design.
- Lou-Polk-Skouras suggests the earnings-momentum premium is captured overnight; a day-trader buying after the open is mostly not paid for the earnings news itself. Expect any intraday edge to come from the in-play/ORB mechanism, not from "earnings beat".

### Gaps
- No peer-reviewed single-stock study found of day-1 open-to-close returns after earnings gaps, by gap size (e.g. >20%), surprise sign, or cap. Practitioner "earnings gap" articles (e.g. TradingSim, daytradingtoolkit) exist but give no auditable data; not cited as evidence.
- Lou-Polk-Skouras announcement-day table (A6) numbers by overnight/intraday not retrieved.

## 3. Is a day-move cap (e.g. 25%) or gap-size band supported, or should ranking be by RVOL and catalyst?

### Takeaway
No source tested a day-move cap or an 8-15% / 8-25% band. The rigorous evidence supports **ranking by opening relative volume** and **conditioning on catalyst type and first-bar direction**, with a soft extension penalty for no-news / small-cap attention spikes rather than a hard cap for news-driven mid caps.

### Cited Findings
- ORB stocks-in-play universe has no gap/day-move filter; RVOL is the selection variable, and expectancy rises with RVOL (−0.02R <100%, +0.08R >100%, +0.38R >30x) — [Zarattini et al. full text](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content)
- Extreme attention (bigger moves, more retail buying) increases the intraday give-back; small, low-institutional, hard-to-value stocks worst — [Berkman et al. 2012](https://kuscholarworks.ku.edu/bitstream/1808/10965/1/Koch_Paying%20Attention.pdf)
- Robinhood herding days: average ~+14% (42% for extreme herding), mean opening return ~11%, subsequent losses traced to intraday returns, concentrated in < $1B caps — [Barber, Huang, Odean & Schwarz 2020 SSRN](https://www.smallake.kr/wp-content/uploads/2020/12/SSRN-id3715077.pdf) (from prior evaluation notes)
- Information vs no-information at a fixed ±10% threshold: direction of the follow-through depends on information, not on the size of the move — [Savor 2012](https://core.ac.uk/download/132270865.pdf)
- QuantConnect commenters: adding momentum filters to stocks-in-play ORB lowered returns **[forum, unverified]** — [QuantConnect thread](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)

### Inferences (recommended SILAS rules; parameters marked "paper" come from Zarattini et al., others are my inference)
- **Drop the hard day-move band as a qualifier** (both v1 8-25% and v2 8-15%). Replace with:
  1. Liquidity gate (paper): open > $5; 14-day ADV >= 1,000,000 shares; 14-day ATR >= $0.50 (or ATR >= 1% of price for low-priced names, per the QC variant).
  2. In-play gate (paper): 5-minute opening-range RVOL >= 1.0 (vs 14-day average of first-5-minute volume); rank by RVOL; candidate list = top 20. With 2 slots, take the highest-RVOL qualifiers that pass the other gates.
  3. Direction gate (paper): first 5-minute candle close > open; entry only on a break of the 5-minute high (buy-stop), stop 10% of 14-day ATR below entry (paper) — or SILAS's own stop if risk rules require, but note it is a different strategy then.
  4. Spread gate (inference, from prior notes): spread <= 0.5-1% at 09:35, and well below the stop distance.
  5. Extension: replace the cap with a **soft penalty** — if the gap/day move is > ~25% *and* the catalyst is not earnings/guidance/analyst-confirmed, or cap < $300M, skip; earnings gappers with cap >= $300M and passing gates 1-4 are allowed at any gap size. The 25% figure is inherited from SILAS, not from evidence.
- Ranking score (inference): RVOL rank first; tie-break by catalyst class (Section 4) then by tighter spread. Do not rank by % change.
- Under these rules on 2026-11-18: BRBR passes gates 1-2 and 4 (if RVOL >= 1 and ADV >= 1M — not verified), and its entry would hinge on gate 3; PONY, CUE, TGL, WYHG, GMM, CLRO, AKAN, NCPL, GP fail the $5 floor; CALM fails RVOL (0.47). So "zero trades" can still be the correct outcome on a day like this; the fix changes *why*.

### Gaps
- No evidence quantifies how many stocks per day pass $5 / 1M ADV / RVOL >= 1 / bullish first bar in the long-only half; top-20 is a two-sided list.
- Whether BRBR met 1M 14-day ADV and RVOL >= 1 at 09:35 was not in the context files.

## 4. Catalyst classification: which catalysts continue intraday?

### Takeaway
Rigorous evidence supports a two-way split — **information (earnings, analyst/guidance) → drift; no-news → reversal** — at daily horizons. For social-media/promotional spikes in microcaps the evidence points to reversal within days. For biotech/FDA news, I found only weak evidence (pre-commercial companies' pop fades within days). No study measures these by catalyst at the intraday ORB horizon.

### Cited Findings
- Analyst-report (information) shocks drift; no-information shocks reverse (~9.6% of the move over 20 days); no-info long-short ~+20% annualised alpha (t≈7.3); information-event long-short is the reverse sign — [Savor 2012](https://core.ac.uk/download/132270865.pdf)
- Headline news → drift; no-news extreme moves → reversal — [Chan 2003, EconPapers record](https://econpapers.repec.org/RePEc:eee:jfinec:v:70:y:2003:i:2:p:223-260) (abstract not retrieved)
- Social-media pump spikes: Renault (2017) on OTC microcaps (Oct 2014-Sep 2015): abnormal return +3.1% the day before a Twitter spike, +6.5% on the spike day, −2.5% cumulative over the next five days; stronger at lower price/cap thresholds; short sample **[working paper via secondary summary]** — [CXO Advisory summary](https://www.cxoadvisory.com/?p=30149)
- FDA breakthrough-therapy designations: commercial-stage companies show essentially no price response; pre-commercial companies rise on the announcement day but the gain fades within a few days (study authors and figures not given in the article) **[trade press, weak]** — [Endpoints News](https://endpts.com/?p=206983)
- At-the-market dilution: ATM issuers are small (median equity $0.18B) and sell shares into price strength — [Billett, Floros & Garfinkel, JFQA 2019 PDF](https://www.biz.uiowa.edu/faculty/jgarfinkel/pubs/ATM.pdf) (from prior evaluation notes)

### Inferences — proposed catalyst classes for ranking/vetoes
- **A (allow, rank highest at equal RVOL):** scheduled earnings/guidance with confirmed press release, cap >= $300M; analyst up/downgrade with coverage.
- **B (allow, reduced size/stricter confirmation):** M&A target (only if not a fixed-price cash deal — those pin to the deal price, already vetoed), contract wins at mid caps, FDA decisions at *commercial-stage* companies.
- **C (de-prioritise; require stronger RVOL and first-bar confirmation):** FDA/clinical news at pre-commercial biotechs; sector sympathy moves.
- **D (veto):** no identifiable news on a >10% move in a sub-$1B name; unverified press-release/social-media spikes; active shelf/ATM, reverse-split history, shells (SILAS already vetoes most of these).
- These are inferences mapping Savor/Chan/Renault to SILAS; the class boundaries and the $300M figure are not tested in any source.

### Gaps
- No intraday (09:30-16:00) evidence by catalyst type found. No rigorous FDA/biotech intraday study retrieved (search results were small-journal/thesis items, not reviewed).
- No study found on low-quality "press-release pumps" on listed (Nasdaq) small caps specifically, as opposed to OTC.

## 5. Market-cap / float effects on intraday continuation

### Takeaway
Every relevant rigorous source finds the intraday give-back is larger in smaller, lower-institutional-ownership, harder-to-value, retail-attention stocks; information-driven moves cluster in larger firms. The profitable ORB universe is effectively mid/large caps ($5+, 1M+ ADV). I found no study of float specifically.

### Cited Findings
- Small high-attention low-IO stocks: +29 bp overnight / −19 bp intraday vs large +9 / −11 bp; smaller firms have larger trading-day reversals in Fama-MacBeth regressions — [Berkman et al. 2012](https://kuscholarworks.ku.edu/bitstream/1808/10965/1/Koch_Paying%20Attention.pdf)
- Robinhood herding losses concentrated in stocks under $1B — [Barber et al. 2020](https://www.smallake.kr/wp-content/uploads/2020/12/SSRN-id3715077.pdf)
- Information shocks are at larger firms (mean ~$3.0bn vs ~$1.0bn); drift/reversal results survive excluding < $5 and bottom-decile size — [Savor 2012](https://core.ac.uk/download/132270865.pdf)
- Twitter-pump fade stronger at lower price and market-cap thresholds — [CXO summary of Renault 2017](https://www.cxoadvisory.com/?p=30149)
- ORB top names are liquid mid/large caps (NVDA, FSLR, RCL, DDD) — [Zarattini et al.](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content); QC commenter: raising the price floor to $50 hurt results **[forum]** — [QuantConnect thread](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)

### Inferences
- Keep the $5 floor and 1M ADV (paper) for all variants, not only v2; v1's $1 floor puts SILAS in the segment with the strongest documented intraday reversal. A market-cap floor around $300M-$1B is consistent with the evidence direction but no source gives a cutoff; treat $300M as a starting value to test.
- Do not add an upper price cap beyond affordability; the forum evidence (weak) suggests high-price filters hurt. On a ~$120 account, affordability (whole shares under a stop) is the binding upper limit — a sizing issue, not an evidence one (CALM at $68.56 was over half the book).

### Gaps
- No study found on float size (low-float) and intraday continuation; low-float claims are practitioner folklore in what I found.
- No ORB results by market-cap bucket.
