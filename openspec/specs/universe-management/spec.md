# universe-management Specification

## Purpose

TBD - created by archiving change add-universe-management. Update Purpose after archive.

## Requirements

### Requirement: Symbol classification metadata is available locally

The system MUST maintain local classification metadata (market, industry category, ETF flag, listing date) for tracked symbols, sourced from official TWSE/TPEx public data.

#### Scenario: Look up a symbol's classification

- **WHEN** a caller queries classification metadata for a symbol code
- **THEN** the system MUST return its market (上市/上櫃), industry category, ETF flag, and
  listing date when available
- **AND** it MUST indicate when a symbol has no classification data rather than failing.

### Requirement: Named universes group symbols for reuse across runs

The system MUST support named, version-controlled universes that expand to a list of stock codes at run time.

#### Scenario: Define an explicit-code universe

- **WHEN** a universe file under `universes/` specifies an explicit `codes` list
- **THEN** the universe MUST expand to exactly that code list.

#### Scenario: Define a rule-based universe

- **WHEN** a universe file specifies a classification rule (e.g. `industry: "半導體"`)
- **THEN** the universe MUST expand to all symbols whose classification metadata matches
  the rule at resolution time
- **AND** the resolved code list MUST be recorded in the run's output metadata for
  reproducibility.

### Requirement: Backtest CLIs accept a universe reference in place of an explicit code list

The backtest CLI and its task wrappers MUST accept an `@universe-name` token as the `--codes` value, expanding it to the named universe's code list before running.

#### Scenario: Run a backtest against a universe

- **WHEN** `--codes` is given as `@universe-name`
- **THEN** the CLI MUST resolve it to that universe's expanded code list before executing
  the backtest
- **AND** behavior after resolution MUST be identical to passing the same codes directly.

#### Scenario: Unknown universe name

- **WHEN** `--codes` references a universe name that does not exist
- **THEN** the CLI MUST fail clearly before executing the backtest.

### Requirement: Multiple universes can be compared in one command

The backtest runtime MUST support running the same strategy and parameters across multiple universes in one invocation, producing a full summary per universe plus a cross-universe comparison artifact.

#### Scenario: Run a multi-universe comparison

- **WHEN** the CLI receives multiple universe references for one backtest invocation
- **THEN** it MUST write a full `summary_<universe>.json` per universe
- **AND** it MUST write a `comparison.json` with headline metrics per universe
- **AND** `summary.json` MUST alias to a designated default universe's result for backward
  compatibility with tooling that reads only `summary.json`.
