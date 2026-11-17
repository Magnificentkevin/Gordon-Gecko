---
name: gordongecko
description: Disciplined trade desk for long stock trades - market regime check, chart read, risk-based sizing, pre-trade gate, and (if Trayd is connected) a confirmed Robinhood limit order. Use for /gordongecko or "should I take this trade / plan a trade on TICKER".
---

# Gordongecko

"Greed is good" - but only inside a risk limit. Gordongecko runs one trade idea through a fixed process and produces a trade ticket. It never skips the risk steps and never places an order without the user's explicit yes.

Educational tool, not financial advice. The user makes every trading decision.

## Setup

The scripts live in the skill folder (`scripts/`) and in the public repo
https://github.com/Magnificentkevin/Gordon-Gecko. If `scripts/` is not present, clone the repo into its own directory and run from there:

```bash
mkdir -p ~/ext && cd ~/ext && git clone -q --depth 1 https://github.com/Magnificentkevin/Gordon-Gecko.git gordongecko
```

Python 3.9+, standard library only. No API keys.

## Inputs

Ask only for what is missing:
- Ticker
- Account equity (or read it from Trayd if connected)
- Entry idea: price or "at market", and a stop (or let ATR set it)
- Target (needed for reward:risk)
- Risk already open, as % of equity (default 0)
- Optional: weekly chart image

## Process

### 1. Market regime
```bash
python3 scripts/gecko_regime.py
```
Gives RISK-ON (x1.0), CONSTRUCTIVE (x0.75), CAUTION (x0.5) or DEFENSIVE (x0, no new longs). If the script can't reach the data, fetch the CSV URL printed in the script with WebFetch and pass it with `--csv`; if that also fails, treat the regime as DEFENSIVE. If the market-breadth-analyzer skill is installed, it can be used for a deeper read.

### 2. Setup read
- With a chart image: trend, support/resistance, 20/50/200-week MAs, volume, and 2-3 scenarios with probabilities (use the technical-analyst skill if installed).
- Without a chart: get the current quote (Trayd `quote` tool if connected, otherwise WebSearch) and confirm the stop sits below a real support level, not an arbitrary %.
- Check for earnings in the next 7 days. Flag it if present.

### 3. Size and gate
```bash
python3 scripts/gecko_size.py --account EQUITY --entry ENTRY --stop STOP --target TARGET \
  --regime-mult MULT --open-risk-pct OPEN [--fractional 4] [--json]
```
Defaults: 1% base risk, 20% max position, 6% max portfolio heat, 2.0 minimum reward:risk, 2% hard risk ceiling. Use `--fractional` only if the user's broker supports fractional shares.

The gate FAILS on: reward:risk below minimum, DEFENSIVE regime, heat above cap, risk above 2%, or zero shares. A FAIL means no order. Explain each reason plainly and say what would fix it (tighter stop, smaller size, wait for a better regime).

### 4. Trade ticket
Present a short ticket:

| Field | Value |
|---|---|
| Ticker / side | |
| Order | Limit buy N @ $X (day / extended) |
| Stop / target | $S / $T, R:R |
| Dollar risk | $R (x% of account) |
| Regime | label, multiplier |
| Gate | PASS / FAIL and why |
| Notes | earnings, chart scenarios |

### 5. Execute (only if Trayd is connected and the gate PASSED)
- Show the exact order and ask: "Place this order? (yes/no)". Place it only after an explicit yes in the same turn.
- Default to a **limit** order at or below the planned entry. Use a market order only if the user explicitly asks.
- After placing, read the order back from Trayd and report its status.
- Then offer the protective stop: place a stop order if Trayd supports it, otherwise tell the user to set it in the Robinhood app.
- Never place orders on a schedule or in a loop without a fresh yes for each order.

If Trayd is not connected, stop at the ticket and say the user can place it in Robinhood or connect Trayd (Settings > Connectors > custom connector `https://mcp.trayd.ai/mcp`).

### 6. Journal
Save the ticket and reasoning as `journal/YYYY-MM-DD_TICKER.md` (template: `references/trade_plan_template.md`) so it can be reviewed after the trade closes.

## Rules that never bend
1. No stop, no trade.
2. Size comes from risk, never from conviction.
3. Regime DEFENSIVE or UNKNOWN means no new longs.
4. Total open risk stays under 6% of equity.
5. No order without an explicit yes.
