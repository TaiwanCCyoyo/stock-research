## Why

The Panel → React dashboard v2 rewrite (`add-dashboard-v2`) never carried forward a
requirement for closing the dashboard, so the new frontend shipped with no shutdown
affordance at all. In practice the dashboard is a single `uvicorn` process
(`research_api.main:app`, bound to `127.0.0.1:8503`) started in the foreground by
`open_research_dashboard.cmd`; closing the browser tab has no effect on it, and the only
way to stop it today is `Ctrl-C` in the terminal the user launched it from. The user asked
for the closing behavior to be restored: an explicit close control in the GUI, and — since
they don't require typing `Ctrl-C` — the server should also stop on its own once the
browser tab is gone.

## What Changes

- Add `POST /shutdown` and `POST /heartbeat` to the research API, both guarded by the
  existing `X-Requested-With` CSRF pattern used by `POST /backtests`.
- Add a `research_api.__main__` launcher (`uv run python -m research_api`) that owns the
  `uvicorn.Server` object so it can act on `/shutdown` and on a heartbeat timeout;
  `open_research_dashboard.cmd` is repointed to it. The Vite-dev launcher
  (`open_research_api.cmd`) keeps running plain `uvicorn research_api.main:app` unchanged,
  so a dev API process does not self-terminate when a dev browser tab closes.
- Add an always-visible "關閉 Dashboard" control to the React frontend with a confirm step,
  plus a full-screen "已關閉" state once the server has been asked to stop.
- Add a periodic heartbeat sent from the frontend; the launcher stops the server once
  heartbeats have been missing for longer than a grace period (browser tab closed).

## Capabilities

### Modified Capabilities

- `research-dashboard`: gains an explicit shutdown control and an automatic
  shutdown-after-tab-close behavior.
- `research-api`: gains `POST /shutdown` and `POST /heartbeat` endpoints.

## Non-Goals

- No remote or non-localhost shutdown — the server remains bound to `127.0.0.1` and the
  new endpoints rely on that, plus the existing no-CORS/CSRF-header pattern, for safety.
- No authentication/authorization layer — out of scope for a localhost-only research tool,
  consistent with the rest of `research-api`.
- No change to backtest subprocess lifecycle (`JobManager`) — a running backtest job is a
  child process tracked independently of the dashboard server's own lifetime.
- The Vite dev workflow (`open_research_api.cmd` + `npm run dev`) intentionally keeps the
  API process alive regardless of heartbeats; only the production launcher self-terminates.

## Impact

- `research_api/main.py`: two new endpoints, a small `HeartbeatState` singleton, and a
  shared `_require_csrf_header` helper (also adopted by the existing `POST /backtests`
  check to avoid tripling the same three lines).
- `research_api/__main__.py`: new file, the production entry point.
- `open_research_dashboard.cmd`: launches via `python -m research_api` instead of the bare
  `uvicorn` CLI. `open_research_api.cmd` is unchanged.
- `research_web/src/api/client.ts`, `App.tsx`, new `components/ShutdownControl.tsx` and
  `components/ClosedState.tsx`, `index.css`.
- `tests/test_research_api_security.py`: new CSRF and shutdown-signal tests.
- No Docker-backed verification required; this repo's existing local `uv run`/`npm run`
  workflow covers it.
