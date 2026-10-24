"""Small-file-only discovery for the local data overview; never scan data tables."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from research_core import live_producer
from research_core.artifact_store import file_digest, read_json, relative_name, safe_path
from research_core.producer_data import producer_data_root
from research_core.shared_data import shared_data_root
from research_core.shared_data_view import catalog_summary, discovery_labels

LOGGER = logging.getLogger(__name__)
SCHEMA = "research-data-status.v1"
MAX_METADATA_BYTES = 2_000_000
PRODUCER_NAMES = {
    "official_daily": "官方每日股價",
    "price_daily": "整合每日股價",
    "institutional": "三大法人買賣",
    "monthly_revenue": "每月營收",
    "corporate_actions": "除權息與減資",
    "symbol_meta": "股票名稱與產業",
}
READ_ERRORS = (OSError, ValueError, KeyError, TypeError, RuntimeError)


def _count(value: Any) -> int | None:
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError("nonnegative integer or null required")
    return value


def _period_value(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value):
        raise ValueError("ISO date or month required")
    datetime.strptime(value, "%Y-%m" if len(value) == 7 else "%Y-%m-%d")
    return value


def _period(first: Any, last: Any) -> dict[str, str | None]:
    first, last = _period_value(first), _period_value(last)
    if first is not None and last is not None and (len(first) != len(last) or first > last):
        raise ValueError("inconsistent period")
    return {"from": first, "to": last}


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("ISO timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed.astimezone(timezone.utc)


def _old(value: datetime | None, now: datetime, days: int = 7) -> bool:
    return value is None or value > now + timedelta(minutes=5) or now - value > timedelta(days=days)


def _coverage_old(period: dict[str, str | None], now: datetime) -> bool:
    first, last = period["from"], period["to"]
    if first is None or last is None:
        return True
    if len(last) == 7:
        month = datetime.strptime(last, "%Y-%m").replace(tzinfo=timezone.utc)
        next_month = month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)
        return _old(next_month - timedelta(days=1), now, 45)
    return _old(datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=timezone.utc), now)


def _name(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or re.search(r"[/\\:]|[a-fA-F0-9]{32,}", value):
        return fallback
    value = re.sub(r"第[一二三四五六七八九十百0-9]+版|初版|[vV]\d+|版本|快照|世代", "", value).strip()
    return value if value and re.search(r"[\u3400-\u9fff]", value) else fallback


def _empty(data_id: str, source: str, name: str, status: str = "missing") -> dict[str, Any]:
    return {
        "id": data_id,
        "source": source,
        "name": name,
        "data_period": {"from": None, "to": None},
        "last_updated": None,
        "symbols": None,
        "rows": None,
        "status": status,
    }


class DataStatusView:
    """Project bounded status JSON and catalog metadata into a display-safe contract."""

    def __init__(
        self,
        *,
        producer_root: Callable[[], Path] | None = None,
        shared_root: Callable[[], Path] | None = None,
        catalog: Callable[[], tuple[dict[str, Any] | None, str | None]] | None = None,
        labels: Callable[[], dict[str, dict[str, str]]] | None = None,
        idle: Callable[[], None] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self._producer_root = producer_root or producer_data_root
        self._shared_root = shared_root or shared_data_root
        self._catalog = catalog or catalog_summary
        self._labels = labels or discovery_labels
        self._idle = idle or (lambda: live_producer.assert_producer_idle(task_timeout=5))
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _producer(self, now: datetime) -> tuple[list[dict[str, Any]], list[str], bool]:
        empty = [_empty(key, "producer", name) for key, name in PRODUCER_NAMES.items()]
        try:
            self._idle()
            path = safe_path(self._producer_root() / "data-status.json")
            document = live_producer.read_stable(path, lambda source: read_json(source, max_bytes=MAX_METADATA_BYTES))
            self._idle()
            if document.get("schema") != "producer-data-status.v1":
                raise ValueError("unsupported producer status")
            generated = _timestamp(document["generated_at"])
            values = document["datasets"]
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError("bounded dataset list required")
            indexed = {}
            for value in values:
                if not isinstance(value, dict) or not isinstance(value.get("id"), str) or value["id"] in indexed:
                    raise ValueError("unique dataset identifiers required")
                indexed[value["id"]] = value
            rows, warnings = [], []
            for key, name in PRODUCER_NAMES.items():
                try:
                    item = indexed[key]
                    state = item["status"]
                    if state not in {"ok", "stale", "missing"}:
                        raise ValueError("unsupported dataset state")
                    period = _period(item["data_period"]["from"], item["data_period"]["to"])
                    expected_length = 7 if key == "monthly_revenue" else 10
                    if any(value is not None and len(value) != expected_length for value in period.values()):
                        raise ValueError("dataset period granularity mismatch")
                    observed = _timestamp(item["last_updated"])
                    row_count, symbols = _count(item["rows"]), _count(item["symbols"])
                    if state == "ok" and (
                        row_count is None or symbols is None or row_count == 0 or symbols == 0 or period["from"] is None or period["to"] is None
                    ):
                        raise ValueError("healthy datasets require measured coverage")
                    freshness_days = {"monthly_revenue": 45, "symbol_meta": 14}.get(key, 7)
                    if state == "ok" and (_old(generated, now) or _old(observed, now, freshness_days)):
                        state = "stale"
                    rows.append({
                        **_empty(key, "producer", name),
                        "data_period": period,
                        "last_updated": observed.isoformat() if observed else None,
                        "symbols": symbols,
                        "rows": row_count,
                        "status": state,
                    })
                except READ_ERRORS:
                    rows.append(_empty(key, "producer", name))
                    warnings.append(f"{name}的狀態尚無法確認。")
            return rows, warnings, False
        except live_producer.ProducerBusyError:
            return [dict(item, status="updating") for item in empty], ["來源資料正在更新，稍後即可重新讀取。"], True
        except READ_ERRORS as exc:
            LOGGER.info("Producer data status unavailable: %s", exc)
            return empty, ["來源資料的狀態檔尚未建立或無法驗證。"], False

    def _derived(self, now: datetime, labels: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
        rows, warnings = [], []
        try:
            directory = safe_path(self._shared_root() / "derived")
            if not directory.is_dir():
                return [], ["共用衍生資料尚未建立。"]
            families = sorted(directory.iterdir(), key=lambda item: item.name)
            if len(families) > 100:
                raise ValueError("too many derived families")
            for family in families:
                if family.name.startswith("."):
                    continue
                name = _name(labels.get(family.name, {}).get("display_title"), "共用衍生資料")
                empty = _empty(f"derived:{family.name}", "derived", name)
                try:
                    safe_path(family)
                    if not family.is_dir():
                        continue
                    pointer = read_json(family / "current.json", max_bytes=MAX_METADATA_BYTES)
                    generation = relative_name(pointer["generation"])
                    if "/" in generation:
                        raise ValueError("single generation name required")
                    path = safe_path(family / "generations" / generation / "status.json")
                    if path.stat().st_size > MAX_METADATA_BYTES:
                        raise ValueError("status exceeds metadata limit")
                    if file_digest(path) != pointer["status_sha256"]:
                        raise ValueError("status pin mismatch")
                    status = read_json(path, max_bytes=MAX_METADATA_BYTES)
                    if file_digest(path) != pointer["status_sha256"] or status.get("family") != family.name or status.get("generation") != generation:
                        raise ValueError("status identity mismatch")
                    calendar = status.get("calendar", {})
                    bases = status.get("bases", {})
                    if not isinstance(calendar, dict) or not isinstance(bases, dict) or not isinstance(bases.get("raw", {}), dict):
                        raise ValueError("invalid derived counts or calendar")
                    observed = _timestamp(status.get("built_at_utc"))
                    period = _period(calendar.get("first"), calendar.get("last", status.get("asof")))
                    rows.append({
                        **empty,
                        "data_period": period,
                        "last_updated": observed.isoformat() if observed else None,
                        "symbols": _count(status.get("codes")),
                        "rows": _count(bases.get("raw", {}).get("rows")),
                        "status": "stale" if _old(observed, now) or _coverage_old(period, now) else "ok",
                    })
                except READ_ERRORS as exc:
                    LOGGER.info("Derived status unavailable family=%s: %s", family.name, exc)
                    rows.append(empty)
                    warnings.append(f"{name}的狀態尚無法確認。")
            return rows, warnings
        except READ_ERRORS as exc:
            LOGGER.info("Shared data status unavailable: %s", exc)
            return [], ["共用衍生資料的目錄無法讀取。"]

    def _catalog_rows(self, labels: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
        rows, warnings = [], []
        try:
            catalog, error = self._catalog()
            if error or catalog is None:
                return [], ["研究資料包的目錄無法讀取或驗證。"]
            entries = catalog["entries"]
            if not isinstance(entries, list) or len(entries) > 1000:
                raise ValueError("bounded catalog entries required")
            for entry in entries:
                data_id = entry["data_id"]
                name = _name(labels.get(data_id, {}).get("display_title"), "研究資料包")
                empty = _empty(f"catalog:{data_id}:{entry['version_id']}", "catalog", name)
                try:
                    period = entry["coverage"]["raw_input_period"]
                    metadata = entry.get("viewer_metadata") or {}
                    state = "missing" if entry.get("metadata_error") else "ok" if entry["status"] == "complete" else "stale"
                    rows.append({
                        **empty,
                        "data_period": _period(period["start"], period["end"]),
                        "symbols": _count(metadata.get("security_count")),
                        "status": state,
                    })
                    if state != "ok":
                        warnings.append(f"{name}的內容未齊、僅供歷史查閱，或尚無法驗證；請依資料契約判讀。")
                except READ_ERRORS:
                    rows.append(empty)
                    warnings.append(f"{name}的狀態尚無法確認。")
            return rows, warnings
        except READ_ERRORS as exc:
            LOGGER.info("Catalog data status unavailable: %s", exc)
            return rows, [*warnings, "研究資料包的目錄無法讀取或驗證。"]

    def status(self) -> dict[str, Any]:
        now = self._now().astimezone(timezone.utc)
        producer, producer_warnings, updating = self._producer(now)
        try:
            labels = self._labels()
        except READ_ERRORS:
            labels = {}
        derived, derived_warnings = self._derived(now, labels)
        catalog, catalog_warnings = self._catalog_rows(labels)
        rows = producer + derived + catalog
        warnings = list(dict.fromkeys(producer_warnings + derived_warnings + catalog_warnings))
        state = "updating" if updating else "partial" if warnings or any(row["status"] != "ok" for row in rows) else "ok"
        return {"schema": SCHEMA, "status": state, "generated_at": now.isoformat(), "datasets": rows, "warnings": warnings}


def synthetic_data_status() -> dict[str, Any]:
    """Clearly fictional response without constructing any private readers."""
    return {
        "schema": SCHEMA,
        "status": "ok",
        "generated_at": "2000-01-03T00:00:00+00:00",
        "datasets": [
            {
                **_empty("synthetic-prices", "producer", "虛構示範股價", "ok"),
                "data_period": {"from": "2000-01-01", "to": "2000-01-03"},
                "last_updated": "2000-01-03T00:00:00+00:00",
                "symbols": 2,
                "rows": 6,
            }
        ],
        "warnings": ["這是虛構示範資料，與這台電腦的資料無關。"],
    }
