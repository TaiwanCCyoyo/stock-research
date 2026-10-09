---
description: Check how far data/official_daily.sqlite has been updated — latest date per market, gaps in daily coverage, and backfill checkpoint progress. Use when asked how far the database is updated, what date the data goes up to, or to check backfill progress.
---

# Check Data Progress

Delegate this task to `.claude/skills/check-data-progress/SKILL.md`.

The official-price database (`data/official_daily.sqlite`) and its update
history live entirely in the `stock-data-downloader` submodule, not this repo.
The skill points to the submodule's own
`.claude/commands/check-data-progress.md`, which holds the actual procedure.
