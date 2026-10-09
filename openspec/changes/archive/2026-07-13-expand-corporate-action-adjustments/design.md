## Context

`DataLoader._apply_corporate_action_policy` (`StockProject/engine/data_loader.py:216`)
currently handles two event families end-to-end:

- `SPLIT_EVENTS` (`ETF_SPLIT`, `ETF_REVERSE_SPLIT`): permanent `SplitAdjustmentFactor`
  applied to all prior dates, `Broker.handle_split` scales held share count on the event
  date.
- `CASH_DIVIDEND`: a 5-day `DividendSignalFactor` "fill window" — the signal price is
  discounted until the raw close recovers to the pre-event close (`DividendFilled`), or the
  window expires after 5 rows.

Everything else — `EX_RIGHT`, `EX_RIGHT_AND_DIVIDEND`, and three capital-reduction event
types — falls into `UNSUPPORTED_EVENTS` (`data_loader.py:14`) and is skipped entirely: no
price adjustment, no share-count change, just a warning string appended to
`self._warnings`. The `corporate_actions` table already carries `price_factor` and
`share_factor` for these rows (per the `price-data-pipeline` baseline spec), so the data
needed to adjust them is present — it is simply not consumed yet. This has zero test
coverage today, which is the primary reason no one has touched it: any change risks
silently breaking the split/dividend math that dozens of existing task summaries depend on.

## Goals / Non-Goals

**Goals:**

- Adjust `EX_RIGHT` (stock dividend / rights issue), `EX_RIGHT_AND_DIVIDEND` (combined
  stock + cash), and evidenced capital-reduction events using the same `price_factor` /
  `share_factor` fields already computed by `fetch_corporate_actions.py`.
- Keep the existing raw-vs-signal separation contract: adjustments only ever change
  `Signal*` columns and `Broker` share counts, never `Raw*` execution prices.
- Lock in current split/dividend behavior with characterization tests before changing
  anything, so regressions in the well-tested paths are caught immediately.
- Make the residual "unsupported" set explicit and small (ideally empty, or limited to rows
  `evidence_status` marks as insufficiently evidenced).

**Non-Goals:**

- Do not model merger/exchange-ratio corporate actions.
- Do not change how splits or cash dividends are adjusted — their existing behavior is the
  baseline to preserve, not to redesign.
- Do not change fee/tax/execution-price logic in `Broker`.

## Decisions

**0. Data-availability correction (found during apply, confirmed with user 2026-07-13):
use `price_factor`, not `share_factor`, and do not adjust Broker share count for
`EX_RIGHT`/`EX_RIGHT_AND_DIVIDEND`.**
Inspection of the live `corporate_actions.sqlite` showed `share_factor` and
`cash_per_share` are hardcoded to `None` for every row in all three
`fetch_corporate_actions.py` normalizers — the underlying TWSE feeds (`twt49u`,
`twtcau`, `twtauu`) do not carry a subscription-ratio/subscription-price field at all, so
`share_factor` cannot be computed from current data, not merely "not yet wired up." The
field that is populated for 100% of the 4,957 events is `price_factor`
(`reference_price / previous_close`), the same field already driving `ETF_SPLIT`
adjustment today. Separately, on a real `EX_RIGHT`/`EX_RIGHT_AND_DIVIDEND` ex-date, held
share count does not actually change yet — new shares from a rights subscription list
weeks later on a date this table does not track — so mirroring `handle_split`'s
same-day share-count bump for these two event types would model an event that doesn't
happen on that date, introducing a new error rather than fixing one. Capital-reduction
events are mechanically different: real share count changes same-day (physical
cancellation/consolidation), so they remain split-like for both price and share count.
This revises decisions 1–3 below relative to the original proposal/specs; the delta spec
in this change has been updated to match.

**1. Treat `EX_RIGHT`'s stock-dividend component as a signal-price-only adjustment, using
`price_factor`; do not change held share count.**
Reuse the existing `SplitAdjustmentFactor` pattern: apply `price_factor` as a permanent
multiplicative adjustment to prior-date signal prices for `EX_RIGHT`/
`EX_RIGHT_AND_DIVIDEND` rows. Do **not** extend `Broker`'s share-count-scaling logic to
these event types (see Decision 0). Alternative considered: treat it purely as a
cash-dividend-style window — rejected because the theoretical reference-price adjustment
is permanent (like a split's price effect), not a temporary fill-window effect, even
though the share-count side is out of scope.

**2. Treat `EX_RIGHT_AND_DIVIDEND`'s cash component like `CASH_DIVIDEND`, on top of the
price-factor adjustment.**
`EX_RIGHT_AND_DIVIDEND` rows carry `cash_dividend_estimate`/`price_factor` inputs
analogous to `CASH_DIVIDEND`. Apply the permanent price-factor adjustment first, then run
the existing 5-day fill-window logic for the cash portion on the same event date.
Alternative considered: a single combined factor — rejected because it would conflate a
permanent adjustment with a temporary fill-window one, and the existing test/verification
patterns already distinguish the two mechanisms.

**3. Capital-reduction events use `price_factor` directly for both price and share count,
gated by a valid (non-null, positive) factor — not by `evidence_status`.**
Inspection showed `evidence_status` is `REFERENCE_PRICE_ONLY` for every non-`CASH_DIVIDEND`
row in the live data — there is no "insufficiently evidenced" tier distinct from that today,
so gating on `evidence_status` string values would either adjust nothing or everything,
never something in between. The real, already-established sufficiency gate is the
existing `price_factor` null/`<=0` guard used for splits and cash dividends. Rows with a
valid `price_factor` get the same split-style permanent price and share-count adjustment;
rows without one remain unsupported/warning-only — this residual set is expected to be
empty in current data but the guard stays as a defensive check. Alternative considered:
adjust all capital-reduction rows unconditionally — rejected, keep the existing
null/invalid-factor guard for consistency with splits/dividends.

**4. Characterization tests come first, as their own commit/step.**
Before touching `_apply_corporate_action_policy`, write tests that pin today's exact output
for known split and cash-dividend fixtures. This converts "zero test coverage" risk into a
concrete safety net the rest of the change can run against. Alternative considered: write
tests for old and new behavior together — rejected because it would not catch an
accidental regression in the split/dividend paths introduced while adding the new event
handling.

**5. Price-policy version bump signals the behavior change.**
`price_policy.name` moves from `corporate_action_aware_v1` to `corporate_action_aware_v2`
in `summary.json`, so anyone comparing summaries generated before/after this change can see
why numbers differ for affected symbols.

## Risks / Trade-offs

- [Risk] Re-running historical tasks after this change will change `summary.json` metrics
  for any symbol that experienced a previously-unsupported event → Mitigation: this is the
  intended correctness fix; call it out explicitly in the proposal's Impact section and in
  task re-run notes, and confirm via characterization tests that _unaffected_ symbols
  produce byte-identical output.
- [Risk] `price_factor` values from TWSE open data could themselves have
  errors or edge cases (e.g. zero/negative factors) → Mitigation: reuse the existing
  guard pattern (`if pd.isna(price_factor) or price_factor <= 0: continue`) already present
  for splits and cash dividends.
- [Risk] Not adjusting Broker share count for `EX_RIGHT`/`EX_RIGHT_AND_DIVIDEND` leaves a
  one-time mark-to-market discontinuity at the event date (old share count priced at new
  post-event raw prices) → Mitigation: this is the existing (pre-change) behavior for these
  event types, not a new regression; documented as a residual limitation pending real
  share-count data, not silently modeled with an invented number.
- [Risk] Combining share adjustment and cash fill-window logic for
  `EX_RIGHT_AND_DIVIDEND` in the wrong order could double-count the price impact →
  Mitigation: explicit test case combining both components against a hand-computed
  expected value.

## Migration Plan

- No data migration. This is a pure engine-logic change; `corporate_actions.sqlite` schema
  is unchanged.
- Rollout: merge behind the version-string bump so downstream consumers (dashboard,
  diagnosis) can tell which policy generated a given summary. No feature flag needed since
  this is a correctness fix, not an optional behavior.
- Rollback: revert the `_apply_corporate_action_policy` and `Broker` changes; prior
  behavior (treat as unsupported/warning-only) is restored automatically since it was the
  default before this change.
