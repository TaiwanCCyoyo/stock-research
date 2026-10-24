"""HTTP access to existing stored institutional and monthly revenue observations."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query

from research_core.data_series import DataSeriesView, Dataset, Market, SeriesRequestError, synthetic_series


def create_data_series_router(view: DataSeriesView | None = None) -> APIRouter:
    router = APIRouter(prefix="/data-series/v1")
    store = view or DataSeriesView()

    def series(dataset: Dataset, code: str, first: str | None, last: str | None, market: Market | None) -> dict:
        mode = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
        try:
            if mode == "public-synthetic":
                return synthetic_series(dataset, code, first, last, market)
            if mode != "local-private":
                raise HTTPException(503, "資料模式無法辨識，請檢查本機設定。")
            return store.series(dataset, code, first, last, market)
        except SeriesRequestError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/institutional/{code}")
    def institutional(
        code: str, first: str | None = Query(default=None, alias="from"), last: str | None = Query(default=None, alias="to"), market: Market | None = None
    ) -> dict:
        return series("institutional", code, first, last, market)

    @router.get("/monthly-revenue/{code}")
    def monthly_revenue(
        code: str, first: str | None = Query(default=None, alias="from"), last: str | None = Query(default=None, alias="to"), market: Market | None = None
    ) -> dict:
        return series("monthly-revenue", code, first, last, market)

    return router
