"""Bounded reconciliation of caller-supplied same-day residual order reports.

This adapter owns no broker state and never infers a fill, expiry, or future
report.  It is deliberately exclusive with new orders and corporate actions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from research_core.auction import (
    AccountState,
    AuctionBatch,
    AuctionOutcome,
    AuctionQuote,
    BatchResult,
    CostSchedule,
    OrderIntent,
    RoutedOrder,
    _cents_decimal,
    _costs,
    _positive_int,
    _price,
    _text,
    _time,
    resolve_auction_batch,
    resolve_auction_cohort,
)
from research_core.execution_prices import PriceLimits


class LifecycleError(ValueError):
    """Raised when supplied same-day lifecycle evidence is inconsistent."""


def _fail(message: str) -> None:
    raise LifecycleError(message)


def _clock(value: Any, name: str) -> datetime:
    try:
        return _time(value, name)
    except ValueError as exc:
        raise LifecycleError(str(exc)) from exc


def _id(value: Any, name: str) -> str:
    try:
        return _text(value, name)
    except ValueError as exc:
        raise LifecycleError(str(exc)) from exc


@dataclass(frozen=True)
class FillReport:
    report_id: str
    order_id: str
    event_at: datetime
    available_at: datetime
    sequence: int
    qty: int
    price_cents: int
    limits: PriceLimits
    source_id: str
    capacity_basis: str

    def __post_init__(self) -> None:
        _id(self.report_id, "report_id")
        _id(self.order_id, "order_id")
        _clock(self.event_at, "event_at")
        _clock(self.available_at, "available_at")
        if self.event_at > self.available_at:
            _fail("report event_at must not follow available_at")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            _fail("sequence must be a positive integer")
        try:
            _positive_int(self.qty, "qty")
            _price(self.price_cents, "price_cents")
        except ValueError as exc:
            raise LifecycleError(str(exc)) from exc
        if not isinstance(self.limits, PriceLimits):
            _fail("limits must be PriceLimits")
        _id(self.source_id, "source_id")
        _id(self.capacity_basis, "capacity_basis")
        value = _cents_decimal(self.price_cents)
        if value < self.limits.lower or (self.limits.upper is not None and value > self.limits.upper):
            _fail("fill price is outside supplied limits")


@dataclass(frozen=True)
class TerminalReport:
    report_id: str
    order_id: str
    event_at: datetime
    available_at: datetime
    sequence: int
    status: str
    cumulative_filled_qty: int
    source_id: str

    def __post_init__(self) -> None:
        _id(self.report_id, "report_id")
        _id(self.order_id, "order_id")
        _clock(self.event_at, "event_at")
        _clock(self.available_at, "available_at")
        if self.event_at > self.available_at:
            _fail("report event_at must not follow available_at")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            _fail("sequence must be a positive integer")
        if self.status not in {"FILLED", "CANCELLED", "EXPIRED", "REJECTED"}:
            _fail("unknown terminal status")
        if isinstance(self.cumulative_filled_qty, bool) or not isinstance(self.cumulative_filled_qty, int) or self.cumulative_filled_qty < 0:
            _fail("cumulative_filled_qty must be a nonnegative integer")
        _id(self.source_id, "source_id")


@dataclass(frozen=True)
class LifecycleResult:
    initial_result: BatchResult
    additional_events: tuple[Mapping[str, Any], ...]
    next_state: AccountState | None
    unresolved_order_ids: tuple[str, ...]
    evidence_basis: str = "caller_supplied_same_day_reports"
    # The reports this reconciliation actually saw and validated. A caller must read these rather
    # than the evidence it supplied: `_visible_prefix` drops reports dated after the cutoff, and
    # `_validate_reports` never sees the dropped ones -- so a dropped report has been checked
    # against nothing. Reading the raw list would let an unchecked report describe an order's fate.
    visible_reports: tuple[FillReport | TerminalReport, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "additional_events", tuple(MappingProxyType(dict(x)) for x in self.additional_events))
        object.__setattr__(self, "visible_reports", tuple(self.visible_reports))

    @property
    def continuation_allowed(self) -> bool:
        return self.initial_result.state_complete and self.next_state is not None and not self.next_state.pending_order_ids and not self.unresolved_order_ids


def _limits_match(left: PriceLimits, right: PriceLimits) -> bool:
    return left.lower == right.lower and left.upper == right.upper


def _visible_prefix(
    reports: Sequence[FillReport | TerminalReport],
    batch: AuctionBatch,
    cutoff: datetime,
) -> tuple[tuple[FillReport | TerminalReport, ...], bool]:
    """Validate packet structure, but never reconcile invisible stateful content."""
    seen_ids: set[str] = set()
    previous_event: datetime | None = None
    previous_sequence = 0
    visible: list[FillReport | TerminalReport] = []
    blocked = False
    for report in reports:
        if not isinstance(report, (FillReport, TerminalReport)):
            _fail("reports must contain FillReport or TerminalReport")
        if report.report_id in seen_ids:
            _fail("report IDs must be unique")
        seen_ids.add(report.report_id)
        if previous_event is not None and report.event_at < previous_event:
            _fail("report event_at must be nondecreasing")
        if report.sequence <= previous_sequence:
            _fail("report sequence must be globally strictly increasing")
        previous_event, previous_sequence = report.event_at, report.sequence
        if report.event_at < batch.auction_at or report.event_at.date() != batch.auction_at.date():
            _fail("report event_at is outside auction date")
        if blocked or report.event_at > cutoff:
            continue
        if report.available_at > cutoff:
            blocked = True
            continue
        visible.append(report)
    return tuple(visible), blocked


def _validate_reports(
    reports: Sequence[FillReport | TerminalReport],
    routes: Mapping[str, RoutedOrder],
    outcomes: Mapping[str, AuctionOutcome],
    batch: AuctionBatch,
    expiry: datetime,
    allowed_ids: set[str],
    initial_fills: Mapping[str, int],
    quotes: Mapping[tuple[str, str], AuctionQuote],
    *,
    reconcile_cumulative: bool,
) -> None:
    terminal_ids: set[str] = set()
    cumulative = dict(initial_fills)
    limits_by_route = {key: quote.limits for key, quote in quotes.items() if quote.limits is not None}
    for report in reports:
        if report.order_id not in routes or report.order_id not in outcomes:
            _fail("report order_id is unrecognized")
        if report.order_id not in allowed_ids:
            _fail("report must target an initially pending order")
        route = routes[report.order_id]
        order, order_batch = route.order, route.batch
        if isinstance(report, FillReport):
            if order_batch.venue == "afterhours_odd":
                _fail("afterhours_odd has no later fills")
            if report.event_at <= batch.auction_at or report.event_at > expiry:
                _fail("later fill must be after auction and before expiry")
            if order_batch.venue == "regular_open" and report.qty % 1000:
                _fail("regular fill must be a board-lot multiple")
            if order.side == "BUY" and report.price_cents > order.limit_price_cents:
                _fail("fill price violates order limit")
            if order.side == "SELL" and report.price_cents < order.limit_price_cents:
                _fail("fill price violates order limit")
            quote_key = (order_batch.session_id, order.code)
            known_limits = limits_by_route.setdefault(quote_key, report.limits)
            if not _limits_match(known_limits, report.limits):
                _fail("daily price limits are inconsistent")
            if report.order_id in terminal_ids:
                _fail("fill follows terminal")
            if reconcile_cumulative:
                cumulative[report.order_id] = cumulative.get(report.order_id, 0) + report.qty
                if cumulative[report.order_id] > order.qty:
                    _fail("fill exceeds order quantity")
                if order_batch.venue != "regular_open" and cumulative[report.order_id] > 999:
                    _fail("odd-lot cumulative fill exceeds 999")
            continue
        if report.order_id in terminal_ids:
            _fail("duplicate terminal")
        terminal_ids.add(report.order_id)
        if report.status == "EXPIRED" and report.event_at != expiry:
            _fail("EXPIRED must occur exactly at expiry")
        if report.status != "EXPIRED" and report.event_at > expiry:
            _fail("terminal follows expiry")
        if report.status == "FILLED" and report.cumulative_filled_qty != order.qty:
            _fail("FILLED terminal must have requested cumulative quantity")
        if report.status != "FILLED" and report.cumulative_filled_qty >= order.qty:
            _fail("non-FILLED terminal must leave a residual")
        if report.status == "REJECTED" and report.cumulative_filled_qty != 0:
            _fail("REJECTED must have zero fills")
        if reconcile_cumulative and report.cumulative_filled_qty != cumulative.get(report.order_id, 0):
            _fail("terminal cumulative fill does not match reports")


def _reconcile_after_initial(
    initial: BatchResult,
    routes: Mapping[str, RoutedOrder],
    quotes: Mapping[tuple[str, str], AuctionQuote],
    *,
    batch: AuctionBatch,
    expires_at: datetime,
    as_of: datetime,
    reports: Sequence[FillReport | TerminalReport],
) -> LifecycleResult:
    """Apply visible reports to one already-resolved common-auction result."""
    expiry, cutoff = _clock(expires_at, "expires_at"), _clock(as_of, "as_of")
    if not isinstance(reports, Sequence) or isinstance(reports, (str, bytes)):
        _fail("reports must be a sequence")
    if batch.auction_at > cutoff or expiry < batch.auction_at or expiry.date() != batch.auction_at.date() or cutoff.date() != batch.auction_at.date():
        _fail("auction, expiry, and as_of must be ordered on one date")

    outcome_by_id = {outcome.order_id: outcome for outcome in initial.outcomes}
    incomplete_ids = {
        outcome.order_id
        for outcome in initial.outcomes
        if outcome.disposition in {"unavailable", "partial", "unfilled"} and outcome.reason != "order_limit_outside_bounds"
    }
    pending = tuple(initial.next_state.pending_order_ids) if initial.next_state is not None else ()
    initial_fills = {outcome.order_id: outcome.filled_qty for outcome in initial.outcomes}
    visible_reports, hidden_current = _visible_prefix(reports, batch, cutoff)
    _validate_reports(
        visible_reports,
        routes,
        outcome_by_id,
        batch,
        expiry,
        set(pending) if initial.state_complete else incomplete_ids,
        initial_fills,
        quotes,
        reconcile_cumulative=initial.state_complete,
    )
    if not initial.state_complete or initial.next_state is None:
        return LifecycleResult(
            initial,
            (),
            None,
            tuple(outcome.order_id for outcome in initial.outcomes if outcome.order_id in incomplete_ids),
            visible_reports=visible_reports,
        )

    cumulative = {order_id: initial_fills[order_id] for order_id in pending}
    notional = {order_id: initial_fills[order_id] * (outcome_by_id[order_id].price_cents or 0) for order_id in pending}
    charged = {
        order_id: (outcome_by_id[order_id].commission_cents, outcome_by_id[order_id].tax_cents, outcome_by_id[order_id].penalty_cents)
        if initial_fills[order_id]
        else (0, 0, 0)
        for order_id in pending
    }
    terminals: set[str] = set()
    events: list[Mapping[str, Any]] = []
    cash, positions = initial.next_state.cash_cents, dict(initial.next_state.positions)
    for report in visible_reports:
        route = routes[report.order_id]
        order, outcome, costs = route.order, outcome_by_id[report.order_id], route.costs
        if isinstance(report, TerminalReport):
            terminals.add(report.order_id)
            continue
        new_qty = cumulative[order.order_id] + report.qty
        new_notional = notional[order.order_id] + report.qty * report.price_cents
        new_costs = _costs(new_notional, order.side, costs)
        delta = tuple(new - old for new, old in zip(new_costs, charged[order.order_id], strict=True))
        if min(delta) < 0:
            _fail("cumulative cost delta cannot be negative")
        total_cost = sum(delta)
        if order.side == "BUY":
            debit = report.qty * report.price_cents + total_cost
            if new_notional + sum(new_costs) > outcome.reserved_cash_cents:
                _fail("buy fill exceeds original cash reservation")
            if cash - debit < 0:
                _fail("buy fill would make cash negative")
            cash -= debit
            positions[order.code] = positions.get(order.code, 0) + report.qty
            total = -debit
        else:
            net = report.qty * report.price_cents - total_cost
            if sum(new_costs) - new_notional > outcome.reserved_cash_cents:
                _fail("sell fill exceeds original cash reservation")
            if positions.get(order.code, 0) < report.qty:
                _fail("sell fill exceeds shares")
            if cash + net < 0:
                _fail("sell fill would make cash negative")
            cash += net
            positions[order.code] -= report.qty
            if not positions[order.code]:
                del positions[order.code]
            total = net
        cumulative[order.order_id], notional[order.order_id], charged[order.order_id] = new_qty, new_notional, new_costs
        event: dict[str, Any] = {
            "action": order.side,
            "code": order.code,
            "date": report.event_at.isoformat(),
            "qty": report.qty,
            "total": total / 100,
            "order_id": order.order_id,
            "session_id": route.batch.session_id,
            "venue": route.batch.venue,
            "source_id": report.source_id,
            "capacity_basis": report.capacity_basis,
            "report_id": report.report_id,
            "price": report.price_cents / 100,
            "price_cents": report.price_cents,
            "gross_cents": report.qty * report.price_cents,
            "total_cents": total,
            "commission_cents": delta[0],
            "tax_cents": delta[1],
            "penalty_cents": delta[2],
        }
        if order.side == "SELL":
            event.update({"gross_proceeds": report.qty * report.price_cents / 100, "cost_total": total_cost / 100})
        events.append(MappingProxyType(event))
    unresolved = tuple(order_id for order_id in pending if order_id not in terminals)
    next_state = (
        None
        if unresolved or hidden_current
        else AccountState(
            cash,
            positions,
            cutoff,
            "trade_date_cash" if events else initial.next_state.cash_basis,
            reserved_position_codes=initial.next_state.reserved_position_codes,
        )
    )
    return LifecycleResult(initial, tuple(events), next_state, unresolved, visible_reports=visible_reports)


def reconcile_order_lifecycle(
    state: AccountState,
    orders: Sequence[OrderIntent],
    quotes: Mapping[str, AuctionQuote],
    *,
    batch: AuctionBatch,
    costs: CostSchedule,
    max_positions: int,
    expires_at: datetime,
    as_of: datetime,
    reports: Sequence[FillReport | TerminalReport],
) -> LifecycleResult:
    """Resolve one auction then apply only visible, caller-supplied residual reports."""
    try:
        initial = resolve_auction_batch(state, orders, quotes, batch=batch, costs=costs, max_positions=max_positions)
        routes = {order.order_id: RoutedOrder(order, batch, costs) for order in orders}
        keyed_quotes = {(batch.session_id, code): quote for code, quote in quotes.items()}
        return _reconcile_after_initial(
            initial,
            routes,
            keyed_quotes,
            batch=batch,
            expires_at=expires_at,
            as_of=as_of,
            reports=reports,
        )
    except ValueError as exc:
        raise LifecycleError(str(exc)) from exc


def reconcile_cohort_lifecycle(
    state: AccountState,
    routed_orders: Sequence[RoutedOrder],
    quotes: Mapping[tuple[str, str], AuctionQuote],
    *,
    max_positions: int,
    expires_at: datetime,
    as_of: datetime,
    reports: Sequence[FillReport | TerminalReport],
) -> LifecycleResult:
    """Resolve one simultaneous cohort once, then reconcile its visible residual reports."""
    try:
        initial = resolve_auction_cohort(state, routed_orders, quotes, max_positions=max_positions)
        batch = routed_orders[0].batch
        routes = {routed.order.order_id: routed for routed in routed_orders}
        return _reconcile_after_initial(
            initial,
            routes,
            quotes,
            batch=batch,
            expires_at=expires_at,
            as_of=as_of,
            reports=reports,
        )
    except ValueError as exc:
        raise LifecycleError(str(exc)) from exc
