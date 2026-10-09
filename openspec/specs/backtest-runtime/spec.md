# Backtest Runtime

## Purpose

Define the baseline behavior and artifact contract for running local or Docker-backed Taiwan stock strategy backtests.

## Requirements

### Requirement: Backtest CLI loads task-selected strategies dynamically

The backtest runtime MUST accept a strategy file path, load exactly one concrete `StrategyBase` subclass from that file, and fail clearly when no valid strategy class is available.

#### Scenario: Run a strategy file

- **WHEN** the user runs `StockProject/backtest_cli.py` with `--strategy`
- **THEN** the CLI MUST resolve the strategy path
- **AND** it MUST load a concrete subclass of `StrategyBase`
- **AND** it MUST reject missing files or files without a valid strategy class.

### Requirement: Backtest CLI accepts explicit research inputs

The backtest runtime MUST accept explicit symbols, date range, cash, benchmark symbol, data path, output path, and optional strategy parameters.

#### Scenario: Parse strategy parameters

- **WHEN** the CLI receives `--params-file`, `--params-json`, or both
- **THEN** it MUST merge the decoded JSON objects into the strategy context
- **AND** it MUST reject parameter inputs that do not decode to a JSON object.

#### Scenario: Select symbols and dates

- **WHEN** the CLI receives comma-separated `--codes`, `--start`, and optional `--end`
- **THEN** it MUST run the backtest only for the requested symbol list and date window.

### Requirement: Summary JSON exposes stable research metrics

The backtest runtime MUST write a stable summary contract for downstream agents, dashboards, and reports.

#### Scenario: Build summary metrics

- **WHEN** a backtest completes successfully
- **THEN** `summary.json` MUST include run metadata, strategy metadata, data paths, top-level metrics, benchmark data, price policy, per-symbol metrics, portfolio state, trades, and warnings
- **AND** metrics MUST include final value, total PnL, return rate, trade counts, win rate, max drawdown, benchmark return, and excess return.

#### Scenario: Include trade quality metrics

- **WHEN** closed trades exist
- **THEN** the summary metrics SHOULD include average win, average loss, payoff ratio, expectancy, gross profit, gross loss, profit factor, largest win, largest loss, and Calmar ratio when computable.

#### Scenario: No closed trades

- **WHEN** there are no closed trades
- **THEN** closed-trade statistics such as win rate, payoff ratio, expectancy, and profit factor MUST degrade to `null` rather than misleading numeric placeholders.

### Requirement: Benchmarks are explicit and comparable

The backtest runtime MUST include benchmark results that make the comparison method clear.

#### Scenario: Portfolio benchmark comparison

- **WHEN** a backtest summary is generated
- **THEN** it MUST include a market buy-and-hold benchmark for the configured benchmark symbol
- **AND** it SHOULD include stock-pool equal-allocation and odd-lot equal-allocation buy-and-hold references
- **AND** it MUST describe benchmark limitations and comparison method in the summary.

### Requirement: Docker-backed execution remains optional but supported

The repository MUST support Docker-backed Python backtests when execution isolation is useful, while allowing local verification when Docker is unavailable.

#### Scenario: Isolated research run

- **WHEN** Codex chooses Docker-backed execution for generated strategy code
- **THEN** the Docker service SHOULD mount engine code and local market data read-only
- **AND** it SHOULD write only task or report outputs to writable locations
- **AND** skipped Docker verification MUST be reported when Docker is unavailable.

### Requirement: A single command runs the strategy under all capital modes

The backtest runtime MUST support a `--capital-mode all` trigger that executes three
independent broker passes — `shared`, `per_stock`, and `unconstrained` — within a single
invocation, sharing one data-loading step across passes.

#### Scenario: Run all capital modes from one command

- **WHEN** the backtest CLI receives `--capital-mode all`
- **THEN** the runtime MUST load price and corporate-action data once
- **AND** it MUST execute three sequential passes, one per capital mode, each with its
  own independent broker and engine instance
- **AND** it MUST write Option-A artifacts on completion.

#### Scenario: Single-mode runs are unchanged

- **WHEN** the backtest CLI receives `--capital-mode shared`, `per_stock`, or
  `unconstrained`
- **THEN** behaviour MUST be identical to the pre-existing single-mode contract.

### Requirement: Backtests expose explicit capital allocation modes

The backtest runtime MUST support explicit capital allocation modes so research can
distinguish portfolio cash constraints from signal-only diagnostics.

#### Scenario: Use shared portfolio cash

- **WHEN** a backtest runs with `capital_mode` set to `shared`
- **THEN** all symbols MUST draw from and return proceeds to one shared cash pool
- **AND** buy orders MUST fail when the shared pool cannot cover the gross amount plus fees.

#### Scenario: Use per-symbol (`per_stock`) cash buckets

- **WHEN** a backtest runs with `capital_mode` set to `per_stock`
- **THEN** the initial cash MUST be split evenly across the selected symbol list
- **AND** each symbol MUST draw from and return proceeds to its own cash bucket
- **AND** one symbol's cash usage MUST NOT prevent another symbol from buying with its
  own remaining bucket.

#### Scenario: Use unconstrained diagnostic capital

- **WHEN** a backtest runs with `capital_mode` set to `unconstrained`
- **THEN** buy orders MUST be allowed even when cash would become negative
- **AND** the summary MUST still expose resulting cash, portfolio state, and
  scale-independent trade-quality metrics for diagnostics.

#### Scenario: Reject unknown capital mode

- **WHEN** a caller supplies an unknown capital mode string
- **THEN** the runtime MUST fail clearly before executing the backtest.

#### Scenario: Empty or unlisted symbol code in per_stock mode

- **WHEN** `capital_mode` is `per_stock` and the `codes` list is empty
- **THEN** the runtime MUST NOT divide by zero; it MUST treat the per-symbol bucket as
  equal to `initial_cash`.

### Requirement: Unconstrained mode suppresses capital-scale-dependent metrics

The backtest runtime MUST suppress return-based metrics when `capital_mode` is
`unconstrained`, because `initial_cash` is not a real constraint in that mode.

#### Scenario: Null return metrics for unconstrained mode

- **WHEN** a backtest summary is generated for `unconstrained` mode
- **THEN** `summary.metrics.return_rate` MUST be `null`
- **AND** `calmar_ratio`, `max_drawdown_rate`, and all `excess_return_rate` variants MUST
  be `null`
- **AND** per-symbol `excess_return_rate` and `odd_lot_excess_return_rate` MUST be `null`.

#### Scenario: Keep scale-independent metrics for unconstrained mode

- **WHEN** a backtest summary is generated for `unconstrained` mode
- **THEN** `win_rate`, `payoff_ratio`, `expectancy`, `profit_factor`, `avg_win`,
  `avg_loss`, `largest_win`, `largest_loss`, `gross_profit`, `gross_loss`, and all trade
  counts MUST still be reported.

### Requirement: Cash-blocked entry count is recorded per mode

The summary MUST expose how many entry intents were suppressed by insufficient cash, so
researchers can quantify capital contention directly.

#### Scenario: Count cash-blocked entries

- **WHEN** a backtest completes
- **THEN** `summary.metrics.cash_blocked_entry_count` MUST equal the number of buy
  attempts that were skipped or rejected solely because available cash was insufficient.

#### Scenario: Unconstrained mode has zero cash-blocked entries

- **WHEN** a backtest runs with `capital_mode` set to `unconstrained`
- **THEN** `cash_blocked_entry_count` MUST be 0, because no buy is ever blocked by cash.

### Requirement: Backtest summaries record capital mode metadata

The backtest runtime MUST record the selected capital mode in summary artifacts so
dashboards, reports, and trade-query tooling can interpret cash values correctly.

#### Scenario: Record selected mode

- **WHEN** a backtest summary is generated
- **THEN** `summary.json` MUST include `run.capital_mode`.

#### Scenario: Record per-symbol initial cash

- **WHEN** a backtest summary is generated for `per_stock` mode
- **THEN** `summary.json` MUST include `run.per_stock_initial_cash`
- **AND** that value MUST represent the initial cash assigned to each selected symbol bucket.

### Requirement: Comparison runs write Option-A artifacts

A `--capital-mode all` run MUST produce a complete, independently-queryable artifact for
each mode plus a thin cross-mode comparison file.

#### Scenario: Write per-mode summaries

- **WHEN** a `--capital-mode all` run completes successfully
- **THEN** the output directory MUST contain `summary_shared.json`,
  `summary_per_stock.json`, and `summary_unconstrained.json`
- **AND** each file MUST conform to the full summary schema (same as a single-mode run).

#### Scenario: Write comparison artifact

- **WHEN** a `--capital-mode all` run completes successfully
- **THEN** the output directory MUST contain `comparison.json` with per-mode headline
  metrics and a per-symbol contention view
- **AND** symbols whose `total_pnl` is negative under `shared` but non-negative under
  `per_stock` MUST be flagged as contention-affected.

#### Scenario: Backward-compatible summary.json

- **WHEN** a `--capital-mode all` run completes successfully
- **THEN** `summary.json` MUST equal `summary_shared.json`
- **AND** existing trade-query, dashboard, and diagnosis tooling that reads only
  `summary.json` MUST continue to work without modification.

### Requirement: Task wrappers preserve capital mode

Task-level backtest and parameter sweep wrappers MUST pass the selected capital mode —
including `all` — to the core backtest runtime.

#### Scenario: Run a task backtest with a capital mode

- **WHEN** `scripts/run_task_backtest.py` receives `--capital-mode`
- **THEN** it MUST pass the same value to `StockProject/backtest_cli.py`.

#### Scenario: Run a parameter sweep with a capital mode

- **WHEN** `scripts/run_task_param_sweep.py` receives `--capital-mode`
- **THEN** every generated run MUST use that same capital mode.

### Requirement: Partial data gaps within the backtest window are reported separately from fully missing symbols

The backtest runtime MUST distinguish a symbol with no local data at all from a symbol whose local data has significant gaps within the requested date range.

#### Scenario: Symbol has significant partial gaps

- **WHEN** a requested symbol has local data but is missing more than a configurable
  threshold of trading days within the backtest's start/end window
- **THEN** `summary.json` MUST include that symbol in a `partial_data_symbols` warning list
- **AND** the backtest MUST still complete using the available rows rather than failing.

#### Scenario: Symbol has no meaningful gaps

- **WHEN** a requested symbol's local data covers the backtest window without exceeding the
  gap threshold
- **THEN** that symbol MUST NOT appear in `partial_data_symbols`.
