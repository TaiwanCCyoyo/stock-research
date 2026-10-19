# Artifact integrity and verification standard

Applies to new work. It changes no sealed hash, stored result or published version;
frozen evidence keeps the rules it was sealed under.

## 0. What a new study records (owner decision 2026-10-19)

Owner decisions 2026-10-15 ([record](decision-records/2026-10-15-drop-input-sealing.md))
and 2026-10-19: **hash final results only.** A new study records exactly three things in
its `run-receipt.v1` (`research_core/run_receipt.py`):

1. **Final results**: the SHA-256 of each result file the study publishes, so an
   accidental edit is detectable.
2. **What it read**, as information: a description of each live producer input (path,
   size, modification time, rows and date range, producer as-of; no file hash) and the
   record a shared-data reader returns (`write_run_receipt(..., shared_data=[record])`:
   family, generation, as-of). These say which data and version were used. They are not
   copies, the study does not hash them, and they never decide whether a finished result
   may be saved: an input that changed during the run is listed in the receipt
   (`inputs_changed_during_run`), not refused.
3. **How it ran**: Git commit plus dirty flag, definition, parameters and
   preregistration.

A new study does **not**:

- hash, manifest or write per-file receipts for intermediate files (per-stock parts,
  phase outputs, worker files, caches, previews);
- verify intermediate files between phases or bind a later phase's identity to them;
- copy inputs or source code into a snapshot;
- treat a later producer update or shared-data generation as invalidating a finished
  result, or rerun a whole study because a generation it read was deleted. A study that
  still reads one generation for days may hold it
  ([shared data](research-derived-data.md#維護中的共用衍生資料)); if a remaining step needs
  a generation that is gone, only that step reads the current one or is redone.

Intermediate files are disposable working data. If they are lost or no longer match,
the study reruns the step; it does not prove their bytes.

Studies sealed before these decisions keep their own hashes, manifests and
verification. Do not remove, re-pin or weaken them, and do not copy their pattern into
new work.

## 1. What a hash is for

| Risk                            | Does a hash help?                                               | What actually decides it                                                                                           |
| ------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Accidental change or corruption | Yes. Raw bytes against a stored digest.                         | A formatter, editor, line-ending conversion or partial write is the realistic cause in this repository.            |
| Using the wrong data version    | Yes, as an identifier, **if the consumer holds the pin**.       | The receipt names the producer inputs and the shared generation that were read.                                    |
| Result cannot be reproduced     | Necessary (inputs, parameters, code), not sufficient.           | Rerun on current data and compare. Equality checks are the evidence, not the digest.                               |
| Deliberate tampering            | Only when the pin lives where the writer cannot also change it. | Reviewed Git history. A manifest next to the data, or a read-only attribute, proves consistency, not authenticity. |
| Wrong calculation               | No. A hash keeps a wrong number the same wrong number.          | Tests, invariants, independent recomputation.                                                                      |

## 2. Identity per artifact (new work)

| Artifact                          | Identity                                                                                                                                                                              | Lives in                 |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| Producer inputs (parquet, sqlite) | Description of the live input read: path, size, modification time, rows and date range, producer as-of; no hash (receipts before 2026-10-19 also carry a file SHA-256 and stay valid) | `run-receipt.v1` receipt |
| Maintained shared derived data    | The reader's record (family, generation, as-of), kept as information                                                                                                                  | receipt `shared_data`    |
| Parameters                        | Git                                                                                                                                                                                   | `tasks/<id>/params/`     |
| Code of a run                     | Git commit plus dirty flag; loaded modules are not hashed                                                                                                                             | `run-receipt.v1` receipt |
| Final results                     | SHA-256 of each published result file                                                                                                                                                 | `run-receipt.v1` receipt |
| Intermediate files                | None                                                                                                                                                                                  | not recorded             |
| Reports and prose                 | Git only                                                                                                                                                                              | `tasks/<id>/`            |

A maintained shared family checks its own published files against its `status.json`
when they are read. Those files are the family's final results, so this is the
results-only rule applied to the family; a study adds no source hashing on top.

Legacy identities stay valid for the artifacts that use them and are not a pattern for
new studies: content digests of per-stock derived caches and feature blocks,
`research_data` bundle manifests (version id = manifest digest), and semantic equality of
public result JSON with a sealed result. Content digests there normalize floats by exact
value (`float.hex()`), keep missing distinct from zero, keep dates typed, use a unique
sort key, never equate `bool` with a number, and reject duplicate JSON keys, `NaN` and
`Infinity`.

## 3. Format before hash

1. Bytes that are hashed are the final bytes. Format result files first and write the
   receipt afterwards, as `run_receipt` does.
2. A completed run's results are never reformatted and re-hashed. A changed result is a
   new run with its own receipt.
3. Do not bind any identity to live shared-library files that a pure formatting edit would
   change; the code identity is the commit.
4. Do not add a per-path formatter or line-ending exception for a new artifact. If a new
   artifact seems to need one, it does not belong in Git.

## 4. Updating data

Producer files change daily by design and are not hash-protected; a study records what
it read and reads only while the producer is idle (`research_core/live_producer.py`).
Maintained shared families are rebuilt as a new generation on each update. A finished
result stays valid after that; a study still reading an older generation holds it, and a
remaining step whose generation is gone reads the current one or is redone. Legacy
immutable versions (`research_data`, `research_cache`) stay readable; any byte change
inside one of them is an error.

## 5. Verification cost rules

| When                                  | What                                                                                                                                                 |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| During a study                        | Nothing for inputs or intermediate files. A shared family checks its own files once per process when read.                                           |
| Before a report or PR claims a result | Check the final results against the receipt once (`run_receipt.changed_results`), or run the legacy study's `verify` once.                           |
| Legacy bundles                        | Verify a bundle once per process when first used; `DataCatalog.get_verified` keeps no memo, so a caller that needs it twice keeps the result itself. |
| Across sessions                       | No cached "verified" state until a measurement shows the need. Size, modification time or a read-only attribute alone is not verification.           |

- Verifying the same thing twice inside one call is a defect, not a safety margin.
- Build `DataRoots` and `DataCatalog` once per process. The worktree isolation walk
  (`validate_worktree`) costs about 1.5 s for a 28k-entry worktree; do not repeat it per
  call. The annual `run_study.py` still builds one per phase; it is left as sealed because
  its source is part of the run's evidence.
- Before adding any verification pass, record wall and CPU time by phase. An unmeasured
  pass is not justified by "it is only a hash"; the first version of this review found
  180 s of path checking behind 0.2 s of hashing.
- New traversal code must keep the exact predicate of the check it replaces and add a
  differential test against that check.

## 6. Pins in Git

A legacy pin is `data_id`, `version_id` and the manifest digest, one per consumed bundle.
Never embed a previous pin or entry (a nested chain grew a pin from 20 KB to 121 KB in
three versions). Full digests in tracked JSON count against the secret-scanner baseline,
which is capped at 1 MiB; adding to the baseline is an owner decision and is recorded in
the PR that needs it. Prose may refer to a version by a short prefix.

## 7. Measured reference (single machine, warm cache, 2026-10-13)

| Step                                             | Before                             | After                         |
| ------------------------------------------------ | ---------------------------------- | ----------------------------- |
| Worktree isolation walk (28,472 entries)         | 180.8 s CLI run, 215 s timed alone | 1.4–1.8 s                     |
| `verified_result`, one public result             | 0.64–0.89 s                        | under 1 s, not re-timed alone |
| SHA-256 of a 205 MB parquet                      | 0.13 s                             | unchanged                     |
| `run_study.py verify`, end to end                | 180.8 s                            | 1.9–2.0 s                     |
| `scripts.verify_published_artifacts` (16 checks) | 22 s                               | 21 s                          |

Cold-disk hashing time was not measured. Re-measure before relying on these.

## 8. Checklist for a new study

1. The receipt has the input descriptions, any shared-data records, the commit, and a
   SHA-256 per final result file; nothing about the inputs blocks saving it.
2. No intermediate file is hashed, manifested or re-verified.
3. Result files are formatted before the receipt is written.
4. A generation still read over several days is held, and released when the study ends.
5. Phase timings are recorded; unknowns are marked as unknown.
