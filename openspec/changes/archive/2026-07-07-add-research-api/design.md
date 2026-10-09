## Context

`research_lab/dashboard_core.py` and `scripts/stock_research_query.py` already contain all
the logic needed to answer "what tasks exist," "what happened in this task," "what does
this symbol's price look like," and "what happened in this specific trade." Panel calls
these functions directly in-process. A React frontend cannot call Python functions
directly, so it needs an HTTP boundary — but that boundary should be a thin pass-through,
not a reimplementation.

## Goals / Non-Goals

**Goals:**

- Provide exactly the read operations `add-dashboard-v2`'s frontend needs, and no more.
- Reuse existing functions verbatim; the API layer only handles HTTP request/response
  shaping (path/query parsing, JSON serialization, error → HTTP status mapping).
- Keep the API stateless and safe to run alongside the existing Panel server.

**Non-Goals:**

- No new business logic, no new artifact computation.
- No write/mutation endpoints (that's `add-dashboard-v2` phase 6c, layered on top later).
- No auth — local-only tool, same trust boundary as `open_research_dashboard.cmd`.

## Decisions

**1. FastAPI, matching the tech stack already implied by the project's Python-first
tooling (uv, Ruff, pytest) and avoiding a second Python web framework's worth of new
conventions.**
Alternative considered: Flask — rejected in favor of FastAPI's built-in request/response
typing and automatic OpenAPI docs, which will help the React frontend team (a separate
change) know the exact contract without hand-written API docs.

**2. Endpoints are thin wrappers, not new query logic.**
`GET /tasks/{task_id}/prices` calls `DataLoader.load_symbols` (from
`update-price-loading-performance`) directly; `GET /tasks/{task_id}/trades/{trade_id}`
calls `inspect_task_trade` directly. The route function's only job is parsing the request
and serializing the return value. Alternative considered: build a separate "API service
layer" with its own data-access functions — rejected as needless duplication of
already-correct, already-tested logic.

**3. Runs as a separate process on its own port, not embedded in Panel.**
Panel's `bokeh`/Tornado server and FastAPI's ASGI server are different stacks; running them
as separate processes (like the existing static-build vs. server-mode split already does)
avoids a complex embedding effort for a transitional API that will eventually stand alone
once Panel is retired. Alternative considered: mount FastAPI as a sub-application inside
Panel's Tornado server — rejected as unnecessary integration complexity for a capability
that is explicitly transitional.

## Risks / Trade-offs

- [Risk] Running two servers (Panel + FastAPI) during the transition period could confuse
  which one is "the dashboard" → Mitigation: document clearly in `add-dashboard-v2`'s
  design which server is authoritative at each stage, and keep this API read-only so it
  cannot diverge from what Panel shows.
- [Risk] Reusing `dashboard_core.py` functions directly could couple the API to
  Panel-specific return shapes (e.g. `pn.Column` objects mixed with data) →
  Mitigation: call only the pure data-producing functions (already separated from
  Panel-specific rendering functions per this codebase's existing "pure function + thin
  panel builder" convention), not the Panel widget-construction functions.

## Migration Plan

- Purely additive: a new service that reads existing files; no existing file or function
  behavior changes.
- Rollback: stop running the FastAPI service; nothing else depends on it existing.
