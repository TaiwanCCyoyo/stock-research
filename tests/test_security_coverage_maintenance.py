from __future__ import annotations

import contextlib
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_core import research_measurement_v1
from research_core.artifact_store import file_digest
from research_core.security_coverage_sources import _metadata, _sqlite_members, parquet_members


def test_sqlite_member_scans_filter_codes_before_gap_window(tmp_path: Path):
    database = tmp_path / "official_daily.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE official_daily_price(market TEXT, code TEXT, date TEXT)")
        connection.executemany(
            "INSERT INTO official_daily_price VALUES (?, ?, ?)",
            [
                ("TWSE", "AAA", "2010-01-04"),
                ("TWSE", "AAA", "2023-01-02"),
                ("TWSE", "BBB", "2010-01-04"),
                ("TWSE", "BBB", "2010-01-05"),
            ],
        )

    result = _sqlite_members(
        database,
        "official_daily_price",
        "date",
        deadline=10**12,
        gaps=True,
        codes=("AAA",),
    )

    assert [row["code"] for row in result] == ["AAA"]
    assert result[0]["gaps"] == [["2010-01-04", "2023-01-02"]]


def test_metadata_and_parquet_readers_filter_selected_codes(tmp_path: Path):
    metadata_path = tmp_path / "symbol_meta.sqlite"
    with sqlite3.connect(metadata_path) as connection:
        connection.execute(
            "CREATE TABLE symbol_meta(code TEXT, name TEXT, market TEXT, listed_date TEXT, is_etf INTEGER, "
            "security_category TEXT, fetched_at TEXT, industry_category TEXT)"
        )
        connection.executemany(
            "INSERT INTO symbol_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA", "A", "TWSE", "2010-01-04", 0, "股票", "2026-10-24", "測試業"),
                ("BBB", "B", "TWSE", "2010-01-04", 0, "股票", "2026-10-24", "測試業"),
            ],
        )
    records = _metadata(metadata_path, 10**12, ("BBB",))
    assert [row["code"] for row in records] == ["BBB"]
    assert records[0]["industry_category"] == "測試業"

    parquet_path = tmp_path / "prices.parquet"
    pq.write_table(
        pa.table({
            "Code": ["AAA", "AAA", "BBB"],
            "Date": pa.array([date(2020, 1, 1), date(2020, 1, 2), date(2021, 1, 1)], type=pa.date32()),
        }),
        parquet_path,
    )
    members = parquet_members(parquet_path, {"AAA": {"TWSE"}, "BBB": {"TWSE"}}, deadline=10**12, codes=("BBB",))
    assert [(row["code"], row["rows"]) for row in members] == [("BBB", 1)]


def test_adjusted_summary_reports_held_generation_identity_and_measurement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from research_core import maintained_adjusted_daily as maintained
    from research_core.security_coverage_sources import collect_adjusted_summary

    parquet_path = tmp_path / "reference_factor_adjusted.parquet"
    pq.write_table(
        pa.table({"Code": ["AAA", "BBB"], "Date": pa.array([date(2024, 1, 1), date(2024, 1, 2)], type=pa.date32())}),
        parquet_path,
    )
    digest = file_digest(parquet_path)
    generation = "fixture-generation"
    pinned = {
        "generation": generation,
        "path": tmp_path,
        "bases": {"reference_factor_adjusted": {"bytes": parquet_path.stat().st_size, "sha256": digest}},
    }
    holds: list[str] = []
    monkeypatch.setattr(maintained, "current_generation", lambda **kwargs: pinned)
    monkeypatch.setattr(maintained, "hold_generation", lambda *args, **kwargs: holds.append(args[0]))
    monkeypatch.setattr(maintained, "release_generation", lambda holder: holds.append(f"released:{holder}"))
    monkeypatch.setattr(research_measurement_v1, "resource_sample", _sample_counter())

    sources: dict[str, Any] = {}
    collect_adjusted_summary(
        sources,
        {"AAA": {"TWSE"}, "BBB": {"TWSE"}},
        seconds_per_source=10,
        codes=("AAA",),
        measure_resources=True,
    )

    adjusted = sources["adjusted_daily"]
    assert adjusted["input_identifier"] == {"generation": generation, "sha256": digest}
    assert adjusted["checked_at"]
    assert adjusted["measurement"]["phase"] == "security_coverage_source:adjusted_daily"
    assert adjusted["measurement"]["wall_seconds"] == 1.0
    assert adjusted["measurement"]["cpu_seconds"] == 0.5
    assert "physical reads may include full row groups" in adjusted["measurement"]["scan_scope"]
    assert [row["code"] for row in adjusted["members"]] == ["AAA"]
    assert holds[0] == generation
    assert holds[1].startswith("released:security-coverage-")


def _sample_counter():
    counter = iter(range(10))

    def sample():
        value = next(counter)
        return {"wall": float(value), "cpu": float(value) / 2, "native": None}

    return sample


def test_measurement_profiles_selected_reads_without_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from research_core import security_coverage_maintenance as maintenance

    monkeypatch.setattr(maintenance, "_maintenance_guard", contextlib.nullcontext)
    monkeypatch.setattr(maintenance, "producer_data_root", lambda: tmp_path)
    monkeypatch.setattr(research_measurement_v1, "resource_sample", _sample_counter())
    calls: list[dict[str, Any]] = []

    def collect(_root: Path, **kwargs: Any):
        calls.append(kwargs)
        return {"official_daily": {"status": "ok", "measurement": {"phase": "source"}}}, []

    monkeypatch.setattr(maintenance, "collect_sources", collect)
    monkeypatch.setattr(maintenance, "publish_coverage", lambda *args, **kwargs: pytest.fail("measurement published"))

    report = maintenance.measure_coverage([" AAA ", "BBB"], seconds_per_source=12)

    assert calls == [{"seconds_per_source": 12, "codes": ("AAA", "BBB"), "measure_resources": True}]
    assert report["status"] == "measured"
    assert report["measurement"]["selected_codes"] == ["AAA", "BBB"]
    assert report["measurement"]["publication"] == "none"
    assert report["measurement"]["phase"] == "security_coverage_selected_source_measurement"
    assert report["measurement"]["wall_seconds"] == 1.0
    assert report["measurement"]["cpu_seconds"] == 0.5
    assert "generation" not in report


def test_all_sources_unavailable_retains_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from research_core import security_coverage_maintenance as maintenance

    monkeypatch.setattr(maintenance, "_maintenance_guard", contextlib.nullcontext)
    monkeypatch.setattr(maintenance, "producer_data_root", lambda: tmp_path)
    monkeypatch.setattr(maintenance, "collect_sources", lambda *args, **kwargs: ({"official_daily": {"status": "unavailable"}}, []))
    monkeypatch.setattr(maintenance, "publish_coverage", lambda *args, **kwargs: pytest.fail("published empty replacement"))

    with pytest.raises(RuntimeError, match="No usable coverage source"):
        maintenance.update_coverage()


def test_update_records_resource_receipt_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from research_core import security_coverage_maintenance as maintenance

    monkeypatch.setattr(maintenance, "_maintenance_guard", contextlib.nullcontext)
    monkeypatch.setattr(maintenance, "producer_data_root", lambda: tmp_path)
    monkeypatch.setattr(research_measurement_v1, "resource_sample", _sample_counter())
    source_calls: list[dict[str, Any]] = []
    published: list[dict[str, Any]] = []

    def collect(_root: Path, **kwargs: Any):
        source_calls.append(kwargs)
        return {"official_daily": {"status": "ok", "measurement": {"phase": "source"}}}, []

    monkeypatch.setattr(maintenance, "collect_sources", collect)
    monkeypatch.setattr(maintenance, "project_security_coverage", lambda *args, **kwargs: {"securities": []})
    monkeypatch.setattr(maintenance, "code_identity", lambda: {"commit": "synthetic"})

    def publish(document: dict[str, Any]):
        published.append(document)
        return {"generation": "fixture-generation"}

    monkeypatch.setattr(maintenance, "publish_coverage", publish)

    result = maintenance.update_coverage(seconds_per_source=15)

    metrics = published[0]["build_metrics"]
    assert source_calls == [{"seconds_per_source": 15, "measure_resources": True}]
    assert result["metrics"] == metrics
    assert metrics["wall_seconds"] == 1.0
    assert metrics["cpu_seconds"] == 0.5
    assert metrics["native"] is None
    assert metrics["workers"] == 1
    assert metrics["max_in_flight"] == 1
    assert "ends before artifact serialization and publication" in metrics["measurement_scope"]
