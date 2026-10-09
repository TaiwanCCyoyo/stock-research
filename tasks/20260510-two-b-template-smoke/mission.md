# Mission

## Scope

- Market: Taiwan stocks
- Symbols: 2330, 2308, 2454, 2317, 3711, 2383, 2345, 3017, 3037, 2360, 2382, 2303, 6669, 2357, 3008, 3034, 3231, 2301, 2324, 2352, 2353, 2356
- Data: local K-line only
- Start: 2022-01-01
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

- Data path: `C:\Users\xjp01\Documents\Stock\shioaji_stock_prices\data`
- Price file exists: `False`
- Loaded date range: `2018-12-07` to `2026-01-05`
- Available requested symbols: 2330, 2308, 2454, 2317, 3711, 2383, 2345, 3017, 3037, 2360, 2382, 2303, 6669, 2357, 3008, 3034, 3231, 2301, 2324, 2352, 2353, 2356
- Missing requested symbols: none

Warnings:

- No data warnings from runner preflight.

## Objective

- Smoke test 2B MA convergence template.
- Use `data_audit.json` before interpreting results.
- Write machine-readable output under `runs/`.
- Promote the selected run to `summary.json`.
- Generate `walkthrough.md` and `nightly_report.md`.
- Prepare a Notion-ready daily research summary from local artifacts when Notion is configured.
