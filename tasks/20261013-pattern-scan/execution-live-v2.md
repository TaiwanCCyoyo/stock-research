# Pattern-scan live-input execution v2

This addendum applies the [2026-10-15 owner policy](../../docs/en/decision-records/2026-10-15-drop-input-sealing.md)
to PR #17. The approved [mission](mission.md), Q1–Q6, H1=HHHL v4, L3=legacy F33,
cohorts, conditions, controls and viewed-period records remain unchanged.
The calculation calendar stays **2010-01-04 through 2026-10-12**. Later dates
describe the raw source fingerprint; they do not extend the study.

## Takeover and integration

Session `01a13ddd-a434-71f2-a54c-1ebdb3cdbe35` takes over the original
`D:/Project/stock-research/.worktrees/research-data-entry` worktree and
`codex/pattern-scan-execution` branch. Before writing, it confirmed HEAD
`56bb62c2`, no uncommitted research changes or Git lock, the original session's
completed turn, no Python/uv writer, and both `StockProject-*` tasks Ready.
These are point-in-time checks. No other worktree was inventoried or cleaned.

Normal fetch found main `758348df`. Merge `0a8dc6f` retained both new tests at
the only conflict, in the CI domain list. The 101 CI scope tests and normal
merge hooks passed. Before reader adaptation, all 16 published-artifact checks
passed; current-head tests and hosted review are separate evidence.

The historical initialized producer submodule and seeded inputs remain in place.
Its checkout differs from the newly merged gitlink, so Git reports a dirty
submodule. New research does not consume that checkout. It is not updated,
deinitialized or removed; run receipts retain the truthful dirty flag. Task-owned
research code is committed before measured execution.

## Live source access

`pattern_scan_live_inputs_v2.load_live_inputs` resolves only through
`producer_data_root()`. The checked root here is
**`D:/StockData/stock-data-downloader`**, with no appended `data` directory.
The inherited process has no `STOCK_PRODUCER_DATA_ROOT`; the old seeded worktree
therefore deliberately refuses automatic discovery. `--producer-root` sets the
value only in the invoking process and its owned children.

The reader fingerprints the three sources actually consumed before loading:
`price_daily.parquet`, `symbol_meta.sqlite` and `corporate_actions.sqlite`.
SQLite uses read-only transactions, without `immutable=1`, serialization or
database-image copies. Parquet uses `read_stable`. The read phase rechecks
recorded file/WAL identities before its receipt. It reuses the approved calendar,
official-source filter, reference inventory and
`price-basis.v2/reference_factor_adjusted`. Current metadata is not historical
membership or a PIT certification.

`assert_producer_idle` refuses weekday 18:00–18:45 Asia/Taipei and running
`StockProject-*` tasks. This workflow changes no scheduler state and deletes no
SQLite sidecar. Read-only SQLite may create its own WAL/SHM files.

## Read phase and numerical phases

The short producer-read phase computes necessary adjusted-price checkpoints and
0050, then finishes with `producer-read-receipt.json`. This normal
`run-receipt.v1` retains the live fingerprint, code commit/dirty flag, definition,
parameters, mission and result hashes. No new bundle stores producer input bytes.

Later numerical phases fingerprint those task-owned derived prices and retain
the original producer fingerprint through `derived-preparation.json`. They do
not reopen today's producer. Computation can cross the producer write window
after the read phase completes. Derived prices are computational checkpoints,
not raw-input archives or a guarantee of exact future recomputation. Formal
reusable versions still publish additively to the primary catalog/cache.

`input_id` excludes capture time and includes actual source identity, calendar,
cutoff and price policy. Legacy prepared receipts retain their manifest contract;
new `pattern-scan-prepared.v2` receipts use the fingerprint identity. The two
forms cannot substitute for one another.

`pattern_scan_git_source_v2` records Git commit/dirty flag, runtime, platform and
numerical thread limits. New owned Windows Jobs import the task checkout
normally, without a new source ZIP or loaded-module hash inventory. Legacy
sealed dispatch, archived implementations, packets and receipts retain their
bytes. Directly pinned preparation helpers/tests are unchanged. Completed v2
results are checked by their hashes, without reopening live inputs or requiring
the current checkout to reproduce the historical run.

## Public phases

Use `uv run python -m scripts.pattern_scan_live`, with explicit primary/data roots,
run ID and `--calculation-authorized`. The script delegates to
`research_core.pattern_scan_run_v2`.

| Mode              | Scope and prerequisite                                                                                                  | Retained result                                                       |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `profile`         | Metadata/coverage strata, 1/2/4-worker parity, at most four global-preflight stocks                                     | Producer-read receipt, resource profile and native coordinator memory |
| `storage-profile` | Completed representative preparation/profile; same four stocks, all their events and Q1–Q6 paths; no formal publication | Full representative file sizes/rows and phase resources               |
| `prepare`         | Full reference set; measured same-source/input profile and complete capacity plan                                       | Derived preparation and producer-read receipt                         |
| `stock`           | Full preparation in the same run, valid profile and capacity plan                                                       | Stock/shared versions; no full-study claim                            |
| `all`             | The same prerequisites as `stock`                                                                                       | Full analysis versions and complete-study receipt on success          |

`prepare`, `stock` and `all` may use the same run ID: their request, result,
response and run-receipt names are phase-specific. Representative preparation
cannot become full preparation. Missing/mismatched ancestry fails. Completed
checkpoints and failed staging remain; final receipts publish atomically without
replacement. An interrupted producer-read receipt can finish only while the
producer is idle and the original fingerprint still matches.

Resource observations are not research findings. Full-market Q1–Q6, independent
event/candidate audits and the final report remain pending.

The streaming followup finalizer now enumerates registered cells lazily instead
of running the independent batch oracle over empty frames to construct a
template. It retains the same six tables, order, zero cells, counts and exact
raw-sample quantiles. DEBUG-disabled feeds no longer traverse accumulated sample
buffers merely to construct a log argument. Differential tests compare every
table, including dtypes and missing values, against the unchanged batch oracle;
the new registry test checks that unconsumed table families are not expanded.

The first v2 profile attempt was stopped before derived preparation completed,
after a static delivery check found that report publication still required the
legacy source ZIP. Its request remains under
`.tmp/pattern-scan-execution/profile-2010-20261015-live-v2`; its owned coordinator
and children were confirmed stopped before source edits. The corrected live
report publishes Git/request, producer-read receipt and preparation/profile/
capacity metadata, with no source ZIP. Legacy report inputs remain unchanged.

The shared catalog snapshot
`68e541007b46afddd68a40e0312cfb3181aea66fc0c17a4286c7385602f12e12`
contains no completed 2010-onward pattern-scan assets. Its 2019-onward
price/pattern versions, 0050-only context ending 2026-10-02, and annual-rotation
outputs differ in scope, calendar or definition. They are discovery evidence,
not interchangeable blocks for this scan. Existing frozen versions remain.

Numerical run receipts also fingerprint the actual phase request and any
resource profile/capacity plan consumed; memory limits and timeout are retained
as parameters. These task-owned metadata reads do not reopen the producer.

## Capacity gate

Takeover measured **182,916,579,328 free bytes** on D:. The old 12.6 GB free
value and v3 capacity verdict remain historical.

The v3 six-stock output was 18,752,934 bytes: linear extrapolation to 1,942
reference securities is about 6.07 GB. Four-stock event payloads were
86,967,134 bytes, extrapolating to 42.22 GB. Formal publication physically copies
payloads, so sources and published payloads coexist: events alone suggest
approximately **84.45 GB**, before other components. These are sample estimates,
not full-market measurements or upper bounds.

| Coexisting component                                                 | Required evidence                                             |
| -------------------------------------------------------------------- | ------------------------------------------------------------- |
| Derived prices, stock checkpoints and six stock bundles              | Per-stock bytes, variation and extrapolation                  |
| Global barrier and published features/market sidecars                | Stock/date grid, serialized bytes and constant sidecars       |
| Event checkpoints and event-outcomes bundle                          | All targets per stock, including the publication copy         |
| Q1–Q3 full/annual/candidate summaries and report copies              | Zero-cell and annual/drop serialization                       |
| Q4 episodes, Q5–Q6 observations/quantiles/summaries and their copies | Uncapped representative event work; memory separate from disk |
| Retained failed staging and reserve                                  | Explicit allowance without deleting existing evidence         |

`pattern_scan_capacity_v2` requires all twelve estimates with evidence and a
positive reserve. Unknown components or insufficient free space block full-market
starts. `storage-profile` supplies missing representative measurements; the plan
must state extrapolation assumptions and uncertainty before formal execution.
No old result or unrelated worktree is deleted to meet it. A different storage
root or retirement of existing evidence requires the owner's decision.
