"""Saved coverage projections; all endpoints remain acquisition-free."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from research_core.security_coverage import project_security_coverage
from research_core.security_coverage_store import CoverageStore


class SyntheticCoverageStore(CoverageStore):
    def load(self) -> dict:
        metadata: list[dict[str, Any]] = [
            {"market": "TWSE", "code": "DEMO", "name": "虛構示範公司", "security_category": "股票", "listed_date": "2012-01-02"},
            {"market": "TWSE", "code": "NEW23", "name": "新芽示範", "security_category": "股票", "listed_date": "2023-01-02"},
            {"market": "TPEx", "code": "REVENUE", "name": "月營收示範", "security_category": "股票"},
            {
                "market": "TWSE",
                "code": "PAST",
                "name": "歷史示範",
                "security_category": "股票",
                "listing_status": "delisted",
                "listing_evidence": "synthetic-only",
            },
            {"market": "TWSE", "code": "X123", "name": "新身分示範", "security_category": "股票", "listed_date": "2023-01-02"},
            {"market": "TWSE", "code": "FUND", "name": "基金示範", "is_etf": True},
        ]
        metadata += [{"market": "TWSE", "code": f"FX{i:03}", "name": f"虛構企業 {i:02}", "security_category": "股票"} for i in range(55)]
        sources = {
            "institutional": {
                "status": "ok",
                "first": "2019-01-02",
                "checked_at": "2026-10-24T00:00:00+00:00",
                "members": [
                    {"market": "TWSE", "code": "DEMO", "rows": 10, "first": "2019-01-02", "last": "2026-10-23"},
                    {"market": "TWSE", "code": "NEW23", "rows": 10, "first": "2023-01-02", "last": "2026-10-23"},
                    {"market": "TWSE", "code": "X123", "rows": 10, "first": "2019-01-02", "last": "2026-10-23"},
                ],
            },
            "monthly_revenue": {
                "status": "ok",
                "checked_at": "2026-10-24T00:00:00+00:00",
                "members": [
                    {"market": row["market"], "code": row["code"], "rows": 6, "first": "2025-01", "last": "2026-09" if row["code"] == "PAST" else "2026-10"}
                    for row in metadata
                ],
            },
        }
        doc = project_security_coverage(
            sources,
            metadata,
            built_at="2026-10-24T00:00:00+00:00",
            as_of="2026-10-24",
        )
        return {**doc, "synthetic": True}


def create_data_coverage_router(store: CoverageStore | None = None) -> APIRouter:
    router = APIRouter(prefix="/data-coverage")
    private_store = store or CoverageStore()
    demo_store = SyntheticCoverageStore()

    def selected() -> CoverageStore:
        mode = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
        if mode == "public-synthetic":
            return demo_store
        if mode == "local-private":
            return private_store
        raise HTTPException(503, "資料模式設定無法確認。")

    @router.get("/securities")
    def securities(
        market: str = "",
        kind: str = "",
        status: str = "",
        q: str = "",
        dataset: str = "",
        mark: str = "",
        page: int = Query(1, ge=1, le=100_000),
        size: int = Query(50, ge=1, le=200),
    ) -> dict:
        try:
            result = selected().list(market=market, kind=kind, status=status, q=q, dataset=dataset, mark=mark, page=page, size=size)
            result["synthetic"] = os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic") == "public-synthetic"
            return result
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/resolve")
    def resolve(code: str) -> dict:
        try:
            return selected().resolve(code)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/securities/{key}")
    def detail(key: str) -> dict:
        try:
            result = selected().detail(key)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if result is None:
            raise HTTPException(404, "找不到這個證券身分。")
        return result

    return router
