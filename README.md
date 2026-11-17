# Gordongecko

A Claude skill with two modes on Robinhood's official Trading connector:

- **Trade Planner** - one trade idea, step by step, and you approve every order (below).
- **SILAS Desk** - the automated weekday cash-equity day-trading desk with hard risk floors (50% bank stop, 5% max loss per trade, flat before the close). See the Mode B section of `SKILL.md`, `reference/` and `scripts/README.md`.

## Trade Planner

1. **Market regime**: scores S&P 500 breadth (share of stocks above their 200-day average) and sets a risk multiplier.
2. **Setup read**: chart or quote check, support/resistance, earnings flag.
3. **Size and gate**: sizes from dollar risk, caps by position size and portfolio heat, and returns PASS/FAIL.
4. **Trade ticket**: one clear table.
5. **Execute (optional)**: through Robinhood's Trading connector it previews the order, then places a **limit** order only after you say yes.
6. **Journal**: saves the plan for review after the trade.

Run it with `/gordongecko`, or ask "plan a trade on NVDA".

## Install

- **Claude.ai / Claude app**: upload this folder as a skill (zip it, or save it from a Claude chat).
- **Claude Code**: copy the folder to `~/.claude/skills/gordongecko/`.

## Scripts (Python 3.9+, standard library only)

```bash
python3 scripts/gecko_regime.py            # regime + risk multiplier
python3 scripts/gecko_size.py --account 10000 --entry 155 --stop 148.50 --target 170 --regime-mult 0.75
```

Example output:

```
Regime: CONSTRUCTIVE  (risk multiplier x0.75)
Verdict: PASS
Buy 11 shares @ $155.00  stop $148.50 (4.19%)  target $170.00  R:R 2.31
Position $1,705.00 (17.05% of account), limited by risk budget
Risk $71.50 (0.715%), regime x0.75, heat after trade 0.71%
```

## Default limits

| Rule | Default |
|---|---|
| Base risk per trade | 1% of equity |
| Hard risk ceiling | 2% |
| Max position | 20% of equity |
| Max portfolio heat | 6% |
| Minimum reward:risk | 2.0 |

## Credits

SILAS Desk: Kevin's own desk, merged in 2026-11-17.
Breadth data: [tradermonty/market-breadth-analysis](https://tradermonty.github.io/market-breadth-analysis/). Workflow inspired by [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) (MIT). Gordongecko's code is original.

## Disclaimer

For education and process discipline only. Not financial advice. Trading involves risk of loss. You are responsible for every order.
