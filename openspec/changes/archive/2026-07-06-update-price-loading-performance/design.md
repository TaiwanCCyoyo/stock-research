## Context

`StockProject/engine/data_loader.py`'s `DataLoader.load_all()` globs every `*_day.csv` in
the data directory and reads them all with `pandas.read_csv`, regardless of how many
symbols the caller actually needs. This is correct for a full backtest across the universe,
but the dashboard's K-line/trade-drilldown path (`scripts/stock_research_query.py:load_price_data`)
only ever needs one or a handful of symbols per render, and pays the full-corpus cost every
time. Separately, `research_lab/dashboard_core.py:discover_tasks` parses every task's full
`summary.json` (and sibling files) at server startup just to populate the task-selector
dropdown, when only the id/title/timestamp are needed until a task is actually opened.

A `price_daily.parquet` fast path already exists in `DataLoader` (built for the Docker
pipeline via `StockProject/dev_workflow/data_converter.py`), but no local script produces
that file for the non-Docker workflow, so the CSV-glob path is what actually runs today.

## Goals / Non-Goals

**Goals:**

- Make single/few-symbol price loads scale with the number of requested symbols, not the
  size of the full local corpus.
- Make dashboard startup scale with the number of tasks' metadata, not the size of every
  task's full artifact bundle.
- Keep output values byte-for-byte identical to the current path for any given
  symbol/date range — this is a performance change, not a behavior change.
- Produce a reusable fast-path that `add-research-api`'s FastAPI backend can call directly.

**Non-Goals:**

- Do not change corporate-action adjustment math, warnings, or the price policy contract.
- Do not introduce a persistent server-side cache, background refresh daemon, or database
  server — an in-process cache and a locally-built parquet file are sufficient for a
  single-user research tool.
- Do not redesign dashboard layout or visuals.

## Decisions

**1. `load_symbols(codes)` reads individual CSVs directly rather than filtering a
pre-loaded `load_all()` DataFrame.**
Rationale: filtering after a full load defeats the purpose. Reading only the requested
`{code}_day.csv` files (and joining only the relevant corporate-action rows) bounds cost by
`len(codes)`. Alternative considered: always require the parquet file and drop CSV support
— rejected because the parquet file may be stale or missing right after a daily data
refresh, and CSVs remain the authoritative per-symbol source of truth.

**2. Parquet is a cache, not a new source of truth.**
`scripts/build_price_parquet.py` is a local build step (analogous to
`StockProject/dev_workflow/data_converter.py`) invoked after `run_daily.py`. `DataLoader`
already prefers parquet when present and falls back to CSV; this change only ensures the
file exists for local (non-Docker) runs. Alternative considered: switch daily storage to
parquet directly — rejected as a larger migration with no clear benefit over CSV +
generated parquet cache for this project's scale.

**3. In-process cache keyed by `(path, mtime)`.**
A simple `functools.lru_cache`-style or dict cache keyed on file path and modification time
avoids serving stale data after `run_daily.py` updates a CSV, without needing explicit
invalidation logic. Alternative considered: time-based TTL — rejected because mtime-keying
is simpler and exactly correct for this access pattern (files change only via the daily
pipeline).

**4. Task discovery becomes two-tier: lightweight index first, full bundle on demand.**
`discover_tasks` reads or builds a small `tasks/_index.json`-equivalent (id, title,
generated_at) for the dropdown; `load_task_bundle` (already implemented) remains the full
loader, called only when a task is selected. Alternative considered: lazy-load everything
via Panel's reactive graph without an index file — rejected because the dropdown itself
needs enough metadata (title, freshness) to be useful before selection.

## Risks / Trade-offs

- [Risk] Parquet cache goes stale if `build_price_parquet.py` isn't rerun after new data
  arrives → Mitigation: `DataLoader` compares parquet mtime against source CSV mtimes and
  falls back to CSV-glob when the parquet is older than any relevant CSV; document the
  rebuild step in `run_daily.py`'s follow-up steps.
- [Risk] Task index file drifts from actual task directory contents (task added/removed
  without index rebuild) → Mitigation: rebuild the index whenever its mtime is older than
  the `tasks/` directory listing, same pattern as the parquet staleness check.
- [Risk] In-process cache grows unbounded over a long-running dashboard session →
  Mitigation: bound cache size (e.g. `maxsize` on the memoization) since the corpus is
  ~2,000 symbols at most and each entry is small.

## Migration Plan

- Additive only: `load_symbols`, the parquet build script, and the task index are new
  code paths that existing callers do not depend on until wired in. `load_price_data` and
  `discover_tasks` are updated to use the new paths behind unchanged public signatures, so
  no caller elsewhere in the repo needs to change.
- Rollback: revert the two call-site changes (`load_price_data`, `discover_tasks`); the new
  helper functions can remain unused without harm.
