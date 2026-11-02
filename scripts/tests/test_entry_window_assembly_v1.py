"""Independent artificial packets for the pure E1 study assembly boundary."""

from __future__ import annotations

import builtins
import json
import socket
import sqlite3
import urllib.request
from collections import Counter
from dataclasses import FrozenInstanceError, asdict, dataclass, replace
from pathlib import Path
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd
import pytest

from research_core import entry_window_assembly_v1 as assembly
from research_core import entry_window_bootstrap_v1 as bootstrap
from research_core import entry_window_inputs_v1 as staging
from research_core import entry_window_v1 as entry
from research_core import momentum_only_v1 as canonical


@dataclass(frozen=True)
class Fixture:
    request: assembly.AssemblyRequest
    packets: tuple[assembly.StockPackets, ...]


class PacketIdentity(TypedDict):
    security_id: str
    generation: str
    study_as_of: pd.Timestamp
    universe_id: str
    calendar_id: str
    calendar: pd.DatetimeIndex
    source: str


def _changes(field: str, value: object) -> dict[str, Any]:
    """Allow deliberately malformed runtime values without weakening the API."""
    return {field: value}


def _fixture() -> Fixture:
    # A deliberately sparse common calendar: cooling counts sessions, not years.
    calendar = pd.DatetimeIndex(["2010-12-30", "2010-12-31", "2011-01-03", "2012-12-31", "2013-01-02", "2018-12-28", "2018-12-31", "2019-01-02", "2020-01-02"])
    request = assembly.AssemblyRequest(
        codes=("FAKE_A", "FAKE_ZERO"),
        generation="artificial-generation",
        study_as_of=cast(pd.Timestamp, pd.Timestamp("2020-01-02")),
        common_calendar=calendar,
        universe_id="artificial-universe",
        calendar_id="artificial-calendar",
    )
    packets = []
    for code in request.codes:
        n = len(calendar)
        active = code == "FAKE_A"
        input_request = staging.InputRequest(
            security_id=code,
            generation=request.generation,
            study_as_of=request.study_as_of,
            common_calendar=calendar,
            universe_id=request.universe_id,
            calendar_id=request.calendar_id,
        )
        identity: PacketIdentity = {
            "security_id": code,
            "generation": request.generation,
            "study_as_of": request.study_as_of,
            "calendar": calendar,
            "universe_id": request.universe_id,
            "calendar_id": request.calendar_id,
            "source": f"artificial source for {code}; no real data",
        }
        # All canonical labels are supplied by hand, including non-E1 targets.
        # Position 3 is full-window unknown; positions 7/8 are censored.
        stock = canonical.StockDaily(
            code,
            "artificial",
            np.full(n, active, dtype=bool),
            np.zeros(n, dtype=bool),
            np.zeros(n, dtype=bool),
            {atom: np.ones(n, dtype=np.int8) for atom in ("A1", "A2", "A3")},
            np.full(n, np.nan, dtype=np.float64),
            {label: np.array([1, 2, 3, 0, 1, 2, 1, 1, 0], dtype=np.int8) for label in canonical.LABELS},
            {label: np.array([True, True, True, False, True, True, True, False, False]) for label in canonical.LABELS},
            {horizon: np.array([True, True, True, True, True, True, True, False, False]) for horizon in canonical.HORIZONS},
        )
        limits = staging.OfficialLimitsPacket(**identity, basis="raw", lower=np.full(n, 9.0), upper=np.full(n, 11.0), quality=np.ones(n, dtype=np.int8))
        packets.append(
            assembly.StockPackets(
                request=input_request,
                canonical=staging.CanonicalPacket(
                    **identity,
                    stock=stock,
                    definition="momentum-only.v1",
                    basis="reference_factor_adjusted",
                    availability_note="artificial labels, no historical PIT claim",
                ),
                raw=staging.RawQuotePacket(
                    **identity,
                    basis="raw",
                    raw_open=np.array([10, np.nan, 9.6, 10.4, 10, 10, 10, 10, 10], dtype=np.float64),
                    raw_high=np.full(n, 11.0),
                    raw_low=np.full(n, 9.0),
                    raw_close=np.full(n, 10.0),
                ),
                intervals=staging.IntervalPacket(
                    **identity,
                    action_to_next=np.array([0, 0, 0, 1, 0, 0, 0, 0, 0], dtype=np.int8),
                    event_quality_to_next=np.ones(n, dtype=np.int8),
                    quote_quality_to_next=np.ones(n, dtype=np.int8),
                    event_coverage=np.ones(n, dtype=np.int8),
                    coverage_note="explicit artificial whole-interval coverage",
                ),
                limits=limits if active else None,
            )
        )
    return Fixture(request, tuple(packets))


def _direct_quotes(packet: assembly.StockPackets) -> entry.Quotes:
    limits = packet.limits
    official = None if limits is None else entry.OfficialLimits(limits.source, limits.lower, limits.upper, limits.quality)
    return entry.Quotes(
        packet.request.security_id,
        packet.request.common_calendar,
        packet.raw.raw_open,
        packet.raw.raw_high,
        packet.raw.raw_low,
        packet.raw.raw_close,
        packet.intervals.action_to_next,
        packet.intervals.event_quality_to_next,
        packet.intervals.quote_quality_to_next,
        official,
    )


def _arrays(packet: assembly.StockPackets) -> list[np.ndarray]:
    stock = packet.canonical.stock
    arrays = [
        stock.eligible,
        stock.jump,
        stock.c52w,
        stock.ret120,
        *stock.atoms.values(),
        *stock.labels.values(),
        *stock.main_eligible.values(),
        *stock.calendar_full.values(),
        packet.raw.raw_open,
        packet.raw.raw_high,
        packet.raw.raw_low,
        packet.raw.raw_close,
        packet.intervals.action_to_next,
        packet.intervals.event_quality_to_next,
        packet.intervals.quote_quality_to_next,
        packet.intervals.event_coverage,
    ]
    if packet.limits is not None:
        arrays.extend((packet.limits.lower, packet.limits.upper, packet.limits.quality))
    return arrays


@pytest.fixture(scope="module")
def assembled() -> tuple[Fixture, assembly.StudyAssembly]:
    f = _fixture()
    return f, assembly.assemble_study(f.request, f.packets, reps=5)


def test_complete_rows_diagnostics_and_rates_match_public_b1_oracle(assembled: tuple[Fixture, assembly.StudyAssembly]) -> None:
    f, result = assembled
    direct = [entry.count_stock(f.request.common_calendar, packet.canonical.stock, _direct_quotes(packet)) for packet in f.packets]
    assert result.rows == tuple(row for counts in direct for row in counts.rows)
    assert result.diagnostics == tuple(row for counts in direct for row in counts.diagnostics)
    expected = entry.aggregate_rows(row for counts in direct for row in counts.rows)
    assert dict(result.summaries) == expected
    assert len(result.comparisons) == 288
    assert len(result.intervals) == 5760
    assert [(c.era, c.cell_id, c.cadence) for c in result.comparisons] == [
        (era, cell.cell_id, cadence) for era in entry.ERAS for cell in entry.COMPARISONS for cadence in entry.CADENCES
    ]
    for comparison in result.comparisons:
        cell = next(cell for cell in entry.COMPARISONS if cell.cell_id == comparison.cell_id)
        assert (comparison.primary, comparison.set_id, comparison.band_id, comparison.label) == (cell.primary, cell.set_id, cell.band_id, cell.label)
        assert dict(comparison.rates) == entry.comparison_rates(expected, cell, comparison.cadence, comparison.era)
        assert tuple(comparison.rates) == bootstrap.STATISTICS


def test_axes_include_calendar_years_and_zero_stock_and_distinct_counts_are_unions(assembled: tuple[Fixture, assembly.StudyAssembly]) -> None:
    f, result = assembled
    expected_years = {"all": (2010, 2011, 2012, 2013, 2018, 2019, 2020), "2010-2012": (2010, 2011, 2012), "2013-2018": (2013, 2018), "2019+": (2019, 2020)}
    assert tuple(result.axes) == entry.ERAS
    for era, years in expected_years.items():
        assert result.axes[era] == bootstrap.CountAxes(f.request.codes, years, era)
    assert any(row.security_id == "FAKE_ZERO" for row in result.rows)
    assert all(not any(row.counts) for row in result.rows if row.security_id == "FAKE_ZERO")
    assert any(row.t0_year == 2020 and row.arm == "M" for row in result.rows)
    assert all(not any(row.counts) for row in result.rows if row.t0_year == 2020 and row.arm == "M")
    summary = result.summaries[entry.SummaryKey("CORE", "daily", None, (126, 2.0), "all", "S")]
    assert summary.counts == (9, 6, 3, 2, 1, 2, 2, 1)
    assert summary.stock_ids == summary.known_stock_ids == frozenset(("FAKE_A",))
    assert summary.distinct_stock_n == 1
    # A full-history cooldown selects the first position once, even across years.
    cool = [
        row
        for row in result.rows
        if row.security_id == "FAKE_A" and row.set_id == "CORE" and row.cadence == "cooled20" and row.arm == "S" and row.label == (126, 2.0)
    ]
    assert {row.t0_year: row.counts[0] for row in cool} == {2010: 1, 2011: 0, 2012: 0, 2013: 0, 2018: 0, 2019: 0, 2020: 0}
    for row in result.rows:
        event, known, hit, loss, flat, unknown, censored, full_unknown = row.counts
        assert all(type(value) is int for value in row.counts)
        assert event == known + full_unknown + censored
        assert known == hit + loss + flat
        assert full_unknown <= unknown <= full_unknown + censored


@pytest.mark.parametrize("cell_index,cadence,era", [(0, "daily", "all"), (3, "cooled20", "2013-2018"), (35, "daily", "2019+")])
def test_interval_matches_public_bootstrap_oracle(assembled: tuple[Fixture, assembly.StudyAssembly], cell_index: int, cadence: str, era: str) -> None:
    _, result = assembled
    cell = entry.COMPARISONS[cell_index]
    axes = result.axes[era]
    selected = (
        row
        for row in result.rows
        if row.t0_year in axes.years
        and row.set_id == cell.set_id
        and row.cadence == cadence
        and row.label == cell.label
        and ((row.arm == "M" and row.band_id is None) or (row.arm in entry.ARMS and row.band_id == cell.band_id))
    )
    cube = bootstrap.build_cell_cube(selected, axes=axes, cell=cell, cadence=cadence)
    actual = tuple(row for row in result.intervals if row.cell_id == cell.cell_id and row.cadence == cadence and row.era == era)
    expected = tuple(row for method in ("stock", "two_way") for row in bootstrap.bootstrap_cell(cube, bootstrap.paired_weights(axes, method=method, reps=5)))
    assert actual == expected


def test_interval_order_nulls_and_provenance_are_retained_and_json_safe(assembled: tuple[Fixture, assembly.StudyAssembly]) -> None:
    f, result = assembled
    assert [(r.era, r.cell_id, r.cadence, r.method, r.statistic) for r in result.intervals] == [
        (era, cell.cell_id, cadence, method, statistic)
        for era in entry.ERAS
        for cell in entry.COMPARISONS
        for cadence in entry.CADENCES
        for method in ("stock", "two_way")
        for statistic in bootstrap.STATISTICS
    ]
    comparisons = {(c.era, c.cell_id, c.cadence): c for c in result.comparisons}
    for row in result.intervals:
        assert row.point_estimate == comparisons[row.era, row.cell_id, row.cadence].rates[row.statistic]
        assert row.seed == bootstrap.SEEDS[row.method]
        assert row.reps == row.valid_replicate_n + row.null_replicate_n == 5
        assert row.generator == bootstrap.GENERATOR
        assert row.order == bootstrap.ORDER
        assert row.numpy_version == np.__version__
    nulls = [r for r in result.intervals if r.era == "2013-2018" and r.cadence == "cooled20"]
    assert len(nulls) == 720
    assert all(r.point_estimate is r.lower is r.upper is None and r.valid_replicate_n == 0 and r.null_replicate_n == 5 for r in nulls)
    assert tuple(result.alignment_records) == f.request.codes
    for packet in f.packets:
        record = result.alignment_records[packet.request.security_id]
        staged = staging.stage_stock_inputs(packet.request, canonical=packet.canonical, raw=packet.raw, intervals=packet.intervals, limits=packet.limits)
        assert dict(record) == dict(staged.alignment_record)
        assert record["generation"] == f.request.generation
        assert record["session_count"] == len(f.request.common_calendar)
        assert record["official_limits_source"] == (None if packet.limits is None else packet.limits.source)
    json.dumps(
        {
            "intervals": [asdict(row) for row in result.intervals],
            "comparisons": [dict(c.rates) for c in result.comparisons],
            "records": {code: dict(record) for code, record in result.alignment_records.items()},
        },
        allow_nan=False,
    )


def test_all_staging_precedes_whole_history_counts_and_eight_weight_objects_are_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    f = _fixture()
    original_stage, original_count = staging.stage_stock_inputs, entry.count_stock
    original_weights, original_bootstrap, original_cube = bootstrap.paired_weights, bootstrap.bootstrap_cell, bootstrap.build_cell_cube
    events: list[tuple[str, str]] = []
    weight_objects: dict[tuple[str, str], bootstrap.PairedWeights] = {}
    uses: Counter[tuple[str, str]] = Counter()
    cube_keys: set[tuple[str, str, str]] = set()

    def stage(request: staging.InputRequest, **kwargs: Any) -> staging.StagedInputs:
        result = original_stage(request, **kwargs)
        events.append(("stage", request.security_id))
        return result

    def count(calendar: pd.DatetimeIndex, stock: canonical.StockDaily, quotes: entry.Quotes) -> entry.StockCounts:
        assert calendar.equals(f.request.common_calendar)
        assert len(stock.eligible) == len(f.request.common_calendar)
        assert events[: len(f.packets)] == [("stage", code) for code in f.request.codes]
        events.append(("count", stock.code))
        return original_count(calendar, stock, quotes)

    def weights(axes: bootstrap.CountAxes, *, method: str, reps: int = 2000) -> bootstrap.PairedWeights:
        key = axes.era, method
        assert key not in weight_objects
        result = original_weights(axes, method=method, reps=reps)
        weight_objects[key] = result
        return result

    def interval(cube: bootstrap.CellCube, weights: bootstrap.PairedWeights) -> tuple[bootstrap.IntervalRow, ...]:
        key = cube.era, weights.method
        assert weights is weight_objects[key]
        uses[key] += 1
        return original_bootstrap(cube, weights)

    def build_cube(rows: Any, *, axes: bootstrap.CountAxes, cell: entry.Comparison, cadence: str) -> bootstrap.CellCube:
        key = axes.era, cell.cell_id, cadence
        assert key not in cube_keys
        cube_keys.add(key)
        return original_cube(rows, axes=axes, cell=cell, cadence=cadence)

    monkeypatch.setattr(staging, "stage_stock_inputs", stage)
    monkeypatch.setattr(entry, "count_stock", count)
    monkeypatch.setattr(bootstrap, "paired_weights", weights)
    monkeypatch.setattr(bootstrap, "bootstrap_cell", interval)
    monkeypatch.setattr(bootstrap, "build_cell_cube", build_cube)
    result = assembly.assemble_study(f.request, reversed(f.packets), reps=3)
    assert events == [("stage", code) for code in f.request.codes] + [("count", code) for code in f.request.codes]
    assert len(weight_objects) == 8
    assert len(cube_keys) == 288
    assert uses == Counter({(era, method): 72 for era in entry.ERAS for method in ("stock", "two_way")})
    assert len(result.intervals) == 5760


@pytest.mark.parametrize("codes", [(), ("FAKE_ZERO", "FAKE_A"), ("FAKE_A", "FAKE_A"), ("",), (" ",), ["FAKE_A", "FAKE_ZERO"], (1,)])
def test_invalid_code_axes_fail_before_count(monkeypatch: pytest.MonkeyPatch, codes: object) -> None:
    f = _fixture()
    _assert_preflight_rejection(monkeypatch, replace(f.request, **_changes("codes", codes)), f.packets)


@pytest.mark.parametrize("reps", [0, -1, True, 1.5, np.int64(2), "2", None])
def test_invalid_replicate_counts_fail_before_count(monkeypatch: pytest.MonkeyPatch, reps: object) -> None:
    f = _fixture()
    _assert_preflight_rejection(monkeypatch, f.request, f.packets, reps=reps)


def _assert_preflight_rejection(monkeypatch: pytest.MonkeyPatch, request: assembly.AssemblyRequest, packets: object, *, reps: object = 3) -> None:
    def forbidden_count(*args: object, **kwargs: object) -> None:
        raise AssertionError("no stock may be counted before every input passes preflight")

    monkeypatch.setattr(entry, "count_stock", forbidden_count)
    with pytest.raises(ValueError):
        assembly.assemble_study(request, cast(Any, packets), reps=cast(Any, reps))


@pytest.mark.parametrize("case", ["missing", "duplicate", "extra", "empty"])
def test_exactly_one_packet_per_requested_stock_is_required(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    f = _fixture()
    extra = replace(f.packets[0], request=replace(f.packets[0].request, security_id="UNREQUESTED"))
    choices = {"missing": f.packets[:1], "duplicate": (f.packets[0], f.packets[0], f.packets[1]), "extra": (*f.packets, extra), "empty": ()}
    _assert_preflight_rejection(monkeypatch, f.request, choices[case])


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", "other-generation"),
        ("study_as_of", pd.Timestamp("2020-01-03")),
        ("universe_id", "other-universe"),
        ("calendar_id", "other-calendar"),
        ("common_calendar", pd.DatetimeIndex(["2010-01-01", "2013-01-01", "2019-01-01"])),
    ],
)
def test_internally_consistent_second_stock_still_requires_study_identity(monkeypatch: pytest.MonkeyPatch, field: str, value: object) -> None:
    f = _fixture()
    packet = f.packets[1]
    packet_field = "calendar" if field == "common_calendar" else field
    changed = replace(
        packet,
        request=replace(packet.request, **_changes(field, value)),
        canonical=replace(packet.canonical, **_changes(packet_field, value)),
        raw=replace(packet.raw, **_changes(packet_field, value)),
        intervals=replace(packet.intervals, **_changes(packet_field, value)),
    )
    _assert_preflight_rejection(monkeypatch, f.request, (f.packets[0], changed))


@pytest.mark.parametrize("missing_era", ["2010-2012", "2013-2018", "2019+"])
def test_any_missing_calendar_era_is_rejected_before_count(monkeypatch: pytest.MonkeyPatch, missing_era: str) -> None:
    f = _fixture()
    calendars = {
        "2010-2012": pd.DatetimeIndex(["2013-01-02", "2019-01-02"]),
        "2013-2018": pd.DatetimeIndex(["2010-01-04", "2019-01-02"]),
        "2019+": pd.DatetimeIndex(["2010-01-04", "2013-01-02"]),
    }

    def forbidden_count(*args: object, **kwargs: object) -> None:
        raise AssertionError("missing calendar eras must fail before counting")

    monkeypatch.setattr(entry, "count_stock", forbidden_count)
    with pytest.raises(ValueError, match=missing_era.replace("+", r"\+")):
        assembly.assemble_study(replace(f.request, common_calendar=calendars[missing_era]), f.packets, reps=3)


@pytest.mark.parametrize("case", ["float32", "missing_label", "coverage", "packet_identity"])
def test_malformed_later_packet_never_counts_the_valid_first_stock(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    f = _fixture()
    packet = f.packets[1]
    if case == "float32":
        packet = replace(packet, raw=replace(packet.raw, raw_open=packet.raw.raw_open.astype(np.float32)))
    elif case == "missing_label":
        labels = {key: values for key, values in packet.canonical.stock.labels.items() if key != canonical.LABELS[-1]}
        packet = replace(packet, canonical=replace(packet.canonical, stock=replace(packet.canonical.stock, labels=labels)))
    elif case == "coverage":
        packet = replace(packet, intervals=replace(packet.intervals, event_coverage=np.zeros(len(f.request.common_calendar), dtype=np.int8)))
    else:
        packet = replace(packet, raw=replace(packet.raw, generation="mismatched-generation"))
    _assert_preflight_rejection(monkeypatch, f.request, (f.packets[0], packet))


def test_order_independence_determinism_and_readonly_inputs() -> None:
    f = _fixture()
    arrays = [array for packet in f.packets for array in _arrays(packet)]
    snapshots = [array.copy() for array in arrays]
    calendars = [packet.request.common_calendar.copy() for packet in f.packets]
    for array in arrays:
        array.flags.writeable = False
    first = assembly.assemble_study(f.request, f.packets, reps=3)
    second = assembly.assemble_study(f.request, (packet for packet in reversed(f.packets)), reps=3)
    assert first == second
    for array, snapshot in zip(arrays, snapshots, strict=True):
        np.testing.assert_array_equal(array, snapshot)
        assert not array.flags.writeable
    for packet, calendar in zip(f.packets, calendars, strict=True):
        assert packet.request.common_calendar.equals(calendar)
    with pytest.raises(FrozenInstanceError):
        first.rows = ()  # type: ignore[misc]
    for mapping in (first.summaries, first.axes, first.alignment_records, first.comparisons[0].rates, first.alignment_records["FAKE_A"]):
        with pytest.raises(TypeError):
            cast(Any, mapping)["injected"] = None


def test_assembly_works_with_source_io_and_label_construction_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import maintained_adjusted_daily as maintained

    f = _fixture()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("pure assembly must not read sources, calculate labels, or perform I/O")

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
        result = assembly.assemble_study(f.request, f.packets, reps=2)
        assert len(result.comparisons) == 288
        assert len(result.intervals) == 5760
