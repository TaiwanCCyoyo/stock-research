"""Hand-calculable prefix accounting; no market files or historical outcomes."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from research_core.chronology import ChronologyResult, Scenario
from research_core.decision import CloseObservation, build_decision_snapshot
from research_core.ledger import LedgerError

LOCATION = Path(__file__).resolve().parents[2] / "tasks" / "20261005-relative-strength-holding" / "measurement.py"
SPEC = importlib.util.spec_from_file_location("h05_measurement_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
measurement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurement)
ORIGIN = datetime.fromisoformat("2020-01-01T00:00:00+08:00")


def stamp(day: int, hour: int = 9) -> datetime:
    return ORIGIN + timedelta(days=day, hours=hour)


def event(action: str, code: str, day: int, total: float = 0, **extra: Any) -> dict[str, Any]:
    return {"action": action, "code": code, "date": stamp(day).isoformat(), "total": total, **extra}


def trade(action: str, code: str, day: int, price: float, qty: int = 1000, cost: int = 0) -> dict[str, Any]:
    total = -(price * qty + cost / 100) if action == "BUY" else price * qty - cost / 100
    extra = {"gross_proceeds": price * qty, "cost_total": cost / 100} if action == "SELL" else {}
    return event(action, code, day, total, price=price, qty=qty, commission_cents=cost, tax_cents=0, penalty_cents=0, **extra)


def result(events: list[dict[str, Any]], prices: Sequence[Mapping[str, float]]) -> ChronologyResult:
    snapshots = []
    for day, marks in enumerate(prices):
        close = stamp(day, 13) + timedelta(minutes=30)
        observations = {code: CloseObservation(round(price * 100), Decimal(str(price)), close, close, "synthetic") for code, price in marks.items()}
        snapshots.append(
            build_decision_snapshot(
                initial_cash_cents=200_000_000,
                history_start=ORIGIN,
                as_of=stamp(day, 20),
                events=[item for item in events if datetime.fromisoformat(item["date"]) <= stamp(day, 20)],
                session_closes=[stamp(i, 13) + timedelta(minutes=30) for i in range(day + 1)],
                calendar_id="synthetic",
                prices=observations,
                execution_complete=True,
                execution_checkpoint_id=f"synthetic:{day}",
                cash_basis="trade_date_cash",
                unresolved_order_ids=(),
                max_positions=5,
            )
        )
    return ChronologyResult(
        "complete",
        None,
        Scenario("synthetic", frozenset(), 0),
        "synthetic",
        "initial",
        tuple(events),
        tuple(snapshots),
        (),
        (),
        (),
        (),
        frozenset(),
        frozenset(),
    )


def measure(value: ChronologyResult) -> dict[str, Any]:
    return measurement.measure(value, expected_reviews=[stamp(i, 20) for i in range(len(value.snapshots))])


def test_initial_cash_and_no_attempts_are_not_zero_erosion_evidence() -> None:
    report = measure(result([], [{}, {}]))
    assert report["account"]["net_return"] == 0
    assert report["account"]["close_max_drawdown"] == 0
    assert report["non_hit_attribution"]["whole_study"]["net_cents"] is None
    assert report["non_hit_attribution"]["window_summary"]["status"] == "insufficient_windows"


@pytest.mark.parametrize("sell_price,expected", [(150, "hit"), (149.99, "non_hit"), (110, "non_hit"), (90, "non_hit")])
def test_captured_threshold_includes_small_wins_and_costs_once(sell_price: float, expected: str) -> None:
    value = result([trade("BUY", "A", 0, 100), trade("SELL", "A", 1, sell_price)], [{"A": 100}, {}])
    report = measure(value)
    assert report["attempts"][0]["disposition"] == expected
    assert report["account"]["net_return"] == pytest.approx((sell_price - 100) * 1000 / 2_000_000)
    assert report["attempts"][0]["gross_buy_cents"] == 10_000_000
    charged = result([trade("BUY", "A", 0, 100, cost=20_000), trade("SELL", "A", 1, 150, cost=30_000)], [{"A": 100}, {}])
    report = measure(charged)
    assert report["attempts"][0]["disposition"] == "non_hit"
    assert report["attempts"][0]["captured_return"] == 0.495
    assert report["account"]["annual"][0]["cost_cents"] == 50_000
    assert report["account"]["net_return"] == pytest.approx(49_500 / 2_000_000)


def test_winner_does_not_mask_twenty_nonhits_and_small_win_stays_in_window() -> None:
    events = [trade("BUY", "WINNER", 0, 100)]
    prices = [{"WINNER": 100}]
    for index in range(20):
        buy_day = 2 * index + 1
        sell_price = 105 if index == 19 else 90
        events += [trade("BUY", "A", buy_day, 100), trade("SELL", "A", buy_day + 1, sell_price)]
        prices += [{"WINNER": 500, "A": 100}, {"WINNER": 500}]
    events.append(trade("SELL", "WINNER", 41, 500))
    prices.append({})
    report = measure(result(events, prices))
    assert report["disposition_counts"] == {"hit": 1, "non_hit": 20, "unknown": 0}
    assert report["account"]["net_return"] == pytest.approx(215_000 / 2_000_000)
    erosion = report["non_hit_attribution"]
    assert erosion["max_known_non_hit_run"] == 20
    assert len(erosion["windows"]) == 1
    assert erosion["whole_study"]["net_cents"] == -18_500_000
    assert erosion["whole_study"]["worst_loss_cents"] == 19_000_000
    assert erosion["window_summary"]["worst_peak_to_trough_fraction_initial"] == 0.095
    assert report["non_hit_mean_signed_cash_cents"] == -925_000


@pytest.mark.parametrize("kind,payment", [("DIVIDEND_ENTITLEMENT", "DIVIDEND"), ("CAPITAL_RETURN_ENTITLEMENT", "CAPITAL_RETURN")])
def test_unpaid_right_is_unknown_and_payment_cannot_create_second_profit(kind: str, payment: str) -> None:
    events = [trade("BUY", "A", 0, 100), event(kind, "A", 1, amount=60_000, entitlement_id="right"), trade("SELL", "A", 2, 100)]
    report = measure(result(events, [{"A": 100}, {"A": 100}, {}]))
    assert report["attempts"][0]["disposition"] == "unknown"
    assert report["attempts"][0]["captured_return"] is None
    assert report["account"]["net_return"] == pytest.approx(0.03)
    events += [trade("BUY", "A", 3, 100), event(payment, "A", 4, 60_000, entitlement_id="right")]
    report = measure(result(events, [{"A": 100}, {"A": 100}, {}, {"A": 100}, {"A": 100}]))
    old, new = report["attempts"]
    assert old["disposition"] == "hit" and old["gross_buy_cents"] == 10_000_000
    assert old["captured_return"] == 0.6 and new["disposition"] == "unknown"
    assert report["daily"][-1]["equity_cents"] == report["daily"][-2]["equity_cents"]
    assert report["daily"][-1]["attempt_pnl_cents"] == {"0": 6_000_000, "3": 0}


def test_split_marks_use_actual_post_event_units_and_do_not_make_profit() -> None:
    events = [trade("BUY", "A", 0, 100), event("SPLIT", "A", 1, old_qty=1000, new_qty=2000), trade("SELL", "A", 2, 75, qty=2000)]
    report = measure(result(events, [{"A": 100}, {"A": 50}, {}]))
    assert [row["equity_cents"] for row in report["daily"]] == [200_000_000, 200_000_000, 205_000_000]
    assert report["attempts"][0]["disposition"] == "hit"


def test_unsettled_fraction_is_open_even_after_selling_all_tradable_shares() -> None:
    events = [
        trade("BUY", "A", 0, 10, qty=100),
        event(
            "SHARE_ENTITLEMENT", "A", 1, entitlement_id="fraction", share_numerator=1, share_denominator=2, valuation_policy="same-class-raw-close-cent-half-up"
        ),
        trade("SELL", "A", 2, 10, qty=100),
    ]
    report = measure(result(events, [{"A": 10}, {"A": 10}, {"A": 10}]))
    assert report["attempts"][0]["unknown_reason"] == "open_stock_or_share_claim"
    assert report["daily"][-1]["share_claim_value_cents"] == 500
    events.append(event("SHARE_CASH_SETTLEMENT", "A", 3, 5, entitlement_id="fraction"))
    report = measure(result(events, [{"A": 10}, {"A": 10}, {"A": 10}, {}]))
    assert report["attempts"][0]["disposition"] == "non_hit"
    assert report["attempts"][0]["paid_fraction_cents"] == 500
    assert report["daily"][-1]["equity_cents"] == report["daily"][-2]["equity_cents"]


def test_same_close_multiple_entries_keep_event_order_not_symbol_order() -> None:
    events = [trade("BUY", "Z", 0, 100), trade("BUY", "A", 0, 100), trade("SELL", "A", 1, 90), trade("SELL", "Z", 1, 110)]
    report = measure(result(events, [{"A": 100, "Z": 100}, {}]))
    assert [item["code"] for item in report["attempts"]] == ["Z", "A"]
    assert report["non_hit_attribution"]["whole_study"]["net_cents"] == 0


def test_unknown_can_hide_worst_twenty_window_instead_of_becoming_a_hit() -> None:
    events = [trade("BUY", "UNKNOWN", 0, 100)]
    prices = [{"UNKNOWN": 100}]
    for index in range(19):
        day = 2 * index + 1
        events += [trade("BUY", "A", day, 100), trade("SELL", "A", day + 1, 90)]
        prices += [{"UNKNOWN": 100, "A": 100}, {"UNKNOWN": 100}]
    report = measure(result(events, prices))
    assert report["non_hit_attribution"]["window_summary"] == {"status": "unavailable", "span": 20, "worst_peak_to_trough_fraction_initial": None}
    assert report["non_hit_attribution"]["whole_study"]["status"] == "partial"


@pytest.mark.parametrize("change", ["incomplete", "missing_day", "equity", "cash", "claim", "count", "held", "stale", "after_endpoint", "missing_mark", "cost"])
def test_rejects_incomplete_or_unreconciled_evidence(change: str) -> None:
    value = result([trade("BUY", "A", 0, 100)], [{"A": 100}, {"A": 90}])
    snapshots = list(value.snapshots)
    if change == "incomplete":
        value = replace(value, status="incomplete", stop_reason="missing_close_marks")
    elif change == "missing_day":
        value = replace(value, snapshots=(snapshots[0],))
    elif change in {"equity", "cash", "claim", "count", "held"}:
        fields: dict[str, dict[str, Any]] = {
            "equity": {"equity_cents": 1},
            "cash": {"cash_cents": 1},
            "claim": {"share_claim_value_cents": 1},
            "count": {"event_count": 0},
            "held": {"holdings": {}},
        }
        snapshots[-1] = replace(snapshots[-1], **fields[change])
        value = replace(value, snapshots=tuple(snapshots))
    elif change in {"stale", "missing_mark"}:
        marks = {} if change == "missing_mark" else snapshots[0].prices
        snapshots[-1] = replace(snapshots[-1], prices=marks)
        value = replace(value, snapshots=tuple(snapshots))
    else:
        bad = dict(value.events[0])
        if change == "cost":
            bad.pop("penalty_cents")
        else:
            bad["date"] = stamp(3).isoformat()
        value = replace(value, events=(bad,))
    with pytest.raises((measurement.MeasurementError, LedgerError)):
        measurement.measure(value, expected_reviews=[stamp(0, 20), stamp(1, 20)])
