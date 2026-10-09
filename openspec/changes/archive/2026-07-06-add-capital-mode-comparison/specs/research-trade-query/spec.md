# Research Trade Query Delta

## MODIFIED Requirements

### Requirement: Price and cash context are explicit

Trade inspection MUST include enough context to explain why and how a trade was recorded
without requiring manual JSON or CSV inspection.

#### Scenario: Build price context

- **WHEN** a trade inspection resolves a trade date and code
- **THEN** the result MUST include same-day OHLC, raw OHLC, split-adjusted OHLC, signal
  price policy, dividend-window flags, corporate action types, prior close, moving
  averages, convergence fields, trend fields, and swing-break fields when available.

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
