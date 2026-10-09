---
description: Check today's scheduled data-pipeline logs (run_daily.py, backfill_official_history.py) and data_quality_report.json for problems. Use when asked to check today's log, whether the daily download ran, or for errors in the automated pipeline.
---

# Check Daily Log

Delegate this task to `.claude/skills/check-daily-log/SKILL.md`.

The scheduled data pipeline (Windows Task Scheduler → `run_daily.py` /
`backfill_official_history.py`) and its logs live entirely in the
`stock-data-downloader` submodule, not this repo. The skill points to the
submodule's own `.claude/commands/check-daily-log.md`, which holds the
actual procedure.
