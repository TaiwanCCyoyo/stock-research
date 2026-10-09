---
description: Diagnose an existing research task using its mission and recorded evidence. Usage: /diagnose-strategy <task-id>
---

Provide the task's absolute path and requested output to `strategy-diagnostician`.
It reads the current owner contract, mission and recorded artifacts, then writes
only the authorized `strategy_diagnosis.md`. Report the diagnosis and evidence
in chat; the dashboard is optional. Missing old metrics are limitations to explain,
not authorization to rerun a backtest or invent new acceptance thresholds.
