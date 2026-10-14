---
name: check-daily-log
description: Points to the stock-data-downloader submodule's own check-daily-log command for reviewing today's scheduled data-pipeline logs. Use when asked to check today's log, whether the daily download ran, or for errors in the automated pipeline.
---

# Skill: Check-Daily-Log

This repo does not own the scheduled data pipeline or its logs — the
`stock-data-downloader` submodule does (own Windows Task Scheduler tasks, own
`logs/` directory, own `data_quality_report.json`). This skill is a pointer,
not a duplicate procedure, so the two never drift apart.

## Procedure

Use the primary checkout's producer, `<primary stock-research checkout>/stock-data-downloader/`
(here `D:/Project/stock-research/stock-data-downloader/`). Linked worktrees no longer
initialize the submodule (2026-10-15), so a worktree's own `stock-data-downloader/` is
empty or stale; never read logs or data from it.

1. Read and follow
   `<primary>/stock-data-downloader/.claude/commands/check-daily-log.md` verbatim —
   that file is the source of truth for what to check and how to report it.
2. Run its steps with a working directory of that primary `stock-data-downloader/`, since
   all paths in that command (`logs/`, `data/data_quality_report.json`,
   `data/official_daily.sqlite`) are relative to the submodule root, not this
   repo's root.
3. Report back in the format that command specifies (a short Traditional
   Chinese summary). Do not add unrelated repo-wide status to the report.

If the submodule file's content ever meaningfully diverges from what this
pointer describes, trust the submodule file — it is edited independently of
this repo and may move ahead of this skill's cached understanding of it.
