"""Read-only study cards, isolated from public fictional demonstration data."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from research_core.study_cards import REPO_ROOT, StudyCards, synthetic_study_cards


def create_studies_router(*, tasks_root: Path | None = None, package_path: Path | None = None, shared_root: Path | None = None) -> APIRouter:
    mode = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    configured = os.environ.get("STOCK_SAVED_STUDIO_PACKAGE")
    # No reader is constructed in public mode, even if private paths were injected.
    service = None
    if mode == "local-private":
        service = StudyCards(
            tasks_root or REPO_ROOT / "tasks", package_path=package_path or (Path(configured) if configured else None), shared_root=shared_root
        )
    router = APIRouter(tags=["study cards"])

    @router.get("/studies")
    def studies(include_tooling: bool = False, x_research_data_mode: str | None = Header(None)) -> dict[str, Any]:
        if mode not in {"local-private", "public-synthetic"} or (x_research_data_mode is not None and x_research_data_mode != mode):
            raise HTTPException(503, "資料模式設定無法確認，請檢查本機服務設定。", headers={"X-Research-Evidence-Error": "unavailable"})
        if mode == "public-synthetic":
            return synthetic_study_cards(include_tooling=include_tooling)
        assert service is not None
        return service.read(include_tooling=include_tooling)

    return router
