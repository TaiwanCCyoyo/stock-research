# Sealed producer inputs v1

Owner decision 2026-10-15: research inputs from the producer are frozen once, as
immutable versioned bundles in the primary checkout, and read in place by pin. No
worktree copies producer data, and research worktrees need no initialized
`stock-data-downloader` submodule (stock-research imports no producer code; CI does not
initialize it). This replaces the per-worktree copies made by `.githooks/post-checkout`
and `scripts/seed_worktree_inputs.py`, which cost about 5 GB per worktree.

This is infrastructure. A sealed version is an input snapshot, not a validated market
calculation, and sealing it approves no study.

## Layout and identity

```text
<primary>/research_cache/producer-inputs/
  <version_id>/
    manifest.json                    research-data-bundle.v1
    stock-data-downloader/data/...   payload in the producer's relative layout
  receipts/<version_id>/<utc>-<uuid>.json   one per seal run (also for reuse)
```

- **Read set** (`research_core.producer_inputs.NAMES`, unchanged from the seeder):
  `price_daily.parquet`, `*_day.csv`, `corporate_actions` / `symbol_meta` /
  `institutional` / `monthly_revenue` `.sqlite`, `stock_symbol_mapping.json5`,
  `value_chain_classification.json`, `dividends.parquet`, `data_quality_report.json`,
  and legacy `adjusted_prices/daily/{price_daily.parquet,dividends.parquet,*_day.csv}`
  when present. Minute bars, `official_daily.sqlite`, `raw/` and `technical_features`
  are excluded.
- **SQLite** is captured with the online backup API in one step (one read
  transaction, so committed WAL contents are included and a writer cannot restart it),
  converted to `journal_mode=DELETE`, `quick_check`ed and closed before hashing. A
  sealed database therefore opens read-only without creating `-wal`/`-shm` next to
  sealed bytes. Other files are copied only when size and mtime are unchanged across
  the copy and the bytes match the source digest before and after.
- **Version id** is the SHA-256 of the canonical manifest, which equals the manifest
  file's SHA-256. The manifest holds no time or machine path, so resealing identical
  content resolves to the existing version (measured: unchanged SQLite backups are
  byte-identical). Seal time, source path, source size/mtime per file and phase timings
  are in the receipt, outside the identity.
- **Publication** stages a sibling `.staging-<uuid>` tree, then `publish_noreplace`
  moves it into place. Members are made read-only. A failed or reused seal deletes its
  own unpublished staging; it never replaces a version.
- **Catalog**: `data_id` `producer-inputs`, reader `bundle`, manifest scope `primary`
  at `research_cache/producer-inputs/<version_id>/manifest.json`. Its kind is the
  existing `prices`; a new kind would make catalog readers on older code reject the
  whole catalog. Coverage `raw_input_period` is the `price_daily.parquet` date range;
  indicator and label periods are not applicable.

## Reading

```python
from research_core.producer_inputs import open_from_env

sealed = open_from_env(VERSION_ID, MANIFEST_SHA256)   # STOCK_RESEARCH_DATA_ROOT
prices = sealed.path("price_daily.parquet")           # hashes that member on first use
loader_dir = sealed.data_root                         # directory for DataLoader/--data-path
legacy_root = sealed.root                             # for readers joining root/stock-data-downloader/data
sealed.verify_all()                                   # before handing data_root to a bulk reader
```

`open_producer_inputs` checks the manifest pin and content id, rejects any symlink,
junction, hardlink, unlisted file (for example a `-shm` sidecar) or size difference,
and leaves member hashing to `path`/`verify_all`, once per instance. There is no
`latest`, no missing-version fallback and no live-data fallback. CLI:

```powershell
$env:STOCK_RESEARCH_DATA_ROOT = 'D:/Project/stock-research/research_data'
uv run python -m scripts.seal_producer_inputs verify VERSION_ID --manifest-sha256 SHA256
uv run python -m StockProject.backtest_cli --strategy S.py --codes 2330 --producer-inputs VERSION_ID --producer-inputs-sha256 SHA256
uv run python -m scripts.build_sector_wave_catalog --output-dir DIR --run-id ID --producer-inputs VERSION_ID --producer-inputs-sha256 SHA256
```

Live dashboards and queries (`research_lab.dashboard_core`, `research_lab.display`,
`StockProject.universe`, `scripts.stock_research_query`, `scripts.prepare_nightly_research`,
`backtest_cli` without `--producer-inputs`) keep reading the live
`producer_data_root()` (`STOCK_PRODUCER_DATA_ROOT`). The builders above take
`--live-producer-data` when live data is the deliberate choice.

## Locating the primary root

A worktree finds primary through the explicit `STOCK_RESEARCH_DATA_ROOT`
(`<primary>/research_data`, validated by `DataRoots`), the setting the shared entry
already requires. Deriving primary from `git rev-parse --git-common-dir` was
considered and not adopted: the
[shared entry contract](../20261012-research-data-entry/data-contract.md) states that a
linked worktree's `.git` file cannot establish a primary root, and an implicit
derivation would also resolve inside containers and copied checkouts that have no
primary. Measured 2026-10-15 on this machine: the variable lookup takes about 1 µs; the
derivation takes a `git` subprocess, 28.5 ms on average over 20 runs, and would still need
the same `DataRoots` validation.

## Sealing

```powershell
$env:STOCK_RESEARCH_DATA_ROOT = 'D:/Project/stock-research/research_data'
uv run python -m scripts.seal_producer_inputs seal            # source: producer_data_root()
uv run python -m scripts.seal_producer_inputs seal --source D:/Project/stock-research/stock-data-downloader/data
```

The command refuses while any `StockProject-*` scheduled task is running, and on
weekdays between 17:50 and 19:00 unless `--allow-window` is passed after checking that
writers are idle. It reads `producer_data_root()` by default, so it follows the producer
data relocation. Seal on demand when a study needs newer inputs, not on a schedule: each
changed version costs about 5 GB, mostly `institutional.sqlite`, and `research_cache` is
in the `artifact_backup` scope.

## First sealed version

See the receipt under `research_cache/producer-inputs/receipts/` for exact timings.
The version, its size and coverage are recorded in [report.md](report.md).

## Retirement of per-worktree seeding

`.githooks/post-checkout` is removed. `core.hooksPath` points at the primary checkout's
`.githooks`, so new worktrees stop initializing the submodule and copying data only
after this change is merged and primary `main` is updated. `scripts/seed_worktree_inputs.py`
stays as a manual legacy tool for reproducing an old worktree-snapshot layout; no hook
calls it. Existing worktree snapshots and their receipts are retained as they are;
historical task runners and SHA-pinned evidence keep reading them.
