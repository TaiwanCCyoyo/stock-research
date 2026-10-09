# experiment-spec

## ADDED Requirements

### Requirement: Experiment contract is a validated task-local artifact

The system SHALL define a task-local `experiment.json` that fully bounds an unattended research run: hypothesis text, strategy file reference, fixed run configuration (codes, cash, data path), tunable parameter dimensions with explicit ranges or choice lists, acceptance gates, train window, holdout window, and stop conditions (max iterations, no-improvement rounds, wall-clock budget). The file MUST be validated against a schema before any loop iteration runs, and validation failure MUST abort with a machine-readable reason.

#### Scenario: Valid spec accepted

- **WHEN** a task contains an `experiment.json` whose fields satisfy the schema, whose parameter ranges are non-empty, and whose train and holdout windows do not overlap
- **THEN** spec validation succeeds and the loop harness is allowed to start iteration 1.

#### Scenario: Invalid spec rejected before any backtest

- **WHEN** `experiment.json` is missing a required field, declares an empty tunable range, or declares overlapping train/holdout windows
- **THEN** validation MUST fail before any backtest subprocess is launched
- **AND** the failure reason MUST be written to the experiment journal.

### Requirement: Acceptance gates encode the big-wins-small-losses philosophy

The experiment spec SHALL declare acceptance gates as machine-checkable thresholds over summary metrics, defaulting to expectancy > 0, payoff ratio >= 2, and profit factor > 1, plus a minimum `closed_trade_count` below which a run is an automatic gate failure.

#### Scenario: Gate defaults applied

- **WHEN** an experiment spec omits explicit gate thresholds
- **THEN** the default thresholds (expectancy > 0, payoff ratio >= 2, profit factor > 1) and the minimum closed-trade-count guard MUST be used.

#### Scenario: Too few trades fails gates explicitly

- **WHEN** a run's `closed_trade_count` is below the spec's minimum
- **THEN** gate evaluation MUST report failure with a distinct "insufficient trades" reason rather than evaluating ratio metrics on the tiny sample.

### Requirement: Spec is immutable while a loop runs

The system SHALL treat `experiment.json` as immutable for the duration of a loop run; iterations MUST NOT modify the spec, and a detected mid-run change MUST stop the loop.

#### Scenario: Mid-run spec change stops the loop

- **WHEN** the spec file's content hash at iteration N+1 differs from the hash recorded at iteration 1
- **THEN** the harness MUST refuse to run the iteration and journal the mismatch as the stop reason.
