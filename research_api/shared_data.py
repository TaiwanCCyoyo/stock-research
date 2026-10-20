"""Private, read-only shared-data HTTP interface."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from research_core.shared_data_view import SharedDataView, ViewUnavailable, ViewWarming, catalog_summary, family_summary


def create_shared_data_router(view: SharedDataView | None = None) -> APIRouter:
    store = view or SharedDataView()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if os.environ.get("STOCK_RESEARCH_DATA_MODE") == "local-private":
            store.start()
        yield
        store.close()

    router = APIRouter(prefix="/shared-data/v1", lifespan=lifespan)

    def private() -> None:
        if os.environ.get("STOCK_RESEARCH_DATA_MODE") != "local-private":
            raise HTTPException(503, "需要本機私有資料；目前是合成示範模式。")

    def unavailable(exc: Exception) -> HTTPException:
        return HTTPException(503, str(exc), headers={"Retry-After": "1"} if isinstance(exc, ViewWarming) else None)

    @router.get("/families")
    def families() -> dict:
        private()
        catalog, error = catalog_summary()
        try:
            family = family_summary(store.status())
        except ViewUnavailable as exc:
            raise unavailable(exc) from exc
        return {"families": [family], "catalog": catalog, "catalogError": error}

    @router.get("/adjusted-daily-v1/symbols")
    def symbols() -> dict:
        private()
        try:
            return store.symbols()
        except (ViewUnavailable, ViewWarming) as exc:
            raise unavailable(exc) from exc

    @router.get("/adjusted-daily-v1/series/{code}")
    def series(
        code: str,
        basis: Literal["raw", "permanent_adjusted", "reference_factor_adjusted"] = "reference_factor_adjusted",
        first: date | None = Query(default=None, alias="from"),
        last: date | None = Query(default=None, alias="to"),
    ) -> JSONResponse:
        private()
        if len(code) > 16 or not code.isascii() or not code.isalnum():
            raise HTTPException(422, "股票代號格式不符。")
        if first and last and first > last:
            raise HTTPException(422, "起日不可晚於迄日。")
        try:
            return JSONResponse(store.series(code, basis, first.isoformat() if first else None, last.isoformat() if last else None))
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ViewUnavailable, ViewWarming) as exc:
            raise unavailable(exc) from exc

    return router
