# Entry-window v1 — E1-B1 implementation handoff

This handoff implements the fixed [mission](mission.md) and [data contract](data-contract.md),
merged through PR #101. It changes neither record nor the `not_evaluated` study card.
Only B1 is implemented: pure quote masks, canonical membership/cooling/outcome counts,
and integer aggregation. There are no market results, fill claims, bootstrap intervals,
parameter selection, or research conclusions.

## Public API and alignment

Module: [`research_core.entry_window_v1`](../../research_core/entry_window_v1.py),
definition `entry-window.v1`.

- `Quotes` takes an explicit security ID, the common `pd.DatetimeIndex`, raw OHLC
  vectors on that calendar, and three interval-state vectors. `classify_quotes(calendar, quotes)`
  rejects duplicate, descending, non-session-date, timezone-aware, or mismatched calendars,
  vector lengths/types, and unknown state codes. It never sorts, fills, skips a missing
  next-session quote, or discovers a data root.
- Raw OHLC and optional official lower/upper bounds require exact `np.float64` dtype.
  float16/float32, including a lower-precision raw close mixed with a float64 open,
  raise `ValueError` rather than enter quote classification. This makes the typed
  price contract explicit and keeps band multiplication, shifted quotes, ratios and
  official-limit comparisons in the same precision. Callers are responsible for
  supplying these arrays; B1 does not silently convert them or restore precision
  already lost upstream. The fixed bands, inclusive endpoints and no-epsilon policy
  are unchanged.
- `action_to_next[i]` describes **the whole `(calendar[i], calendar[i+1]]` interval**:
  `1` action, `0` explicitly no action, `-1` unknown. `event_quality_to_next[i]` and
  `quote_quality_to_next[i]` describe interval coverage and the fixed t1 quote quality:
  `1` known good, `0` known invalid, `-1` unknown. Boolean state arrays are rejected.
  The final row has no next session irrespective of its supplied interval states.
  A future source adapter must establish these states explicitly; this interface does
  not assert historical PIT availability.
- `QuoteMasks.quote_known` is Q; `clean` is M before signal intersection. Primary
  quote-failure priority is `no_next_session`, `invalid_raw_close`, `no_open`, then
  `invalid_quote_ratio` for numeric overflow/underflow. Multi-reason diagnostics retain
  simultaneous problems. Corporate-action unknown, event invalid/unknown and quote
  invalid/unknown have separate reason counts; `Q_minus_M` is the deduplicated loss.
- `BANDS` and `COMPARISONS` expose exactly B01–B06, M01–M24 and S01–S12. Inclusive
  comparisons multiply the original raw close by the fixed endpoints, without tick
  rounding or epsilon. Above/below never change after an intraday range touch.
- `range_touch` and `one_price` use `-1/0/1` for unknown/false/true. Missing, invalid,
  inconsistent needed bars or unqualified quote quality stay unknown. Range touch
  only requires the high/low pair and valid original raw close. `OfficialLimits`
  is optional, with explicit official source, bounds and tri-state source quality on
  quote-session dates; missing/unqualified evidence gives `limit_status=unknown`.
  `at_upper`, `at_lower`, `inside` and `outside` describe only the observed open
  against those supplied limits. One-price and official-limit evidence never imply
  lock status, personal queue allocation, or filled/executable orders.
- `count_stock(calendar, stock, quotes)` requires a complete, already aligned canonical
  `momentum_only_v1.StockDaily` and matching quote ID/calendar. `StockDaily` has no date
  axis of its own: the caller explicitly attests that its positions use this common
  calendar. Vector lengths and states are validated; no adapter silently aligns it.
  All canonical label arrays are required by `group_counts`, but output selects only
  2x/H126, 2x/H252, 5x/H504. No labels or source arrays are rewritten.

## Membership, counts and aggregation

`count_stock` uses `condition_sets`, `set_members`, `groups`, `cooled` and `group_counts`
directly from `momentum_only_v1`. CORE maps to `A1&A2`; LEAD_B1 retains all three original
atoms. Daily and cooled20 use the canonical lookback. Cooling occurs once per whole
stock/set before quote/quality/band/year filtering. Missing/rejected/excluded events
consume that clock and do not cause replacement candidates.

`StockCounts.rows` contains `CountRow` records keyed by set, cadence, optional band,
original label, security ID, t0 year and arm. Counts follow canonical `METRICS` order:
event, known, hit, loss, flat-win, unknown, censored, full-unknown.

- `band_id=None` has S, Q, M, S_minus_Q and Q_minus_M once each. The common M baseline
  is never copied into six band totals.
- Each band has accepted/rejected/above/below counts under the same M and original
  t label. All groups conserve `event=known+full_unknown+censored` and
  `known=hit+loss+flat_win`; unknown and censored may overlap. A source censored-hit
  remains unchanged in `StockDaily.labels` and contributes no main hit.
- `StockCounts.diagnostics` is one stock/year row per set/cadence: S/Q/M and exclusions,
  multi-reasons, mutually exclusive primary failures, and tri-state/official diagnostics.
  Reason counts may overlap and are not a replacement for deduplicated Q_minus_M.
- `aggregate_rows(rows)` recombines disjoint stock/year rows into all four fixed eras,
  preserving every empty grid cell. It rejects duplicate stock/year keys. Canonical
  counts widen to int64 immediately, then aggregate as unbounded Python integers.
  Stock IDs and known-stock IDs are retained as unions across years; annual distinct
  counts are never added. Partition the resulting rows, **not the input history**,
  so a year/chunk boundary cannot reset cooling.
- `comparison_rates(summaries, cell, cadence, era)` checks shared-arm conservation and
  computes only mission point estimates, after summing counts. Zero denominators and
  unavailable differences return `None`. `rejected_hit_share` uses all-M known hits
  as its denominator. Counts and stock sets expose the later runner's required
  cooled20 readability check (`known_n<100` or `distinct_stock_n<30`); B1 does not
  turn this into a strategy verdict.

## Synthetic verification and CI

[`test_entry_window_v1.py`](../../scripts/tests/test_entry_window_v1.py) uses only
in-memory synthetic bars and canonical `outcomes_for_targets`; no real prices,
labels, holdout, forward outcomes or production/shared roots are read.
Coverage includes fixed missing t1 versus a later quote, Saturday sessions,
all six exact endpoints and adjacent floating values, overlapping quality exclusions,
pre-mask cooldown across a year boundary, canonical arm-count equality and jump
overlay, censored-unhit/missing-before-hit/hit, full-known hit/loss/flat-win/full-unknown,
stock/year reassembly, stock unions, integer overflow boundaries, empty/null cells,
original-signal invariance to supplied quote changes, and malformed inputs.

The exact `entry_window` CI domain selects B1 without broad future-version patterns.
Changes to its canonical membership/count/cooldown/lookback and synthetic-outcome
dependencies also select its tests while preserving existing consumers and unknown-path
full fallback. Normal hooks and proportional synthetic checks are required for delivery;
the PR records their actual head-specific outcome.

Local evidence (2026-10-27): `python -m pytest scripts/tests/test_entry_window_v1.py
scripts/tests/test_ci_scope.py -q` passed 276 tests. After adding the numeric-ratio
edge case and completing typed-calendar corrections, the final core-only run passed
41 tests. Normal commit hooks passed whitespace, size, secrets, UTF-8, Mypy, Pyright
and Ruff checks; Prettier's asset-row formatting was retained before the final commit.
These are synthetic implementation checks, not real-input parity or a research run.

### PR #105 price-precision correction

[Astra's finding on head 9e1415d](https://github.com/TaiwanCCyoyo/stock-research/pull/105#issuecomment-6439190907)
reproduced a float32 raw close of 10 with float64 open 9.7 being classified below
B01: the lower bound was multiplied in float32. Validation now enforces the existing
`NDArray[np.float64]` price annotations at runtime for every raw OHLC and official
limit bound. Supplied low/mixed precision is rejected explicitly; no implicit
conversion, band change, rounding or epsilon is introduced.

Author verification of the correction: the new mixed-dtype endpoint regressions
failed all 12 cases before the fix. The complete updated core suite (77 cases) plus
an unchanged local copy of the reviewer-owned probe suite (60 cases) passed all 137
cases afterwards. The original reviewer files under the task-14 probe checkout were
read only and remain unchanged. This author rerun corroborates the correction;
Astra's independent re-review must still bind the new pushed head. The published
branch was synchronized by normal merge with docs-only main `465405b067b2de4c50b0ec6c30cafe43a773a5d1`.

Session-owned isolated checkout: `C:/Users/xjp01/Documents/Codex/2026-10-27/task-8/repo`,
branch `codex/entry-window-core`, starting from fetched `origin/main`
`71acd4e70f9c0d227eeb6f1941caa4bb6dacb2ce`. The executor's writable workspace determines
this checkout location. Other worktrees, primary dirty submodule and forward-log stay
with their existing owners. This session owns one checkout, retained for the draft PR;
it creates no inspection worktree or research scratch run.

## Remaining B2/C and execution gates

B2 is a separate bounded task after B1 review/integration: paired stock/two-way
bootstrap, explicit source readers/adapters and bounded runner, with their own synthetic
acceptance. They are absent here. Formal provenance/generation/fingerprint checks and
result publication are also later work, not implied by these arrays.

Actual market execution remains gated by owner-approved mission, compatible canonical
universe/calendar and original label/research permissions, source/quality alignment,
owner/resource coordination including S1/S2/PR17, and explicit single-run compute
admission. A mission merge or passing synthetic test grants none of those permissions.
No market probe, download, shared-family update, hold/release, deployment, scheduler
change, production-root operation, or trade is authorized by B1. Definition ambiguity
or incompatible sources must return to parent/owner without changing the mission,
canonical helpers, cutoff, population or thresholds. Astra review binds the proposed
PR head; merging stays with the owner.
