## MODIFIED Requirements

### Requirement: Unsupported corporate actions are visible

The system MUST surface unsupported or partially supported corporate action events instead of silently ignoring them, and the set of unsupported event types MUST be limited to events that genuinely cannot be adjusted (e.g. missing or invalid `price_factor`), not to event types with usable factor data.

#### Scenario: Encounter unsupported event

- **WHEN** the data loader detects a corporate action that is not fully modeled
- **THEN** the summary MUST include a warning
- **AND** the dashboard SHOULD translate that warning into user-facing language without exposing raw internal warning phrasing as the primary message.

#### Scenario: Encounter a capital-reduction event without a usable factor

- **WHEN** a capital-reduction row's `price_factor` is missing or not positive
- **THEN** the data loader MUST NOT apply an adjustment for that row
- **AND** it MUST emit the same visibility warning as other unsupported events.

## ADDED Requirements

### Requirement: Rights and stock-dividend events adjust signal prices only

The system MUST adjust signal prices for `EX_RIGHT` and `EX_RIGHT_AND_DIVIDEND` events using the corporate-action index's `price_factor`, the same mechanical adjustment already applied for splits. Held share quantities MUST NOT be changed for these event types: on the recorded ex-date, real share count has not yet changed (new shares from a rights subscription list separately, on a date this data does not track), so no share-count adjustment is modeled.

#### Scenario: Apply rights-issue price adjustment to signal prices

- **WHEN** the data loader processes an `EX_RIGHT` or `EX_RIGHT_AND_DIVIDEND` event with a
  valid `price_factor`
- **THEN** it MUST apply a permanent multiplicative adjustment to signal prices for dates
  before the event, using the same mechanism as `SplitAdjustmentFactor`
- **AND** it MUST leave raw/accounting prices unchanged
- **AND** it MUST NOT change the broker's held share quantity for this event.

### Requirement: Combined rights-and-cash events also apply a cash signal window

The system MUST apply the existing cash-dividend signal-window adjustment for the cash component of `EX_RIGHT_AND_DIVIDEND` events, in addition to the price-factor adjustment.

#### Scenario: Apply both components of a combined event

- **WHEN** the data loader processes an `EX_RIGHT_AND_DIVIDEND` event with both a valid
  `price_factor` and cash-dividend inputs
- **THEN** it MUST apply the permanent price-factor adjustment first
- **AND** it MUST then apply the existing cash-dividend fill-window logic on top of the
  price-adjusted signal prices for the same event date.

### Requirement: Capital-reduction events adjust signal prices and share counts

The system MUST adjust signal prices and held share quantities for capital-reduction events (`CASH_CAPITAL_REDUCTION`, `LOSS_OFFSET_CAPITAL_REDUCTION`, `CAPITAL_REDUCTION`) when the row has a valid `price_factor`, since real share count changes on the same date for these events (physical share cancellation/consolidation), unlike rights issues.

#### Scenario: Apply a capital-reduction adjustment

- **WHEN** the data loader processes a capital-reduction event whose `price_factor` is
  valid (not null, greater than zero)
- **THEN** it MUST apply the same permanent price and share-count adjustment mechanism
  used for splits.

### Requirement: Price policy version identifies adjustment coverage

The backtest summary MUST record a price-policy version that distinguishes the expanded corporate-action adjustment coverage from the prior policy.

#### Scenario: Emit expanded price policy version

- **WHEN** a backtest summary is generated after this change
- **THEN** `price_policy.name` MUST reflect the expanded adjustment coverage (e.g.
  `corporate_action_aware_v2`) so summaries can be distinguished from those generated under
  the prior policy.
