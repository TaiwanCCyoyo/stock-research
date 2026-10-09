## Why

The user's core complaint is that the Panel dashboard looks and feels like "a crude report,"
not the modern, directly-operable research workbench they expected: there is no button to
re-run a backtest, no way to reselect a stock range or edit strategy parameters from the UI,
and even the newest capital-mode comparison view still looks unpolished. Panel's rendering
model (Plotly-based candlesticks, full-page reactive rebuilds) also caps how fast and fluid
the interface can feel. This change replaces the dashboard's frontend with a React +
TradingView lightweight-charts application served by the read-only API from
`add-research-api`, and adds the missing operability: triggering backtests and editing
parameters directly from the UI.

## What Changes

### 6a already covered by `add-research-api`

This change assumes `add-research-api`'s read-only endpoints exist and are stable.

### 6b — Frontend skeleton

- New React + TypeScript + Vite application consuming `add-research-api`'s endpoints.
- Pages: task browser (with industry/universe filtering from `add-universe-management`
  once available), K-line workbench (TradingView lightweight-charts: candles, MA overlays,
  buy/sell markers, corporate-action markers, optional institutional buy/sell subplot from
  `add-institutional-data-pipeline` once available), trade table with click-through
  drilldown (trigger reason, cash/position context), and the capital-mode/universe
  comparison view.
- Visual design: dark-mode-first modern trading-research aesthetic, following this
  project's `dataviz` skill color discipline for consistency and accessibility.

### 6c — Backtest trigger and parameter editing

- New write endpoint `POST /backtests` (added to the API service from `add-research-api`)
  accepting strategy selection (scanned from task `candidates/*.py`), universe/code
  selection, date range, cash, capital mode, and strategy parameters (auto-generated form
  from the strategy's params JSON schema, with a raw-JSON edit fallback).
- The endpoint runs `scripts/run_task_backtest.py` as a background subprocess; the frontend
  polls job status and tails log output, and the new result appears in the task browser on
  completion.
- This directly closes the "no button to re-run, no idea how to edit params or type the
  command" gap.

### 6d — Parity validation and Panel retirement

- Once the new frontend covers every view Panel currently provides (verified against the
  `research-dashboard` spec's existing requirements), `open_research_dashboard.cmd` is
  repointed to the new service and the Panel implementation moves to `legacy/`.

## Capabilities

### New Capabilities

- `research-dashboard-v2`: the React frontend's presentation and interaction contract
  (task browsing, K-line workbench, trade drilldown, comparison views).
- `backtest-trigger-api`: the write endpoint and background-job contract for triggering a
  backtest and editing parameters from the UI.

### Modified Capabilities

- `research-dashboard`: once parity is reached, the "MUST discover task artifacts" and
  presentation requirements are satisfied by the new frontend instead of Panel; Panel-only
  implementation details are retired, the observable contract is preserved.

## Non-Goals

- No change to backtest artifact formats, engine behavior, or the trade-query deterministic
  core — this change is presentation and orchestration only.
- No multi-user auth, deployment, or hosting beyond localhost — same trust model as today.
- No mobile-responsive design requirement — this is a desktop research tool.
- Docker-backed execution is not required for local validation; note any skipped Docker
  checks in completion notes.

## Impact

- New frontend application directory (e.g. `research_web/`).
- `add-research-api`'s service gains a `POST /backtests` write endpoint and job-status
  endpoints.
- `open_research_dashboard.cmd` eventually repoints to the new service (only after parity,
  task 6d).
- Existing Panel code (`research_lab/`) moves to `legacy/` once retired, not deleted.
- This is the largest and longest-running change in the roadmap; expect it to be worked
  incrementally across multiple sessions, with 6b/6c/6d tracked as distinct sections in
  `tasks.md`.
