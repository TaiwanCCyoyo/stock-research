## Why

There is no stock classification or grouping in this project — only a flat code→name
lookup (`stock_symbol_mapping.json5`). The user wants to run the same strategy parameters
across different named groups of stocks (e.g. "半導體" vs "傳產金融") and compare results,
which today requires manually typing comma-separated code lists for `--codes` every time
and offers no cross-group comparison output. This change adds industry/classification
metadata, named reusable universes, and a comparison mode that mirrors the existing
capital-mode comparison pattern.

## What Changes

- Add symbol classification metadata sourced from TWSE/TPEx ISIN public industry-category
  data: market (上市/上櫃), industry category, ETF flag, listing date. Stored locally
  (SQLite or JSON, matching the project's existing lightweight-storage convention).
- Add `universes/*.json` — user-defined, version-controlled named groups of stock codes
  (either an explicit code list or a rule such as `industry: 半導體`).
- Extend `--codes` in `StockProject/backtest_cli.py` and `scripts/run_task_backtest.py` to
  accept `@universe-name`, expanding to that universe's code list at runtime.
- Add a batch comparison mode: running with multiple `@universe` arguments (or a
  `--universes` flag) produces one full summary per universe plus a thin cross-universe
  comparison artifact, following the same Option-A pattern established by
  `build_capital_mode_comparison`/`write_comparison_artifacts` in `backtest_cli.py`.
- Add industry/universe filtering to the dashboard's task and ranking views so results can
  be sliced by classification without re-running a backtest.

## Capabilities

### New Capabilities

- `universe-management`: symbol classification metadata, named universe definitions,
  `@universe` code-list expansion, and cross-universe comparison artifacts.

### Modified Capabilities

- `research-dashboard`: task/ranking views gain industry/universe filtering.

## Non-Goals

- No automatic strategy recommendation per industry — this is a filtering/comparison
  capability, not a new strategy.
- No real-time reclassification — industry metadata refreshes on the same cadence as other
  reference data (manual/periodic re-fetch), not per-backtest.
- No change to per-symbol backtest mechanics — a universe is purely a named code list at the
  CLI boundary.
- Docker-backed execution is not required for local validation; note any skipped Docker
  checks in completion notes.

## Impact

- New local metadata store: `shioaji_stock_prices/data/symbol_meta.sqlite` (or equivalent
  JSON, TBD in design).
- New directory: `universes/*.json`.
- `StockProject/backtest_cli.py`: `--codes` gains `@universe` expansion; new
  `--universes` batch mode reusing the Option-A artifact pattern
  (`build_capital_mode_comparison`, `write_comparison_artifacts`).
- `scripts/run_task_backtest.py`, `scripts/create_research_task.py`: same `@universe`
  support.
- `research_lab/dashboard_core.py`: industry/universe filter on ranking and task views.
