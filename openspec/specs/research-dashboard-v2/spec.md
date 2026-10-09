# research-dashboard-v2 Specification

## Purpose

TBD - created by archiving change add-dashboard-v2. Update Purpose after archive.

## Requirements

### Requirement: The frontend browses tasks with classification filtering

The frontend MUST let a researcher browse discoverable tasks and filter them by industry or universe when that metadata is available.

#### Scenario: Browse the task list

- **WHEN** a researcher opens the task browser
- **THEN** it MUST list tasks from `GET /tasks` with title and freshness
- **AND** it MUST support filtering by industry or universe when classification metadata
  is present.

### Requirement: The K-line workbench renders trade and corporate-action context

The K-line workbench MUST render candlesticks with moving averages, buy/sell trade markers, and corporate-action markers using data from the research API.

#### Scenario: Render a symbol's K-line

- **WHEN** a researcher selects a symbol within a task
- **THEN** the workbench MUST render candlesticks and configured moving averages using
  `GET /tasks/{task_id}/prices`
- **AND** it MUST show buy/sell markers for that symbol's trades
- **AND** it MUST show a marker for any corporate-action event in the displayed range.

#### Scenario: Render institutional buy/sell context when available

- **WHEN** institutional data is available for the displayed symbol and date range
- **THEN** the workbench SHOULD render a secondary pane showing foreign/trust/dealer net
  buy-sell figures aligned to the same date axis.

### Requirement: Trade drilldown explains why and how a trade was recorded

Selecting a trade MUST show its triggering reason, price context, and cash/position context without requiring the researcher to inspect raw JSON.

#### Scenario: Inspect a trade

- **WHEN** a researcher selects a trade in the trade table
- **THEN** the frontend MUST display trigger reason, cash before/after, position
  before/after, and realized/cumulative PnL using `GET /tasks/{task_id}/trades/{trade_id}`.

### Requirement: Comparison views present capital-mode and universe results clearly

The frontend MUST present capital-mode and universe comparison results in a clearly labeled, readable layout.

#### Scenario: View a capital-mode comparison

- **WHEN** a task has `comparison.json` for capital modes
- **THEN** the frontend MUST show headline metrics per mode and any contention-affected
  symbols in a clearly distinguished layout (not a flat unlabeled table).

#### Scenario: View a universe comparison

- **WHEN** a task has `comparison.json` for universes
- **THEN** the frontend MUST show headline metrics per universe in the same clear layout
  pattern as the capital-mode comparison view.

### Requirement: Dashboard surfaces local data quality

The dashboard MUST show local price data completeness so a researcher can see whether a
result may be affected by missing or gapped data.

#### Scenario: Data quality report is available

- **WHEN** `GET /data-quality` returns a report
- **THEN** the dashboard's data-quality panel MUST display missing symbols, symbols with
  partial trading-day gaps, and any flagged corporate-action mismatches from that report.

#### Scenario: Data quality report is unavailable

- **WHEN** `GET /data-quality` returns the neutral "not yet checked" response
- **THEN** the dashboard MUST show a neutral "not yet checked" state rather than an error
  or a misleading "all clear" state.
