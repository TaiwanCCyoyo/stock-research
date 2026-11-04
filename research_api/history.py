"""Versioned read-only HTTP access to a configured frozen opportunity snapshot."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from research_core.opportunity_history_bundle import BundleUnavailable
from research_core.opportunity_history_store import HistoryLoading, LazyHistoryStore
from research_core.opportunity_history_versions import HistorySelection, HistoryVersions

logger = logging.getLogger(__name__)


def history_router(provider: LazyHistoryStore | None = None, *, versions: HistoryVersions | None = None) -> APIRouter:
    registry = versions or HistoryVersions(provider)
    router = APIRouter(prefix="/opportunity-history/v1")

    def selection(
        request: Request,
        version_id: str | None = Query(default=None),
        manifest_sha256: str | None = Query(default=None),
    ) -> HistorySelection:
        if any(len(request.query_params.getlist(name)) > 1 for name in ("version_id", "manifest_sha256")):
            raise HTTPException(status_code=422, detail="Duplicate history version identity")
        try:
            return registry.select(version_id, manifest_sha256)
        except ValueError:
            raise HTTPException(status_code=422, detail="Require a valid version_id and manifest_sha256 pair") from None
        except BundleUnavailable:
            logger.exception("Pinned historical version unavailable")
            raise HTTPException(status_code=503, detail="The exact registered history version is unavailable; no fallback") from None

    def store(selected: HistorySelection):
        try:
            return selected.provider.get_ready()
        except HistoryLoading:
            raise HTTPException(
                status_code=503, detail={"state": "loading", "message": "正在核對歷史資料，其他頁面可以先使用。"}, headers={"Retry-After": "1"}
            ) from None
        except Exception:
            logger.exception("Frozen historical opportunity snapshot unavailable")
            raise HTTPException(status_code=503, detail="歷史目錄尚未載入或驗證未通過，請保留現有資料並檢查本機快照。") from None

    @router.get("/status")
    def status(selected: HistorySelection = Depends(selection)) -> dict:
        return selected.provider.status()

    @router.get("/metadata")
    def metadata(selected: HistorySelection = Depends(selection)) -> dict:
        return store(selected).metadata()

    @router.get("/frame")
    def frame(date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"), selected: HistorySelection = Depends(selection)) -> dict:
        try:
            return store(selected).frame(date)
        except ValueError:
            raise HTTPException(status_code=422, detail="請選擇目錄內有價格的日期。") from None

    @router.get("/directory")
    def directory(selected: HistorySelection = Depends(selection)) -> dict:
        return store(selected).directory()

    @router.get("/membership")
    def membership(
        code: str = Query(pattern=r"^(?:TW:)?[A-Za-z0-9-]{1,20}$"),
        date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
        threshold: float = Query(default=100, ge=0, le=10000, allow_inf_nan=False),
        mode: Literal["launched", "catalog"] = "launched",
        selected: HistorySelection = Depends(selection),
    ) -> dict:
        saved = store(selected)
        return {
            "schema": "opportunity-map-membership.v1",
            "code": code.removeprefix("TW:"),
            "date": date,
            "thresholdPct": threshold,
            "mode": mode,
            "metricUnit": "fraction",
            **({"bundleIdentity": saved.bundle_identity} if hasattr(saved, "bundle_identity") else {}),
            **selected.capture._ready(code.removeprefix("TW:"), date, saved.identity, threshold, mode),
        }

    @router.get("/options")
    def options(date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"), selected: HistorySelection = Depends(selection)) -> dict:
        try:
            return store(selected).options(date)
        except ValueError:
            raise HTTPException(status_code=422, detail="請選擇目錄內有價格的日期。") from None

    @router.get("/security/{code}")
    def detail(code: str, date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"), selected: HistorySelection = Depends(selection)) -> dict:
        saved = store(selected)
        if code not in saved.series:
            raise HTTPException(status_code=404, detail="這份目錄沒有這檔股票。")
        if date not in saved.dates:
            raise HTTPException(status_code=422, detail="請選擇目錄內有價格的日期。")
        try:
            return saved.detail(code, date)
        except (ValueError, OSError):
            logger.exception("Saved historical security detail failed validation")
            raise HTTPException(status_code=503, detail="這檔股票的已保存證據無法通過核對。") from None

    return router
