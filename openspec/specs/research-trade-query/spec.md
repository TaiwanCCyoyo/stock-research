# Research Trade Query

## Purpose

Define the baseline deterministic query surface for inspecting local task trades, signal evidence, cash context, and same-day price context from task artifacts.

## Requirements

### Requirement: Trade queries use local task artifacts as evidence

The research trade query tooling MUST answer task trade questions from local task artifacts and local price data rather than recomputing unrelated research state.

#### Scenario: Inspect a task trade

- **WHEN** a caller inspects one task trade by `trade_id` or by code, date, action, and occurrence
- **THEN** the tool MUST load the task's `summary.json`
- **AND** it MUST return task id, query parameters, stable trade id, trade index, trade record, signal events, cash context, price context, strategy metadata, strategy parameters, price policy, and data path.

#### Scenario: Missing task or trade

- **WHEN** the requested task, summary, price data, or trade cannot be found
- **THEN** the tooling MUST fail with a user-readable query error rather than returning partial invented evidence.

### Requirement: Trade ids are stable within a task summary

The query tooling MUST expose stable task-local trade ids derived from summary trade order.

#### Scenario: Convert trade index to id

- **WHEN** a trade is returned from `summary.json`
- **THEN** its stable id MUST use the `T001`, `T002`, `T003` sequence based on zero-based trade index plus one.

#### Scenario: Query by trade id

- **WHEN** a caller supplies a stable trade id
- **THEN** the query MUST resolve it back to the corresponding trade index
- **AND** it MUST reject malformed or out-of-range trade ids.

### Requirement: Trade lists provide compact selection context

The query tooling MUST provide compact task trade lists so users and agents can disambiguate which trade to inspect.

#### Scenario: List task trades

- **WHEN** a caller lists trades for a task
- **THEN** the result MUST include count and compact rows with trade id, date, code, action, price, quantity, total, signal reason, realized PnL, cumulative realized PnL, and add-on status when available.

#### Scenario: Filter task trades

- **WHEN** a caller provides code, action, or limit filters
- **THEN** the trade list MUST apply those filters before returning rows.

### Requirement: MCP and CLI surfaces share the same deterministic core

The MCP server and CLI fallback MUST use the same underlying query functions so their evidence contracts stay aligned.

#### Scenario: Use MCP server

- **WHEN** `scripts/mcp_stock_research_server.py` runs
- **THEN** it MUST expose `inspect_task_trade`, `list_task_trades`, and `list_research_tasks` tools over stdio MCP transport.

#### Scenario: Use CLI fallback

- **WHEN** MCP tooling is unavailable
- **THEN** `scripts/inspect_task_trade.py` MUST provide a CLI fallback for inspecting a task trade
- **AND** it MUST support JSON output as the default format.

### Requirement: Price and cash context are explicit

Trade inspection MUST include enough context to explain why and how a trade was recorded
without requiring manual JSON or CSV inspection, and MUST resolve that context without
reading price data for symbols unrelated to the inspected trade.

#### Scenario: Build price context

- **WHEN** a trade inspection resolves a trade date and code
- **THEN** the result MUST include same-day OHLC, raw OHLC, split-adjusted OHLC, signal
  price policy, dividend-window flags, corporate action types, prior close, moving
  averages, convergence fields, trend fields, and swing-break fields when available.

#### Scenario: Build price context without a full-corpus scan

- **WHEN** a trade inspection resolves price context for one symbol
- **THEN** the underlying price load MUST read only that symbol's local data (and its
  corporate-action rows) rather than loading every symbol's price file
- **AND** the returned price context MUST be identical to the value produced by loading
  the full local corpus and filtering to the same symbol.

#### Scenario: Build cash context

- **WHEN** a trade inspection resolves a trade index
- **THEN** the result MUST include cash before trade, cash after trade, position before
  trade, gross amount, fee, tax, recorded total, add-on status, realized PnL, and
  cumulative realized PnL when available.

#### Scenario: Build per-symbol (`per_stock`) cash context

- **WHEN** a trade inspection resolves a trade from a summary whose `run.capital_mode` is
  `per_stock`
- **THEN** cash before trade and cash after trade MUST be calculated from that trade's
  symbol bucket only, starting from `run.per_stock_initial_cash`
- **AND** unrelated symbols' trades MUST NOT reduce or increase the inspected symbol's
  cash context.

> **Implementation note**: the `per_stock` branch of `cash_context` in
> `scripts/stock_research_query.py` was implemented and committed before this change. This
> change activates it end-to-end by producing `summary_per_stock.json` as a queryable
> artifact, and adds regression tests to lock the behaviour.

#### Scenario: Query a per-mode summary directly

- **WHEN** a caller passes `summary_per_stock.json` or `summary_unconstrained.json` as
  the source summary
- **THEN** `inspect_task_trade` MUST resolve trades and cash context from that summary
  using the same logic as for `summary.json`.

### Requirement: Research task discovery reports artifact availability

The query tooling MUST expose recent local research tasks and whether key analysis artifacts are available.

#### Scenario: List research tasks

- **WHEN** a caller lists research tasks
- **THEN** the result MUST include task ids and availability flags for summary, signal events, stock rankings, data audit, and visual report artifacts.
