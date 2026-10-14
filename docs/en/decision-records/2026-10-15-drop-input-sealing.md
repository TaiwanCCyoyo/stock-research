# 2026-10-15: Drop input sealing and exact re-computability

**Status:** owner decision, 2026-10-15. Applies to new work from the merge of PR #20.
The loss of exact recomputation for new studies is intended, not a regression.

## Decision

The owner decided that research no longer stores its inputs so that a study can be
recomputed bit for bit. Methods change continually, so bit-exact recomputation of old
studies has little value compared with its storage and maintenance cost.

Each study keeps:

- its results, each with a SHA-256 so that accidental edits are detectable;
- the code commit (with a dirty flag), definition, parameters and preregistration;
- an **input fingerprint**: path, SHA-256 (files) or row counts (SQLite), date range,
  and producer as-of time for each input read. The fingerprint records identity only,
  never bytes.

When a result cannot be reproduced later, the experiment is rerun on current data. The old
result stays as a historical record, labeled with its fingerprint. Material that cannot
be reacquired, such as the owner's manual labels, is still kept. Caches are
performance-only and can be rebuilt.

Research worktrees read the live producer root read-only through
`research_core/producer_data.py::producer_data_root()`. Nothing is copied or linked, and no
submodule needs to be initialized. `research_core/run_receipt.py` writes the fingerprint and
result hashes. It identifies the inputs read and the code commit only. It does not hash
loaded modules, so a source edit does not invalidate a receipt or force a rebuild.

## What stays

- Holdout and viewed-period discipline (`docs/en/research-registry.json`, owner contract).
- Result hashes, to detect accidental edits.
- Never deleting or rewriting existing data, and keeping stored results readable.
- Existing frozen datasets, sealed versions, research caches and worktree snapshots stay
  where they are. Retiring them needs a separate owner-approved cleanup.

## Measured cost that motivated it

- **Storage:** an audit on 2026-10-14 found about 41 GB across six stock-research
  worktrees. The post-checkout hook copied about 5 GB of live producer inputs into every
  new worktree. A bug left about 4.47 GB of scratch SQLite behind on each seed (fixed
  separately in PR #18).
- **Composition of one read set (measured 2026-10-15, 4,990,335,543 bytes in 2,088 files):**

    | File                                                                                  | Size          |
    | ------------------------------------------------------------------------------------- | ------------- |
    | `institutional.sqlite`                                                                | 3.83 GB       |
    | `monthly_revenue.sqlite`                                                              | 0.62 GB       |
    | 2,080 `*_day.csv`                                                                     | 0.30 GB       |
    | `price_daily.parquet`                                                                 | 0.20 GB       |
    | `corporate_actions.sqlite`, mapping/classification JSON, report, `symbol_meta.sqlite` | about 0.04 GB |

    Both large SQLite files carried the 2026-10-14 evening run's modification time, so a
    copy taken on each new day would duplicate them again. Byte sharing between
    consecutive days was not measured.

- **The copies never certified coherence:** each seeder receipt stated
  `input_set_coherence: not_certified_by_file_seeding`.

## Repeated hash and pin work

Each item below was checked against Git history and the documents cited.

- When the owner approved normal formatting, all 72 affected paths (59 JSON, six Markdown,
  five HTML, two EOF-only) were reformatted and their identities recomputed, with an
  old/new mapping kept ([bootstrap record](../bootstrap-stock-research.md)).
- Producer commit `8795859` ("chore: refresh renamed candidate provenance hashes",
  2026-10-09) changed one line in `docs/migration/source-files.csv` only to re-pin a
  renamed file's hash.
- PR #11 ("Default maintained text to LF and seal research sources before execution",
  merged 2026-10-12) added sealing of research sources before runs.
- `run_study.py verify` took 180.8 s end to end. Almost all of that was path and link
  validation; the SHA-256 work was about 0.2 s ([integrity standard](../artifact-integrity.md),
  PR #15).
- `research_data_incremental.implementation_identity()` hashes every loaded
  `research_core`/`StockProject`/`scripts` module. Any source edit therefore marks stored
  checkpoints incompatible and forces affected outputs to rebuild. The new receipt
  helper deliberately does not repeat that pattern.

## Live-read safety

Live files change during the producer's evening runs. A research read calls
`assert_producer_idle()` once per run. It refuses the weekday 18:00-18:45 window and any
running `StockProject-*` scheduled task, which also covers the long first-of-month
backfill. SQLite is opened with `readonly_sqlite()` (`?mode=ro`). Files are read through
`read_stable()`, which compares size and mtime before and after, so a parquet rewritten
mid-read fails instead of being half-read.

On a WAL database, a read-only connection may still create SQLite's own `-shm`/`-wal`
files beside the live database. This was observed on 2026-10-15: a 0-byte `-wal` and a
32 KB `-shm` were left beside `institutional.sqlite` and `monthly_revenue.sqlite`. They
belong to SQLite and must not be deleted while anything may have the database open.

## Superseded intermediate design

Before this decision, PR #20 first implemented sealed, content-addressed producer-input
bundles. One version was produced and registered, and it stays in place under "What stays":

- `data_id` `producer-inputs`, version and manifest SHA-256
  `03d65832c9f0a8553d5ab4a2332a98a8ea6bcedf6cd9e5a275c21f5fb9ba5397`;
- `D:/Project/stock-research/research_cache/producer-inputs/03d65832…/`, 4.99 GB, prices
  2010-01-04 to 2026-10-14;
- registered in the shared catalog as kind `prices`, reader `bundle`. The generic
  catalog reader on `main` verifies it; the sealing code was removed before merge.

No study references it. It is a retirement candidate that needs owner approval.

## Rule changes (old → new)

| Location                                                   | Old                                                                                                                                          | New                                                                                                                                                                                                  |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AGENTS.md` Verification                                   | "hash snapshots rather than live files"                                                                                                      | "hash results and fingerprint inputs rather than copying them"                                                                                                                                       |
| `AGENTS.md` Research And Data                              | "Preserve frozen mutable input snapshots rather than replacing them with shared live data."                                                  | Existing frozen snapshots stay until an owner-approved retirement; new studies record an input fingerprint.                                                                                          |
| `AGENTS.md` Research And Data                              | "Keep source and availability timing truthful, missing values distinct from zero, and evidence re-computable."                               | Keep timing truthful and missing values distinct from zero; keep results with SHA-256, commit, definition, parameters, preregistration and input fingerprint, and rerun on current data when needed. |
| `AGENTS.md` Research And Data                              | "worktree input copies remain explicit research snapshots"                                                                                   | "research worktrees read the live producer root and hold no input copies"                                                                                                                            |
| `AGENTS.md` Research And Data                              | "Mutable producer inputs use physical worktree snapshots, never symlinks or junctions."                                                      | Worktrees read the live producer root read-only through `producer_data_root()`, with no copy or link and no submodule, and never during the write window.                                            |
| `docs/en/stock-agent-operations.md`                        | "mutable producer snapshots remain physical copies"; "Mutable `price_daily.parquet` remains an explicit physical input snapshot"             | Producer inputs are read live and fingerprinted; caches are performance-only.                                                                                                                        |
| `docs/en/stock-agent-operations.md`                        | "Mutable producer inputs are **copied, never linked**, into a new worktree …"                                                                | Worktrees copy no producer data; how `producer_data_root()` finds the root.                                                                                                                          |
| `docs/en/stock-agent-operations.md`                        | "A worktree's `data/` copy is a snapshot taken at creation time …"                                                                           | Live-read safety: idle check, read-only SQLite, `read_stable`, run receipt.                                                                                                                          |
| `docs/en/stock-agent-operations.md`                        | "The tracked `.githooks/post-checkout` initializes submodules …"; seeder receipt paragraph                                                   | Hook retired; seeder kept as a manual legacy tool; existing snapshots stay.                                                                                                                          |
| `docs/en/stock-agent-operations.md` Canonical data updates | "future worktree copies"; "Development worktrees hold physical input snapshots"                                                              | Worktrees read live; development worktrees hold test fixtures.                                                                                                                                       |
| `docs/en/artifact-integrity.md`                            | Producer inputs = "Raw SHA-256 of the snapshot copy"; code = "Snapshot copied into the bundle"; checklist "Inputs are snapshots in a bundle" | Input fingerprint and Git commit in a `run-receipt.v1` receipt.                                                                                                                                      |
| `docs/en/research-foundation.md`                           | none                                                                                                                                         | New section "Input identity (owner decision 2026-10-15)".                                                                                                                                            |
| `.claude/rules/common/data-structures.md`                  | none                                                                                                                                         | Live research reads obey the producer schedule.                                                                                                                                                      |
| `docs/en/sector-wave-catalog.md`                           | "Run from a physical task worktree with the manifest's producer snapshot"                                                                    | Reads the live root while idle; a mismatch means rerunning on current data.                                                                                                                          |
| `.githooks/post-checkout`                                  | Initialized the submodule and seeded about 5 GB per new worktree                                                                             | Removed.                                                                                                                                                                                             |
