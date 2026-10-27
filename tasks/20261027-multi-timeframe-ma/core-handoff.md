# S7-B1 pure cutoff core handoff

This package delivers **pure mathematics with synthetic evidence only**, under
[mission](mission.md) / [data contract](data-contract.md). Research definition
`multi-timeframe-ma.v1` and the existing study card remain `not_evaluated`.
The reusable engineering component is `multi-timeframe-ma-core.v1`.
This is not full S7-B acceptance, a reader, or a market execution admission.

## Scope, ownership and base

- Owner: the delegated S7-B1 implementer in the 2026-10-27 `task-15` executor.
- Initial implementation base: `f337736f8e06c4dd21d010d19677ba8771a8ce87`.
- Local integration base: fetched `origin/main` =
  `9945d6878e1b3be530e4790ef8fd3a5db6dbcc7a` (PR105 merged); normal merge
  `210aa4351db3323403a4b5ec27bf054d16856aa3` preserved the reviewed S7 commits.
  The fresh GitHub open-PR query returned no PRs before integration.
- Branch: `codex/multi-timeframe-ma-core`.
- Isolated checkout: `C:/Users/xjp01/Documents/Codex/2026-10-27/task-15/repo`;
  one session-owned checkout, retained pending authorized draft PR delivery. The executor's
  writable workspace is used; the dirty primary checkout is unchanged.
- Initial implementation wrote the new core, its synthetic test module and this
  handoff. The parent subsequently designated this task the sole S7 shared
  integration writer, adding only `docs/en/research-program.md`,
  `scripts/ci_test_domains.json` and `scripts/tests/test_ci_scope.py` to scope.
- Before branching, Git worktree metadata listed 20 existing checkouts. Exact
  checks for all three allowlisted paths across those checkouts returned no
  files; the sole open PR105 changed six E1/shared files, none in this allowlist.
  The historical S7 mission branch is a different, already merged package.
- The full `worktree_inventory.py --json` invocation reported 20 checkouts but
  did not finish its broader inventory; the acting session interrupted that
  read-only command. Ignored-byte totals and other sessions' liveness remain
  unknown. No resource was cleaned, reassigned, or treated as abandoned.
- PR105 owned shared integration at initial verification. After its merge,
  parent explicitly authorized the local S7-only integration recorded below;
  E1-B2 packages remain separate owners, and no E1-B2 files are changed here.

### Delivery status

Implementation commit: `1306d939b15cbe3444b12daa87a8ca2024d0f438`.
Its exact committed-head synthetic suite passed **87 tests in 1.17s**;
normal commit hooks all passed, including Mypy, Pyright, Ruff, formatting,
secret/large-file/UTF-8/whitespace checks. That implementation changed only the
initial three allowlisted paths; its working tree was clean before publication.

Publication is **blocked, known not executed**. The executor's automatic
approval review rejected the exact action
`git push --set-upstream origin codex/multi-timeframe-ma-core` to
`https://github.com/TaiwanCCyoyo/stock-research.git`, saying external publication
was not explicitly authorized by trusted user text. No remote branch, PR,
hosted CI, bot review request or PR merge was created by this task. No alternate
publication route was attempted. Explicit trusted approval of that branch/PR
publication is the remaining execution-permission gate; a known-unexecuted
denial may only be retried once with materially new relevant evidence.

Parent reported an independent Astra clean review of
`6a4d7029aee09bc68739ce7f276728286115cdbd`, with 87 independent synthetic tests
plus MA/tri-state/lineage probes passing. The local main synchronization and
shared integration leave the reviewed core and its test file byte-identical.
The new shared integration still needs its own SHA-bound Astra review.

## Public API and numerical contract

Module: `research_core.multi_timeframe_ma_core_v1`.

- `PERIODS=(20,60,120)`, `UNKNOWN=-1`, `FALSE=0`, `TRUE=1`.
- `CutoffSeries(security_id, generation, decision_cutoff, price_basis, bar_kind,
bar_dates, close, valid)` validates explicit identity, dates, shape and exact
  float64/bool arrays, then copies its inputs. Dates are normalized, naive
  Asia/Taipei day labels; no sorting, dropping, filling or week inference.
- `moving_averages(series) -> MovingAverages`: float64 SMA and SMA-seeded EMA
  arrays for all three periods, effective bar `valid`, and positional boolean
  reason arrays. Invalid bars reset every window and preserve their position.
  SMA uses the oracle's segment-local pandas rolling mean; EMA uses its pandas
  first-N mean seed and `alpha*close + (1-alpha)*previous` order. EMA120 is new.
  All seed/recursive history is consumed. Numeric overflow becomes NaN with a
  nonfinite reason, never a known zero.
- MA results retain the exact originating `CutoffSeries` object in memory.
  `bull_at_cutoff` and `density_at_cutoff` reject even an equivalent new input
  object. Same length, dates or metadata alone cannot authorize mixing. No
  source hashing or external lineage lookup is used. Input and output arrays
  are copied/read-only; the public dictionaries should be treated as results.
- `bull_at_cutoff(series, ma) -> BullState`: last bar only; fields `state`,
  `strong_state`, `reasons`, `strong_reasons`. All operands must be known before
  conjunction; comparisons are strict `>` with no epsilon. D and W share this
  function. It does not return a reconstructed historical D/W series.
- `ratio_cross(states) -> RatioCross`: consumes caller-preserved D in common
  session order, accepting integer arrays with only -1/0/1, rejecting bool and
  floating arrays. Float64 `ratio` and `previous_ratio` preserve length and
  unknown NaN positions; int8 `cross50`/`cross70` use strict below-to-at-least
  crossings. The immediately preceding position supplies Rprev.
- `weekly_turn(*, confirmed_today, previous, current) -> int`: explicit integer
  tri-state confirmation; no calendar or stored state. Caller must not repeat
  confirmation on following days.
- `density_at_cutoff(series, ma) -> DensityState`: only caller-confirmed
  `completed_weekly`, with `values` in SMA20/60/120, EMA20/60/120 order,
  `denominator`, `density`, `known`, `reasons`. Scalar unknowns are `None`.
  Density is population std (`ddof=0`) / same-cutoff last WeeklyClose.
  It has no ranking, percentile, dense flag, common M or cross-stock behavior.

MA reason arrays: `invalid_upstream`, `invalid_close`, and
`{sma,ema}_{warmup,nonfinite}_{20,60,120}`. Bull/density reasons prefix these
causes with the affected operand, also exposing `insufficient_history`,
`empty_series`, or `density_nonfinite` where applicable. Ratio reasons are
`insufficient_history`, `unknown_in_window`, `current_ratio_unknown`, and
`previous_ratio_unknown`.

The caller owns OHLC and factor validity, missing-session insertion, full-week
quality aggregation, and completed-week confirmation. The accepted bar kind and
date labels do not certify those upstream facts or historical PIT availability.

## Synthetic verification

Command: `uv run pytest scripts/tests/test_multi_timeframe_ma_core_v1.py -q`.
Initial result: **87 passed in 3.91s**. The first sandboxed attempt failed in uv's
interpreter cache before executing tests; the exact bounded command then ran
successfully through the executor's formal escalation mechanism.

| Required case                                                                                                               | Test evidence                                                                                                                                                                                                   |
| --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N-1/N/N+1, constant/rising/falling, daily/weekly, EMA120 119/120/121                                                        | `test_n_minus_one_seed_and_first_recurrence`                                                                                                                                                                    |
| Public SMA20/60/120 and EMA20/60 parity, missing/quality/invalid close reset                                                | `test_exact_public_oracle_parity_and_segment_resets`: exact array equality against both public APIs; no tolerance                                                                                               |
| Preserved gaps, new seed, history older than 120 still contributes                                                          | Oracle reset test and `test_ema_retains_seed_history_beyond_last_120_bars`                                                                                                                                      |
| Same-cutoff positive scale across 20/60/120 and artificial split/dividend jumps                                             | `test_full_history_same_cutoff_scaling_including_all_windows`; MA tolerance only for floating multiplication order; signal comparisons have no epsilon                                                          |
| False plus unknown, strict equality, positional lag20, overflow reasons                                                     | `test_bull_strict_equalities_and_unknown_even_when_an_operand_is_false`, `test_lag20_uses_original_position_without_skipping_invalid_bars`, `test_numeric_overflow_has_reasons_and_never_becomes_false_or_zero` |
| Fixed denominator20, unknown window/Rprev, 0.45→0.50 and 0.65→0.70, no repeat at equality                                   | `test_ratio_uses_fixed_20_and_crosses_only_from_below`, `test_unknown_ratio_window_and_previous_are_positional_not_last_known`                                                                                  |
| Saved original-cutoff D, future append, differing latest-history reconstruction, future-row rejection                       | `test_saved_cutoff_states_survive_future_append_and_restatement`                                                                                                                                                |
| Confirmation false/unknown, unknown prior W, false→true, true→true, next-day no repeat                                      | `test_weekly_turn_confirmation_and_no_next_day_repeat`                                                                                                                                                          |
| Hand-computed six-value population std, equal values=0, invalid denominator/warmup unknown, no rank                         | `test_density_has_six_same_scale_values_population_std_and_no_rank`, `test_density_invalid_denominator_is_unknown`                                                                                              |
| Duplicate/reversed/future/aware/non-normal dates; shape/dtype; generation/security/cutoff/daily-weekly mix; caller mutation | `test_bad_series_rejected_without_sorting_casting_or_dropping`, `test_same_length_is_not_sufficient_ma_lineage`, malformed-state tests, `test_snapshot_no_mutation_and_empty_results`                           |

Only artificial arrays and in-memory OHLC were used. The public oracle calls
are `derived_features.compute_features` and `technical_daily_v1.compute_technical`;
no private helpers are imported and no maintained-family or frozen bytes change.
EMA120 has hand-seed/recurrence evidence, **not** claimed existing-oracle parity.
Normal commit hooks passed on the implementation commit. SHA-bound hosted CI
is not available because publication was denied; it remains a delivery gate.

## Local shared integration after PR105 merge

The previously staged S7-only changes are now applied under the parent's sole
writer assignment. The shared-file changes are limited to:

- `docs/en/research-program.md`: the `multi-timeframe-ma-core.v1` reusable asset
  row, linking this handoff and the S7 data contract, naming the five public
  functions and explicitly retaining pure/synthetic scope and market gates.
- `scripts/ci_test_domains.json`: `multi_timeframe_ma` owns the new core,
  this handoff, S7 mission/data-contract and the two public oracle source paths;
  its test is registered in the domain and sorted `reviewed_tests` inventory.
  Direct ownership of `technical_daily_v1.py` selects both S7 and the existing
  research-data consumers; no broad consumer edge is added. Existing consumer
  relationships and the `research_core/derived_*` full fallback are unchanged.
- `scripts/tests/test_ci_scope.py`: 14 A/M cases check exact domain/test
  selection for the module, test, handoff, mission and data-contract, preserve
  technical-oracle consumers, and retain the derived-oracle full fallback.
  This is the corrected existing selector path; no guessed selector is added.

Validation command:

```text
uv run pytest scripts/tests/test_multi_timeframe_ma_core_v1.py scripts/tests/test_ci_scope.py -q
```

Result: **337 passed in 75.72s** (87 S7 synthetic cases and 250 selector cases).
The selector suite checks selection/contracts without running the repository's
full test plan. The core suite still uses only artificial in-memory inputs.
Normal commit hooks must pass on the reported local integration commit; its
final SHA and hook evidence accompany the local patch delivery.

This closes local shared registration and selector validation only. Publication
remains blocked/pending explicit trusted approval; no push or PR creation is
attempted in this integration turn. SHA-bound hosted CI and independent Astra
review of the integrated head remain gates before any merge-ready claim.

## Deferred work and unchanged admission gates

Not implemented or accepted here: calendar knowability, Wednesday truncation,
Saturday/holiday/emergency closure handling, full-week aggregation, provisional
EMA, as_of readers and real-source parity, cross-stock P barrier, ranking/ties/
small pools/dense, common M, S6/CORE integration, canonical cooldown, labels,
counts, bootstrap/CI, lead-lag, successful episodes, orchestration or CLI.
The mission's full 16-class S7-B matrix has **not** passed.

No market prices, outcomes, labels, holdout, producer/shared root, downloads,
generation holds/updates, scratch/research computation, production deployment,
scheduler or trading were accessed or changed. No report, receipt or market
result is manufactured. Local shared integration is complete; review of that
integration, publication and hosted CI remain open. Actual market work still
needs S1/S2 completion or explicit owner reorder,
owner overlap verification, qualified fixed-G/as_of data, and the original
owner/data/compute and single-long-run admission gates.
