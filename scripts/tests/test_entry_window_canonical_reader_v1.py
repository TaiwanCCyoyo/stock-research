"""Canonical public-reader integration over entirely artificial generations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import entry_window_canonical_v1 as canonical_reader
from research_core import entry_window_inputs_v1 as staging
from research_core import entry_window_raw_quotes_v1 as raw_reader
from research_core import entry_window_v1 as entry
from research_core import maintained_adjusted_daily, run_receipt
from research_core import momentum_only_v1 as momentum

SESSION_COUNT = 620
ACTION_INDEX = 180
MISSING_INDEX = 300
AVAILABILITY_NOTE = "Artificial ordinary-reference declaration; historical membership and source availability are not certified"


@dataclass(frozen=True)
class ArtificialGeneration:
    shared: Path
    request: staging.InputRequest


@pytest.fixture()
def artificial_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtificialGeneration:
    producer, shared = tmp_path / "artificial producer", tmp_path / "artificial shared root"
    producer.mkdir()
    shared.mkdir()
    calendar = pd.bdate_range("2023-01-02", periods=SESSION_COUNT)
    last_session = cast(pd.Timestamp, calendar[-1])
    cutoff = cast(pd.Timestamp, last_session + pd.Timedelta(days=2))
    future_session = cast(pd.Timestamp, last_session + pd.Timedelta(days=3))
    source_calendar = calendar.append(pd.DatetimeIndex([future_session]))
    rows: list[dict[str, Any]] = []
    for code in ("1101", "2330"):
        for index, day in enumerate(source_calendar):
            if code == "2330" and index == MISSING_INDEX:
                continue
            close = 50.0 if code == "1101" else float(100.0 * np.exp(0.007 * index))
            if code == "2330" and index >= ACTION_INDEX:
                close *= 0.9
            if code == "2330" and day == future_session:
                close *= 0.5
            rows.append({
                "Code": code,
                "Date": day,
                "Open": close,
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
                "Volume": 1000.0,
                "Source": "official",
            })
    pd.DataFrame(rows).to_parquet(producer / "price_daily.parquet", index=False)
    with sqlite3.connect(producer / "corporate_actions.sqlite") as connection:
        connection.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
        connection.executemany(
            "INSERT INTO corporate_actions VALUES (?, ?, ?, ?)",
            [
                ("2330", cast(pd.Timestamp, calendar[ACTION_INDEX]).date().isoformat(), "CASH_DIVIDEND", 0.9),
                ("2330", future_session.date().isoformat(), "CASH_DIVIDEND", 0.5),
            ],
        )
    # The public builder reads real parquet/SQLite and publishes real generation
    # files, but all paths and producer classification remain inside this fixture.
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(producer))
    monkeypatch.setenv("STOCK_RESEARCH_SHARED_ROOT", str(shared))
    monkeypatch.setattr(run_receipt, "producer_data_root", lambda: producer)
    monkeypatch.setattr(run_receipt, "assert_producer_idle", lambda now=None: None)
    monkeypatch.setattr(maintained_adjusted_daily, "code_identity", lambda: {"commit": "synthetic-canonical-reader", "dirty": False})
    generation = maintained_adjusted_daily.update(producer_root=producer, root=shared)["generation"]
    return ArtificialGeneration(
        shared=shared,
        request=staging.InputRequest(
            security_id="2330",
            generation=generation,
            study_as_of=cutoff,
            common_calendar=calendar,
            universe_id="artificial-universe.v1",
            calendar_id="artificial-calendar.v1",
        ),
    )


def _assert_all_stock_fields_equal(actual: momentum.StockDaily, expected: momentum.StockDaily) -> None:
    assert actual.code == expected.code and actual.split == expected.split
    for name in ("eligible", "jump", "c52w", "ret120"):
        left, right = getattr(actual, name), getattr(expected, name)
        assert left.dtype == right.dtype
        np.testing.assert_array_equal(left, right)
    for name in ("atoms", "labels", "main_eligible", "calendar_full"):
        actual_mapping, expected_mapping = getattr(actual, name), getattr(expected, name)
        assert actual_mapping.keys() == expected_mapping.keys()
        for key, values in actual_mapping.items():
            assert values.dtype == expected_mapping[key].dtype
            np.testing.assert_array_equal(values, expected_mapping[key], err_msg=f"{name}[{key}]")


@pytest.mark.parametrize("ordinary_reference", [True, False])
def test_public_generation_matches_original_calculation_for_every_stock_field(
    artificial_generation: ArtificialGeneration, ordinary_reference: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = artificial_generation
    request = fixture.request
    frame, record = maintained_adjusted_daily.read_adjusted_daily(
        "reference_factor_adjusted",
        root=fixture.shared,
        generation=request.generation,
        codes=[request.security_id],
        as_of=request.study_as_of,
        calendar=request.common_calendar,
    )
    prepared = frame.drop(columns="Code").set_index("Date")
    expected = momentum.stock_daily(request.security_id, prepared, ordinary_reference=ordinary_reference)
    before_frame = frame.copy(deep=True)
    reader_calls: list[tuple[str, dict[str, Any]]] = []
    calculator_calls: list[bool] = []
    generation_calls: list[str | None] = []
    public_read = maintained_adjusted_daily.read_adjusted_daily
    public_stock = momentum.stock_daily
    public_generation = maintained_adjusted_daily.current_generation

    def observed_read(basis: str, **kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
        reader_calls.append((basis, kwargs.copy()))
        return public_read(basis, **kwargs)

    def observed_stock(code: str, values: pd.DataFrame, *, ordinary_reference: bool = True) -> momentum.StockDaily:
        calculator_calls.append(ordinary_reference)
        pd.testing.assert_frame_equal(values, prepared)
        return public_stock(code, values, ordinary_reference=ordinary_reference)

    def pinned_generation(root: Path | None = None, *, generation: str | None = None) -> dict[str, Any]:
        generation_calls.append(generation)
        assert root == fixture.shared and generation == request.generation
        return public_generation(root, generation=generation)

    monkeypatch.setattr(maintained_adjusted_daily, "read_adjusted_daily", observed_read)
    monkeypatch.setattr(maintained_adjusted_daily, "current_generation", pinned_generation)
    monkeypatch.setattr(momentum, "stock_daily", observed_stock)
    result = canonical_reader.load_canonical_packet(request, root=fixture.shared, ordinary_reference=ordinary_reference, availability_note=AVAILABILITY_NOTE)

    assert len(reader_calls) == 1
    basis, kwargs = reader_calls[0]
    assert basis == "reference_factor_adjusted"
    assert kwargs["root"] == fixture.shared and kwargs["generation"] == request.generation
    assert kwargs["codes"] == [request.security_id] and kwargs["as_of"] == request.study_as_of
    assert kwargs["calendar"].equals(request.common_calendar)
    assert generation_calls == [request.generation] and calculator_calls == [ordinary_reference]
    _assert_all_stock_fields_equal(result.packet.stock, expected)
    pd.testing.assert_frame_equal(frame, before_frame)
    assert result.ordinary_reference is ordinary_reference
    assert result.packet.availability_note == AVAILABILITY_NOTE
    assert result.packet.definition == "momentum-only.v1" and result.packet.basis == "reference_factor_adjusted"
    assert result.packet.calendar.equals(request.common_calendar)
    for name in ("security_id", "generation", "study_as_of", "universe_id", "calendar_id"):
        assert getattr(result.packet, name) == getattr(request, name)
    assert dict(result.source_record) == record
    assert result.source_record["as_of"] == request.study_as_of.date().isoformat()
    assert pd.Timestamp(result.source_record["asof"]) > request.study_as_of > request.common_calendar[-1]
    assert frame.loc[0, "restatement_factor"] == 0.9, "The later 0.5 action must not restate the cutoff read"
    assert frame.loc[ACTION_INDEX + 1, "restatement_factor"] == 1.0
    assert frame.loc[MISSING_INDEX, "quality_reason"] == "missing_official_quote"
    assert np.isnan(frame.loc[MISSING_INDEX, "Close"])
    assert not result.packet.stock.eligible[:59].any(), "No eligibility is invented during warmup"
    assert not result.packet.stock.eligible[MISSING_INDEX : MISSING_INDEX + 60].any()
    assert np.isnan(result.packet.stock.ret120[0]) and np.isfinite(result.packet.stock.ret120[250])
    assert "A4" not in result.packet.stock.atoms, "A single-stock reader must not invent a cross-sectional rank"
    assert set(result.packet.stock.labels) == set(momentum.LABELS) and len(result.packet.stock.labels) == 12
    for horizon in momentum.HORIZONS:
        assert result.packet.stock.calendar_full[horizon][: SESSION_COUNT - horizon].all()
        assert not result.packet.stock.calendar_full[horizon][SESSION_COUNT - horizon :].any()
    assert result.packet.stock.labels[252, 2.0][400] == 1, "An observed hit may still be censored"
    assert not result.packet.stock.main_eligible[252, 2.0][400]
    if ordinary_reference:
        assert result.packet.stock.eligible[80] and result.packet.stock.eligible[-1]
    else:
        assert not result.packet.stock.eligible.any(), "False must reach the existing eligibility calculation unchanged"


def test_real_canonical_and_raw_packets_stage_and_count_with_unknown_intervals(artificial_generation: ArtificialGeneration) -> None:
    fixture = artificial_generation
    request = fixture.request
    canonical = canonical_reader.load_canonical_packet(request, root=fixture.shared, ordinary_reference=True, availability_note=AVAILABILITY_NOTE)
    raw = raw_reader.load_raw_quote_packet(request, root=fixture.shared)
    n = len(request.common_calendar)
    intervals = staging.IntervalPacket(
        security_id=request.security_id,
        generation=request.generation,
        study_as_of=request.study_as_of,
        calendar=request.common_calendar.copy(),
        universe_id=request.universe_id,
        calendar_id=request.calendar_id,
        source="Artificial interval declaration; source actions do not establish complete coverage",
        action_to_next=np.full(n, -1, dtype=np.int8),
        event_quality_to_next=np.full(n, -1, dtype=np.int8),
        quote_quality_to_next=np.full(n, -1, dtype=np.int8),
        event_coverage=np.full(n, -1, dtype=np.int8),
        coverage_note="No interval event or quote-quality source has been admitted in this synthetic wiring test",
    )
    staged = staging.stage_stock_inputs(request, canonical=canonical.packet, raw=raw.packet, intervals=intervals)
    masks = entry.classify_quotes(staged.calendar, staged.quotes)
    counted = entry.count_stock(staged.calendar, staged.stock, staged.quotes)

    assert staged.stock is canonical.packet.stock
    assert staged.calendar.equals(request.common_calendar)
    assert masks.quote_known.any() and not masks.clean.any()
    assert masks.reasons["corporate_action_unknown"].all()
    assert masks.reasons["event_quality_unknown"].all()
    assert masks.reasons["quote_quality_unknown"].all()
    assert np.all(staged.quotes.action_to_next == -1) and np.all(staged.quotes.event_quality_to_next == -1)
    assert np.all(staged.quotes.quote_quality_to_next == -1) and np.all(intervals.event_coverage == -1)
    assert raw.quality.any(), "Good daily rows must not promote the separately unknown interval evidence"
    signal_rows = [row for row in counted.rows if row.set_id == "CORE" and row.cadence == "daily" and row.label == (126, 2.0) and row.arm == "S"]
    assert sum(row.counts[0] for row in signal_rows) > 0, "The synthetic trend exercises actual condition members"
    assert all(row.counts[0] == 0 for row in counted.rows if row.arm == "M")
    assert counted.rows and counted.diagnostics
    for row in counted.rows:
        event, known, hit, loss, flat, unknown, censored, full_unknown = row.counts
        assert event == known + full_unknown + censored and known == hit + loss + flat
        assert full_unknown <= unknown <= full_unknown + censored
    assert staged.alignment_record["generation"] == request.generation
    assert staged.alignment_record["canonical_definition"] == "momentum-only.v1"
    assert staged.alignment_record["event_coverage_note"] == intervals.coverage_note
