"""Execution assumptions that must be stated, never defaulted.

The 2026-09-12 prototype had a `daily_limits(previous_close)` helper that applied a fixed +/-10%
band around the previous close. That helper reads like an observation and is not one. It is wrong
on an ex-dividend day (the exchange's reference price is not the previous close), wrong on a
resumption day, and wrong on a session with no limit at all -- and in each case it produces a
plausible band rather than an error, which is the failure mode that matters.

So the band is no longer computed from a price this module happens to have. A caller supplies a
`PriceBandPolicy` naming the **reference price**, whether limits **apply at all**, the band width,
and the **source or assumption** each of those came from. When the evidence is absent the result
is `unavailable`, and the order does not fill.

`no limit` and `unknown` are kept apart deliberately. A session with no price limit is tradable at
any price; a session whose limit we cannot establish is not something to guess at. Collapsing them
would turn missing evidence into the most permissive possible assumption.

Costs, capacity and venue are the same shape: required config with a stated basis, never a
built-in default. None of the values a caller passes in the tests are approved market parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from research_core.auction import CostSchedule
from research_core.execution_prices import PriceError, PriceLimits, round_stock_price

LimitStatus = Literal["bounded", "no_limit", "unavailable"]


class PolicyError(ValueError):
    """An execution assumption was requested without the evidence it requires."""


@dataclass(frozen=True)
class PriceBandPolicy:
    """How one session's price band is established, including the case where it is not.

    `reference_price` is whatever the exchange actually uses for that session, which on an
    ordinary day is the previous close and on an ex-dividend day is not. This module does not
    derive it; supplying it is the caller's job precisely because deriving it is what went wrong.
    """

    status: LimitStatus
    reference_price: Decimal | None
    band: Fraction | None
    basis: str

    def __post_init__(self) -> None:
        if not self.basis:
            raise PolicyError("every band policy must state its basis")
        if self.status == "bounded":
            if self.reference_price is None or self.band is None:
                raise PolicyError("a bounded band needs both a reference price and a width")
            if self.reference_price <= 0:
                raise PolicyError("reference price must be positive")
        if self.status in {"no_limit", "unavailable"} and (self.reference_price is not None or self.band is not None):
            raise PolicyError(f"a {self.status} band must not carry a reference price or width")

    def resolve(self) -> PriceLimits | None:
        """The limits to hand the auction layer, or None when the session is unbounded.

        Raises for `unavailable`: a caller must decide what to do about missing evidence rather
        than receive a band that looks usable.
        """
        if self.status == "unavailable":
            raise PolicyError(f"price band unavailable: {self.basis}")
        if self.status == "no_limit":
            # PriceLimits supports an open upper bound explicitly. A lower bound of one tick is
            # still required because a price must remain a positive number on the grid.
            return PriceLimits(lower=Decimal("0.01"), upper=None)
        assert self.reference_price is not None and self.band is not None
        try:
            lower = round_stock_price(self.reference_price * (Decimal(1) - Decimal(self.band.numerator) / Decimal(self.band.denominator)), "up")
            upper = round_stock_price(self.reference_price * (Decimal(1) + Decimal(self.band.numerator) / Decimal(self.band.denominator)), "down")
        except PriceError as error:
            raise PolicyError(f"reference price is not representable on the tick grid: {error}") from error
        return PriceLimits(lower=lower, upper=upper)


def bounded_band(*, reference_price: Decimal | float, band: Fraction, basis: str) -> PriceBandPolicy:
    return PriceBandPolicy(status="bounded", reference_price=Decimal(str(reference_price)), band=band, basis=basis)


def unlimited_band(*, basis: str) -> PriceBandPolicy:
    return PriceBandPolicy(status="no_limit", reference_price=None, band=None, basis=basis)


def unavailable_band(*, basis: str) -> PriceBandPolicy:
    return PriceBandPolicy(status="unavailable", reference_price=None, band=None, basis=basis)


@dataclass(frozen=True)
class CapacityPolicy:
    """How many shares this account is assumed able to fill, and on what stated basis.

    The shared auction layer refuses to fill a TRADED quote without `allocated_shares`, which is
    correct: an opening print is not evidence that this order could have been filled at it. The
    number therefore has to come from somewhere explicit, and that somewhere is recorded here so
    it can be sealed as the assumption it is.
    """

    shares: int
    basis: str

    def __post_init__(self) -> None:
        if self.shares < 0:
            raise PolicyError("capacity cannot be negative")
        if not self.basis:
            raise PolicyError("capacity must state its basis")


@dataclass(frozen=True)
class VenuePolicy:
    """Whether odd lots may be used, and from which date the chosen venue exists.

    The intraday odd-lot session begins 2020-10-26. That is a fact about the INTRADAY venue only
    and says nothing about after-hours odd-lot history, which is a separate market and a separate
    data question. Whole-lot-only is likewise a modelling choice, not a market rule: it changes
    what a small account can hold in a high-priced name, so it is config with a basis rather than
    a silent default.
    """

    allow_odd_lot: bool
    basis: str

    def __post_init__(self) -> None:
        if not self.basis:
            raise PolicyError("venue policy must state its basis")


@dataclass(frozen=True)
class LimitPolicy:
    """How a request's limit price is set, which decides whether a gap fills at all.

    This was an accidental default in the first draft: requests carried the decision session's
    close as their limit, so on a rising open every buy came back `limit_not_reached`. That is a
    real order type, but choosing it silently meant the book never traded and nothing said why.

    `band` makes the order marketable within the next session's legal range: a buy is priced at
    the highest price that session may print, a sell at the lowest. It is the closest feasible
    model of "take the opening auction" while staying a limit order, and it is still an
    assumption -- the basis records that.

    `reference` keeps the literal decision-session price, which is a genuinely different strategy
    (patient limit) and must be chosen deliberately, not inherited.
    """

    mode: Literal["band", "reference"]
    band: Fraction | None
    basis: str

    def __post_init__(self) -> None:
        if not self.basis:
            raise PolicyError("a limit policy must state its basis")
        if self.mode == "band" and self.band is None:
            raise PolicyError("a band limit policy needs a band width")

    def limit_cents(self, *, reference_cents: int, side: str) -> int:
        if self.mode == "reference" or self.band is None:
            return reference_cents
        reference = Decimal(reference_cents) / Decimal(100)
        width = Decimal(self.band.numerator) / Decimal(self.band.denominator)
        # Round inward so the limit is itself a legally printable price.
        edge = round_stock_price(reference * (Decimal(1) + width), "down") if side == "BUY" else round_stock_price(reference * (Decimal(1) - width), "up")
        return int(edge * 100)


@dataclass(frozen=True)
class ExecutionConfig:
    """Everything the runner must be told before it can fill anything."""

    costs: CostSchedule
    costs_basis: str
    venue: VenuePolicy
    gross_budget_cents: int
    max_positions: int
    limits: LimitPolicy

    def __post_init__(self) -> None:
        if not self.costs_basis:
            raise PolicyError("the cost schedule must state its basis")
        if self.gross_budget_cents <= 0:
            raise PolicyError("gross budget must be positive")
        if self.max_positions <= 0:
            raise PolicyError("max_positions must be positive")


def cost_schedule(*, commission_rate: Fraction, sell_tax_rate: Fraction, min_commission_cents: int, rounding: str = "floor") -> CostSchedule:
    """Build a cost schedule from explicitly supplied rates. No published default is assumed."""
    return CostSchedule(
        commission_rate=commission_rate,
        min_commission_cents=min_commission_cents,
        commission_quantum_cents=1,
        commission_rounding=rounding,
        sell_tax_rate=sell_tax_rate,
        tax_quantum_cents=1,
        tax_rounding=rounding,
        penalty_rate=Fraction(0),
        penalty_quantum_cents=1,
        penalty_rounding=rounding,
    )
