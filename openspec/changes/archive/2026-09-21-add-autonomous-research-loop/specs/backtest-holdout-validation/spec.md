# backtest-holdout-validation

## ADDED Requirements

### Requirement: Train and holdout windows are evaluated separately

The system SHALL support evaluating one parameter set over two disjoint windows — the train window used for iteration and a holdout window untouched by search — by orchestrating the existing backtest CLI over each window and computing acceptance gates on each summary independently. No modification of `StockProject/engine/` is required or permitted for this capability.

#### Scenario: Holdout run for a candidate winner

- **WHEN** an iteration produces a parameter set that passes gates on the train window
- **THEN** the harness SHALL run the same strategy and parameters over the spec's holdout window
- **AND** journal the holdout gate results alongside the train results.

#### Scenario: Search never reads holdout results

- **WHEN** the loop selects the next parameter adjustment
- **THEN** the selection input MUST be limited to train-window results; holdout results MUST only be used for acceptance and reporting.

### Requirement: Final acceptance requires gates on both windows

An experiment outcome SHALL be reported as "accepted" only when its acceptance gates pass on the train window and on the holdout window; passing on train alone MUST be reported as "candidate — failed holdout" with both metric sets shown.

#### Scenario: Overfit candidate is not accepted

- **WHEN** a parameter set passes gates on the train window but fails any gate on the holdout window
- **THEN** the journal and morning report MUST record it as failing holdout validation, not as an accepted result.

### Requirement: Holdout evaluations are metered

The system SHALL journal every holdout evaluation, and the morning report MUST state the total holdout-evaluation count for the run so repeated peeking is visible to the reviewer.

#### Scenario: Peeking is visible

- **WHEN** a loop run evaluated the holdout window three times
- **THEN** the morning report MUST state that count explicitly.
