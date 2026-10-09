# Mission

## Scope

- Market: Taiwan stocks
- Symbols: 2330, 2454, 2317
- Data: local K-line only
- Start: 2024-01-01
- End: latest available local data

## Research Question

- Explore whether a breakout-style entry can reduce false positives when combined with simple trend filters.
- Treat this as a daily research discussion with Codex, not as a production trading signal.

## Constraints

- No real trading.
- No broker credentials.
- No internet research unless the user explicitly asks for it.
- Do not modify `StockProject/engine/` during strategy experiments.
- Use Docker-backed backtests when executing generated or uncertain strategy code.
- Keep local task artifacts as the source of truth.
- If Notion is configured, sync only a research summary, not secrets or trading instructions.

## Objective

- Create or choose at least one task-local candidate strategy.
- Run a backtest or parameter sweep when useful.
- Promote the selected run to `summary.json`.
- Summarize the strategy hypothesis, experiments, key metrics, risks, and next experiment ideas.
