"""Read-only dashboard routes for revision-pinned direction discussion drafts."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response

from research_core.direction_discussions import (
    DirectionDiscussionNotFound,
    DirectionDiscussionReader,
    DirectionDiscussionUnavailable,
)

LOGGER = logging.getLogger(__name__)
MODE_HEADER = "X-Research-Evidence-Error"


def create_direction_discussions_router(*, repo_root: Path | None = None) -> APIRouter:
    """Create the draft-only API while keeping the public demo isolated from local files."""
    mode = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    # Public mode must not construct a private reader or even resolve its repository path.
    reader = DirectionDiscussionReader(repo_root) if mode == "local-private" else None
    router = APIRouter(tags=["direction discussions"])

    def verify_mode(request_mode: str | None) -> None:
        if mode not in {"local-private", "public-synthetic"} or (request_mode is not None and request_mode != mode):
            raise HTTPException(
                status_code=503,
                detail="方向草稿資料模式無法確認。",
                headers={MODE_HEADER: "unavailable", "Cache-Control": "no-store"},
            )

    @router.get("/direction-drafts")
    def list_direction_drafts(
        response: Response,
        x_research_data_mode: str | None = Header(None),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        verify_mode(x_research_data_mode)
        if mode == "public-synthetic":
            return {"schema": "direction-drafts.v1", "mode": mode, "items": []}
        if reader is None:
            raise HTTPException(
                status_code=503,
                detail="方向草稿資料目前無法讀取。",
                headers={MODE_HEADER: "unavailable", "Cache-Control": "no-store"},
            )
        try:
            items = reader.list_items()
        except DirectionDiscussionUnavailable as error:
            LOGGER.warning("direction draft discovery unavailable: %s", type(error).__name__)
            raise HTTPException(
                status_code=503,
                detail="方向草稿資料目前無法讀取。",
                headers={MODE_HEADER: "unavailable", "Cache-Control": "no-store"},
            ) from None
        return {"schema": "direction-drafts.v1", "mode": mode, "items": items}

    @router.get("/direction-drafts/{task_id}")
    def get_direction_draft(
        task_id: str,
        response: Response,
        x_research_data_mode: str | None = Header(None),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        verify_mode(x_research_data_mode)
        if mode == "public-synthetic":
            raise HTTPException(status_code=404, detail="方向草稿不存在。", headers={"Cache-Control": "no-store"})
        if reader is None:
            raise HTTPException(
                status_code=503,
                detail="方向草稿資料目前無法讀取。",
                headers={MODE_HEADER: "unavailable", "Cache-Control": "no-store"},
            )
        try:
            detail = reader.detail(task_id)
        except DirectionDiscussionNotFound:
            raise HTTPException(status_code=404, detail="方向草稿不存在。", headers={"Cache-Control": "no-store"}) from None
        except DirectionDiscussionUnavailable as error:
            LOGGER.warning("direction draft unavailable for task %s: %s", task_id, type(error).__name__)
            raise HTTPException(
                status_code=503,
                detail="方向草稿資料目前無法讀取。",
                headers={MODE_HEADER: "unavailable", "Cache-Control": "no-store"},
            ) from None
        return {**detail, "mode": mode}

    return router
