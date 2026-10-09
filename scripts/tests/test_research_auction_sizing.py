"""Exact, venue-specific buy sizing without candidate or market-data selection."""

from fractions import Fraction

import pytest

from research_core.auction import AuctionError, CostSchedule, buy_quantity_for_budget


def schedule(
    *,
    commission_rate: Fraction = Fraction(0),
    minimum: int = 0,
    commission_quantum: int = 1,
    penalty_rate: Fraction = Fraction(0),
    penalty_quantum: int = 1,
) -> CostSchedule:
    return CostSchedule(
        commission_rate=commission_rate,
        min_commission_cents=minimum,
        commission_quantum_cents=commission_quantum,
        commission_rounding="ceil",
        sell_tax_rate=Fraction(0),
        tax_quantum_cents=1,
        tax_rounding="ceil",
        penalty_rate=penalty_rate,
        penalty_quantum_cents=penalty_quantum,
        penalty_rounding="ceil",
    )


def test_zero_and_insufficient_budgets_return_zero() -> None:
    costs = schedule(minimum=2_000)
    assert buy_quantity_for_budget(budget_cents=0, price_cents=100, costs=costs, venue="intraday_odd") == 0
    assert buy_quantity_for_budget(budget_cents=2_099, price_cents=100, costs=costs, venue="intraday_odd") == 0


def test_exact_budget_includes_fee_minimum_quantum_rounding_and_penalty() -> None:
    costs = schedule(
        commission_rate=Fraction(1, 1_000),
        minimum=20,
        commission_quantum=10,
        penalty_rate=Fraction(1, 1_000),
        penalty_quantum=10,
    )
    # 101 shares at $1: 10,100 notional + 20 commission + 20 penalty.
    assert buy_quantity_for_budget(budget_cents=10_140, price_cents=100, costs=costs, venue="intraday_odd") == 101


def test_regular_open_returns_largest_valid_lot_and_next_lot_is_over_budget() -> None:
    costs = schedule(commission_rate=Fraction(1, 1_000))
    quantity = buy_quantity_for_budget(budget_cents=3_003_000, price_cents=1_000, costs=costs, venue="regular_open")
    assert quantity == 3_000
    assert quantity % 1_000 == 0
    assert 4_000 * 1_000 + 4_000 > 3_003_000


def test_one_cent_shortfall_reduces_size_instead_of_rounding_the_budget() -> None:
    costs = schedule(minimum=2000)
    assert buy_quantity_for_budget(budget_cents=12000, price_cents=100, costs=costs, venue="intraday_odd") == 100
    assert buy_quantity_for_budget(budget_cents=11999, price_cents=100, costs=costs, venue="intraday_odd") == 99
    assert buy_quantity_for_budget(budget_cents=101999, price_cents=100, costs=costs, venue="regular_open") == 0


@pytest.mark.parametrize("venue", ["intraday_odd", "afterhours_odd"])
def test_odd_lot_sizing_is_capped_at_999(venue: str) -> None:
    assert buy_quantity_for_budget(budget_cents=1_000_000, price_cents=100, costs=schedule(), venue=venue) == 999


@pytest.mark.parametrize(
    ("kwargs"),
    [
        {"budget_cents": -1, "price_cents": 100},
        {"budget_cents": True, "price_cents": 100},
        {"budget_cents": "100", "price_cents": 100},
        {"budget_cents": 100, "price_cents": -100},
        {"budget_cents": 100, "price_cents": True},
        {"budget_cents": 100, "price_cents": "100"},
        {"budget_cents": 100, "price_cents": 1_001},
    ],
)
def test_budget_and_price_inputs_must_be_valid_integer_grid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(AuctionError):
        buy_quantity_for_budget(**kwargs, costs=schedule(), venue="intraday_odd")  # type: ignore[arg-type]


@pytest.mark.parametrize("venue", ["unsupported", "", True])
def test_unsupported_venue_and_invalid_costs_are_rejected(venue: object) -> None:
    with pytest.raises(AuctionError):
        buy_quantity_for_budget(budget_cents=100, price_cents=100, costs=schedule(), venue=venue)  # type: ignore[arg-type]
    with pytest.raises(AuctionError):
        buy_quantity_for_budget(budget_cents=100, price_cents=100, costs=object(), venue="intraday_odd")  # type: ignore[arg-type]
