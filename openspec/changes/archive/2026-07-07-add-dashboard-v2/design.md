## Context

Panel's reactive model rebuilds substantial portions of the page on interaction and renders
candlesticks via Plotly, which is heavier than purpose-built financial charting libraries.
The user has explicitly asked for a two-stage approach: first fix Panel's underlying data
performance (`update-price-loading-performance`), then replace the frontend entirely once
a stable read API exists (`add-research-api`). This change is that replacement. It is
intentionally split into three tracked sub-phases (6b/6c/6d) because it is the largest
change in the roadmap and will likely span multiple work sessions and possibly multiple
agents.

## Goals / Non-Goals

**Goals:**

- Deliver a fast, modern, directly-operable research UI: browse tasks, inspect K-lines and
  trades, and — critically — trigger new backtests and edit parameters without touching a
  terminal.
- Reuse `add-research-api`'s read contract verbatim; add only the write endpoint this
  change needs.
- Reach observable parity with the current Panel dashboard's `research-dashboard` spec
  before retiring Panel, so no capability is silently lost.

**Non-Goals:**

- No redesign of what data is computed — only how it is presented and triggered.
- No general-purpose plugin/theming system — one well-designed dark-mode-first UI.
- No real-time streaming market data — this remains a post-hoc research tool over completed
  backtest runs.

## Decisions

**1. React + TypeScript + Vite + TradingView lightweight-charts.**
Lightweight-charts is purpose-built for OHLC/candlestick research UIs, is far lighter than
Plotly for this use case, and has first-class support for markers (buy/sell, corporate
actions) and secondary panes (institutional buy/sell) that this project needs. Vite gives
fast local dev iteration, important since this is a solo-researcher tool where iteration
speed matters. Alternative considered: stay on Panel/Bokeh and only restyle — rejected
per the user's explicit direction; Alternative considered: a heavier framework
(Next.js) — rejected as unnecessary for a local single-page research tool with no
server-rendering requirement.

**2. Backtest triggering runs the existing CLI as a subprocess, not a re-implementation
in the API service.**
`POST /backtests` shells out to `scripts/run_task_backtest.py` exactly as a human would
from the terminal, capturing stdout/stderr for the frontend's log tail and polling a job
status file/table for completion. Alternative considered: import and call the backtest
functions in-process inside the FastAPI service — rejected because it would require the
API process to hold engine state per job and handle concurrency/isolation the OS process
boundary already gives for free; the existing CLI is the single source of truth for how a
backtest runs and should stay that way.

**3. Parameter editing is a generated form over each strategy's params JSON schema, with a
raw-JSON fallback.**
Strategies already accept `--params-json`/`--params-file`. The UI introspects (or is given)
a lightweight schema per strategy (field name, type, default) to render a form; any
strategy without a declared schema still works via a raw JSON textarea. Alternative
considered: require every strategy to declare a full JSON Schema up front — rejected as too
large a prerequisite; the raw-JSON fallback keeps existing strategies usable on day one.

**4. Panel retirement is gated on explicit parity verification, not a fixed timeline.**
6d only proceeds once every requirement in the `research-dashboard` spec has an equivalent
in the new frontend, checked off explicitly. Alternative considered: retire Panel as soon
as the new frontend "looks done" — rejected because subjective readiness has already
produced an unpolished capital-mode comparison view once; an explicit spec-based checklist
prevents repeating that.

## Risks / Trade-offs

- [Risk] This is the largest, most open-ended change in the roadmap and risks scope creep
  across sessions/agents → Mitigation: the proposal and tasks explicitly split it into
  6b (frontend skeleton), 6c (trigger/params), 6d (parity + retirement); each is
  independently reviewable and mergeable.
- [Risk] A background subprocess model for backtest triggering could leave orphaned
  processes or unclear job state on API restart → Mitigation: persist job status (pid,
  start time, status) to a small local file/table so a restarted API can report "unknown/
  interrupted" rather than silently losing track.
- [Risk] Running two dashboards (Panel + new frontend) during the transition could confuse
  the user about which is authoritative → Mitigation: keep Panel as the default entry point
  until 6d's parity checklist is complete; document the new frontend's URL as
  "preview/in-progress" until then.

## Migration Plan

- 6b and 6c are additive: a new frontend and one new write endpoint, running alongside
  Panel with no changes to Panel itself.
- 6d is the only step that changes existing behavior: repointing
  `open_research_dashboard.cmd` and moving Panel code to `legacy/`. This step requires the
  explicit parity checklist to be complete and should be done as its own reviewable step,
  separate from 6b/6c implementation work.
- Rollback: `open_research_dashboard.cmd` can be repointed back to the Panel entry point at
  any time before Panel code is deleted (moved to `legacy/`, not deleted, to keep rollback
  cheap).
