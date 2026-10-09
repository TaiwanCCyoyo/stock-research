## 1. Per-symbol loading (write parity tests first)

- [x] 1.1 Write a characterization test that runs `DataLoader.load_all()` for a small fixed
      set of codes and records the exact output (columns, dtypes, values) as the ground truth.
      (`tests/test_data_loader_symbols.py::test_load_all_characterization_with_corporate_action`)
- [x] 1.2 Implement `DataLoader.load_symbols(codes: list[str])` in
      `StockProject/engine/data_loader.py` that reads only the requested `{code}_day.csv`
      files and their corporate-action rows.
- [x] 1.3 Add a parity test asserting `load_symbols(codes)` output equals
      `load_all()` filtered to the same `codes`, for both a single symbol and a multi-symbol
      set, including at least one symbol with corporate-action events.
      Note: on the real heterogeneous corpus the only difference is `Volume` dtype
      (int64 per-file vs float64 promoted by the full-corpus concat when some files
      lack the column); values are numerically identical and no code in the repo
      reads `Volume`. Parity is therefore value-level, verified on real data.
- [x] 1.4 Add an in-process cache (path + mtime keyed) around per-symbol loads; add a test
      that a second call within the same process does not re-read the file (mock/spy on the
      file read) and that changing the file's mtime invalidates the cache.

## 2. Local parquet build

- [x] 2.1 Write `scripts/build_price_parquet.py`, writing to a local
      `shioaji_stock_prices/data/price_daily.parquet`. Note: instead of importing
      `StockProject/dev_workflow/data_converter.py` (whose paths are hardcoded to
      Docker mounts), the script reuses the engine's own `_read_day_csv` parser so
      parquet rows are exactly what `load_all()` would produce from CSVs.
- [x] 2.2 Add a staleness check in `DataLoader`'s parquet fast path: if any relevant source
      CSV has a newer mtime than the parquet file, fall back to the CSV path for that symbol
      (implemented as `_refresh_stale_symbols`, with a warning suggesting a rebuild).
- [x] 2.3 Add a test that `build_price_parquet.py` output matches `load_all()` for a sample
      of codes. (`tests/test_build_price_parquet.py`)
- [x] 2.4 Document the rebuild step (run after `run_daily.py`) in
      `shioaji_stock_prices/README.md`. Note: that path is a git submodule; the doc
      edit lives in the submodule worktree.

## 3. Wire `load_symbols` into the trade-query path

- [x] 3.1 Update `scripts/stock_research_query.py:load_price_data` to call
      `DataLoader.load_symbols` for the requested code(s) instead of `load_all()`.
- [x] 3.2 Confirm existing `tests/test_stock_research_query.py` still passes unchanged
      (output contract must not change).
- [x] 3.3 Add a timing assertion or smoke test showing a single-symbol load no longer scans
      the full data directory
      (`tests/test_stock_research_query.py::test_load_price_data_reads_only_requested_symbol_file`).

## 4. Lazy task discovery

- [x] 4.1 Add a lightweight task index (`discover_task_index()` in
      `research_lab/dashboard_core.py`) built from directory listing only — no
      summary.json parse — replacing `discover_tasks` for the server task selector.
- [x] 4.2 Keep `load_task_bundle` as the full loader, invoked only when a task is selected;
      the static site builder (`scripts/build_research_dashboard.py`) still uses the
      full `discover_tasks` since it renders per-task metric cards in batch.
      `make_trade_workbench` now takes only the selector and lazily loads the
      selected task's summary via the new `load_task_summary()`.
- [x] 4.3 Add a test that the task selector populates correctly with the lightweight index
      and that selecting a task still loads the full bundle correctly.
      (`tests/test_dashboard_task_index.py`)
- [x] 4.4 Staleness: the index is rebuilt from the directory listing on every call (it is a
      cheap listdir+stat, not a persisted file), so new/removed tasks and newer
      summaries are always reflected; covered by
      `test_discover_task_index_reflects_new_and_removed_tasks`.

## 5. Panel UI polish (small, ride-along)

- [x] 5.1 Add a loading indicator around the K-line pane while `load_price_data` runs
      (Panel global `loading_indicator=True`; the evidence pane shows a spinner during
      re-render — with the per-symbol cache, loads are now ~0.05–0.2s).
- [x] 5.2 Fix column widths/contrast on the capital-mode comparison tables: replaced the
      unstyled fixed-height `pn.pane.DataFrame` with a styled HTML table
      (`comparison_table_html` + `.capital-table` CSS: full width, padded cells,
      zebra rows, accent header, no clipped height).

## 6. Validation

- [x] 6.1 Run `uv run python -m pytest tests/ -q` — 109 passed (parity, cache, parquet,
      task-index, presentation tests all green).
- [x] 6.2 Run `uv run ruff check` on changed files — all checks passed.
- [x] 6.3 Manual E2E: user restarted `open_research_dashboard.cmd` and confirmed the
      dashboard looks correct; verified via live browser check (Playwright) that the index
      view renders, task switching is instant, the styled capital-mode comparison table
      renders with readable columns, and the K-line workbench renders candles + MA lines +
      buy/sell markers for the selected trade. Timing evidence: app build 2.9s (was eager
      parse + 76s `load_all` per K-line render); single-symbol load 0.19s cold / 0.05s cached.
- [x] 6.4 Re-run `tasks/sample`'s backtest with default parameters pre/post parquet build
      and diff run summaries — identical except `generated_at`/`run_id`/`output_path`
      (timestamps). `metrics` and `trades` byte-identical.
- [x] 6.5 Docker-backed verification skipped: all work targets local paths
      (`shioaji_stock_prices/data`); the Docker converter (`data_converter.py`) was not
      modified.
