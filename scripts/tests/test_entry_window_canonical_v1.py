"""Artificial canonical adapter cases, with the original public calculation oracle."""

from __future__ import annotations

import builtins
import copy
import inspect
import socket
import sqlite3
import urllib.request
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import entry_window_canonical_v1 as reader
from research_core import entry_window_inputs_v1 as inputs
from research_core import maintained_adjusted_daily as maintained
from research_core import momentum_only_v1 as canonical
from research_core.artifact_store import object_digest

NUMERIC_COLUMNS = ("Open", "High", "Low", "Close", "RawClose", "VolumeLots", "Turnover")
NOTE = "Artificial declared membership/availability only; no historical PIT certification"


@dataclass(frozen=True)
class Fixture:
    request: inputs.InputRequest
    frame: pd.DataFrame
    record: dict[str, Any]


def _fixture(n: int = 140) -> Fixture:
    calendar = pd.date_range("2017-01-02", periods=n, freq="D")
    cutoff = cast(pd.Timestamp, calendar[-1] + pd.Timedelta(days=2))
    request = inputs.InputRequest(
        security_id="FAKE_CANONICAL",
        generation="artificial-canonical-generation",
        study_as_of=cutoff,
        common_calendar=calendar,
        universe_id="artificial-universe",
        calendar_id="artificial-calendar",
    )
    # These numbers are supplied directly; no source reader or price builder runs.
    close = np.exp(np.linspace(np.log(10), np.log(60), n)).astype(np.float64)
    frame = pd.DataFrame({
        "Code": pd.Series([request.security_id] * n, dtype=object),
        "Date": calendar,
        "Open": close * 0.998,
        "High": close * 1.02,
        "Low": close * 0.98,
        "Close": close,
        "RawClose": close * 0.9,
        "VolumeLots": np.full(n, 2500.0),
        "Turnover": np.full(n, 150000.0),
        "Quality": np.ones(n, dtype=bool),
        "quality_reason": pd.Series([None] * n, dtype=object),
    })
    for position in (0, 7, n - 1):
        frame.loc[position, ["Open", "High", "Low", "Close", "RawClose"]] = np.nan
        frame.loc[position, "Quality"] = False
        frame.loc[position, "quality_reason"] = "missing_official_quote"
    frame.loc[n // 2, "quality_reason"] = "unexplained_adjusted_jump"
    days = [day.date().isoformat() for day in calendar]
    record: dict[str, Any] = {
        "family": "adjusted-daily-v1",
        "generation": request.generation,
        "asof": cast(pd.Timestamp, cutoff + pd.Timedelta(days=9)).date().isoformat(),
        "basis": "reference_factor_adjusted",
        "file": "artificial-generation/reference_factor_adjusted.parquet; not opened",
        "sha256": "a" * 64,
        "status_sha256": "b" * 64,
        "as_of": cutoff.date().isoformat(),
        "as_of_method": "price_basis.prepare_prices at as_of from the generation's raw quotes and actions snapshot",
        "definition": "price-basis.v2",
        "actions_sha256": "c" * 64,
        "calendar": {"source": "caller", "sessions": n, "first": days[0], "last": days[-1], "sha256": object_digest(days)},
        "codes": 1,
        "extra": {"notes": ["artificial retained metadata"]},
    }
    return Fixture(request, frame, record)


def _adapt(f: Fixture, *, ordinary_reference: bool = True) -> reader.CanonicalRead:
    return reader.adapt_canonical_read(f.request, f.frame, f.record, ordinary_reference=ordinary_reference, availability_note=NOTE)


def _assert_stock_equal(actual: canonical.StockDaily, expected: canonical.StockDaily) -> None:
    assert actual.code == expected.code and actual.split == expected.split
    for name in ("eligible", "jump", "c52w", "ret120"):
        np.testing.assert_array_equal(getattr(actual, name), getattr(expected, name))
    for name in ("atoms", "labels", "main_eligible", "calendar_full"):
        actual_mapping, expected_mapping = getattr(actual, name), getattr(expected, name)
        assert tuple(actual_mapping) == tuple(expected_mapping)
        for key in expected_mapping:
            np.testing.assert_array_equal(actual_mapping[key], expected_mapping[key])


def _stub_stock(code: str, n: int) -> canonical.StockDaily:
    """Hand supplied values for call-boundary spies, never an outcome oracle."""
    return canonical.StockDaily(
        code,
        "artificial",
        np.zeros(n, dtype=bool),
        np.zeros(n, dtype=bool),
        np.zeros(n, dtype=bool),
        {atom: np.full(n, -1, dtype=np.int8) for atom in canonical.LOCAL_ATOMS},
        np.full(n, np.nan),
        {label: np.zeros(n, dtype=np.int8) for label in canonical.LABELS},
        {label: np.zeros(n, dtype=bool) for label in canonical.LABELS},
        {horizon: np.zeros(n, dtype=bool) for horizon in canonical.HORIZONS},
    )


@pytest.fixture(scope="module", params=[True, False], ids=["ordinary", "not-ordinary"])
def oracle_case(request: pytest.FixtureRequest) -> tuple[Fixture, bool, reader.CanonicalRead, canonical.StockDaily]:
    ordinary = cast(bool, request.param)
    f = _fixture()
    result = _adapt(f, ordinary_reference=ordinary)
    prepared = f.frame.copy(deep=True).drop(columns="Code").set_index("Date")
    oracle = canonical.stock_daily(f.request.security_id, prepared, ordinary_reference=ordinary)
    return f, ordinary, result, oracle


def test_every_stock_daily_field_matches_original_public_calculation(oracle_case: tuple[Fixture, bool, reader.CanonicalRead, canonical.StockDaily]) -> None:
    f, ordinary, result, oracle = oracle_case
    _assert_stock_equal(result.packet.stock, oracle)
    stock = result.packet.stock
    assert result.ordinary_reference is ordinary
    assert set(stock.labels) == set(stock.main_eligible) == set(canonical.LABELS)
    assert len(stock.labels) == 12 and set(stock.calendar_full) == set(canonical.HORIZONS)
    assert set(stock.atoms) == set(canonical.LOCAL_ATOMS) and "A4" not in stock.atoms
    assert stock.jump[len(f.frame) // 2]
    assert np.isfinite(stock.ret120).any()
    for horizon in canonical.HORIZONS:
        assert bool(stock.calendar_full[horizon].any()) is (horizon < len(f.frame))
        assert not stock.calendar_full[horizon][-1]
    assert not stock.eligible[:60].any()
    assert bool(stock.eligible.any()) is ordinary


def test_packet_metadata_is_explicit_and_preserves_original_record(oracle_case: tuple[Fixture, bool, reader.CanonicalRead, canonical.StockDaily]) -> None:
    f, _, result, _ = oracle_case
    packet = result.packet
    assert isinstance(packet, inputs.CanonicalPacket)
    assert packet.security_id == f.request.security_id
    assert packet.generation == f.request.generation
    assert packet.study_as_of == f.request.study_as_of > f.request.common_calendar[-1]
    assert packet.calendar.equals(f.request.common_calendar)
    assert packet.calendar is not f.request.common_calendar
    assert packet.calendar_id == f.request.calendar_id and packet.universe_id == f.request.universe_id
    assert packet.definition == "momentum-only.v1" and packet.basis == "reference_factor_adjusted"
    assert packet.availability_note == NOTE and packet.source.strip()
    for key in ("generation", "asof", "as_of", "file", "sha256", "status_sha256", "actions_sha256", "definition", "as_of_method"):
        assert result.source_record[key] == f.record[key]
    assert result.source_record["extra"]["notes"] == ("artificial retained metadata",)
    assert "source" in result.validation_scope.lower() and "interval" in result.validation_scope.lower()
    assert {field.name for field in fields(result)} == {"packet", "source_record", "ordinary_reference", "validation_scope"}


def test_empty_calendar_preserves_empty_original_calculation_without_inventing_sessions() -> None:
    f = _fixture(40)
    calendar = pd.DatetimeIndex([])
    frame = f.frame.iloc[:0].copy(deep=True)
    request = replace(f.request, common_calendar=calendar)
    f.record["calendar"] = {"source": "caller", "sessions": 0, "first": None, "last": None, "sha256": object_digest([])}
    result = _adapt(replace(f, request=request, frame=frame))
    oracle = canonical.stock_daily(request.security_id, frame.drop(columns="Code").set_index("Date"), ordinary_reference=True)
    _assert_stock_equal(result.packet.stock, oracle)
    assert result.packet.calendar.empty
    assert set(result.packet.stock.labels) == set(canonical.LABELS)
    assert all(values.size == 0 for values in result.packet.stock.labels.values())


@pytest.fixture
def no_calculation(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid declarations must fail before canonical calculation")

    monkeypatch.setattr(canonical, "stock_daily", forbidden)


@pytest.mark.parametrize("function_name", ["adapt_canonical_read", "load_canonical_packet"])
@pytest.mark.parametrize("argument", ["ordinary_reference", "availability_note"])
def test_ordinary_and_availability_are_required_without_defaults(function_name: str, argument: str, no_calculation: None) -> None:
    function = getattr(reader, function_name)
    assert inspect.signature(function).parameters[argument].default is inspect.Parameter.empty
    f = _fixture(40)
    kwargs: dict[str, Any] = {"ordinary_reference": True, "availability_note": NOTE}
    kwargs.pop(argument)
    with pytest.raises(TypeError):
        if function_name == "adapt_canonical_read":
            function(f.request, f.frame, f.record, **kwargs)
        else:
            function(f.request, root=Path("D:/artificial-root-not-opened"), **kwargs)


@pytest.mark.parametrize("value", [None, 0, 1, "true", np.bool_(True)])
def test_ordinary_reference_requires_exact_python_bool(value: object, no_calculation: None) -> None:
    f = _fixture(40)
    with pytest.raises(ValueError):
        reader.adapt_canonical_read(f.request, f.frame, f.record, ordinary_reference=cast(Any, value), availability_note=NOTE)


@pytest.mark.parametrize("value", [None, "", " ", 1])
def test_availability_note_requires_explicit_nonempty_text(value: object, no_calculation: None) -> None:
    f = _fixture(40)
    with pytest.raises(ValueError):
        reader.adapt_canonical_read(f.request, f.frame, f.record, ordinary_reference=True, availability_note=cast(Any, value))


@pytest.mark.parametrize("column", NUMERIC_COLUMNS)
@pytest.mark.parametrize("dtype", ["float32", "int64", "object", "Float64", ">f8"])
def test_every_numeric_input_requires_native_float64(column: str, dtype: str, no_calculation: None) -> None:
    f = _fixture(40)
    f.frame[column] = np.arange(len(f.frame), dtype=np.int64) if dtype == "int64" else f.frame[column].astype(dtype)
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize("column", ["Code", "Date", *NUMERIC_COLUMNS, "Quality", "quality_reason"])
def test_all_canonical_input_columns_are_required(column: str, no_calculation: None) -> None:
    f = _fixture(40)
    with pytest.raises(ValueError):
        _adapt(replace(f, frame=f.frame.drop(columns=column)))


@pytest.mark.parametrize("case", ["code", "missing_position", "duplicate_date", "duplicate_column", "reordered", "intraday", "timezone", "date_strings", "nat"])
def test_identity_and_original_calendar_positions_fail_closed(case: str, no_calculation: None) -> None:
    f = _fixture(40)
    frame = f.frame.copy(deep=True)
    if case == "code":
        frame.loc[3, "Code"] = "OTHER"
    elif case == "missing_position":
        frame = frame.drop(index=3)
    elif case == "duplicate_date":
        frame.loc[3, "Date"] = frame.loc[2, "Date"]
    elif case == "duplicate_column":
        frame = pd.concat((frame, frame[["Close"]]), axis=1)
    elif case == "reordered":
        frame = frame.iloc[::-1]
    elif case == "intraday":
        frame["Date"] = frame["Date"] + pd.Timedelta(hours=1)
    elif case == "timezone":
        frame["Date"] = pd.DatetimeIndex(frame["Date"]).tz_localize("UTC")
    elif case == "date_strings":
        frame["Date"] = frame["Date"].astype(str)
    else:
        frame.loc[3, "Date"] = pd.NaT
    with pytest.raises(ValueError):
        _adapt(replace(f, frame=frame))


@pytest.mark.parametrize("case", ["quality_int", "quality_nullable", "reason_nan", "reason_number", "duplicate_source"])
def test_quality_is_not_coerced_and_duplicate_source_is_not_silently_excluded(case: str, no_calculation: None) -> None:
    f = _fixture(40)
    if case == "quality_int":
        f.frame["Quality"] = f.frame["Quality"].astype(np.int64)
    elif case == "quality_nullable":
        f.frame["Quality"] = f.frame["Quality"].astype("boolean")
    else:
        f.frame.at[3, "quality_reason"] = {"reason_nan": np.nan, "reason_number": 1, "duplicate_source": "invalid_ohlc|duplicate_date"}[case]
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize(
    "field,value",
    [
        ("basis", "raw"),
        ("generation", "other-generation"),
        ("definition", "price-basis.v1"),
        ("as_of", "2017-01-01"),
        ("asof", "2017-01-01"),
        ("as_of_method", "other-method"),
        ("codes", 2),
        ("sha256", "invalid-digest"),
    ],
)
def test_source_record_must_describe_the_requested_adjusted_read(field: str, value: object, no_calculation: None) -> None:
    f = _fixture(40)
    f.record[field] = value
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize("field,value", [("source", "generation"), ("sessions", 39), ("sha256", "d" * 64)])
def test_calendar_record_is_verified_for_canonical_consumer(field: str, value: object, no_calculation: None) -> None:
    f = _fixture(40)
    f.record["calendar"][field] = value
    with pytest.raises(ValueError):
        _adapt(f)


def test_future_calendar_is_rejected_before_calculation(no_calculation: None) -> None:
    f = _fixture(40)
    cutoff = cast(pd.Timestamp, f.request.common_calendar[-2])
    f.record["as_of"] = cutoff.date().isoformat()
    with pytest.raises(ValueError):
        _adapt(replace(f, request=replace(f.request, study_as_of=cutoff)))


def test_original_calculation_is_called_once_on_a_detached_prepared_frame_with_false_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    f = _fixture(40)
    before = f.frame.copy(deep=True)
    calls: list[bool] = []

    def stock_daily(code: str, prepared: pd.DataFrame, *, ordinary_reference: bool) -> canonical.StockDaily:
        assert code == f.request.security_id
        pd.testing.assert_frame_equal(prepared, before.drop(columns="Code").set_index("Date"), check_exact=True)
        assert "Code" not in prepared.columns and "Date" not in prepared.columns
        calls.append(ordinary_reference)
        prepared.loc[prepared.index[1], "Close"] = -999.0
        prepared.loc[prepared.index[1], "quality_reason"] = "artificial callback mutation"
        return _stub_stock(code, len(prepared))

    monkeypatch.setattr(canonical, "stock_daily", stock_daily)
    result = _adapt(f, ordinary_reference=False)
    assert calls == [False]
    assert result.ordinary_reference is False
    pd.testing.assert_frame_equal(f.frame, before, check_exact=True)


@pytest.mark.parametrize("case", ["relative_root", "root_string", "missing_generation", "future_calendar", "ordinary_int", "empty_note"])
def test_invalid_loader_declarations_fail_before_any_source_read(case: str, monkeypatch: pytest.MonkeyPatch, no_calculation: None) -> None:
    f = _fixture(40)
    request = f.request
    kwargs: dict[str, Any] = {"root": Path("D:/artificial-root-not-opened"), "ordinary_reference": True, "availability_note": NOTE}
    if case == "relative_root":
        kwargs["root"] = Path("relative")
    elif case == "root_string":
        kwargs["root"] = "D:/artificial-root-not-opened"
    elif case == "missing_generation":
        request = replace(request, generation=" ")
    elif case == "future_calendar":
        request = replace(request, study_as_of=cast(pd.Timestamp, request.common_calendar[-2]))
    elif case == "ordinary_int":
        kwargs["ordinary_reference"] = 1
    else:
        kwargs["availability_note"] = " "

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid loader declaration must not reach source I/O")

    monkeypatch.setattr(maintained, "read_adjusted_daily", forbidden)
    with pytest.raises(ValueError):
        reader.load_canonical_packet(request, **kwargs)


def test_deterministic_real_calculation_immutable_inputs_and_no_source_files_database_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    f = _fixture(40)
    before_frame, before_record = f.frame.copy(deep=True), copy.deepcopy(f.record)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("canonical adaptation must use supplied frames without source I/O")

    with monkeypatch.context() as patch:
        for owner, name in [
            (maintained, "read_adjusted_daily"),
            (maintained, "read_official_quotes"),
            (maintained, "current_generation"),
            (canonical, "pr17_calendar"),
            (canonical, "pr17_codes"),
            (builtins, "open"),
            (Path, "open"),
            (Path, "read_bytes"),
            (Path, "read_text"),
            (Path, "write_bytes"),
            (Path, "write_text"),
            (sqlite3, "connect"),
            (socket, "create_connection"),
            (urllib.request, "urlopen"),
            (pd, "read_parquet"),
            (pd, "read_sql_query"),
        ]:
            patch.setattr(owner, name, forbidden)
        first, second = _adapt(f), _adapt(f)
    _assert_stock_equal(first.packet.stock, second.packet.stock)
    assert first.source_record == second.source_record
    pd.testing.assert_frame_equal(f.frame, before_frame, check_exact=True)
    assert f.record == before_record
    first_snapshot = first.packet.stock.ret120.copy()
    f.frame.loc[1, "Close"] = 999.0
    f.frame.loc[1, "quality_reason"] = "mutated later"
    f.record["extra"]["notes"].append("mutated later")
    f.record["calendar"]["sessions"] = 999
    np.testing.assert_array_equal(first.packet.stock.ret120, first_snapshot)
    assert first.source_record["extra"]["notes"] == ("artificial retained metadata",)
    assert first.source_record["calendar"]["sessions"] == 40
    with pytest.raises(TypeError):
        cast(Any, first.source_record["calendar"])["sessions"] = 1
    with pytest.raises(FrozenInstanceError):
        first.ordinary_reference = False  # type: ignore[misc]
