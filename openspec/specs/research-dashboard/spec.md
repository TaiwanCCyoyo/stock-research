# Research Dashboard

## Purpose

Define the baseline local dashboard behavior for discovering research tasks, rendering results, verifying trades, and presenting strategy health.

## Requirements

### Requirement: Dashboard builds from local task artifacts

The local research dashboard MUST discover task artifacts under `tasks/` and render static or interactive views without requiring Notion as a source of truth, and MUST discover the task list without parsing every task's full artifact bundle up front.

#### Scenario: Build static dashboard

- **WHEN** `scripts/build_research_dashboard.py` runs
- **THEN** it MUST create an index page
- **AND** it MUST create task pages for discoverable tasks
- **AND** links in static pages MUST target local task artifacts.

#### Scenario: Serve interactive dashboard

- **WHEN** the dashboard is used in server mode
- **THEN** artifact links MUST route through server artifact endpoints rather than static relative paths.

#### Scenario: Discover tasks without an eager full-bundle load

- **WHEN** the dashboard server starts and populates the task selector
- **THEN** task discovery MUST read only lightweight metadata (task id, title, generated
  timestamp) for tasks that are not yet selected
- **AND** a task's full artifact bundle (summaries, rankings, signal events, comparison
  data) MUST be loaded only when that task is selected for viewing.

#### Scenario: Show loading state while K-line data loads

- **WHEN** a user selects a symbol or trade whose price data has not yet been loaded
- **THEN** the K-line pane MUST show a loading indicator until the chart renders
- **AND** it MUST NOT appear frozen or blank with no feedback during the load.

### Requirement: Dashboard presents strategy results in user-facing language

The dashboard MUST translate internal signal, corporate action, and trade action codes into user-facing Traditional Chinese labels.

#### Scenario: Render trade table

- **WHEN** trades are displayed for a task
- **THEN** trade dates MUST be shown without time noise
- **AND** actions, stock labels, prices, quantities, and totals MUST be formatted for review.

#### Scenario: Render signal labels

- **WHEN** signal reasons or signal price policy codes appear in task artifacts
- **THEN** the dashboard MUST translate known codes into user-facing labels.

### Requirement: Dashboard provides strategy health diagnostics

The dashboard MUST present health metrics for closed-trade strategies and degrade gracefully when metrics are unavailable.

#### Scenario: Health metrics available

- **WHEN** summary metrics include closed trades and trade-quality fields
- **THEN** the dashboard SHOULD show payoff ratio, expectancy, profit factor, Calmar ratio, average win, average loss, largest win, largest loss, and a verdict.

#### Scenario: Passive or non-closing strategy

- **WHEN** a strategy does not produce closed trades for active-trading health analysis
- **THEN** the dashboard MUST not show an active-trading health panel
- **AND** win rate SHOULD be shown as not applicable rather than as a missing value.

#### Scenario: Diagnosis report exists

- **WHEN** a non-empty `strategy_diagnosis.md` exists for a task
- **THEN** the dashboard SHOULD render the diagnosis panel
- **AND** it MUST omit that panel for empty or whitespace-only diagnosis content.

### Requirement: Trade verification supports strategy-specific context

The dashboard MUST select trade verification views that match the strategy type and available artifacts.

#### Scenario: Verify trade with matching context

- **WHEN** a task strategy has a recognized verification mode
- **THEN** the dashboard MUST use the verification mode that matches the strategy type and available artifacts
- **AND** it MUST not claim to show unavailable strategy-specific context.

#### Scenario: Verify trade with optional technical fields

- **WHEN** a verification view uses configurable technical fields such as moving-average windows
- **THEN** the dashboard SHOULD render the configured fields when available
- **AND** missing values MUST display as `n/a` rather than causing rendering errors.

#### Scenario: Existing verification examples

- **WHEN** current task artifacts use simple buy-and-hold or 2B moving-average convergence strategies
- **THEN** those strategies MAY be used as examples of recognized verification modes
- **AND** the stable dashboard contract MUST remain strategy-agnostic for future task-local experiments.

### Requirement: Dashboard shows capital-mode comparison when available

The dashboard MUST surface a capital-mode comparison panel when a task has been run with
`--capital-mode all`, so a researcher can diagnose capital contention without inspecting
raw JSON files.

#### Scenario: Render comparison panel

- **WHEN** `comparison.json` is present in the task directory
- **THEN** the task view MUST include a capital-mode comparison panel showing `shared`,
  `per_stock`, and `unconstrained` results side by side
- **AND** the panel MUST display at minimum: `return_rate` (null for unconstrained),
  `win_rate`, `payoff_ratio`, `expectancy`, and `cash_blocked_entry_count` per mode.

#### Scenario: Omit panel for single-mode runs

- **WHEN** `comparison.json` is absent (single-mode run)
- **THEN** the task view MUST render without the comparison panel and without errors.

#### Scenario: Flag contention-affected symbols

- **WHEN** the comparison panel renders
- **THEN** symbols identified in `comparison.json` as contention-affected (negative PnL
  under `shared`, non-negative under `per_stock`) MUST be highlighted so the researcher
  can see which symbols benefit from capital isolation.

### Requirement: Comparison panel follows the existing testability pattern

The comparison panel helpers MUST be structured so they can be tested without rendering.

#### Scenario: Pure data function is independently testable

- **WHEN** `capital_mode_comparison_rows(comparison)` is called with a `comparison.json`
  dict
- **THEN** it MUST return formatted metric rows without importing or invoking Panel.

#### Scenario: Panel builder returns None for missing data

- **WHEN** `capital_mode_comparison_panel(None)` or an empty dict is passed
- **THEN** the function MUST return `None`.

### Requirement: Capital-mode results render as per-pool sub-tabs

When a comparison run is present, the dashboard MUST present each capital pool as its own
sub-view so a researcher can inspect per-pool backtest status and debug signals, instead of
a single flat table.

#### Scenario: Render per-pool tabs

- **WHEN** `comparison.json` and the per-mode summaries are present
- **THEN** the task view MUST render a tab group with a "比較總覽" tab plus one tab each for
  `shared`, `per_stock`, and `unconstrained`
- **AND** each pool tab MUST show that pool's metrics, strategy-health verdict, equity/
  drawdown chart, and a debug block including `cash_blocked_entry_count`
- **AND** the comparison table's `max_drawdown_rate` MUST be populated from the per-mode
  summaries (not rendered as `n/a`).

#### Scenario: Unconstrained tab marks null returns

- **WHEN** the `unconstrained` tab renders
- **THEN** return-scale fields that are null MUST be shown as signal-quality-only (not as
  real return) with an explanatory note.

### Requirement: Dashboard provides per-pool and cross-pool judgments

The dashboard MUST provide a textual judgment for each capital pool and a comparative
judgment across pools, derived by pure, independently testable functions.

#### Scenario: Cross-pool judgment identifies the bottleneck

- **WHEN** `shared` underperforms `per_stock` and `comparison.json` flags contention-affected
  symbols (or `cash_blocked_entry_count` is positive)
- **THEN** the comparative judgment MUST state that the signal may be sound but capital
  allocation is the bottleneck, and recommend a future "未賣出但需換股" rotation strategy.

#### Scenario: Judgment functions are pure

- **WHEN** `capital_mode_comparative_verdict(...)` or `capital_mode_pool_verdict(...)` is
  called with summary/comparison dicts
- **THEN** they MUST return judgment strings without importing or invoking Panel.

### Requirement: Dashboard provides a usage/help view and removes raw artifact links

The dashboard MUST provide a help view describing where task artifacts live and how to
re-run a backtest, and MUST NOT surface raw html/json artifact links in the sidebar or task
body.

#### Scenario: Help view documents data locations and re-run commands

- **WHEN** the user opens the "使用說明" view
- **THEN** it MUST list the `tasks/<id>/` artifact locations and the CLI commands to re-run a
  backtest (including `--capital-mode all`) and to rebuild/serve the dashboard.

#### Scenario: Raw artifact links removed

- **WHEN** the server app renders
- **THEN** the sidebar and task body MUST NOT contain the raw html/json artifact link list;
  file locations are conveyed via the help view instead.

### Requirement: The dashboard contract is implementation-agnostic

The `research-dashboard` capability's requirements MUST be satisfied by whichever implementation is currently the primary entry point (Panel or the new frontend), and switching the primary entry point MUST NOT drop any existing requirement.

#### Scenario: Verify parity before switching the primary entry point

- **WHEN** `open_research_dashboard.cmd` is repointed from the Panel implementation to the
  new frontend
- **THEN** every scenario in this capability's existing requirements MUST have a
  demonstrated equivalent in the new frontend
- **AND** the retired Panel server is removed following the owner-authorized cleanup;
  its source remains recoverable from Git history. Shared API and static-report helpers remain supported.

### Requirement: Dashboard filters results by classification and universe

The dashboard MUST let a researcher filter stock rankings and task views by industry classification or by the named universe used for the run, when that metadata is available.

#### Scenario: Filter rankings by industry

- **WHEN** classification metadata is available for the symbols in a task's rankings
- **THEN** the ranking view SHOULD offer an industry filter
- **AND** applying it MUST show only symbols matching the selected industry.

#### Scenario: Task run used a named universe

- **WHEN** a task's `summary.json` records the universe used for the run
- **THEN** the dashboard MUST display the universe name alongside the run metadata.

### Requirement: Dashboard provides an explicit shutdown control

The dashboard MUST offer an always-visible control that lets a researcher stop the local
dashboard server from the browser, without requiring terminal access.

#### Scenario: Shut down from the GUI

- **WHEN** the researcher activates the shutdown control and confirms in the follow-up
  dialog
- **THEN** the dashboard MUST request a server shutdown
- **AND** it MUST then show a full-screen closed state indicating the researcher can safely
  close the browser tab.

#### Scenario: Cancel the shutdown confirmation

- **WHEN** the researcher opens the shutdown confirmation and dismisses it (cancel or close)
  without confirming
- **THEN** the dashboard MUST NOT request a server shutdown
- **AND** the dashboard MUST remain fully usable.

### Requirement: Dashboard shuts down after the browser is closed

The dashboard server MUST stop on its own once the researcher closes the browser tab,
without requiring an explicit shutdown action.

#### Scenario: Browser tab closed

- **WHEN** the frontend stops sending its periodic heartbeat (e.g. the tab was closed) for
  longer than the server's configured grace period
- **THEN** the dashboard server MUST stop.

#### Scenario: Page refresh does not trigger shutdown

- **WHEN** the researcher reloads the page (e.g. F5) and the heartbeat resumes within the
  grace period
- **THEN** the dashboard server MUST NOT stop.
