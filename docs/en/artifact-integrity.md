# Artifact integrity and verification standard

Applies to new work from the merge of this document. It changes no sealed hash,
stored result or published version; frozen evidence keeps the rules it was sealed under.

Owner decision 2026-10-15 ([record](decision-records/2026-10-15-drop-input-sealing.md)): new studies keep results with their
SHA-256 plus an input **fingerprint**, not input bytes. A result that cannot be
reproduced later is rerun on current data. The producer-input and sealed-code rows
below changed accordingly; earlier sealed studies keep the rules they used.

## 1. What a hash is for

| Risk                            | Does a hash help?                                               | What actually decides it                                                                                           |
| ------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Accidental change or corruption | Yes. Raw bytes against a stored digest.                         | A formatter, editor, line-ending conversion or partial write is the realistic cause in this repository.            |
| Using the wrong data version    | Yes, as an identifier, **if the consumer holds the pin**.       | `DataCatalog.get` takes an explicit version and manifest digest and has no "latest".                               |
| Result cannot be reproduced     | Necessary (inputs, parameters, code), not sufficient.           | Rerun and compare. Reuse equality checks are the evidence, not the digest.                                         |
| Deliberate tampering            | Only when the pin lives where the writer cannot also change it. | Reviewed Git history. A manifest next to the data, or a read-only attribute, proves consistency, not authenticity. |
| Wrong calculation               | No. A hash keeps a wrong number the same wrong number.          | Tests, invariants, independent recomputation.                                                                      |

## 2. Identity per artifact

| Artifact                          | Identity                                                                                                                                                 | Lives in                      |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| Producer inputs (parquet, sqlite) | Description of the live input read: path, size, time, rows and date range, producer as-of; no file hash since 2026-10-19 (older receipts also carry one) | `run-receipt.v1` receipt      |
| Per-stock derived inputs          | Digest of the normalized content (see below)                                                                                                             | derived cache / feature block |
| Parameters                        | Git, plus canonical-JSON digest inside the bundle identity                                                                                               | `tasks/<id>/params/`          |
| Code of a run                     | Git commit plus dirty flag; loaded modules are not hashed                                                                                                | `run-receipt.v1` receipt      |
| Results and process bundles       | Manifest of member bytes and digests; version id is the digest of the manifest                                                                           | `research_data` bundle        |
| Public result JSON in Git         | Semantic equality with the sealed result (the study's verifier, e.g. annual `verified_result`), not raw bytes                                            | `tasks/<id>/`                 |
| Reports and prose                 | Git only                                                                                                                                                 | `tasks/<id>/`                 |

Normalization for content digests must keep every distinction that matters: floats
by exact value (`float.hex()`), missing distinct from zero, dates with their type,
a unique sort key (reject duplicates instead of sorting through them), `bool`
never equal to a number, and no duplicate JSON keys, `NaN` or `Infinity`.

## 3. Format before hash

1. Bytes that are hashed are the final bytes. Produce them with a deterministic
   writer and store them outside any formatter-managed tree, or format first and
   hash what was formatted.
2. Sealed bytes live in `research_data` or `research_cache`. Git carries conclusions,
   the pin needed to find them, and code. A JSON file in Git is a reading copy.
3. A completed run's sources are never reformatted and re-pinned. A formatted or
   changed implementation is a new version with recorded lineage.
4. Do not bind a derived artifact's identity to live shared-library files that a
   pure formatting edit would change. Prefer an explicit definition version plus a
   stored source snapshot. Do not add a new live file to an identity list.
5. Do not add a per-path formatter or line-ending exception for a new artifact. If a
   new artifact seems to need one, it belongs in the data store instead.

## 4. Updating data

New stocks, history or corrected events produce a **new immutable version**; the old
version and every result that cites it stay readable. Inside an existing version any
byte change is an error, whoever made it and however well meant, so no judgement
about intent is needed. Producer live files change daily by design and are not
hash-protected; a study fingerprints what it read (`research_core/run_receipt.py`) and
reads only while the producer is idle (`research_core/live_producer.py`).

## 5. Verification cost rules

| When                                  | What                                                                                                                                                                                                                                                                                                             |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Publishing a version                  | Verify every member once.                                                                                                                                                                                                                                                                                        |
| First use in a process                | Verify the bundle once. `DataCatalog.get_verified` returns the manifest of that one verification; it keeps no memo, so a caller that needs a bundle twice keeps the result itself.                                                                                                                               |
| A reader that consumes bytes          | Hash or re-verify the bytes it consumed, not a separate earlier pass.                                                                                                                                                                                                                                            |
| Before a report or PR claims a result | Run the study's `verify` once.                                                                                                                                                                                                                                                                                   |
| Across sessions                       | No cached "verified" state until a measurement shows the need. Any such cache must be keyed by the manifest digest and each file's size, `mtime_ns` and file id, miss on any difference, and never be used to publish or to certify. Size, modification time or a read-only attribute alone is not verification. |

- Verifying the same version twice inside one call is a defect, not a safety margin.
- Build `DataRoots` and `DataCatalog` once per process. The worktree isolation walk
  (`validate_worktree`) is linear in entries and costs about 1.5 s for a 28k-entry
  worktree, but it is still not something to repeat per call. The annual `run_study.py`
  still builds one per phase (up to three walks, about 1.5 s each); it is left as
  sealed because its source is part of the run's evidence.
- Before adding a verification pass, record wall and CPU time by phase (disk read,
  SHA, JSON, path checks, other) in the phase receipt. An unmeasured pass is not
  justified by "it is only a hash"; the first version of this review found 180 s
  of path checking behind 0.2 s of hashing.
- New traversal code must keep the exact predicate of the check it replaces and add
  a differential test against that check.

## 6. Pins in Git

A pin is `data_id`, `version_id` and the manifest digest, one per consumed bundle.
Never embed a previous pin or entry (a nested chain grew a pin from 20 KB to 121 KB
in three versions). Full digests in tracked JSON count against the secret-scanner
baseline, which is capped at 1 MiB; adding to the baseline is an owner decision and
is recorded in the PR that needs it. Prose may refer to a version by a short prefix.

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

1. Inputs are fingerprinted in the run receipt; results carry their SHA-256.
2. Nothing hashed will be touched by a formatter afterwards.
3. Each bundle is verified once per process; the runner builds its catalog once.
4. Public JSON in Git is checked semantically against the sealed result.
5. Phase timings are in the receipt; unknowns are marked as unknown.
