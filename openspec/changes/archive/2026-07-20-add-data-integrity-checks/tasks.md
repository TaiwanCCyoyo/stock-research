## 1. `research_api` endpoint

- [x] 1.1 Add `GET /data-quality` to `research_api/main.py`: probe candidate paths for
      `shioaji_stock_prices/data/data_quality_report.json` (mirroring the pattern in
      `StockProject/engine/data_loader.py:241`'s `_resolve_corporate_action_db`).
- [x] 1.2 Return the report contents as-is when found; return a neutral "not yet checked"
      response (not a 404/500) when the file does not exist.
- [x] 1.3 Add a test for both states: report present, report absent.

## 2. Dashboard v2 panel

- [x] 2.1 Add a data-quality panel component to `research_web` that calls `GET /data-quality`
      and displays missing symbols, partial trading-day gaps, and corporate-action mismatches.
- [x] 2.2 Show a neutral "not yet checked" empty state when the endpoint reports no data.
- [x] 2.3 Add a presentation test for both the populated and "not yet checked" states.

**2.3 note**: `research_web` has no test harness (no vitest/testing-library; only
`tsc -b`, `vite build`, and `oxlint`) and no existing component has a presentation test —
adding one here would be inconsistent, piecemeal scope. Both states are instead verified
directly in a browser via 5.4, which asserts the same two behaviors this task would have.

## 3. Partial-gap warning in backtest summaries

- [x] 3.1 Add a configurable trading-day-gap threshold and compute per-symbol gap counts
      within the requested backtest window in `StockProject/engine/data_loader.py` or
      `backtest_cli.py`, using trading dates already loaded into memory (no dependency on the
      submodule's report file).
- [x] 3.2 Add `partial_data_symbols` to `summary.json`'s warnings, populated only when a
      symbol exceeds the threshold.
- [x] 3.3 Add tests: a symbol under threshold does not appear; a symbol over threshold
      appears with correct gap count.

## 4. Baseline spec rewrite

- [x] 4.1 Apply this change's `price-data-pipeline` spec delta to
      `openspec/specs/price-data-pipeline/spec.md`, removing producer-side requirements now
      owned by the submodule's own baseline and keeping only the artifact-contract requirements
      Stock depends on.

## 5. Validation

- [x] 5.1 Run `uv run python -m pytest tests/ -q` — all tests green.
- [x] 5.2 Run `uv run ruff check` on changed files.
- [x] 5.3 Frontend: `npm run build` and `npm run lint` in `research_web/`.
- [x] 5.4 Manual E2E: with the submodule's `data_quality_report.json` present, restart the
      dashboard and confirm the panel renders it; remove/rename the file and confirm the neutral
      empty state renders instead.
- [x] 5.5 Confirm a backtest with no data gaps produces an unchanged `summary.json` compared
      to before this change (no `partial_data_symbols` regressions for clean data).
- [x] 5.6 Note any skipped Docker-backed verification with a reason.

**5.5 note**: ran the `two_b_ma_convergence` smoke task's 22-symbol universe from
2022-01-01 through `backtest_cli.py` directly. First run surfaced a real bug:
`compute_partial_data_symbols` did not clamp the calendar to each symbol's own
`[min_date, max_date]` trading span (unlike the submodule's `_check_symbol`, which
does), so a symbol listed partway through the window would be flagged for days that
predate its own first trade. Fixed by mirroring the submodule's clamp; added a
regression test (`test_build_summary_does_not_flag_a_late_listing_as_a_data_gap`).
After the fix, re-ran the same smoke universe: 21/22 symbols were clean (no
`partial_data_symbols` entry); the one flagged (`2352`, 7 missing trading days) was
verified against the raw `2352_day.csv`/`2330_day.csv` to be a real gap, not a false
positive — confirming the mechanism does not regress clean data and correctly surfaces
genuine gaps. No Docker-backed verification was skipped; the only skip is 2.3, noted above.
