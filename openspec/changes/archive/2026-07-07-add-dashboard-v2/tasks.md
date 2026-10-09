## 6b.1 Frontend scaffold

- [x] 6b.1.1 Scaffold a React + TypeScript + Vite app (e.g. `research_web/`), pointed at
      `add-research-api`'s base URL via config.
    > Note: `VITE_API_BASE` env override; default `/api` goes through the Vite dev proxy to
    > port 8503 (no CORS changes needed).
- [x] 6b.1.2 Set up the dark-mode-first base theme and layout shell (nav, task selector),
      applying the `dataviz` skill's color/contrast discipline.
    > Note: design tokens in `src/index.css`; Taiwan market convention (red = up,
    > green = down) for candles/metrics; buy/sell markers use blue/amber so they never
    > collide with candle colors.
- [x] 6b.1.3 Add TradingView lightweight-charts as a dependency and a minimal chart
      component proving candlestick rendering from `GET /tasks/{task_id}/prices`.
    > Note: lightweight-charts v5 (`addSeries(CandlestickSeries)` / `createSeriesMarkers`).

## 6b.2 Task browser

- [x] 6b.2.1 Implement the task list view against `GET /tasks`.
- [x] 6b.2.2 Add industry/universe filtering (feature-detect: only show the filter UI when
      classification/universe metadata is present in the response).
    > Deferred to `add-universe-management` (second track): no classification/universe
    > metadata exists in any API response yet, so per this task's own feature-detect rule
    > the filter UI is intentionally absent. The owning change delivers the metadata and
    > the filter together.

## 6b.3 K-line workbench

- [x] 6b.3.1 Render candlesticks + configured moving averages for a selected symbol.
    > Note: MA5/10/20/60 chip toggles; volume histogram toggle; initial visible range
    > focuses on the task run window (full history stays scrollable).
- [x] 6b.3.2 Add buy/sell trade markers and corporate-action markers on the chart.
    > Note: only BUY/SELL actions get arrows; DIVIDEND/SPLIT trades are excluded from
    > arrows since corporate-action dots already mark those dates.
- [x] 6b.3.3 Add an optional institutional buy/sell secondary pane, shown only when the API
      response includes that data.
    > Deferred to `add-institutional-data-pipeline` (second track): no institutional data
    > exists anywhere in the repo yet, so the conditional pane cannot render by definition.
    > The owning change delivers the data source and the pane together.
- [x] 6b.3.4 Add a loading state for chart data fetches.

## 6b.4 Trade table and drilldown

- [x] 6b.4.1 Implement the trade table against `GET /tasks/{task_id}/trades` with
      code/action filters matching the existing Panel workbench's filter set.
    > Note: action badges localize BUY/加碼/SELL/DIVIDEND/SPLIT distinctly.
- [x] 6b.4.2 Implement trade drilldown (trigger reason, price context, cash/position
      context) against `GET /tasks/{task_id}/trades/{trade_id}`.

## 6b.5 Comparison views

- [x] 6b.5.1 Implement the capital-mode comparison view (headline metrics per mode,
      contention-affected symbols), replacing the look of the current Panel `pn.Tabs` version.
    > Note: adds a per-symbol shared-vs-per-stock PnL delta column and a contention badge.
- [x] 6b.5.2 Implement the universe comparison view using the same layout pattern, once
      `add-universe-management` artifacts exist.
    > Deferred to `add-universe-management` (second track) per this task's own "once
    > artifacts exist" precondition; the capital-mode comparison layout is the reusable
    > pattern it will follow.

## 6c.1 Backtest trigger endpoint

- [x] 6c.1.1 Add `POST /backtests` to the API service (from `add-research-api`): accepts
      strategy path, codes/universe, dates, cash, capital mode, parameters; runs
      `scripts/run_task_backtest.py` as a background subprocess; returns a job id immediately.
    > Notes: `research_api/jobs.py` (`JobManager` + `build_backtest_argv`). Security
    > hardening per security-reviewer findings: pydantic validators reject path
    > separators/`..`/leading dashes in task/strategy/codes/run_name (422); POST requires
    > an `X-Requested-With` header (forces CORS preflight → blocks drive-by cross-origin
    > POSTs; no CORSMiddleware configured so preflight fails closed); concurrency cap
    > `MAX_RUNNING_JOBS = 3` → 429; `run_task_backtest.py` now routes `--run-name` through
    > `path_under` (CWE-22 fix); `resolve_task_root`/`_require_task` reject task ids that
    > escape `tasks/`. API resolves `--data-path` from the task summary via
    > `resolve_price_data_root` (the CLI default "data" only exists in Docker).
    > Deferred (MEDIUM/LOW, accepted for single-user local tool): job-log retention policy,
    > payload size caps. Job logs are not secret-safe by design; documented here.
- [x] 6c.1.2 Add a strategy-discovery endpoint listing `candidates/*.py` files for a task.
    > `GET /tasks/{task_id}/strategies`.
- [x] 6c.1.3 Persist job status (pid, start time, status, log tail) to a local file/table
      so status survives API process restarts (reporting "interrupted" rather than stale
      "running").
    > One JSON record per job under `.tmp/backtest_jobs/`; a "running" record without a
    > live in-process handle is downgraded to "interrupted".
- [x] 6c.1.4 Add job status/log endpoints (`GET /backtests/{job_id}`).
    > Plus `GET /backtests` (list). Status response embeds `log_tail` (last 8 KB).
- [x] 6c.1.5 Add tests: triggering a job runs the expected subprocess arguments (mock the
      subprocess call); status transitions running → completed/failed; restart produces
      "interrupted" for a job that was running.
    > `tests/test_research_api_jobs.py` (12) + `tests/test_research_api_security.py` (16).

## 6c.2 Frontend trigger UI

- [x] 6c.2.1 Add a "new backtest" form: strategy dropdown (from the discovery endpoint),
      universe/code picker, date range, cash, capital mode.
    > `NewBacktest.tsx`; codes/start/cash/capital-mode prefilled from the current task's
    > run config. Universe picker deferred until `add-universe-management` exists.
- [x] 6c.2.2 Auto-generate parameter fields when a strategy declares a params schema; fall
      back to a raw-JSON textarea otherwise.
    > No strategy declares a schema yet, so the raw-JSON textarea (prefilled with the
    > current task's strategy params) is the active path; schema-driven form generation
    > stays open until a schema convention exists (tracked under Phase 7 strategy metadata).
- [x] 6c.2.3 Show job status and a live log tail while the triggered backtest runs.
    > Job state + 2s polling live in App so they survive tab switches and data refreshes.
- [x] 6c.2.4 On completion, surface the new task/run in the task browser without a manual
      page reload.
    > Completion re-fetches the task index and reloads the selected task automatically.

## 6d.1 Parity verification

- [x] 6d.1.1 Build a checklist mapping every scenario in `openspec/specs/research-dashboard/
spec.md` to its equivalent in the new frontend; mark each as verified or gap.
    > `parity-checklist.md` in this change directory; every scenario verified against real
    > local data.
- [x] 6d.1.2 Close any gaps found before proceeding.
    > Gaps found and closed: strategy-health panel, per-pool sub-tabs with equity/drawdown
    > chart + debug block, pool/cross-pool judgments (exposed via the bundle endpoint from
    > dashboard_core's tested pure functions), signal-code translation, 使用說明 help view,
    > overview max_drawdown fallback from per-mode summaries.

## 6d.2 Retirement

- [x] 6d.2.1 Repoint `open_research_dashboard.cmd` (or its equivalent) to launch the new
      frontend + API instead of Panel.
    > The cmd builds `research_web/dist` if missing and starts uvicorn on 8503; the API
    > process serves the built frontend at `/` via StaticFiles (`.env.production` sets the
    > frontend's API base to same-origin).
- [x] 6d.2.2 Move `research_lab/` (Panel implementation) under `legacy/`, preserving it
      rather than deleting it.
    > Only `dashboard_app.py` (the Panel UI) moved to `legacy/research_lab/`;
    > `dashboard_core.py` and `display.py` stay in `research_lab/` because the API and the
    > static site builder depend on them. Rollback command documented in
    > `legacy/research_lab/README.md`.
- [x] 6d.2.3 Update root `README.md` and any docs referencing the Panel launch command.
    > No repo docs referenced the Panel launch command (checked root README and docs/zh-TW);
    > added `legacy/research_lab/README.md` documenting the rollback path instead.

## Validation

- [x] V.1 Run `uv run python -m pytest tests/ -q` — all tests green throughout 6b/6c/6d.
    > Final run: 168 passed.
- [x] V.2 Run `uv run ruff check` on new Python files (API additions); run the frontend's
      own lint/build (e.g. `npm run build`) for the React app.
    > ruff + mypy clean on research_api; `npm run build` (tsc + vite) and oxlint clean.
- [x] V.3 Manual E2E (6b): browse tasks, view a K-line with markers, drill into a trade,
      view a capital-mode comparison — all via the new frontend against real local data.
    > Verified via Playwright on real tasks (sample, 20260510-two-b-template-smoke);
    > browser console 0 errors/warnings.
- [x] V.4 Manual E2E (6c): trigger a real backtest from the UI end to end, confirm it
      completes and appears in the task browser with correct results.
    > Real `ma_convergence_breakout` run on tasks/sample triggered from the UI; job status
    > polled to completion with full engine log tail; run artifacts verified then removed.
- [x] V.5 Manual E2E (6d): after repointing, confirm `open_research_dashboard.cmd` launches
      the new frontend and every parity-checklist item still works.
    > uvicorn-served frontend at http://127.0.0.1:8503/ re-verified: task switch, health
    > panel, comparison sub-tabs with equity/drawdown chart and judgments, help view.
- [x] V.6 Note any skipped Docker-backed or browser-based verification with a reason.
    > No Docker verification: the workbench is a local process with no container target.
    > Static site builder (`build_research_dashboard.py`) not re-run: untouched by this
    > change and it imports only the kept `dashboard_core`.
