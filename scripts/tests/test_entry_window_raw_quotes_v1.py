"""Artificial frame/record boundaries only; no maintained generation is opened."""

from __future__ import annotations

import builtins
import copy
import logging
import socket
import sqlite3
import urllib.request
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd
import pytest

from research_core import entry_window_inputs_v1 as inputs
from research_core import entry_window_raw_quotes_v1 as raw_reader
from research_core import entry_window_v1 as entry
from research_core import momentum_only_v1 as canonical
from research_core.artifact_store import object_digest


@dataclass(frozen=True)
class Fixture:
    request: inputs.InputRequest
    frame: pd.DataFrame
    record: dict[str, Any]


class PacketIdentity(TypedDict):
    security_id: str
    generation: str
    study_as_of: pd.Timestamp
    calendar: pd.DatetimeIndex
    universe_id: str
    calendar_id: str
    source: str


def _date(value: str) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(value))


def _fixture() -> Fixture:
    calendar = pd.DatetimeIndex(["2018-12-28", "2018-12-29", "2018-12-31", "2019-01-02", "2019-01-03", "2019-01-04", "2019-01-07", "2019-01-08"])
    request = inputs.InputRequest(
        security_id="FAKE_A",
        generation="artificial-generation",
        study_as_of=_date("2019-01-10"),
        common_calendar=calendar,
        universe_id="artificial-universe",
        calendar_id="artificial-calendar",
    )
    frame = pd.DataFrame({
        "Code": pd.Series([request.security_id] * len(calendar), dtype=object),
        "Date": calendar,
        "RawOpen": np.array([np.nan, 10, 9.7, np.nan, 10.5, 0, -1, np.nan], dtype=np.float64),
        "RawHigh": np.array([np.nan, 11, 11, np.nan, np.inf, 11, 11, np.nan], dtype=np.float64),
        "RawLow": np.array([np.nan, 9, 9, np.nan, 9, 9, -1, np.nan], dtype=np.float64),
        "RawClose": np.array([np.nan, 10, 10, np.nan, 10, 10, 10, np.nan], dtype=np.float64),
        # Masked OHLC deliberately disagree with all available raw prices.
        "Open": np.full(len(calendar), np.nan),
        "High": np.full(len(calendar), np.nan),
        "Low": np.full(len(calendar), np.nan),
        "Close": np.full(len(calendar), np.nan),
        "Quality": np.array([False, True, False, False, False, False, False, False]),
        "quality_reason": pd.Series(
            [
                "missing_official_quote",
                "",
                "invalid_ohlc",
                "missing_official_quote",
                "invalid_ohlc|synthetic_other",
                "invalid_ohlc",
                "invalid_ohlc",
                "missing_official_quote",
            ],
            dtype=object,
        ),
    })
    days = [day.date().isoformat() for day in calendar]
    record: dict[str, Any] = {
        "family": "adjusted-daily-v1",
        "generation": request.generation,
        "asof": "2019-01-31",
        "basis": "raw",
        "file": "artificial-generation/raw.parquet; not opened",
        "sha256": "a" * 64,
        "status_sha256": "b" * 64,
        "as_of": "2019-01-10",
        "as_of_method": "price_basis.prepare_prices at as_of from the generation's raw quotes and actions snapshot",
        "definition": "price-basis.v2",
        "actions_sha256": "c" * 64,
        "calendar": {"source": "caller", "sessions": len(days), "first": days[0], "last": days[-1], "sha256": object_digest(days)},
        "codes": 1,
    }
    return Fixture(request, frame, record)


def _adapt(f: Fixture) -> raw_reader.RawQuoteRead:
    return raw_reader.adapt_raw_quote_read(f.request, f.frame, f.record)


def test_raw_prices_quality_and_original_calendar_are_retained_without_masking() -> None:
    f = _fixture()
    result = _adapt(f)
    packet = result.packet
    assert isinstance(packet, inputs.RawQuotePacket)
    assert packet.security_id == f.request.security_id
    assert packet.generation == f.request.generation
    assert packet.study_as_of == f.request.study_as_of > f.request.common_calendar[-1]
    assert packet.calendar.equals(f.request.common_calendar)
    assert cast(pd.Timestamp, packet.calendar[1]).dayofweek == 5
    assert packet.universe_id == f.request.universe_id and packet.calendar_id == f.request.calendar_id
    assert packet.basis == "raw" and packet.source.strip()
    for field, column in (("raw_open", "RawOpen"), ("raw_high", "RawHigh"), ("raw_low", "RawLow"), ("raw_close", "RawClose")):
        values = getattr(packet, field)
        np.testing.assert_array_equal(values, f.frame[column].to_numpy())
        assert values.dtype == np.dtype(np.float64) and values.dtype.isnative
        assert not values.flags.writeable
    assert packet.raw_open[2] == 9.7 and not result.quality[2]
    assert np.isnan(packet.raw_open[[0, 3, 7]]).all()
    assert np.isinf(packet.raw_high[4]) and packet.raw_open[5] == 0 and packet.raw_open[6] == -1
    np.testing.assert_array_equal(result.quality, f.frame["Quality"].to_numpy())
    assert not result.quality.flags.writeable
    assert result.quality_reason == tuple(f.frame["quality_reason"])
    assert result.source_record["asof"] == "2019-01-31"
    assert result.source_record["as_of"] == "2019-01-10"
    assert result.source_record["actions_sha256"] == "c" * 64
    assert result.source_record["as_of_method"] == f.record["as_of_method"]
    assert result.validation_scope and "source" in result.validation_scope.lower()
    assert {field.name for field in fields(result)} == {"packet", "quality", "quality_reason", "source_record", "validation_scope"}
    assert not any("interval" in field.name or "label" in field.name or "limit" in field.name for field in fields(packet))


@pytest.mark.parametrize("position", [0, 3, 7])
@pytest.mark.parametrize("reason", ["duplicate_date", "invalid_ohlc|duplicate_date", "duplicate_date|synthetic_other"])
def test_duplicate_date_reason_refuses_the_entire_read(position: int, reason: str) -> None:
    f = _fixture()
    f.frame.loc[position, "quality_reason"] = reason
    with pytest.raises(ValueError, match="duplicate_date"):
        _adapt(f)


def test_reason_none_and_unrelated_tokens_remain_separate_without_inventing_interval_quality() -> None:
    f = _fixture()
    f.frame.loc[1, "quality_reason"] = None
    f.frame.loc[2, "quality_reason"] = "not_duplicate_date|invalid_ohlc"
    result = _adapt(f)
    assert result.quality_reason[1] is None
    assert result.quality_reason[2] == "not_duplicate_date|invalid_ohlc"
    assert not result.quality[2]


@pytest.mark.parametrize("column", ["Code", "Date", "RawOpen", "RawHigh", "RawLow", "RawClose", "Quality", "quality_reason"])
def test_each_required_frame_column_must_be_explicit(column: str) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _adapt(replace(f, frame=f.frame.drop(columns=column)))


def test_masked_columns_are_not_required_or_substitutes_for_missing_raw_columns() -> None:
    f = _fixture()
    without_masked = f.frame.drop(columns=["Open", "High", "Low", "Close"])
    result = _adapt(replace(f, frame=without_masked))
    np.testing.assert_array_equal(result.packet.raw_open, f.frame["RawOpen"].to_numpy())
    with pytest.raises(ValueError):
        _adapt(replace(f, frame=f.frame.drop(columns="RawOpen")))


@pytest.mark.parametrize(
    "case", ["reversed", "missing_first", "missing_middle", "missing_last", "duplicate_date", "duplicate_column", "intraday", "timezone", "nat"]
)
def test_date_positions_must_match_the_calendar_without_reordering_or_filling(case: str) -> None:
    f = _fixture()
    frame = f.frame.copy(deep=True)
    if case == "reversed":
        frame = frame.iloc[::-1]
    elif case.startswith("missing"):
        position = {"missing_first": 0, "missing_middle": 3, "missing_last": 7}[case]
        frame = frame.drop(index=position)
    elif case == "duplicate_date":
        frame.loc[2, "Date"] = frame.loc[1, "Date"]
    elif case == "duplicate_column":
        frame = pd.concat((frame, frame[["RawOpen"]]), axis=1)
    elif case == "intraday":
        frame["Date"] = frame["Date"] + pd.Timedelta(hours=1)
    elif case == "timezone":
        frame["Date"] = pd.DatetimeIndex(frame["Date"]).tz_localize("UTC")
    else:
        frame.loc[3, "Date"] = pd.NaT
    with pytest.raises(ValueError):
        _adapt(replace(f, frame=frame))


@pytest.mark.parametrize("value", ["OTHER", None, 123])
def test_every_frame_row_requires_the_exact_security_id(value: object) -> None:
    f = _fixture()
    f.frame.loc[3, "Code"] = value
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize("column", ["RawOpen", "RawHigh", "RawLow", "RawClose"])
@pytest.mark.parametrize("dtype", ["float16", "float32", "int64", "object", "Float64", ">f8"])
def test_raw_prices_require_native_float64_and_never_cast(column: str, dtype: str) -> None:
    f = _fixture()
    f.frame[column] = np.arange(len(f.frame), dtype=np.int64) if dtype == "int64" else f.frame[column].astype(dtype)
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize("dtype", ["int64", "object", "boolean"])
def test_quality_requires_native_boolean_without_casting(dtype: str) -> None:
    f = _fixture()
    f.frame["Quality"] = f.frame["Quality"].astype(dtype)
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize("value", [1, np.nan, [], {}])
def test_quality_reason_does_not_silently_stringify_malformed_values(value: object) -> None:
    f = _fixture()
    f.frame.at[2, "quality_reason"] = value
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize(
    "field",
    ["family", "generation", "asof", "basis", "file", "sha256", "status_sha256", "as_of", "as_of_method", "definition", "actions_sha256", "calendar", "codes"],
)
def test_each_source_record_field_is_required(field: str) -> None:
    f = _fixture()
    f.record.pop(field)
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize(
    "field,value",
    [
        ("family", "other-family"),
        ("generation", "other-generation"),
        ("basis", "reference_factor_adjusted"),
        ("definition", "price-basis.v1"),
        ("as_of", "2019-01-09"),
        ("asof", "2019-01-09"),
        ("asof", "2019-01-31 12:00"),
        ("asof", None),
        ("file", " "),
        ("as_of_method", "some other reconstruction"),
        ("codes", 2),
        ("codes", True),
        ("codes", 1.0),
    ],
)
def test_record_identity_cutoff_definition_and_single_code_scope_are_checked(field: str, value: object) -> None:
    f = _fixture()
    f.record[field] = value
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize("field", ["sha256", "status_sha256", "actions_sha256"])
@pytest.mark.parametrize("value", ["", "A" * 64, "g" * 64, "a" * 63, None])
def test_source_digests_must_be_explicit_lowercase_sha256(field: str, value: object) -> None:
    f = _fixture()
    f.record[field] = value
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize(
    "field,value", [("source", "generation"), ("sessions", 7), ("sessions", True), ("first", "2018-12-29"), ("last", "2019-01-07"), ("sha256", "d" * 64)]
)
def test_calendar_record_checks_every_declared_dimension_and_digest(field: str, value: object) -> None:
    f = _fixture()
    f.record["calendar"][field] = value
    with pytest.raises(ValueError):
        _adapt(f)


@pytest.mark.parametrize("field", ["source", "sessions", "first", "last", "sha256"])
def test_calendar_record_cannot_omit_a_dimension(field: str) -> None:
    f = _fixture()
    f.record["calendar"].pop(field)
    with pytest.raises(ValueError):
        _adapt(f)


def test_future_calendar_is_rejected_even_if_frame_and_calendar_record_agree() -> None:
    f = _fixture()
    request = replace(f.request, study_as_of=_date("2019-01-07"))
    f.record["as_of"] = "2019-01-07"
    with pytest.raises(ValueError):
        _adapt(replace(f, request=request))


def test_adapter_borrows_no_frame_arrays_or_mutable_source_record_state() -> None:
    f = _fixture()
    original_frame, original_record = f.frame.copy(deep=True), copy.deepcopy(f.record)
    result = _adapt(f)
    again = _adapt(f)
    pd.testing.assert_frame_equal(f.frame, original_frame, check_exact=True)
    assert f.record == original_record
    assert result.source_record == again.source_record
    assert result.quality_reason == again.quality_reason
    assert result.packet.calendar.equals(again.packet.calendar)
    for name in ("raw_open", "raw_high", "raw_low", "raw_close"):
        np.testing.assert_array_equal(getattr(result.packet, name), getattr(again.packet, name))
    f.frame.loc[1, "RawOpen"] = 999.0
    f.frame.loc[1, "Quality"] = False
    f.frame.loc[1, "quality_reason"] = "mutated"
    f.record["calendar"]["sessions"] = 999
    f.record["generation"] = "mutated-generation"
    assert result.packet.raw_open[1] == 10.0 and result.quality[1]
    assert result.quality_reason[1] == ""
    assert result.source_record["calendar"]["sessions"] == 8
    assert result.source_record["generation"] == "artificial-generation"
    with pytest.raises(TypeError):
        cast(Any, result.source_record)["generation"] = "injected"
    with pytest.raises(TypeError):
        cast(Any, result.source_record["calendar"])["sessions"] = 1
    with pytest.raises(FrozenInstanceError):
        result.validation_scope = "injected"  # type: ignore[misc]


def test_public_request_validation_is_available_without_changing_legacy_staging_semantics() -> None:
    f = _fixture()
    inputs.validate_input_request(f.request)
    with pytest.raises(ValueError):
        inputs.validate_input_request(replace(f.request, generation=" "))
    # InputRequest historically permits a calendar beyond its cutoff. The new
    # raw adapter alone imposes the maintained-reader cutoff boundary.
    old_boundary = replace(f.request, study_as_of=_date("2019-01-07"))
    inputs.validate_input_request(old_boundary)


def test_adapted_packet_stages_and_counts_like_manually_constructed_b1_quotes() -> None:
    f = _fixture()
    result = _adapt(f)
    n = len(f.request.common_calendar)
    stock = canonical.StockDaily(
        f.request.security_id,
        "artificial",
        np.ones(n, dtype=bool),
        np.zeros(n, dtype=bool),
        np.zeros(n, dtype=bool),
        {atom: np.ones(n, dtype=np.int8) for atom in ("A1", "A2", "A3")},
        np.full(n, np.nan, dtype=np.float64),
        {label: np.array([1, 2, 3, 0, 1, 2, 1, 0], dtype=np.int8) for label in canonical.LABELS},
        {label: np.array([True, True, True, False, True, True, True, False]) for label in canonical.LABELS},
        {horizon: np.array([True, True, True, True, True, True, True, False]) for horizon in canonical.HORIZONS},
    )
    identity: PacketIdentity = {
        "security_id": f.request.security_id,
        "generation": f.request.generation,
        "study_as_of": f.request.study_as_of,
        "calendar": f.request.common_calendar,
        "universe_id": f.request.universe_id,
        "calendar_id": f.request.calendar_id,
        "source": "artificial independent canonical/whole-interval evidence",
    }
    canonical_packet = inputs.CanonicalPacket(
        **identity,
        stock=stock,
        definition="momentum-only.v1",
        basis="reference_factor_adjusted",
        availability_note="All canonical labels hand supplied; no PIT claim",
    )
    interval_packet = inputs.IntervalPacket(
        **identity,
        action_to_next=np.zeros(n, dtype=np.int8),
        event_quality_to_next=np.ones(n, dtype=np.int8),
        quote_quality_to_next=np.ones(n, dtype=np.int8),
        event_coverage=np.ones(n, dtype=np.int8),
        coverage_note="Explicit synthetic whole-interval coverage; not inferred from raw daily quality",
    )
    staged = inputs.stage_stock_inputs(f.request, canonical=canonical_packet, raw=result.packet, intervals=interval_packet)
    direct = entry.Quotes(
        f.request.security_id,
        f.request.common_calendar,
        f.frame["RawOpen"].to_numpy(),
        f.frame["RawHigh"].to_numpy(),
        f.frame["RawLow"].to_numpy(),
        f.frame["RawClose"].to_numpy(),
        interval_packet.action_to_next,
        interval_packet.event_quality_to_next,
        interval_packet.quote_quality_to_next,
    )
    actual = entry.count_stock(staged.calendar, staged.stock, staged.quotes)
    assert actual == entry.count_stock(f.request.common_calendar, stock, direct)
    masks = entry.classify_quotes(staged.calendar, staged.quotes)
    assert masks.quote_known.tolist() == [False, True, False, False, False, False, False, False]
    assert masks.bands["B01"].accepted[1]
    assert not result.quality[2] and masks.quote_known[1]
    assert masks.primary_reason[2] == "no_open" and masks.primary_reason[-1] == "no_next_session"
    assert actual.rows and actual.diagnostics


def test_pure_adapter_never_calls_sources_files_database_network_logging_or_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import maintained_adjusted_daily as maintained

    f = _fixture()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("pure raw adapter must not call I/O, logging callbacks, or label constructors")

    with monkeypatch.context() as patch:
        logger = logging.getLogger(raw_reader.__name__)
        patch.setattr(logger, "level", logging.DEBUG)
        patch.setattr(logger, "_cache", {})
        patch.setattr(logging.Logger, "_log", forbidden)
        assert logger.isEnabledFor(logging.DEBUG)
        for owner, name in [
            (maintained, "read_adjusted_daily"),
            (maintained, "read_official_quotes"),
            (maintained, "current_generation"),
            (canonical, "stock_daily"),
            (canonical, "outcomes_for_targets"),
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
        assert _adapt(f).packet.raw_open[2] == 9.7
