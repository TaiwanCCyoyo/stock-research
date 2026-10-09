---
name: check-data-progress
description: Points to the stock-data-downloader submodule's own check-data-progress command for checking how far data/official_daily.sqlite has been updated. Use when asked how far the database is updated, what date the data goes up to, or to check backfill progress.
---

# Skill: Check-Data-Progress

This repo does not own the official-price database or its update
history — the `stock-data-downloader` submodule does (own
`data/official_daily.sqlite`, own daily-fetch and backfill scripts). This
skill is a pointer, not a duplicate procedure, so the two never drift apart.

## Procedure

1. Read and follow
   `stock-data-downloader/.claude/commands/check-data-progress.md` verbatim —
   that file is the source of truth for what to check and how to report it.
2. Run its steps with a working directory of `stock-data-downloader/`, since
   all paths in that command (`data/official_daily.sqlite`) are relative to
   the submodule root, not this repo's root.
3. Report back in the format that command specifies (a short Traditional
   Chinese summary). Do not add unrelated repo-wide status to the report.

If the submodule file's content ever meaningfully diverges from what this
pointer describes, trust the submodule file — it is edited independently of
this repo and may move ahead of this skill's cached understanding of it.
