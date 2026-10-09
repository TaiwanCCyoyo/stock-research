"""Hand-calculable H05 costs through public shared execution entry points."""

import importlib.util
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from research_core.auction import (
    AccountState,
    AuctionBatch,
    AuctionQuote,
    CostSchedule,
    OrderIntent,
    buy_quantity_for_budget,
    resolve_auction_batch,
)
from research_core.execution_prices import PriceLimits

LOCATION = Path(__file__).resolve().parents[2] / "tasks" / "20261005-relative-strength-holding" / "costs.py"
SPEC = importlib.util.spec_from_file_location("h05_costs_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
costs_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(costs_module)
cost_schedule = costs_module.cost_schedule
DECISION = datetime.fromisoformat("2026-01-02T16:00:00+08:00")
SUBMITTED = datetime.fromisoformat("2026-01-05T08:30:00+08:00")
BOUNDS = PriceLimits(Decimal("0.01"), None)


def batch(venue: str = "regular_open") -> AuctionBatch:
    clock = "09:00" if venue == "regular_open" else "09:10"
    return AuctionBatch("TWSE", venue, SUBMITTED, datetime.fromisoformat(f"2026-01-05T{clock}:00+08:00"), "synthetic")


def quote(price: int, qty: int) -> AuctionQuote:
    return AuctionQuote("TRADED", price, BOUNDS, qty, "synthetic-price", "synthetic-capacity")


@pytest.mark.parametrize("scenario,penalty_rate", [("baseline", Fraction(1, 1000)), ("high-friction", Fraction(3, 1000))])
def test_schedule_is_the_shared_exact_contract(scenario: str, penalty_rate: Fraction) -> None:
    assert cost_schedule(scenario) == CostSchedule(Fraction(1425, 1_000_000), 2000, 100, "ceil", Fraction(3, 1000), 100, "ceil", penalty_rate, 100, "ceil")
    assert cost_schedule() == cost_schedule("baseline")


@pytest.mark.parametrize("scenario", ["", "other", "BASELINE"])
def test_unknown_scenarios_are_rejected(scenario: str) -> None:
    with pytest.raises(ValueError, match="unknown H05 cost scenario"):
        cost_schedule(scenario)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("scenario,penalty", [("baseline", 10_000), ("high-friction", 30_000)])
def test_regular_fill_costs_are_cash_surcharges(side: str, scenario: str, penalty: int) -> None:
    # 1,000 shares at $100 = 10,000,000 cents. Fee 14,250 -> 14,300.
    initial = 200_000_000
    result = resolve_auction_batch(
        AccountState(initial, {"A": 1000} if side == "SELL" else {}, DECISION, "trade_date_cash"),
        [OrderIntent("fill", "A", side, 1000, 10_000, DECISION)],
        {"A": quote(10_000, 1000)},
        batch=batch(),
        costs=cost_schedule(scenario),
        max_positions=5,
    )
    outcome = result.outcomes[0]
    tax = 30_000 if side == "SELL" else 0
    assert outcome.disposition == "filled"
    assert (outcome.commission_cents, outcome.tax_cents, outcome.penalty_cents) == (14_300, tax, penalty)
    assert outcome.price_cents == 10_000
    assert result.ledger_events[0]["price"] == 100
    assert result.next_state is not None
    expected_cash = initial + 10_000_000 - 14_300 - tax - penalty if side == "SELL" else initial - 10_000_000 - 14_300 - penalty
    assert result.next_state.cash_cents == expected_cash


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_one_odd_share_pays_minimum_and_each_nonzero_component_rounds_up(side: str) -> None:
    result = resolve_auction_batch(
        AccountState(10_000, {"A": 1} if side == "SELL" else {}, DECISION, "trade_date_cash"),
        [OrderIntent("odd", "A", side, 1, 1000, DECISION)],
        {"A": quote(1000, 1)},
        batch=batch("intraday_odd"),
        costs=cost_schedule(),
        max_positions=5,
    )
    assert result.outcomes[0].filled_qty == 1
    assert (result.outcomes[0].commission_cents, result.outcomes[0].tax_cents, result.outcomes[0].penalty_cents) == (2000, 100 if side == "SELL" else 0, 100)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_separate_actual_legs_each_pay_minimum(side: str) -> None:
    state = AccountState(1_000_000, {"A": 200} if side == "SELL" else {}, DECISION, "trade_date_cash")
    split = resolve_auction_batch(
        state,
        [OrderIntent(f"leg-{i}", "A", side, 100, 1000, DECISION) for i in range(2)],
        {"A": quote(1000, 200)},
        batch=batch("intraday_odd"),
        costs=cost_schedule(),
        max_positions=5,
    )
    combined = resolve_auction_batch(
        state,
        [OrderIntent("combined", "A", side, 200, 1000, DECISION)],
        {"A": quote(1000, 200)},
        batch=batch("intraday_odd"),
        costs=cost_schedule(),
        max_positions=5,
    )
    assert [outcome.filled_qty for outcome in split.outcomes] == [100, 100]
    assert [outcome.commission_cents for outcome in split.outcomes] == [2000, 2000]
    assert combined.outcomes[0].commission_cents == 2000


def test_unfilled_leg_does_not_charge_minimum() -> None:
    state = AccountState(1_000_000, {}, DECISION, "trade_date_cash")
    result = resolve_auction_batch(
        state,
        [OrderIntent("unfilled", "A", "BUY", 100, 1000, DECISION)],
        {"A": quote(1000, 0)},
        batch=batch("intraday_odd"),
        costs=cost_schedule(),
        max_positions=5,
    )
    assert result.outcomes[0].filled_qty == 0
    assert result.outcomes[0].commission_cents == 0
    assert result.next_state is not None and result.next_state.cash_cents == state.cash_cents


@pytest.mark.parametrize("scenario,fee,penalty", [("baseline", 42_800, 30_000), ("high-friction", 42_800, 90_000)])
def test_five_fixed_slot_budgets_fit_initial_cash(scenario: str, fee: int, penalty: int) -> None:
    schedule = cost_schedule(scenario)
    quantity = buy_quantity_for_budget(budget_cents=40_000_000, price_cents=10_000, costs=schedule, venue="regular_open")
    assert quantity == 3000
    # The next lot needs 40m notional + 57,000 fee + a nonzero surcharge.
    codes = [f"A{i}" for i in range(5)]
    result = resolve_auction_batch(
        AccountState(200_000_000, {}, DECISION, "trade_date_cash"),
        [OrderIntent(code, code, "BUY", quantity, 10_000, DECISION) for code in codes],
        {code: quote(10_000, quantity) for code in codes},
        batch=batch(),
        costs=schedule,
        max_positions=5,
    )
    assert all(outcome.disposition == "filled" for outcome in result.outcomes)
    assert all(outcome.reserved_cash_cents == 30_000_000 + fee + penalty <= 40_000_000 for outcome in result.outcomes)
    assert result.next_state is not None
    assert result.next_state.cash_cents == 200_000_000 - 5 * (30_000_000 + fee + penalty)
