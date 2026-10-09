## ADDED Requirements

### Requirement: Daily institutional buy/sell data is fetched from official sources

The system MUST fetch daily three-major-institution (foreign, trust, dealer) buy/sell data for tracked symbols from official TWSE and TPEx open-data sources.

#### Scenario: Fetch listed-stock institutional data

- **WHEN** the institutional fetcher runs for a listed (上市) symbol and date range
- **THEN** it MUST retrieve data from the TWSE T86 open-data endpoint
- **AND** it MUST upsert rows into `institutional_daily` keyed by `(date, code)` without
  duplicating existing rows.

#### Scenario: Fetch OTC-stock institutional data

- **WHEN** the institutional fetcher runs for an OTC (上櫃) symbol and date range
- **THEN** it MUST retrieve data from the equivalent TPEx open-data endpoint
- **AND** it MUST upsert rows using the same schema and key as listed-stock data.

#### Scenario: Repeated fetch is idempotent

- **WHEN** the fetcher runs twice for the same symbol and overlapping date range
- **THEN** the second run MUST NOT create duplicate rows
- **AND** it MUST track already-fetched ranges so repeated runs skip redundant requests.

### Requirement: Institutional data storage records per-category flow

The local institutional database MUST record foreign, trust, and dealer net (and gross) buy/sell figures per symbol per day.

#### Scenario: Store a daily record

- **WHEN** a row is upserted into `institutional_daily`
- **THEN** it MUST include foreign net shares, trust net shares, dealer net shares, and the
  underlying buy/sell share counts per category where the source provides them.

### Requirement: Engine access to institutional data is opt-in

The backtest engine MUST NOT change the default bar snapshot shape or any existing backtest result when institutional data is present locally; access MUST require an explicit opt-in by the caller.

#### Scenario: Default backtest run is unaffected

- **WHEN** a backtest runs without explicitly requesting institutional data
- **THEN** `summary.json` output MUST be identical to a run against the same inputs before
  this change existed.

#### Scenario: Strategy opts into institutional data

- **WHEN** a caller explicitly requests the institutional join for a set of symbols
- **THEN** the resulting bar snapshot MUST include the per-category buy/sell fields for
  dates where local institutional data exists
- **AND** dates with no institutional data available MUST expose those fields as `null`
  rather than a default numeric value.
