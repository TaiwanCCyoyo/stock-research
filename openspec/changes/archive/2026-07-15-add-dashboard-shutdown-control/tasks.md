## 1. API endpoints

- [x] 1.1 Add `HeartbeatState` + `heartbeat` singleton and `HEARTBEAT_GRACE_SECONDS` to
      `research_api/main.py`.
- [x] 1.2 Extract `_require_csrf_header(...)` and reuse it for `POST /backtests`,
      `POST /heartbeat`, and `POST /shutdown`.
- [x] 1.3 Add `POST /heartbeat` (updates `heartbeat.last_seen`) and `POST /shutdown` (sets
      `app.state.server.should_exit = True` when a server is attached; no-op otherwise).

## 2. Production launcher

- [x] 2.1 Add `research_api/__main__.py`: builds `uvicorn.Config`/`uvicorn.Server`, attaches
      the server to `app.state.server`, and runs a monitor coroutine that stops the server once
      `heartbeat.last_seen` is older than `HEARTBEAT_GRACE_SECONDS`.
- [x] 2.2 Repoint `open_research_dashboard.cmd` to `uv run python -m research_api`. Leave
      `open_research_api.cmd` (Vite dev) on the plain `uvicorn` CLI.

## 3. Frontend

- [x] 3.1 Add `sendHeartbeat()` and `shutdownDashboard()` to `research_web/src/api/client.ts`
      (CSRF header, matching `createBacktest`'s pattern).
- [x] 3.2 Add `components/ShutdownControl.tsx`: always-visible button + confirm modal (custom,
      not `window.confirm`) with a close (`×`) affordance, wired to `shutdownDashboard()`.
- [x] 3.3 Add `components/ClosedState.tsx`: full-screen "Dashboard 已關閉" view.
- [x] 3.4 Wire heartbeat interval + shutdown control + closed state into `App.tsx`; the
      heartbeat effect runs independent of whether a task is loaded and stops once closed.
- [x] 3.5 Add matching dark-theme styles in `index.css` (`.shutdown-btn`, `.modal-overlay`,
      `.modal`, `.btn-danger`, `.closed-state`, etc.) reusing existing design tokens.

## 4. Tests

- [x] 4.1 `tests/test_research_api_security.py`: CSRF-header rejection (403) and success
      (200) for both new endpoints; `/shutdown` sets `should_exit` on an attached fake server and
      is a harmless no-op with none attached.

## 5. Validation

- [x] 5.1 Run `uv run python -m pytest tests/test_research_api.py tests/test_research_api_security.py -q`.
- [x] 5.2 Run `uv run ruff check research_api` and `uv run mypy research_api`.
- [x] 5.3 Run `cd research_web && npm run build && npm run lint`.
- [ ] 5.4 Manual E2E: click "關閉 Dashboard" → confirm → terminal's uvicorn exits, tab shows
      "已關閉". Not performed — a stale dashboard process (started before this change, without
      the new endpoints) was already bound to port 8503; stopping it required killing a process
      this session didn't start, which needed explicit user sign-off. Asked the user; they opted
      to skip manual E2E and rely on the automated checks (5.1-5.3) instead.
- [ ] 5.5 Manual E2E: close the browser tab instead → terminal's uvicorn exits on its own
      after the heartbeat grace period. Not performed, same reason as 5.4.
- [ ] 5.6 Manual E2E: refresh (F5) mid-session → server does NOT exit (heartbeat resumes
      within the grace period). Not performed, same reason as 5.4.
- [x] 5.7 No Docker-backed checks were skipped; all verification ran via the existing local
      `uv run`/`npm run` workflow.
