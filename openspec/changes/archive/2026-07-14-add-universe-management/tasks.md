## 1. Classification metadata

- [x] 1.1 Identify the TWSE/TPEx ISIN public data source(s) for industry category, market,
      ETF flag, and listing date.
- [x] 1.2 Implement a fetcher writing `shioaji_stock_prices/data/symbol_meta.sqlite`
      (or documented equivalent), recording a fetch timestamp.
- [x] 1.3 Add a lookup helper for querying classification by code, returning an explicit
      "no data" result for unknown symbols.
- [x] 1.4 Add tests for the fetcher (fixture response → expected rows) and the lookup
      helper (known symbol, unknown symbol).

## 2. Universe definitions

- [x] 2.1 Define the `universes/*.json` schema (explicit `codes` list vs. `rule`-based).
- [x] 2.2 Implement universe resolution: explicit-code universes return their list directly;
      rule-based universes query `symbol_meta.sqlite` at resolution time.
- [x] 2.3 Add at least two example universe files matching real classification data (e.g.
      one explicit-code, one rule-based) for validation.
- [x] 2.4 Add tests for both resolution paths, including an unknown-universe-name failure
      case.

## 3. CLI integration

- [x] 3.1 Add `@universe-name` parsing to `--codes` in `StockProject/backtest_cli.py`,
      resolving before the existing comma-split logic runs.
- [x] 3.2 Propagate the same support through `scripts/run_task_backtest.py` and
      `scripts/create_research_task.py`.
- [x] 3.3 Record the resolved code list (and universe name, if used) in `summary.json` run
      metadata for reproducibility.
- [x] 3.4 Add tests: `@universe` resolves correctly; plain comma-separated codes are
      unaffected; unknown universe name fails clearly before running.

## 4. Multi-universe comparison mode

- [x] 4.1 Add a `--universes` (or repeated `@universe`) batch mode to `backtest_cli.py`,
      reusing `build_capital_mode_comparison`/`write_comparison_artifacts`'s Option-A pattern:
      one full `summary_<universe>.json` per universe, plus `comparison.json`.
- [x] 4.2 Alias `summary.json` to a designated default universe's result for backward
      compatibility.
- [x] 4.3 Add tests mirroring the existing capital-mode comparison tests: artifact emission,
      `summary.json` aliasing, and headline metrics in `comparison.json`.

## 5. Dashboard filtering

- [x] 5.1 Add an industry filter to the stock-ranking view. The React dashboard
      (`research_web/`) had no ranking view at all (rankings were fetched but never
      rendered); built a new `RankingTable` component + tab, backed by a pure
      `rankings_with_classification` helper in `research_lab/dashboard_core.py`.
- [x] 5.2 Display the universe name (when present) alongside task run metadata.
- [x] 5.3 Add presentation tests for the filter and universe-name display
      (Python: `tests/test_symbol_classification.py`; frontend has no test harness,
      so the new component was verified via `npm run build`/`lint` and a live API
      payload check instead).

## 6. Validation

- [x] 6.1 Run `uv run python -m pytest tests/ -q` — all tests green (216 passed).
- [x] 6.2 Run `uv run ruff check` on new/changed files — all clean. The submodule's
      `fetch_symbol_meta.py`/`test_fetch_symbol_meta.py` fail the main repo's `T201`
      no-`print()` rule when linted with the main repo's `ruff.toml`, matching the
      pre-existing `fetch_corporate_actions.py` in the same submodule (no `ruff.toml`
      there; print-based CLI output is that submodule's existing convention).
- [x] 6.3 Manual E2E: ran the backtest with `--codes @core_blue_chips` and with the
      equivalent explicit `--codes 2330,2317,2454,0050` — resulting `summary.json` files
      are identical except for the `output_path` string.
- [x] 6.4 Manual E2E: ran `--universes semiconductor,core_blue_chips`, inspected
      `summary_<universe>.json` + `comparison.json` (headline metrics per universe,
      `codes` list per universe), and confirmed via a live `/tasks/{id}` API response that
      the dashboard payload carries `run.universe` and per-row `industry_category`. Could
      not click through the React UI itself — the Chrome extension used for browser
      automation was not connected in this environment — but `npm run build`/`lint`
      passed and the API payload shape was verified directly.
- [x] 6.5 Confirmed existing plain `--codes` comma-list usage is unaffected: the
      explicit-codes run in 6.3 used the new `resolve_codes()` path and matched the
      universe-resolved run byte-for-byte, showing the plain-codes branch is unchanged.
- [x] 6.6 No Docker-backed verification was skipped; all checks ran locally via
      `uv run` per this repo's existing (non-Docker) local research workflow.
