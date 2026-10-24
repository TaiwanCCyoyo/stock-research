"""Stored chart rows retain their source values without touching private data."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.data_series import create_data_series_router
from research_core import data_series, live_producer
from research_core.data_series import SPECS, DataSeriesView, Dataset


def _insert(root: Path, dataset: Dataset, **values: Any) -> None:
    spec = SPECS[dataset]
    with sqlite3.connect(root / spec.filename) as connection:
        primary_key = ",PRIMARY KEY(market,code,revenue_month)" if dataset == "monthly-revenue" else ""
        connection.execute(f"CREATE TABLE IF NOT EXISTS {spec.table} ({','.join(spec.columns)}{primary_key})")
        connection.execute(
            f"INSERT INTO {spec.table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()),
        )


@pytest.fixture
def view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataSeriesView:
    monkeypatch.setattr(live_producer, "assert_producer_idle", lambda **kwargs: None)
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    _insert(tmp_path, "institutional", code="2330", market="TWSE", date="2020-01-03", foreign_total_net=-1200, trust_net=None, dealer_total_net=0)
    _insert(tmp_path, "institutional", code="2330", market="TWSE", date="2020-01-02", foreign_total_net=2000)
    _insert(tmp_path, "institutional", code="2330", market="TPEx", date="2020-01-02", foreign_total_net=10)
    _insert(tmp_path, "institutional", code="9999", market="TWSE", date="2020-01-02", foreign_total_net=90)
    _insert(
        tmp_path,
        "monthly-revenue",
        code="2330",
        market="TWSE",
        revenue_month="2020-02",
        current_revenue_k_twd=123456,
        mom_pct=-1.25,
        yoy_pct=None,
        available_at=None,
        source_report_date="2020-03-10",
        availability_kind="HISTORICAL_NO_EXACT_TIME",
        first_observed_at="2026-10-24T00:00:00Z",
        last_fetched_at="2026-10-24T01:00:00Z",
    )
    _insert(tmp_path, "monthly-revenue", code="2330", market="TWSE", revenue_month="2020-01", current_revenue_k_twd=100000)
    _insert(tmp_path, "monthly-revenue", code="2330", market="TPEx", revenue_month="2020-02", current_revenue_k_twd=20)
    return DataSeriesView(tmp_path)


def _client(view: DataSeriesView) -> TestClient:
    app = FastAPI()
    app.include_router(create_data_series_router(view))
    return TestClient(app)


def test_institutional_filters_and_preserves_shares_nulls_and_zero(view: DataSeriesView) -> None:
    result = view.series("institutional", "2330", "2020-01-03", "2020-01-03", "TWSE")
    assert result["status"] == "ok"
    assert result["granularity"] == "daily"
    assert result["units"] == {"counts": "shares"}
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["foreign_total_net"] == -1200
    assert row["trust_net"] is None
    assert row["dealer_total_net"] == 0
    assert row["three_institutions_net"] is None


def test_unfiltered_markets_remain_separate_and_ordered(view: DataSeriesView) -> None:
    rows = view.series("institutional", "2330")["rows"]
    assert [(row["date"], row["market"]) for row in rows] == [("2020-01-02", "TPEx"), ("2020-01-02", "TWSE"), ("2020-01-03", "TWSE")]
    assert {row["code"] for row in rows} == {"2330"}


def test_revenue_is_monthly_current_revision_with_original_availability(view: DataSeriesView) -> None:
    result = view.series("monthly-revenue", "2330", "2020-02", "2020-02", "TWSE")
    assert result["granularity"] == "monthly"
    assert result["units"] == {"revenue": "thousands_TWD", "percentages": "percentage_points"}
    row = result["rows"][0]
    assert len(result["rows"]) == 1
    assert row["current_revenue_k_twd"] == 123456
    assert row["mom_pct"] == -1.25
    assert row["yoy_pct"] is None and row["available_at"] is None and row["announcement_at"] is None
    assert row["source_report_date"] == "2020-03-10"
    assert row["first_observed_at"] == "2026-10-24T00:00:00Z"
    assert row["availability_kind"] == "HISTORICAL_NO_EXACT_TIME"
    assert result["warnings"]


def test_empty_selection_stays_empty_without_other_code_or_period(view: DataSeriesView) -> None:
    result = view.series("monthly-revenue", "2330", "2019-12", "2019-12")
    assert result["status"] == "missing" and result["rows"] == []


def test_revenue_without_market_seeks_primary_key_and_keeps_both_markets(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original = live_producer.readonly_sqlite
    queries: list[str] = []

    def traced(path: Path, **kwargs: Any) -> sqlite3.Connection:
        connection = original(path, **kwargs)
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(live_producer, "readonly_sqlite", traced)
    rows = view.series("monthly-revenue", "2330", "2020-02", "2020-02")["rows"]
    assert [(row["market"], row["current_revenue_k_twd"]) for row in rows] == [("TPEx", 20), ("TWSE", 123456)]
    select = next(query for query in queries if query.startswith("SELECT "))
    connection = original(tmp_path / "monthly_revenue.sqlite")
    try:
        plan = [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + select)]
    finally:
        connection.close()
    assert any("SEARCH monthly_revenue_current USING INDEX sqlite_autoindex_monthly_revenue_current_1 (market=? AND code=?" in step for step in plan)
    assert not any("SCAN monthly_revenue_current" in step for step in plan)


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("institutional/2330", {"from": "2020-1-01"}),
        ("institutional/2330", {"from": "2020-02-30"}),
        ("institutional/2330", {"from": "2020-01-03", "to": "2020-01-02"}),
        ("monthly-revenue/2330", {"from": "2020-13"}),
        ("monthly-revenue/2330", {"from": "2020-01-01"}),
        ("monthly-revenue/2330", {"from": "2020-02", "to": "2020-01"}),
        ("institutional/2330", {"market": "OTHER"}),
        ("institutional/2330'OR'1'='1", {}),
        ("institutional/台積電", {}),
    ],
)
def test_invalid_requests_fail_before_private_read(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch, path: str, params: dict) -> None:
    def forbidden(**kwargs: Any) -> None:
        pytest.fail("invalid selection attempted producer read")

    monkeypatch.setattr(live_producer, "assert_producer_idle", forbidden)
    assert _client(view).get("/data-series/v1/" + path, params=params).status_code == 422


def test_oversized_results_are_rejected_instead_of_truncated(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_series, "MAX_ROWS", 1)
    result = _client(view).get("/data-series/v1/institutional/2330")
    assert result.status_code == 422
    assert "rows" not in result.json()


def test_busy_producer_does_not_resolve_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")

    def busy(**kwargs: Any) -> None:
        raise live_producer.ProducerBusyError("synthetic running task")

    def forbidden() -> Path:
        pytest.fail("busy producer root was resolved")

    monkeypatch.setattr(live_producer, "assert_producer_idle", busy)
    monkeypatch.setattr(data_series, "producer_data_root", forbidden)
    result = _client(DataSeriesView()).get("/data-series/v1/institutional/2330")
    assert result.status_code == 200
    assert result.json()["status"] == "updating" and result.json()["rows"] == []


def test_writer_starting_after_read_discards_rows(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch) -> None:
    checks = []

    def idle_then_busy(**kwargs: Any) -> None:
        checks.append(True)
        if len(checks) == 2:
            raise live_producer.ProducerBusyError("synthetic writer started")

    monkeypatch.setattr(live_producer, "assert_producer_idle", idle_then_busy)
    result = view.series("institutional", "2330")
    assert len(checks) == 2
    assert result["status"] == "updating" and result["rows"] == []


def test_slow_task_probes_keep_their_own_budget_without_exhausting_query(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    probe_timeouts: list[float] = []
    monkeypatch.setattr(data_series, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def slow_idle(*, task_timeout: float) -> None:
        probe_timeouts.append(task_timeout)
        clock[0] += 3.0

    monkeypatch.setattr(live_producer, "assert_producer_idle", slow_idle)
    result = view.series("monthly-revenue", "2330")
    assert result["status"] == "ok" and len(result["rows"]) == 3
    assert probe_timeouts == [5.0, 5.0]
    assert clock[0] == 106.0


def test_query_still_has_a_separate_five_second_deadline(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    opened: list[sqlite3.Connection] = []
    timeouts: list[float] = []
    monkeypatch.setattr(data_series, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    class SlowConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            cursor = super().execute(sql, parameters)
            clock[0] += 6.0
            return cursor

    def slow_query(path: Path, *, timeout: float) -> sqlite3.Connection:
        timeouts.append(timeout)
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=timeout, factory=SlowConnection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(live_producer, "readonly_sqlite", slow_query)
    result = view.series("monthly-revenue", "2330")
    assert result["status"] == "missing" and result["rows"] == []
    assert timeouts == [5.0]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


@pytest.mark.parametrize("change", ["main", "wal"])
def test_database_or_wal_change_after_read_discards_rows(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    original = live_producer.read_stable

    def changed(path: Path, read: Any) -> Any:
        rows = original(path, read)
        if change == "wal":
            path.with_name(path.name + "-wal").write_bytes(b"synthetic WAL identity change")
        else:
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        return rows

    monkeypatch.setattr(live_producer, "read_stable", changed)
    result = view.series("institutional", "2330")
    assert result["status"] == "updating" and result["rows"] == []


def test_connections_are_readonly_and_closed(view: DataSeriesView, monkeypatch: pytest.MonkeyPatch) -> None:
    original = live_producer.readonly_sqlite
    opened = []

    def checked(path: Path, **kwargs: Any) -> sqlite3.Connection:
        connection = original(path, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM institutional_daily")
        opened.append(connection)
        return connection

    monkeypatch.setattr(live_producer, "readonly_sqlite", checked)
    assert view.series("institutional", "2330")["status"] == "ok"
    assert opened
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_missing_and_invalid_artifacts_do_not_leak_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_producer, "assert_producer_idle", lambda **kwargs: None)
    view = DataSeriesView(tmp_path)
    missing = view.series("institutional", "2330")
    assert missing["status"] == "missing"
    (tmp_path / "institutional.sqlite").write_bytes(b"not a SQLite database")
    malformed = view.series("institutional", "2330")
    assert malformed["status"] == "missing"
    assert str(tmp_path) not in str(missing) + str(malformed)


@pytest.mark.parametrize("dataset", ["institutional", "monthly-revenue"])
def test_synthetic_mode_never_reads_private_data(monkeypatch: pytest.MonkeyPatch, dataset: str) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "public-synthetic")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("synthetic request attempted private data access")

    monkeypatch.setattr(DataSeriesView, "series", forbidden)
    monkeypatch.setattr(data_series, "producer_data_root", forbidden)
    monkeypatch.setattr(live_producer, "assert_producer_idle", forbidden)
    client = _client(DataSeriesView())
    result = client.get(f"/data-series/v1/{dataset}/DEMO").json()
    assert result["synthetic"] is True and result["rows"][0]["name"] == "虛構示範公司"
    assert client.get(f"/data-series/v1/{dataset}/2330").json()["rows"] == []


def test_unknown_mode_fails_closed_before_private_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "unknown")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("unknown mode attempted private read")

    monkeypatch.setattr(DataSeriesView, "series", forbidden)
    assert _client(DataSeriesView()).get("/data-series/v1/institutional/DEMO").status_code == 503
