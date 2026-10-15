# stock-research Agent Operations

Read with the root `AGENTS.md` before worktree/data operations or research reporting.

## Data And Worktrees

- Owner update 2026-10-12: formal shared research versions use the primary `research_data/` catalog. Worktrees read explicit pinned versions through the absolute `STOCK_RESEARCH_DATA_ROOT` setting, with no copy, symlink, junction or hardlink. Existing task/cache artifacts are registered in place; producer inputs are read live, not copied (below). Root/path/link validation and the isolated Windows deletion contract are in [shared entry v1](../../tasks/20261012-research-data-entry/data-contract.md). Read-only attributes are supplementary, not access isolation or backup. Before removal verify the exact task target cannot contain primary/shared data and rerun the worktree isolation check; never test deletion on actual research data.

- Before removing a stock-research worktree, inventory its ignored task datasets, `runs/`, any producer inputs copied by the retired seeding hook and other needed artifacts separately from tracked status. The generic inventory does not measure ignored files inside tracked submodules: inspect `stock-data-downloader/data/` explicitly, including reparse attributes. Preserve session-owned reusable outputs in the primary canonical location with provenance, integrity checks, backup coverage and an indexed data contract before cleanup; never overwrite existing artifacts or import a frozen input snapshot into live producer data. If ownership, equivalence or preservation is unknown, retain the worktree and report the blocker. Existing canonical data needs no duplicate copy merely because a worktree is removed.

- Owner update 2026-10-08: acquisition, minute-to-daily conversion, official/source consolidation, raw corporate-action facts, metadata/calendar, institutional/revenue normalization and source backups belong in `stock-data-downloader`. stock-research owns research price restoration policy, indicators, support/resistance, patterns and derived-cache/experiment backups. See [derived data](research-derived-data.md). Historical producer SMA/EMA and technical_features remain compatibility artifacts until the separately coordinated migration; new research must use stock-research definitions.
- Maintained stock-research derived data lives once under the shared root outside every checkout (`STOCK_RESEARCH_SHARED_ROOT`, resolved by `research_core/shared_data.py`; `D:/StockData/stock-research`), as `derived/<family>-v<N>/` with a `current.json` pointer ([decision](decision-records/2026-10-15-maintained-shared-data.md), [contract](research-derived-data.md#維護中的共用衍生資料)). Worktrees read it in place, never copy or link it, and record the generation read in the run receipt. It is performance-only and rebuildable; producer inputs, `price_daily.parquet` included, are read live and fingerprinted. Updates run on demand outside the producer write window (for example `uv run python -m scripts.maintain_adjusted_daily update`); do not introduce schedules or mutate raw inputs. Legacy hash-named versions under the primary `research_cache/` take no new versions.
- Reshaping those artifacts is allowed when it improves research quality, data access or reuse, or removes repeated work — an added column, index, or status file, or a restructured table — under the constraints in `.claude/rules/common/data-structures.md`: never destroy existing data, never break a stored result's readability, and always check the download schedule first rather than assuming a window is free — `StockProject-OfficialBackfill` caught up with its history on 2026-08-27 and now finishes in seconds, but it still runs ~1.5h on the first run after a month rolls over, and `StockProject-DailyUpdate` holds 18:00–18:45 on weekdays — it ran 19–45 min over the twelve weekday runs to 2026-09-08, nine of which overlapped the backfill's 18:25 trigger. Never kill processes indiscriminately; `taskkill /F /IM python.exe` has already ended a backfill mid-run.
- Owner decision 2026-10-15 ([record](decision-records/2026-10-15-drop-input-sealing.md)): research worktrees copy **no** producer data and need no initialized `stock-data-downloader` submodule. They read the live producer root in place, read-only, through `research_core/producer_data.py::producer_data_root()`, which owns root discovery (`STOCK_PRODUCER_DATA_ROOT`, otherwise the primary checkout's configuration; see that module and the producer relocation runbook) and fails clearly rather than falling back. Nothing is copied or linked into a worktree. Linking previously caused real data loss when worktree removal traversed a junction into main; inspect Windows reparse attributes before any cleanup and do not assume `os.path.islink` detects every junction.
- Live reads are safe only while the producer is idle. Use `research_core/live_producer.py`: call `assert_producer_idle()` once per research run: it refuses the weekday 18:00-18:45 window and any running `StockProject-*` task (which also covers the long first-of-month backfill). Open SQLite with `readonly_sqlite()` (`?mode=ro`; on a WAL database SQLite may still create its own `-shm`/`-wal` files beside the live database, so never delete those while anything may be open). Wrap file reads in `read_stable()`, or compare size/mtime before and after, so a parquet rewritten mid-read fails instead of being half-read. Record what was read with `research_core/run_receipt.py` (input fingerprint, code commit, result SHA-256); writing the receipt re-checks every fingerprinted input, including a SQLite WAL, so a writer that ran during the study fails the run instead of mixing old and new files. The window is evaluated on the producer schedule's clock, Asia/Taipei (UTC+08:00, no daylight saving): an aware timestamp is converted and a naive one is refused. Inputs are classified fail-closed: under a resolvable `producer_data_root()` they are live; without one, an input must be declared (`live_producer=False` for a task-owned file), and a task-owned declaration under the producer root is rejected. `StockProject.backtest_cli` applies all of this at its entry point: it fingerprints the data directory before any read: the `*_day.csv` listing (even when empty), optional inputs recorded as absent when missing, and the corporate-action database the loader actually resolved (data directory, parent or grandparent); refuses the window, routes the SHA-pinned `DataLoader`'s corporate-action SQLite read and `universe.py`'s metadata read through read-only connections, and re-checks the inputs before writing results, which carry the fingerprint in `data.input_fingerprint`. Authorized acquisition/backfill and data-refresh scripts run from the primary producer checkout and write its canonical data location; see [canonical data updates](#canonical-data-updates).
- The quota-limited producer cache remains backed up by its own `backup_data.py` inside `run_daily.py`, additively with verification. stock-research now separately backs up its legacy caches, task datasets and owner labels (maintained shared derived data is rebuildable from producer data and is not backed up); the producer backup does not cover those. See [backup scopes and restore](price-cache-backup.md). No stock-research backup is silently added to the producer's scheduler.
- `.githooks/post-checkout` is retired (2026-10-15): new linked worktrees neither initialize the submodule nor copy data. `core.hooksPath` points at the primary checkout's `.githooks`, so this takes effect once primary `main` carries the removal. Producer code development uses its own producer task worktrees ([below](#submodule-development-and-delivery)).
- `scripts/seed_worktree_inputs.py` remains only as a manual legacy tool; no hook runs it. When run, it backs SQLite up directly into its publish staging file, so no scratch copy remains under `.tmp/` (PR #18). Worktrees seeded before 2026-10-15 keep their snapshots and `.tmp/worktree-seed-*/receipt.json` inventories, and historical task runners and SHA-pinned evidence keep reading them until a separate owner-approved retirement. Those receipts never certified input coherence (`input_set_coherence: not_certified_by_file_seeding`).

## Submodule Development And Delivery

The owner authorizes agents to proactively change schemas, indexes, derived columns
or artifact layout when there is a concrete research benefit. Being a submodule is
not a reason to avoid producer improvements. Aim for intuitive data organization
that other sessions can find, understand and reuse without repeating acquisition
or computation. Keep acquisition and normalization in the producer repository.
Preserve raw evidence, existing data and
stored-result interpretation, plus backup coverage, restore compatibility and the
scheduled daily/backfill pipeline. Prefer additive or versioned formats when an
in-place change would invalidate consumers; destructive migration still needs its
own authorization. The submodule's own instructions and data contracts also apply.

1. Inspect the primary submodule checkout's branch, local changes and current use.
   Develop from its latest remote `main` in a dedicated submodule task worktree.
   Keep the primary checkout on its existing branch; do not switch it to the task
   branch, reset it or use it for experimental edits.
2. Verify and commit the producer change, then deliver its submodule PR and follow
   its current-head CI/review through fixes and thread resolution. The owner merges
   it; neither a worktree commit nor an open PR updates the producer's `main`.
3. After merge, verify the release commit is on remote `main`. Before changing
   production files, follow [deployment](#deploying-a-data-pipeline-update), including
   its writer-idle gate and authorized prevention of new starts. Fast-forward the
   primary submodule's `main` only when it is already on `main`, clean and available
   for that update. If another session owns it, its branch differs or writers are
   active, preserve its state and report the pending production handoff.
4. In a stock-research task worktree based on current `origin/main`, deliberately update the
   gitlink to the merged producer commit and adapt affected consumers/contracts.
   Deliver a separate stock-research PR and follow its CI/review. Do not pin an unmerged or
   unpublished task commit; stock-research merging also remains with the owner.
5. Report both PRs, the merged producer SHA, the primary checkout's actual branch/
   HEAD and stock-research's proposed or merged gitlink. Keep any pending primary update,
   stock-research merge or data refresh explicit; do not call the whole handoff complete
   when only the submodule PR is finished.

This two-repository delivery follows the owner's scoped authorization recorded in
[Git workflow](git-workflow.md#delivery-authorization). It does not authorize direct
pushes to either `main`, arbitrary branch changes or scheduler configuration changes.

## Canonical Data Updates

The shared producer location is `<primary stock-research checkout>/stock-data-downloader/`;
in this workspace it is `D:/Project/stock-research/stock-data-downloader/`. Its configured data
directory is the canonical source that other sessions and worktrees read live.
Check its existing artifacts, coverage and update records before downloading or
recomputing shared data; reuse or extend what is available. When acquisition,
backfill or refresh is authorized, run the integrated producer code there,
coordinate scheduled/manual writers first, and preserve the existing
backup and restore path. Development worktrees hold test fixtures, not input
snapshots. Shared downloads and refreshes target the canonical producer data
directory; `.tmp/` and development worktrees cannot be the only lasting location
of new shared data.

Record the canonical artifact paths, source/input versions, coverage, retrieval or
update time, producer commit and observed backup status in existing producer
receipts/manifests and link them from the task's data description. Mark unverified
items and gaps explicitly so another session can find the update without chat.
Gitlink updates select code; they neither transfer ignored data nor refresh older
worktree snapshots. Leave existing snapshots and sealed research inputs in place
rather than silently replacing them; new studies fingerprint the live inputs.

If previously acquired data exists only in a worktree, report it as a pending
canonical-data handoff. Before an authorized import, verify provenance, schema,
integrity and reader compatibility, coordinate writers and preserve backup/restore
behavior. Follow the producer's consistent snapshot/import procedures; do not copy
a live SQLite database file-by-file or overwrite canonical history blindly.

## Deploying A Data-Pipeline Update

Updating the `stock-data-downloader` gitlink selects code; it does not migrate
Windows task actions. A release that moves launchers into `cron/` requires this
production handoff, following the submodule's
[Windows scheduling procedure](https://github.com/TaiwanCCyoyo/shioaji-stock-prices/blob/49c89190f37b47f57806ab9688236c6b6d70558e/docs/operations.md#windows-scheduling):

1. Before updating production files, inspect both `StockProject-DailyUpdate` and
   `StockProject-OfficialBackfill` actions and states, plus download/backfill
   processes using the primary checkout. Under owner-authorized deployment,
   preserve the task definitions and enabled states, then pause both triggers
   before changing files, including when their actions already use `cron/`.
   Pausing prevents new scheduled starts; it does not stop a running process.
2. Wait until neither task is `Running` and every associated download/backfill
   process, including manual runs and child processes, has exited naturally.
   If the writers cannot be verified idle, defer deployment and ask the owner.
   Do not terminate another session's process. Only after this gate may the
   production checkout be pulled or its submodule updated.
3. After the release's `cron/` files are present in the primary checkout, run
   `./cron/setup_scheduled_tasks.ps1 -UpdateActionsOnly` from its
   `stock-data-downloader` directory. This preserves triggers, principal, settings
   and enabled state; it does not start a task. Skip migration when both actions
   already reference that checkout's `cron/` launchers.
4. Confirm both actions reference existing `cron/` VBS files and their adjacent
   CMD files before any owner-authorized resumption. Keep paused tasks paused
   until the owner authorizes resuming them.

Do not migrate task actions or register tasks from a development worktree. Task
action or enabled-state changes require owner authorization. A code-update
request alone does not authorize downloads or resuming a paused task.

## Communicating With The Owner

The owner asked for this on 2026-09-06, after a research summary they could not act on.

- **Assume no finance, statistics or backtesting vocabulary in the conversation.** The owner
  is the domain expert on what they want and a layperson on how it is measured. Words like
  turnover, pool share, capture, participation, drawdown, holdout, plateau and asymmetry mean
  nothing to them unless the sentence defines them in passing. Prefer the thing itself: "how
  many times you buy in a year", "how much of the big moves you actually caught", "the years
  the backtest never saw".
- **Put numbers in units they live in.** `drag 4.97%` is not a number they can weigh;
  "about NT$500,000 a year on a NT$10M account" is. Convert rates to money, ratios to
  "X times out of Y", and index-like metrics to a percentage of the current setting.
- Present material owner choices clearly. Use an interactive comparison when it makes the decision easier, without prescribing a particular UI tool or asking again about an already-settled choice.
- **Say which parts are your opinion and which the data settled**, and say plainly when a
  threshold was your choice rather than theirs. Several research verdicts on this project turn
  on bars this project invented; the owner cannot weigh a result without knowing that.
- **This applies to the conversation, not to the committed record.** `tasks/*/mission.md` and
  `tasks/*/report.md` stay precise and technical: they are the audit trail, they are read by
  the other research line, and dumbing them down would lose the evidence. Translate at the
  point of delivery instead.
