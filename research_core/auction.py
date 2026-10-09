"""One explicitly identified, causally reserved synthetic auction batch.

This is deliberately not an exchange simulator or a broker buying-power model.
It consumes caller-supplied auction evidence and never converts missing evidence
into a zero fill or a later executable account state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from research_core.execution_prices import PriceError, PriceLimits, round_stock_price


class AuctionError(ValueError):
    """Raised when a single-auction input violates this compact contract."""


def _positive_int(value: Any, name: str, *, zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1):
        raise AuctionError(f"{name} must be a {'nonnegative' if zero else 'positive'} integer")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuctionError(f"{name} must be a non-empty string")
    return value


def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise AuctionError(f"{name} must be an aware +08:00 datetime")
    return value


def _price(cents: Any, name: str) -> int:
    cents = _positive_int(cents, name)
    try:
        decimal = _cents_decimal(cents)
        if round_stock_price(decimal, "down") != decimal:
            raise AuctionError(f"{name} must be on the stock tick grid")
    except PriceError as error:
        raise AuctionError(f"{name} is not a valid stock price") from error
    return cents


def _cents_decimal(cents: int) -> Decimal:
    """Construct a price without involving the caller's Decimal context."""
    return Decimal(f"{cents // 100}.{cents % 100:02d}")


@dataclass(frozen=True)
class CostSchedule:
    commission_rate: Fraction
    min_commission_cents: int
    commission_quantum_cents: int
    commission_rounding: str
    sell_tax_rate: Fraction
    tax_quantum_cents: int
    tax_rounding: str
    penalty_rate: Fraction
    penalty_quantum_cents: int
    penalty_rounding: str

    def __post_init__(self) -> None:
        for name in ("commission_rate", "sell_tax_rate", "penalty_rate"):
            value = getattr(self, name)
            if type(value) is not Fraction or value < 0:
                raise AuctionError(f"{name} must be a nonnegative Fraction")
        if self.commission_rate + self.sell_tax_rate + self.penalty_rate >= 1:
            raise AuctionError("combined cost rates must be less than one")
        _positive_int(self.min_commission_cents, "min_commission_cents", zero=True)
        for name in ("commission_quantum_cents", "tax_quantum_cents", "penalty_quantum_cents"):
            _positive_int(getattr(self, name), name)
        for name in ("commission_rounding", "tax_rounding", "penalty_rounding"):
            if getattr(self, name) not in {"ceil", "floor", "half_up"}:
                raise AuctionError(f"{name} must be ceil, floor, or half_up")


@dataclass(frozen=True)
class AccountState:
    cash_cents: int
    positions: Mapping[str, int]
    as_of: datetime
    cash_basis: str
    pending_order_ids: tuple[str, ...] = ()
    reserved_position_codes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _positive_int(self.cash_cents, "cash_cents", zero=True)
        if not isinstance(self.positions, Mapping):
            raise AuctionError("positions must be a mapping")
        copied: dict[str, int] = {}
        for code, qty in self.positions.items():
            copied[_text(code, "position code")] = _positive_int(qty, "position qty")
        _time(self.as_of, "as_of")
        if self.cash_basis not in {"trade_date_cash", "settled_cash"}:
            raise AuctionError("cash_basis must be trade_date_cash or settled_cash")
        if not isinstance(self.pending_order_ids, tuple):
            raise AuctionError("pending_order_ids must be a tuple")
        pending = tuple(_text(order_id, "pending order_id") for order_id in self.pending_order_ids)
        if len(set(pending)) != len(pending):
            raise AuctionError("pending_order_ids must be unique")
        if not isinstance(self.reserved_position_codes, (set, frozenset)):
            raise AuctionError("reserved_position_codes must be a set or frozenset")
        reserved_codes = frozenset(_text(code, "reserved position code") for code in self.reserved_position_codes)
        object.__setattr__(self, "positions", MappingProxyType(copied))
        object.__setattr__(self, "pending_order_ids", pending)
        object.__setattr__(self, "reserved_position_codes", reserved_codes)


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    code: str
    side: str
    qty: int
    limit_price_cents: int
    decision_at: datetime

    def __post_init__(self) -> None:
        _text(self.order_id, "order_id")
        _text(self.code, "code")
        if self.side not in {"BUY", "SELL"}:
            raise AuctionError("side must be BUY or SELL")
        _positive_int(self.qty, "qty")
        _price(self.limit_price_cents, "limit_price_cents")
        _time(self.decision_at, "decision_at")


@dataclass(frozen=True)
class AuctionQuote:
    status: str
    price_cents: int | None
    limits: PriceLimits | None
    allocated_shares: int | None
    source_id: str
    capacity_basis: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"TRADED", "HALT", "NO_TRADE", "UNKNOWN"}:
            raise AuctionError("unknown quote status")
        if self.status != "UNKNOWN":
            _text(self.source_id, "source_id")
        elif self.source_id:
            _text(self.source_id, "source_id")
        if self.limits is not None and not isinstance(self.limits, PriceLimits):
            raise AuctionError("limits must be PriceLimits or None")
        if self.price_cents is not None:
            _price(self.price_cents, "price_cents")
        if self.allocated_shares is not None:
            _positive_int(self.allocated_shares, "allocated_shares", zero=True)
            _text(self.capacity_basis, "capacity_basis")
        if self.status in {"HALT", "NO_TRADE"} and (self.price_cents is not None or self.allocated_shares is not None):
            raise AuctionError("HALT and NO_TRADE cannot carry price or capacity")
        if self.status == "TRADED" and self.price_cents is not None and self.limits is not None:
            value = _cents_decimal(self.price_cents)
            if value < self.limits.lower or (self.limits.upper is not None and value > self.limits.upper):
                raise AuctionError("observed price is outside supplied limits")


@dataclass(frozen=True)
class AuctionBatch:
    exchange: str
    venue: str
    submitted_at: datetime
    auction_at: datetime
    session_id: str

    def __post_init__(self) -> None:
        if self.exchange not in {"TWSE", "TPEX"} or self.venue not in {"regular_open", "intraday_odd", "afterhours_odd"}:
            raise AuctionError("unsupported exchange or venue")
        submitted, auction = _time(self.submitted_at, "submitted_at"), _time(self.auction_at, "auction_at")
        if submitted >= auction:
            raise AuctionError("submitted_at must precede auction_at")
        if self.venue == "regular_open":
            expected = (9, 0)
        elif self.venue == "intraday_odd":
            if auction.date().isoformat() < "2020-10-26":
                raise AuctionError("intraday odd-lot is unsupported before 2020-10-26")
            expected = (9, 10)
        else:
            expected = (14, 30)
        if (auction.hour, auction.minute, auction.second, auction.microsecond) != (*expected, 0, 0):
            raise AuctionError("auction_at does not match the modeled venue time")
        _text(self.session_id, "session_id")


@dataclass(frozen=True)
class RoutedOrder:
    """One intent routed to a caller-identified session and its fee schedule."""

    order: OrderIntent
    batch: AuctionBatch
    costs: CostSchedule

    def __post_init__(self) -> None:
        if not isinstance(self.order, OrderIntent) or not isinstance(self.batch, AuctionBatch) or not isinstance(self.costs, CostSchedule):
            raise AuctionError("RoutedOrder requires OrderIntent, AuctionBatch, and CostSchedule")


@dataclass(frozen=True)
class AuctionOutcome:
    order_id: str
    code: str
    side: str
    disposition: str
    reason: str
    requested_qty: int
    filled_qty: int
    reserved_cash_cents: int
    price_cents: int | None
    commission_cents: int = 0
    tax_cents: int = 0
    penalty_cents: int = 0
    source_id: str | None = None
    capacity_basis: str | None = None


@dataclass(frozen=True)
class BatchResult:
    next_state: AccountState | None
    state_complete: bool
    outcomes: tuple[AuctionOutcome, ...]
    ledger_events: tuple[Mapping[str, Any], ...]

    @property
    def continuation_allowed(self) -> bool:
        """Whether this result may seed another batch without lifecycle reconciliation."""
        return self.state_complete and self.next_state is not None and not self.next_state.pending_order_ids


def _rounded(amount: Fraction, quantum: int, rule: str) -> int:
    units = amount / quantum
    floor = units.numerator // units.denominator
    if rule == "floor":
        return floor * quantum
    if rule == "ceil":
        return (floor + (units != floor)) * quantum
    return (floor + (2 * (units - floor) >= 1)) * quantum


def _costs(notional: int, side: str, costs: CostSchedule) -> tuple[int, int, int]:
    commission = max(
        costs.min_commission_cents,
        _rounded(notional * costs.commission_rate, costs.commission_quantum_cents, costs.commission_rounding),
    )
    tax = _rounded(notional * costs.sell_tax_rate, costs.tax_quantum_cents, costs.tax_rounding) if side == "SELL" else 0
    penalty = _rounded(notional * costs.penalty_rate, costs.penalty_quantum_cents, costs.penalty_rounding)
    return commission, tax, penalty


def buy_quantity_for_budget(
    *,
    budget_cents: int,
    price_cents: int,
    costs: CostSchedule,
    venue: str,
) -> int:
    """Return the largest buy quantity whose notional and modeled costs fit a budget."""
    budget = _positive_int(budget_cents, "budget_cents", zero=True)
    price = _price(price_cents, "price_cents")
    if not isinstance(costs, CostSchedule):
        raise AuctionError("costs must be a CostSchedule")
    if venue == "regular_open":
        unit = 1000
        upper = budget // (unit * price)
    elif venue in {"intraday_odd", "afterhours_odd"}:
        unit = 1
        upper = 999
    else:
        raise AuctionError("unsupported venue")

    def affordable(units: int) -> bool:
        qty = units * unit
        commission, tax, penalty = _costs(qty * price, "BUY", costs)
        return qty * price + commission + tax + penalty <= budget

    low, high = 0, upper
    while low < high:
        middle = (low + high + 1) // 2
        if affordable(middle):
            low = middle
        else:
            high = middle - 1
    return low * unit


def _sell_shortfall(order: OrderIntent, venue: str, costs: CostSchedule) -> int:
    unit = 1000 if venue == "regular_open" else 1
    rate = costs.commission_rate + costs.sell_tax_rate + costs.penalty_rate

    def error(rate: Fraction, quantum: int, rounding: str) -> int:
        return quantum if rate and rounding in {"ceil", "half_up"} else 0

    constant = max(costs.min_commission_cents, error(costs.commission_rate, costs.commission_quantum_cents, costs.commission_rounding))
    constant += error(costs.sell_tax_rate, costs.tax_quantum_cents, costs.tax_rounding)
    constant += error(costs.penalty_rate, costs.penalty_quantum_cents, costs.penalty_rounding)
    deficit = Fraction(constant) - (1 - rate) * unit * order.limit_price_cents
    return max(0, -(-deficit.numerator // deficit.denominator))


def _valid_qty(order: OrderIntent, venue: str) -> bool:
    return order.qty % 1000 == 0 if venue == "regular_open" else 1 <= order.qty <= 999


def _resolve_auction_core(
    state: AccountState,
    routed_orders: Sequence[RoutedOrder],
    quotes: Mapping[tuple[str, str], AuctionQuote],
    *,
    max_positions: int,
    cutoff: datetime,
) -> BatchResult:
    """Resolve already-validated routed requests against one shared reservation."""
    orders = [routed.order for routed in routed_orders]

    available = state.cash_cents
    held_reserved: dict[str, int] = {}
    admitted: list[tuple[RoutedOrder, int]] = []
    outcomes: list[AuctionOutcome] = []
    buy_codes: set[str] = set()
    occupied_codes = set(state.positions) | set(state.reserved_position_codes)
    for routed in routed_orders:
        order, batch, costs = routed.order, routed.batch, routed.costs
        if not _valid_qty(order, batch.venue):
            outcomes.append(AuctionOutcome(order.order_id, order.code, order.side, "rejected", "invalid_venue_quantity", order.qty, 0, 0, None))
            continue
        if order.side == "BUY":
            commission, tax, penalty = _costs(order.qty * order.limit_price_cents, "BUY", costs)
            reserved = order.qty * order.limit_price_cents + commission + tax + penalty
            adds_slot = order.code not in occupied_codes and order.code not in buy_codes
            if available < reserved:
                reason = "insufficient_reserved_cash"
            elif adds_slot and len(occupied_codes | buy_codes) >= max_positions:
                reason = "max_positions_reserved"
            else:
                available -= reserved
                buy_codes.add(order.code)
                admitted.append((routed, reserved))
                continue
        else:
            reserved = _sell_shortfall(order, batch.venue, costs)
            if state.positions.get(order.code, 0) - held_reserved.get(order.code, 0) < order.qty:
                reason = "insufficient_reserved_shares"
            elif available < reserved:
                reason = "insufficient_reserved_cash"
            else:
                available -= reserved
                held_reserved[order.code] = held_reserved.get(order.code, 0) + order.qty
                admitted.append((routed, reserved))
                continue
        outcomes.append(AuctionOutcome(order.order_id, order.code, order.side, "rejected", reason, order.qty, 0, 0, None))

    positions = dict(state.positions)
    cash = state.cash_cents
    remaining_cap: dict[tuple[str, str], int] = {}
    events: list[Mapping[str, Any]] = []
    complete = True
    pending_order_ids: list[str] = []
    for routed, reserved in admitted:
        order, batch, costs = routed.order, routed.batch, routed.costs
        quote = quotes.get((batch.session_id, order.code))
        if (
            quote is None
            or quote.status == "UNKNOWN"
            or (quote.status == "TRADED" and (quote.price_cents is None or quote.limits is None or quote.allocated_shares is None))
        ):
            outcomes.append(
                AuctionOutcome(
                    order.order_id,
                    order.code,
                    order.side,
                    "unavailable",
                    "missing_auction_evidence",
                    order.qty,
                    0,
                    reserved,
                    None,
                    source_id=None if quote is None else quote.source_id,
                )
            )
            complete = False
            continue
        if quote.status in {"HALT", "NO_TRADE"}:
            outcomes.append(
                AuctionOutcome(
                    order.order_id,
                    order.code,
                    order.side,
                    "unfilled",
                    quote.status.lower(),
                    order.qty,
                    0,
                    reserved,
                    None,
                    source_id=quote.source_id,
                )
            )
            pending_order_ids.append(order.order_id)
            continue
        assert quote.price_cents is not None and quote.limits is not None and quote.allocated_shares is not None
        price = quote.price_cents
        limit = _cents_decimal(order.limit_price_cents)
        if limit < quote.limits.lower or (quote.limits.upper is not None and limit > quote.limits.upper):
            outcomes.append(
                AuctionOutcome(
                    order.order_id,
                    order.code,
                    order.side,
                    "unfilled",
                    "order_limit_outside_bounds",
                    order.qty,
                    0,
                    reserved,
                    None,
                    source_id=quote.source_id,
                )
            )
            continue
        if (order.side == "BUY" and price > order.limit_price_cents) or (order.side == "SELL" and price < order.limit_price_cents):
            outcomes.append(
                AuctionOutcome(
                    order.order_id,
                    order.code,
                    order.side,
                    "unfilled",
                    "limit_not_reached",
                    order.qty,
                    0,
                    reserved,
                    price,
                    source_id=quote.source_id,
                )
            )
            pending_order_ids.append(order.order_id)
            continue
        capacity_key = (batch.session_id, order.code)
        cap = remaining_cap.setdefault(capacity_key, quote.allocated_shares)
        filled = min(order.qty, cap)
        if batch.venue == "regular_open":
            filled = (filled // 1000) * 1000
        remaining_cap[capacity_key] = cap - filled
        if not filled:
            outcomes.append(
                AuctionOutcome(
                    order.order_id,
                    order.code,
                    order.side,
                    "unfilled",
                    "no_allocated_capacity",
                    order.qty,
                    0,
                    reserved,
                    price,
                    source_id=quote.source_id,
                    capacity_basis=quote.capacity_basis,
                )
            )
            pending_order_ids.append(order.order_id)
            continue
        commission, tax, penalty = _costs(filled * price, order.side, costs)
        total_cost = commission + tax + penalty
        if order.side == "BUY":
            cash -= filled * price + total_cost
            positions[order.code] = positions.get(order.code, 0) + filled
            total = -(filled * price + total_cost)
        else:
            cash += filled * price - total_cost
            positions[order.code] -= filled
            if positions[order.code] == 0:
                del positions[order.code]
            total = filled * price - total_cost
        event: dict[str, Any] = {
            "action": order.side,
            "code": order.code,
            "date": batch.auction_at.isoformat(),
            "qty": filled,
            "total": total / 100,
            "order_id": order.order_id,
            "session_id": batch.session_id,
            "venue": batch.venue,
            "source_id": quote.source_id,
            "capacity_basis": quote.capacity_basis,
            "price": price / 100,
            "commission_cents": commission,
            "tax_cents": tax,
            "penalty_cents": penalty,
        }
        if order.side == "SELL":
            event.update({"gross_proceeds": filled * price / 100, "cost_total": total_cost / 100})
        events.append(MappingProxyType(event))
        outcomes.append(
            AuctionOutcome(
                order.order_id,
                order.code,
                order.side,
                "filled" if filled == order.qty else "partial",
                "filled" if filled == order.qty else "residual_pending",
                order.qty,
                filled,
                reserved,
                price,
                commission,
                tax,
                penalty,
                quote.source_id,
                quote.capacity_basis,
            )
        )
        if filled != order.qty:
            pending_order_ids.append(order.order_id)
    # Return outcomes in input priority even though admission failures were discovered early.
    by_id = {item.order_id: item for item in outcomes}
    next_state = (
        AccountState(
            cash,
            positions,
            cutoff,
            "trade_date_cash" if events else state.cash_basis,
            tuple(pending_order_ids),
            state.reserved_position_codes,
        )
        if complete
        else None
    )
    return BatchResult(next_state, complete, tuple(by_id[item.order_id] for item in orders), tuple(events))


def _validate_cohort(
    state: AccountState,
    routed_orders: Sequence[RoutedOrder],
    quotes: Mapping[tuple[str, str], AuctionQuote],
    max_positions: int,
    *,
    require_nonempty: bool,
) -> None:
    if not isinstance(state, AccountState):
        raise AuctionError("state must use auction contract types")
    _positive_int(max_positions, "max_positions")
    if not isinstance(routed_orders, Sequence) or isinstance(routed_orders, (str, bytes)):
        raise AuctionError("routed_orders must be a sequence")
    if require_nonempty and not routed_orders:
        raise AuctionError("routed_orders must be nonempty")
    if not isinstance(quotes, Mapping):
        raise AuctionError("quotes must be a mapping")
    if state.pending_order_ids:
        raise AuctionError("pending orders require external lifecycle reconciliation")
    if len(set(state.positions) | set(state.reserved_position_codes)) > max_positions:
        raise AuctionError("initial positions exceed max_positions")
    if not routed_orders:
        return
    first = routed_orders[0]
    if not isinstance(first, RoutedOrder):
        raise AuctionError("routed_orders must contain RoutedOrder")
    submitted, auction, venue = first.batch.submitted_at, first.batch.auction_at, first.batch.venue
    if state.as_of > submitted:
        raise AuctionError("state.as_of must not follow submission")
    sessions: dict[str, AuctionBatch] = {}
    exchange_venues: dict[tuple[str, str], str] = {}
    code_sessions: dict[str, str] = {}
    order_ids: set[str] = set()
    sides: dict[str, str] = {}
    for routed in routed_orders:
        if not isinstance(routed, RoutedOrder):
            raise AuctionError("routed_orders must contain RoutedOrder")
        order, batch = routed.order, routed.batch
        if (batch.submitted_at, batch.auction_at, batch.venue) != (submitted, auction, venue):
            raise AuctionError("cohort batches must share submission, auction, and venue")
        if batch.session_id in sessions and sessions[batch.session_id] != batch:
            raise AuctionError("session_id must map to one complete AuctionBatch")
        exchange_venue = (batch.exchange, batch.venue)
        if exchange_venue in exchange_venues and exchange_venues[exchange_venue] != batch.session_id:
            raise AuctionError("only one batch per exchange and venue is allowed")
        sessions[batch.session_id] = batch
        exchange_venues[exchange_venue] = batch.session_id
        if order.order_id in order_ids:
            raise AuctionError("order IDs must be unique")
        if order.code in sides and sides[order.code] != order.side:
            raise AuctionError("opposite sides for a code are ambiguous")
        if order.code in code_sessions and code_sessions[order.code] != batch.session_id:
            raise AuctionError("a code cannot route to different sessions")
        if order.decision_at > submitted or order.decision_at.date() >= auction.date():
            raise AuctionError("decision time is not eligible for this auction")
        order_ids.add(order.order_id)
        sides[order.code] = order.side
        code_sessions[order.code] = batch.session_id
    for key, quote in quotes.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise AuctionError("quote keys must be (session_id, code) tuples")
        session_id, code = key
        _text(session_id, "quote session_id")
        _text(code, "quote code")
        if session_id not in sessions:
            raise AuctionError("quote references an unrecognized session_id")
        if not isinstance(quote, AuctionQuote):
            raise AuctionError("quotes must contain AuctionQuote")


def resolve_auction_cohort(
    state: AccountState,
    routed_orders: Sequence[RoutedOrder],
    quotes: Mapping[tuple[str, str], AuctionQuote],
    *,
    max_positions: int,
) -> BatchResult:
    """Reserve simultaneous routed requests once, then resolve each route's evidence."""
    _validate_cohort(state, routed_orders, quotes, max_positions, require_nonempty=True)
    return _resolve_auction_core(
        state,
        routed_orders,
        quotes,
        max_positions=max_positions,
        cutoff=routed_orders[0].batch.auction_at,
    )


def resolve_auction_batch(
    state: AccountState,
    orders: Sequence[OrderIntent],
    quotes: Mapping[str, AuctionQuote],
    *,
    batch: AuctionBatch,
    costs: CostSchedule,
    max_positions: int,
) -> BatchResult:
    """Reserve ordered requests before resolving supplied evidence for one auction."""
    if not isinstance(state, AccountState) or not isinstance(batch, AuctionBatch) or not isinstance(costs, CostSchedule):
        raise AuctionError("state, batch, and costs must use auction contract types")
    if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes)) or not isinstance(quotes, Mapping):
        raise AuctionError("orders must be a sequence and quotes a mapping")
    if state.as_of > batch.submitted_at:
        raise AuctionError("state.as_of must not follow submission")
    if any(not isinstance(order, OrderIntent) for order in orders):
        raise AuctionError("orders must contain OrderIntent")
    for code, supplied_quote in quotes.items():
        _text(code, "quote code")
        if not isinstance(supplied_quote, AuctionQuote):
            raise AuctionError("quotes must contain AuctionQuote")
    routed = tuple(RoutedOrder(order, batch, costs) for order in orders)
    keyed_quotes = {(batch.session_id, code): quote for code, quote in quotes.items()}
    _validate_cohort(state, routed, keyed_quotes, max_positions, require_nonempty=False)
    return _resolve_auction_core(state, routed, keyed_quotes, max_positions=max_positions, cutoff=batch.auction_at)
