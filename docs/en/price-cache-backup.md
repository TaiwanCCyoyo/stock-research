# Price Cache Backup

How the `stock-data-downloader/data` cache is protected, and why the design
looks the way it does.

The implementation lives in the `stock-data-downloader` submodule
(`backup_data.py`, wired into `run_daily.py`), because it backs up that
repository's own data and needs no knowledge of this one. This page records
the reasoning and the operating procedure for this checkout; the submodule's
own README documents the commands.

## Why this exists

On 2026-08-13, `git worktree remove` was run against a worktree whose
`shioaji_stock_prices/data` was an NTFS junction pointing at the main
checkout. The removal traversed the junction and deleted ~4000 per-symbol
CSVs from the canonical cache. There was no backup, and Volume Shadow Copy
was not enabled on the drive, so the only recovery path was re-downloading
under a daily API quota — days of work.

Two lessons shaped everything below:

1. **A mirror that deletes is not a backup.** A conventional `robocopy /MIR`
   job would have replicated that deletion into the backup within a day and
   destroyed both copies.
2. **"It reported success" is not evidence.** In this incident `ln -s`
   reported success while silently copying, and the worktree removal reported
   failure while succeeding at deleting. Every tier below verifies its own
   result rather than trusting an exit code.

The worktree aliasing that caused the loss is fixed separately — worktrees
now receive a copy of the read-set rather than a link. See
`.githooks/post-checkout` and the worktree notes in `docs/en/stock-agent-operations.md`.

## What is worth protecting

Priority follows reacquisition cost, not file size:

| Priority | Data                                          | Size    | Cost to rebuild                                    |
| -------- | --------------------------------------------- | ------- | -------------------------------------------------- |
| Highest  | `*_min.csv`, `*_day.csv`                      | 15.6 GB | Shioaji enforces a **daily download quota** — days |
| Medium   | `official_daily.sqlite`                       | 642 MB  | TWSE endpoints are free but backfill is slow       |
| Low      | `price_daily.parquet`, `*.sqlite` derivatives | ~90 MB  | Derived; regenerated from the above in minutes     |

The backup copies everything regardless — the table is for judging what a
tier is worth, not what it includes.

## Tier 1 + 2: local additive mirror with verification

Set the destination once in `stock-data-downloader/.env` (gitignored, so the
machine-specific path is never committed):

```dotenv
SHIOAJI_BACKUP_DIR=D:/StockDataBackup
```

`run_daily.py` then mirrors the cache there as its last step, on every
successful scheduled run. No separate scheduling is needed: the daily task
already runs `cron/run_daily_scheduled.cmd`, and the backup is inside it.

To run it by hand from the submodule directory:

```powershell
uv run backup_data.py                 # mirror + verify
uv run backup_data.py --verify-only   # re-check without copying
```

### Format: an uncompressed file-for-file mirror, not an archive

Tier 1 stores plain files in the same layout as the source:

```
D:\StockDataBackup\
├── data\              <- file-for-file mirror of stock-data-downloader\data
│   ├── 2330_day.csv
│   ├── 2330_min.csv
│   ├── raw\...
│   └── ...
├── archive\           <- only when --archive is used (tier 3 uploads)
└── backup.log
```

Compression belongs in tier 3, not here, for four reasons:

- **Partial restore.** Recovering one symbol means copying one file, not
  unpacking 15 GB.
- **Incremental cost.** Only changed files are copied, so runs after the
  first take seconds. An archive must be rebuilt in full every time.
- **Per-file verification.** The size check is only possible against
  individual files.
- **Isolated corruption.** A damaged file in a mirror costs that file. A
  damaged archive can cost everything in it.

Expect ~18 GB, growing with the source.

### What verification does and does not prove

Verification compares byte counts per file. It proves a copy landed whole; it
cannot prove a copy of a _moving_ file is a coherent snapshot. Two files here
are written continuously — `official_daily.sqlite` and its `-wal` sidecar grow
all evening while the historical backfill runs, which overlaps the daily
backup by design (backfill starts 18:25, the backup step lands around 18:26).

So a file whose source changed after it was copied is reported as one snapshot
behind, not as a failure. Before 2026-08-20 it failed the whole run: that night
the backup aborted on `official_daily.sqlite-wal` having grown mid-verify,
hours after the price data the backup exists to protect had already been
mirrored and verified. A short copy of a source that has _not_ changed is still
a failure, and a missing file always is.

What this leaves standing is that the mirror's copy of `official_daily.sqlite`
is a snapshot of a live database. SQLite tolerates this better than it sounds —
the copy taken on 2026-08-20 opened clean, `PRAGMA quick_check` returning `ok`
across 3.18M rows — but it is not guaranteed, and it is the reason that
database is not in the quarterly archives either. Restoring it is a
best-effort path; the price CSVs, which are static once written, are the tier
that carries a real guarantee.

### When the backup is skipped

The backup does not run if a step that writes the price cache failed
(download, convert, parquet rebuild). Mirroring a half-written file over a good
backup copy is the one way an additive backup can still lose data. A failed
corporate-action refresh, official-price fetch, or health check does not block
it, and a non-trading day that downloads nothing is not a failure.

The corporate-action refresh used to block it too, until 2026-08-19, when a
transient TWSE read timeout in that step cost a night's mirror of the price
cache. It writes its own database one transaction at a time and never touches
the price cache, so it cannot leave the half-written file the rule exists for —
blocking on it traded an outage in the cheapest data to refetch for protection
of the most expensive.

`run_daily.py` exits non-zero when any step failed, so a bad night is visible
in Task Scheduler's Last Run Result instead of silently reporting success.

### What this tier does not protect against, and which drive to use

At the default `D:\StockDataBackup` the mirror shares a physical disk with
the repository, so it defends against tooling accidents — the failure that
actually happened — but not against that drive failing.

`C:` and `D:` are separate physical SSDs here (`C:` = Crucial 1 TB, `D:` =
Kingston 2 TB) and the repository lives on `D:`, so pointing
`SHIOAJI_BACKUP_DIR` at `C:\StockDataBackup` would also survive the loss of
`D:`, at the cost of ~18 GB on the system drive and nothing else. Tier 3
covers the remaining case of losing the whole machine.

## Tier 3: quarterly archives on Google Drive

Needed because tiers 1 and 2 both live on this machine. An uploaded archive
cannot be modified by any later local accident, which makes this the only
tier structurally immune to corruption propagation rather than merely to
deletion.

Build the archives from the submodule directory:

```powershell
uv run backup_data.py --archive
```

| Archive                     | Contents                                                                                                                                 | Approx. size        |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| `data_day_<YYYYQn>.tar.gz`  | `*_day.csv` + `*.json5`                                                                                                                  | ~40 MB              |
| `data_min_<YYYYQn>.tar.gz`  | `*_min.csv`                                                                                                                              | ~2.3 GB             |
| `data_meta_<YYYYQn>.tar.gz` | `corporate_actions.sqlite`, `symbol_meta.sqlite`, and latest/history `value_chain_classification*.json` with relative history paths kept | Small; grows weekly |

Split by data type on purpose. Measured from the January 2026 snapshot the
whole CSV set compresses 15.13 GB -> 2.34 GB (15.5%), and almost all of that
bulk is minute bars. Daily bars are both the smaller and the more valuable
half — they are what the backtest engine reads, via `price_daily.parquet`
derived from them — so keeping many quarters of `data_day` costs almost
nothing, while `data_min` is the one worth pruning.

`data_meta` carries small artifacts that describe the bars rather than
containing them. They are cheap enough to keep at every retention tier,
and the corporate-action index in particular is not reconstructible from the
price CSVs at all — losing it silently changes every backtest that spans an
ex-dividend. It also carries `value_chain_classification.json` and every
`value_chain_classification_history/YYYY-MM-DDTHHMMSSZ.json` observation
without flattening the history paths. Those snapshots preserve when the
official taxonomy was first observed; a current snapshot must not be treated
as historical classification before its own `fetched_at`.

The point-in-time side of the cache is deliberately not archived at all:
`official_daily.sqlite`, `monthly_revenue.sqlite` and `institutional.sqlite`,
and the raw responses stored beside the latter two under
`data/raw/monthly_revenue/` and `data/raw/institutional/`.

The three databases are excluded because they use WAL mode — archiving a main
database file alone could drop committed rows still in its `-wal` sidecar, and
doing it safely needs a SQLite checkpoint step first. The raw evidence is
excluded so that one rule covers the whole point-in-time side rather than one
rule per pipeline; otherwise revenue and institutional evidence would differ
only by which pipeline happened to be written first.

All of it remains covered by the mirror, which copies the WAL sidecars
alongside the databases, is additive, and is verified every run — but the
mirror is the only copy. Those raw snapshots record when an observation first
reached this machine and are not re-fetchable. Wanting them offsite is a
reasonable future decision; make it for all of them at once.

**Budget hours, not minutes.** Measured on this machine, `data_day` took
about eight minutes and `data_min` over five hours — single-threaded gzip
over 15.3 GB. Start it when nothing else needs the disk, and not shortly
before 18:00: the daily run's own backup step writes to the same mirror the
archive is reading, so an overlap risks sealing a half-written file into the
archive.

**Cadence and retention:** upload once per quarter and keep the latest two
quarters of `data_min` — ~4.7 GB, comfortably inside Drive's free tier.
Retention is a manual delete on Drive. Nothing in the backup system deletes
anything, which is deliberate: the one subsystem that exists to survive an
accidental deletion should not contain a deletion path of its own.

Uploading is manual — drag the archives into Drive. Automating it would
mean storing OAuth credentials, which is not worth it for a four-times-a-year
task; if it ever becomes worth it, use `rclone`, which keeps its own config
outside the repository. Never commit credentials.

GitHub Releases was considered and rejected: its 2 GiB per-asset cap sits
just below the 2.34 GB archive, and the `shioaji-stock-prices` repository is
public, which would republish broker-sourced minute data.

## Restore

A backup that has never been restored is not yet known to be a backup.

To restore the whole cache, copy back from the backup root — additively, so
that anything newer in the live cache survives:

```powershell
robocopy D:\StockDataBackup\data <repo>\stock-data-downloader\data /E /R:1 /W:5
```

Then rebuild the derived artifacts with the submodule's own pipeline rather
than trusting restored copies of them.

To pull individual files out of a quarterly archive, use Windows' bundled
bsdtar explicitly:

```powershell
C:\Windows\System32\tar.exe -xzf D:\StockDataBackup\archive\data_day_2026Q3.tar.gz -C <scratch> 2330_day.csv
```

Not a bare `tar` under Git Bash: that resolves to GNU tar, which reads
`D:\...` as a remote `host:path` and fails with "Cannot connect to D:".

### Drill record

Performed 2026-08-14, after the first mirror completed. Six files covering
every class — a daily CSV, a minute CSV, `price_daily.parquet`,
`symbol_meta.sqlite`, `stock_symbol_mapping.json5`, and a nested
`raw/isin/twse.html` — were copied out of the backup to a scratch directory
and MD5-compared against the live cache. All six matched. A file extracted
from `data_day_2026Q3.tar.gz` (2037 entries) also matched.

Repeat the drill after any change to the backup code. Restoring a handful of
files takes minutes and is the only thing that turns an assumption into a
fact.

## Stock research data backup

Owner decision 2026-10-08 adds a separate Stock scope: `research_cache/`, formal
`tasks/*/datasets/`, and `tasks/20261010-owner-hhhl-labels/` when Claude has delivered
it. Producer source backups above remain unchanged. This is an explicit command,
not a new schedule or an extension of `run_daily`.

```powershell
uv run python -m scripts.backup_research_data backup --project D:/Project/Stock --destination D:/StockResearchBackup
uv run python -m scripts.backup_research_data verify D:/StockResearchBackup/snapshots/EXPLICIT_DIGEST.json
uv run python -m scripts.backup_research_data restore D:/StockResearchBackup/snapshots/EXPLICIT_DIGEST.json --destination D:/StockResearchRestore/NEW_DRILL_DIRECTORY
```

The backup stores SHA256-named content objects and immutable inventory snapshots.
Repeated identical content is verified and reused. Source deletion never deletes
backup objects or older snapshots. Content/filename changes during copying prevent
a completion receipt; incomplete attempts remain diagnostic evidence. Each new
invocation retains its immutable `attempts/<id>.json` started record. After snapshot
verification, an atomic `completions/<id>.json` links that attempt's path/hash to the
verified snapshot's path/id/hash and execution counts. A started record is not a
terminal failure when its matching completion verifies; absent completion means
completion was not confirmed. Historical attempts without this record remain
unchanged and are not retrospectively relabeled as failed or completed. Restore
requires a destination that does not exist and verifies every byte; it never
replaces current research. Symlinks/junctions, unfinished cache staging/locks,
credentials and live SQLite databases are rejected, not silently skipped.

New content objects and snapshot manifests are published by same-directory
partial-file verification and atomic rename under exclusive per-target locks.
Interrupted partials remain diagnostic files, not final objects or snapshots;
retry can finish without overwriting retained evidence. Existing damaged final
objects are still refused rather than silently repaired. Follow the single-writer
contract and inspect a crash-retained lock before any manual recovery.

Restore also publishes only after completion: it copies into a unique sibling
staging tree, verifies the entire inventory and receipt plus the stable backup
manifest, then atomically renames under an exclusive destination lock. Interrupted
copy/receipt attempts retain staging for diagnosis without creating a partial
final destination; a new attempt can restore to the same final path. Existing or
competing destinations and another writer's lock are never removed or replaced.

A historical closed SQLite input may be copied only with explicit
`--frozen-sqlite PATH=SEALED_SHA256`, verified against its original sealed input
receipt, and no WAL/SHM/journal sidecars before or after. This is not authority to
copy a live producer database; use its consistent snapshot procedure instead.

The D-drive destination was selected by the owner. It protects against accidental
deletion, not failure of the same physical D drive. Git/source packet retention,
primary cache availability, byte backup and a successful restore are separate
claims. Actual coverage/drill receipts and any missing owner-label handoff are
recorded in `tasks/20261008-research-data-architecture/`.
