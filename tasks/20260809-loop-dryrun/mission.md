# Mission

## Scope

- Market: Taiwan stocks
- Symbols: 1101, 2891
- Data: local K-line only
- Start: 2023-01-01
- End: latest available local data
- Prepared by: `scripts/prepare_nightly_research.py`

## Constraints

- No real trading
- No broker credentials
- No internet research
- Do not modify `StockProject/engine/`
- Use Docker for generated strategy execution
- Runner only prepares this task; Codex remains responsible for strategy design and interpretation

## Data Preflight

- Data path: `shioaji_stock_prices/data`
- Price file exists: `True`
- Loaded date range: `2018-12-07` to `2026-08-07`
- Available requested symbols: 1101, 2891
- Missing requested symbols: none

Warnings:

- No data warnings from runner preflight.

## Objective

- Autonomous-research-loop 2-iteration smoke test on the merged tooling with real price data.
- Use `data_audit.json` before interpreting results.
- Write machine-readable output under `runs/`.
- Promote the selected run to `summary.json`.
- Prepare a Notion-ready daily research summary from local artifacts when Notion is configured.
