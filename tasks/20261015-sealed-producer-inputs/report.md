# Sealed producer inputs: first version and migration status

Contract: [data-contract.md](data-contract.md). Owner decision 2026-10-15.

## First sealed version

| Field        | Value                                                                                                                                                                 |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `data_id`    | `producer-inputs`                                                                                                                                                     |
| Pin          | `version_id` = manifest SHA-256 = `03d65832c9f0a8553d5ab4a2332a98a8ea6bcedf6cd9e5a275c21f5fb9ba5397`                                                                  |
| Location     | `D:/Project/stock-research/research_cache/producer-inputs/03d65832…/`                                                                                                 |
| Members      | 2,088 files, 4,990,335,543 bytes (`institutional.sqlite` 3.83 GB, `monthly_revenue.sqlite` 0.62 GB, 2,080 `*_day.csv` 0.30 GB, `price_daily.parquet` 0.20 GB, others) |
| Raw period   | `price_daily.parquet` 2010-01-04 to 2026-10-14                                                                                                                        |
| Legacy daily | absent at seal time (primary has no `adjusted_prices/daily`)                                                                                                          |
| Catalog      | registered, catalog snapshot `68e54100…`; readable by the current `main` catalog code                                                                                 |
| Sealed       | 2026-10-15 01:47 local from `D:/Project/stock-research/stock-data-downloader/data`                                                                                    |
| Writer check | both `StockProject-*` tasks `Ready`; no `-wal`/`-shm`/`-journal` beside producer SQLite                                                                               |

Measured on this machine (receipts under `research_cache/producer-inputs/receipts/03d65832…/`):

| Step                                                   | Wall time |
| ------------------------------------------------------ | --------- |
| First seal: capture (copy, SQLite backup, hash)        | 98.8 s    |
| First seal: one verification of every member (catalog) | 10.4 s    |
| Reseal of unchanged data: capture                      | 63.8 s    |
| Reseal: verification of the reused version             | 5.6 s     |
| `open_producer_inputs` (pin, identity, tree, sizes)    | 0.27 s    |

The reseal resolved to the same version: unchanged SQLite online backups were
byte-identical, so identical producer content never creates a second 5 GB version.
A sealed `institutional.sqlite` opened `?mode=ro` reports `journal_mode=delete` and left
no sidecar.

Storage effect: a new research worktree previously received about 5 GB of copies (plus
the scratch SQLite fixed in PR #18). After this change and the primary `main` update it
receives none; the sealed versions cost about 5 GB each, once, in primary.

## Consumers not migrated

| Consumer                                                                                                                                                                                                           | Why it is left                                                                                                                                                                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `research_core/feature_atlas_io.py` and its builder `scripts/build_feature_discrimination_atlas.py`                                                                                                                | `feature_atlas_io.py` is SHA-pinned in the hhhl-v4-variants receipt. It joins `<root>/stock-data-downloader/data`, so passing a sealed version's `root` serves it unchanged (tested).                   |
| `StockProject/engine/data_loader.py`                                                                                                                                                                               | SHA-pinned in 28 stored artifacts. It already takes an explicit `data_path`; pass `sealed.data_root`.                                                                                                   |
| `scripts/smoke_task_research_runtime.py`, the 2B rerun commands in `research_lab/dashboard_core.py`                                                                                                                | Use the legacy relative `stock-data-downloader/data/adjusted_prices/daily`, which primary no longer has. They work only in a retained worktree snapshot or the container; needs a sample-task decision. |
| `scripts/prepare_opportunity_history.py`, `scripts/export_market_atlas.py`, `scripts/capture_owner_hhhl_rule_hits.py`, `research_api` summary paths                                                                | Already take explicit paths; a sealed `data_root` can be passed without code changes.                                                                                                                   |
| Live readers on `producer_data_root()`: `research_lab.dashboard_core`, `research_lab.display`, `StockProject.universe`, `scripts.stock_research_query`, `scripts.prepare_nightly_research`, `backtest_cli` default | Live by design. In a worktree without the submodule they need `STOCK_PRODUCER_DATA_ROOT`; the default location belongs to the producer relocation work.                                                 |
| `tasks/*` runners and evidence code                                                                                                                                                                                | Historical; they keep reading their retained snapshots.                                                                                                                                                 |
