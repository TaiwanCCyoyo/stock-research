"""Artificial packets only: no labels calculated and no real sources loaded."""

from __future__ import annotations

import builtins
import socket
import sqlite3
import urllib.request
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd
import pytest

from research_core import entry_window_inputs_v1 as staging
from research_core import entry_window_v1 as entry
from research_core import momentum_only_v1 as canonical


@dataclass(frozen=True)
class Fixture:
    request: staging.InputRequest
    canonical: staging.CanonicalPacket
    raw: staging.RawQuotePacket
    intervals: staging.IntervalPacket
    limits: staging.OfficialLimitsPacket


class PacketIdentity(TypedDict):
    security_id: str
    generation: str
    study_as_of: pd.Timestamp
    universe_id: str
    calendar_id: str
    calendar: pd.DatetimeIndex
    source: str


def _changes(name: str, value: object) -> dict[str, Any]:
    """Deliberately inject malformed fields in runtime validation tests."""
    return {name: value}


def _fixture() -> Fixture:
    calendar = pd.DatetimeIndex(["2018-12-28", "2018-12-29", "2019-01-02", "2019-01-03", "2019-01-04"])
    n = len(calendar)
    request = staging.InputRequest(
        security_id="synthetic-A",
        generation="synthetic-G",
        study_as_of=cast(pd.Timestamp, pd.Timestamp("2019-01-04")),
        universe_id="synthetic-universe",
        calendar_id="synthetic-calendar",
        common_calendar=calendar,
    )
    packet_identity: PacketIdentity = {
        "security_id": request.security_id,
        "generation": request.generation,
        "study_as_of": request.study_as_of,
        "universe_id": request.universe_id,
        "calendar_id": request.calendar_id,
        "calendar": calendar,
        "source": "artificial fixture; no real data",
    }
    # Every horizon/target is supplied by hand, including the nine non-E1 labels.
    # The final hit is censored; position 3 is a full-window unknown.
    stock = canonical.StockDaily(
        "synthetic-A",
        "synthetic",
        np.ones(n, dtype=bool),
        np.zeros(n, dtype=bool),
        np.zeros(n, dtype=bool),
        {atom: np.ones(n, dtype=np.int8) for atom in ("A1", "A2", "A3", "A5")},
        np.full(n, np.nan, dtype=np.float64),
        {label: np.array([1, 2, 3, 0, 1], dtype=np.int8) for label in canonical.LABELS},
        {label: np.array([True, True, True, False, False]) for label in canonical.LABELS},
        {horizon: np.array([True, True, True, True, False]) for horizon in canonical.HORIZONS},
    )
    return Fixture(
        request,
        staging.CanonicalPacket(
            **packet_identity, stock=stock, definition="momentum-only.v1", basis="reference_factor_adjusted", availability_note="synthetic only; no PIT proof"
        ),
        staging.RawQuotePacket(
            **packet_identity,
            basis="raw",
            raw_open=np.array([10, np.nan, 9.7, 10, 10], dtype=np.float64),
            raw_high=np.full(n, 11.0),
            raw_low=np.full(n, 9.0),
            raw_close=np.full(n, 10.0),
        ),
        staging.IntervalPacket(
            **packet_identity,
            action_to_next=np.zeros(n, dtype=np.int8),
            event_quality_to_next=np.ones(n, dtype=np.int8),
            quote_quality_to_next=np.ones(n, dtype=np.int8),
            event_coverage=np.ones(n, dtype=np.int8),
            coverage_note="whole intervals explicitly covered by fixture",
        ),
        staging.OfficialLimitsPacket(**packet_identity, basis="raw", lower=np.full(n, 9.0), upper=np.full(n, 11.0), quality=np.ones(n, dtype=np.int8)),
    )


def _stage(f: Fixture, *, with_limits: bool = False) -> staging.StagedInputs:
    return staging.stage_stock_inputs(f.request, canonical=f.canonical, raw=f.raw, intervals=f.intervals, limits=f.limits if with_limits else None)


def _direct_quotes(f: Fixture, *, with_limits: bool = False) -> entry.Quotes:
    limits = entry.OfficialLimits(f.limits.source, f.limits.lower, f.limits.upper, f.limits.quality) if with_limits else None
    return entry.Quotes(
        f.request.security_id,
        f.request.common_calendar,
        f.raw.raw_open,
        f.raw.raw_high,
        f.raw.raw_low,
        f.raw.raw_close,
        f.intervals.action_to_next,
        f.intervals.event_quality_to_next,
        f.intervals.quote_quality_to_next,
        limits,
    )


def _arrays(f: Fixture) -> list[np.ndarray]:
    stock = f.canonical.stock
    return [
        stock.eligible,
        stock.jump,
        stock.c52w,
        stock.ret120,
        *stock.atoms.values(),
        *stock.labels.values(),
        *stock.main_eligible.values(),
        *stock.calendar_full.values(),
        f.raw.raw_open,
        f.raw.raw_high,
        f.raw.raw_low,
        f.raw.raw_close,
        f.intervals.action_to_next,
        f.intervals.event_quality_to_next,
        f.intervals.quote_quality_to_next,
        f.intervals.event_coverage,
        f.limits.lower,
        f.limits.upper,
        f.limits.quality,
    ]


@pytest.mark.parametrize("with_limits", [False, True])
def test_stage_matches_all_direct_b1_counts_and_diagnostics_without_mutation(with_limits: bool) -> None:
    f = _fixture()
    arrays = _arrays(f)
    before = [a.copy() for a in arrays]
    dates_before = [p.calendar.copy() for p in (f.canonical, f.raw, f.intervals, f.limits)]
    for array in arrays:
        array.flags.writeable = False
    staged = _stage(f, with_limits=with_limits)
    counted = entry.count_stock(staged.calendar, staged.stock, staged.quotes)
    assert counted == entry.count_stock(f.request.common_calendar, f.canonical.stock, _direct_quotes(f, with_limits=with_limits))
    assert staged.stock is f.canonical.stock
    assert staged.calendar is f.request.common_calendar
    assert staged.quotes.raw_open is f.raw.raw_open
    assert set(staged.stock.labels) == set(canonical.LABELS)
    for actual, expected in zip(arrays, before, strict=True):
        np.testing.assert_array_equal(actual, expected)
        assert not actual.flags.writeable
    for packet, expected in zip((f.canonical, f.raw, f.intervals, f.limits), dates_before, strict=True):
        assert packet.calendar.equals(expected)
    for row in counted.rows:
        event, known, hit, loss, flat, unknown, censored, full_unknown = row.counts
        assert event == known + full_unknown + censored
        assert known == hit + loss + flat
        assert full_unknown <= unknown <= full_unknown + censored
    all_daily = [r for r in counted.rows if r.set_id == "CORE" and r.cadence == "daily" and r.arm == "S" and r.label == (126, 2.0)]
    assert {r.t0_year: r.counts for r in all_daily} == {2018: (2, 2, 1, 1, 0, 0, 0, 0), 2019: (3, 1, 0, 0, 1, 1, 1, 1)}


def test_fixed_next_position_missing_middle_saturday_and_last_row() -> None:
    f = _fixture()
    staged = _stage(f)
    masks = entry.classify_quotes(staged.calendar, staged.quotes)
    assert cast(pd.Timestamp, staged.calendar[1]).dayofweek == 5  # An explicit Saturday is retained.
    assert masks.primary_reason == ("no_open", None, None, None, "no_next_session")
    assert masks.quote_known.tolist() == [False, True, True, True, False]
    assert masks.bands["B01"].accepted[1]  # float64 10 * .97 == 9.7
    assert not masks.bands["B04"].accepted[1]
    assert np.isnan(staged.quotes.raw_open[1])


@pytest.mark.parametrize("packet_name", ["canonical", "raw", "intervals", "limits"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("security_id", "synthetic-B"),
        ("generation", "other-G"),
        ("study_as_of", pd.Timestamp("2019-01-03")),
        ("universe_id", "other-universe"),
        ("calendar_id", "other-calendar"),
        ("source", " "),
    ],
)
def test_packet_identity_and_source_fail_closed(packet_name: str, field: str, value: object) -> None:
    f = _fixture()
    changed = replace(getattr(f, packet_name), **_changes(field, value))
    with pytest.raises(ValueError):
        _stage(replace(f, **{packet_name: changed}), with_limits=True)


@pytest.mark.parametrize("packet_name", ["canonical", "raw", "intervals", "limits"])
@pytest.mark.parametrize("case", ["shifted", "reversed", "duplicate", "intraday", "timezone", "nat", "short"])
def test_exact_calendar_rejects_same_length_mismatch_and_malformed_dates(packet_name: str, case: str) -> None:
    f = _fixture()
    dates = f.request.common_calendar
    alternatives = {
        "shifted": dates + pd.Timedelta(days=1),
        "reversed": dates[::-1],
        "duplicate": pd.DatetimeIndex([dates[0], dates[0], *dates[2:]]),
        "intraday": dates + pd.Timedelta(hours=1),
        "timezone": dates.tz_localize("UTC"),
        "nat": pd.DatetimeIndex([pd.NaT, *dates[1:]]),
        "short": dates[:-1],
    }
    with pytest.raises(ValueError):
        _stage(replace(f, **{packet_name: replace(getattr(f, packet_name), calendar=alternatives[case])}), with_limits=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("security_id", ""),
        ("generation", " "),
        ("universe_id", ""),
        ("calendar_id", ""),
        ("study_as_of", pd.NaT),
        ("study_as_of", pd.Timestamp("2019-01-04 12:00")),
        ("study_as_of", pd.Timestamp("2019-01-04", tz="UTC")),
        ("common_calendar", pd.DatetimeIndex(["2019-01-02", "2019-01-01"])),
    ],
)
def test_request_metadata_is_explicit(field: str, value: object) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _stage(replace(f, request=replace(f.request, **_changes(field, value))))


@pytest.mark.parametrize(
    "packet_name,field,value",
    [
        ("canonical", "basis", "raw"),
        ("canonical", "definition", "momentum-only.v2"),
        ("canonical", "availability_note", ""),
        ("raw", "basis", "reference_factor_adjusted"),
        ("intervals", "coverage_note", ""),
        ("limits", "basis", "reference_factor_adjusted"),
    ],
)
def test_basis_definition_and_notes_are_checked_per_role(packet_name: str, field: str, value: str) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _stage(replace(f, **{packet_name: replace(getattr(f, packet_name), **_changes(field, value))}), with_limits=True)


@pytest.mark.parametrize("mapping", ["labels", "main_eligible", "calendar_full", "atoms"])
def test_all_canonical_keys_required_without_synthesizing_missing_labels(mapping: str) -> None:
    f = _fixture()
    data = dict(getattr(f.canonical.stock, mapping))
    # (252, 10x) is outside all three E1 labels but public group_counts needs it.
    key = (252, 10.0) if mapping in ("labels", "main_eligible") else 252 if mapping == "calendar_full" else "A3"
    data.pop(key)
    stock = replace(f.canonical.stock, **_changes(mapping, data))
    with pytest.raises(ValueError):
        _stage(replace(f, canonical=replace(f.canonical, stock=stock)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("code", "synthetic-B"),
        ("eligible", np.ones(4, dtype=bool)),
        ("jump", np.ones(5, dtype=np.int8)),
        ("c52w", np.ones((5, 1), dtype=bool)),
        ("ret120", np.ones(5, dtype=np.int32)),
        ("atoms", {"A1": np.full(5, 2, dtype=np.int8), "A2": np.ones(5, dtype=np.int8), "A3": np.ones(5, dtype=np.int8)}),
    ],
)
def test_canonical_stock_shape_state_and_identity_fail_closed(field: str, value: object) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _stage(replace(f, canonical=replace(f.canonical, stock=replace(f.canonical.stock, **_changes(field, value)))))


@pytest.mark.parametrize("mapping", ["labels", "main_eligible", "calendar_full"])
def test_canonical_values_have_full_shape_dtype_and_enum_checks(mapping: str) -> None:
    f = _fixture()
    data = dict(getattr(f.canonical.stock, mapping))
    key = next(iter(data))
    data[key] = np.full(5, 4, dtype=np.int8) if mapping == "labels" else np.ones(4, dtype=bool)
    with pytest.raises(ValueError):
        _stage(replace(f, canonical=replace(f.canonical, stock=replace(f.canonical.stock, **_changes(mapping, data)))))


@pytest.mark.parametrize(
    "packet_name,field", [("raw", name) for name in ("raw_open", "raw_high", "raw_low", "raw_close")] + [("limits", "lower"), ("limits", "upper")]
)
@pytest.mark.parametrize(
    "bad",
    [
        np.ones(5, dtype=np.float32),
        np.ones(5, dtype=np.int64),
        np.ones(4, dtype=np.float64),
        np.ones((5, 1), dtype=np.float64),
        np.array([10.0, np.float32(9.7), 10.0, 10.0, 10.0], dtype=object),
    ],
)
def test_raw_and_official_bounds_never_cast_bad_or_mixed_precision(packet_name: str, field: str, bad: np.ndarray) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _stage(replace(f, **{packet_name: replace(getattr(f, packet_name), **_changes(field, bad))}), with_limits=True)


@pytest.mark.parametrize("field", ["action_to_next", "event_quality_to_next", "quote_quality_to_next", "event_coverage"])
@pytest.mark.parametrize("bad", [np.full(5, 2, dtype=np.int8), np.ones(4, dtype=np.int8), np.ones(5, dtype=np.float64)])
def test_interval_states_validate_enum_shape_and_dtype(field: str, bad: np.ndarray) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _stage(replace(f, intervals=replace(f.intervals, **_changes(field, bad))))


def test_event_coverage_requires_int8() -> None:
    f = _fixture()
    with pytest.raises(ValueError, match="event_coverage.*int8"):
        _stage(replace(f, intervals=replace(f.intervals, event_coverage=np.ones(5, dtype=np.int64))))


@pytest.mark.parametrize("bad", [np.full(5, 2, dtype=np.int8), np.ones(4, dtype=np.int8), np.ones(5, dtype=np.float64)])
def test_official_quality_requires_aligned_tristates(bad: np.ndarray) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _stage(replace(f, limits=replace(f.limits, quality=bad)), with_limits=True)


@pytest.mark.parametrize("coverage", [-1, 0])
@pytest.mark.parametrize("action,quality", [(0, -1), (-1, 1), (1, 1)])
def test_claims_of_no_action_or_good_event_quality_require_full_coverage(coverage: int, action: int, quality: int) -> None:
    f = _fixture()
    changed = replace(
        f.intervals,
        action_to_next=np.full(5, action, dtype=np.int8),
        event_quality_to_next=np.full(5, quality, dtype=np.int8),
        event_coverage=np.full(5, coverage, dtype=np.int8),
    )
    with pytest.raises(ValueError, match="event_coverage=1"):
        _stage(replace(f, intervals=changed))


def test_interval_at_t_is_not_shifted_and_event_survives_incomplete_coverage() -> None:
    f = _fixture()
    changed = replace(
        f.intervals,
        action_to_next=np.array([0, 1, 0, -1, 1], dtype=np.int8),
        event_quality_to_next=np.array([1, -1, 1, -1, 1], dtype=np.int8),
        event_coverage=np.array([1, 0, 1, -1, -1], dtype=np.int8),
    )
    staged = _stage(replace(f, intervals=changed))
    masks = entry.classify_quotes(staged.calendar, staged.quotes)
    assert masks.clean.tolist() == [False, False, True, False, False]
    assert masks.reasons["corporate_action"].tolist() == [False, True, False, False, True]
    assert staged.quotes.action_to_next[3] == -1
    assert changed.event_coverage.tolist() == [1, 0, 1, -1, -1]
    assert masks.primary_reason[-1] == "no_next_session"  # Terminal states never create t1.


@pytest.mark.parametrize("quote_quality", [-1, 0])
def test_no_open_unknown_event_and_bad_quality_keep_overlapping_reasons_and_deduplicate(quote_quality: int) -> None:
    f = _fixture()
    changed = replace(
        f.intervals,
        action_to_next=np.array([-1, 0, 0, 0, 0], dtype=np.int8),
        event_quality_to_next=np.array([-1, 1, 1, 1, 1], dtype=np.int8),
        event_coverage=np.array([-1, 1, 1, 1, 1], dtype=np.int8),
        quote_quality_to_next=np.array([quote_quality, 1, 1, 1, 1], dtype=np.int8),
    )
    staged = _stage(replace(f, intervals=changed))
    counted = entry.count_stock(staged.calendar, staged.stock, staged.quotes)
    diagnostic = next(r.counts for r in counted.diagnostics if r.set_id == "CORE" and r.cadence == "daily" and r.t0_year == 2018)
    assert diagnostic["S"] == 2 and diagnostic["Q"] == diagnostic["M"] == 1
    assert diagnostic["S_minus_Q"] == 1 and diagnostic["Q_minus_M"] == 0
    assert diagnostic["reason:no_open"] == diagnostic["reason:corporate_action_unknown"] == diagnostic["reason:event_quality_unknown"] == 1
    assert diagnostic[f"reason:quote_quality_{'unknown' if quote_quality == -1 else 'invalid'}"] == 1


@pytest.mark.parametrize("quality", [-1, 0])
def test_known_quote_with_multiple_quality_failures_excludes_m_once(quality: int) -> None:
    f = _fixture()
    changed = replace(
        f.intervals,
        action_to_next=np.array([0, 0, 1, 0, 0], dtype=np.int8),
        event_quality_to_next=np.array([1, 1, quality, 1, 1], dtype=np.int8),
        quote_quality_to_next=np.array([1, 1, quality, 1, 1], dtype=np.int8),
    )
    staged = _stage(replace(f, intervals=changed))
    counted = entry.count_stock(staged.calendar, staged.stock, staged.quotes)
    diagnostic = next(r.counts for r in counted.diagnostics if r.set_id == "CORE" and r.cadence == "daily" and r.t0_year == 2019)
    assert diagnostic["S"] == 3 and diagnostic["Q"] == 2 and diagnostic["M"] == 1
    assert diagnostic["Q_minus_M"] == 1
    assert diagnostic["reason:corporate_action"] == 1
    assert diagnostic[f"reason:event_quality_{'unknown' if quality == -1 else 'invalid'}"] == 1
    assert diagnostic[f"reason:quote_quality_{'unknown' if quality == -1 else 'invalid'}"] == 1


def test_official_limits_use_quote_session_while_intervals_use_signal_session() -> None:
    f = _fixture()
    upper = np.array([11.0, 11.0, 9.7, 11.0, 11.0], dtype=np.float64)
    staged = _stage(replace(f, limits=replace(f.limits, upper=upper)), with_limits=True)
    masks = entry.classify_quotes(staged.calendar, staged.quotes)
    assert masks.limit_status == ("unknown", "at_upper", "inside", "inside", "unknown")


@pytest.mark.parametrize("missing", [np.nan, 0.0, -1.0, np.inf])
def test_float64_bad_values_remain_for_b1_diagnostics(missing: float) -> None:
    f = _fixture()
    values = np.full(5, missing, dtype=np.float64)
    staged = _stage(replace(f, raw=replace(f.raw, raw_close=values)))
    np.testing.assert_array_equal(staged.quotes.raw_close, values)
    masks = entry.classify_quotes(staged.calendar, staged.quotes)
    assert not masks.quote_known.any()
    assert masks.reasons["invalid_raw_close"].all()


def test_official_limits_missing_unknown_and_one_price_do_not_imply_fill_or_change_q_m() -> None:
    f = _fixture()
    bars = np.full(5, 10.0)
    f = replace(f, raw=replace(f.raw, raw_open=bars, raw_high=bars, raw_low=bars, raw_close=bars))
    without = _stage(f)
    unknown = _stage(replace(f, limits=replace(f.limits, quality=np.full(5, -1, dtype=np.int8))), with_limits=True)
    a = entry.classify_quotes(without.calendar, without.quotes)
    b = entry.classify_quotes(unknown.calendar, unknown.quotes)
    np.testing.assert_array_equal(a.quote_known, b.quote_known)
    np.testing.assert_array_equal(a.clean, b.clean)
    assert a.one_price.tolist() == [1, 1, 1, 1, -1]
    assert a.limit_status == b.limit_status == ("unknown",) * 5
    assert a.bands["B04"].range_touch.tolist() == [1, 1, 1, 1, -1]
    assert not any("filled" in field.name or "executable" in field.name for value in (without, without.quotes, a) for field in fields(value))
    assert all(value is None or isinstance(value, (str, int)) for value in without.alignment_record.values())
    assert without.alignment_record["canonical_basis"] == "reference_factor_adjusted"
    assert without.alignment_record["raw_basis"] == "raw"
    assert without.alignment_record["generation"] == f.request.generation


def test_staging_and_public_b1_count_work_when_readers_labels_files_database_and_network_are_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import maintained_adjusted_daily as maintained

    f = _fixture()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("in-memory staging must not call source I/O or calculate labels")

    with monkeypatch.context() as patch:
        for owner, name in [
            (maintained, "read_adjusted_daily"),
            (maintained, "read_official_quotes"),
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
        staged = _stage(f, with_limits=True)
        assert entry.count_stock(staged.calendar, staged.stock, staged.quotes).rows
