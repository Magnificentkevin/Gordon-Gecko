# Entries and TA

The current profile (`higher-risk+15`) supersedes older 4/5 or 5/5 TA
lines and older cutoffs that may still appear lower in procedure files.

## When the desk may buy

- **09:35–10:00 ET** — primary live window. Setups: `gap_and_go`,
  `early_momentum`. TA ≥ 3/5 plus every hard filter.
- **10:00–13:30 ET** — A+ path only (`entryPlaybook.aPlus`): on today's
  watchlist, score ≥ 0.51, TA ≥ 3/5, at most 3 such fills per day, **never
  a re-entry**. Tag `playbookTag=aPlus`.
- **13:30–15:45** — no new live buys. Manage exits only.
- **15:45+** — flatten path; no new buys.

Paper-only until promoted from paper-session evidence (`entryPlaybook.promote`:
typically ≥ 10 trades, win ≥ 40%, avg ≥ +0.5%): `recycle_bounce`,
`orb_breakout`, `midday_momentum`, `vwap_reclaim`, `momentum_pullback`.
Live recycling of a **winner** (green close today) is still allowed when
filters pass; live recycling after a **loss** is not.

If the day is in protect mode, halted by the kill switch, at the
round-trip cap (9), at the 2-slot cap, or `protection.buysAllowed` is
false, place no new buys.

## Hard filters (all live entries)

| Filter | Current rule |
|---|---|
| Day-move at entry | 8–25%. Names in 8–15% rank first (ranking bonus, not a hard cap at 15). Moves > 15% historically stop out often. |
| Relative volume | ≥ 1.75 (volume-shape keep-RVOL ≥ 1.5) |
| Liquidity | Time-of-day average shares (and dollar volume for the fractional lane) over the last 3 completed 5-minute bars. See bands below. |
| Spread | Skip if bid-ask spread ≥ 8% (tighter 3% band under $0.25) |
| Bid-to-stop | Hard spread-equivalent filter stays anchored at **ask × 0.98** (`entryFilters.bidToStopPct` −2.0) even though the recovery decision point is −3.45%. Skip if the gap to that level is too tight. |
| Price floor | Last / ask ≥ **$1.00** |
| Coverage | Skip if bar coverage for TA < 80% (`taIncomplete` → skip the name; never invent indicators) |
| Dilution / offering | Skip a name with a dilution filing in the last 30 days, listing noncompliance, or a going-concern warning |
| Event veto | Skip tender, Dutch-auction, and merger-arb names (below) |
| No re-buy after a loss | If this symbol already closed at a loss today, do not buy it again |
| Halted / not tradable | Skip. Eligibility from `get_equity_tradability` in this same run, never a cached flag |
| Chase veto | Do not buy a gapper whose high already printed in the first 5 minutes if price is below the opening-range high or VWAP |

### Liquidity bands (shares per 5-minute bar / fractional dollar floor)

Current config (the midday band has been learned upward from the original
50k–150k U-shape):

| Window (ET) | Min avg shares | Fractional min $ volume |
|---|---|---|
| 09:30–10:30 | 100,000 | $1,500,000 |
| 10:30–11:30 | 100,000 | $1,000,000 |
| 11:30–14:00 | 200,000 | $500,000 |
| 14:00–15:00 | 75,000 | $750,000 |
| 15:00–15:45 | 100,000 | $1,000,000 |

`ta.py` prints the band it used as `liqFloor`. The floor is tape quality,
not fill size. Default whole-share floor in the helper is 150k when no
band applies.

## The five TA checks (need 3)

Helper:

```
python3 ${HELPERS_DIR}/ta.py analyze --symbol S --bars <5m> [--bars1 <1m>] --cash <available> --now <ISO>
```

Prefer broker 5-minute historicals (batch up to 10 symbols). Fall back to
1-minute bars from 10:01, dropping interpolated or zero-volume bars. Do
not invent values; if a check cannot be scored, mark the name incomplete
and skip it.

1. **Volume shape.** RVOL still acceptable; last complete 5-minute bar is
   not collapsing (< 50% of the prior 3-bar average is a fail).
2. **StochRSI (14).** Longs only. Prefer %K rising from ≤ 30, or 30–70
   with higher lows. Skip a new entry if %K ≥ 80 unless price is
   reclaiming VWAP on rising volume. On a pullback re-hit, prefer %K
   turning up from ≤ 40.
3. **Session VWAP.** Prefer price ≥ VWAP. Skip if fading more than 1%
   below VWAP on falling volume. Strongest pattern: prior bar closed
   below VWAP, current bid/last back above, volume rising.
4. **Bollinger (20, 2 std, 5-minute).** Prefer mid-band or a bounce off
   the lower band with StochRSI turning up, or a squeeze-to-expansion
   close above mid. Skip a chase if last is above the upper band and
   StochRSI %K ≥ 80.
5. **Fibonacci.** Impulse from the session (or first 30–60 minute) low to
   high, or a first-entry fallback swing. Prefer a re-hit in 38.2–61.8%
   that holds, with VWAP or mid-BB. Skip a re-hit that breaks 61.8% on
   rising sell volume. If there is no clear impulse, do not fail the
   name on fib alone (`fibPending`); the other checks must still pass.

`requiredPassCount` is 3, `strictMinPassCount` is 3, all day. After enough
trades under the current profile, `desk_learn.py` may step that count by
1 within 3–5.

## Setup playbook

- **gap_and_go** — gapper holding above the premarket high / VWAP at the
  open on heavy volume; enter on the first 1–5 minute higher low. This is
  the strongest live setup in the record (see
  [Lessons learned](lessons-learned.md)).
- **early_momentum** — 09:45–10:00 continuation that still passes filters.
- **orb_breakout** — break of the 09:30–09:35 (or 5-minute) opening-range
  high with volume, above VWAP. Paper-only until promoted.
- **vwap_reclaim** — flush then reclaim of session VWAP on rising volume;
  stop under VWAP / the hard stop. Paper-only until promoted.
- **momentum_pullback** — strong trend, pullback into 23.6–61.8% fib or
  mid-BB with stoch turning up, then the next green bar. Paper-only
  until promoted.
- **recycle_bounce** — re-entry of a symbol that closed **green** today
  after a pullback. Never after a red close. Live winner-recycles are
  allowed; the broader setup still lags in the live record.
- **midday_momentum** — 10:30+ continuation. Historically the weakest
  slot; live only via the A+ path.

## Event veto

Reject a name with a same-day (filed or announced today or since the prior
close) tender offer, Dutch auction, or merger agreement. Upside is pinned
and stop wicks are cheap.

Forms: `SC TO-I`, `SC TO-T`, `SC TO-C`, `SC 14D9` / `SC 14D-9`, `DEFM14A`,
`PREM14A`, `8-K` item 1.01 (merger agreement).

Headline keywords: tender offer, dutch auction, self-tender, to be
acquired, definitive agreement to be acquired, merger agreement, agreed to
be acquired, take-private, go-private.

```
python3 ${HELPERS_DIR}/discretion.py gate --symbol S --last L --day-pct P \
  [--filings 'SC TO-I,8-K:1.01'] [--news 'headline text'] --now <ISO> --state <state>
```

## Watchlist

- Evening kb-refresh drafts `${DESK_ROOT}/kb/watchlist-<next-session>.json`
  from after-hours catalysts (`desk_learn.py watchlist`).
- 07:00 research refines it.
- After 10:00, A+ entries require this file and a score ≥ 0.51. A thin or
  empty watchlist, or scores well under 0.51, means **no** after-10:00
  entries — that is a correct skip, not a reason to loosen the gate
  mid-session.

## Entry gate and sizing helpers

```
python3 ${HELPERS_DIR}/discretion.py gate --state <state> --symbol S --last L --day-pct P --now <ISO>
python3 ${HELPERS_DIR}/discretion.py size --state <state> --ask A --buy-limit L --now <ISO>
```

The gate enforces the playbook, the kill switch, protection, caps, the
price floor, and the no-rebuy-after-loss rule. Size from this fire's cash,
not from a cached `bankUsd`.
