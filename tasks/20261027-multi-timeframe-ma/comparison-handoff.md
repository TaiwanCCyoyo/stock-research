# S7 complete-population comparison handoff

`multi-timeframe-ma-comparison.v1` is the finite in-memory layer after
[StockCounts](counts-handoff.md), under the unchanged [mission](mission.md) and
[data contract](data-contract.md). The study remains `not_evaluated`.

## Scope and ownership

- This session owns `codex/s7-comparison` in
  `D:/Project/stock-research/.worktrees/s7-comparison`, retained for owner review
  of this local-only delivery. No push, PR, deployment or scheduler change.
- Base: fetched `origin/main` `946f00787f3c65058006c7481b9cd53b0830aaf8`;
  merged counts PR117 is `8cafbb648bce252108c636954c4e01d1c2e0b5b3`.
  Main had no comparison module; GitHub plugin search found no open S7 /
  multi-timeframe / StockCounts PR. Registered pre-existing worktrees had no
  module at the new path. Primary and original counts checkout were clean.
- Required worktree inventory completed with 47 pre-existing entries, preserved
  under the primary checkout's `.tmp/s7-aggregation-inventory.json`. Its subprocess
  PR lookups reported `gh exited 4` (wrapper not used); those PR states remain
  unknown. The independent plugin search above supplied the relevant open-PR
  check. No login, credential changes or cleanup of other sessions was performed.
- Only the new module/test/handoff, the shared bootstrap seed type extension,
  asset index, counts handoff link and CI integration change. Core, panel, weeks,
  count_stock, frozen evidence, mission, study card and data contract are unchanged.
  `.agents/skills` is absent; applicable repository skills are in `.codex/skills`.

## API and output contract

```python
aggregate_counts(*, codes: tuple[str, ...],
                 stocks: Iterable[StockCounts]) -> ComparisonTables
```

Caller supplies a nonempty unique complete population, including explicit zero
StockCounts. Caller code order is preserved as the resampling index. Packets can
arrive in arbitrary order or chunks through the iterable; every code must appear
exactly once. Missing stocks are errors, never filled with zeros. This API cannot
certify that a supplied complete population is the actual PR61 universe.

All fixed axes must exactly equal the counts module's axes. Exact int64 shapes,
nonnegative counts, outcome partitions, diagnostics, S6/M/state/membership
conservation, C-base admission and cooled subset consistency are validated.
`excluded_known_n != 0` fails. Conservative bounds reject potential int64 overflow
and weighted totals beyond exact float64 integer capacity (`2**53-1`). No dtype
coercion, sorting, input mutation, reads or writes are performed.

`ComparisonTables` contains explicit `codes`, `years` and tuples of row dictionaries:

| Table     | Fixed rows                                                        |
| --------- | ----------------------------------------------------------------- |
| summary   | 6 groups × 2 cadences × 8 labels × 4 eras × 3 row kinds = 1,152   |
| annual    | 6 × 2 × 8 × 17 original-t years × 3 row kinds = 4,896             |
| contrasts | 4 candidates × 2 baselines × 8 labels × 2 cadences × 4 eras = 512 |
| intervals | 512 contrasts × 2 bootstrap types × 2 statistics = 2,048          |

Summary/annual rows retain all 12 integer metrics, all-event distinct stock count,
shared rate/bound/concentration summaries, scoped supplied coverage/state/membership
totals, cooled sample counts and `sample_sufficient`. Years are always 2010..2026;
empty rows remain present with null rates. Eras are all/2010–2012/2013–2018/2019+.
All counts are added as int64 before rates. Distinct stocks are recomputed across
the selected stock/year cells; annual distinct numbers are never added together.
Unknown/censored overlap and censored observed hits retain their original meaning.

Drop-best rows use public `best_year` / `best_stock` within each reported
arm/cadence/label/slice, removing the most eligible-hit year/stock across all
metrics and audits. Ties use earliest year/smallest code; an event-bearing slice
with zero hits still drops by that tie rule. An event-empty slice removes nothing.
The removed ID is recorded. In an annual drop-year row the single year is removed,
leaving an explicit empty sensitivity row. Each row's cooled sufficiency uses the
same excluded stock/year as that row. Contrasts and intervals use `full` rows;
drop-best remains a concentration description and does not replace the main comparison.

Both daily and cooled contrasts match baseline cadence. The two primary labels
remain 2x/H252 and 5x/H504 (16 contrasts per cadence/era); the other six remain
secondary. These stratum repetitions do not create new primary hypotheses.
Both arms' known and distinct counts and their corresponding cooled counts are
reported. Even daily rows require at least 100 cooled known events and 30 cooled
all-event stocks in each arm. Otherwise status is `insufficient`, interpretation
`inseparable`; numeric descriptive differences are retained when defined. Zero
known in either arm gives a null difference with the affected arm in `missing_reasons`.

The dictionaries are ordinary caller-owned in-memory outputs, not immutable
published artifacts. This package supplies no serializer, result receipt or files.

## Paired intervals and shared primitives

`count_cube_v1.summarize`, `best_year`, `best_stock`, `resampled_totals` and
`percentile_interval` remain the only statistical primitives used here.
`bootstrap_weights` additionally accepts an explicit NumPy Generator; integer seeds
retain their old streams, so existing consumers need no changes.

- Stock: seed 20261030, exactly 2,000 replicates.
- Two-way: seed 20261031, exactly 2,000 replicates.
- Generator: NumPy `Generator(PCG64)` / `default_rng`; NumPy version is reported.
- Draw stock indices as the complete `[rep, stock_draw]` block first, then (for
  two-way) the complete `[rep, year_draw]` block using the same RNG. Every original
  t year, including empty years, stays in that index. Era masks apply after drawing;
  eras do not reseed, redraw or compress either population. This makes all rows'
  shared weights and index identities explicit.
- All candidate/baseline/cadence/label rows share the replicate weights. Two-way
  cell weights are stock multiplicity times year multiplicity. Weighted total
  counts precede each arm's hit/loss rate, then the candidate-minus-baseline
  difference. Bounds use public 2.5/97.5 linear percentiles of finite differences.
- Each statistic reports seed/reps, point estimate, bounds and valid/null counts.
  A zero denominator in either arm makes that replicate null. No valid replicates
  means both bounds null. Insufficient samples do not become a no-advantage verdict.

## Verification

Environment: Python 3.13.18, pytest 9.0.3. The tests use invented StockCounts only, including independent scalar aggregation
and bootstrap oracles, complete row identities, chunks versus one iterable,
overlapping annual stocks, zero stocks/cells, tied drops, paired weights and both
fixed seeds, malformed inputs, no mutation and forbidden I/O. CI integration
registers the test itself plus counts/count-cube dependency paths and preserves
existing consumers. Actual local executions:

- `D:/Project/stock-research/.venv/Scripts/python.exe -m pytest scripts/tests/test_multi_timeframe_ma_comparison_v1.py -q`:
  **39 passed in 13.65s**. This includes heterogeneous stock rates and one-arm-zero
  denominators, both fixed-seed scalar bootstrap oracles, all-event versus known
  stock sufficiency, and both censored diagnostic undercounts and overcounts.
  An earlier test expectation incorrectly named 2011 instead of the fixture's
  actual best-hit year 2018; the test now checks 2018 and separately checks an
  all-tied label's earliest-year removal at 2010.
- Selector integration worker ran `.../python.exe -m pytest scripts/tests/test_ci_scope.py`:
  **430 passed in 32.15s**.
- Actual staged eight-file diff was parsed with `ci_scope.parse_changes`, passed
  to `make_plan` and executed with the existing `execute_plan` (4 bounded workers).
  Plan: **32 files, full=false, frontend=false**, including the new test, all five
  S7 suites and existing count-cube consumers. Result: **1,848 passed, 1 skipped,
  1 failed in 42.23s**. Sole failure was the existing synthetic Windows junction
  test's `mklink /J` returning `Access is denied` under sandbox restrictions.
  The failed operation was stopped and rerun through normal permission approval:
  `.../python.exe -m pytest scripts/tests/test_momentum_forward_publication_v3.py::test_real_windows_junction_is_rejected_and_target_kept -q`
  then **1 passed in 0.79s**. No check was skipped or weakened to resolve it.
  Plan/log are retained in this checkout's `.tmp/s7-ci-plan.json` and
  `.tmp/s7-selected-tests.log`. The later source edits were type annotations and formatting only.
- Internal read-only review identified a MEDIUM validation gap: censored unknown
  plus observed-hit previously only had an upper bound. The validation now
  requires exact equality, matching count_stock's rejection of censored loss/flat.
  The regression test and stronger paired/null fixtures passed in the runs above.

Normal commit hooks remain the commit gate; the final local commit result is
reported with the delivery SHA. Hosted CI has not run because this delivery is local-only.

## Remaining conditions

- **MEDIUM, unresolved:** existing EMA floating tails may alter exact density
  ranking/dense after uniform scaling. Universal S7 scale-invariance acceptance
  remains **UNSATISFIED**. Nothing here changes EMA, epsilon, normalization, ties,
  candidate definitions, thresholds or weekly confirmation.
- Supplied S6/M/state/membership totals are scoped counts, not proof that arms
  used identical masks, the full P/rank-pool population, reason-level coverage,
  source availability, full PIT or a fixed real-data generation. Missing upstream
  evidence is explicitly unavailable, never emitted as fabricated zeros.
- Historical cross-week assembly, first confirmation and late/multiple-week
  handling remain separately gated. No lead-lag, episode diagnostics, reader,
  market label/outcome builder, runner, final report or research verdict is supplied.
- No real labels/market/holdout/sealed data were read; no market calculations were
  rerun. Owner/data/compute admission, research ordering and full S7 acceptance
  remain unmet. This package's passing synthetic checks cannot complete S7.
