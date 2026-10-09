import math
from typing import Any

import pytest

from research_core.ledger import (
    LedgerError,
    consecutive_non_hit_effects,
    mark_equity,
    max_drawdown,
    replay_ledger,
)


@pytest.mark.parametrize("identity", [None, [], {}, True, ""])
def test_malformed_attempt_ids_raise_ledger_error(identity: Any) -> None:
    with pytest.raises(LedgerError):
        consecutive_non_hit_effects([{"id": identity, "hit": False, "effect": 0.1}], 1)


def event(action: str, code: str, date: str, qty: Any = None, total: float = 0, **extra: Any) -> dict[str, Any]:
    value = {"action": action, "code": code, "date": date, "total": total, **extra}
    if qty is not None:
        value["qty"] = qty
    return value


def test_replays_five_shared_positions_and_cash_rows() -> None:
    events = [event("BUY", str(code), "2026-01-01", 1, -100) for code in range(5)]
    ledger = replay_ledger(1_000, events, marks={str(code): 110 for code in range(5)}, max_positions=5)
    assert ledger["cash"] == 500
    assert len(ledger["positions"]) == 5
    assert ledger["marked_equity"] == 1_050
    assert [row["cash"] for row in ledger["cash_rows"]] == [900, 800, 700, 600, 500]
    with pytest.raises(LedgerError, match="max_positions"):
        replay_ledger(1_000, events + [event("BUY", "overflow", "2026-01-01", 1, -1)], max_positions=5)


def test_attempts_include_adds_partials_dividend_split_and_same_day_rebuy() -> None:
    ledger = replay_ledger(
        1_000,
        [
            event("BUY", "A", "2026-01-01", 2, -202),  # fee already included
            event("BUY", "A", "2026-01-02", 1, -101),
            event("DIVIDEND", "A", "2026-01-03", total=9),
            event("SPLIT", "A", "2026-01-04", 3, 0, old_qty=3, new_qty=6),
            event("SELL", "A", "2026-01-05", 2, 198),  # tax already included
            event("SELL", "A", "2026-01-05", 4, 404),
            event("BUY", "A", "2026-01-05", 1, -50),
        ],
    )
    closed = ledger["attempts"][0]
    assert closed["id"] == 0
    assert [row["attempt_id"] for row in ledger["cash_rows"]] == [0, 0, 0, 0, 0, 0, 6]
    assert closed["pnl_ex_dividend"] == 299
    assert closed["net_pnl"] == 308
    assert closed["net_return_on_gross_buys"] == pytest.approx(308 / 303)
    assert ledger["open_attempts"][0]["id"] == 6
    assert ledger["positions"] == {"A": 1}


def test_explicit_dividend_entitlement_is_nonspendable_and_paid_to_original_attempt() -> None:
    before_payment = replay_ledger(
        100,
        [
            event("BUY", "A", "2026-01-01", 1, -100),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="A-2026", amount=10),
            event("SELL", "A", "2026-01-03", 1, 90),
            event("BUY", "A", "2026-01-04", 1, -90),
        ],
        marks={"A": 90},
    )
    ledger = replay_ledger(
        100,
        [
            event("BUY", "A", "2026-01-01", 1, -100),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="A-2026", amount=10),
            event("SELL", "A", "2026-01-03", 1, 90),
            event("BUY", "A", "2026-01-04", 1, -90),
            event("DIVIDEND", "A", "2026-01-05", total=10, entitlement_id="A-2026"),
        ],
        marks={"A": 90},
    )
    closed = ledger["attempts"][0]
    assert ledger["cash_rows"][1]["cash"] == 0
    assert ledger["cash_rows"][1]["dividend_receivable"] == 10
    assert ledger["cash_rows"][2]["cash"] == 90
    assert ledger["cash_rows"][3]["cash"] == 0
    assert ledger["cash_rows"][3]["dividend_receivable"] == 10
    assert before_payment["marked_equity"] == ledger["marked_equity"]
    assert [row["attempt_id"] for row in ledger["cash_rows"]] == [0, 0, 0, 3, 0]
    assert closed["id"] == 0
    assert closed["dividend_total"] == 10
    assert closed["dividend_receivable"] == 0
    assert closed["net_cash_flow"] == 0
    assert closed["net_pnl"] == 0
    assert closed["net_return_on_gross_buys"] == 0
    assert ledger["open_attempts"][0]["id"] == 3
    assert ledger["dividend_receivable"] == 0
    assert ledger["marked_equity"] == 100
    assert ledger["dividend_entitlements"] == [{"id": "A-2026", "code": "A", "attempt_id": 0, "amount": 10, "paid": True}]


def test_entitlements_preserve_amount_through_partial_sale_and_split() -> None:
    ledger = replay_ledger(
        200,
        [
            event("BUY", "A", "2026-01-01", 4, -100),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="first", amount=7),
            event("SELL", "A", "2026-01-03", 1, 25),
            event("SPLIT", "A", "2026-01-04", 3, 0, old_qty=3, new_qty=6),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-05", total=0, entitlement_id="second", amount=3),
        ],
    )
    assert ledger["dividend_receivable"] == 10
    assert ledger["open_attempts"][0]["dividend_receivable"] == 10
    assert [row["attempt_id"] for row in ledger["cash_rows"]] == [0, 0, 0, 0, 0]
    assert [item["amount"] for item in ledger["dividend_entitlements"]] == [7, 3]
    # Cash 200 - 100 + 25, six shares at 20, and ten still receivable.
    assert mark_equity(ledger, {"A": 20}) == 255


def test_receivable_cannot_fund_a_buy_or_occupy_a_stock_slot() -> None:
    events = [
        event("BUY", "A", "2026-01-01", 1, -100),
        event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="x", amount=10),
    ]
    assert replay_ledger(100, events, marks={"A": 90})["marked_equity"] == 100
    with pytest.raises(LedgerError, match="insufficient cash"):
        replay_ledger(100, events + [event("BUY", "B", "2026-01-02", 1, -10)])
    closed = events + [event("SELL", "A", "2026-01-03", 1, 90)]
    ledger = replay_ledger(100, closed, marks={})
    assert ledger["cash"] == 90
    assert ledger["marked_equity"] == 100
    assert ledger["attempts"][0]["net_cash_flow"] == -10
    assert ledger["attempts"][0]["net_pnl"] == 0
    rebought = replay_ledger(100, closed + [event("BUY", "B", "2026-01-04", 1, -90)], max_positions=1)
    assert rebought["positions"] == {"B": 1}


@pytest.mark.parametrize("identity", [None, True, 1, [], {}, ""])
def test_explicit_payment_id_cannot_fall_back_to_legacy(identity: Any) -> None:
    with pytest.raises(LedgerError, match="entitlement_id"):
        replay_ledger(100, [event("BUY", "A", "2026-01-01", 1, -10), event("DIVIDEND", "A", "2026-01-02", total=1, entitlement_id=identity)])


def test_explicit_entitlement_cannot_also_be_paid_as_an_unlinked_legacy_event() -> None:
    with pytest.raises(LedgerError, match="requires entitlement_id"):
        replay_ledger(
            100,
            [
                event("BUY", "A", "2026-01-01", 1, -10),
                event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="x", amount=1),
                event("DIVIDEND", "A", "2026-01-03", total=1),
            ],
        )


def test_legacy_then_explicit_dividend_is_also_rejected() -> None:
    with pytest.raises(LedgerError, match="cannot mix"):
        replay_ledger(
            100,
            [
                event("BUY", "A", "2026-01-01", 1, -10),
                event("DIVIDEND", "A", "2026-01-02", total=1),
                event("DIVIDEND_ENTITLEMENT", "A", "2026-01-03", entitlement_id="x", amount=1),
            ],
        )


def test_small_receivable_survives_payment_of_a_large_entitlement_on_another_attempt() -> None:
    events = [
        event("BUY", "A", "2026-01-01", 1, -10),
        event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="large", amount=1e16),
        event("SELL", "A", "2026-01-03", 1, 10),
        event("BUY", "B", "2026-01-04", 1, -10),
        event("DIVIDEND_ENTITLEMENT", "B", "2026-01-05", entitlement_id="small", amount=1),
        event("DIVIDEND", "A", "2026-01-06", total=1e16, entitlement_id="large"),
    ]
    ledger = replay_ledger(100, events)
    assert ledger["dividend_receivable"] == ledger["open_attempts"][0]["dividend_receivable"] == 1
    assert ledger["attempts"][0]["dividend_receivable"] == 0
    with pytest.raises(LedgerError, match="does not match"):
        replay_ledger(100, events[:-1] + [event("DIVIDEND", "A", "2026-01-06", total=1e16 + 1000, entitlement_id="large")])


def test_out_of_order_payments_reconcile_multiple_entitlements_exactly() -> None:
    events = [event("BUY", "A", "2026-01-01", 1, -10)]
    for identity, amount in [("one", 0.1), ("two", 0.2), ("three", 0.3)]:
        events.append(event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id=identity, amount=amount))
    for identity, amount in [("three", 0.3), ("one", 0.1), ("two", 0.2)]:
        events.append(event("DIVIDEND", "A", "2026-01-03", total=amount, entitlement_id=identity))
        ledger = replay_ledger(100, events)
        expected = math.fsum(row["amount"] for row in ledger["dividend_entitlements"] if not row["paid"])
        assert ledger["dividend_receivable"] == ledger["open_attempts"][0]["dividend_receivable"] == expected
    assert ledger["dividend_receivable"] == 0


@pytest.mark.parametrize("amount", [None, True, 0, -1, math.nan, math.inf])
def test_entitlement_amount_must_be_positive_and_finite(amount: Any) -> None:
    with pytest.raises(LedgerError):
        replay_ledger(
            100,
            [
                event("BUY", "A", "2026-01-01", 1, -10),
                event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="x", amount=amount),
            ],
        )


def test_aggregate_entitlement_overflow_is_a_ledger_error() -> None:
    with pytest.raises(LedgerError, match="overflow"):
        replay_ledger(
            100,
            [
                event("BUY", "A", "2026-01-01", 1, -10),
                event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="x", amount=1e308),
                event("DIVIDEND_ENTITLEMENT", "A", "2026-01-03", entitlement_id="y", amount=1e308),
            ],
        )


def test_payment_after_exit_without_rebuy_and_amount_check_independent_of_capital() -> None:
    events = [
        event("BUY", "A", "2026-01-01", 1, -100),
        event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="x", amount=10),
        event("SELL", "A", "2026-01-03", 1, 90),
    ]
    ledger = replay_ledger(100, events + [event("DIVIDEND", "A", "2026-01-04", total=10, entitlement_id="x")], marks={})
    assert ledger["positions"] == {}
    assert ledger["cash"] == ledger["marked_equity"] == 100
    with pytest.raises(LedgerError, match="does not match"):
        replay_ledger(1e12, events + [event("DIVIDEND", "A", "2026-01-04", total=11, entitlement_id="x")])


@pytest.mark.parametrize(
    "events",
    [
        [event("DIVIDEND_ENTITLEMENT", "A", "2026-01-01", total=0, entitlement_id="x", amount=1)],
        [event("BUY", "A", "2026-01-01", 1, -1), event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=1, entitlement_id="x", amount=1)],
        [event("BUY", "A", "2026-01-01", 1, -1), event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="", amount=1)],
        [event("BUY", "A", "2026-01-01", 1, -1), event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="x", amount=math.nan)],
        [event("BUY", "A", "2026-01-01", 1, -1), event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="x", amount=-1)],
        [
            event("BUY", "A", "2026-01-01", 1, -1),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="x", amount=1),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-03", total=0, entitlement_id="x", amount=2),
        ],
        [event("BUY", "A", "2026-01-01", 1, -1), event("DIVIDEND", "A", "2026-01-02", total=1, entitlement_id="missing")],
        [
            event("BUY", "A", "2026-01-01", 1, -1),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="x", amount=1),
            event("DIVIDEND", "B", "2026-01-03", total=1, entitlement_id="x"),
        ],
        [
            event("BUY", "A", "2026-01-01", 1, -1),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="x", amount=1),
            event("DIVIDEND", "A", "2026-01-03", total=2, entitlement_id="x"),
        ],
        [
            event("BUY", "A", "2026-01-01", 1, -1),
            event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", total=0, entitlement_id="x", amount=1),
            event("DIVIDEND", "A", "2026-01-03", total=1, entitlement_id="x"),
            event("DIVIDEND", "A", "2026-01-04", total=1, entitlement_id="x"),
        ],
    ],
)
def test_rejects_invalid_explicit_dividend_entitlements(events: list[dict[str, Any]]) -> None:
    with pytest.raises(LedgerError):
        replay_ledger(100, events)


@pytest.mark.parametrize(
    "events",
    [
        [event("NOPE", "A", "2026-01-01", 1, -1)],
        [event("SELL", "A", "2026-01-01", 1, 1)],
        [event("BUY", "A", "2026-01-01", 1, -101)],
        [event("BUY", "A", "2026-01-01", 1, math.nan)],
        [event("BUY", "A", "not-a-date", 1, -1)],
        [event("BUY", "A", "2026-01-02", 1, -1), event("BUY", "B", "2026-01-01", 1, -1)],
        [event("BUY", "A", "2026-01-01", 1, -1), event("SPLIT", "A", "2026-01-02", 1, 1, old_qty=1, new_qty=2)],
        [event("BUY", "A", "2026-01-01", 1, -1), event("SPLIT", "A", "2026-01-02", 1, 0, old_qty=2, new_qty=2)],
        [event("BUY", "A", "2026-01-01", 1, -1), event("SPLIT", "A", "2026-01-02", 2, 0, old_qty=1, new_qty=2)],
    ],
)
def test_rejects_invalid_events(events: list[dict[str, Any]]) -> None:
    with pytest.raises(LedgerError):
        replay_ledger(100, events)


def test_mark_equity_requires_explicit_marks() -> None:
    ledger = replay_ledger(100, [event("BUY", "A", "2026-01-01", 2, -20)])
    assert mark_equity(ledger, {"A": 15}) == 110
    with pytest.raises(LedgerError, match="missing mark"):
        mark_equity(ledger, {})
    with pytest.raises(LedgerError, match="nonnegative"):
        mark_equity(ledger, {"A": -1})


@pytest.mark.parametrize(("total", "costs", "ending_cash"), [(0, 1, 99), (-19, 20, 80)])
def test_net_cost_sale_still_closes_attempt_and_charges_cash(total: float, costs: float, ending_cash: float) -> None:
    ledger = replay_ledger(
        100,
        [
            event("BUY", "A", "2026-01-01", 1, -1),
            event("SELL", "A", "2026-01-02", 1, total, gross_proceeds=1, cost_total=costs),
        ],
        marks={},
    )
    assert ledger["positions"] == {}
    assert ledger["cash"] == ledger["marked_equity"] == ending_cash
    assert ledger["attempts"][0]["sell_total"] == total
    assert ledger["attempts"][0]["net_pnl"] == ending_cash - 100


def test_net_cost_sale_cannot_spend_unpaid_dividend() -> None:
    events = [
        event("BUY", "A", "2026-01-01", 1, -1),
        event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="A-dividend", amount=20),
        event("SELL", "A", "2026-01-03", 1, -19, gross_proceeds=1, cost_total=20),
    ]
    with pytest.raises(LedgerError, match="insufficient cash for SELL costs"):
        replay_ledger(1, events)


@pytest.mark.parametrize(
    "details",
    [
        {},
        {"gross_proceeds": 1},
        {"cost_total": 20},
        {"gross_proceeds": 0, "cost_total": 19},
        {"gross_proceeds": 1, "cost_total": -18},
        {"gross_proceeds": 1, "cost_total": 19},
        {"gross_proceeds": 1, "cost_total": math.nan},
    ],
)
def test_nonpositive_sale_requires_reconciled_components(details: dict[str, Any]) -> None:
    with pytest.raises(LedgerError):
        replay_ledger(100, [event("BUY", "A", "2026-01-01", 1, -1), event("SELL", "A", "2026-01-02", 1, -19, **details)])


def test_positive_sale_components_are_checked_without_relative_tolerance() -> None:
    with pytest.raises(LedgerError, match="does not reconcile"):
        replay_ledger(
            100,
            [
                event("BUY", "A", "2026-01-01", 1, -1),
                event("SELL", "A", "2026-01-02", 1, 1e12 + 1, gross_proceeds=1e12, cost_total=0),
            ],
        )


def test_sale_components_preserve_decimal_cancellation_and_large_integer_difference() -> None:
    bought = [event("BUY", "A", "2026-01-01", 1, -1)]
    ledger = replay_ledger(
        100,
        bought
        + [
            event("SELL", "A", "2026-01-02", 1, 0.01, gross_proceeds=100_000_000.01, cost_total=100_000_000),
        ],
    )
    assert ledger["cash"] == 99.01
    assert ledger["positions"] == {}
    with pytest.raises(LedgerError, match="does not reconcile"):
        replay_ledger(
            100,
            bought
            + [
                event("SELL", "A", "2026-01-02", 1, 0, gross_proceeds=10**20 + 1, cost_total=10**20),
            ],
        )


def test_reverse_split_uses_broker_delta_and_explicit_new_quantity() -> None:
    ledger = replay_ledger(
        100,
        [
            event("BUY", "A", "2026-01-01", 4, -40),
            event("SPLIT", "A", "2026-01-02", -2, 0, old_qty=4, new_qty=2),
        ],
    )
    assert ledger["positions"] == {"A": 2}


def test_drawdown_handles_recovery_and_zero_but_not_negative() -> None:
    assert max_drawdown([100, 120, 60, 120]) == pytest.approx(0.5)
    assert max_drawdown([100, 0, 80]) == 1
    with pytest.raises(LedgerError):
        max_drawdown([100, -1])


def test_consecutive_non_hit_windows_do_not_bridge_hits_or_unknowns() -> None:
    attempts = [
        {"id": "a", "effect": 0.05, "hit": False},
        {"id": "b", "effect": -0.10, "hit": False},
        {"id": "c", "effect": -0.30, "hit": True},
        {"id": "d", "effect": -0.02, "hit": False},
        {"id": "e", "effect": -0.03, "hit": False},
    ]
    result = consecutive_non_hit_effects(attempts, 2)
    assert result == {
        "status": "ok",
        "worst_compounded_net_effect": pytest.approx(-0.055),
        "ids": ["a", "b"],
        "unit": "fraction",
        "metric": "synthetic_non_hit_effect.v1",
    }
    unavailable = consecutive_non_hit_effects(attempts + [{"id": "f", "effect": 0.01, "hit": None}], 2)
    assert unavailable["status"] == "unavailable"
    assert "worst_compounded_net_effect" not in unavailable
    assert consecutive_non_hit_effects(attempts[:1], 2)["status"] == "insufficient_windows"
    assert (
        consecutive_non_hit_effects(
            [{"id": "a", "effect": -0.1, "hit": False}, {"id": "b", "effect": -0.1, "hit": True}, {"id": "c", "effect": -0.1, "hit": False}],
            2,
        )["status"]
        == "no_eligible_windows"
    )
    with pytest.raises(LedgerError, match="greater than -1"):
        consecutive_non_hit_effects([{"id": "x", "effect": -1, "hit": False}], 1)
    with pytest.raises(LedgerError, match="present and unique"):
        consecutive_non_hit_effects([{"id": "x", "effect": 0, "hit": False}, {"id": "x", "effect": 0, "hit": False}], 1)
