"""Small artificial seven-day facts and prices; no official calendar or reader."""

from __future__ import annotations

import ast
import builtins
import inspect
import socket
import sqlite3
from dataclasses import FrozenInstanceError, asdict, fields, replace
from pathlib import Path
from typing import NoReturn, cast

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from research_core import multi_timeframe_ma_weeks_v1 as weeks
from research_core.multi_timeframe_ma_core_v1 import CutoffSeries, moving_averages
from research_core.multi_timeframe_ma_weeks_v1 import CalendarFact, CalendarSnapshot, WeekAssessment, aggregate_week, assess_week


def stamp(value: str, *, tz: str | None = None) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(value, tz=tz))


MONDAY = stamp("2026-01-05")
BASIS = "reference_factor_adjusted"


def aware(value: str) -> pd.Timestamp:
    return stamp(value, tz="Asia/Taipei")


def facts_for(
    monday: pd.Timestamp = MONDAY,
    *,
    sessions: tuple[int, ...] = (0, 1, 2, 3, 4),
    known_at: pd.Timestamp | None = None,
) -> tuple[CalendarFact, ...]:
    known = aware("2010-01-01 08:00") if known_at is None else known_at
    return tuple(
        CalendarFact(
            cast(pd.Timestamp, monday + pd.Timedelta(days=i)),
            int(i in sessions),
            known,
            cast(pd.Timestamp, (monday + pd.Timedelta(days=i, hours=14, minutes=7)).tz_localize("Asia/Taipei")) if i in sessions else None,
            f"synthetic-source:{i}",
        )
        for i in range(7)
    )


def assessment_at(
    decision: pd.Timestamp | None = None,
    *,
    facts: tuple[CalendarFact, ...] | None = None,
    monday: pd.Timestamp = MONDAY,
) -> WeekAssessment:
    iso = monday.isocalendar()
    snapshot = CalendarSnapshot(
        "FAKE-calendar",
        aware("2026-01-09 14:07") if decision is None else decision,
        facts_for(monday) if facts is None else facts,
        "Synthetic caller-selected facts; no independent PIT certification",
    )
    return assess_week(snapshot, iso_year=int(iso[0]), iso_week=int(iso[1]))


def daily(
    dates: tuple[pd.Timestamp, ...] | pd.DatetimeIndex,
    *,
    close: NDArray[np.float64] | None = None,
    valid: NDArray[np.bool_] | None = None,
    cutoff: pd.Timestamp | None = None,
) -> CutoffSeries:
    index = pd.DatetimeIndex(dates)
    return CutoffSeries(
        "FAKE_A",
        "synthetic-G",
        stamp("2026-01-09") if cutoff is None else cutoff,
        BASIS,
        "daily",
        index,
        np.arange(10, 10 + len(index), dtype=np.float64) if close is None else close,
        np.ones(len(index), dtype=np.bool_) if valid is None else valid,
    )


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ("2026-01-07 14:07", "incomplete"),
        ("2026-01-09 14:06:59.999999999", "incomplete"),
        ("2026-01-09 14:07", "complete"),
        ("2026-01-09 14:07:00.000000001", "complete"),
    ],
)
def test_five_day_week_explicit_close_boundaries(decision: str, expected: str) -> None:
    result = assessment_at(aware(decision))
    assert result.status == expected
    assert result.required_session_dates == tuple(pd.date_range(MONDAY, periods=5))
    assert result.last_session_date == stamp("2026-01-09")
    assert len(result.days) == 7
    # Only Wednesday prices cannot change Friday's calendar conclusion.
    cutoff = result.decision_at.tz_localize(None).normalize()
    bar = aggregate_week(daily(result.required_session_dates[:3], cutoff=cutoff), result)
    assert bar.status == ("withheld_calendar" if expected == "incomplete" else "invalid_bar")
    assert bar.has_bar == (expected == "complete")
    assert not bar.bar_valid and bar.close is None


def test_weekend_coverage_cannot_be_inferred_from_prices() -> None:
    result = assessment_at(facts=facts_for()[:5])
    assert result.status == "unknown" and result.last_session_date is None
    assert [day.reasons for day in result.days[-2:]] == [("missing_fact",), ("missing_fact",)]
    bar = aggregate_week(daily(result.required_session_dates), result)
    assert bar.status == "withheld_calendar" and bar.prices == ()
    assert not bar.has_bar and not bar.bar_valid and bar.close is None
    assert "2026-01-10:missing_fact" in bar.reasons


@pytest.mark.parametrize("empty_prices", [False, True])
def test_seven_known_closed_days_have_no_bar_or_missing_price(empty_prices: bool) -> None:
    result = assessment_at(facts=facts_for(sessions=()))
    source = daily(()) if empty_prices else daily((MONDAY,))
    bar = aggregate_week(source, result)
    assert result.status == "closed_no_sessions"
    assert result.required_session_dates == () and result.last_session_date is None
    assert bar.status == "empty_closed_week" and not bar.has_bar and not bar.bar_valid
    assert bar.close is None and bar.prices == () and bar.reasons == ("empty_closed_week",)
    assert bar.ignored_non_session_dates == (() if empty_prices else (MONDAY,))


def test_real_saturday_session_waits_for_its_own_close_and_sunday_quote_is_ignored() -> None:
    facts = facts_for(sessions=(0, 1, 2, 3, 4, 5))
    before = assessment_at(aware("2026-01-10 14:06"), facts=facts)
    assert before.status == "incomplete" and before.required_session_dates[-1] == stamp("2026-01-10")
    result = assessment_at(aware("2026-01-11 16:00"), facts=facts)
    source = daily(pd.date_range(MONDAY, periods=7), close=np.array([10, 11, 12, 13, 14, 15, 999], dtype=np.float64), cutoff=stamp("2026-01-11"))
    bar = aggregate_week(source, result)
    assert result.status == "complete" and bar.bar_valid
    assert bar.close == 15 and bar.last_session_date == stamp("2026-01-10")
    assert len(bar.prices) == 6 and bar.ignored_non_session_dates == (stamp("2026-01-11"),)
    missing = aggregate_week(daily(tuple(source.bar_dates[:5]), cutoff=source.decision_cutoff), result)
    assert missing.status == "invalid_bar" and missing.close is None
    assert missing.prices[-1].reasons == ("missing_price",)


def test_sunday_can_be_a_real_session_and_closed_phantom_quality_is_irrelevant() -> None:
    facts = facts_for(sessions=(6,))
    before = assessment_at(aware("2026-01-11 14:06"), facts=facts)
    assert before.status == "incomplete"
    result = assessment_at(aware("2026-01-11 14:07"), facts=facts)
    assert result.status == "complete" and result.required_session_dates == (stamp("2026-01-11"),)
    source = daily(
        pd.date_range(MONDAY, periods=7),
        close=np.array([np.nan, np.inf, -1, 0, 999, 0, 25], dtype=np.float64),
        valid=np.array([False] * 6 + [True], dtype=np.bool_),
        cutoff=stamp("2026-01-11"),
    )
    bar = aggregate_week(source, result)
    assert bar.close == 25 and bar.bar_valid and not bar.reasons
    assert bar.ignored_non_session_dates == tuple(pd.date_range(MONDAY, periods=6))


def test_known_closures_allow_early_completion_but_late_announcements_do_not_backfill() -> None:
    known = facts_for(sessions=(0, 1, 2))
    decision = aware("2026-01-07 14:07")
    complete = assessment_at(decision, facts=known)
    assert complete.status == "complete" and complete.last_session_date == stamp("2026-01-07")
    late = tuple(replace(fact, known_at=aware("2026-01-08 09:00")) if i in (3, 4) else fact for i, fact in enumerate(known))
    original = assessment_at(decision, facts=late)
    saved = asdict(original)
    assert original.status == "unknown" and original.last_session_date is None
    assert all(original.days[i].reasons == ("fact_not_yet_known",) for i in (3, 4))
    later = assessment_at(aware("2026-01-08 09:00"), facts=late)
    assert later.status == "complete"
    assert asdict(original) == saved
    # Metadata stores the assessment time, never a guessed first confirmation.
    assert later.decision_at == aware("2026-01-08 09:00")


@pytest.mark.parametrize("state", [-1, 0, 1])
@pytest.mark.parametrize("knowledge", [None, "2026-01-09 14:07:00.000000001"])
def test_unknown_or_future_fact_never_supplies_current_calendar_evidence(state: int, knowledge: str | None) -> None:
    facts = list(facts_for())
    facts[3] = CalendarFact(
        facts[3].date, state, None if knowledge is None else aware(knowledge), facts[3].close_at if state == 1 else None, None if state == -1 else "synthetic"
    )
    result = assessment_at(facts=tuple(facts))
    assert result.status == "unknown" and result.days[3].session_state == -1
    assert facts[3].date not in result.required_session_dates
    assert "known_at_unknown" in result.days[3].reasons if knowledge is None else "fact_not_yet_known" in result.days[3].reasons


def test_unknown_coverage_precedes_incomplete_and_retains_all_day_reasons() -> None:
    facts = list(facts_for())
    facts[1] = replace(facts[1], close_at=None)
    result = assessment_at(aware("2026-01-07 08:00"), facts=tuple(facts[:6]))
    assert result.status == "unknown"
    assert result.days[1].reasons == ("session_close_unknown",)
    assert result.days[6].reasons == ("missing_fact",)
    assert result.days[4].reasons == ("session_not_closed",)
    assert facts[1].date in result.required_session_dates  # Known session, unknown clock.
    assert result.last_session_date is None


def test_iso_cross_year_and_aware_zone_conversion() -> None:
    monday = stamp("2015-12-28")
    facts = facts_for(monday)
    utc_facts = tuple(
        replace(fact, known_at=cast(pd.Timestamp, fact.known_at).tz_convert("UTC"), close_at=None if fact.close_at is None else fact.close_at.tz_convert("UTC"))
        for fact in facts
    )
    # 2016-01-01 belongs to ISO 2015-W53; UTC comparison is the same instant.
    result = assessment_at(stamp("2016-01-01 06:07Z"), facts=utc_facts, monday=monday)
    assert result.week_id == (2015, 53) and result.status == "complete"
    assert result.last_session_date == stamp("2016-01-01")
    assert str(result.decision_at.tz) == "Asia/Taipei"
    assert aggregate_week(daily(result.required_session_dates, cutoff=stamp("2016-01-01")), result).close == 14
    snapshot = CalendarSnapshot("cal", stamp("2026-01-08 16:05Z"), facts_for(), "synthetic")
    today = assess_week(snapshot, iso_year=2026, iso_week=2)
    assert today.decision_at.date().isoformat() == "2026-01-09"
    assert aggregate_week(daily(today.required_session_dates), today).status == "withheld_calendar"


@pytest.mark.parametrize(("year", "week"), [(2021, 53), (2026, 0), (2026, 54), (0, 1), (10000, 1), (True, 1), (2026, 2.0)])
def test_invalid_iso_week_is_rejected(year: int, week: int) -> None:
    with pytest.raises(ValueError):
        assess_week(CalendarSnapshot("cal", aware("2026-01-09 14:07"), facts_for(), "synthetic"), iso_year=year, iso_week=week)


@pytest.mark.parametrize("field", ["decision_at", "known_at", "close_at"])
@pytest.mark.parametrize("value", [stamp("2026-01-09 14:07"), pd.NaT, "2026-01-09T14:07+08:00"])
def test_naive_missing_or_string_instants_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        if field == "decision_at":
            CalendarSnapshot("cal", cast(pd.Timestamp, value), facts_for(), "synthetic")
        elif field == "known_at":
            replace(facts_for()[4], known_at=cast(pd.Timestamp, value))
        else:
            replace(facts_for()[4], close_at=cast(pd.Timestamp, value))


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, 2, -2, np.int8(1)])
def test_illegal_fact_states_fail_closed(value: object) -> None:
    with pytest.raises(ValueError, match="session_state"):
        replace(facts_for()[0], session_state=cast(int, value))


@pytest.mark.parametrize("value", [stamp("2026-01-05 00:01"), aware("2026-01-05 00:00"), pd.NaT, "2026-01-05"])
def test_invalid_fact_date_labels_are_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="normalized"):
        replace(facts_for()[0], date=cast(pd.Timestamp, value))


@pytest.mark.parametrize("state", [0, 1])
@pytest.mark.parametrize("source", [None, "", " ", 5])
def test_declared_known_states_require_explicit_source(state: int, source: object) -> None:
    with pytest.raises(ValueError, match="source_ref"):
        CalendarFact(MONDAY, state, None, None, cast(str, source))


def test_unknown_state_requires_no_fabricated_knowledge_or_source() -> None:
    fact = CalendarFact(MONDAY, -1, None, None, None)
    result = assessment_at(facts=(fact,))
    assert result.days[0].reasons == ("session_state_unknown", "known_at_unknown")


def test_contradictory_closed_close_or_wrong_taipei_session_day_is_rejected() -> None:
    with pytest.raises(ValueError, match="closed facts"):
        replace(facts_for()[0], session_state=0)
    with pytest.raises(ValueError, match="Asia/Taipei"):
        replace(facts_for()[0], close_at=stamp("2026-01-05 16:01Z"))
    # UTC date differs, but Taipei day is correct.
    assert replace(facts_for()[0], close_at=stamp("2026-01-04 17:01Z")).close_at == aware("2026-01-05 01:01")


@pytest.mark.parametrize("mode", ["duplicate", "reverse", "dict", "list", "wrong_fact"])
def test_bad_fact_collections_are_not_sorted_cast_or_last_wins(mode: str) -> None:
    original = facts_for()
    value: object = {
        "duplicate": original[:1] + original,
        "reverse": original[::-1],
        "dict": {"date": MONDAY},
        "list": list(original),
        "wrong_fact": (MONDAY,),
    }[mode]
    with pytest.raises(ValueError):
        CalendarSnapshot("cal", aware("2026-01-09 14:07"), cast(tuple[CalendarFact, ...], value), "synthetic")


@pytest.mark.parametrize("field", ["calendar_id", "availability_note"])
@pytest.mark.parametrize("value", ["", " ", None])
def test_snapshot_requires_explicit_lineage_and_availability(field: str, value: str) -> None:
    snapshot = CalendarSnapshot("cal", aware("2026-01-09 14:07"), facts_for(), "synthetic")
    with pytest.raises(ValueError):
        if field == "calendar_id":
            replace(snapshot, calendar_id=value)
        else:
            replace(snapshot, availability_note=value)


@pytest.mark.parametrize("missing_index", [0, 2, 4])
def test_every_required_price_is_checked_and_invalid_week_position_is_retained(missing_index: int) -> None:
    result = assessment_at()
    dates = result.required_session_dates
    source = daily(dates[:missing_index] + dates[missing_index + 1 :])
    bar = aggregate_week(source, result)
    assert bar.week_id == (2026, 2) and bar.last_session_date == stamp("2026-01-09")
    assert bar.has_bar and not bar.bar_valid and bar.close is None and bar.status == "invalid_bar"
    assert len(bar.prices) == 5
    assert bar.prices[missing_index].reasons == ("missing_price",)
    assert bar.reasons == (f"{dates[missing_index].date().isoformat()}:missing_price",)


@pytest.mark.parametrize(
    ("bad", "cause"),
    [(np.nan, "nonfinite_close"), (np.inf, "nonfinite_close"), (-np.inf, "nonfinite_close"), (0.0, "nonpositive_close"), (-1.0, "nonpositive_close")],
)
@pytest.mark.parametrize("position", [1, 4])
def test_bad_middle_or_final_close_invalidates_whole_week(bad: float, cause: str, position: int) -> None:
    result = assessment_at()
    close = np.full(5, 10.0)
    close[position] = bad
    bar = aggregate_week(daily(result.required_session_dates, close=close), result)
    assert not bar.bar_valid and bar.close is None and bar.has_bar
    assert bar.prices[position].reasons == (cause,)
    assert bar.last_session_date == result.last_session_date


def test_upstream_quality_or_unknown_factor_and_overlapping_price_reasons_are_retained() -> None:
    result = assessment_at()
    valid = np.array([True, False, True, True, False], dtype=np.bool_)
    close = np.array([10, np.nan, 12, 13, 0], dtype=np.float64)
    bar = aggregate_week(daily(result.required_session_dates, close=close, valid=valid), result)
    assert bar.prices[1].reasons == ("invalid_upstream", "nonfinite_close")
    assert bar.prices[4].reasons == ("invalid_upstream", "nonpositive_close")
    assert len(bar.reasons) == 4 and not bar.bar_valid and bar.close is None
    quality_only = aggregate_week(daily(result.required_session_dates, valid=valid), result)
    assert quality_only.prices[1].reasons == ("invalid_upstream",)
    assert quality_only.close is None  # Never guess unknown factor=1.


def test_only_last_required_session_supplies_close_and_other_history_is_irrelevant() -> None:
    result = assessment_at(aware("2026-01-11 18:00"))
    dates = pd.DatetimeIndex([stamp("2026-01-02"), *result.required_session_dates, stamp("2026-01-11")])
    source = daily(dates, close=np.array([999, 30, 100, 25, 15, 20, 9999], dtype=np.float64), cutoff=stamp("2026-01-11"))
    bar = aggregate_week(source, result)
    assert bar.close == 20 and bar.bar_valid
    assert bar.ignored_non_session_dates == (stamp("2026-01-11"),)
    assert (bar.security_id, bar.generation, bar.price_basis, bar.calendar_id) == ("FAKE_A", "synthetic-G", BASIS, "FAKE-calendar")
    assert bar.availability_note == result.availability_note and bar.decision_at == result.decision_at
    assert bar.decision_cutoff == source.decision_cutoff


@pytest.mark.parametrize("factor", [0.25, 0.97, 2.0])
def test_same_cutoff_positive_scaling_changes_only_weekly_close(factor: float) -> None:
    result = assessment_at()
    close = np.array([100, 90, 95, 93, 97], dtype=np.float64)
    first = aggregate_week(daily(result.required_session_dates, close=close), result)
    second = aggregate_week(daily(result.required_session_dates, close=close * factor), result)
    assert second == replace(first, close=cast(float, first.close) * factor)


@pytest.mark.parametrize("kind", ["cutoff", "basis", "weekly", "float32", "bool_as_int", "shape", "dates"])
def test_wrong_daily_contract_is_rejected(kind: str) -> None:
    result = assessment_at()
    source = daily(result.required_session_dates)
    if kind == "cutoff":
        source = replace(source, decision_cutoff=stamp("2026-01-10"))
    elif kind == "weekly":
        source = replace(source, bar_kind="completed_weekly")
    else:
        # Probe boundary validation even if a caller bypassed core's frozen record.
        name, value = {
            "basis": ("price_basis", "raw"),
            "float32": ("close", source.close.astype(np.float32)),
            "bool_as_int": ("valid", source.valid.astype(np.int8)),
            "shape": ("close", source.close.reshape(1, -1)),
            "dates": ("bar_dates", source.bar_dates[::-1]),
        }[kind]
        object.__setattr__(source, name, value)
    with pytest.raises(ValueError):
        aggregate_week(source, result)


@pytest.mark.parametrize("change", ["required", "last", "status", "week", "decision", "coverage", "lineage"])
def test_aggregation_rejects_assessment_overrides(change: str) -> None:
    result = assessment_at()
    changed = {
        "required": {"required_session_dates": result.required_session_dates[-1:]},
        "last": {"last_session_date": result.required_session_dates[-2]},
        "status": {"status": "closed_no_sessions"},
        "week": {"week_id": (2026, 3)},
        "decision": {"decision_at": aware("2026-01-10 14:07")},
        "coverage": {"days": result.days[:5]},
        "lineage": {"calendar_id": "another"},
    }[change]
    with pytest.raises(ValueError, match="evidence"):
        aggregate_week(daily(result.required_session_dates), replace(result, **changed))


def test_wrong_api_objects_are_rejected() -> None:
    with pytest.raises(TypeError):
        assess_week(cast(CalendarSnapshot, {}), iso_year=2026, iso_week=2)
    result = assessment_at()
    with pytest.raises(TypeError):
        aggregate_week(cast(CutoffSeries, {}), result)
    with pytest.raises(TypeError):
        aggregate_week(daily(result.required_session_dates), cast(WeekAssessment, {}))


@pytest.mark.parametrize("week_id", [(), (2026,), (2026, 2, 1), "2026-W02"])
def test_malformed_assessment_week_identity_is_rejected(week_id: object) -> None:
    result = assessment_at()
    with pytest.raises(ValueError, match="week_id"):
        aggregate_week(daily(result.required_session_dates), replace(result, week_id=cast(tuple[int, int], week_id)))


def test_invalid_week_record_resets_core_weekly_warmup_in_test_only_wiring() -> None:
    # This fixture assembles only already complete records, not a production
    # calendar state machine. No unknown/incomplete/empty week is skipped here.
    records = []
    for i in range(41):
        monday = cast(pd.Timestamp, MONDAY + pd.Timedelta(weeks=i))
        friday = cast(pd.Timestamp, monday + pd.Timedelta(days=4))
        assessment = assessment_at(cast(pd.Timestamp, (friday + pd.Timedelta(hours=16)).tz_localize("Asia/Taipei")), monday=monday)
        valid = np.array([True, True, i != 20, True, True], dtype=np.bool_)
        records.append(aggregate_week(daily(assessment.required_session_dates, cutoff=friday, valid=valid), assessment))
    assert all(record.has_bar for record in records)
    assert records[20].status == "invalid_bar" and records[20].last_session_date == MONDAY + pd.Timedelta(weeks=20, days=4)
    source = CutoffSeries(
        "FAKE_A",
        "synthetic-G",
        records[-1].decision_cutoff,
        BASIS,
        "completed_weekly",
        pd.DatetimeIndex([record.last_session_date for record in records]),
        np.array([np.nan if record.close is None else record.close for record in records], dtype=np.float64),
        np.array([record.bar_valid for record in records], dtype=np.bool_),
    )
    ma = moving_averages(source)
    assert np.isfinite(ma.ema[20][19])
    assert not ma.valid[20] and np.isnan(ma.ema[20][20:40]).all()
    assert np.isfinite(ma.ema[20][40]) and np.isfinite(ma.sma[20][40])
    assert len(source.close) == 41
    withheld = aggregate_week(daily(()), assessment_at(facts=facts_for()[:5]))
    assert not withheld.has_bar and withheld.status == "withheld_calendar"


def test_future_week_facts_and_prices_do_not_rewrite_saved_cutoff_results() -> None:
    original = assessment_at()
    source = daily(original.required_session_dates)
    original_bar = aggregate_week(source, original)
    later_facts = facts_for() + facts_for(cast(pd.Timestamp, MONDAY + pd.Timedelta(weeks=1)), known_at=aware("2026-01-12 09:00"))
    same_cutoff = assessment_at(facts=later_facts)
    assert same_cutoff == original
    assert asdict(same_cutoff) == asdict(original)
    assert aggregate_week(source, same_cutoff) == original_bar
    # A new later cutoff may carry future quotes; reassess the earlier week
    # with its unchanged facts. Only decision lineage changes, not the close.
    later = assessment_at(aware("2026-01-16 16:00"), facts=later_facts)
    extended = daily(pd.date_range(MONDAY, periods=12, freq="D"), cutoff=stamp("2026-01-16"))
    later_bar = aggregate_week(extended, later)
    assert later_bar.close == original_bar.close and later_bar.status == original_bar.status
    assert aggregate_week(source, original) == original_bar
    with pytest.raises(ValueError, match="beyond"):
        daily(extended.bar_dates, cutoff=source.decision_cutoff)


def test_immutable_outputs_no_input_mutation_and_no_call_aliasing() -> None:
    facts = facts_for()
    snapshot = CalendarSnapshot("cal", aware("2026-01-09 14:07"), facts, "synthetic")
    original_facts = tuple(asdict(fact) for fact in facts)
    result = assess_week(snapshot, iso_year=2026, iso_week=2)
    close = np.array([10, 11, 12, 13, 14], dtype=np.float64)
    valid = np.ones(5, dtype=np.bool_)
    source = daily(result.required_session_dates, close=close, valid=valid)
    source_dates = source.bar_dates.copy(deep=True)
    source_close = source.close.copy()
    source_valid = source.valid.copy()
    bar = aggregate_week(source, result)
    close[:] = 999
    valid[:] = False
    other = aggregate_week(daily(result.required_session_dates, close=close, valid=valid), result)
    assert bar.bar_valid and bar.close == 14 and not other.bar_valid
    np.testing.assert_array_equal(source.close, source_close)
    np.testing.assert_array_equal(source.valid, source_valid)
    assert source.bar_dates.equals(source_dates)
    assert tuple(asdict(fact) for fact in facts) == original_facts
    for value, name, replacement in [
        (facts[0], "session_state", 0),
        (snapshot, "calendar_id", "other"),
        (result, "status", "unknown"),
        (result.days[0], "session_state", 0),
        (bar, "close", 999),
        (bar.prices[0], "reasons", ("bad",)),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, replacement)


def test_runtime_no_io_and_public_api_has_no_loader_or_strategy_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    result = assessment_at()
    source = daily(result.required_session_dates)

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("I/O is outside single-week assessment")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(Path, "open", forbidden)
        guard.setattr(Path, "read_bytes", forbidden)
        guard.setattr(Path, "read_text", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(sqlite3, "connect", forbidden)
        assessed = assessment_at()
        bar = aggregate_week(source, assessed)
    assert bar.bar_valid
    assert tuple(inspect.signature(assess_week).parameters) == ("snapshot", "iso_year", "iso_week")
    assert tuple(inspect.signature(aggregate_week).parameters) == ("daily_series", "assessment")
    for record in (result, bar):
        names = {field.name for field in fields(record)}
        assert not names & {"first_confirmed_at", "confirmed_today", "weekly_turn", "historical_PIT_certified", "w", "w_previous", "signal"}
    tree = ast.parse(inspect.getsource(weeks))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    modules = {node.module for node in imports if isinstance(node, ast.ImportFrom)}
    assert modules == {"__future__", "dataclasses", "datetime", "typing", "research_core.multi_timeframe_ma_core_v1"}
    for node in imports:
        assert all(not alias.name.startswith("_") for alias in node.names)
