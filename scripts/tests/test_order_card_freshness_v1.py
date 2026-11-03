"""Artificial calendar and dataset metadata only; no market or card execution."""

from __future__ import annotations

import builtins
import logging
import socket
import sqlite3
import urllib.request
from dataclasses import FrozenInstanceError, asdict, dataclass, replace
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from research_core import multi_timeframe_ma_weeks_v1 as weeks
from research_core import order_card_freshness_v1 as freshness


def _date(value: str) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(value))


def _aware(value: str) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(value, tz="Asia/Taipei"))


def _changes(field: str, value: object) -> dict[str, Any]:
    return {field: value}


@dataclass(frozen=True)
class Fixture:
    request: freshness.FreshnessRequest
    snapshot: weeks.CalendarSnapshot
    observations: tuple[freshness.DatasetObservation, ...]


def _fixture() -> Fixture:
    expected = _date("2026-01-09")
    requirements = tuple(
        freshness.DatasetRequirement(dataset_id=name, definition=f"{name}.v1", generation=f"artificial-{name}-generation") for name in ("B", "A")
    )
    request = freshness.FreshnessRequest(expected_session=expected, universe_id="artificial-universe", requirements=requirements)
    known = _aware("2026-01-01 08:00")
    snapshot = weeks.CalendarSnapshot(
        "artificial-calendar",
        _aware("2026-01-12 08:00"),
        (
            weeks.CalendarFact(expected, 1, known, _aware("2026-01-09 13:30"), "artificial-session"),
            weeks.CalendarFact(_date("2026-01-10"), 0, known, None, "artificial-Saturday-closure"),
            weeks.CalendarFact(_date("2026-01-11"), 0, known, None, "artificial-Sunday-closure"),
            # A declared Monday closure intentionally defeats weekday guesses.
            weeks.CalendarFact(_date("2026-01-12"), 0, known, None, "artificial-Monday-closure"),
        ),
        "Artificial caller-selected fact versions; no source/PIT certification",
    )
    observations = tuple(
        freshness.DatasetObservation(
            dataset_id=requirement.dataset_id,
            definition=requirement.definition,
            generation=requirement.generation,
            calendar_id=snapshot.calendar_id,
            universe_id=request.universe_id,
            as_of_session=expected,
            available_at=_aware("2026-01-09 18:00"),
            status="complete",
            source_ref=f"artificial-metadata:{requirement.dataset_id}",
        )
        for requirement in requirements
    )
    return Fixture(request, snapshot, observations)


def _assess(f: Fixture) -> freshness.FreshnessAssessment:
    return freshness.assess_card_freshness(f.request, f.snapshot, f.observations)


def test_current_session_and_explicit_closures_pass_with_complete_evidence() -> None:
    f = _fixture()
    result = _assess(f)
    assert result.freshness_ready and result.reasons == ()
    assert result.expected_session == f.request.expected_session
    assert result.universe_id == f.request.universe_id
    assert result.calendar_id == f.snapshot.calendar_id
    assert result.decision_at == f.snapshot.decision_at
    assert result.calendar_availability_note == f.snapshot.availability_note
    assert result.calendar_days == weeks.assess_calendar_range(f.snapshot, first_day=_date("2026-01-09"), last_day=_date("2026-01-12"))
    assert tuple(day.date for day in result.calendar_days) == tuple(pd.date_range("2026-01-09", "2026-01-12"))
    assert tuple(day.session_state for day in result.calendar_days) == (1, 0, 0, 0)
    assert tuple(dataset.requirement.dataset_id for dataset in result.datasets) == ("A", "B")
    by_id = {observation.dataset_id: observation for observation in f.observations}
    for dataset in result.datasets:
        assert dataset.observation == by_id[dataset.requirement.dataset_id]
        assert dataset.freshness_ready and dataset.reasons == ()
    assert result.validation_scope and "source" in result.validation_scope.lower()


def test_public_range_is_inclusive_and_matches_existing_week_day_evidence() -> None:
    f = _fixture()
    result = weeks.assess_calendar_range(f.snapshot, first_day=_date("2026-01-08"), last_day=_date("2026-01-11"))
    original = weeks.assess_week(f.snapshot, iso_year=2026, iso_week=2)
    assert result == original.days[3:]
    assert result[0].reasons == ("missing_fact",)
    assert result[0].declared_state is None and result[0].session_state == -1
    single = weeks.assess_calendar_range(f.snapshot, first_day=_date("2026-01-09"), last_day=_date("2026-01-09"))
    assert len(single) == 1 and single[0] == original.days[4]


@pytest.mark.parametrize("first,last", [("2026-01-12", "2026-01-09"), ("2026-01-09 01:00", "2026-01-12"), ("2026-01-09", "2026-01-12 01:00")])
def test_range_rejects_reversed_or_non_date_boundaries(first: str, last: str) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        weeks.assess_calendar_range(f.snapshot, first_day=_date(first), last_day=_date(last))


@pytest.mark.parametrize("day_index", [1, 2, 3])
@pytest.mark.parametrize(
    "case,reason",
    [("missing", "missing_fact"), ("unknown", "session_state_unknown"), ("unknown_time", "known_at_unknown"), ("future_time", "fact_not_yet_known")],
)
def test_every_civil_day_must_have_known_closure_not_a_weekend_guess(day_index: int, case: str, reason: str) -> None:
    f = _fixture()
    facts = list(f.snapshot.facts)
    day = facts[day_index].date
    if case == "missing":
        facts.pop(day_index)
    elif case == "unknown":
        facts[day_index] = replace(facts[day_index], session_state=-1)
    elif case == "unknown_time":
        facts[day_index] = replace(facts[day_index], known_at=None)
    else:
        facts[day_index] = replace(facts[day_index], known_at=f.snapshot.decision_at + pd.Timedelta(nanoseconds=1))
    result = _assess(replace(f, snapshot=replace(f.snapshot, facts=tuple(facts))))
    assert not result.freshness_ready and result.reasons
    evidence = next(item for item in result.calendar_days if item.date == day)
    assert reason in evidence.reasons and evidence.session_state == -1
    assert result.reasons == (reason,)
    assert all(dataset.freshness_ready for dataset in result.datasets)


@pytest.mark.parametrize(
    "case,reason",
    [
        ("missing", "missing_fact"),
        ("unknown", "session_state_unknown"),
        ("unknown_time", "known_at_unknown"),
        ("future_time", "fact_not_yet_known"),
        ("unknown_close", "session_close_unknown"),
        ("unclosed", "session_not_closed"),
        ("closed", None),
    ],
)
def test_expected_day_itself_requires_known_closed_session(case: str, reason: str | None) -> None:
    f = _fixture()
    facts = list(f.snapshot.facts)
    decision = f.snapshot.decision_at
    if case == "missing":
        facts.pop(0)
    elif case == "unknown":
        facts[0] = replace(facts[0], session_state=-1)
    elif case == "unknown_time":
        facts[0] = replace(facts[0], known_at=None)
    elif case == "future_time":
        facts[0] = replace(facts[0], known_at=decision + pd.Timedelta(nanoseconds=1))
    elif case == "unknown_close":
        facts[0] = replace(facts[0], close_at=None)
    elif case == "unclosed":
        decision = _aware("2026-01-09 13:29:59.999999999")
    else:
        facts[0] = replace(facts[0], session_state=0, close_at=None)
    result = _assess(replace(f, snapshot=replace(f.snapshot, decision_at=decision, facts=tuple(facts))))
    assert not result.freshness_ready and result.reasons
    if reason is not None:
        assert reason in result.calendar_days[0].reasons
    else:
        assert result.calendar_days[0].session_state == 0


@pytest.mark.parametrize("decision", ["2026-01-12 08:00", "2026-01-12 13:30"])
def test_newer_session_withholds_even_if_open_and_old_sources_are_recently_published(decision: str) -> None:
    f = _fixture()
    facts = (*f.snapshot.facts[:-1], replace(f.snapshot.facts[-1], session_state=1, close_at=_aware("2026-01-12 13:30")))
    observations = tuple(replace(item, available_at=_aware(decision)) for item in f.observations)
    result = _assess(replace(f, snapshot=replace(f.snapshot, decision_at=_aware(decision), facts=facts), observations=observations))
    assert not result.freshness_ready and result.reasons
    assert result.calendar_days[-1].session_state == 1
    assert "newer_session" in result.reasons
    assert all(dataset.freshness_ready for dataset in result.datasets)


def test_future_expected_session_is_withheld_without_fabricating_calendar_range() -> None:
    f = _fixture()
    result = _assess(replace(f, request=replace(f.request, expected_session=_date("2026-01-13"))))
    assert not result.freshness_ready and result.reasons
    assert result.calendar_days == ()
    assert result.reasons == ("expected_session_future", "dataset_not_ready")


@pytest.mark.parametrize("delta,ready", [(-1, True), (0, True), (1, False)])
def test_session_close_boundary_is_inclusive_to_nanosecond(delta: int, ready: bool) -> None:
    f = _fixture()
    close = _aware("2026-01-09 13:30")
    decision = close - pd.Timedelta(nanoseconds=delta)
    observations = tuple(replace(item, available_at=close - pd.Timedelta(hours=1)) for item in f.observations)
    result = _assess(replace(f, snapshot=replace(f.snapshot, decision_at=decision), observations=observations))
    assert result.freshness_ready is ready


@pytest.mark.parametrize("field", ["known_at", "available_at"])
@pytest.mark.parametrize("delta,ready", [(-1, True), (0, True), (1, False)])
def test_known_and_available_time_equality_and_future_boundary(field: str, delta: int, ready: bool) -> None:
    f = _fixture()
    timestamp = f.snapshot.decision_at + pd.Timedelta(nanoseconds=delta)
    if field == "known_at":
        f = replace(f, snapshot=replace(f.snapshot, facts=tuple(replace(fact, known_at=timestamp) for fact in f.snapshot.facts)))
    else:
        f = replace(f, observations=tuple(replace(item, available_at=timestamp) for item in f.observations))
    assert _assess(f).freshness_ready is ready


def test_utc_equivalent_instants_and_taipei_decision_civil_day_are_identical() -> None:
    f = _fixture()
    # UTC Sunday afternoon is already Monday in Taipei: Monday evidence is required.
    decision = _aware("2026-01-12 00:00")
    local = replace(f, snapshot=replace(f.snapshot, decision_at=decision))
    utc_facts = tuple(
        replace(
            fact,
            known_at=None if fact.known_at is None else fact.known_at.tz_convert("UTC"),
            close_at=None if fact.close_at is None else fact.close_at.tz_convert("UTC"),
        )
        for fact in local.snapshot.facts
    )
    utc = replace(
        local,
        snapshot=replace(local.snapshot, decision_at=decision.tz_convert("UTC"), facts=utc_facts),
        observations=tuple(replace(item, available_at=cast(pd.Timestamp, item.available_at).tz_convert("UTC")) for item in f.observations),
    )
    assert _assess(utc) == _assess(local)
    assert _assess(utc).calendar_days[-1].date == _date("2026-01-12")
    without_monday = replace(utc, snapshot=replace(utc.snapshot, facts=utc.snapshot.facts[:-1]))
    assert not _assess(without_monday).freshness_ready


@pytest.mark.parametrize("status", ["missing", "unknown", "updating"])
def test_noncomplete_dataset_status_withholds(status: freshness.DatasetStatus) -> None:
    f = _fixture()
    result = _assess(replace(f, observations=(replace(f.observations[0], status=status), f.observations[1])))
    assert not result.freshness_ready and result.reasons
    affected = next(item for item in result.datasets if item.requirement.dataset_id == "B")
    assert not affected.freshness_ready and affected.reasons
    assert affected.reasons == (f"status_{status}",)
    assert result.reasons == ("dataset_not_ready",)
    assert affected.observation is not None and affected.observation.status == status


@pytest.mark.parametrize(
    "field,value",
    [
        ("definition", "other.v1"),
        ("generation", "other-generation"),
        ("calendar_id", "other-calendar"),
        ("universe_id", "other-universe"),
        ("as_of_session", _date("2026-01-08")),
        ("as_of_session", _date("2026-01-12")),
        ("as_of_session", None),
        ("available_at", None),
    ],
)
def test_each_required_identity_and_session_is_checked(field: str, value: object) -> None:
    f = _fixture()
    changed = replace(f.observations[0], **_changes(field, value))
    result = _assess(replace(f, observations=(changed, f.observations[1])))
    assert not result.freshness_ready
    affected = next(item for item in result.datasets if item.requirement.dataset_id == changed.dataset_id)
    assert affected.observation == changed and affected.reasons and not affected.freshness_ready
    reason = {"as_of_session": "as_of_session_unknown" if value is None else "as_of_session_mismatch", "available_at": "available_at_unknown"}.get(
        field, f"{field}_mismatch"
    )
    assert affected.reasons == (reason,)
    assert any(item.freshness_ready for item in result.datasets)


def test_missing_observation_withholds_and_retains_expected_metadata() -> None:
    f = _fixture()
    result = _assess(replace(f, observations=f.observations[1:]))
    missing = next(item for item in result.datasets if item.requirement.dataset_id == "B")
    assert not result.freshness_ready and not missing.freshness_ready
    assert missing.observation is None and missing.requirement == f.request.requirements[0]
    assert missing.reasons
    assert missing.reasons == ("missing_observation",)


def test_all_source_failures_have_stable_order_and_global_reason_is_deduplicated() -> None:
    f = _fixture()
    observations = tuple(
        replace(
            item,
            definition="other.v1",
            generation="other-generation",
            calendar_id="other-calendar",
            universe_id="other-universe",
            status="updating",
            as_of_session=None,
            available_at=None,
        )
        for item in f.observations
    )
    result = _assess(replace(f, observations=observations))
    assert result.reasons == ("dataset_not_ready",)
    for dataset in result.datasets:
        assert dataset.reasons == (
            "definition_mismatch",
            "generation_mismatch",
            "calendar_id_mismatch",
            "universe_id_mismatch",
            "status_updating",
            "as_of_session_unknown",
            "available_at_unknown",
        )


def test_repeated_calendar_failures_retain_each_day_and_deduplicate_global_codes() -> None:
    f = _fixture()
    facts = tuple(replace(fact, known_at=f.snapshot.decision_at + pd.Timedelta(nanoseconds=1)) for fact in f.snapshot.facts)
    result = _assess(replace(f, snapshot=replace(f.snapshot, facts=facts)))
    assert result.reasons == ("expected_session_not_known_session", "fact_not_yet_known")
    assert len(result.calendar_days) == 4
    assert all(day.reasons == ("fact_not_yet_known",) for day in result.calendar_days)


def test_fresh_metadata_does_not_make_old_dataset_fresh() -> None:
    f = _fixture()
    stale = tuple(replace(item, as_of_session=_date("2026-01-08"), available_at=f.snapshot.decision_at) for item in f.observations)
    result = _assess(replace(f, observations=stale))
    assert not result.freshness_ready
    assert all(not item.freshness_ready and item.reasons for item in result.datasets)
    assert all(item.observation is not None and item.observation.available_at == f.snapshot.decision_at for item in result.datasets)


@pytest.mark.parametrize("case", ["duplicate", "unexpected"])
def test_duplicate_or_extra_observation_ids_are_input_errors(case: str) -> None:
    f = _fixture()
    extra = f.observations[0] if case == "duplicate" else replace(f.observations[0], dataset_id="UNREQUESTED")
    with pytest.raises(ValueError):
        _assess(replace(f, observations=(*f.observations, extra)))


@pytest.mark.parametrize("field", ["dataset_id", "definition", "generation", "calendar_id", "universe_id", "source_ref"])
@pytest.mark.parametrize("value", ["", " ", None])
def test_malformed_observation_text_is_an_input_error(field: str, value: object) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _assess(replace(f, observations=(replace(f.observations[0], **_changes(field, value)), f.observations[1])))


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "ready"),
        ("status", True),
        ("as_of_session", pd.NaT),
        ("as_of_session", _date("2026-01-09 12:00")),
        ("as_of_session", _aware("2026-01-09 00:00")),
        ("as_of_session", "2026-01-09"),
        ("available_at", pd.NaT),
        ("available_at", _date("2026-01-09 18:00")),
        ("available_at", "2026-01-09T18:00:00+08:00"),
    ],
)
def test_malformed_observation_dates_status_and_naive_instants_are_errors(field: str, value: object) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _assess(replace(f, observations=(replace(f.observations[0], **_changes(field, value)), f.observations[1])))


@pytest.mark.parametrize("field", ["dataset_id", "definition", "generation"])
def test_requirement_fields_are_explicit_nonempty_text(field: str) -> None:
    f = _fixture()
    requirements = (replace(f.request.requirements[0], **_changes(field, " ")), f.request.requirements[1])
    with pytest.raises(ValueError):
        _assess(replace(f, request=replace(f.request, requirements=requirements)))


@pytest.mark.parametrize("case", ["empty", "duplicate", "list"])
def test_requirements_are_nonempty_unique_explicit_tuple(case: str) -> None:
    f = _fixture()
    choices = {"empty": (), "duplicate": (f.request.requirements[0], f.request.requirements[0]), "list": list(f.request.requirements)}
    with pytest.raises(ValueError):
        _assess(replace(f, request=replace(f.request, **_changes("requirements", choices[case]))))


@pytest.mark.parametrize(
    "field,value",
    [
        ("universe_id", " "),
        ("expected_session", pd.NaT),
        ("expected_session", _date("2026-01-09 12:00")),
        ("expected_session", _aware("2026-01-09 00:00")),
        ("expected_session", "2026-01-09"),
    ],
)
def test_malformed_request_is_rejected(field: str, value: object) -> None:
    f = _fixture()
    with pytest.raises(ValueError):
        _assess(replace(f, request=replace(f.request, **_changes(field, value))))


def test_input_immutability_deterministic_order_and_repeated_calls() -> None:
    f = _fixture()
    before = asdict(f)
    first = _assess(f)
    reordered = replace(f, observations=tuple(reversed(f.observations)), request=replace(f.request, requirements=tuple(reversed(f.request.requirements))))
    assert first == _assess(reordered) == _assess(f)
    assert asdict(f) == before
    with pytest.raises(FrozenInstanceError):
        first.freshness_ready = False  # type: ignore[misc]
    assert isinstance(first.datasets, tuple) and isinstance(first.calendar_days, tuple) and isinstance(first.reasons, tuple)


def test_assessment_uses_no_source_readers_database_files_network_or_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import maintained_adjusted_daily as maintained
    from research_core import momentum_only_v1 as canonical

    f = _fixture()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("freshness assessment must stay pure and use explicit metadata")

    with monkeypatch.context() as patch:
        logger = logging.getLogger(freshness.__name__)
        patch.setattr(logger, "level", logging.DEBUG)
        patch.setattr(logger, "_cache", {})
        patch.setattr(logging.Logger, "_log", forbidden)
        assert logger.isEnabledFor(logging.DEBUG)
        for owner, name in [
            (weeks, "assess_week"),
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
        assert _assess(f).freshness_ready
