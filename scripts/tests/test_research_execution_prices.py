from __future__ import annotations

from decimal import ROUND_DOWN, Context, Decimal, Inexact, Overflow, Rounded, getcontext, setcontext

import pytest

from research_core.execution_prices import PriceCandidate, PriceError, PriceLimits, adverse_stock_price, round_stock_price, stock_tick


@pytest.mark.parametrize(
    ("price", "tick"),
    [("0.01", "0.01"), ("9.99", "0.01"), ("10", "0.05"), ("50", "0.1"), ("100", "0.5"), ("500", "1"), ("1000", "5")],
)
def test_stock_tick_boundaries(price: str, tick: str) -> None:
    assert stock_tick(Decimal(price)) == Decimal(tick)


@pytest.mark.parametrize(
    ("price", "up", "down"),
    [
        ("0.011", "0.02", "0.01"),
        ("9.991", "10", "9.99"),
        ("10.01", "10.05", "10"),
        ("50.01", "50.1", "50"),
        ("100.01", "100.5", "100"),
        ("500.01", "501", "500"),
        ("1000.01", "1005", "1000"),
    ],
)
def test_rounding_crosses_tick_bands_in_both_directions(price: str, up: str, down: str) -> None:
    assert round_stock_price(Decimal(price), "up") == Decimal(up)
    assert round_stock_price(Decimal(price), "down") == Decimal(down)


def test_rounding_down_is_a_floor() -> None:
    assert round_stock_price(Decimal("40.601"), "down") == Decimal("40.60")


@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf"), Decimal("NaN"), Decimal("Infinity"), 0, -1])
def test_stock_price_rejects_invalid_values(value: object) -> None:
    with pytest.raises(PriceError):
        stock_tick(value)  # type: ignore[arg-type]


def test_documented_numeric_domain_boundaries() -> None:
    assert stock_tick(Decimal("9E60")) == Decimal("5")
    with pytest.raises(PriceError):
        stock_tick(Decimal("1E61"))
    with pytest.raises(PriceError):
        adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=Decimal("1E-61"), limits=None)


def test_limits_are_immutable_explicit_and_on_grid() -> None:
    limits = PriceLimits(Decimal("36.550"), None)
    assert limits.lower == Decimal("36.55")
    assert limits.upper is None
    with pytest.raises((AttributeError, TypeError)):
        limits.lower = Decimal("40")  # type: ignore[misc]
    for lower, upper in [("36.551", "44.65"), ("36.55", "44.651"), ("44.65", "36.55")]:
        with pytest.raises(PriceError):
            PriceLimits(Decimal(lower), Decimal(upper))


def test_missing_observation_precedes_unknown_limits_and_unlimited_is_explicit() -> None:
    assert adverse_stock_price(side="BUY", observed_price=None, slippage_bps=0, limits=None) == PriceCandidate(None, "missing_price")
    assert adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=0, limits=None) == PriceCandidate(None, "missing_limits")
    unlimited = PriceLimits(Decimal("0.01"), None)
    assert adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=0, limits=unlimited) == PriceCandidate(
        Decimal("40.60"), "price_feasible"
    )


def test_adverse_prices_are_rounded_and_never_capped() -> None:
    limits = PriceLimits(Decimal("36.55"), Decimal("44.65"))
    assert adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=10, limits=limits) == PriceCandidate(
        Decimal("40.65"), "price_feasible"
    )
    assert adverse_stock_price(side="SELL", observed_price=Decimal("40.60"), slippage_bps=10, limits=limits) == PriceCandidate(
        Decimal("40.55"), "price_feasible"
    )
    assert adverse_stock_price(side="BUY", observed_price=Decimal("44.65"), slippage_bps=10, limits=limits) == PriceCandidate(None, "outside_limits")
    assert adverse_stock_price(side="SELL", observed_price=Decimal("36.55"), slippage_bps=10, limits=limits) == PriceCandidate(None, "outside_limits")


def test_synthetic_limit_regressions_and_zero_bps() -> None:
    limits = PriceLimits(Decimal("90"), Decimal("110"))
    assert adverse_stock_price(side="BUY", observed_price=Decimal("109.5"), slippage_bps=50, limits=limits) == PriceCandidate(None, "outside_limits")
    assert adverse_stock_price(side="SELL", observed_price=Decimal("90.1"), slippage_bps=50, limits=limits) == PriceCandidate(None, "outside_limits")
    assert adverse_stock_price(side="BUY", observed_price=Decimal("100"), slippage_bps=0, limits=limits) == PriceCandidate(Decimal("100"), "price_feasible")


def test_candidate_price_does_not_add_a_fee() -> None:
    limits = PriceLimits(Decimal("36.55"), Decimal("44.65"))
    # This layer returns a price only; no fee, cash, or quantity adjustment exists.
    assert adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=0, limits=limits) == PriceCandidate(Decimal("40.60"), "price_feasible")


@pytest.mark.parametrize("side", ["buy", "SHORT", True])
def test_invalid_side_bps_and_observation_evidence_are_rejected(side: object) -> None:
    limits = PriceLimits(Decimal("36.55"), Decimal("44.65"))
    with pytest.raises(PriceError):
        adverse_stock_price(side=side, observed_price=Decimal("40.60"), slippage_bps=0, limits=limits)  # type: ignore[arg-type]
    for bps in [True, "1", float("nan"), float("inf"), -1, 10000]:
        with pytest.raises(PriceError):
            adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=bps, limits=limits)  # type: ignore[arg-type]
    for observed in [Decimal("40.61"), Decimal("44.70")]:
        with pytest.raises(PriceError):
            adverse_stock_price(side="BUY", observed_price=observed, slippage_bps=0, limits=limits)


def test_invalid_direction_and_wrong_limits_type_are_controlled_errors() -> None:
    invalid_directions: list[object] = ["sideways", [], None]
    for direction in invalid_directions:
        with pytest.raises(PriceError):
            round_stock_price(Decimal("40.60"), direction)  # type: ignore[arg-type]
    with pytest.raises(PriceError):
        adverse_stock_price(side=[], observed_price=Decimal("40.60"), slippage_bps=0, limits=PriceLimits(Decimal("36.55"), Decimal("44.65")))  # type: ignore[arg-type]
    with pytest.raises(PriceError):
        adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=0, limits=object())  # type: ignore[arg-type]
    with pytest.raises(PriceError):
        adverse_stock_price(side="BUY", observed_price=None, slippage_bps=0, limits=object())  # type: ignore[arg-type]


def test_decimal_context_does_not_change_result_or_mutate_input() -> None:
    observed = Decimal("40.60")
    limits = PriceLimits(Decimal("36.55"), Decimal("44.65"))
    original_precision = getcontext().prec
    try:
        getcontext().prec = 6
        low_precision = adverse_stock_price(side="BUY", observed_price=observed, slippage_bps=10, limits=limits)
        getcontext().prec = 50
        high_precision = adverse_stock_price(side="BUY", observed_price=observed, slippage_bps=10, limits=limits)
    finally:
        getcontext().prec = original_precision
    assert low_precision == high_precision == PriceCandidate(Decimal("40.65"), "price_feasible")
    assert observed == Decimal("40.60")


def test_hostile_decimal_context_does_not_change_adverse_tick_rounding() -> None:
    saved_context = getcontext().copy()
    limits = PriceLimits(Decimal("36.55"), Decimal("44.65"))
    try:
        setcontext(Context(prec=6, Emin=-6, Emax=6, rounding=ROUND_DOWN, traps=[Inexact, Rounded, Overflow]))
        assert adverse_stock_price(side="BUY", observed_price=Decimal("40.60"), slippage_bps=Decimal("1e-60"), limits=limits) == PriceCandidate(
            Decimal("40.65"), "price_feasible"
        )
        assert adverse_stock_price(side="SELL", observed_price=Decimal("40.60"), slippage_bps=Decimal("1e-60"), limits=limits) == PriceCandidate(
            Decimal("40.55"), "price_feasible"
        )
    finally:
        setcontext(saved_context)
