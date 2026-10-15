# Producer layout correction

## Decision 2026-10-15: producer data leaves the repository

Decided by the owner on 2026-10-15. The producer's live data moves out of the
research checkout to `D:/StockData/stock-data-downloader`, selected by the
producer's own `.env` `SHIOAJI_DATA_DIR`. The reasons:

- **No data in the repository or its worktrees.** A storage audit found the
  checkout at 90.7 GB, 42.6 GB of it the producer's live data, with worktrees
  holding further partial copies.
- **Research worktrees stop needing the submodule or a post-checkout copy.** They
  read producer data by explicit absolute root instead of seeding snapshots.
- **Worktree removal and `git clean` cannot reach canonical data.** Data outside
  every checkout is outside the blast radius of routine Git cleanup.

Scope: this reverses only the data-location part of the correction recorded
below. The producer code stays the `stock-data-downloader` submodule, and the
scheduled tasks keep running from `D:/Project/stock-research/stock-data-downloader`.
Step 3 below ("data beneath `data/`") is superseded for the data only. The target
is on the same volume, so the move is a rename. Execution follows the
[relocation runbook](producer-data-relocation-runbook.md), which needs a separate
owner-approved window. The producer side is
[stock-data-downloader#2](https://github.com/TaiwanCCyoyo/stock-data-downloader/pull/2).
The companion research-input policy (live read-only inputs plus an input
fingerprint, no sealing) is recorded in
[drop input sealing](decision-records/2026-10-15-drop-input-sealing.md)
(stock-research#20).

The record below is kept as history.

## Earlier correction: producer inside the research checkout

The initial clean-repository migration deployed the producer to an independent
`D:/Project/stock-data-downloader` checkout while research consumers still defaulted
to the old submodule name. This differed from the owner’s intended single live
producer inside the research checkout. It is a configuration correction, with no
claim of data loss or an observed download failure.

## Code contract

The submodule name and path are `stock-data-downloader`, URL
`https://github.com/TaiwanCCyoyo/stock-data-downloader`, pinned at
`8795859880eef99c0968fc6c3bca4863743003d2`. Default live reads use
`<research checkout>/stock-data-downloader/data`. Query, universe metadata, CLI,
dashboard metadata/name mapping and nightly preparation share the resolver.
`STOCK_PRODUCER_DATA_ROOT` remains an explicit absolute override; invalid or
missing configured roots fail without fallback. Explicit task roots and saved
snapshots remain explicit; historical paths and input provenance are not rewritten.
Since 2026-10-15 worktrees read the live root read-only and fingerprint what a study read; existing worktree snapshots stay in place until an owner-approved retirement.

## Deployment gates and rollback

This PR changes code and guidance only. The existing independent producer and its
two enabled jobs remain the production setup until owner merge and safe deployment.

1. Preserve both task XML definitions and enabled states; check scheduled and manual
   download/backfill writers, then pause triggers to prevent new starts. Let running
   writers exit naturally. Never terminate them.
2. Coordinate the primary research checkout: unrelated local changes must be
   preserved by their writer before a safe main update. Do not reset, stash or
   switch another session’s branch. Initialize the renamed submodule only after
   updating to the merged code. Inventory both old and new data paths first;
   initialized old submodule directories can remain after Git updates. Never delete
   their ignored data during cleanup.
3. Final production root is
   `D:/Project/stock-research/stock-data-downloader`, data beneath `data/`. Prefer a
   checked same-volume directory transfer while all writers are idle, without
   junctions or symlinks. Confirm the target is absent or explicitly reconcile its
   code-only metadata; never overwrite unknown contents. Inventory and checkpoint
   SQLite consistently before transfer and verify after it. Preserve the source
   code checkout, complete `D:/StockDataBackup` mirror and the separately preserved
   prior backup version. A directory transfer changes ownership of the live data;
   record exact paths so rollback can transfer it back while writers remain idle.
   An extra full copy requires space/cost review first.
4. The new target requires persistent local credentials for scheduled login. Do not
   recopy API keys without the owner’s separate confirmation. Preserve the existing
   ignored `.env`; backup destination remains `D:/StockDataBackup`. Never publish
   credentials, market files or private verification logs.
5. Read back the actual resolver, query, CLI metadata and dashboard paths. Honor
   existing explicit research snapshots; inspect any process/user/machine override
   before claiming the default live root is aligned. Use the production submodule’s
   `cron/setup_scheduled_tasks.ps1 -UpdateActionsOnly` and verify both VBS/CMD paths,
   working directories, unchanged triggers/principals/settings and paused state.
6. Run the authorized bounded normal producer trial and backup. Verify database
   integrity and changed-file backup hashes. Resume only the same two existing
   tasks once ready, then confirm exactly one enabled job set and no legacy actions.
   On failure keep them paused, restore recorded actions/data placement as needed,
   and report which credentials or deployment gate remains unresolved.

Legacy checkout, legacy producer folders, old data and other sessions’ worktrees remain
untouched. Local task resources are retained for the open PR, not production.
