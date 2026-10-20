@echo off
rem Research workbench (dashboard v2): FastAPI serves the built React frontend
rem and the read-only research API on port 8503.
rem
rem Runs via `python -m research_api` (not `uvicorn research_api.main:app`) so
rem the process owns the uvicorn.Server object: this enables the dashboard's
rem close button (POST /shutdown) and auto-shutdown after the browser tab
rem closes (missed heartbeats). See research_api/__main__.py.
rem The Node release manager checks source freshness and stages a replacement
rem frontend; a failed build preserves any previously usable research_web\dist.
setlocal
set "REPO_ROOT=%~dp0..\.."
cd /d "%REPO_ROOT%"
set UV_CACHE_DIR=.uv-cache
rem Check the source fingerprint and stage a fresh build before replacing dist.
rem Failed builds leave any previously usable dist in place.
node research_web\scripts\build-dashboard.mjs
if errorlevel 1 exit /b 1
rem Set RESEARCH_VIEWER_SKIP_BROWSER=1 for launcher smoke tests.
if /i not "%RESEARCH_VIEWER_SKIP_BROWSER%"=="1" start "" http://127.0.0.1:8503/
uv run --group viewer python -m research_api
