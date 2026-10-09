@echo off
rem Optional research viewer API on port 8503. Also serves the frontend if
rem research_web/dist exists; no backtest launching or background job manager.
setlocal
set "REPO_ROOT=%~dp0..\.."
cd /d "%REPO_ROOT%"
set UV_CACHE_DIR=.uv-cache
uv run --group viewer uvicorn research_api.main:app --host 127.0.0.1 --port 8503
