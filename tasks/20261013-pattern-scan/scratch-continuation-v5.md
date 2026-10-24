# Q2–Q6 continuation on shared scratch

**Status: runner implementation only; the remaining research has not started.**
This implements package D's runner changes from
[the current handoff](../20261024-data-homes-and-scratch/codex-handoff.md#d-pr17-續跑程式修改與重跑).
The numerical definition stays `pattern-scan-local-remaining.v5`. The scratch run
name `q2-q6-v6` identifies the new execution location, not a changed calculation.
Historical receipts, pinned reports and the original input files remain unchanged.

## Execution and progress

The public CLI accepts an exact scratch run directory registered through
`scratch_runs.create_run()`, as well as the legacy calling checkout's `.tmp/`.
For shared scratch, the launcher holds `scratch_runs.open_run()` for its whole
lifetime, including worker startup and teardown. One numerical worker stays inside
the existing 8 GiB Windows Job; the host must have another 4 GiB available. The
default timeout is ten days, rather than two, to accommodate the previously
measured six-day continuation. `--timeout-seconds` can still bound a shorter retry.

After each completed or adopted conditions group, the worker writes the current
`step`, `total` and `<family> conditions` label into `progress.json`. The launcher
relays changes to the run's `heartbeat()` while holding its writer lock, and repeats
the current heartbeat at least every minute during a long group. Only the launcher
writes `run.json`; the numerical worker writes the ordinary continuation metadata.
Q4 and followup report phase labels while they run. An interruption leaves the run
`running` and resumable. All twelve families' three final phases must be verified
before the launcher marks the run `complete`.

Top-level progress identity compares only `source_id` and `input_id`. Published
and staged final results resolve by their relative `results` keys under the current
phase root, preserving directories such as `pattern%3Aunion-h126/`; historical
absolute `path` values are descriptive. Containment, recorded sizes and final-file
SHA-256 verification still apply. Published receipts are never rewritten. Copied
v5 phase-start records retain their original `code`, with retry commits appended
idempotently to `execution_codes`.

Completion never releases `pr17-pattern-scan`. `release_pending` remains true until
the separate owner-controlled delivery and merge steps have finished.

## Read-only readiness check, 2026-10-24

The original stock/global metadata agrees on 1,942 securities. All 19,424 required
stock tables, global tables and sidecars exist; none are missing. This existence
check took 1.487 wall seconds / 1.406 CPU seconds and did not hash inputs or run
market calculations. Schema and calendar checks remain with the existing reader
when execution begins; file existence alone is not a numerical validation.

The retained outputs match the handoff:

| Family | Terminal phase receipts | Completed conditions groups to adopt |
| ------ | ----------------------- | ------------------------------------ |
| B1     | 3                       | already final                        |
| H1     | 3                       | already final                        |
| B2     | 0                       | 19                                   |
| B4     | 0                       | 6                                    |
| P1     | 0                       | 6                                    |
| R1     | 0                       | 9                                    |
| R3     | 0                       | 9                                    |

B1 has phase-start records for q4 and followup only; its completed conditions
receipt already records the original executor. No missing phase-start record is
invented for a final phase. H1 has all three. Each unfinished family has its
conditions phase-start record. The original generation hold is present.

## Pending execution and delivery

PR #64 and #66 are merged. This runner change must merge, and package A's study
cards must be available, before the remaining ten families start. No actual scratch
run has been created, no old output copied and no live producer read by this change.

After those gates, use the run creation, verified copy and execution steps in
[package D](../20261024-data-homes-and-scratch/codex-handoff.md#d-pr17-續跑程式修改與重跑):

- Create `20261013-pattern-scan/q2-q6-v6`, with the original primary-checkout input
  directory in `depends_on`; read it in place.
- Copy B1/H1 final outputs, the five unfinished families' completed groups and all
  existing phase-start records, retaining nested directories and comparing every
  copied file's SHA-256. Do not copy `_temporary/`, incomplete group staging or the
  old top-level `progress.json`.
- Run one process in `DEFAULT_TARGET_ORDER`, using `--output` set to that run's
  path and `--stock-result` set to the original `phase-stock-result.json`. Reuse
  that same command and run after an interruption. Register `scratch_run` in the
  study card when execution starts.
- Deliver the final tables, receipts, report and study card as specified in the
  handoff. Release the hold and mark `delivered` only after that delivery merges.
  Removal of the old worktree or original inputs still needs the owner's approval.

## Verification

`uv run pytest scripts/tests/test_pattern_scan_local_remaining_v5.py
scripts/tests/test_pattern_scan_local_conditions_v5.py
scripts/tests/test_scratch_runs.py -q`: **102 passed in 24.50 seconds** on Windows.
The tests exercise nested receipt relocation and tampering, source/input identity,
original and retry executors, group reuse, the real scratch writer lock across CLI
launch and failure, progress relay, and retained holds after complete computation.

`uv run python -m scripts.verify_published_artifacts` passed before and after this
change with the same checks passing. CLI `--help` also succeeds. These are reader
compatibility and synthetic execution checks; they do not claim the remaining
market calculations or their delivery are complete.
