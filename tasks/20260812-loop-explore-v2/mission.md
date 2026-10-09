# Mission

## Scope

- Market: Taiwan stocks
- Symbols: 2330, 2454
- Data: local K-line only
- Start: 2022-01-01
- End: 2024-06-30
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
- Loaded date range: `2018-12-07` to `2026-08-11`
- Available requested symbols: 2330, 2454
- Missing requested symbols: none

Warnings:

- No data warnings from runner preflight.

## Objective

- Explore whether tightening stop-loss or loosening the 2B convergence threshold raises expectancy on 2330/2454
- Use `data_audit.json` before interpreting results.
- Write machine-readable output under `runs/`.
- Promote the selected run to `summary.json`.
- Prepare a Notion-ready daily research summary from local artifacts when Notion is configured.
