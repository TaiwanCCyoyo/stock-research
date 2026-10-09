"""Synthetic source-bound interruption plans; no market files or strategy runs."""

from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core.auction import CostSchedule
from research_core.chronology import CorporateEvidence, Scenario

ROOT = Path(__file__).resolve().parents[2]
TAIPEI = timezone(timedelta(hours=8))
REFERENCE, HALT, RESUMED = date(2019, 3, 12), date(2019, 3, 13), date(2019, 3, 14)
CODE = "2375"
HALT_SOURCE = "TWSE:TWTAWU:2375:2019-03-13"
Key = tuple[date, str]
Rows = dict[Key, dict[str, Any]]


def _load(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runtime = _load("close_review_sessions_runtime", "tasks/20261005-relative-strength-holding/runtime.py")
sessions = runtime._SESSIONS
valuation = _load("close_review_sessions_retained_valuation", "tasks/20260921-evening-pilot/valuation.py")


@dataclass
class SyntheticSession:
    raw: Rows
    panel: Rows
    calendar: tuple[date, ...]
    case: SimpleNamespace


def _rows(day: date, source: str, *, close: float | None, count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    available = datetime.combine(day, time(18), TAIPEI)
    raw = {
        "Market": "TWSE",
        "Open": close,
        "High": close,
        "Low": close,
        "Close": close,
        "Volume": 0 if close is None else 1_000,
        "available_at": available,
        "source_id": source,
    }
    panel = {
        "Market": "TWSE",
        # Deliberately unlike raw close: valuation must retain raw old-share units.
        "signal_close": None if close is None else Decimal("100"),
        "consecutive_usable": count,
        "available_at": available,
        "source_id": source,
    }
    return raw, panel


def _single_halt(recovery: int = 1) -> SyntheticSession:
    # Dates and 49.85 identify an explicit source fixture, not market analysis.
    case = SimpleNamespace(
        code=CODE,
        reference_day=REFERENCE,
        halt_day=HALT,
        resumed_day=RESUMED,
        reference_close_cents=4_985,
        reference_source_id="synthetic:reference-row",
        halt_source_id=HALT_SOURCE,
        halt_price_source_id="synthetic:halt-row",
        resumed_source_id="synthetic:resumed-row",
    )
    # A supplied synthetic session sequence, not a claim about exchange weekdays.
    recovery_days = tuple(RESUMED + timedelta(days=index) for index in range(recovery))
    calendar = (REFERENCE, HALT, *recovery_days)
    raw, panel = {}, {}
    raw[(REFERENCE, CODE)], panel[(REFERENCE, CODE)] = _rows(REFERENCE, case.reference_source_id, close=49.85, count=60)
    raw[(HALT, CODE)], panel[(HALT, CODE)] = _rows(HALT, case.halt_price_source_id, close=None, count=0)
    for count, day in enumerate(recovery_days, start=1):
        source = case.resumed_source_id if count == 1 else f"synthetic:recovery:{count}"
        raw[(day, CODE)], panel[(day, CODE)] = _rows(day, source, close=50.0, count=count)
    return SyntheticSession(raw, panel, calendar, case)


def _build(sample: SyntheticSession) -> Any:
    return sessions.build_session_plan(
        {"valuation": valuation},
        raw_by_key=sample.raw,
        panel_by_key=sample.panel,
        calendar=sample.calendar,
        halt_cases=(sample.case,),
    )


def test_bound_halt_is_a_mark_only_and_preserves_source_tables() -> None:
    sample = _single_halt()
    before = deepcopy((sample.raw, sample.panel))
    plan = _build(sample)
    key = (HALT, CODE)
    assert plan.calendar == sample.calendar
    assert set(plan.marks) == {key}
    assert dict(plan.confirmed_halts) == {key: HALT_SOURCE}
    assert dict(plan.statuses) == {key: ("confirmed_halt", HALT_SOURCE), (RESUMED, CODE): ("resumed_rewarming", HALT_SOURCE)}
    mark = plan.marks[key]
    assert isinstance(mark, valuation.ModeledHaltMark)
    assert mark.kind == "modeled_valuation_only"
    assert mark.raw_close_cents == 4_985
    assert mark.signal_close == Decimal("49.85")
    assert mark.reference_observed_at == datetime.combine(REFERENCE, time(13, 30), TAIPEI)
    assert mark.observed_at == datetime.combine(HALT, time(13, 30), TAIPEI)
    assert mark.available_at == datetime.combine(HALT, time(18), TAIPEI)
    assert mark.halt_evidence_id == HALT_SOURCE
    assert mark.source_id == f"{valuation.POLICY}|{HALT_SOURCE}|reference:{sample.case.reference_source_id}"
    assert (sample.raw, sample.panel) == before
    assert all(sample.raw[key][field] is None for field in ("Open", "High", "Low", "Close"))
    assert sample.raw[key]["Volume"] == 0
    assert sample.panel[key]["signal_close"] is None


@pytest.mark.parametrize("which", ["reference", "resumed"])
def test_named_halt_requires_adjacent_calendar_sessions(which: str) -> None:
    sample = _single_halt()
    if which == "reference":
        sample.case.reference_day = REFERENCE - timedelta(days=1)
        sample.calendar = (sample.case.reference_day, *sample.calendar)
        message = "preceding calendar session"
    else:
        sample.case.resumed_day = RESUMED + timedelta(days=1)
        sample.calendar = (*sample.calendar, sample.case.resumed_day)
        message = "next calendar session"
    with pytest.raises(ValueError, match=message):
        _build(sample)


def test_rewarming_ends_at_sixty_contiguous_observations() -> None:
    sample = _single_halt(recovery=61)
    plan = _build(sample)
    recovery = sample.calendar[2:]
    assert {key for key, value in plan.statuses.items() if value[0] == "resumed_rewarming"} == {(day, CODE) for day in recovery[:59]}
    assert (recovery[59], CODE) not in plan.statuses
    assert (recovery[60], CODE) not in plan.statuses
    assert set(plan.marks) == {(HALT, CODE)}
    assert set(plan.confirmed_halts) == {(HALT, CODE)}


@pytest.mark.parametrize("gap_kind", ["missing_row", "raw_close", "signal_close"])
def test_unknown_gap_stops_named_rewarming_exception(gap_kind: str) -> None:
    sample = _single_halt(recovery=5)
    gap = (sample.calendar[4], CODE)
    if gap_kind == "missing_row":
        del sample.raw[gap]
        del sample.panel[gap]
    elif gap_kind == "raw_close":
        sample.raw[gap]["Close"] = None
    else:
        sample.panel[gap]["signal_close"] = None
    # Later observations start a new unrelated run; they cannot inherit the case.
    for count, day in enumerate(sample.calendar[5:], start=1):
        sample.panel[(day, CODE)]["consecutive_usable"] = count
    plan = _build(sample)
    assert set(plan.statuses) == {(HALT, CODE), (sample.calendar[2], CODE), (sample.calendar[3], CODE)}
    assert gap not in plan.marks
    assert gap not in plan.confirmed_halts


@pytest.mark.parametrize("count", [1, 3, 60])
def test_rewarming_rejects_wrong_counter_including_sixtieth_observation(count: int) -> None:
    sample = _single_halt(recovery=60)
    sample.panel[(sample.calendar[count + 1], CODE)]["consecutive_usable"] = count + 1
    with pytest.raises(ValueError, match="reset contiguous feature history"):
        _build(sample)


@pytest.mark.parametrize(
    ("table", "day", "field", "value", "message"),
    [
        ("raw", REFERENCE, "source_id", "synthetic:wrong", "raw/panel source mismatch"),
        ("panel", REFERENCE, "source_id", "synthetic:wrong", "raw/panel source mismatch"),
        ("raw", HALT, "source_id", "synthetic:wrong", "volume/source differs"),
        ("raw", RESUMED, "source_id", "synthetic:wrong", "resumed row/source contradicts"),
        ("raw", REFERENCE, "Close", 50.0, "reference price/source contradicts"),
        ("raw", REFERENCE, "Market", "TPEX", "TWSE-only"),
        ("panel", REFERENCE, "Market", "TPEX", "TWSE-only"),
        ("raw", HALT, "Market", "TPEX", "conflicts with market price"),
        ("raw", RESUMED, "Market", "TPEX", "resumed row/source contradicts"),
        ("raw", HALT, "Open", 49.85, "conflicts with market price"),
        ("raw", HALT, "High", 49.85, "conflicts with market price"),
        ("raw", HALT, "Low", 49.85, "conflicts with market price"),
        ("raw", HALT, "Close", 49.85, "conflicts with market price"),
        ("raw", HALT, "Volume", 1, "volume/source differs"),
        ("raw", HALT, "Volume", None, "volume/source differs"),
        ("panel", HALT, "signal_close", 49.85, "must not be filled"),
    ],
)
def test_source_market_and_price_conflicts_are_rejected(table: str, day: date, field: str, value: Any, message: str) -> None:
    sample = _single_halt()
    getattr(sample, table)[(day, CODE)][field] = value
    with pytest.raises(ValueError, match=message):
        _build(sample)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reference_source_id", "synthetic:unbound-reference", "reference price/source contradicts"),
        ("halt_price_source_id", "synthetic:unbound-halt", "volume/source differs"),
        ("resumed_source_id", "synthetic:unbound-resumed", "resumed row/source contradicts"),
        ("halt_source_id", "synthetic:unapproved-halt", "limited to the confirmed record"),
    ],
)
def test_all_three_bound_row_sources_and_official_halt_identity_are_required(field: str, value: str, message: str) -> None:
    sample = _single_halt()
    setattr(sample.case, field, value)
    with pytest.raises(ValueError, match=message):
        _build(sample)


def _capital_fixture() -> tuple[Rows, Rows, tuple[date, ...], SimpleNamespace]:
    prior, resumed = date(2019, 9, 25), date(2019, 10, 7)
    calendar = (prior, date(2019, 9, 26), date(2019, 9, 27), date(2019, 9, 30), date(2019, 10, 1), resumed, date(2019, 10, 8))
    event = SimpleNamespace(code="2316", stopped_on=date(2019, 9, 26), resumed_on=resumed, source_id="synthetic:bound-capital-event")
    raw, panel = {}, {}
    for day, count in ((prior, 60), (calendar[1], 0), (resumed, 1), (calendar[-1], 2)):
        raw[(day, event.code)], panel[(day, event.code)] = _rows(day, f"synthetic:capital-row:{day}", close=None if count == 0 else 49.85, count=count)
    return raw, panel, calendar, event


def test_bound_capital_halt_preserves_old_share_marks_without_creating_bars() -> None:
    raw, panel, calendar, event = _capital_fixture()
    before = deepcopy((raw, panel))
    plan = sessions.build_session_plan({"valuation": valuation}, raw_by_key=raw, panel_by_key=panel, calendar=calendar, capital_events=(event,))
    expected = {(day, event.code) for day in calendar[1:5]}
    assert set(plan.marks) == expected
    assert dict(plan.confirmed_halts) == dict.fromkeys(expected, event.source_id)
    for key, mark in plan.marks.items():
        assert isinstance(mark, valuation.ModeledHaltMark)
        assert mark.raw_close_cents == 4_985
        assert mark.signal_close == Decimal("49.85")
        assert mark.reference_observed_at == datetime.combine(calendar[0], time(13, 30), TAIPEI)
        assert mark.observed_at.date() == key[0]
        assert mark.halt_evidence_id == event.source_id
        assert mark.source_id == f"{valuation.CAPITAL_POLICY}|{event.source_id}|reference:synthetic:capital-row:{calendar[0]}"
        assert plan.statuses[key] == ("confirmed_halt", event.source_id)
    assert plan.statuses[(calendar[-2], event.code)] == ("resumed_rewarming", event.source_id)
    assert plan.statuses[(calendar[-1], event.code)] == ("resumed_rewarming", event.source_id)
    assert (raw, panel) == before
    assert raw[(calendar[1], event.code)]["Close"] is None
    assert panel[(calendar[1], event.code)]["signal_close"] is None
    assert all((day, event.code) not in raw for day in calendar[2:5])


@pytest.mark.parametrize("field,value", [("code", "9999"), ("stopped_on", date(2019, 9, 27)), ("resumed_on", date(2019, 10, 8))])
def test_capital_exception_cannot_expand_beyond_bound_event(field: str, value: Any) -> None:
    raw, panel, calendar, event = _capital_fixture()
    setattr(event, field, value)
    with pytest.raises(ValueError, match="only the already-bound 2316"):
        sessions.build_session_plan({"valuation": valuation}, raw_by_key=raw, panel_by_key=panel, calendar=calendar, capital_events=(event,))


@pytest.mark.parametrize("name", ["marks", "statuses", "confirmed_halts"])
def test_session_plan_maps_are_immutable_copies(name: str) -> None:
    original = _build(_single_halt())
    maps = {field: dict(getattr(original, field)) for field in ("marks", "statuses", "confirmed_halts")}
    plan = sessions.SessionPlan(original.calendar, **maps)
    maps[name].clear()
    assert dict(getattr(plan, name)) == dict(getattr(original, name))
    with pytest.raises(TypeError):
        getattr(plan, name)[(HALT, CODE)] = None


def test_out_of_range_bound_cases_do_not_create_marks_or_statuses() -> None:
    sample = _single_halt()
    _, _, _, event = _capital_fixture()
    calendar = (date(2020, 1, 2),)
    plan = sessions.build_session_plan(
        {"valuation": valuation}, raw_by_key={}, panel_by_key={}, calendar=calendar, halt_cases=(sample.case,), capital_events=(event,)
    )
    assert plan.calendar == calendar
    assert not plan.marks and not plan.statuses and not plan.confirmed_halts


@pytest.mark.parametrize("missing", ["reference_row", "reference_session", "halt_row"])
def test_single_halt_requires_its_reference_and_halt_inputs(missing: str) -> None:
    sample = _single_halt()
    day = HALT if missing == "halt_row" else REFERENCE
    del sample.raw[(day, CODE)]
    del sample.panel[(day, CODE)]
    if missing == "reference_session":
        sample.calendar = sample.calendar[1:]
        message = "needs its reference and halted sessions"
    else:
        message = "halt row unavailable" if missing == "halt_row" else "reference is unavailable"
    with pytest.raises(ValueError, match=message):
        _build(sample)


def test_capital_halt_requires_real_old_share_reference() -> None:
    raw, panel, calendar, event = _capital_fixture()
    del raw[(calendar[0], event.code)]
    del panel[(calendar[0], event.code)]
    with pytest.raises(ValueError, match="reference is unavailable"):
        sessions.build_session_plan({"valuation": valuation}, raw_by_key=raw, panel_by_key=panel, calendar=calendar, capital_events=(event,))


def test_bound_plan_flows_through_runtime_to_native_next_session_sale() -> None:
    # Load retained code only: no source binder, data reader or old strategy runs.
    source_modules = _load("close_review_sessions_sources", "tasks/20261005-relative-strength-holding/source_modules.py")
    modules = source_modules.load_execution_adapters()
    execution = _load("close_review_sessions_execution", "tasks/20261005-relative-strength-holding/execution.py")
    sample = _single_halt(recovery=2)
    entry_day, exit_day = date(2019, 3, 11), date(2019, 3, 15)
    sample.calendar = (entry_day, *sample.calendar)
    sample.raw[(entry_day, CODE)], sample.panel[(entry_day, CODE)] = _rows(entry_day, "synthetic:entry-row", close=49.8, count=61)
    sample.raw[(RESUMED, CODE)].update(Open=49.9, High=49.9, Low=49.9, Close=49.9)
    sample.raw[(exit_day, CODE)].update(Open=49.95, High=49.95, Low=49.95, Close=49.95)
    case = modules["resumption_execution"].ResumptionCase(**vars(sample.case))
    for day in sample.calendar:
        key = (day, CODE)
        sample.raw[key].update(Code=CODE, Date=pd.Timestamp(day))
        sample.panel[key].update(
            Code=CODE,
            Date=pd.Timestamp(day),
            signal_close=sample.raw[key]["Close"],
            ma20=49.0 if day < HALT else float("nan"),
            ma60=48.0 if day < HALT else float("nan"),
            ret60=0.1 if day < HALT else None,
            rs60=1.0 if day < HALT else None,
            rank_eligible=day < HALT,
            liquidity_twd=30_000_000.0,
            eligible=day == entry_day,
            eligibility_reason="eligible" if day == entry_day else "synthetic:ineligible",
            panel_source_id="synthetic:hand-supplied-h05-panel",
        )
    raw = pd.DataFrame([sample.raw[(day, CODE)] for day in sample.calendar])
    panel = pd.DataFrame([sample.panel[(day, CODE)] for day in sample.calendar])
    original_raw, original_panel = raw.copy(deep=True), panel.copy(deep=True)
    plan = sessions.build_session_plan(modules, raw_by_key=sample.raw, panel_by_key=sample.panel, calendar=sample.calendar, halt_cases=(case,))
    assert isinstance(plan, runtime._SESSIONS.SessionPlan)
    diagnostics: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    factory = execution.build_execution_factory(
        modules,
        raw_by_key=sample.raw,
        calendar=sample.calendar,
        economics=SimpleNamespace(corporate_keys=frozenset(), event_limits={}),
        halt_cases=(case,),
        no_trade=None,
        confirmed_halts=plan.confirmed_halts,
        diagnostics=diagnostics,
        resumption_audit=audit,
    )
    costs = CostSchedule(Fraction(0), 0, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
    inputs = runtime.prepare_inputs(
        raw,
        panel,
        calendar=sample.calendar,
        costs=costs,
        execution_factory=factory,
        corporate_factory=lambda: lambda _since, _until, _prefix: CorporateEvidence("synthetic:complete-empty-corporate-domain", (), True),
        calendar_id="synthetic:named-halt-end-to-end",
        calendar_complete=True,
        history_start=datetime.combine(entry_day - timedelta(days=1), time(20), TAIPEI),
        exit_ma_days=20,
        session_plan=plan,
    )
    result = inputs.run(Scenario("synthetic:baseline", frozenset(), 0))
    assert result.status == "complete", result.stop_reason
    buy = result.decisions[0].requests[0]
    quantity = buy.intent.qty
    assert buy.intent.side == "BUY" and quantity > 0
    assert result.snapshots[1].holdings[CODE].qty == quantity
    assert inputs.frames[2].prices[CODE] is plan.marks[(HALT, CODE)]
    assert result.snapshots[2].holdings[CODE].qty == quantity
    assert result.snapshots[2].cash_cents == result.snapshots[1].cash_cents
    assert result.snapshots[2].equity_cents == result.snapshots[1].equity_cents
    assert result.decisions[2].requests == ()
    sell = result.decisions[3].requests[0]
    assert sell.intent.side == "SELL" and sell.intent.qty == quantity
    assert sell.intent.decision_at == datetime.combine(RESUMED, time(20), TAIPEI)
    assert sell.intent.order_id != buy.intent.order_id
    assert sell.exchange == "TWSE" and sell.venue == "regular_open"
    assert [event["action"] for event in result.events] == ["BUY", "SELL"]
    assert result.events[0]["date"] == datetime.combine(REFERENCE, time(9), TAIPEI).isoformat()
    assert result.events[1]["date"] == datetime.combine(exit_day, time(9), TAIPEI).isoformat()
    assert result.snapshots[-1].holdings == {} and result.pending == ()
    # Zero synthetic costs isolate actual raw fill prices, 49.85 then 49.95.
    assert result.snapshots[-1].cash_cents == inputs.initial_cash_cents + quantity * (4_995 - 4_985)
    assert not diagnostics
    # No advice existed on the halted close, so there is no order on resume open.
    assert not audit
    pd.testing.assert_frame_equal(raw, original_raw)
    pd.testing.assert_frame_equal(panel, original_panel)
