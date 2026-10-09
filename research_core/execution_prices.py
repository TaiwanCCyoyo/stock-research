"""Pure TWSE/TPEx ordinary-stock price feasibility helpers.

These functions model only a caller-supplied observed price, adverse slippage,
the ordinary-stock tick table, and explicitly known bounds.  A feasible price
is not evidence that an order filled: this module has no queue, venue, time,
quantity, cash, or fee model.  In particular, it never derives a daily price
limit from a previous close.

Numeric inputs are finite ``Decimal``, ``int``, or ``float`` values (floats
are converted through ``str``).  Values with more than 60 coefficient digits,
or nonzero values whose adjusted decimal exponent is outside [-60, 60], are
outside the supported domain and raise ``PriceError``.  The exponent condition
means ``1E-60 <= abs(value) < 1E61``; trailing coefficient zeros count toward
the digit limit.  Internal arithmetic uses its own fixed Decimal context.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Any

_MIN_PRICE = Decimal("0.01")
_BPS_DENOMINATOR = Decimal("10000")
_MAX_SIGNIFICANT_DIGITS = 60
_MAX_ADJUSTED = 60
_DECIMAL_CONTEXT = Context(prec=200, Emin=-200, Emax=200, rounding=ROUND_HALF_EVEN, traps=[])


class PriceError(ValueError):
    """Raised when price-feasibility input is invalid or unsupported."""


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float)):
        raise PriceError(f"{name} must be a finite Decimal, int, or float")
    if isinstance(value, float) and not math.isfinite(value):
        raise PriceError(f"{name} must be finite")
    try:
        number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
        if not number.is_finite():
            raise PriceError(f"{name} must be finite")
        digits = number.as_tuple().digits
        if len(digits) > _MAX_SIGNIFICANT_DIGITS or (number != 0 and abs(number.adjusted()) > _MAX_ADJUSTED):
            raise PriceError(f"{name} is outside the supported numeric domain")
        return number
    except (InvalidOperation, OverflowError, ValueError) as error:
        raise PriceError(f"{name} must be a finite Decimal, int, or float") from error


def _normalized(number: Decimal) -> Decimal:
    try:
        with localcontext(_DECIMAL_CONTEXT):
            return number.normalize()
    except (InvalidOperation, OverflowError, ValueError) as error:
        raise PriceError("numeric result is outside the supported domain") from error


def stock_tick(price: Decimal | int | float) -> Decimal:
    """Return the ordinary-stock tick for a positive TWSE/TPEx stock price."""
    value = _decimal(price, "price")
    return _stock_tick_decimal(value)


def _stock_tick_decimal(value: Decimal) -> Decimal:
    """Return a tick for an externally validated or internally computed price."""
    if value < _MIN_PRICE:
        raise PriceError("price must be at least 0.01")
    if value < Decimal("10"):
        return Decimal("0.01")
    if value < Decimal("50"):
        return Decimal("0.05")
    if value < Decimal("100"):
        return Decimal("0.1")
    if value < Decimal("500"):
        return Decimal("0.5")
    if value < Decimal("1000"):
        return Decimal("1")
    return Decimal("5")


def round_stock_price(price: Decimal | int | float, direction: str = "up") -> Decimal:
    """Round a positive stock price adversely to the applicable tick grid."""
    if not isinstance(direction, str) or direction not in {"up", "down"}:
        raise PriceError("direction must be 'up' or 'down'")
    value = _decimal(price, "price")
    return _round_decimal(value, direction)


def _round_decimal(value: Decimal, direction: str) -> Decimal:
    """Round an already validated or internally computed finite price."""
    if value < _MIN_PRICE:
        raise PriceError("price must be at least 0.01")
    tick = _stock_tick_decimal(value)
    rounding = ROUND_CEILING if direction == "up" else ROUND_FLOOR
    try:
        with localcontext(_DECIMAL_CONTEXT):
            rounded = (value / tick).to_integral_value(rounding=rounding) * tick
    except (InvalidOperation, OverflowError, ValueError) as error:
        raise PriceError("price is outside the supported numeric domain") from error
    return _normalized(rounded)


def _grid_price(value: Any, name: str) -> Decimal:
    price = _decimal(value, name)
    if price < _MIN_PRICE:
        raise PriceError(f"{name} must be at least 0.01")
    if round_stock_price(price, "down") != price:
        raise PriceError(f"{name} must be on the stock tick grid")
    return _normalized(price)


@dataclass(frozen=True)
class PriceLimits:
    """Caller-verified feasible bounds; ``upper=None`` explicitly means unlimited."""

    lower: Decimal
    upper: Decimal | None

    def __post_init__(self) -> None:
        lower = _grid_price(self.lower, "lower")
        upper = None if self.upper is None else _grid_price(self.upper, "upper")
        if upper is not None and upper < lower:
            raise PriceError("upper must be at least lower")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)


@dataclass(frozen=True)
class PriceCandidate:
    """A modeled feasible price, never proof that an order actually filled."""

    price: Decimal | None
    reason: str

    def __post_init__(self) -> None:
        if self.price is not None:
            object.__setattr__(self, "price", _grid_price(self.price, "price"))
        if not isinstance(self.reason, str) or not self.reason:
            raise PriceError("reason must be a non-empty string")


def adverse_stock_price(
    *,
    side: str,
    observed_price: Decimal | int | float | None,
    slippage_bps: Decimal | int | float,
    limits: PriceLimits | None,
) -> PriceCandidate:
    """Return an adverse rounded candidate or an explicit unavailable reason.

    ``missing_price`` takes precedence when both an observation and limits are
    absent.  ``limits=None`` otherwise means the caller has not supplied known
    bounds, so the result is ``missing_limits``.  Prices outside known bounds
    are invalid evidence; adverse candidates beyond a bound are unavailable and
    are never capped to that bound.
    """
    if not isinstance(side, str) or side not in {"BUY", "SELL"}:
        raise PriceError("side must be BUY or SELL")
    bps = _decimal(slippage_bps, "slippage_bps")
    if bps < 0 or bps >= _BPS_DENOMINATOR:
        raise PriceError("slippage_bps must be in [0, 10000)")
    if limits is not None and not isinstance(limits, PriceLimits):
        raise PriceError("limits must be PriceLimits or None")
    if observed_price is None:
        return PriceCandidate(None, "missing_price")
    observed = _grid_price(observed_price, "observed_price")
    if limits is None:
        return PriceCandidate(None, "missing_limits")
    if observed < limits.lower or (limits.upper is not None and observed > limits.upper):
        raise PriceError("observed_price is outside supplied limits")
    try:
        with localcontext(_DECIMAL_CONTEXT):
            factor = Decimal(1) + bps / _BPS_DENOMINATOR if side == "BUY" else Decimal(1) - bps / _BPS_DENOMINATOR
            target = observed * factor
    except (InvalidOperation, OverflowError, ValueError) as error:
        raise PriceError("adverse price is outside the supported numeric domain") from error
    if target < _MIN_PRICE:
        return PriceCandidate(None, "outside_limits")
    candidate = _round_decimal(target, "up" if side == "BUY" else "down")
    if candidate < limits.lower or (limits.upper is not None and candidate > limits.upper):
        return PriceCandidate(None, "outside_limits")
    return PriceCandidate(candidate, "price_feasible")
