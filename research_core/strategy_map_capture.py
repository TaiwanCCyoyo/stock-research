"""Daily strategy membership projected from the very same historical map rows."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from research_core.opportunity_history_store import HistoryLoading, LazyHistoryStore
from research_core.opportunity_history_view import build_frame


def appears_on_map(row: dict[str, Any], date: str, threshold_pct: float = 100, mode: str = "launched") -> bool:
    """Mirror the public map contract, including its threshold tolerance."""
    if mode not in {"launched", "catalog"} or not math.isfinite(threshold_pct) or threshold_pct < 0:
        raise ValueError("Invalid map membership options")
    end = row.get("endConfirmedAt")
    if end is not None and date >= end:
        return False
    growth = row.get("growth") or {}
    metric = growth.get("sizingGainPct")
    if growth.get("basis") not in {"actual", "annualized"} or isinstance(metric, bool) or not isinstance(metric, (int, float)):
        return False
    if not math.isfinite(metric) or metric < threshold_pct - 1e-9:
        return False
    launch = row.get("launchCandidate")
    return mode == "catalog" or bool(launch and launch.get("date") and launch["date"] <= date)


class HistoryCapture:
    def __init__(self, provider: LazyHistoryStore) -> None:
        self.provider = provider

    def state(self) -> str:
        self.provider.start()
        return str(self.provider.status()["state"])

    def __call__(self, code: str, date: str) -> dict[str, Any] | None:
        try:
            store = self.provider.get_ready()
        except HistoryLoading:
            return None
        except RuntimeError:
            return {"onMap": None, "metric": None, "missingReason": "歷史目錄核對失敗，無法確認當日是否是飆股。"}
        return self._ready(code.removeprefix("TW:"), date, store.identity)

    @lru_cache(maxsize=100_000)
    def _ready(self, code: str, date: str, catalog_id: str, threshold_pct: float = 100, mode: str = "launched") -> dict[str, Any]:
        store = self.provider.get_ready()
        if date not in store.dates or code not in store.series:
            return {"onMap": None, "metric": None, "catalogId": catalog_id, "missingReason": "這份歷史目錄未涵蓋該股票或日期。"}
        # Select a security BEFORE projecting. All interval, gain, launch and
        # phase operations are still the unchanged frame implementation.
        catalog = store.catalog | {"securities": {code: store.securities[code]}}
        rows = build_frame(catalog, date)["rows"]
        if not rows:
            return {"onMap": False, "metric": None, "catalogId": catalog_id, "name": store.securities[code].get("name") or code}
        row = rows[0]
        metric = (row.get("growth") or {}).get("sizingGainPct")
        return {
            "onMap": appears_on_map(row, date, threshold_pct, mode),
            "metric": metric / 100 if isinstance(metric, (int, float)) and math.isfinite(metric) else None,
            "name": row["name"],
            "waveId": row["waveId"],
            "catalogId": catalog_id,
            "start": row["start"],
            "launchDate": row["launchCandidate"]["date"] if row.get("launchCandidate") else None,
        }
