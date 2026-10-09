# Price Data Pipeline

## Purpose

Define the artifact contract Stock consumes from the `shioaji_stock_prices` submodule's
local data pipeline — per-symbol daily price files, the corporate-action index, and the
consolidated parquet cache — and the degrade-without-crashing behavior
`StockProject/engine/data_loader.py` must provide when that data is missing or stale.
Producer-side fetching, conversion, and index-building are owned by the submodule's own
OpenSpec baseline; this spec covers only what Stock reads and how it behaves when the
data is incomplete.

## Requirements

### Requirement: Daily price files are read as the primary local price record

Stock MUST read `{code}_day.csv` files produced by the `shioaji_stock_prices` submodule as
its primary local price record, without depending on how those files are produced.

#### Scenario: Read a daily price file

- **WHEN** `StockProject/engine/data_loader.py` loads a symbol
- **THEN** it MUST read that symbol's `{code}_day.csv`
- **AND** it MUST expect `Date`, `Open`, `High`, `Low`, `Close`, `Volume` columns.

### Requirement: Corporate-action database path is resolved from candidate locations

Stock MUST locate the submodule's `corporate_actions.sqlite` by probing a fixed set of
candidate paths, without assuming a single fixed location relative to the data directory.

#### Scenario: Resolve the corporate-action database path

- **WHEN** the engine data loader needs corporate-action data for adjustment
- **THEN** it MUST probe known candidate paths for `corporate_actions.sqlite`
- **AND** it MUST fall back to the legacy per-symbol yfinance dividend CSVs under
  `data/dividends/` only when the SQLite index is unavailable.

### Requirement: Unsupported corporate-action event types are explicitly tracked

The pipeline MUST distinguish corporate-action event types it fully adjusts from those it only surfaces as warnings, so downstream consumers do not silently trust unadjusted prices.

#### Scenario: Encounter an unsupported event type

- **WHEN** the data loader reads a corporate-action row whose `event_type` is in the unsupported set (`EX_RIGHT`, `EX_RIGHT_AND_DIVIDEND`, `CASH_CAPITAL_REDUCTION`, `LOSS_OFFSET_CAPITAL_REDUCTION`, `CAPITAL_REDUCTION`)
- **THEN** it MUST NOT apply a price or share adjustment for that row
- **AND** it MUST emit a warning identifying the symbol, date, and event type, per `corporate-action-price-policy`'s visibility requirement.

### Requirement: Consolidated parquet cache freshness is checked against source CSVs

Stock MUST treat `shioaji_stock_prices/data/price_daily.parquet` as a read-optimized cache
owned and rebuilt by the submodule, and MUST detect when a source CSV is newer than that
cache.

#### Scenario: A daily CSV is newer than the parquet cache

- **WHEN** `DataLoader.load_all()` finds a `{code}_day.csv` with a newer mtime than
  `price_daily.parquet`
- **THEN** it MUST reload that symbol from the CSV instead of the stale parquet row
- **AND** it MUST emit a warning naming the affected symbol count and pointing at the
  submodule's rebuild entry point (`run_daily.py` or `build_price_parquet.py`).

### Requirement: Missing local price data degrades without crashing

Stock MUST treat a symbol with no local daily file as an observable, non-fatal condition
rather than raising an unhandled exception.

#### Scenario: Symbol has no local daily file

- **WHEN** `DataLoader` is asked for a symbol with no `{code}_day.csv` on disk
- **THEN** it MUST return an empty result for that symbol rather than raising
- **AND** the backtest summary MUST list the symbol under `missing_symbols` with a warning.

## Non-Goals

- This spec does not change the price-adjustment math itself — see `corporate-action-price-policy` for the adjustment contract and `expand-corporate-action-adjustments` (planned change) for closing the unsupported-event gap.
- This spec does not cover data acquisition, conversion, or corporate-action indexing — those are owned by the `shioaji_stock_prices` submodule's own `price-data-pipeline`, `corporate-actions-index`, `symbol-metadata`, and `daily-update-orchestration` baseline specs. Stock reads their output artifacts by contract only.
