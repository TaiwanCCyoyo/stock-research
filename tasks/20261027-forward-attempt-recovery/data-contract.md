# Forward invocation journal v2

Status: code-ready infrastructure, synthetic verification only. Production deployment
and the owner-reviewed switch remain pending. This does not start F1, approve a new
research hypothesis, or change the PR61 mission/confirmatory window.

## Ownership and access

`research_core.momentum_forward_attempts_v2` owns identity, OS ownership, durable
start/terminal publication, recovery, and the v2 JSONL projection. The orchestration
in `research_core.momentum_forward_run_v2` uses the frozen v1 public `record_day`,
`freeze_deadline`, `missing_entry`, and generation API. The opt-in CLI is
`python -m scripts.record_momentum_forward_day_v2`. Existing scheduled actions and
the v1 CLI remain unchanged.

All paths below are relative to the explicitly selected forward root:

| Path                                         | Contract                                                                                                                                                              |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `attempt-journal-v2/<uuidhex>/started.json`  | Atomic no-replace publication of fsynced UTF-8 JSON before identity resolution, generation reads, producer checks, universe loading, waiting, or computation.         |
| `attempt-journal-v2/<uuidhex>/owner.lock`    | Stable per-attempt OS lock held before start publication until terminal projection completes or fails. Never delete/recreate lock files.                              |
| `attempt-journal-v2/<uuidhex>/terminal.json` | Authoritative immutable terminal; fsynced before atomic no-replace publication, then projected to JSONL. Retained for recovery and audit.                             |
| `attempts-v2.jsonl`                          | New physical ledger, complete UTF-8 JSON lines with unique `attempt_id`. Append+flush+fsync under `.attempts-v2-append.lock`, including the check for an existing ID. |
| `.attempts-v2-writer.lock`                   | Single v2 root writer across waits and day/cohort publication. Contention refuses the invocation with its own durable terminal.                                       |

Every accepted invocation has a random UUID `attempt_id`, a UTC
`attempted_at_utc`, `requested_day` (nullable), `mode` (`manual`/`scheduled`), and
`code_commit`. Start uses `unknown` when identity has not yet been resolved; the
terminal may record the resolved commit without rewriting start. `owner_protocol`
is `local-os-lock.v2` and `owner_host` identifies the local protocol owner.
An OS launch that dies before durable start is outside accepted-invocation coverage.
Files/staging evidence are retained; no cleanup or history migration runs here.

## Terminal and recovery semantics

Normal terminals retain v1 meanings: `on_time`, `late`, `cohort_recovered`,
`already_frozen`, `refused`, `failed`, and scheduled `not_recorded`. Failures and
interrupt exceptions are re-raised after terminal persistence. Manual existing-day
`FileExistsError` is re-raised; scheduled existing-day completion returns its path.
Known completion records the actual UTC `finished_at_utc`; the business clock
continues moving through v1's pre-publication check. Starting before Taipei 09:00
does not make a run completed after 09:00 on time.

Recovery acquires the **existing** local attempt's OS lock through
`artifact_store.try_os_lock/release_os_lock`; age and PIDs are never death evidence.
A busy/failed lock, missing owner lock, foreign host or unknown protocol stays
pending. Nothing kills processes. A cooperating local owner retains its OS lock
for its entire attempt; acquiring that same released lock establishes that it no
longer owns the attempt. Uncertain or externally tampered ownership needs manual
inspection, not inference from timeouts.

When the owner is gone and no terminal exists, recovery persists `interrupted`,
`completion: unknown`, `finished_at_utc: null` and an actual `recovered_at_utc`.
It preserves the original start and requested date. It does not claim an original
finish time or success based on a day file. A known durable terminal is replayed
unchanged. Check+append deduplicates by ID and exact terminal content, never by time.
An append-lock conflict leaves the terminal available for a subsequent recovery.
The logical terminal is unique; its physical JSONL projection can remain pending.

Malformed/partial JSONL, duplicate IDs, conflicting complete rows, corrupt start
or terminal JSON stop automatic reconciliation with an explicit error. Existing
bytes are preserved, including a non-newline-terminated final row. Recovery does
not truncate, rewrite, infer a lost row, or guarantee automatic exactly-once at
every possible crash point. Journal terminal files remain available for reviewed
manual reconciliation. Disk-full/permission errors can also leave projection
pending. Fsync plus native no-replace targets process crashes; filesystem/hardware
power-loss guarantees and directory metadata durability are not claimed.

## Compatibility and frozen evidence

`attempts.jsonl` is never appended or rewritten by v2. `read_attempts` can return
legacy rows followed by v2 rows with `physical_ledger` source tags. Repeated legacy
rows remain repeated; no missing attempt IDs or historic runs are invented.

The journal itself never reads/writes days, cohorts, hit/loss or market inputs.
Orchestration writes a new day/cohort only through v1 `record_day`; existing day
bytes are never replaced. A death after day publication and before cohort creation
is recorded as unknown. A later invocation may call public v1 `record_day` again;
only v1's existing frozen `recorded_late` and `recorded_at_utc` evidence can recover
its cohort. Recovery itself does not create, shift, or guess a confirmatory window.
No terminal-free historical date, including 2026-10-26, is retrospectively filled.

The root writer lock coordinates v2 writers only. Deployment must establish that
no legacy/scheduled/manual recorder still writes that root; v1 does not honor this
lock. No new calendar, atom, price, qualification or wait-deadline definition exists.
Generation checks, refused runs, busy producers and failures use synthetic sources
in tests. A stale generation is not evidence of a market holiday.

## Verification scope

Focused tests: `scripts/tests/test_momentum_forward_attempts_v2.py`,
`scripts/tests/test_momentum_forward_run_v2.py`, and unchanged
`scripts/tests/test_momentum_forward_v1.py`. Tests use temporary roots, fixture
generation/calendar/frames, and only child processes they create. They cover
crashes after start, terminal and append fsync; active/unknown owners; concurrent
invocations; frozen-day/cohort interruption; clock crossing; corrupt intent/JSONL;
and byte preservation of synthetic legacy ledger/day/cohort artifacts. The CI
domain registers the precise new production paths and both tests, with the v1
suite as a regression dependency.
