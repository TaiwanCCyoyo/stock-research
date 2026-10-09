# Research views (optional)

This directory contains shared presentation/data helpers used by the current API
and optional static report builder. It is not the task workspace. Evidence lives under `tasks/`; new
headless contracts and accounting utilities live in `research_core/`.

Start with [the research foundation](../docs/en/research-foundation.md). Chat
reports and deterministic CLI/MCP queries are the primary research interface.
Dashboard feature expansion is paused; do not require a new view for every study.

## Rules

- Treat `StockProject/engine/` as read-only.
- Write experimental strategies, logs, and notes under approved research paths only.
- Record every experiment with the strategy file, input parameters, backtest command, result summary, and conclusion.
- Do not store secrets, API keys, account tokens, or broker credentials in this directory.
- Do not place real trading logic here until a separate safety review exists.

Shared readers and pure presentation helpers do not import Panel or Plotly at
runtime. Historical imports from `dashboard_core` remain supported; only calling
static rendering functions requires the `static-report` dependency group.

## Local Dashboard

Build the static research dashboard entry point:

```bash
uv run --group static-report python -m scripts.build_research_dashboard
```

Open `research_lab/site/index.html` to review completed task dashboards.
This optional legacy exporter reads every eligible task summary and uses CDN
resources. Do not run it over sealed periods or as a prerequisite for new research.

The current React viewer is launched from the repository root:

```bash
.\scripts\research\open_research_dashboard.cmd
```

It serves on port 8503. The old Panel server on port 8502 has been removed.
Panel is installed only for the optional static report builder, not the React viewer.

## Execution Boundary

Approved research runs through task-specific Python commands. Docker is optional;
the existing configuration needs repair and verification before use (see the root
README). The viewer cannot start research or manage backtest jobs. Neither opening
a view nor verifying infrastructure authorizes a backtest or changes research gates.
