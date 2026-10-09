"""Synthetic measured chronology, actual ledger slot release and metadata counts."""

import copy
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from research_core.auction import AuctionBatch, OrderIntent, RoutedOrder
from research_core.chronology import DecisionRecord, ExecutionEvidence, PriorCloseRequest, WindowRecord
from research_core.signals import SignalIdentity
from scripts.tests import test_h05_measurement as measured
from scripts.tests.test_close_review_execution import COSTS

LOCATION = Path(__file__).resolve().parents[2] / "tasks/20261005-relative-strength-holding/diagnostics.py"
SPEC = importlib.util.spec_from_file_location("h05_diagnostics_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


def summarize(events: list[dict[str, Any]], marks: list[dict[str, Any]]):
    result = measured.result(events, marks)
    return diagnostics.diagnose(result, measured.measure(result))


def test_partial_exit_keeps_slot_and_unpaid_cash_releases_it_in_event_order() -> None:
    events = [
        measured.trade("BUY", "A", 0, 10, qty=100),
        measured.event("DIVIDEND_ENTITLEMENT", "A", 1, amount=20, entitlement_id="unpaid"),
        measured.trade("SELL", "A", 1, 10, qty=50),
        measured.trade("BUY", "B", 1, 10, qty=100),
        measured.trade("SELL", "A", 2, 10, qty=50),
        measured.trade("BUY", "C", 2, 10, qty=100),
        measured.trade("SELL", "C", 2, 10, qty=100),
        measured.trade("BUY", "C", 2, 10, qty=100),
    ]
    output = summarize(events, [{"A": 10}, {"A": 10, "B": 10}, {"B": 10, "C": 10}])
    assert output["slot_labels"]["attempt_slot"] == {"0": 1, "3": 2, "5": 1, "7": 1}
    slot = output["slot_labels"]["slots"][0]
    assert (slot["entries"], slot["successive_attempts"], slot["issuer_changes"]) == (3, 2, 1)
    assert output["net_loss_streak"]["unknown_attempt_ids"] == ["0", "3", "7"]
    assert output["positive_profit_concentration"]["excluded_unsettled_count"] == 3
    json.dumps(output, allow_nan=False)


def test_share_claim_keeps_slot_until_actual_fraction_settlement() -> None:
    events = [
        measured.trade("BUY", "A", 0, 10, qty=100),
        measured.event(
            "SHARE_ENTITLEMENT", "A", 1, entitlement_id="fraction", share_numerator=1, share_denominator=2, valuation_policy="same-class-raw-close-cent-half-up"
        ),
        measured.trade("SELL", "A", 1, 10, qty=100),
        measured.trade("BUY", "B", 1, 10, qty=100),
        measured.event("SHARE_CASH_SETTLEMENT", "A", 2, 5, entitlement_id="fraction"),
        measured.trade("BUY", "C", 2, 10, qty=100),
    ]
    output = summarize(events, [{"A": 10}, {"A": 10, "B": 10}, {"B": 10, "C": 10}])
    assert output["slot_labels"]["attempt_slot"] == {"0": 1, "3": 2, "5": 1}


def test_profit_concentration_uses_only_positive_settled_denominator() -> None:
    events = []
    marks = []
    for i, price in enumerate((160, 140, 110, 90)):
        events += [measured.trade("BUY", "A", 2 * i, 100), measured.trade("SELL", "A", 2 * i + 1, price)]
        marks += [{"A": 100}, {}]
    output = summarize(events, marks)
    concentration = output["positive_profit_concentration"]
    assert concentration["positive_profit_sum_cents"] == 11_000_000
    assert concentration["top1_fraction"] == pytest.approx(6 / 11)
    assert concentration["top3_fraction"] == 1
    assert concentration["positive_attempt_count"] == 3


def test_no_positive_profit_is_null_and_small_win_breaks_loss_streak() -> None:
    events = []
    marks = []
    for i, price in enumerate((90, 90, 105, 90, 90)):
        events += [measured.trade("BUY", "A", 2 * i, 100), measured.trade("SELL", "A", 2 * i + 1, price)]
        marks += [{"A": 100}, {}]
    output = summarize(events, marks)
    assert output["net_loss_streak"]["max_known"] == 2
    assert output["net_loss_streak"]["known_runs"] == [["0", "2"], ["6", "8"]]
    no_wins = summarize(events[:4], marks[:4])["positive_profit_concentration"]
    assert no_wins["positive_profit_sum_cents"] == 0
    assert no_wins["top1_fraction"] is None and no_wins["top3_fraction"] is None


def test_unknown_in_hit_gap_is_not_zero_or_nonhit_and_edges_are_censored() -> None:
    events = [
        measured.trade("BUY", "L", 0, 100),
        measured.trade("SELL", "L", 1, 90),
        measured.trade("BUY", "H", 2, 100),
        measured.trade("SELL", "H", 3, 160),
        measured.trade("BUY", "U", 4, 100),
        measured.trade("BUY", "H", 5, 100),
        measured.trade("SELL", "H", 6, 160),
        measured.trade("BUY", "L", 7, 100),
        measured.trade("SELL", "L", 8, 90),
    ]
    marks = [{"L": 100}, {}, {"H": 100}, {}, {"U": 100}, {"U": 100, "H": 100}, {"U": 100}, {"U": 100, "L": 100}, {"U": 100}]
    output = summarize(events, marks)
    leading, gap, trailing = output["hit_gaps"]["segments"]
    assert leading["attempt_ids"] == ["0"] and leading["left_censored"]
    assert gap["unknown_attempt_ids"] == ["4"] and gap["known_non_hit_count"] == 0
    assert gap["exact_non_hit_gap"] is None and not gap["classification_complete"]
    assert trailing["attempt_ids"] == ["7"] and trailing["right_censored"]
    assert output["net_loss_streak"]["unknown_attempt_ids"] == ["4"]


def test_unknown_breaks_known_losses_and_missing_signal_metadata_is_explicit() -> None:
    events = [
        measured.trade("BUY", "A", 0, 100),
        measured.trade("SELL", "A", 1, 90),
        measured.trade("BUY", "U", 2, 100),
        measured.trade("BUY", "A", 3, 100),
        measured.trade("SELL", "A", 4, 90),
    ]
    output = summarize(events, [{"A": 100}, {}, {"U": 100}, {"U": 100, "A": 100}, {"U": 100}])
    assert output["net_loss_streak"]["max_known"] == 1
    assert output["net_loss_streak"]["unknown_attempt_ids"] == ["2"]
    assert not output["net_loss_streak"]["classification_complete"]
    assert not output["burden"]["signal_count_complete"]
    assert output["burden"]["unlinked_fill_event_indices"] == [0, 1, 2, 3, 4]


def test_regular_and_odd_legs_are_separate_from_signal_count() -> None:
    events = [
        measured.trade("BUY", "A", 1, 100, qty=1000),
        measured.trade("BUY", "A", 1, 100, qty=1),
        measured.trade("SELL", "A", 2, 110, qty=1000),
        measured.trade("SELL", "A", 2, 110, qty=1),
    ]
    venues = ("regular_open", "afterhours_odd", "regular_open", "afterhours_odd")
    requests = []
    routes = []
    signal = SignalIdentity("buy-advice", "A", "BUY", measured.stamp(0, 20))
    for i, (event, venue) in enumerate(zip(events, venues, strict=True)):
        event.update(venue=venue, order_id=f"leg{i}")
        if venue == "afterhours_odd":
            event["date"] = measured.stamp(1 if i < 2 else 2, 14).replace(minute=30).isoformat()
        decision = measured.stamp(0 if i < 2 else 1, 20)
        intent = OrderIntent(f"leg{i}", "A", event["action"], event["qty"], 11000 if i < 2 else 9000, decision)
        requests.append(PriorCloseRequest(intent, "TWSE", venue, signal if i < 2 else None))
        day = 1 if i < 2 else 2
        submitted = measured.stamp(day, 8 if venue == "regular_open" else 14)
        auction = measured.stamp(day, 9 if venue == "regular_open" else 14).replace(minute=0 if venue == "regular_open" else 30)
        routes.append(RoutedOrder(intent, AuctionBatch("TWSE", venue, submitted, auction, f"s{i}"), COSTS))
    result = measured.result(events, [{}, {"A": 100}, {}])
    result = replace(
        result,
        decisions=(DecisionRecord(measured.stamp(0, 20), tuple(requests[:2]), ()), DecisionRecord(measured.stamp(1, 20), tuple(requests[2:]), ())),
        signals=(signal,),
        windows=tuple(WindowRecord(f"w{i}", "synthetic", (route,), None, ExecutionEvidence("synthetic", {}, (), True, True)) for i, route in enumerate(routes)),
    )
    output = diagnostics.diagnose(result, measured.measure(result))["burden"]
    assert output["known_advice_signal_ids"] == ["buy-advice"]
    assert output["unknown_signal_order_ids"] == ["leg2", "leg3"]
    assert output["order_legs"] == output["route_legs"] == 4
    assert output["active_advice_days"] == 2 and output["max_order_legs_created_per_day"] == 2
    annual = output["annual"][0]
    assert annual["fills"]["BUY"]["regular_open"] == annual["fills"]["BUY"]["afterhours_odd"] == 1
    assert annual["fills"]["SELL"]["regular_open"] == annual["fills"]["SELL"]["afterhours_odd"] == 1
    assert not annual["signal_count_complete"]


@pytest.mark.parametrize("change", ["incomplete", "id", "prefix", "money", "profit"])
def test_rejects_mismatched_measurement_or_incomplete_chronology(change: str) -> None:
    result = measured.result([measured.trade("BUY", "A", 0, 100)], [{"A": 100}])
    report = copy.deepcopy(measured.measure(result))
    if change == "incomplete":
        result = replace(result, status="incomplete")
    elif change == "id":
        report["attempts"][0]["id"] = "wrong"
    elif change == "prefix":
        report["daily"][0]["event_count"] = 0
    elif change == "money":
        report["daily"][0]["equity_cents"] += 1
    else:
        report["attempts"][0]["net_paid_cash_cents"] += 1
    with pytest.raises(diagnostics.DiagnosticError):
        diagnostics.diagnose(result, report)


@pytest.mark.parametrize("change", ["threshold", "ordering", "small_win_hit", "hit_non_hit", "gross_buy", "resolution"])
def test_validates_actual_gross_buys_and_fixed_settled_hit_classification(change: str) -> None:
    sale = 160 if change == "hit_non_hit" else 110
    result = measured.result([measured.trade("BUY", "A", 0, 100), measured.trade("SELL", "A", 1, sale)], [{"A": 100}, {}])
    report = copy.deepcopy(measured.measure(result))
    if change == "threshold":
        report["hit_threshold"] = "1/10"
    elif change == "ordering":
        report["attempt_order"] = "exit_order"
    elif change == "small_win_hit":
        report["attempts"][0]["disposition"] = "hit"
    elif change == "hit_non_hit":
        report["attempts"][0]["disposition"] = "non_hit"
    elif change == "gross_buy":
        report["attempts"][0]["gross_buy_cents"] = 1
    else:
        report["attempts"][0]["cash_resolution_at"] = measured.stamp(0, 20).isoformat()
    with pytest.raises(diagnostics.DiagnosticError):
        diagnostics.diagnose(result, report)


def test_every_reviewed_year_has_zero_burden_without_any_orders() -> None:
    result = measured.result([], [{}] * 367)  # Leap-year 2020 plus the first 2021 review.
    rows = diagnostics.diagnose(result, measured.measure(result))["burden"]["annual"]
    assert [row["year"] for row in rows] == [2020, 2021]
    for row in rows:
        assert row["order_legs"] == row["route_legs"] == row["active_advice_days"] == 0
        assert row["known_advice_signal_count"] == row["max_order_legs_created_per_day"] == 0
        assert all(count == 0 for counts in row["fills"].values() for count in counts.values())


def test_hit_waits_follow_cash_resolution_not_entry_order_and_keep_unknowns() -> None:
    events = [
        measured.trade("BUY", "A", 0, 100),
        measured.event("DIVIDEND_ENTITLEMENT", "A", 1, amount=60_000, entitlement_id="late-cash"),
        measured.trade("SELL", "A", 2, 100),
        measured.trade("BUY", "B", 3, 100),
        measured.trade("SELL", "B", 4, 160),
        measured.event("DIVIDEND", "A", 5, 60_000, entitlement_id="late-cash"),
        measured.trade("BUY", "U", 6, 100),
    ]
    output = summarize(events, [{"A": 100}, {"A": 100}, {}, {"B": 100}, {}, {}, {"U": 100}, {"U": 100}])
    assert output["hit_gaps"]["hit_attempt_ids"] == ["0", "3"]
    waits = output["cash_resolved_hit_waits"]
    assert waits["resolved_hit_attempt_ids"] == ["3", "0"]
    assert waits["uncompleted_attempt_count"] == 1 and waits["uncompleted_attempt_ids"] == ["6"]
    leading, middle, trailing = waits["intervals"]
    assert leading["right_hit_id"] == "3" and leading["left_observation_boundary"]
    assert leading["elapsed_days"] == pytest.approx(3 + 13 / 24)
    assert middle["left_hit_id"] == "3" and middle["right_hit_id"] == "0"
    assert middle["elapsed_days"] == 1 and not middle["right_censored"]
    assert trailing["elapsed_days"] == pytest.approx(2 + 11 / 24)
    assert trailing["right_censored"] and trailing["end_at"] == measured.stamp(7, 20).isoformat()


def test_hit_already_resolved_at_first_review_never_creates_negative_wait() -> None:
    output = summarize([measured.trade("BUY", "A", 0, 100), measured.trade("SELL", "A", 0, 160)], [{}, {}])
    waits = output["cash_resolved_hit_waits"]
    assert waits["already_resolved_at_first_review_ids"] == ["0"]
    assert len(waits["intervals"]) == 1
    assert waits["intervals"][0]["elapsed_days"] == 1
    assert waits["intervals"][0]["left_observation_boundary"] and waits["intervals"][0]["right_censored"]
