# Stock Agent Operations

Read with the root `AGENTS.md` before worktree/data operations or research reporting.

## Data And Worktrees

- Before removing a Stock worktree, inventory its ignored task datasets, `runs/`, copied producer inputs and other needed artifacts separately from tracked status. The generic inventory does not measure ignored files inside tracked submodules: inspect `stock-data-downloader/data/` explicitly, including reparse attributes. Preserve session-owned reusable outputs in the primary canonical location with provenance, integrity checks, backup coverage and an indexed data contract before cleanup; never overwrite existing artifacts or import a frozen input snapshot into live producer data. If ownership, equivalence or preservation is unknown, retain the worktree and report the blocker. Existing canonical data needs no duplicate copy merely because a worktree is removed.

- Owner update 2026-10-08: acquisition, minute-to-daily conversion, official/source consolidation, raw corporate-action facts, metadata/calendar, institutional/revenue normalization and source backups belong in `stock-data-downloader`. Stock owns research price restoration policy, indicators, support/resistance, patterns and derived-cache/experiment backups. See [derived data](research-derived-data.md). Historical producer SMA/EMA and technical_features remain compatibility artifacts until the separately coordinated migration; new research must use Stock definitions.
- Immutable Stock caches live at `<primary Stock checkout>/research_cache/<family>/<version>/`. Worktrees read explicit absolute versions directly, never copy them or create links; record version and manifest hash in the mission. Mutable `price_daily.parquet` remains an explicit physical input snapshot. Cache builds are on demand, version-additive and independent of the producer's schedule; do not introduce schedules or mutate raw inputs.
- Reshaping those artifacts is allowed when it improves research quality, data access or reuse, or removes repeated work — an added column, index, or status file, or a restructured table — under the constraints in `.claude/rules/common/data-structures.md`: never destroy existing data, never break a stored result's readability, and always check the download schedule first rather than assuming a window is free — `StockProject-OfficialBackfill` caught up with its history on 2026-08-27 and now finishes in seconds, but it still runs ~1.5h on the first run after a month rolls over, and `StockProject-DailyUpdate` holds 18:00–18:45 on weekdays — it ran 19–45 min over the twelve weekday runs to 2026-09-08, nine of which overlapped the backfill's 18:25 trigger. Never kill processes indiscriminately; `taskkill /F /IM python.exe` has already ended a backfill mid-run.
- Mutable producer inputs are **copied, never linked**, into a new worktree: `price_daily.parquet`, `*_day.csv`, corporate-action/metadata/institutional/revenue SQLite snapshots, mapping/classification and dividends. Retained formal daily-price files under `adjusted_prices/daily` are also physical legacy input snapshots for unmigrated sample/runtime consumers, not newly calculated Stock caches. The explicit whitelist is maintained in `scripts/seed_worktree_inputs.py`; unknown artifacts, minute/raw stores, `technical_features` and new immutable derived caches are not copied. Existing snapshots are never overwritten. Stable files retain source nanosecond modification times so CSV/parquet freshness comparisons remain meaningful. Under the one-writer-per-worktree contract, an exclusive per-file seeder lock guards same-directory staging, checksum verification and atomic rename; interrupted partials remain diagnostic files, never published inputs. SQLite uses its online backup API to include committed WAL data, not a live database file copy; its copied timestamp is that of the completed snapshot, not the live main DB file. Linking previously caused real data loss when worktree removal traversed a junction into main. Inspect Windows reparse attributes before any cleanup; do not assume `os.path.islink` detects every junction.
- A worktree's `data/` copy is a snapshot taken at creation time; it does not follow the main checkout's refreshes. Authorized acquisition/backfill and data-refresh scripts run from the primary producer checkout and write its canonical data location; the excluded bulk (`*_min.csv`, `official_daily.sqlite`, `raw/`) remains producer-owned. See [canonical data updates](#canonical-data-updates) for cross-session handoff.
- The quota-limited producer cache remains backed up by its own `backup_data.py` inside `run_daily.py`, additively with verification. Stock now separately backs up its immutable caches, task datasets and owner labels; the producer backup does not cover those. See [backup scopes and restore](price-cache-backup.md). No Stock backup is silently added to the producer's scheduler.
- The tracked `.githooks/post-checkout` initializes submodules only for a fresh linked worktree (all-zero previous SHA), with a local object-store fallback when the pinned commit is unavailable remotely. It then calls `uv run --no-project python -m scripts.seed_worktree_inputs`: shell-neutral Python owns snapshot selection, checksums, SQLite backup and a `.tmp/worktree-seed-*/receipt.json`. It never deletes data or copies `technical_features`/`research_cache`. Failure is nonfatal to checkout but means research inputs are incomplete; inspect the receipt and finish the required snapshot before research. The hook requires the clone's configured `core.hooksPath` and `uv`; changing an existing branch does not refresh its data.
- Seeder receipts include full new and preserved file inventories, not just retained names. An existing file without original provenance remains unknown; the currently observed producer reference is not its original source identity. Byte equality is not logical SQLite/WAL equality or cross-source PIT coherence. Seeding never certifies whole-input coherence; when preserved provenance is unknown or current stable-source bytes differ, `source_alignment_required` is true. Verify the intended frozen data bundle before research rather than mixing retry outputs or silently replacing preserved files.

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
4. In a Stock task worktree based on current `origin/main`, deliberately update the
   gitlink to the merged producer commit and adapt affected consumers/contracts.
   Deliver a separate Stock PR and follow its CI/review. Do not pin an unmerged or
   unpublished task commit; Stock merging also remains with the owner.
5. Report both PRs, the merged producer SHA, the primary checkout's actual branch/
   HEAD and Stock's proposed or merged gitlink. Keep any pending primary update,
   Stock merge or data refresh explicit; do not call the whole handoff complete
   when only the submodule PR is finished.

This two-repository delivery follows the owner's scoped authorization recorded in
[Git workflow](git-workflow.md#delivery-authorization). It does not authorize direct
pushes to either `main`, arbitrary branch changes or scheduler configuration changes.

## Canonical Data Updates

The shared producer location is `<primary Stock checkout>/stock-data-downloader/`;
in this workspace it is `D:/Project/stock-research/stock-data-downloader/`. Its configured data
directory is the canonical source for other sessions and future worktree copies.
Check its existing artifacts, coverage and update records before downloading or
recomputing shared data; reuse or extend what is available. When acquisition,
backfill or refresh is authorized, run the integrated producer code there,
coordinate scheduled/manual writers first, and preserve the existing
backup and restore path. Development worktrees hold physical input snapshots and
test fixtures. Shared downloads and refreshes target the canonical producer data
directory; `.tmp/` and development worktrees cannot be the only lasting location
of new shared data.

Record the canonical artifact paths, source/input versions, coverage, retrieval or
update time, producer commit and observed backup status in existing producer
receipts/manifests and link them from the task's data description. Mark unverified
items and gaps explicitly so another session can find the update without chat.
Gitlink updates select code; they neither transfer ignored data nor refresh older
worktree snapshots. Record any deliberate snapshot refresh and preserve sealed
research inputs rather than silently replacing them.

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
