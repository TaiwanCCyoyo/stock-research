# Add Capital-Mode Comparison Backtest

## Why

Multi-symbol backtests currently use one shared cash pool, so an early buy in one symbol
can prevent a valid signal in another from executing. This makes it impossible to tell
whether a weak result reflects a **bad strategy signal** or merely **capital contention**
between symbols.

A single command should run the same strategy under three capital regimes, produce full
per-mode artifacts, and surface a side-by-side comparison on the dashboard — so a
researcher can see, for example, that a symbol loses under `shared` but is fine under
`per_stock` and conclude the strategy signal is sound but capital allocation is the
bottleneck.

## What Changes

### Engine — single-command multi-pass runner

A new `--capital-mode all` trigger runs the backtest three times in one invocation,
sharing a single data-loading pass across modes: `shared`, `per_stock`, and
`unconstrained`. Each pass gets its own independent broker and engine instance.

A `cash_blocked_entry_count` metric is added to each summary, counting the number of
entry intents suppressed by insufficient cash. This is ~0 under `unconstrained` and
higher under `shared`, making capital contention directly measurable.

### Capital modes (broker already implemented; this change activates multi-pass)

- `shared` — one pool for all symbols (current default behaviour).
- `per_stock` — initial cash split evenly per symbol; buckets are isolated so one symbol
  cannot starve another.
- `unconstrained` — no cash gate; buys always succeed even if cash goes negative
  (signal-quality diagnostic only).

### Unconstrained return semantics

`unconstrained` mode reports `null` for all capital-scale-dependent metrics because
`initial_cash` is arbitrary when capital is unbounded:

- Nulled: `return_rate`, `calmar_ratio`, `max_drawdown_rate`, all `excess_return_rate`
  variants, and per-symbol excess returns.
- Kept (scale-independent): `win_rate`, `payoff_ratio`, `expectancy`, `profit_factor`,
  `avg_win/loss`, `largest_win/loss`, `gross_profit/loss`, trade counts.

### Artifacts — Option A (three full summaries + comparison)

Under `tasks/<id>/`, a `--capital-mode all` run writes:

- `summary_shared.json` — full summary for `shared` mode.
- `summary_per_stock.json` — full summary for `per_stock` mode.
- `summary_unconstrained.json` — full summary for `unconstrained` mode (return fields null).
- `comparison.json` — thin cross-mode table: headline metrics per mode + per-symbol
  contention view (flags symbols whose PnL flips from loss under `shared` to profit under
  `per_stock`).
- `summary.json` — set equal to `summary_shared.json` for backward compatibility with
  trade-query, dashboard, and diagnosis tooling.

### Trade query

`cash_context` in `scripts/stock_research_query.py` already handles `per_stock` mode
(logic was committed before this change). This change activates that path end-to-end by
producing the per-mode summary files and locks the behaviour with regression tests.

### Dashboard

A new capital-mode comparison panel in `research_lab/dashboard_core.py` shows the three
modes side by side. It follows the existing `strategy_health_panel` pattern (pure data
function + thin panel builder). The panel appears only when `comparison.json` is present,
so single-mode runs are unaffected.

### Wrappers

`scripts/run_task_backtest.py` and `scripts/run_task_param_sweep.py` accept and pass
through `--capital-mode all`.

### Dashboard — round 2 (per-pool sub-tabs, judgments, help view)

The first-round comparison panel is a single flat table embedded in the scrolling task
view; it never reads the per-mode summaries and produces no interpretation. Round 2:

- Load `summary_shared.json` / `summary_per_stock.json` / `summary_unconstrained.json`
  (already written on disk, currently unread) in `load_task_bundle`.
- Replace the flat panel with a `pn.Tabs` group: "比較總覽" + one tab per pool
  (shared / per_stock / unconstrained). Each pool tab reuses the existing
  `metrics_row` / `strategy_health_panel` / `make_equity_drawdown_figure` builders plus a
  debug block (`cash_blocked_entry_count`, contention-affected symbols). The unconstrained
  tab marks null return fields as signal-quality-only.
- Add per-pool verdicts and a cross-pool comparative verdict (pure, testable). The
  comparative verdict reads `contention_affected` + `cash_blocked_entry_count` and compares
  `shared` vs `per_stock` return to conclude whether the bottleneck is capital allocation
  (and recommend a future "未賣出但需換股" rotation strategy) or signal quality.
- Fix the existing bug where the comparison table's `max_drawdown_rate` is always `n/a`
  (the key is absent from `comparison.json.modes`; read it from the per-mode summaries).
- Add a usage/help view (`build_help_view`) explaining where task artifacts live and the
  exact CLI commands to re-run a backtest; surface it via a sidebar toggle
  (回測分析 / 使用說明). Remove the raw html/json artifact links from the sidebar and the
  task body; list file locations as text in the help view instead.

GUI re-run buttons are explicitly out of scope for this round (the help view documents the
CLI commands only).

## Non-Goals

- No real trading, broker integration, order placement, or investment advice.
- No intra-backtest capital reallocation or "rotate before exit" stock-switching — this is
  a future research direction.
- No portfolio optimization or position sizing.
- No change to the corporate-action price policy; execution prices, dividends, splits, and
  capital reductions remain governed by existing specs.
- Docker-backed execution is not required for local validation; skipped Docker checks must
  be noted in completion notes.

## Verification

- `openspec validate --all --strict` passes.
- `uv run python -m pytest tests/test_broker_capital_modes.py tests/test_stock_research_query.py` stays green.
- New tests cover: `cash_blocked_entry_count` counting; unconstrained null-return rule;
  Option-A artifact emission (four files + `summary.json`=shared); `--capital-mode all`
  wrapper propagation; dashboard comparison panel `None`/`pn.Column` contract.
- End-to-end on `tasks/sample`: run with `--capital-mode all`, inspect the four JSON
  files, confirm `unconstrained` return fields are null and trade-quality metrics present,
  build dashboard and confirm comparison panel renders.
- Verify trade-query works against `summary_per_stock.json` and
  `summary_unconstrained.json` via `inspect_task_trade`.
- Round-2 dashboard: per-pool `pn.Tabs` render for `tasks/sample`; per-pool and cross-pool
  verdict pure functions covered by unit tests (including the "shared bad / per_stock good"
  rotation-suggestion case); `build_help_view` contains the re-run command and `tasks/`
  path; sidebar no longer shows raw artifact links; single-mode tasks render unchanged.
