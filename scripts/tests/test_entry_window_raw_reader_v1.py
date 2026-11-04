"""Real maintained-reader integration using entirely artificial temporary data."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import entry_window_raw_quotes_v1 as raw_reader
from research_core import maintained_adjusted_daily, run_receipt
from research_core.entry_window_inputs_v1 import InputRequest

CALENDAR = pd.DatetimeIndex(["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-17", "2026-10-19"])
CUTOFF = cast(pd.Timestamp, pd.Timestamp("2026-10-20"))


def _producer_quotes(root: Path, *, first_close: float = 100.0, duplicate: bool = False, last_day: str = "2026-10-21") -> None:
    """Supply source-date union independently from the target security's gaps."""
    rows: list[dict[str, Any]] = []
    for day in [*CALENDAR, pd.Timestamp(last_day)]:
        rows.append({"Code": "1101", "Date": day, "Open": 50.0, "High": 51.0, "Low": 49.0, "Close": 50.0, "Volume": 100.0, "Source": "official"})
    for day, opening, high, low, close in (
        ("2026-10-13", first_close, first_close + 1.0, first_close - 1.0, first_close),
        ("2026-10-15", 101.0, 100.0, 99.0, 101.0),  # Invalid high: raw values must survive the quality mask.
        ("2026-10-17", 0.0, 101.0, 0.0, 100.0),  # Explicit Saturday and a nonpositive open.
    ):
        rows.append({
            "Code": "2330",
            "Date": pd.Timestamp(day),
            "Open": opening,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": 1000.0,
            "Source": "official",
        })
    if duplicate:
        rows.append({**rows[-3], "Close": first_close + 0.5})
    pd.DataFrame(rows).to_parquet(root / "price_daily.parquet", index=False)


@pytest.fixture()
def artificial_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    producer, shared = tmp_path / "artificial producer", tmp_path / "artificial shared root"
    producer.mkdir()
    shared.mkdir()
    _producer_quotes(producer)
    with sqlite3.connect(producer / "corporate_actions.sqlite") as connection:
        connection.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
    # Isolate producer classification and scheduler checks: no production resolver
    # or running-task inventory is consulted for these synthetic input files.
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(producer))
    monkeypatch.setenv("STOCK_RESEARCH_SHARED_ROOT", str(shared))
    monkeypatch.setattr(run_receipt, "producer_data_root", lambda: producer)
    monkeypatch.setattr(run_receipt, "assert_producer_idle", lambda now=None: None)
    monkeypatch.setattr(maintained_adjusted_daily, "code_identity", lambda: {"commit": "synthetic-reader-integration", "dirty": False})
    return producer, shared


def _request(generation: str) -> InputRequest:
    return InputRequest(
        security_id="2330",
        generation=generation,
        study_as_of=CUTOFF,
        common_calendar=CALENDAR.copy(),
        universe_id="synthetic-universe.v1",
        calendar_id="synthetic-calendar.v1",
    )


def test_real_generation_reader_preserves_raw_bars_quality_and_original_calendar(artificial_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = artificial_roots
    built = maintained_adjusted_daily.update(producer_root=producer, root=shared)
    request = _request(built["generation"])
    expected_frame, expected_record = maintained_adjusted_daily.read_adjusted_daily(
        "raw", root=shared, generation=request.generation, codes=["2330"], as_of=CUTOFF, calendar=request.common_calendar
    )
    calls: list[tuple[str, dict[str, Any]]] = []
    original = maintained_adjusted_daily.read_adjusted_daily

    def observed_read(basis: str, **kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
        calls.append((basis, kwargs.copy()))
        return original(basis, **kwargs)

    monkeypatch.setattr(maintained_adjusted_daily, "read_adjusted_daily", observed_read)
    result = raw_reader.load_raw_quote_packet(request, root=shared)

    assert len(calls) == 1
    basis, kwargs = calls[0]
    assert basis == "raw"
    assert kwargs["root"] == shared and kwargs["generation"] == request.generation
    assert kwargs["codes"] == ["2330"] and kwargs["as_of"] == CUTOFF
    assert kwargs["calendar"].equals(CALENDAR)
    assert result.packet.calendar.equals(CALENDAR)
    assert result.packet.study_as_of == CUTOFF > CALENDAR[-1]
    assert result.packet.security_id == "2330" and result.packet.generation == request.generation
    assert result.packet.calendar_id == request.calendar_id and result.packet.universe_id == request.universe_id
    assert result.packet.basis == "raw"
    for field in ("Open", "High", "Low", "Close"):
        values = getattr(result.packet, f"raw_{field.lower()}")
        np.testing.assert_array_equal(values, expected_frame[f"Raw{field}"].to_numpy())
        assert values.dtype == np.dtype("float64")
    np.testing.assert_array_equal(result.quality, expected_frame["Quality"].to_numpy())
    assert result.quality_reason == tuple(expected_frame["quality_reason"])
    assert result.quality_reason == ("missing_official_quote", None, "missing_official_quote", "invalid_ohlc", "invalid_ohlc", "missing_official_quote")
    assert np.isnan(result.packet.raw_open[[0, 2, 5]]).all(), "Beginning, middle and end gaps retain their original positions"
    assert cast(pd.Timestamp, CALENDAR[4]).dayofweek == 5 and result.packet.raw_open[4] == 0.0, "A declared Saturday session is not dropped"
    assert np.isnan(expected_frame.loc[3, "Open"]) and result.packet.raw_open[3] == 101.0
    assert np.isnan(expected_frame.loc[4, "Open"]) and result.packet.raw_open[4] == 0.0
    assert dict(result.source_record) == expected_record
    assert result.source_record["asof"] == "2026-10-21" and result.source_record["as_of"] == "2026-10-20"
    assert result.source_record["definition"] == "price-basis.v2"
    assert result.source_record["calendar"]["source"] == "caller"
    assert result.source_record["codes"] == 1
    for key in ("file", "sha256", "status_sha256", "actions_sha256", "as_of_method"):
        assert result.source_record[key] == expected_record[key]
    assert "not" in result.validation_scope.lower()
    assert not hasattr(result, "intervals"), "Empty source actions do not become E1 interval coverage"


def test_explicit_generation_stays_pinned_after_current_changes(artificial_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = artificial_roots
    first = maintained_adjusted_daily.update(producer_root=producer, root=shared)
    request = _request(first["generation"])
    before = raw_reader.load_raw_quote_packet(request, root=shared)
    _producer_quotes(producer, first_close=120.0, last_day="2026-10-22")
    second = maintained_adjusted_daily.update(producer_root=producer, root=shared)
    assert second["generation"] != first["generation"]
    assert maintained_adjusted_daily.current_generation(shared)["generation"] == second["generation"]
    original = maintained_adjusted_daily.current_generation
    seen: list[str | None] = []

    def pinned_status(root: Path | None = None, *, generation: str | None = None) -> dict[str, Any]:
        seen.append(generation)
        assert root == shared and generation == first["generation"], "An adapter may never ask the reader for current"
        return original(root, generation=generation)

    def no_producer_read(*args: object, **kwargs: object) -> None:
        pytest.fail("Loading a retained generation must not read producer inputs or build another generation")

    monkeypatch.setattr(maintained_adjusted_daily, "current_generation", pinned_status)
    monkeypatch.setattr(maintained_adjusted_daily, "load_inputs", no_producer_read)
    after = raw_reader.load_raw_quote_packet(request, root=shared)
    assert seen == [first["generation"]]
    assert after.source_record == before.source_record
    np.testing.assert_array_equal(after.packet.raw_close, before.packet.raw_close)
    assert after.packet.raw_close[1] == 100.0


def test_real_reader_duplicate_source_date_refuses_the_entire_load(artificial_roots: tuple[Path, Path]) -> None:
    producer, shared = artificial_roots
    _producer_quotes(producer, duplicate=True)
    generation = maintained_adjusted_daily.update(producer_root=producer, root=shared)["generation"]
    frame, _ = maintained_adjusted_daily.read_adjusted_daily("raw", root=shared, generation=generation, codes=["2330"], as_of=CUTOFF, calendar=CALENDAR)
    assert frame["quality_reason"].fillna("").str.contains("duplicate_date").any()
    with pytest.raises(ValueError, match="duplicate_date"):
        raw_reader.load_raw_quote_packet(_request(generation), root=shared)


@pytest.mark.parametrize("bad_root", [None, Path("relative/shared")])
def test_loader_refuses_implicit_or_relative_root_before_reader_io(bad_root: Path | None, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_read(*args: object, **kwargs: object) -> None:
        pytest.fail("An invalid explicit root must be rejected before reader I/O")

    monkeypatch.setattr(maintained_adjusted_daily, "read_adjusted_daily", forbidden_read)
    with pytest.raises((TypeError, ValueError)):
        raw_reader.load_raw_quote_packet(_request("fixed-generation"), root=bad_root)  # type: ignore[arg-type]


def test_root_is_required_even_when_environment_has_an_artificial_root(artificial_roots: tuple[Path, Path]) -> None:
    with pytest.raises(TypeError):
        raw_reader.load_raw_quote_packet(_request("fixed-generation"))  # type: ignore[call-arg]


@pytest.mark.parametrize("kind", ["empty_generation", "none_generation", "empty_security", "future_calendar"])
def test_malformed_request_is_rejected_before_reader_io(kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request("fixed-generation")
    if kind == "empty_generation":
        request = replace(request, generation="")
    elif kind == "none_generation":
        request = replace(request, generation=None)  # type: ignore[arg-type]
    elif kind == "empty_security":
        request = replace(request, security_id="")
    else:
        request = replace(request, study_as_of=CALENDAR[-2])

    def forbidden_read(*args: object, **kwargs: object) -> None:
        pytest.fail("Malformed request and calendar after cutoff must fail before reader I/O")

    monkeypatch.setattr(maintained_adjusted_daily, "read_adjusted_daily", forbidden_read)
    with pytest.raises(ValueError):
        raw_reader.load_raw_quote_packet(request, root=tmp_path)


def test_missing_fixed_generation_does_not_fall_back_to_current(artificial_roots: tuple[Path, Path]) -> None:
    producer, shared = artificial_roots
    maintained_adjusted_daily.update(producer_root=producer, root=shared)
    with pytest.raises(FileNotFoundError):
        raw_reader.load_raw_quote_packet(_request("unavailable-fixed-generation"), root=shared)


def test_real_reader_refusal_after_generation_cutoff_propagates(artificial_roots: tuple[Path, Path]) -> None:
    producer, shared = artificial_roots
    generation = maintained_adjusted_daily.update(producer_root=producer, root=shared)["generation"]
    request = replace(_request(generation), study_as_of=pd.Timestamp("2026-10-22"))
    with pytest.raises(ValueError, match="after generation"):
        raw_reader.load_raw_quote_packet(request, root=shared)


def test_reader_exception_is_propagated_without_empty_packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    failure = OSError("synthetic generation read failed")

    def failed_read(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(maintained_adjusted_daily, "read_adjusted_daily", failed_read)
    with pytest.raises(OSError) as caught:
        raw_reader.load_raw_quote_packet(_request("fixed-generation"), root=tmp_path)
    assert caught.value is failure
