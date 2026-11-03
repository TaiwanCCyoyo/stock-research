# L1 recovery stability checks — 2026-11-03 engineering slice

This slice reduces repeated inventory-wide filesystem checks in the bounded
recovery pilot. It changes no L1 cohort, cooldown, outcome, denominator, volume
condition or comparison contract. Validation uses synthetic data only; the saved
five-stock results and their archive remain unchanged.

## Dependency and ownership

The dependency is [PR #155](https://github.com/TaiwanCCyoyo/stock-research/pull/155)
at `a18b3f9a4ab97104e57585e8774f980179c36bba`, which includes main
`edbe7e242c11bc3a01ac16dc65168208af7d1548`. At implementation time it was open
and ready. This follow-up uses the separate `codex/l1-recovery-stability` branch
and targets main; it must not merge before #155. Its isolated review range starts
at that dependency head. Normal main synchronization after the dependency merges
must preserve both changes without force-pushing.
Delivery: [draft PR #157](https://github.com/TaiwanCCyoyo/stock-research/pull/157).

The coordinator owns the publication lifecycle, this record and the asset index.
A Terra worker owns the recovery reader; a SOL worker owns synthetic reader and
operation-count tests; another SOL worker owns publication tests. A separate
Terra worker reviews mutation and path boundaries. Frontend routes and comparison
definitions remain with their established owners.

## Check contract

The input tracker still checks every receipt read before and after parsing, and
every selected payload against its saved size/hash before reading. It verifies all
retained L1 payload hashes during inventory, including unselected retained stocks.
Each actual read still checks file identity and path safety. Directory identity
uses device, inode and type; directory mtime changes from legitimate sibling
creation are ignored. Alias/reparse/hardlink checks are refreshed at every gate.

There are three inventory-wide input checks: inventory completion, immediately
before output creation, and after payload writes before the worker audit. Each
stock's entry and exit checks cover common receipts and that stock's receipts and
read payloads. An unselected but observed file changed between stocks is rejected
at the next global gate. No global population is dropped from the tracker.

These are point-in-time observations, not a filesystem lock or continuous mutation
monitor. Unselected files changed after the worker's last global observation are
not rechecked by the supervisor. Its existing selected-input fingerprints are
checked around receipt publication. Changes restored between observations,
coordinated replacement of data and metadata, and independent source authenticity
are outside this contract. A later source update does not invalidate a finished
historical result.

Output descriptors are derived from serialized bytes before writing. Shared
`publish_generated_bytes` provides verified, no-replace publication through a
fresh scratch directory beside the payload directory. The worker compares outputs
to those descriptors before and after audit publication; the supervisor requires
the exact selected-stock/table inventory and verifies payload, audit and job bytes.
It writes a staging receipt, compares its result descriptors with the original
expected bytes and paths, verifies the receipt bytes, and publishes without
replacement. It checks receipt and result files again before marking the run
complete. Ancestor identities are retained throughout each process's observations.

Failure before final receipt publication leaves no final receipt. A change detected
after that atomic publication leaves the receipt and failure evidence for diagnosis
but does not mark the scratch run complete; receipt existence alone is not success.
No rollback removes diagnostic or unrelated files.

The worker audit adds `payload_descriptors` (portable path, bytes, SHA-256) and
`stability_checks` (full/scoped sweep and observation counts). The formal comparison
JSON schema and synthetic UI fixture are unchanged. Existing saved pilot artifacts
remain readable without migration or rewriting; the new supervisor expects the new
worker's descriptors for new executions only.

## Synthetic acceptance and measurement

The tests cover file replacement with preserved bytes/mtime, normal ancestor
replacement preserving the leaf inode, actual Windows junction rejection with an
unchanged external sentinel, selected hash mismatches, and unselected changes
between stocks. A two-stock differential comparison requires identical events,
conditions, memberships, market classifications, Q1 summary/annual and marginal
summary/annual results under the former global schedule and the scoped schedule.
Publication tests inject mutations into payloads, audit, job metadata and receipt,
including the final publication boundary, and require failure without completion.

Operation counts are measured on synthetic files for 1, 2 and 5 selected stocks
and 20 or 100 unrelated observed files. Both schedules use the same current path
checker, isolating scheduling cost from the added ancestor checks. This is not a
measurement of the old binary's total runtime, physical disk IO, or market speed.
The reproducible matrix is in
`scripts/tests/test_pattern_scan_recovery_stability_v1.py`.

Measured on Windows with Python 3.13.18 (arrows mean former to scoped schedule):

| Stocks | Background files | Background observations | All file observations | Background leaf `lstat` calls |
| ------ | ---------------- | ----------------------- | --------------------- | ----------------------------- |
| 1      | 20               | 100 → 60                | 115 → 75              | 400 → 240                     |
| 2      | 20               | 140 → 60                | 182 → 90              | 560 → 240                     |
| 5      | 20               | 260 → 60                | 455 → 135             | 1,040 → 240                   |
| 1      | 100              | 500 → 300               | 515 → 315             | 2,000 → 1,200                 |
| 2      | 100              | 700 → 300               | 742 → 330             | 2,800 → 1,200                 |
| 5      | 100              | 1,300 → 300             | 1,495 → 375           | 5,200 → 1,200                 |

The measurement window excludes fixture construction, initial registration and
payload ingestion/hashing. Gate-only hash calls are zero under both schedules;
the payload verification code still performs the saved hash checks at ingestion.
The observed four leaf `lstat` calls per observation reflect the current shared
path checker; the regression calibrates that count rather than assuming a fixed
platform implementation.

Local validation passed in bounded groups: 38 recovery cases, 17 filesystem/count
cases and 53 worker/supervisor cases (108 total), plus 420 CI-selection cases.
The two actual Windows junction cases needed a single scoped execution approval
after sandbox denial and then passed; no permissions or ACLs were changed. An
independent review identified the missing post-publication result recheck; the
fix and four mutation cases were re-reviewed with no remaining actionable
HIGH/MEDIUM correctness findings in this slice.

No real pilot, published market-artifact verification or full-market parity run
is part of this synthetic-only task. Historical #155 verification remains prior
evidence, not a claim that this implementation was measured on market data.

## Next real-data boundary

A real-data recheck requires separate execution authorization, a clean committed
executor containing the merged dependency and this slice, the same saved source,
input and label pins, and readable original checkpoints. Use a fresh labelled
shared scratch run. Start with the existing maximum five-stock selection, one
worker, numerical threads set to one, 600 seconds, 2 GiB job committed memory and
128 MiB total output. Record wall/CPU, process memory, IO counters, phase times and
the new operation counts, and require the same retained-event and Q1/marginal
parity checks as the original pilot. Existing historical exposure still applies.

No elapsed-time improvement or full-market execution budget is inferred here.
Full-market recovery and four-cell evaluation require their own parity, resource
evidence and authorization. This change enables neither downloads, deployment,
permission changes nor schedules.
