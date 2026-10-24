# External catalog and studio archive migration

Implements [2026-10-24 decision, section 2](decision-records/2026-10-24-data-homes-and-scratch.md#2-research-data-leaves-the-checkout).

The owner confirmed the deployment order on 2026-10-24: copy and verify, deliver
the resolver PR, restore the existing website with its old configuration, then
switch the primary configuration and restart after the owner merges. The primary
`.env.local` remains unchanged until that final cutover. Old data is retained.

## Locations

| Store                 | Retained source                                                     | New canonical destination after cutover |
| --------------------- | ------------------------------------------------------------------- | --------------------------------------- |
| Catalog and bundles   | `D:/Project/stock-research/research_data/`                          | `D:/StockData/stock-research/catalog/`  |
| Saved studio packages | `D:/Project/stock-research/StockProject/data/private-presentation/` | `D:/StockData/stock-research/archive/`  |

Neither migrated catalog/studio trees nor filesystem links are created in a worktree. Frozen payloads,
implementations, manifests, snapshots and receipts retain their raw bytes.
Catalog `data:` references remain relative to the catalog root. `primary:`
references keep pointing to the primary checkout's `tasks/` and `research_cache/`.

## Reader, writer, configuration and backup inventory

- `research_core/research_data_paths.py`: resolve catalog and primary independently;
  external catalogs must be outside every registered checkout. Legacy explicit
  `research_data` roots remain readable; they are never an unavailable-root fallback.
  Environment values take precedence over the primary `.env.local`.
- `research_core/research_data_catalog.py`, builder, incremental, file-bundle,
  execution and legacy registration modules, and `scripts/research_data.py`:
  readers/writers already use `DataRoots` and scope-relative paths. Execution
  requests serialize `primary` and `data` separately. No packet is rewritten.
- `research_core/opportunity_history_bundle.py` and `shared_data_view.py`:
  pass the repository identity into root discovery; resolve the same pinned bundle.
  `HistoryStore` remains the full payload authority.
- `research_core/pattern_scan_analysis_v1.py` and `pattern_scan_continuation_v4.py`:
  retained request ancestry checks explicitly name the old layout. Preserve that
  historical protocol and its bytes. Such requests need separate retirement or
  migration review before deleting the old source.
- `scripts/start_research_web.py`, `research_api/private_artifacts.py`,
  `saved_research_studio.py`, `studies.py`, and `dashboard_identity.py`: studio
  paths already come from the two private-package settings. Routers can capture
  the settings at startup; restart is required and the service identity changes.
- `scripts/export_saved_research_studio.py`: writes a requested new output;
  this migration does not re-export the package or regenerate studies.
- The registered worktrees' `.env.local` files were inspected for the three
  affected keys. Only primary had them. No worktree config was copied or edited.
- `artifact_backup.default_sources()` now selects the configured catalog and
  sibling archive. Keep the v1 backup namespace `research_data/` for old restore
  compatibility; new archives use `archive/`. Exclude the retained checkout copy
  after cutover. Maintained `derived/` stays outside backup scope. See
  [backup and restore](price-cache-backup.md#stock-research-research-data-backup).

All 12 historical catalog snapshots were parsed and their manifest locations
audited. Historical text mentioning `research_data` occurs in backup-scope
provenance; do not edit those pinned snapshots. One old snapshot
`68e541007b46afddd68a40e0312cfb3181aea66fc0c17a4286c7385602f12e12`
references the already absent `research_cache/producer-inputs/03d65832…/manifest.json`.
That version is retired in the current catalog. This pre-existing historical
gap is retained, not repaired or relabeled as a migration failure.

## Verification receipt

Copied on 2026-10-24 from base `origin/main` `3bb07718583b3c02a5a6776ced68bd8b81856ba2`.
Two `StockProject-*` tasks were Ready before copying and after publication; their
next runs were 2026-10-26 18:00 and 2026-10-25 18:25 (Asia/Taipei), respectively.
The local history API and frontend were absent before copying and were restored
with the original settings afterward. An unrelated producer institutional
backfill used its own producer staging root; it was left untouched and did not
read either migration source.

| Check                                                    | Before                             | After                                                          |
| -------------------------------------------------------- | ---------------------------------- | -------------------------------------------------------------- |
| Catalog file inventory                                   | 10,455 files / 1,237,447,189 bytes | identical, 0 SHA-256 mismatches                                |
| Saved studio file inventory                              | 12 files / 30,785,684 bytes        | identical, 0 SHA-256 mismatches                                |
| `scripts.verify_published_artifacts`                     | 17 pass / 0 fail / 0 local-missing | 17 pass / 0 fail / 0 local-missing                             |
| Verification result JSON, including every detail string  | baseline                           | byte-content-equivalent parsed JSON, all 17 rows identical     |
| Windows synthetic deletion and focused path/backup tests | —                                  | 185 passed / 5 skipped                                         |
| Restored primary website                                 | old private settings               | 8517 + 5177 available, local-private, original config identity |

The transfer used `artifact_store.copy_verified` per file, a full staged
inventory comparison, a source re-inventory, and `publish_noreplace`, then checked
the published inventory again. Both historical SQLite files were sidecar-free
and passed read-only immutable `PRAGMA quick_check`; no database bytes were
changed. All directories were checked for symlinks, junctions and hardlinks.
The original two trees remain in place. The archive also receives a separate
migration-receipt directory; that is new provenance, not an edit to the 12 source
files.

Observed phase wall times: source inventory 18.515 s (catalog) and 0.125 s
(studio); verified copy/publication 714.281 s and 3.078 s; after-publication
17-check verification 26.406 s. Before-verification wall time was not separately
recorded. These are migration timings, not research-performance claims.

Normal commit hooks passed, including mypy, Pyright, Ruff and formatting. A
separate bounded read-only code review found no actionable correctness defects.
Durable receipt directory:
`D:/StockData/stock-research/archive/data-homes-migration-20261024/`.
It retains `inventory-before.json` (every source-relative path, byte count and
SHA-256), `transfer.json`, the identical `before.json` / `after.json`, the catalog
reference audit, phase timings, config patch, website check and diagnostic code.
The 17-check runner does not load the whole migrated history/studio payload.
Supplemental verification used the formal catalog reader (all 12 current manifest
pins), `query_opportunity_history.query_manifest` for 1101, 2330 and 6488 on
2026-10-02, and `saved_research_studio.read_studio_package`. Old and new query
results and the entire parsed studio package were identical (11.515 s before,
12.266 s after). `reader-comparison.json`, `readers.log` and the exact executed
`compare_readers_bounded.py` are preserved in the receipt directory.

An initial optional whole-market `HistoryStore` cold load was interrupted because
it revalidates all six original methods for every saved stock. It supplied no
completed comparison and is not counted as a pass or a new research result. Its
original diagnostic code is retained as `compare_readers.py`; no source evidence
or result was changed. Per-file byte preservation and the specified 17-check
comparison were already complete before this supplemental check.

`receipt-inventory.json` records every retained receipt member's byte count and
SHA-256. Receipt artifacts live outside the worktree; the report and code live in
Git. No production backup was run.

## Final cutover after owner merge

1. Verify the PR state is merged, update primary `main` without recursively
   updating the producer, and confirm it contains the new resolver.
2. Check that no research process reads either source and no `StockProject-*`
   task is Running. Stop only the authorized local website/API services. Inspect
   any process-level overrides as they take precedence over `.env.local`.
3. Reconcile source and destination inventories again before switching. An old
   catalog writer may have published more data since this copy. Verify additions
   and resolve pointer changes explicitly; never blindly overwrite the copied
   catalog or rewrite a stored manifest.
4. Preserve all unrelated `.env.local` settings and replace only these keys:

    ```dotenv
    STOCK_RESEARCH_DATA_ROOT=D:/StockData/stock-research/catalog
    STOCK_PRIVATE_ARTIFACT_ROOT=D:/StockData/stock-research/archive/20261008-first-stage/research_web/public/data
    STOCK_SAVED_STUDIO_PACKAGE=D:/StockData/stock-research/archive/20261008-first-stage/research_web/public/data/saved-research-studio.manifest.json
    ```

5. Run `uv run python -m scripts.verify_published_artifacts` from the updated
   primary checkout; compare all 17 rows with the preserved migration receipt.
   Verify all current catalog entries and load the history and studio packages
   from their new roots with their existing readers. Restart the website with
   `uv run python scripts/start_research_web.py --no-browser` and verify its
   service identity, local-private mode, history and studio endpoints.
6. Confirm `backup_research_data` selects the new catalog/archive. Production
   backup is still an explicit separate operation, not implied by a scope change.
   Historical SQLite needs explicit `--frozen-sqlite PATH=SEALED_SHA256` and closed
   sidecar-free state; unfinished locks are still refused. This migration does
   not claim a completed production backup or off-machine protection.

## When the old locations may be deleted

Do not use a calendar deadline. Recommend deletion only after the merged-code
cutover and live endpoint checks pass, a verified backup/restore covers both new
stores, every retained request/runner using the old absolute layout is migrated
or explicitly retired, and no process/configuration still reads the old copies.
Then present the exact two source paths, a final digest/inventory comparison and
the recovery receipt to the owner for explicit deletion approval. No deletion is
authorized by this PR, by successful verification, or by the owner merging it.

Session-owned worktree: `D:/Project/stock-research/.worktrees/external-data-homes`,
branch `codex/external-data-homes`; retain while its PR is open and through final
cutover verification. Other sessions' worktrees and data are untouched.
