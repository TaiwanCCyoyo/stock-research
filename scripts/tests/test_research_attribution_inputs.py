"""Recorded-prefix attribution integration; entirely hand-calculable fixtures."""

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import pytest

from research_core.attribution import AttributionError, non_hit_attribution
from research_core.attribution_inputs import build_attribution_inputs
from research_core.ledger import LedgerError


def fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool | None]]:
    events = [
        {"action": "BUY", "code": "B", "qty": 1, "total": -100},
        {"action": "BUY", "code": "A", "qty": 2, "total": -102},
        {"action": "DIVIDEND_ENTITLEMENT", "code": "A", "total": 0, "amount": 10, "entitlement_id": "old-A"},
        {"action": "SPLIT", "code": "A", "qty": 2, "old_qty": 2, "new_qty": 4, "total": 0},
        {"action": "SELL", "code": "A", "qty": 2, "total": 44},
        {"action": "SELL", "code": "A", "qty": 2, "total": 44},
        {"action": "BUY", "code": "A", "qty": 1, "total": -40},
        {"action": "DIVIDEND", "code": "A", "total": 10, "entitlement_id": "old-A"},
        {"action": "SELL", "code": "A", "qty": 1, "total": 30},
        {"action": "SELL", "code": "B", "qty": 1, "total": 250},
    ]
    # Explicit pre/post marks: an event does not supply a replacement price for
    # other holdings. No corporate-action date or price is inferred by the bridge.
    before = [
        {},
        {"B": 100},
        {"B": 100, "A": 50},
        {"B": 100, "A": 45},
        {"B": 100, "A": 22.5},
        {"B": 100, "A": 22.5},
        {"B": 100},
        {"B": 100, "A": 40},
        {"B": 100, "A": 30},
        {"B": 250},
    ]
    after = [
        {"B": 100},
        {"B": 100, "A": 50},
        {"B": 100, "A": 45},
        {"B": 100, "A": 22.5},
        {"B": 100, "A": 22.5},
        {"B": 100},
        {"B": 100, "A": 40},
        {"B": 100, "A": 40},
        {"B": 100},
        {},
    ]
    checkpoints = []
    for index, event in enumerate(events):
        stamp = f"2026-01-{index + 1:02d}T09:00:00+08:00"
        event["date"] = stamp
        checkpoints.extend([
            {"date": stamp, "event_count": index, "raw_marks": before[index]},
            {"date": stamp, "event_count": index + 1, "raw_marks": after[index]},
        ])
    return events, checkpoints, {"0": True, "1": False, "6": False}


def build(events: list[dict[str, Any]], checkpoints: list[dict[str, Any]], labels: dict[str, bool | None]) -> dict[str, Any]:
    return build_attribution_inputs(initial_cash=1_000, events=events, checkpoints=checkpoints, classifications=labels)


def test_actual_attempts_feed_reducer_without_winner_masking() -> None:
    events, checkpoints, labels = fixture()
    original = deepcopy((events, checkpoints, labels))
    inputs = build(events, checkpoints, labels)
    assert inputs["schema_version"] == "attribution-inputs.v1"
    assert inputs["attribution_only"] is True
    assert inputs["initial_equity"] == 1_000
    assert [(item["id"], item["entry_index"], item["exit_index"], item["captured_pnl_twd"]) for item in inputs["attempts"]] == [
        ("0", 1, 19, 150),
        ("1", 3, 11, -4),
        ("6", 13, 17, -10),
    ]
    assert inputs["checkpoints"][-1]["equity"] == 1_136
    # The old entitlement is paid after re-entry, but still belongs to attempt 1.
    assert inputs["checkpoints"][14]["attempt_pnl"] == {"0": 0, "1": -4, "6": 0}
    assert inputs["checkpoints"][15]["attempt_pnl"] == inputs["checkpoints"][14]["attempt_pnl"]
    result = non_hit_attribution(inputs["attempts"], inputs["checkpoints"], initial_equity=inputs["initial_equity"], span=2)
    assert result["window_summary"]["status"] == "ok"
    assert result["whole_study"]["net_pnl_twd"] == -14
    assert result["windows"][0]["attempt_ids"] == ["1", "6"]
    assert result["windows"][0]["start_index"] == 2
    assert result["windows"][0]["end_index"] == 17
    assert (events, checkpoints, labels) == original


def test_open_attempt_is_kept_unknown_with_no_invented_exit() -> None:
    events, checkpoints, labels = fixture()
    labels["0"] = None
    inputs = build(events[:9], checkpoints[:18], labels)
    assert inputs["attempts"][0]["exit_index"] is None
    assert inputs["attempts"][0]["captured_pnl_twd"] is None
    result = non_hit_attribution(inputs["attempts"], inputs["checkpoints"], initial_equity=1_000, span=3)
    assert result["unknown_attempt_ids"] == ["0"]
    assert result["window_summary"]["status"] == "unavailable"


def test_captured_profit_does_not_include_unpaid_receivable() -> None:
    stamp = "2026-01-01T09:00:00+08:00"
    events = [
        {"date": stamp, "action": "BUY", "code": "A", "qty": 1, "total": -100},
        {"date": stamp, "action": "DIVIDEND_ENTITLEMENT", "code": "A", "total": 0, "amount": 100, "entitlement_id": "x"},
        {"date": stamp, "action": "SELL", "code": "A", "qty": 1, "total": 90},
    ]
    checkpoints = [{"date": stamp, "event_count": i, "raw_marks": {"A": 90} if i in (1, 2) else {}} for i in range(4)]
    inputs = build(events, checkpoints, {"0": None})
    assert inputs["attempts"][0]["captured_pnl_twd"] == -10
    assert inputs["checkpoints"][-1]["attempt_pnl"] == {"0": 90}
    # Supplying a false hit cannot turn unpaid income into captured profit.
    with pytest.raises(AttributionError):
        falsely_labeled = build(events, checkpoints, {"0": True})
        non_hit_attribution(falsely_labeled["attempts"], falsely_labeled["checkpoints"], initial_equity=1_000, span=1)


@pytest.mark.parametrize(
    "mutation",
    [
        "skip_event",
        "no_initial",
        "incomplete_final",
        "backward_count",
        "boolean_count",
        "late_post",
        "early_post",
        "no_immediate_pre_buy",
        "future_unconsumed_event",
        "naive_checkpoint",
        "naive_event",
        "reversed_event_time",
        "unknown_label_id",
        "missing_label",
        "numeric_label",
        "open_known_label",
        "legacy_dividend",
        "missing_mark",
    ],
)
def test_incomplete_or_contradictory_evidence_is_rejected(mutation: str) -> None:
    events, checkpoints, labels = fixture()
    if mutation == "skip_event":
        del checkpoints[5:7]  # count jumps from 2 to 4
    elif mutation == "no_initial":
        checkpoints = checkpoints[1:]
    elif mutation == "incomplete_final":
        checkpoints = checkpoints[:-1]
    elif mutation == "backward_count":
        checkpoints[4]["event_count"] = 0
    elif mutation == "boolean_count":
        checkpoints[0]["event_count"] = False
    elif mutation == "late_post":
        checkpoints[1]["date"] = "2026-01-01T09:01:00+08:00"
    elif mutation == "early_post":
        checkpoints[1]["date"] = "2026-01-01T08:59:00+08:00"
    elif mutation == "no_immediate_pre_buy":
        del checkpoints[2]
    elif mutation == "future_unconsumed_event":
        checkpoints[2]["date"] = "2026-01-03T09:00:00+08:00"
    elif mutation == "naive_checkpoint":
        checkpoints[0]["date"] = "2026-01-01"
    elif mutation == "naive_event":
        events[0]["date"] = "2026-01-01"
    elif mutation == "reversed_event_time":
        events[2]["date"] = events[0]["date"]
    elif mutation == "unknown_label_id":
        labels["other"] = False
    elif mutation == "missing_label":
        del labels["6"]
    elif mutation == "numeric_label":
        labels["0"] = 1  # type: ignore[assignment]
    elif mutation == "open_known_label":
        events, checkpoints = events[:9], checkpoints[:18]
    elif mutation == "legacy_dividend":
        del events[7]["entitlement_id"]
    elif mutation == "missing_mark":
        del checkpoints[3]["raw_marks"]["B"]
    with pytest.raises((AttributionError, LedgerError)):
        build(events, checkpoints, labels)


def test_empty_account_and_extra_close_checkpoint_are_supported() -> None:
    empty = build([], [{"date": "2026-01-01T00:00:00+08:00", "event_count": 0, "raw_marks": {}}], {})
    assert empty["attempts"] == []
    assert empty["checkpoints"][0]["equity"] == 1_000
    events, checkpoints, labels = fixture()
    checkpoints.insert(2, {"date": "2026-01-01T13:30:00+08:00", "event_count": 1, "raw_marks": {"B": 110}})
    inputs = build(events, checkpoints, labels)
    assert inputs["checkpoints"][2]["equity"] == 1_010
    assert inputs["attempts"][1]["entry_index"] == 4


def test_same_time_order_and_add_do_not_create_a_new_attempt() -> None:
    stamp = "2026-01-01T09:00:00+08:00"
    events = [
        {"date": stamp, "action": "BUY", "code": "A", "qty": 1, "total": -100},
        {"date": stamp, "action": "BUY", "code": "A", "qty": 1, "total": -100},
        {"date": stamp, "action": "SELL", "code": "A", "qty": 2, "total": 210},
    ]
    checkpoints = [{"date": stamp, "event_count": i, "raw_marks": {"A": 100} if i in (1, 2) else {}} for i in range(4)]
    inputs = build(events, checkpoints, {"0": False})
    assert len(inputs["attempts"]) == 1
    assert inputs["attempts"][0]["captured_pnl_twd"] == 10
    assert inputs["attempts"][0]["exit_index"] == 3


def test_sixth_concurrent_holding_is_rejected() -> None:
    stamp = "2026-01-01T09:00:00+08:00"
    events = [{"date": stamp, "action": "BUY", "code": str(i), "qty": 1, "total": -10} for i in range(6)]
    checkpoints = [{"date": stamp, "event_count": i, "raw_marks": {str(j): 10 for j in range(i)}} for i in range(7)]
    with pytest.raises(LedgerError):
        build(events, checkpoints, {str(i): None for i in range(6)})


@pytest.mark.parametrize("limit", [None, True, 0, -1, 5.0])
def test_position_limit_cannot_silently_disable_capacity(limit: Any) -> None:
    with pytest.raises(AttributionError, match="max_positions"):
        build_attribution_inputs(
            initial_cash=1_000,
            events=[],
            checkpoints=[{"date": "2026-01-01T00:00:00+08:00", "event_count": 0, "raw_marks": {}}],
            classifications={},
            max_positions=limit,
        )


def test_twenty_actual_non_hits_keep_small_wins_and_exclude_the_winner() -> None:
    events: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    labels: dict[str, bool | None] = {"0": True}
    start = datetime.fromisoformat("2026-01-01T09:00:00+08:00")

    def record(event: dict[str, Any], before: dict[str, float], after: dict[str, float]) -> None:
        index = len(events)
        stamp = (start + timedelta(days=index)).isoformat()
        events.append({**event, "date": stamp})
        checkpoints.extend([
            {"date": stamp, "event_count": index, "raw_marks": before},
            {"date": stamp, "event_count": index + 1, "raw_marks": after},
        ])

    # Synthetic net executed totals; zero fees here are not the market cost policy.
    record({"action": "BUY", "code": "W", "qty": 1_000, "total": -100_000}, {}, {"W": 100})
    for index in range(20):
        labels[str(len(events))] = False
        record({"action": "BUY", "code": "N", "qty": 1_000, "total": -200_000}, {"W": 100}, {"W": 100, "N": 200})
        sale_price = 180 if index < 10 else 205
        record({"action": "SELL", "code": "N", "qty": 1_000, "total": sale_price * 1_000}, {"W": 100, "N": sale_price}, {"W": 100})
    record({"action": "SELL", "code": "W", "qty": 1_000, "total": 600_000}, {"W": 600}, {})
    inputs = build_attribution_inputs(initial_cash=2_000_000, events=events, checkpoints=checkpoints, classifications=labels)
    result = non_hit_attribution(inputs["attempts"], inputs["checkpoints"], initial_equity=2_000_000, span=20)
    assert inputs["checkpoints"][-1]["equity"] == 2_350_000
    assert result["whole_study"]["net_pnl_twd"] == -150_000
    assert len(result["windows"]) == 1
    assert result["windows"][0]["worst_cumulative_loss_twd"] == 200_000
    assert result["window_summary"]["worst_peak_to_trough_fraction_start"] == pytest.approx(0.1)
