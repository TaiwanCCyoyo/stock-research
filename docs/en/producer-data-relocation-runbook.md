# Producer data relocation runbook

Owner decision 2026-10-15: the producer's live data leaves the research checkout so
that the repository and its worktrees carry no production data. Only the data
moves; the producer code stays the `stock-data-downloader` submodule and the two
scheduled tasks keep running from `D:/Project/stock-research/stock-data-downloader`.

**Status: not executed.** Executing it needs the owner's approval of a move window
in chat. Approval of this document or of its PRs is not that approval.

## Decisions

| Item                                | Decision                                                                                  | Why                                                                                                                                                                                                                        |
| ----------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Target                              | `D:/StockData/stock-data-downloader`                                                      | Same NTFS volume as the source (`D:`), so the move is a directory rename. D: had 45.4 GB free on 2026-10-15; a 42.6 GB copy would nearly fill it. Named after its producer; sits beside the existing `D:/StockDataBackup`. |
| Producer setting                    | `SHIOAJI_DATA_DIR` in the producer primary checkout's own `.env`                          | The scheduled launchers already run in that checkout; no task-action or machine-environment change. Pairs with the existing `SHIOAJI_BACKUP_DIR`.                                                                          |
| Not a user/machine env var          | —                                                                                         | It would leak into every producer worktree and research process.                                                                                                                                                           |
| Tracked `data/stock_category.json5` | Stays in the checkout                                                                     | Code-owned config, anchored to the checkout by the producer change. Moving it would show a deleted tracked file.                                                                                                           |
| Research setting                    | stock-research `.env.local` `STOCK_PRODUCER_DATA_ROOT=D:/StockData/stock-data-downloader` | Distinct, consumer-owned name. Changed at step 9, not earlier.                                                                                                                                                             |

Producer behaviour this relies on ([stock-data-downloader#2](https://github.com/TaiwanCCyoyo/stock-data-downloader/pull/2),
`docs/operations.md#data-location` there): a configured value must be an absolute,
existing, link-free directory outside the checkout, otherwise every entry point
stops at import; a configured root is never created; each checkout reads only its
own `.env`, so producer worktrees keep their own `data/`.

## Preconditions (all must hold; otherwise stop)

1. Producer PR merged; stock-research PR that pins the merged producer commit merged.
2. The primary producer checkout runs the merged code. Old code ignores
   `SHIOAJI_DATA_DIR` and would recreate `data/` and start downloading into it.
    ```powershell
    git -C D:/Project/stock-research/stock-data-downloader log -1 --format=%H
    cd D:/Project/stock-research/stock-data-downloader
    uv run python -c "from config import config; print(config.DATA_DIR_ENV, config.DATA_DIR, config.DATA_DIR_SOURCE)"
    ```
    Expect `SHIOAJI_DATA_DIR ...\stock-data-downloader\data default`.
3. Research readers that seed or read the primary's `stock-data-downloader/data/`
   (owned by the sealed-producer-inputs work) accept `STOCK_PRODUCER_DATA_ROOT`, or
   the owner accepts that new worktree seeding has no source until they do.
4. Window: not 17:30–19:00 on a weekday (DailyUpdate 18:00, 19–45 min), not the
   evening of the 1st (OfficialBackfill runs ~1.5 h after a month rollover).
   Budget about 30 minutes; most of it is hashing ~21 GB of SQLite/Parquet twice.
5. `D:/StockData/stock-data-downloader` does not exist. If it exists with any
   content, stop and ask; never merge into or overwrite it.

## Steps

Run in Windows PowerShell. `$P` is the producer primary checkout, `$T` the target,
`$R` the receipt folder (ignored scratch in the primary research checkout).

```powershell
$P = 'D:\Project\stock-research\stock-data-downloader'
$T = 'D:\StockData\stock-data-downloader'
$R = 'D:\Project\stock-research\.tmp\producer-data-relocation'
New-Item -ItemType Directory -Force $R | Out-Null
```

### 1. Record and pause the tasks (owner-approved)

```powershell
foreach ($n in 'StockProject-DailyUpdate','StockProject-OfficialBackfill') {
  Export-ScheduledTask -TaskName $n | Set-Content -Encoding Unicode "$R\$n.xml"
  $i = Get-ScheduledTaskInfo -TaskName $n
  '{0} state={1} lastResult={2} next={3}' -f $n, (Get-ScheduledTask $n).State, $i.LastTaskResult, $i.NextRunTime
  Disable-ScheduledTask -TaskName $n | Out-Null
}
```

Disabling prevents new starts only. It does not stop a running process.

### 2. Wait for every writer and reader to exit — never kill

```powershell
Get-ScheduledTask -TaskName 'StockProject-*' | Select TaskName, State
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'stock-data-downloader|official_daily|StockData' } |
  Select ProcessId, Name, CommandLine
```

Proceed only when neither task is `Running` and no process references the data
(including other sessions' seeders, research APIs or notebooks). If something
does not exit by itself, defer the window and ask its owner. Never end a process
you did not start.

### 3. Checkpoint SQLite

Folds committed WAL pages into each main file and checks integrity. It does not
change logical content.

```powershell
@'
import sqlite3, sys
from pathlib import Path
root = Path(sys.argv[1])
bad = []
for db in sorted(root.rglob("*.sqlite")):
    con = sqlite3.connect(db)
    try:
        busy, _, _ = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        check = con.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        con.close()
    side = [s for s in ("-wal", "-shm") if Path(f"{db}{s}").exists()]
    print(db.relative_to(root), "busy" if busy else "ok", check, side or "")
    if busy or check != "ok" or side:
        bad.append(db.name)
sys.exit(1 if bad else 0)
'@ | uv run --no-project python - "$P\data"
```

Expect every line `ok ok` and no side files (the last connection's close removes
them). Any `busy`, a `quick_check` other than `ok`, or a remaining `-wal`/`-shm`
means a connection is still open: return to step 2. Do not delete side files.

### 4. Inventory before the move

```powershell
@'
import hashlib, json, os, stat, sys
from pathlib import Path
root, out = Path(sys.argv[1]), Path(sys.argv[2])
files, links = {}, []
for dirpath, dirnames, filenames in os.walk(root):
    for name in dirnames + filenames:
        p = Path(dirpath, name)
        if os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            links.append(str(p))
    for name in filenames:
        p = Path(dirpath, name); st = os.lstat(p)
        entry = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
        if p.suffix in (".sqlite", ".parquet"):
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 24), b""):
                    h.update(chunk)
            entry["sha256"] = h.hexdigest()
        files[p.relative_to(root).as_posix()] = entry
if links:
    sys.exit(f"reparse points present, stop: {links}")
out.write_text(json.dumps({"root": str(root), "files": files}, indent=1), encoding="utf-8")
print(len(files), "files", sum(e["size"] for e in files.values()), "bytes")
'@ | Set-Content -Encoding utf8 "$R\inventory.py"
uv run --no-project python "$R\inventory.py" "$P\data" "$R\before.json"
git -C $P status --porcelain
```

A reparse point anywhere stops the procedure. Record the printed count and bytes
(about 4,170 top-level entries and 42.6 GB were observed on 2026-10-15). Note any
`*.lock` file: a leftover lock moves with the data and is examined, not deleted.

### 5. Move (same-volume rename)

```powershell
if (Test-Path $T) { throw "target exists: stop" }
if ((Get-Item "$P\data").PSDrive.Name -ne (Split-Path $T -Qualifier).TrimEnd(':')) { throw "different volume: stop" }
New-Item -ItemType Directory -Force (Split-Path $T) | Out-Null
Move-Item -LiteralPath "$P\data" -Destination $T
New-Item -ItemType Directory "$P\data" | Out-Null
Move-Item -LiteralPath "$T\stock_category.json5" -Destination "$P\data\stock_category.json5"
git -C $P status --porcelain
```

A directory rename either succeeds whole or fails whole. If `Move-Item` fails
(for example a sharing violation), check that `$P\data` is intact and `$T` absent,
then return to step 2. No junction, symlink or hardlink is created; the old path
keeps only the tracked category file, and `git status` stays clean.

### 6. Verify after the move

```powershell
uv run --no-project python "$R\inventory.py" $T "$R\after.json"
@'
import json, sys
b = json.load(open(sys.argv[1], encoding="utf-8"))["files"]
a = json.load(open(sys.argv[2], encoding="utf-8"))["files"]
b.pop("stock_category.json5", None)  # moved back into the checkout on purpose
diff = sorted(set(a) ^ set(b)) + sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
print("files", len(a), "bytes", sum(e["size"] for e in a.values()), "differences", len(diff))
sys.exit(f"mismatch: {diff[:20]}" if diff else 0)
'@ | uv run --no-project python - "$R\before.json" "$R\after.json"
Get-ChildItem -Force "$P\data"
```

Expect zero differences (size, modification time and SHA-256 identical) and only
`stock_category.json5` left under `$P\data`. Any mismatch: stop, keep tasks
paused, report; do not "fix" by copying.

### 7. Configure the producer

Append one line to the primary producer's existing private `.env`; leave every
other line untouched.

```powershell
Add-Content -LiteralPath "$P\.env" -Value "SHIOAJI_DATA_DIR=$($T -replace '\\','/')"
cd $P
uv run python -c "from config import config; print(config.DATA_DIR, config.DATA_DIR_SOURCE)"
```

Expect `D:\StockData\stock-data-downloader  D:\...\stock-data-downloader\.env`.
A producer development worktree must still print its own `data` and `default`.

### 8. Prove reads, writes and backup on the new root

1. Read-only coverage: follow the producer's `docs/data-progress.md` from `$P`.
   It prints the database path (now under `$T`) and the same per-market coverage
   as before the move.
2. Backup still covers the data: `uv run scripts/backup_data.py --verify-only`.
   The mirror compares relative path, size and modification time, so the rename
   needs no recopy; this must pass without copying.
3. A local write, no network: `uv run scripts/check_data_integrity.py` rewrites
   `data_quality_report.json`. Confirm its new modification time under `$T` and
   that nothing new appeared under `$P\data`.
4. `uv run scripts/backup_data.py` then mirrors that one changed report into
   `D:/StockDataBackup/data`.

### 9. Point research at the new root

In the primary research checkout's ignored `.env.local`, set
`STOCK_PRODUCER_DATA_ROOT=D:/StockData/stock-data-downloader` (replacing the
nonexistent `D:/Project/stock-data-downloader/data`). Read the resolved root back
with the research resolver; inspect any process/user/machine override first.

### 10. Resume and confirm

Re-enable the same two tasks only with the owner's go-ahead:

```powershell
Enable-ScheduledTask -TaskName 'StockProject-DailyUpdate','StockProject-OfficialBackfill'
```

After the next scheduled runs, each log
(`$P\logs\run_daily_<date>.log`, `backfill_official_history_<date>.log`) starts
with `data directory: D:\StockData\stock-data-downloader (...\.env)`, the run
exits 0 and `$P\data` still holds only the category file. Record the outcome
below.

## Stop conditions

Stop, keep the tasks paused and ask the owner when: a task is `Running` or any
process references the data; a checkpoint is busy or `quick_check` fails; the
target exists; volumes differ; a reparse point appears; the move or verification
fails; or step 7/8 shows the old path in use. Never delete, overwrite or recopy
data to get past a stop.

## Rollback

While both tasks are paused: remove the `SHIOAJI_DATA_DIR` line from `$P\.env`,
move `$P\data\stock_category.json5` into `$T`, remove the now-empty `$P\data`
directory, then `Move-Item $T "$P\data"`. Any files written at `$T` after the move
travel back with it. Restore `.env.local`, re-run the step 6 comparison against
the restored path, then re-enable the tasks.

## Execution record

| Date | Operator | Before (files / bytes) | After | Result       |
| ---- | -------- | ---------------------- | ----- | ------------ |
| —    | —        | —                      | —     | not executed |
