# S7-B2b single-week calendar and close assessment

This package implements `multi-timeframe-ma-weeks.v1`: pure single-week evidence
assessment and adjusted-close aggregation, with synthetic tests only. It follows
the existing [mission](mission.md) and [data contract](data-contract.md).
The research definition remains `multi-timeframe-ma.v1`, `not_evaluated`.
No market study, official calendar reader or full S7 acceptance is claimed.

## Local ownership and delivery

- Implementation owner: delegated S7-B2b worker, 2026-10-28 `task` executor.
- Original implementation base: `9c029cd883450d815b3fdcee98688f5fb25ce183`.
- Current integration base: fetched main
  `346156abc534eae591a5bcc67f6f8cc29490352f` (panel PR114 merged).
- Branch: `codex/multi-timeframe-ma-weeks`.
- Isolated checkout: `C:/Users/xjp01/Documents/Codex/2026-10-28/task/repo`.
  This is the session's sole checkout (1/5), in its writable executor workspace;
  retained for independent Astra review and parent-controlled publication.
- Before creation: 25 registered checkouts, no weeks branch in local/remote
  refs, and no matching module/test/handoff at the inventoried checkout paths.
  Open PR111 and PR113 concern another study. The panel worker has its own
  checkout. Parent later confirmed that it released the shared-writer slot;
  this worker then integrated only the weeks entries described below.
- The required `worktree_inventory.py --no-pr --json` was launched before
  creation and reported 25 worktrees. Its broader ignored-byte scan did not
  finish in the bounded preflight and was interrupted. Full ignored-byte and
  other sessions' live status remain unknown; nothing was cleaned, reassigned
  or treated as abandoned. Metadata inventory and exact path checks establish
  this package's isolation, not another task's cleanup eligibility.
- Earlier read-only Git inventory and fetch attempts failed before execution.
  Subsequent explicit owner approval allowed the formal minimum-scope route;
  the inventory queries, fetch and this worktree creation then succeeded.
  No ACL, security setting, credential, producer checkout or other task changed.
- Scope is this module, its synthetic test, this handoff and the three explicitly
  authorized shared integration files below. Main was refreshed again after
  PR114 merged. The unpublished task commit was normally rebased onto that main;
  only manifest lists and selector expected sets conflicted, resolved by union.
  No panel worktree was copied or modified. Final commit SHA and normal-hook
  evidence accompany the handback. Integration review precedes push/draft PR
  under parent coordination; this is **not merge-ready**.

Parent reported independent Astra review of
`30e8dca7c31436419dd1f59b629a7488634d4b3d` with no findings: 108 weeks plus
20 S7 selector cases passed, and independent probes covered 1,152 week states,
1,152 timezone comparisons, 1,152 aggregates, 896 invalid/missing-price cases,
63 knowledge gaps and 16 selectors. The local sync preserves the reviewed weeks
module and dedicated test byte-for-byte, checked with an empty Git diff against
that SHA. These review probes are parent-reported evidence, not rerun here.

## Public API and semantics

Module: `research_core.multi_timeframe_ma_weeks_v1`.

```python
CalendarFact(date, session_state, known_at, close_at, source_ref)
CalendarSnapshot(calendar_id, decision_at, facts, availability_note)
assess_week(snapshot, *, iso_year, iso_week) -> WeekAssessment
aggregate_week(daily_series, assessment) -> WeeklyBarAssessment
```

Facts use normalized naive `pd.Timestamp` civil dates and exact Python int
states -1/0/1. Snapshot facts are an explicit tuple of unique, increasing
`CalendarFact` values; no sorting, latest-wins, weekday inference or coverage
fill is performed. Nonempty calendar identity and availability note are required.
All supplied instants are aware `pd.Timestamp` values converted to Asia/Taipei;
naive, missing and string instants are rejected. No session time is hardcoded.
Declared known states require a source reference. Closed facts cannot carry a
close; session closes must belong to their fact's Taipei day. An absent session
close stays unknown, rather than inventing a close time.

`assess_week` examines Monday through Sunday of a validated ISO year/week and
returns immutable day coverage, effective states and overlapping reasons. Facts
outside that week are ignored. Missing facts, unknown states, absent known_at,
future known_at and unknown session close times cause `unknown`; this takes
precedence over `incomplete` from a known session still awaiting close. The exact
close instant counts as closed. Seven known closed days yield
`closed_no_sessions`. Otherwise all required sessions closed yields `complete`.

`required_session_dates` includes visible known sessions, even a known session
whose close clock is missing. That partial list never authorizes a bar.
`last_session_date` is resolved only when seven-day coverage and all session
close clocks are known; it is None for unknown coverage and empty closed weeks.
Both incomplete and complete weeks can have a resolved final session identity.

`aggregate_week` requires the public core `CutoffSeries` daily kind and
`reference_factor_adjusted` basis. It reuses the public constructor to validate
the exact float64/bool, date, identity and cutoff contract and take a private
snapshot; no core private helper is imported. The cutoff must equal the aware
decision's Taipei date. The assessment is checked against its retained target-week snapshot,
ISO identity and all derived fields, rejecting caller overrides of sessions,
last day, status, coverage, cutoff or calendar identity.

The result preserves independent price generation/security/basis/cutoff and
calendar identity/decision/availability lineage. `calendar_status` is separate
from the price result:

| Result status       | has_bar | bar_valid | Meaning                                                                             |
| ------------------- | ------- | --------- | ----------------------------------------------------------------------------------- |
| `withheld_calendar` | false   | false     | Unknown/incomplete calendar; no required-price examination or completed bar         |
| `empty_closed_week` | false   | false     | Seven explicitly closed days; no bar and no missing-price finding                   |
| `invalid_bar`       | true    | false     | Complete week, but at least one required session lacks a valid price; close is None |
| `valid_bar`         | true    | true      | Every required session is valid; close is the final session's close                 |

All complete-week sessions are checked, not just the last: missing rows,
`invalid_upstream` (including unknown factor/quality), `nonfinite_close` and
`nonpositive_close` retain dates and overlapping reasons. An invalid complete
week keeps its week_id and final session identity. It must retain its position
in any future authorized assembly so that core weekly warmup resets.
No earlier/later valid price substitutes for a missing final price. Quotes on
explicitly known closed days in this week appear in
`ignored_non_session_dates` and never affect close or validity. Other weeks'
history is irrelevant to this single-week result.

Input facts and result records are frozen dataclasses, nested sequences are
tuples, and no input buffer is mutated or shared with output. Scalar unknown
close is None. No first-confirmed-at, confirmed-today, weekly-turn, W/EMA,
provisional state, historical-PIT certification or strategy result is produced.
Caller-selected versions and source_ref do not prove real-source authenticity,
historical publication completeness, or TWSE/TPEx equivalence.

## Synthetic verification

```text
uv run pytest scripts/tests/test_multi_timeframe_ma_weeks_v1.py -q
```

The final suite passed **108 tests in 0.91s**, including Sunday-session,
malformed week-identity and unchanged serialized target-week evidence after
future append. Normal hook and committed-head evidence accompany the handback.

| Acceptance                                                                                                                                    | Test evidence                                                                                                                                                                                                                        |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Wednesday, Friday immediately before/exactly at/after explicit close; truncated prices do not complete calendar                               | `test_five_day_week_explicit_close_boundaries`                                                                                                                                                                                       |
| Missing weekend coverage; seven closed days, empty prices and phantom quotes                                                                  | `test_weekend_coverage_cannot_be_inferred_from_prices`, `test_seven_known_closed_days_have_no_bar_or_missing_price`                                                                                                                  |
| Real Saturday and Sunday sessions, phantom non-session quotes/quality                                                                         | `test_real_saturday_session_waits_for_its_own_close_and_sunday_quote_is_ignored`, `test_sunday_can_be_a_real_session_and_closed_phantom_quality_is_irrelevant`                                                                       |
| Early known closures, future/absent knowledge, later snapshot without backfill, overlapping unknown and incomplete reasons                    | `test_known_closures_allow_early_completion_but_late_announcements_do_not_backfill`, `test_unknown_or_future_fact_never_supplies_current_calendar_evidence`, `test_unknown_coverage_precedes_incomplete_and_retains_all_day_reasons` |
| ISO year boundary, aware zone conversion, naive/malformed dates/times, illegal weeks/states, duplicate/reversed facts and contradictory close | ISO, instant, fact and snapshot rejection tests                                                                                                                                                                                      |
| Missing middle/final price; NaN/Inf/zero/negative and upstream quality/factor false; overlapping causes                                       | `test_every_required_price_is_checked_and_invalid_week_position_is_retained`, bad-close and upstream-quality tests                                                                                                                   |
| Final-session close rather than max/next/previous; independent lineage; scaling; wrong cutoff/basis/kind/dtypes; assessment overrides         | last-session, scaling, daily-contract and assessment-override tests                                                                                                                                                                  |
| Complete invalid week retains position and resets weekly SMA/EMA seed                                                                         | `test_invalid_week_record_resets_core_weekly_warmup_in_test_only_wiring` (41 artificial weeks, no production assembler)                                                                                                              |
| Future append cannot alter saved cutoff result; frozen records, mutation/aliasing; no I/O or loader/signal parameters                         | future-append, immutability and runtime-no-I/O tests                                                                                                                                                                                 |

The no-I/O test blocks filesystem opens/reads, sockets and SQLite connections
while running the public functions, and checks imports/public parameters. Only
small synthetic in-memory data is used. No published-artifact verifier, market
suite, official calendar download, source read, label creation or large compute
is required or performed. The core and its existing tests are unchanged.

## Local shared integration

The initial three-file implementation staged proposals only. Parent then
explicitly transferred the shared-writer slot after panel PR114 publication.
This branch integrates the following weeks entries on main after panel PR114
merged. All original consumer relationships
and unknown-path full fallback remain. No momentum/count-cube dependency is added.

- `docs/en/research-program.md`: adds `multi-timeframe-ma-weeks.v1` beside the
  core asset, linking this handoff and the existing data contract, naming
  `CalendarFact/CalendarSnapshot/assess_week/aggregate_week`, and retaining the
  pure/synthetic scope and source/state/assembly/market gates.
- `scripts/ci_test_domains.json`: adds the weeks module/handoff to the existing
  `multi_timeframe_ma.paths`, and the weeks test to domain `tests` and sorted
  `reviewed_tests`. Core/mission/contract/derived_features/technical_daily paths
  and panel module/handoff registrations are preserved. Domain tests and
  `reviewed_tests` contain core, panel and weeks.
- `scripts/tests/test_ci_scope.py`: adds six A/M selector cases for the weeks
  module/test/handoff and preserves all panel A/M cases. The owned-path exact
  expected test set contains core, panel and weeks; a changed test additionally
  selects the selector itself. Core changes select both new suites.
  Technical-oracle and derived-fallback assertions include both packages while
  preserving existing consumers, panel unknown-path full fallback and all
  E1/count_cube cases.

Exact new domain paths:

```json
[
    "research_core/multi_timeframe_ma_weeks_v1.py",
    "tasks/20261027-multi-timeframe-ma/week-calendar-handoff.md"
]
```

Exact test added to both inventories:

```text
scripts/tests/test_multi_timeframe_ma_weeks_v1.py
```

Focused integration validation:

```text
uv run pytest scripts/tests/test_multi_timeframe_ma_weeks_v1.py scripts/tests/test_ci_scope.py -q
```

The original committed-head result was **378 passed in 41.32s** (108 weeks
cases and 270 selector cases). The final sync handback records the new focused
result, actual CI selection plan and normal-hook evidence.
The selector suite tests contracts; it does not execute the repository-wide plan.
Normal commit hooks remain required, without bypass or rule/dependency changes.

### Completed union with panel PR114

The resulting domain and owned-path exact expected test set contain:

```json
[
    "scripts/tests/test_multi_timeframe_ma_core_v1.py",
    "scripts/tests/test_multi_timeframe_ma_panel_v1.py",
    "scripts/tests/test_multi_timeframe_ma_weeks_v1.py"
]
```

Both packages' A/M cases and technical-oracle dependency assertions, the changed-
test selector addition, and the existing unknown/derived full fallback and
E1/count_cube consumers remain. The program index contains all three asset rows.
No numerical contract, reviewed production/test bytes or unrelated manifest
entry changed during synchronization.

## Remaining gates

SHA-bound Astra review of the synchronization/shared union delta, draft PR and
current-head hosted CI remain. The original implementation has a clean review;
that does not substitute for review of this final integration.
This task stops at a local commit for review despite eventual publication
authorization. No claim of hosted CI or merge readiness is made here.

Deferred: official source/version selection, known_at catalog verification,
late/multiple-week first confirmation, zero-session-week sequence joining,
cross-week assembly, historical D/W preservation, counts/bootstrap/lead-lag/
episode integration, real readers and full S7 acceptance. No default root,
filesystem/network/DB fallback, CLI, download, generation update/hold, scratch
research run, schedule or deployment was added. The original S1/S2/owner,
fixed-G/as_of/source/label/data and single-large-compute admission gates remain.
