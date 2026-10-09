## Why

`corporate_actions.sqlite` already holds official TWSE `price_factor`/`share_factor` data
for 4,957 `EX_RIGHT`, `EX_RIGHT_AND_DIVIDEND`, and capital-reduction events, but
`StockProject/engine/data_loader.py`'s `_apply_corporate_action_policy` treats all of them
as `UNSUPPORTED_EVENTS`: it emits a warning and leaves prices and share counts completely
unadjusted. Any backtest that holds through one of these events silently understates or
overstates returns with no adjustment applied at all — this is a correctness gap in the
"big wins, small losses" research the whole project exists to support. The adjustment math
that already exists for splits and cash dividends has zero test coverage, which is why this
must be fixed carefully rather than as a quick patch.

## What Changes

- Add characterization tests locking the current (pre-change) behavior of split and cash
  dividend adjustment in `_apply_corporate_action_policy`, before touching the function.
- Extend `_apply_corporate_action_policy` to adjust `EX_RIGHT` and
  `EX_RIGHT_AND_DIVIDEND` events: apply `price_factor` to signal prices the same way
  `SplitAdjustmentFactor` is applied for splits, and apply the cash portion of
  `EX_RIGHT_AND_DIVIDEND` through the existing cash-dividend signal-window logic.
  **Scope correction found during apply** (2026-07-13): the originally proposed
  `share_factor` field is unpopulated in the live database and the upstream TWSE feeds
  cannot supply it; held share quantity is therefore NOT adjusted for these two event
  types, since real share count does not change on the recorded ex-date anyway (new
  shares from a rights subscription list weeks later, on an untracked date). See
  design.md Decision 0.
- Extend adjustment handling to capital-reduction event types
  (`CASH_CAPITAL_REDUCTION`, `LOSS_OFFSET_CAPITAL_REDUCTION`, `CAPITAL_REDUCTION`) using
  `price_factor` for both price and share-count adjustment (via `Broker`, mirroring
  `handle_split`), since real share count changes same-day for these — gated by the
  existing null/invalid-`price_factor` guard rather than `evidence_status`, which has no
  usable "insufficient" tier in current data.
- Shrink `UNSUPPORTED_EVENTS` to only the event types that still lack a modeled adjustment
  after this change (expected to be none, or a residual set for insufficient-evidence rows
  encountered at runtime).
- Deprecate the yfinance dividend fallback (`data/dividends/*.csv` /
  `dividends.parquet`) as the primary source: `corporate_actions.sqlite` becomes the sole
  primary source, and any fallback use is explicitly flagged in `summary.json` warnings.
- Bump the `price_policy.name` version string (e.g. `corporate_action_aware_v2`) so
  summaries generated before and after this change are distinguishable.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `corporate-action-price-policy`: signal-price and share-count adjustment now covers
  `EX_RIGHT`, `EX_RIGHT_AND_DIVIDEND`, and evidenced capital-reduction events instead of
  only splits and cash dividends; the "unsupported events are visible" requirement narrows
  to whatever residual event types remain unmodeled.

## Non-Goals

- No real trading, broker integration, or investment advice.
- No change to fee/tax calculation, execution price selection, or the raw-vs-signal price
  separation contract itself — only which event types get adjusted.
- No merger/exchange-ratio modeling — README already states these require additional
  official evidence and remain out of scope.
- Docker-backed execution is not required for local validation; note any skipped Docker
  checks in completion notes.

## Impact

- `StockProject/engine/data_loader.py`: `_apply_corporate_action_policy`,
  `UNSUPPORTED_EVENTS`, price-policy version string.
- `StockProject/engine/broker.py`: `handle_split` extended to also cover
  capital-reduction rows (share count changes same-day); no broker change for
  `EX_RIGHT`/`EX_RIGHT_AND_DIVIDEND` (see Decision 0).
- `StockProject/backtest_cli.py`: `price_policy` metadata block (version bump).
- `tests/`: new characterization tests for existing split/dividend math, new tests for
  rights/capital-reduction adjustment.
- Every existing task's `summary.json` MAY change in metrics for symbols that experienced
  a previously-unsupported event — this is the intended correctness fix, not a regression.
