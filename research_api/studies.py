"""Read-only study cards, isolated from public fictional demonstration data."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from research_core.report_reading import MAX_SOURCES, ReportReadings
from research_core.study_cards import REPO_ROOT, StudyCards, synthetic_study_cards


def create_studies_router(*, tasks_root: Path | None = None, package_path: Path | None = None, shared_root: Path | None = None) -> APIRouter:
    mode = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    configured = os.environ.get("STOCK_SAVED_STUDIO_PACKAGE")
    # No reader is constructed in public mode, even if private paths were injected.
    service = None
    readings = None
    if mode == "local-private":
        service = StudyCards(
            tasks_root or REPO_ROOT / "tasks", package_path=package_path or (Path(configured) if configured else None), shared_root=shared_root
        )
        readings = ReportReadings(tasks_root or REPO_ROOT / "tasks")
    router = APIRouter(tags=["study cards"])

    def check_mode(header: str | None) -> None:
        if mode not in {"local-private", "public-synthetic"} or (header is not None and header != mode):
            raise HTTPException(503, "資料模式設定無法確認，請檢查本機服務設定。", headers={"X-Research-Evidence-Error": "unavailable"})

    @router.get("/studies")
    def studies(include_tooling: bool = False, x_research_data_mode: str | None = Header(None)) -> dict[str, Any]:
        check_mode(x_research_data_mode)
        if mode == "public-synthetic":
            return {**synthetic_study_cards(include_tooling=include_tooling), "readings": [], "reading_warnings": []}
        assert service is not None
        assert readings is not None
        return {**service.read(include_tooling=include_tooling), **readings.read()}

    @router.get("/studies/{task_id}/reading")
    def reading_document(task_id: str, x_research_data_mode: str | None = Header(None)) -> dict[str, Any]:
        check_mode(x_research_data_mode)
        if readings is None:
            raise HTTPException(404, "此模式不提供本機研究原文。")
        try:
            return readings.document(task_id)
        except (OSError, ValueError, RecursionError):
            raise HTTPException(404, "這份報告目前無法安全讀取，請返回研究列表查看來源狀態。") from None

    @router.get("/studies/{task_id}/source")
    def reading_source(task_id: str, index: int = Query(ge=0, lt=MAX_SOURCES), x_research_data_mode: str | None = Header(None)) -> dict[str, str]:
        check_mode(x_research_data_mode)
        if readings is None:
            raise HTTPException(404, "此模式不提供本機研究原文。")
        try:
            return readings.source(task_id, index)
        except (OSError, ValueError, RecursionError):
            raise HTTPException(404, "這份引用來源目前無法安全讀取。") from None

    return router
