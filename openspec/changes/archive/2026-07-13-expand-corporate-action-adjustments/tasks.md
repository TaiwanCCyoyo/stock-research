## 1. Characterization tests (before touching any adjustment logic)

- [x] 1.1 Write fixtures covering: a symbol with no corporate actions, a symbol with only a
      split, a symbol with only a cash dividend, and a symbol with both.
- [x] 1.2 Write characterization tests asserting the exact current output (signal prices,
      `SplitAdjustmentFactor`, `DividendSignalFactor`, `DividendFilled`, `DividendWindowActive`,
      `CorporateActionTypes`) of `_apply_corporate_action_policy` for each fixture.
- [x] 1.3 Write a characterization test for `Broker.handle_split`'s current share-count
      adjustment behavior.
- [x] 1.4 Confirm all characterization tests pass against the current (unmodified) code
      before proceeding.

## 2. Rights and stock-dividend adjustment (`EX_RIGHT`, `EX_RIGHT_AND_DIVIDEND`)

> Scope correction (confirmed with user 2026-07-13): `share_factor` is unpopulated in the
> live database — the upstream TWSE feeds do not carry a subscription-ratio field at all.
> Use `price_factor` for the signal-price adjustment only; do NOT change Broker share
> count for these two event types, since real share count does not change on the recorded
> ex-date (new shares from a rights subscription list separately, weeks later, on a date
> not tracked here). See design.md Decision 0.

- [x] 2.1 Extend `_apply_corporate_action_policy` to apply `price_factor` for `EX_RIGHT`/
      `EX_RIGHT_AND_DIVIDEND` rows using the same permanent-adjustment mechanism as
      `SplitAdjustmentFactor` (guard invalid/zero/negative factors the same way).
- [x] 2.2 Confirm (with a test) that `Broker`/`backtest_engine.py` do NOT change held share
      quantity for `EX_RIGHT`/`EX_RIGHT_AND_DIVIDEND` events — no new broker method or call site
      for these two event types.
- [x] 2.3 Add a test: signal price adjustment for a fixture with a known `price_factor` on
      an `EX_RIGHT` row, asserting prior-date signal prices scale and held share quantity for an
      open position is unchanged across the event date.

## 3. Combined cash component for `EX_RIGHT_AND_DIVIDEND`

- [x] 3.1 After applying the price-factor adjustment, run the existing cash-dividend
      fill-window logic on the same event date for `EX_RIGHT_AND_DIVIDEND` rows.
- [x] 3.2 Add a test combining both components against a hand-computed expected signal
      price sequence.

## 4. Capital-reduction events

> Scope correction: confirmed live data has no `evidence_status` tier distinguishing
> "sufficiently evidenced" from "insufficient" for non-`CASH_DIVIDEND` rows (all are
> `REFERENCE_PRICE_ONLY`). The real, already-established sufficiency gate is the existing
> `price_factor` null/`<=0` guard, reused as-is. Capital-reduction share count changes
> same-day (physical cancellation), so both price and Broker share count are adjusted here,
> unlike `EX_RIGHT`/`EX_RIGHT_AND_DIVIDEND` in section 2.

- [x] 4.1 Confirm (via a test against the real `corporate_actions.sqlite` fixture data) that
      `evidence_status` has no usable "insufficient" tier today, and that the existing
      `price_factor` null/`<=0` guard is the actual sufficiency gate for capital-reduction rows.
- [x] 4.2 Extend `_apply_corporate_action_policy` to apply the permanent price adjustment for
      `CASH_CAPITAL_REDUCTION`/`LOSS_OFFSET_CAPITAL_REDUCTION`/`CAPITAL_REDUCTION` rows with a
      valid `price_factor`; extend `Broker` to adjust held share quantity for these rows too,
      reusing `handle_split`'s scaling logic; leave rows with missing/invalid `price_factor` in
      the unsupported/warning path.
- [x] 4.3 Add tests for both the adjusted path (price + share count) and the
      missing/invalid-factor unsupported path.

## 5. Shrink unsupported set and bump policy version

- [x] 5.1 Update `UNSUPPORTED_EVENTS` to only the residual case(s) (capital-reduction rows
      with a missing/invalid `price_factor`), removing `EX_RIGHT`/`EX_RIGHT_AND_DIVIDEND` and
      valid-factor capital-reduction types. (The static `UNSUPPORTED_EVENTS` set was removed
      entirely — unsupported-ness is now a per-row `price_factor` validity check over
      `RIGHTS_EVENTS | CAPITAL_REDUCTION_EVENTS`, since no event type is unconditionally
      unsupported anymore.)
- [x] 5.2 Bump `price_policy.name` to the new version string in `backtest_cli.py`'s
      price-policy metadata block.
- [x] 5.3 Update `openspec/specs/corporate-action-price-policy/spec.md` expectations are
      reflected in code (cross-check against the delta spec in this change).

## 6. Deprecate yfinance fallback as primary source

- [x] 6.1 Confirm `corporate_actions.sqlite` is checked first and only falls back to
      `dividends.parquet`/yfinance CSVs when the SQLite index is unavailable (already the
      resolution order — verify with a test).
- [x] 6.2 When the fallback path is used, add an explicit `summary.json` warning stating
      that the primary corporate-action index was unavailable.
- [x] 6.3 Mark the yfinance dividend fetch path as deprecated in
      `shioaji_stock_prices/README.md`.

## 7. Validation

- [x] 7.1 Run `uv run python -m pytest tests/ -q` — all characterization and new tests
      green. (201 passed)
- [x] 7.2 Run `uv run ruff check` and `uv run mypy` on changed engine files. (both clean)
- [x] 7.3 Re-run `tasks/sample` (and any other existing task not involving a rights/capital
      event) with default parameters; diff `summary.json` against the pre-change baseline —
      MUST be byte-identical for symbols with no affected events. (2330's rights/dividend
      events are all 2003-2009, outside the task's 2022+ window; re-run diff vs. the existing
      `corporate_action_aware_v1` summary showed zero differences besides `output_path`/
      `run_id` metadata — confirmed byte-identical.)
- [x] 7.4 Identify at least one real symbol/date with an `EX_RIGHT` or
      `EX_RIGHT_AND_DIVIDEND` event in the local data, run a backtest across that event, and
      manually verify the adjusted signal price (and unchanged share count) against a hand
      calculation from the `corporate_actions.sqlite` row. (3037, EX_RIGHT on 2025-11-14,
      price_factor=0.9897478991596638. RawClose on 2025-11-13 = 178.5; hand calc
      178.5 * 0.9897478991596638 = 176.6700, matching the engine's SignalClose exactly. A real
      `BacktestEngine.run()` pass across the event with an open position confirmed
      `get_splits_for_date` excludes the event (no broker share-count change) and
      `get_warnings()` is empty.)
- [x] 7.5 Note any skipped Docker-backed verification with a reason. (Docker-backed
      verification was not run: all checks above (pytest, ruff, mypy, sample-task re-run, real
      EX_RIGHT event verification) ran directly against the host `.venv`/local data, consistent
      with this change's Non-Goals ("Docker-backed execution is not required for local
      validation") and the established pattern from the prior 2B-promotion session, where the
      Docker-only `assert_host_env_not_mounted()` sanity check in
      `smoke_task_research_runtime.py` always fails outside the container and was substituted
      with direct subprocess/module-level verification.)
