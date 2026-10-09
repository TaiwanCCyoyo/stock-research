"""Thin read-only HTTP routes for the additive saved strategy evidence package."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from research_core.saved_research_studio import SavedResearchStudio, StudioError, StudioNotFound, valid_day

logger = logging.getLogger(__name__)
DEFAULT_PACKAGE = None
DEFAULT_HISTORY_PRESENTATION = Path(__file__).resolve().parents[1] / "research_web/public/data/research-presentation.v1.json"
DEFAULT_HISTORY_TITLE_ORIGINS = Path(__file__).resolve().parents[1] / "research_web/public/data/research-history-title-origins.v1.json"


def create_studio_router(
    package_path: Path | None = DEFAULT_PACKAGE,
    capture_provider: Callable[[str, str], dict[str, Any] | None] | None = None,
    history_presentation_path: Path | None = DEFAULT_HISTORY_PRESENTATION,
    history_title_origins_path: Path | None = None,
) -> APIRouter:
    configuration_error: OSError | StudioError | None = None
    if package_path is None:
        mode = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
        if mode == "local-private":
            configured = os.environ.get("STOCK_SAVED_STUDIO_PACKAGE", "")
            if not configured:
                configuration_error = FileNotFoundError("private saved studio package is not configured")
            else:
                package_path = Path(configured)
                if not package_path.is_absolute():
                    configuration_error = StudioError("private saved studio package path must be absolute")
        elif mode != "public-synthetic":
            configuration_error = StudioError("unsupported research data mode")
        if mode == "public-synthetic":
            # The public demo must never enrich fictional records with private data.
            capture_provider = None
            history_presentation_path = None
            history_title_origins_path = None
        elif history_title_origins_path is None:
            history_title_origins_path = DEFAULT_HISTORY_TITLE_ORIGINS
    service = SavedResearchStudio(package_path, capture_provider, history_presentation_path, history_title_origins_path)

    def verify_request_mode(x_research_data_mode: str | None = Header(None)) -> None:
        actual_mode = "public-synthetic" if package_path is None else "local-private"
        if x_research_data_mode is not None and x_research_data_mode != actual_mode:
            raise HTTPException(503, "data mode mismatch; evidence unavailable", headers={"X-Research-Evidence-Error": "unavailable"})

    router = APIRouter(prefix="/saved-research-studio/v1", tags=["saved strategy evidence"], dependencies=[Depends(verify_request_mode)])

    def invoke(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            if configuration_error is not None:
                raise configuration_error
            return {**action(), "dataMode": "public-synthetic" if package_path is None else "local-private", "synthetic": package_path is None}
        except OSError as error:
            logger.warning("saved strategy package unavailable: %s", error)
            raise HTTPException(503, "策略證據包尚未準備完成。", headers={"X-Research-Evidence-Error": "unavailable"}) from error
        except StudioNotFound as error:
            raise HTTPException(404, str(error)) from error
        except StudioError as error:
            logger.error("saved strategy package failed integrity validation: %s", error)
            raise HTTPException(503, "策略證據包未通過完整性檢查，暫時無法讀取。", headers={"X-Research-Evidence-Error": "integrity"}) from error

    @router.get("/runs")
    def runs() -> dict[str, Any]:
        return invoke(service.index)

    @router.get("/research-history")
    def history() -> dict[str, Any]:
        return invoke(service.history)

    @router.get("/run")
    @router.get("/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        return invoke(lambda: service.run(run_id))

    @router.get("/trade")
    @router.get("/runs/{run_id}/trades/{trade_id}")
    def trade(run_id: str, trade_id: str) -> dict[str, Any]:
        return invoke(lambda: service.trade(run_id, trade_id))

    @router.get("/account")
    @router.get("/runs/{run_id}/account")
    def account(run_id: str, date: str = Query(...)) -> dict[str, Any]:
        try:
            valid_day(date)
        except StudioError as error:
            raise HTTPException(422, "請選擇有效日期。") from error
        return invoke(lambda: service.account(run_id, date))

    @router.get("/exposure")
    @router.get("/runs/{run_id}/exposure")
    def exposure(run_id: str) -> dict[str, Any]:
        return invoke(lambda: service.exposure(run_id))

    return router


studio_router = create_studio_router()
