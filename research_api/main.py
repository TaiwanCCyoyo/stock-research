"""Read-only research API: thin HTTP views over existing task/query functions.

Endpoints only re-expose data produced by research_lab.dashboard_core and
scripts.stock_research_query; no new query logic lives here.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from research_api.history import history_router
from research_api.private_artifacts import create_private_artifact_router
from research_api.saved_research_studio import create_studio_router
from research_core.opportunity_history_store import LazyHistoryStore
from research_core.strategy_map_capture import HistoryCapture
from research_lab import dashboard_core
from scripts.stock_research_query import (
    DEFAULT_DATA_PATH,
    QueryError,
    inspect_task_trade,
    list_task_trades,
    resolve_price_data_root,
)
from StockProject.engine.data_loader import DataLoader

logger = logging.getLogger(__name__)

router = APIRouter()


def query_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Expected query failures (unknown task/trade, bad id) map to 404 with the message."""
    assert isinstance(exc, QueryError)
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Unexpected failures keep the same {"detail": ...} JSON shape without leaking internals."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/__research_service__")
def service_identity() -> dict[str, str]:
    """Identify this local checkout without loading the historical catalog."""
    return {
        "schema": "stock-research-service.v1",
        "service": "history-api",
        "projectRoot": str(Path(__file__).resolve().parents[1]),
    }


def _resolve_data_quality_report() -> Path | None:
    """Probe candidate paths for the submodule's data-quality report, mirroring
    DataLoader._resolve_corporate_action_db's layout-tolerant candidate search."""
    candidates = [
        DEFAULT_DATA_PATH / "data_quality_report.json",
        DEFAULT_DATA_PATH.parent / "data_quality_report.json",
        DEFAULT_DATA_PATH.parent.parent / "data_quality_report.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


@router.get("/data-quality")
def get_data_quality() -> dict:
    """Read-only view over stock-data-downloader's health-check report.

    Returns a neutral "not yet checked" response (never a 404/500) when the
    submodule has not produced a report yet, so the dashboard can render an
    empty state instead of an error.
    """
    report_path = _resolve_data_quality_report()
    if report_path is None:
        return {"available": False, "report": None}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {"available": True, "report": report}


def _require_csrf_header(x_requested_with: str | None) -> None:
    # Requiring a custom header forces a CORS preflight, which fails closed for
    # cross-origin pages (no CORSMiddleware is configured) — blocks drive-by POSTs.
    if x_requested_with is None:
        raise HTTPException(status_code=403, detail="missing X-Requested-With header")


# How long the launcher-owned monitor (research_api.__main__) waits after the last
# heartbeat before treating the browser tab as closed and stopping the server.
HEARTBEAT_GRACE_SECONDS = 20


@dataclass
class HeartbeatState:
    """Tracks the most recent frontend heartbeat; read by the launcher's monitor loop."""

    last_seen: float | None = None


heartbeat = HeartbeatState()


@router.post("/heartbeat")
def post_heartbeat(x_requested_with: str | None = Header(default=None)) -> dict[str, str]:
    """Frontend calls this periodically so a closed browser tab can be detected.

    research_api.__main__ owns the monitor loop that reads `heartbeat.last_seen`; under
    TestClient or the Vite-dev `open_research_api.cmd` process nothing reads it, so this
    is a harmless no-op there.
    """
    _require_csrf_header(x_requested_with)
    heartbeat.last_seen = time.monotonic()
    return {"status": "ok"}


@router.post("/shutdown")
def post_shutdown(request: Request, x_requested_with: str | None = Header(default=None)) -> dict[str, str]:
    """Signals the owning uvicorn.Server (set by research_api.__main__) to stop gracefully.

    No-op when the app is not running under that launcher (e.g. under TestClient or the
    Vite-dev `open_research_api.cmd` process) — still returns 200 so callers don't need to
    special-case the dev/test environment.
    """
    _require_csrf_header(x_requested_with)
    server = getattr(request.app.state, "server", None)
    if server is not None:
        server.should_exit = True
    return {"status": "shutting down"}


@router.get("/tasks")
def list_tasks() -> dict:
    rows = dashboard_core.discover_task_index()
    return {"tasks": [{"task": row["task"], "mtime": row["mtime"], "title": row["title"]} for row in rows]}


def _require_task(task_id: str) -> Path:
    root = dashboard_core.task_root(task_id)
    tasks_root = Path(dashboard_core.TASKS_ROOT).resolve()
    if not root.resolve().is_relative_to(tasks_root) or not (root / "summary.json").is_file():
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return root


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    _require_task(task_id)
    bundle = dashboard_core.load_task_bundle(task_id)
    bundle["root"] = str(bundle["root"])
    # Attach presentation-ready values from dashboard_core's pure, tested helpers
    # so the frontend never re-derives health verdicts or capital-mode judgments.
    bundle["rankings"] = dashboard_core.rankings_with_classification(bundle["rankings"])
    bundle["health"] = dashboard_core.strategy_health_rows(bundle["summary"])
    comparison = bundle.get("comparison")
    mode_summaries = bundle.get("mode_summaries") or {}
    bundle["mode_health"] = {mode: dashboard_core.strategy_health_rows(summary) for mode, summary in mode_summaries.items()}
    if comparison:
        bundle["judgments"] = {
            "comparative": dashboard_core.capital_mode_comparative_verdict(comparison, mode_summaries),
            "pools": {mode: dashboard_core.capital_mode_pool_verdict(mode, summary) for mode, summary in mode_summaries.items()},
        }
    else:
        bundle["judgments"] = None
    return bundle


@router.get("/tasks/{task_id}/prices")
def get_task_prices(task_id: str, codes: str = Query(description="Comma-separated stock codes")) -> dict:
    _require_task(task_id)
    summary = dashboard_core.load_task_summary(task_id)
    data_root = resolve_price_data_root(summary.get("data", {}).get("path"))
    requested = list(dict.fromkeys(code.strip() for code in codes.split(",") if code.strip()))

    loader = DataLoader(str(data_root))
    loader.load_symbols(requested)

    prices: dict[str, list[dict]] = {}
    corporate_actions: dict[str, list[dict]] = {}
    for code in requested:
        df = loader.get_stock_data(code)
        prices[code] = json.loads(cast(str, df.to_json(orient="records", date_format="iso"))) if not df.empty else []
        events = loader.get_corporate_actions(code)
        corporate_actions[code] = [
            {"event_type": str(row["event_type"]), "date": cast(datetime, row["Date"]).strftime("%Y-%m-%d")} for _, row in events.iterrows()
        ]
    return {"task": task_id, "codes": requested, "prices": prices, "corporate_actions": corporate_actions}


SummaryFile = Literal["summary.json", "summary_shared.json", "summary_per_stock.json", "summary_unconstrained.json"]


@router.get("/tasks/{task_id}/trades")
def get_task_trades(task_id: str, code: str | None = None, action: str | None = None, limit: int = 50, summary_file: SummaryFile = "summary.json") -> dict:
    return list_task_trades(task_id, code=code, action=action, limit=limit, summary_file=summary_file)


@router.get("/tasks/{task_id}/trades/{trade_id}")
def get_task_trade(task_id: str, trade_id: str, summary_file: SummaryFile = "summary.json") -> dict:
    return inspect_task_trade(task_id, trade_id=trade_id, summary_file=summary_file)


@router.get("/tasks/{task_id}/strategies")
def list_task_strategies(task_id: str) -> dict:
    root = _require_task(task_id)
    candidates = sorted((root / "candidates").glob("*.py")) if (root / "candidates").is_dir() else []
    return {"task": task_id, "strategies": [f"candidates/{path.name}" for path in candidates]}


REPO_ROOT = Path(__file__).resolve().parents[1]


def create_app() -> FastAPI:
    """Build the read-only artifact viewer while preserving the module-level app export."""
    application = FastAPI(
        title="Research API",
        description="Read-only view over backtest task artifacts.",
    )
    application.add_exception_handler(QueryError, query_error_handler)
    application.add_exception_handler(Exception, unexpected_error_handler)
    application.include_router(router)
    application.include_router(create_private_artifact_router())
    application.include_router(create_private_artifact_router(), prefix="/api")
    historical = LazyHistoryStore()
    application.include_router(history_router(historical), prefix="/history-api")
    application.include_router(create_studio_router(capture_provider=HistoryCapture(historical)), prefix="/history-api")

    # API routes take precedence over the optional built frontend.
    frontend_dist = REPO_ROOT / "research_web" / "dist"
    if frontend_dist.joinpath("index.html").is_file():
        application.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return application


app = create_app()
