# Q2–Q6 continuation on shared scratch

**Status 2026-10-28: research remains incomplete; the owner paused the run for
[exact count-plan optimization](count-plan-performance-v5.md).**
PR #97 memory recovery passed actual four-worker capacity and resumed the run.
The latest amendment records the preserved 12 terminal phases, B3's 16 completed
groups, measured bottleneck and optimized-code restart gates. The earlier
[bounded parallel execution](parallel-execution-v5.md) contract still governs
worker limits, deterministic publication and the 8 GiB Job cap.
The single-worker process started below was stopped, with its checkpoints retained.
This implements package D's runner changes from
[the current handoff](../20261024-data-homes-and-scratch/codex-handoff.md#d-pr17-續跑程式修改與重跑).
The numerical definition stays `pattern-scan-local-remaining.v5`. The scratch run
name `q2-q6-v6` identifies the new execution location, not a changed calculation.
Historical receipts, pinned reports and the original input files remain unchanged.

## Execution and progress

The public CLI accepts an exact scratch run directory registered through
`scratch_runs.create_run()`, as well as the legacy calling checkout's `.tmp/`.
For shared scratch, the launcher holds `scratch_runs.open_run()` for its whole
lifetime, including worker startup and teardown. The numerical coordinator and all
pool descendants stay inside the existing 8 GiB Windows Job; the host must have
another 4 GiB available. The
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

PR #64, #66, #71 (runner), #73 (study cards), #78 (run registration) and #81
(parallel pools) are merged. Primary `main` is updated through #81 (`24fff65`). The session-owned
`pr17-scratch-continuation` worktree is now reused on
`codex/pr17-capacity-receipt` for PR #82. It remains available for review and the
paused continuation. The old `pr17-retention-review` worktree also stays.

The registered run is
`D:/StockData/stock-research/scratch/20261013-pattern-scan/q2-q6-v6/`, owned by
`codex`. Its sole input dependency is the original primary-checkout input directory;
no input copy was made. `retained-output-copy.json` in the run records all 346
verified output copies (410,826,077 bytes), their original paths and SHA-256s.
The copy took 9.825 wall seconds / 3.922 CPU seconds. It includes six terminal
receipts, all their final files, the five families' selections and 49 completed
groups, and the ten existing phase-start records. No old top-level progress,
incomplete group staging or `_temporary/` was copied. The study card now links
to this run; its verdict and delivery state still describe an unfinished study.

The original numerical launcher started from clean registration commit `760081b`,
using one worker and the default ten-day timeout. The owner stopped it before
parallel preparation; all its descendants exited, and 576 completed event
projections remain available. Its stdout/stderr and PID are retained
in `continuation.stdout.log`, `continuation.stderr.log` and `launch.json` inside
the run. `run.json` and the OS writer lock are the authority for current liveness;
this registration alone does not establish that a worker is still running.

The accepted engineering probe selects four workers. After follow-up PR #82 merges,
resume the same run from clean merged code with the bounded full-market capacity
invocation first (see the runtime amendment's capacity gate):

```powershell
uv run python -m scripts.run_pattern_scan_remaining --stock-result D:/Project/stock-research/.tmp/pattern-scan-execution/full-2010-20261016-retention-v3/phase-stock-result.json --output D:/StockData/stock-research/scratch/20261013-pattern-scan/q2-q6-v6 --workers 4 --target B2 --phase conditions --timeout-seconds 21600
```

Remaining delivery follows
[package D](../20261024-data-homes-and-scratch/codex-handoff.md#d-pr17-續跑程式修改與重跑):

- Continue one coordinator in `DEFAULT_TARGET_ORDER`, using its bounded pool for
  stock projections and conditions groups. Reuse the same command and run
  after an interruption; completed groups and phases are adopted without recomputing.
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
