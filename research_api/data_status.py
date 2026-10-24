"""Metadata-only data overview HTTP interface."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from research_core.data_status import DataStatusView, synthetic_data_status


def create_data_status_router(view: DataStatusView | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/data-status")
    def status() -> dict:
        mode = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
        if mode == "public-synthetic":
            return synthetic_data_status()
        if mode != "local-private":
            raise HTTPException(503, "資料模式設定無法確認，請檢查本機服務設定。")
        return (view or DataStatusView()).status()

    return router
