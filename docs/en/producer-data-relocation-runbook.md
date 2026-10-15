# Producer data relocation runbook

Owner decision 2026-10-15: the producer's live data leaves the research checkout so
that the repository and its worktrees carry no production data. Only the data
moves; the producer code stays the `stock-data-downloader` submodule and the two
scheduled tasks keep running from `D:/Project/stock-research/stock-data-downloader`.

**Status: relocation completed on 2026-10-15 at 04:11:32 UTC**, as recorded by the
private delivery receipt summarized in the [execution record](#execution-record).
Both configured roots were verified as `D:/StockData/stock-data-downloader`.
This is recorded execution evidence, not a new live-data check. **Do not rerun the
move on this host.** Adopting a later producer gitlink is a code-only deployment,
subject to the writer-idle gates; it does not require another data move.

The procedure below is for a separately approved **future relocation only**:
data must still be in the checkout and the target must be absent. It supports
producer `7e8bf5ec823dcfe38df9342d927bea24b8a2debc` (PR #3) or a compatible
descendant, where the tracked category resource lives in `config/`. The completed
relocation used producer `069205bc27bd309eb9c86e5308328e8a71da3536` (PR #2), with
the category still in `data/`; see [historical layout](#historical-layout).
Approval of this document or its PR is not approval of a new move or rollback.

## Decisions

| Item                                  | Decision                                                                                  | Why                                                                                                                                                                                                                        |
| ------------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Target                                | `D:/StockData/stock-data-downloader`                                                      | Same NTFS volume as the source (`D:`), so the move is a directory rename. D: had 45.4 GB free on 2026-10-15; a 42.6 GB copy would nearly fill it. Named after its producer; sits beside the existing `D:/StockDataBackup`. |
| Producer setting                      | `SHIOAJI_DATA_DIR` in the producer primary checkout's own `.env`                          | The scheduled launchers already run in that checkout; no task-action or machine-environment change. Pairs with the existing `SHIOAJI_BACKUP_DIR`.                                                                          |
| Not a user/machine env var            | —                                                                                         | It would leak into every producer worktree and research process.                                                                                                                                                           |
| Tracked `config/stock_category.json5` | Stays with the code, outside the mutable-data move, inventory and rollback                | Producer PR #3 moved it byte-identically out of `data/`; no category extraction or comparison exclusion is needed.                                                                                                         |
| Research setting                      | stock-research `.env.local` `STOCK_PRODUCER_DATA_ROOT=D:/StockData/stock-data-downloader` | Distinct, consumer-owned name. Changed at step 9, not earlier.                                                                                                                                                             |

Producer behaviour this relies on ([stock-data-downloader#2](https://github.com/TaiwanCCyoyo/stock-data-downloader/pull/2),
`docs/operations.md#data-location` there): a configured value must be an absolute,
existing, link-free directory outside the checkout, otherwise every entry point
stops at import; a configured root is never created; each checkout reads only its
own `.env`, so producer worktrees keep their own `data/`.

## Preconditions (all must hold; otherwise stop)

1. For a future relocation, the supported producer version above must be merged
   and selected by a merged stock-research gitlink. Deploy it inside the approved
   window (step 2b), after writers are idle. This prerequisite does not mean the
   completed relocation is pending a later gitlink update.
2. The primary research checkout `D:/Project/stock-research` is on `main` with no
   uncommitted tracked changes. Another session's work there is never reset,
   stashed or switched; otherwise stop and coordinate with its owner.
3. Research readers resolve through `producer_data_root()` (environment, then the
   primary `.env.local`; no fallback). In a future pre-move setup it must resolve
   the existing in-repository source; step 9 changes it to the external target.
   The earlier incorrect-root observation is historical: the completion receipt
   verifies both producer and research at the external root. Read back the
   resolved path, not the whole private settings file. There is no worktree
   seeding or input sealing to migrate (owner re-scope of stock-research#20).
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
if (Test-Path -LiteralPath $T) { throw "target exists: relocation already completed or needs separate investigation; stop" }
New-Item -ItemType Directory -Force $R | Out-Null
```

### 1. Record and pause the tasks (owner-approved)

```powershell
$enabledBefore = @()
foreach ($n in 'StockProject-DailyUpdate','StockProject-OfficialBackfill') {
  Export-ScheduledTask -TaskName $n | Set-Content -Encoding Unicode "$R\$n.xml"
  $task = Get-ScheduledTask $n
  $i = Get-ScheduledTaskInfo -TaskName $n
  '{0} state={1} lastResult={2} next={3}' -f $n, $task.State, $i.LastTaskResult, $i.NextRunTime
  if ($task.State -ne 'Disabled') { $enabledBefore += $n }
  Disable-ScheduledTask -TaskName $n | Out-Null
}
$enabledBefore | Set-Content "$R\enabled-before.txt"
```

Disabling prevents new starts only. It does not stop a running process.
`enabled-before.txt` lists the tasks that were enabled; step 10 and the rollback
re-enable only those, so a task the owner had already paused stays paused.

### 2. Wait for every writer and reader to exit — never kill

```powershell
Get-ScheduledTask -TaskName 'StockProject-*' | Select TaskName, State
Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'stock-data-downloader|stock-research|official_daily|StockData' } |
  Select ProcessId, Name, CommandLine
```

Proceed only when neither task is `Running` and no listed process can be using the
data (other sessions' seeders, research APIs, notebooks, editors). A command line
does not reveal every open file, so the binding gates are step 3 (no SQLite side
files remain) and step 5 (a directory rename refuses while any handle is open).
If something does not exit by itself, defer the window and ask its owner. Never
end a process you did not start.

### 2b. Deploy the merged producer code (writers idle)

Old code ignores `SHIOAJI_DATA_DIR` and would recreate `data/` and start
downloading into it, so the primary producer must run the merged code before the
setting exists.

```powershell
git -C D:\Project\stock-research status --short --branch --untracked-files=no
git -C D:\Project\stock-research -c submodule.recurse=false pull --ff-only
git -C D:\Project\stock-research submodule update -- stock-data-downloader
git -C $P log -1 --format=%H
cd $P
uv run python -c "from config import config; assert config.STOCK_CATEGORY.is_file(); print(config.DATA_DIR_ENV, config.DATA_DIR, config.DATA_DIR_SOURCE); print(config.STOCK_CATEGORY)"
```

Run the pull only when the status shows `## main...origin/main` and nothing else;
otherwise stop. The producer HEAD must equal the merged commit the gitlink names,
and this future pre-move read-back must print
`SHIOAJI_DATA_DIR ...\stock-data-downloader\data default`, followed by
`...\stock-data-downloader\config\stock_category.json5`. Stop if the category
resource is missing or the producer is still on the earlier layout. On an already
relocated host the data root is external instead: do not enter this procedure.
Both task actions already point at this checkout's `cron/` launchers, so no action
migration is needed.

### 2c. Preflight: links and volume

Check before touching any file. A junction or mount point anywhere on either path
can put the data on another volume while the drive letters look equal, and would
make the rename follow a link.

```powershell
function Test-Reparse([string]$path) {
  $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
  while ($item) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $item.FullName }
    $item = $item.Parent
  }
}
foreach ($path in "$P\data", $P, (Split-Path $T)) {
  if (Test-Path -LiteralPath $path) { $hit = Test-Reparse $path; if ($hit) { throw "reparse point at $($hit): stop" } }
}
if (Test-Path -LiteralPath $T) { throw "target exists: stop" }
$sourceVolume = (Get-Volume -FilePath "$P\data").UniqueId
$targetVolume = (Get-Volume -DriveLetter (Split-Path $T -Qualifier).TrimEnd(':')).UniqueId
if ($sourceVolume -ne $targetVolume) { throw "different volume: stop" }
```

`D:\StockData` may not exist yet; its drive root is then checked through the
volume comparison. Step 4 additionally rejects reparse points inside the data tree.

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

A reparse point anywhere stops the procedure. Record the printed count and bytes;
expect the magnitude of the 2026-10-09 copy receipt (15,245 files,
42,570,473,861 bytes) plus later daily growth. Note any
`*.lock` file: a leftover lock moves with the data and is examined, not deleted.

### 5. Move (same-volume rename)

```powershell
if (Test-Path $T) { throw "target exists: stop" }
if ((Get-Item "$P\data").PSDrive.Name -ne (Split-Path $T -Qualifier).TrimEnd(':')) { throw "different volume: stop" }
New-Item -ItemType Directory -Force (Split-Path $T) | Out-Null
Move-Item -LiteralPath "$P\data" -Destination $T -ErrorAction Stop
git -C $P status --porcelain
```

A directory rename either succeeds whole or fails whole. If `Move-Item` fails,
inspect both paths; return to step 2 only if `$P\data` is intact and `$T` absent.
If the rename succeeded but a later status, verification or configuration step
fails, the data is already at `$T`: keep tasks paused, preserve that state and
report it. Do not rerun the move or assume the old path still exists.
No junction, symlink or hardlink is created. `$P\data` is absent after success;
the tracked category remains untouched in `$P\config` and Git stays clean.

### 6. Verify after the move

```powershell
uv run --no-project python "$R\inventory.py" $T "$R\after.json"
@'
import json, sys
b = json.load(open(sys.argv[1], encoding="utf-8"))["files"]
a = json.load(open(sys.argv[2], encoding="utf-8"))["files"]
diff = sorted(set(a) ^ set(b)) + sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
print("files", len(a), "bytes", sum(e["size"] for e in a.values()), "differences", len(diff))
sys.exit(f"mismatch: {diff[:20]}" if diff else 0)
'@ | Set-Content -Encoding utf8 "$R\compare.py"
uv run --no-project python "$R\compare.py" "$R\before.json" "$R\after.json"
if (Test-Path -LiteralPath "$P\data") { throw "old data path unexpectedly exists: stop and investigate" }
```

Expect zero differences in every inventoried file (size, modification time and
the recorded SQLite/Parquet hashes). The code-owned `config/stock_category.json5`
is outside both inventories; exclude no data-root filename. Any old untracked
category copy in the source must be preserved, compared and reported like any
other file. Any mismatch: stop, keep tasks paused, report; do not "fix" by copying.

### 7. Configure the producer

Append one line to the primary producer's existing private `.env` (CRLF, three
lines, ending in a newline on 2026-10-15); leave every other line untouched. If the
file no longer ends with a newline, add one first, or the new line would fuse with
the last credential. Never print values.

```powershell
$envFile = "$P\.env"
$bytes = [IO.File]::ReadAllBytes($envFile)
if ($bytes.Length -and $bytes[-1] -ne 10) { [IO.File]::AppendAllText($envFile, "`r`n") }
[IO.File]::AppendAllText($envFile, "SHIOAJI_DATA_DIR=D:/StockData/stock-data-downloader`r`n")
cd $P
uv run python -c "from dotenv import dotenv_values; from config import config; print(sorted(dotenv_values(config.ENV_FILE))); print(config.DATA_DIR, config.DATA_DIR_SOURCE)"
```

The key list must hold every earlier key (`API_KEY`, `SECRET_KEY`,
`SHIOAJI_BACKUP_DIR`) plus `SHIOAJI_DATA_DIR`, and the second line must read
`D:\StockData\stock-data-downloader  D:\...\stock-data-downloader\.env`.
A producer development worktree must still print its own `data` and `default`.

### 8. Prove reads, writes and backup on the new root

1. Read-only coverage: follow the producer's `docs/data-progress.md` from `$P`.
   It prints the database path (now under `$T`) and the same per-market coverage
   as before the move.
2. Backup still covers every file at the new root:
   `uv run scripts/backup_data.py --verify-only`. It copies nothing and fails on a
   file missing from the mirror or a same-age size mismatch. It deliberately
   tolerates a stale copy (source newer than mirror) as "one snapshot behind", so a
   pass proves coverage by name, not that the mirror is current.
3. A local write, no network: `uv run scripts/check_data_integrity.py` reads the
   local parquet/SQLite and rewrites only `data_quality_report.json` (it imports no
   network client). Confirm its new modification time under `$T` and
   that nothing new appeared under `$P\data`.
4. `uv run scripts/backup_data.py` then copies every file whose size or
   modification time differs from the mirror (at least the rewritten report, plus
   anything that changed since the last nightly backup) and verifies the result.
   Record the logged copied/verified counts; this run is the proof that the mirror
   is current from the new root.

### 9. Point research at the new root

In the primary research checkout's ignored `.env.local`, set
`STOCK_PRODUCER_DATA_ROOT=D:/StockData/stock-data-downloader` (replacing the
in-repository path). Inspect any process/user/machine override first, then read
the resolved root back from a linked worktree without the variable set:

```powershell
Remove-Item Env:STOCK_PRODUCER_DATA_ROOT -ErrorAction SilentlyContinue
uv run python -c "from research_core.producer_data import producer_data_root; print(producer_data_root())"
```

Expect `D:\StockData\stock-data-downloader`. Docker's fallback mount
`./stock-data-downloader/data` is absent or empty after the move and fails the
`price_daily.parquet` check; always pass `--env-file .env.local`.

### 10. Resume and confirm

Re-enable the same two tasks only with the owner's go-ahead:

```powershell
Get-Content "$R\enabled-before.txt" | ForEach-Object { Enable-ScheduledTask -TaskName $_ | Out-Null; $_ }
```

Only tasks recorded as enabled in step 1 are re-enabled.

After the next scheduled runs, each log
(`$P\logs\run_daily_<date>.log`, `backfill_official_history_<date>.log`) starts
with `data directory: D:\StockData\stock-data-downloader (...\.env)`, the run
exits 0 and `$P\data` has not been recreated; the category remains in `config/`. Record the outcome
below.

## Stop conditions

Stop, keep the tasks paused and ask the owner when: a task is `Running` or any
process references the data; a checkpoint is busy or `quick_check` fails; the
target exists; volumes differ; a reparse point appears; the move or verification
fails; or step 7/8 shows the old path in use. Never delete, overwrite or recopy
data to get past a stop.

## Rollback

Rollback requires a separate owner-approved window. While both tasks are paused,
repeat step 2 (no task `Running`, no process using the data) and step 3 at `$T`
(pass `$T` instead of `"$P\data"` to that Python block; no SQLite side files).
Use the supported config-owned category layout above; it never moves on rollback.

```powershell
uv run --no-project python "$R\inventory.py" $T "$R\rollback-before.json"
if (Test-Path -LiteralPath "$P\data") {
  if ((Get-Item -LiteralPath "$P\data" -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "old data path is a reparse point: stop" }
  [IO.Directory]::Delete("$P\data", $false) # nonrecursive: refuses any existing contents
}
Move-Item -LiteralPath $T -Destination "$P\data" -ErrorAction Stop
uv run --no-project python "$R\inventory.py" "$P\data" "$R\rollback-after.json"
uv run --no-project python "$R\compare.py" "$R\rollback-before.json" "$R\rollback-after.json"
git -C $P status --porcelain
```

The rollback baseline is taken at rollback time, so files legitimately written at
`$T` after the move (for example step 8's `data_quality_report.json`) are expected
and travel back with the directory; comparing against the original `before.json`
would report them as mismatches. If the rename or a later verification fails,
keep tasks paused and inspect both locations; do not repeat or reverse a move
blindly. After a verified return, remove only `SHIOAJI_DATA_DIR` from `$P\.env`,
set the research root back to the verified `$P\data` and check both resolvers
before owner-authorized resumption of only the tasks in `enabled-before.txt`.

## Historical layout

The completed relocation used producer `069205b`, before PR #3. Its tracked
`data/stock_category.json5` was returned to the checkout after moving the data;
the old comparison excluded that code file and rollback returned it to the data
directory first. Those steps apply **only to that earlier layout**, not to the
`7e8bf5e` layout above. The [original procedure at research `758348d`](https://github.com/TaiwanCCyoyo/stock-research/blob/758348df6c5256e3a19c65908c6704da98d30a3e/docs/en/producer-data-relocation-runbook.md)
is retained as historical evidence, not a procedure to rerun on the relocated host.

## Execution record

The private `relocation-delivery-20261015.json` receipt was read during PR #22's
runbook correction; its SHA-256 is
`eacf4b07265715d36127a294308bb825fc2139a29be63d263b4e1bc2f5200771`.
Only this summary is published; private paths, raw logs and settings remain local.

| Completed (UTC)     | Producer / research versions | Before, including old tracked category | Mutable data after move             | Recorded result                                                                                               |
| ------------------- | ---------------------------- | -------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 2026-10-15 04:11:32 | `069205b` / `758348d`        | 14,953 files / 42,625,107,796 bytes    | 14,952 files / 42,625,105,697 bytes | 0 inventory differences after the historical category extraction; logical coverage and both resolvers matched |

The receipt records five SQLite databases passing `quick_check` with no remaining
side files, unchanged scheduler definitions/restored states, and no downloads or
research started. Its additive backup refresh exited 0 (2 copied, 14,953 verified);
the final data check found only the deliberately rewritten
`data_quality_report.json` changed after relocation, matching its mirror. These
are receipt-time observations, not a new validation of live data. The next normal
scheduled runs had not yet occurred and were not manually triggered; that
post-schedule confirmation remains outside the recorded evidence.
