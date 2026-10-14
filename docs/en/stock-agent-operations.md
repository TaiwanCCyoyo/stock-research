# stock-research Agent Operations

Read with the root `AGENTS.md` before worktree/data operations or research reporting.

## Data And Worktrees

- Owner update 2026-10-12: formal shared research versions use the primary `research_data/` catalog. Worktrees read explicit pinned versions through the absolute `STOCK_RESEARCH_DATA_ROOT` setting, with no copy, symlink, junction or hardlink. Existing task/cache artifacts are registered in place; producer inputs are read as sealed versions (below), not copied. Root/path/link validation and the isolated Windows deletion contract are in [shared entry v1](../../tasks/20261012-research-data-entry/data-contract.md). Read-only attributes are supplementary, not access isolation or backup. Before removal verify the exact task target cannot contain primary/shared data and rerun the worktree isolation check; never test deletion on actual research data.

- Before removing a stock-research worktree, inventory its ignored task datasets, `runs/`, any producer inputs copied by the retired seeding hook and other needed artifacts separately from tracked status. The generic inventory does not measure ignored files inside tracked submodules: inspect `stock-data-downloader/data/` explicitly, including reparse attributes. Preserve session-owned reusable outputs in the primary canonical location with provenance, integrity checks, backup coverage and an indexed data contract before cleanup; never overwrite existing artifacts or import a frozen input snapshot into live producer data. If ownership, equivalence or preservation is unknown, retain the worktree and report the blocker. Existing canonical data needs no duplicate copy merely because a worktree is removed.

- Owner update 2026-10-08: acquisition, minute-to-daily conversion, official/source consolidation, raw corporate-action facts, metadata/calendar, institutional/revenue normalization and source backups belong in `stock-data-downloader`. stock-research owns research price restoration policy, indicators, support/resistance, patterns and derived-cache/experiment backups. See [derived data](research-derived-data.md). Historical producer SMA/EMA and technical_features remain compatibility artifacts until the separately coordinated migration; new research must use stock-research definitions.
- Immutable stock-research caches live at `<primary stock-research checkout>/research_cache/<family>/<version>/`. Worktrees read explicit absolute versions directly, never copy them or create links; record version and manifest hash in the mission. Producer inputs, `price_daily.parquet` included, are read the same way as sealed versions. Cache builds are on demand, version-additive and independent of the producer's schedule; do not introduce schedules or mutate raw inputs.
- Reshaping those artifacts is allowed when it improves research quality, data access or reuse, or removes repeated work — an added column, index, or status file, or a restructured table — under the constraints in `.claude/rules/common/data-structures.md`: never destroy existing data, never break a stored result's readability, and always check the download schedule first rather than assuming a window is free — `StockProject-OfficialBackfill` caught up with its history on 2026-08-27 and now finishes in seconds, but it still runs ~1.5h on the first run after a month rolls over, and `StockProject-DailyUpdate` holds 18:00–18:45 on weekdays — it ran 19–45 min over the twelve weekday runs to 2026-09-08, nine of which overlapped the backfill's 18:25 trigger. Never kill processes indiscriminately; `taskkill /F /IM python.exe` has already ended a backfill mid-run.
- Owner update 2026-10-15: research worktrees copy **no** producer data and need no initialized `stock-data-downloader` submodule. The producer research read-set (`price_daily.parquet`, `*_day.csv`, corporate-action/metadata/institutional/revenue SQLite, mapping/classification, dividends, the data-quality report and retained `adjusted_prices/daily` legacy inputs when present) is sealed once into an immutable version at `<primary>/research_cache/producer-inputs/<version_id>/` and read in place by `version_id` plus manifest SHA-256 through the explicit `STOCK_RESEARCH_DATA_ROOT`, never through a symlink, junction or hardlink, with no fallback to live data. SQLite members are online-backup snapshots in rollback-journal mode, so read-only opens create no sidecars. Seal with `uv run python -m scripts.seal_producer_inputs seal` only while producer writers are idle (it refuses while a `StockProject-*` task runs and inside the weekday 17:50-19:00 window); seal on demand, since each changed version costs about 5 GB. Live dashboards and queries read `producer_data_root()` explicitly. Layout, identity, reader API and the first version are in [sealed producer inputs](../../tasks/20261015-sealed-producer-inputs/data-contract.md).
- A sealed version never follows producer refreshes; a study that needs newer data seals a new version and records the new pin. Authorized acquisition/backfill and data-refresh scripts run from the primary producer checkout and write its canonical data location; the excluded bulk (`*_min.csv`, `official_daily.sqlite`, `raw/`) remains producer-owned. See [canonical data updates](#canonical-data-updates) for cross-session handoff.
- The quota-limited producer cache remains backed up by its own `backup_data.py` inside `run_daily.py`, additively with verification. stock-research now separately backs up its immutable caches, task datasets and owner labels; the producer backup does not cover those. See [backup scopes and restore](price-cache-backup.md). No stock-research backup is silently added to the producer's scheduler.
- `.githooks/post-checkout` is retired (2026-10-15): new linked worktrees neither initialize the submodule nor copy data. `core.hooksPath` points at the primary checkout's `.githooks`, so this takes effect once primary `main` carries the removal. Producer code development uses its own producer task worktrees ([below](#submodule-development-and-delivery)), not a stock-research worktree's submodule. Linking previously caused real data loss when worktree removal traversed a junction into main; inspect Windows reparse attributes before any cleanup and do not assume `os.path.islink` detects every junction.
- `scripts/seed_worktree_inputs.py` remains a manual legacy tool for reproducing the old physical-snapshot layout; no hook runs it. Worktrees seeded before 2026-10-15 keep their snapshots and `.tmp/worktree-seed-*/receipt.json` inventories; historical task runners and SHA-pinned evidence keep reading them. Those receipts never certified whole-input coherence and an existing file without original provenance remains unknown; do not replace preserved files or mix them with sealed versions.

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
directory is the canonical source for other sessions and future sealed producer-input versions.
Check its existing artifacts, coverage and update records before downloading or
recomputing shared data; reuse or extend what is available. When acquisition,
backfill or refresh is authorized, run the integrated producer code there,
coordinate scheduled/manual writers first, and preserve the existing
backup and restore path. Research reads sealed producer-input versions; development
worktrees hold test fixtures. Shared downloads and refreshes target the canonical producer data
directory; `.tmp/` and development worktrees cannot be the only lasting location
of new shared data.

Record the canonical artifact paths, source/input versions, coverage, retrieval or
update time, producer commit and observed backup status in existing producer
receipts/manifests and link them from the task's data description. Mark unverified
items and gaps explicitly so another session can find the update without chat.
Gitlink updates select code; they neither transfer ignored data nor refresh older
worktree snapshots or sealed versions. A refresh is a new sealed version with its own
pin; preserve sealed research inputs rather than silently replacing them.

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
