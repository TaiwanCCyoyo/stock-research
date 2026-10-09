# Data Structure Changes

The `stock-data-downloader` submodule owns data acquisition; this repo consumes its
artifacts. That ownership rule says where scripts live. It does not say the artifacts'
_shape_ is frozen — and a shape that forces every research task to recompute the same
derived facts is a cost paid forever.

Owner update 2026-10-08: source acquisition/normalization stay in the producer;
research price policies, indicators, support/resistance, patterns and immutable
derived caches now belong in Stock. See [derived-data ownership](../../../docs/en/research-derived-data.md).
New reusable research derivatives are built in Stock, not new producer columns.
Producer SMA/EMA removal and technical_features migration follow a separate
isolated producer PR after replacement availability and frozen legacy inputs;
this does not authorize rewriting old data or invalidating saved results.

## Standing authorization

Proactively reshape or extend the submodule's data artifacts when doing so makes
research data easier to find, understand or reuse, or removes repeated work:
add a derived column, add a small index or status file, restructure a table, precompute
something every study currently recomputes. Prefer additive or versioned artifacts
while checking consumer compatibility and stored-result interpretation. Preserve
backup/restore and scheduled daily/backfill behavior. Development, two-repository
delivery and canonical data updates follow
[Stock agent operations](../../../docs/en/stock-agent-operations.md#submodule-development-and-delivery).

Three conditions bound this, and the third is the one that has already gone wrong.

**Never destroy or overwrite existing data.** The price cache is quota-limited to
reacquire and took days to build. Additive changes and new files are free; anything that
rewrites or deletes in place is not, and needs the user's explicit agreement first.

**Never break a stored result's readability.** Studies cite numbers produced against a
particular artifact shape. If a change would make an existing `runs/` summary or a
committed table unreadable or differently interpreted, it is a destructive change for this
purpose even though no bytes are lost.

**Check the schedule before writing anything under `stock-data-downloader/data/`.** Two
Windows tasks write there:

| task                            | trigger        | duration                                                                 |
| ------------------------------- | -------------- | ------------------------------------------------------------------------ |
| `StockProject-DailyUpdate`      | 18:00, Mon–Fri | 19–45 min end to end, so it finishes some time between 18:19 and 18:45   |
| `StockProject-OfficialBackfill` | 18:25, daily   | ~20-30s on a normal day; ~1.5h on the first run after a month rolls over |

**The two windows overlap more often than not.** Measured over the twelve weekday runs
from 2026-08-21 to 2026-09-08, `DailyUpdate` finished between 18:19 and 18:45, and **nine
of the twelve ran past 18:26** -- so the backfill's 18:25 trigger usually fires while the
daily run is still in its last steps. Both tasks tolerate this today, because the backfill
has nothing left to fetch and exits in seconds while the daily run is rebuilding a cache.
Do not read it as a guarantee. The run after a month rollover is the long one: 2026-08-31
took 61 minutes and ended at 19:01. Treat **18:00 to 18:45** as occupied on a weekday, and
check rather than assume.

The backfill used to hold that slot for roughly 23 hours, and older guidance said to treat
any hour as potentially inside its window. **That stopped being true on 2026-08-27: it
caught up with its history and now exhausts its units in seconds.** Its own logs date it
precisely -- the last long catch-up run finished 2026-08-27 14:50 after 73,338s, and every
scheduled run since has taken 6-31s. Re-verified 2026-09-02:

- 08-28 through 09-02 all logged `reason=units exhausted` in 6-31s, fetching 0 or 1 unit
  against ~276,000 skipped, with zero failures. The exception is 09-01, below.
- All 280,085 checkpoint rows are `ok` or `empty`. None are `error` or `partial`.
- `official_daily_price` covers 2010-01-04 to date, 27.3M rows over the 1,381 TWSE codes
  the backfill walks.
- 51,898 units carry `status='ok'` with `row_count=0`, written by the code that predates
  the `empty` status, and `is_unit_cached` treats `ok` as settled, so they are never
  re-asked. Only 49 of them (10 codes) fall inside a code's own observed official window,
  and every one of those months has zero rows in _both_ feeds — trading suspensions such
  as 1213 in 2019-05..08, not gaps.

`--max-seconds 82800` is unchanged, so the budget still allows 23 hours; the run simply
has nothing left to spend it on. The exception is the first run after a month rollover,
which queues roughly 1,380 fresh per-code units: 2026-09-01 fetched 1,381 and ran 18:29
to 19:56. Expect that on the 1st of each month, and check rather than assume on any date.

```bash
powershell.exe -NoProfile -Command "Get-ScheduledTask -TaskName 'StockProject-*' | ForEach-Object { \$i = \$_ | Get-ScheduledTaskInfo; '{0} state={1} lastResult={2} next={3}' -f \$_.TaskName, \$_.State, \$i.LastTaskResult, \$i.NextRunTime }"
```

`State=Running` means hands off. `official_daily.sqlite-wal` and `-shm` sitting next to the
database mean a writer is attached, or was attached and did not exit cleanly.

## When to stop and ask

Ask the user before proceeding if a change would rewrite existing data in place, if a task
is currently running, or if the work would take long enough to still be going at 18:00 or
18:25. The user's stated preference is to stop the schedule and let the environment go
quiet rather than have a restructure race a download — so surfacing the conflict costs a
short wait, and not surfacing it costs re-downloading rate-limited data.

## Never kill processes indiscriminately

`taskkill /F /IM python.exe` and its equivalents kill the data pipeline along with whatever
you were trying to stop. On 2026-08-23 that command, run to free CPU for a benchmark, ended
the `OfficialBackfill` run about nine hours in, back when it still held the slot for 23 hours. The database survived —
SQLite's WAL recovery is built for exactly this and `PRAGMA quick_check` came back `ok` —
but the progress did not, and it was only recoverable because the backfill checkpoints its
work per range.

Kill by PID, and only PIDs you started. If a benchmark needs a quiet machine, that is a
reason to schedule around the pipeline or tell the user, not a reason to clear the process
table.

## When two feeds write the same rows

An artifact fed by both a daily bulk fetch and a historical backfill has a failure mode
that looks like nothing until it is measured, and `official_daily_price` had it for three
weeks in August 2026. Assume any new pipeline of that shape has it too — the institutional
one is built the same way.

- **The two feeds may not publish the same quantity.** Measure the overlap per segment
  before assuming two sources agree.
- **They share a primary key, so whichever ran last owns the row.** A backfill that selects
  only _gaps_ never revisits a day the bulk already wrote, which makes the seam permanent
  and puts it on the newest data. Select on the **checkpoint table** instead.
- **An empty response must not settle a re-fetch.** These endpoints answer "not published
  yet" with a successful empty. Settling that strands the day on the other feed's values
  permanently — on today's date, every day.
- **Order the daily run so a derived cache is built after the fetch that feeds it**,
  or its newest row comes from the fallback source and flips on the next run.
- **Read an endpoint's observed values before writing a parser against it.** Never key a
  field mapping off the field _count_, and never infer a schema from a response with no
  rows.

Read `skill: market-data-acquisition` before acting on any of this — it carries the
measured evidence behind each point, the checkpoint status table, and what to verify before
declaring acquisition work done.

## Committing in the submodule

`stock-data-downloader` is its own git repository. A delegated committer must not
commit inside it. Under the owner's scoped data-improvement authorization, finish
the producer PR/review, wait for owner merge, safely update its primary `main`, then
deliberately update Stock's gitlink and deliver the Stock PR. Report pending merges
or production/data handoffs; a local commit or staged gitlink alone is not completion.
Follow [delivery authorization](../../../docs/en/git-workflow.md#delivery-authorization)
without asking again for stages already authorized by the owner.

## Related

Read `skill: market-data-cache` for what the current artifacts contain, their units, and
the traps in reading them.
