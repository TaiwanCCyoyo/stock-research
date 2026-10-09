## Why

The research dashboard is slow enough to hurt daily use: every K-line render calls
`load_price_data` → `DataLoader.load_all()`, which globs and parses all ~2,068
`{code}_day.csv` files in `shioaji_stock_prices/data/` even when the user selected one
symbol. Dashboard startup is similarly slow because `discover_tasks` eagerly parses every
`tasks/*/summary.json` (tens of KB each) before the user has picked a task. This change
fixes the data-loading path underneath the existing Panel dashboard now, and doubles as the
shared fast-path the future FastAPI backend (`add-research-api`) will reuse — so the
investment is not throwaway.

## What Changes

- Add `DataLoader.load_symbols(codes)` that reads only the requested `{code}_day.csv`
  files (plus their corporate-action rows), producing output identical to filtering
  `load_all()` down to the same codes.
- Add a local parquet build script (`scripts/build_price_parquet.py`) that consolidates
  all daily CSVs into `price_daily.parquet`, reusing the conversion logic already proven in
  `StockProject/dev_workflow/data_converter.py`. `DataLoader` already has a parquet fast
  path; this change makes the parquet file actually exist locally.
- Add a process-local cache for per-symbol price loads, keyed by file path + mtime, so
  repeated dashboard interactions (switching trades on the same symbol) do not re-read disk.
- Change `discover_tasks` to build/read a lightweight task index (metadata only: task id,
  title, generated_at) instead of parsing full `summary.json` bundles for every task at
  startup. Full `load_task_bundle` stays eager only for the task the user actually selects.
- Minor Panel-side readability fixes that ride along with this change: a loading indicator
  on the K-line pane while data loads, and column-width/contrast fixes on the capital-mode
  comparison tables. No layout redesign — that is out of scope (see `add-dashboard-v2`).

## Capabilities

### New Capabilities

(none — this change optimizes existing behavior without introducing a new capability
surface)

### Modified Capabilities

- `research-dashboard`: task discovery becomes lazy/metadata-first instead of eagerly
  loading every task bundle at startup; adds a loading-state requirement for the K-line
  pane.
- `research-trade-query`: price loading for a single symbol MUST NOT require reading the
  entire local price corpus.

## Non-Goals

- No change to corporate-action adjustment math (see `expand-corporate-action-adjustments`).
- No change to what data is shown, only how fast it loads — outputs for a given
  symbol/date range MUST be identical to the current `load_all()`-based path.
- No new frontend framework or visual redesign — that is `add-dashboard-v2`.
- Docker-backed execution is not required for local validation; note any skipped Docker
  checks in completion notes.

## Impact

- `StockProject/engine/data_loader.py`: new `load_symbols` method, parquet-aware path
  reuse.
- `scripts/stock_research_query.py`: `load_price_data` switches to `load_symbols` for
  single/few-symbol lookups.
- `research_lab/dashboard_core.py`: `discover_tasks` becomes metadata-first; loading
  indicator added around K-line rendering.
- New file: `scripts/build_price_parquet.py`.
- Tests: new parity tests proving `load_symbols(codes)` output matches
  `load_all()` filtered to the same codes.
