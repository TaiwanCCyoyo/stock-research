"""Bounded read-only projections of stored institutional and monthly revenue rows."""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from research_core import live_producer
from research_core.producer_data import producer_data_root

LOGGER = logging.getLogger(__name__)
MAX_ROWS = 10_000
READ_SECONDS = 15.0
TASK_PROBE_SECONDS = 5.0
QUERY_SECONDS = 5.0
Dataset = Literal["institutional", "monthly-revenue"]
Market = Literal["TWSE", "TPEx"]
INSTITUTIONAL_COLUMNS = (
    "market",
    "date",
    "code",
    "name",
    "instrument_type",
    "foreign_total_buy",
    "foreign_total_sell",
    "foreign_total_net",
    "foreign_excl_dealer_buy",
    "foreign_excl_dealer_sell",
    "foreign_excl_dealer_net",
    "foreign_dealer_buy",
    "foreign_dealer_sell",
    "foreign_dealer_net",
    "trust_buy",
    "trust_sell",
    "trust_net",
    "dealer_total_buy",
    "dealer_total_sell",
    "dealer_total_net",
    "dealer_self_buy",
    "dealer_self_sell",
    "dealer_self_net",
    "dealer_hedge_buy",
    "dealer_hedge_sell",
    "dealer_hedge_net",
    "three_institutions_net",
    "source",
    "schema_signature",
    "published_at",
    "fetched_at",
)
REVENUE_COLUMNS = (
    "market",
    "code",
    "revenue_month",
    "name",
    "industry",
    "current_revenue_k_twd",
    "previous_month_revenue_k_twd",
    "prior_year_month_revenue_k_twd",
    "mom_pct",
    "yoy_pct",
    "cumulative_revenue_k_twd",
    "prior_year_cumulative_revenue_k_twd",
    "cumulative_yoy_pct",
    "note",
    "source",
    "source_report_date",
    "announcement_at",
    "available_at",
    "availability_kind",
    "first_observed_at",
    "last_fetched_at",
    "revision_no",
)


@dataclass(frozen=True)
class SeriesSpec:
    filename: str
    table: str
    period: str
    columns: tuple[str, ...]
    granularity: str
    units: dict[str, str]


SPECS: dict[Dataset, SeriesSpec] = {
    "institutional": SeriesSpec("institutional.sqlite", "institutional_daily", "date", INSTITUTIONAL_COLUMNS, "daily", {"counts": "shares"}),
    "monthly-revenue": SeriesSpec(
        "monthly_revenue.sqlite",
        "monthly_revenue_current",
        "revenue_month",
        REVENUE_COLUMNS,
        "monthly",
        {"revenue": "thousands_TWD", "percentages": "percentage_points"},
    ),
}


class SeriesRequestError(ValueError):
    """An invalid selection or oversized result; no partial result is returned."""


def validate_selection(dataset: Dataset, code: str, first: str | None, last: str | None, market: str | None) -> None:
    if not re.fullmatch(r"[A-Za-z0-9]{1,16}", code):
        raise SeriesRequestError("股票代號格式不符。")
    if market not in (None, "TWSE", "TPEx"):
        raise SeriesRequestError("市場格式不符。")
    for value in (first, last):
        if value is None:
            continue
        try:
            if dataset == "institutional":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError("noncanonical date")
            elif not re.fullmatch(r"\d{4}-\d{2}", value) or date.fromisoformat(value + "-01").strftime("%Y-%m") != value:
                raise ValueError("noncanonical month")
        except ValueError:
            raise SeriesRequestError("日期格式不符，請使用有效的年月或年月日。") from None
    if first is not None and last is not None and first > last:
        raise SeriesRequestError("起日不可晚於迄日。")


def _response(dataset: Dataset, code: str, status: str, rows: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    spec = SPECS[dataset]
    return {
        "schema": "research-data-series.v1",
        "dataset": dataset,
        "code": code,
        "granularity": spec.granularity,
        "units": spec.units,
        "status": status,
        "rows": rows,
        "warnings": warnings,
    }


def _database_identity(path: Path) -> tuple[tuple[int, int], tuple[int, int] | None]:
    wal = path.with_name(path.name + "-wal")
    try:
        wal_identity = live_producer.stat_identity(wal)
    except FileNotFoundError:
        wal_identity = None
    return live_producer.stat_identity(path), wal_identity


class DataSeriesView:
    """Read at most one selected security, without modifying producer artifacts."""

    def __init__(self, root: Path | None = None):
        self._root = root

    def series(self, dataset: Dataset, code: str, first: str | None = None, last: str | None = None, market: Market | None = None) -> dict[str, Any]:
        validate_selection(dataset, code, first, last, market)
        spec = SPECS[dataset]
        deadline = time.monotonic() + READ_SECONDS

        def remaining() -> float:
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError("stored series read timed out")
            return budget

        try:
            live_producer.assert_producer_idle(task_timeout=min(TASK_PROBE_SECONDS, remaining()))
            path = (self._root if self._root is not None else producer_data_root()) / spec.filename
            before = _database_identity(path)

            def read(source: Path) -> list[dict[str, Any]]:
                query_deadline = min(deadline, time.monotonic() + QUERY_SECONDS)

                def query_remaining() -> float:
                    budget = query_deadline - time.monotonic()
                    if budget <= 0:
                        raise TimeoutError("stored series query timed out")
                    return budget

                connection = live_producer.readonly_sqlite(source, timeout=query_remaining())
                try:
                    connection.set_progress_handler(lambda: time.monotonic() >= query_deadline, 1000)
                    query_remaining()
                    connection.row_factory = sqlite3.Row
                    clauses = ["code = ?"]
                    values: list[str | int] = [code]
                    if dataset == "monthly-revenue" and market is None:
                        # The leading PK column is market; constrain both markets so
                        # an unfiltered selection still seeks by (market, code).
                        clauses.append("market IN (?, ?)")
                        values.extend(("TWSE", "TPEx"))
                    for field, operator, value in (("market", "=", market), (spec.period, ">=", first), (spec.period, "<=", last)):
                        if value is not None:
                            clauses.append(f"{field} {operator} ?")
                            values.append(value)
                    values.append(MAX_ROWS + 1)
                    query = f"SELECT {','.join(spec.columns)} FROM {spec.table} WHERE {' AND '.join(clauses)} ORDER BY {spec.period}, market LIMIT ?"
                    rows = [dict(row) for row in connection.execute(query, values).fetchall()]
                    query_remaining()
                    if len(rows) > MAX_ROWS:
                        raise SeriesRequestError("資料超過一萬筆，請縮小日期範圍。")
                    return rows
                finally:
                    connection.close()

            rows = live_producer.read_stable(path, read)
            live_producer.assert_producer_idle(task_timeout=min(TASK_PROBE_SECONDS, remaining()))
            if _database_identity(path) != before:
                raise live_producer.ProducerChangedError("database or WAL changed during series read")
            remaining()
            LOGGER.debug("Read stored overlay dataset=%s code=%s rows=%d", dataset, code, len(rows))
            warnings = [] if rows else ["所選股票與期間沒有已保存的資料。"]
            if dataset == "monthly-revenue" and rows:
                warnings.append("月營收為目前修訂值；營收月份不是公告時間，缺少可取得時間的資料不能作為當時已知的證據。")
            return _response(dataset, code, "ok" if rows else "missing", rows, warnings)
        except (live_producer.ProducerBusyError, live_producer.ProducerChangedError):
            return _response(dataset, code, "updating", [], ["資料更新中，請稍後再讀取。"])
        except (OSError, sqlite3.Error, TimeoutError, ValueError) as exc:
            if isinstance(exc, SeriesRequestError):
                raise
            LOGGER.warning("Stored overlay unavailable dataset=%s code=%s: %s", dataset, code, exc)
            return _response(dataset, code, "missing", [], ["已保存的資料暫時無法讀取，請稍後再試。"])


def synthetic_series(dataset: Dataset, code: str, first: str | None, last: str | None, market: Market | None) -> dict[str, Any]:
    """Explicitly fictional rows; only named demo identities are populated."""
    validate_selection(dataset, code, first, last, market)
    spec = SPECS[dataset]
    row: dict[str, Any] = {column: None for column in spec.columns}
    row.update({"code": "DEMO", "market": market or "TWSE", "name": "虛構示範公司", "source": "fictional-demo"})
    if dataset == "institutional":
        row.update({"date": "2020-01-02", "foreign_total_net": 123, "trust_net": 0, "dealer_total_net": None})
    else:
        row.update({"revenue_month": "2020-01", "current_revenue_k_twd": 123, "yoy_pct": None, "availability_kind": "HISTORICAL_NO_EXACT_TIME"})
        names = {"REVENUE": "月營收示範", "NEW23": "新芽示範", "PAST": "歷史示範"}
        if code in names:
            row.update(code=code, name=names[code], revenue_month="2026-09")
    period = row[spec.period]
    selected = row["code"] == code and (first is None or period >= first) and (last is None or period <= last)
    result = _response(dataset, code, "ok" if selected else "missing", [row] if selected else [], ["這是虛構示範資料，不是真實行情或營收。"])
    result["synthetic"] = True
    return result
