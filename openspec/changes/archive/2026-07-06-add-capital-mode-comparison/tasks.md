# Tasks

## Pre-existing (already committed to main -- no implementation needed)

- [x] Add `--capital-mode` CLI option to the core backtest runtime with values `shared`,
      `per_stock`, and `unconstrained`. (`StockProject/backtest_cli.py`)
- [x] Implement broker cash handling for shared pool, per-symbol buckets, and unconstrained
      buys. (`StockProject/engine/broker.py`)
- [x] Update strategy affordable-lot helpers so per-symbol cash buckets are used when the
      broker runs in `per_stock` mode. (`StockProject/engine/strategy_base.py`)
- [x] Pass `--capital-mode` through task backtest and parameter sweep wrappers.
      (`scripts/run_task_backtest.py`, `scripts/run_task_param_sweep.py`)
- [x] Persist `run.capital_mode` in `summary.json` run metadata.
- [x] Persist `run.per_stock_initial_cash` when `per_stock` mode is used.
- [x] Implement per-symbol cash context in trade-query (`cash_context` in
      `scripts/stock_research_query.py`). Logic was committed before this change; this change
      activates it end-to-end and adds regression tests.

## Implementation -- new work

- [x] Add `cash_blocked_entry_count` counter to `Broker` and increment it at the two cash
      gate points: `broker.buy` rejection and `buy_affordable_lot` qty=0. Surface the counter
      in `summary.metrics`.
- [x] Extend `--capital-mode` choices to include `all`; implement the three-pass runner in
      `backtest_cli.py` that shares a single data-loading pass across modes.
- [x] Implement unconstrained null-return rule in `build_summary`: set `return_rate`,
      `calmar_ratio`, `max_drawdown_rate`, and all `excess_return_rate` variants to `null`
      when `capital_mode == "unconstrained"`.
- [x] Write Option-A artifacts after a comparison run: `summary_shared.json`,
      `summary_per_stock.json`, `summary_unconstrained.json`, `comparison.json`, and update
      `summary.json` to equal the shared result.
- [x] Build `comparison.json`: headline metrics per mode + per-symbol contention view
      (flag symbols that flip from loss under `shared` to profit under `per_stock`).
- [x] Pass `--capital-mode all` through `run_task_backtest.py` and
      `run_task_param_sweep.py`.
- [x] Add `capital_mode_comparison_rows` and `capital_mode_comparison_panel` to
      `research_lab/dashboard_core.py`. Extend `load_task_bundle` to load `comparison.json`
      and wire the panel into `build_task_view`.

## Validation

- [x] Run `uv run pytest tests/test_broker_capital_modes.py` -- add tests for
      `cash_blocked_entry_count` and confirm existing tests pass.
- [x] Run `uv run pytest tests/test_stock_research_query.py` -- add regression tests for
      `per_stock` and `unconstrained` cash context using per-mode summary fixtures.
- [x] Add tests for unconstrained null-return rule in `build_summary`.
- [x] Add tests for Option-A artifact emission (assert four files written + `summary.json`
      equals shared content).
- [x] Add wrapper tests for `--capital-mode all` propagation (currently no wrapper test
      exists).
- [x] Add dashboard tests: `capital_mode_comparison_rows` pure-fn + panel `None`/`pn.Column`
      contract (use escaped `\uXXXX` CJK in test assertions, matching existing test conventions).
- [x] End-to-end run on `tasks/sample` with `--capital-mode all`; inspect JSON files and
      build dashboard.
- [x] For any skipped Docker-backed checks, record why in completion notes.

## Implementation -- dashboard enhancement (round 2)

- [x] Extend `load_task_bundle` to load `summary_shared.json`, `summary_per_stock.json`,
      and `summary_unconstrained.json` into a `mode_summaries` map.
- [x] Add pure `capital_mode_pool_verdict(mode, summary_mode)` reusing `_strategy_verdict`
      and `strategy_health_verdict`; unconstrained returns a signal-quality-only verdict.
- [x] Add pure `capital_mode_comparative_verdict(comparison, mode_summaries=None)` that
      compares shared vs per_stock and emits one of: capital-allocation bottleneck
      (recommend a future "未賣出但需換股" rotation strategy) / pools-similar / signal-quality.
- [x] Add `capital_mode_pool_tab(mode, summary_mode)` reusing `metrics_row`,
      `strategy_health_panel`, `make_equity_drawdown_figure`, plus a debug block.
- [x] Add `capital_mode_tabs_panel(bundle)` returning `pn.Tabs` (比較總覽 + 3 pool tabs)
      or `None`; fill the comparison table's `max_drawdown_rate` from per-mode summaries.
- [x] Wire `capital_mode_tabs_panel` into `build_task_view`, replacing
      `capital_mode_comparison_panel`; keep single-mode behaviour unchanged.
- [x] Add `build_help_view()` (Traditional Chinese, raw UTF-8) documenting artifact
      locations and re-run commands (`run_task_backtest --capital-mode all`, param sweep,
      dashboard serve), including a 2b example and the `--data-path` caveat.
- [x] In `dashboard_app.py` `build_server_app`: remove `sidebar_artifacts`; add
      "回測分析 / 使用說明" sidebar toggle buttons that swap `main_content.objects`; keep
      task select and shutdown button.
- [x] Remove the "## 本地 Artifacts" link block from `build_task_view`
      (keep `artifact_link_targets` function intact for existing tests).

## Validation (round 2)

- [x] `uv run python -m pytest tests/test_dashboard_presentation.py` — add tests for
      `capital_mode_comparative_verdict` (shared-bad/per_stock-good rotation case + two reverse
      cases), `capital_mode_pool_verdict` (unconstrained null case), `capital_mode_tabs_panel`
      (`None` vs `pn.Tabs` with four tabs), and `build_help_view` (contains `run_task_backtest`,
      `--capital-mode all`, `tasks/`). Keep `\uXXXX` CJK assertions.
- [x] Keep `test_capital_mode_comparison_rows_formats_required_metrics` and
      `test_artifact_links_use_different_targets...` green (new params default-compatible;
      `artifact_link_targets` retained).
- [x] `uv run ruff check` + `uv run mypy` on the two dashboard files.
- [x] `uv run python -m scripts.build_research_dashboard` — static build still succeeds.
- [x] Manual E2E on `tasks/sample` at `http://localhost:8502/dashboard_app`: four pool
      sub-tabs with metrics/health/equity/debug, cross-pool verdict text, max-drawdown no longer
      `n/a`; sidebar shows only task select + 回測分析/使用說明 toggle + shutdown; help view lists
      data locations and copyable re-run commands.
