"""As-of decision inputs reconstructed from executed events, never order intents.

Calendar/evidence completeness is supplied by the caller, not certified here.
This bridge has no signal rule, market loader, order lifecycle or acceptance gate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from research_core.auction import AccountState
from research_core.execution_prices import PriceError, round_stock_price
from research_core.ledger import mark_share_claims_cents, replay_ledger


class DecisionError(ValueError):
    """The supplied prefix cannot establish complete decision-time inputs."""


def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise DecisionError(f"{name} must be an aware +08:00 datetime")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DecisionError(f"{name} must be a nonempty string")
    return value


def _cents(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DecisionError(f"{name} must be finite numeric TWD")
    amount = Fraction(str(value)) * 100
    if amount.denominator != 1:
        raise DecisionError(f"{name} must be an integral number of cents")
    return amount.numerator


@dataclass(frozen=True)
class CloseObservation:
    raw_close_cents: int
    signal_close: Decimal
    observed_at: datetime
    available_at: datetime
    source_id: str

    def __post_init__(self) -> None:
        cents = self.raw_close_cents
        if isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
            raise DecisionError("raw_close_cents must be a positive integer")
        price = Decimal(f"{cents // 100}.{cents % 100:02d}")
        try:
            if round_stock_price(price, "down") != price:
                raise DecisionError("raw price must be on the stock grid")
        except PriceError as error:
            raise DecisionError("raw price is outside the supported domain") from error
        if not isinstance(self.signal_close, Decimal) or not self.signal_close.is_finite() or self.signal_close <= 0:
            raise DecisionError("signal_close must be a finite positive Decimal")
        if _time(self.observed_at, "observed_at") > _time(self.available_at, "available_at"):
            raise DecisionError("observation cannot be available before it is observed")
        _text(self.source_id, "source_id")


@dataclass(frozen=True)
class HeldAttempt:
    # Prefix-local entry event index; not an identity across counterfactual runs.
    attempt_id: int
    qty: int
    entry_at: datetime
    completed_closes: int


@dataclass(frozen=True)
class DecisionSnapshot:
    # receivable_cents is all nonspendable cash claims; principal is also broken out.
    as_of: datetime
    calendar_id: str
    event_count: int
    cash_cents: int
    receivable_cents: int
    equity_cents: int
    cash_basis: str
    execution_checkpoint_id: str
    evidence_basis: str
    holdings: Mapping[str, HeldAttempt]
    prices: Mapping[str, CloseObservation]
    capital_return_receivable_cents: int = 0
    occupied_issuer_codes: frozenset[str] = frozenset()
    share_claim_value_cents: int = 0


@dataclass(frozen=True)
class ExecutionAccountSnapshot:
    """Pre-auction account facts; receivable_cents includes dividends and principal."""

    account: AccountState
    event_count: int
    receivable_cents: int
    calendar_id: str
    execution_checkpoint_id: str
    evidence_basis: str
    capital_return_receivable_cents: int = 0


def _exact_cash_prefix(
    *,
    initial_cash_cents: int,
    events: Sequence[Mapping[str, Any]],
    start: datetime,
    end: datetime,
    fill_dates: set[date],
) -> tuple[list[dict[str, Any]], int, list[datetime]]:
    """Validate the caller's ordered prefix and preserve exact-cent cash facts."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise DecisionError("events must be a complete sequence")
    prefix: list[dict[str, Any]] = []
    event_times: list[datetime] = []
    cash = initial_cash_cents
    previous = start
    for event in events:
        if not isinstance(event, Mapping):
            raise DecisionError("each event must be a mapping")
        try:
            when = _time(datetime.fromisoformat(str(event.get("date"))), "event date")
        except ValueError as error:
            raise DecisionError("event date must be an ISO +08:00 timestamp") from error
        if when < previous or when > end:
            raise DecisionError("events must be ordered inside history_start..as_of")
        action = _text(event.get("action"), "action").upper()
        if action in {"BUY", "SELL"} and when.date() not in fill_dates:
            raise DecisionError("fill date is absent from supplied session calendar")
        if action == "DIVIDEND" and "entitlement_id" not in event:
            raise DecisionError("decision replay requires explicit dividend entitlements")
        cash += _cents(event.get("total"), "event total")
        if cash < 0:
            raise DecisionError("insufficient exact cash in event prefix")
        for field in ("gross_proceeds", "cost_total"):
            if field in event:
                _cents(event[field], field)
        if action in {"DIVIDEND_ENTITLEMENT", "CAPITAL_RETURN_ENTITLEMENT"}:
            _cents(event.get("amount"), "entitlement amount")
        prefix.append(dict(event))
        event_times.append(when)
        previous = when
    return prefix, cash, event_times


def build_decision_snapshot(
    *,
    initial_cash_cents: int,
    history_start: datetime,
    as_of: datetime,
    events: Sequence[Mapping[str, Any]],
    session_closes: Sequence[datetime],
    calendar_id: str,
    prices: Mapping[str, CloseObservation],
    execution_complete: bool,
    execution_checkpoint_id: str,
    cash_basis: str,
    unresolved_order_ids: Sequence[str],
    max_positions: int,
) -> DecisionSnapshot:
    """Replay a complete prefix and expose immutable, separately named prices.

    ``completed_closes`` counts supplied session closes at or after actual entry,
    including the entry day's close when entry precedes it. After-hours entry is
    age zero at that day's decision. This is not a choice of minimum-hold policy.
    Missing calendars/marks/executions cannot be replaced with an optimistic book.
    The caller must establish that supplied events, calendar and status are complete.
    """
    start, end = _time(history_start, "history_start"), _time(as_of, "as_of")
    if start >= end:
        raise DecisionError("history_start must precede as_of")
    _text(calendar_id, "calendar_id")
    _text(execution_checkpoint_id, "execution_checkpoint_id")
    if cash_basis != "trade_date_cash":
        raise DecisionError("this replay supports trade_date_cash only, not certified buying power")
    if isinstance(initial_cash_cents, bool) or not isinstance(initial_cash_cents, int) or initial_cash_cents <= 0:
        raise DecisionError("initial_cash_cents must be a positive integer")
    if execution_complete is not True:
        raise DecisionError("execution evidence must be complete")
    if not isinstance(unresolved_order_ids, Sequence) or isinstance(unresolved_order_ids, (str, bytes)):
        raise DecisionError("unresolved_order_ids must be a sequence")
    if unresolved_order_ids:
        raise DecisionError("unresolved orders require lifecycle reconciliation")
    if not isinstance(session_closes, Sequence) or not session_closes:
        raise DecisionError("session_closes must be a nonempty sequence")
    closes = tuple(_time(value, "session close") for value in session_closes)
    if any(value <= start or value > end for value in closes):
        raise DecisionError("session closes must lie within history_start..as_of")
    if any(left.date() >= right.date() for left, right in zip(closes, closes[1:])):
        raise DecisionError("session closes require strictly increasing unique dates")
    if closes[-1].date() != end.date():
        raise DecisionError("as_of must follow the latest supplied session close on its date")
    session_dates = {close.date() for close in closes}
    prefix, cash, event_times = _exact_cash_prefix(
        initial_cash_cents=initial_cash_cents,
        events=events,
        start=start,
        end=end,
        fill_dates=session_dates,
    )
    if not isinstance(prices, Mapping):
        raise DecisionError("prices must be a mapping")
    observations: dict[str, CloseObservation] = {}
    for code, observation in prices.items():
        _text(code, "price code")
        if not isinstance(observation, CloseObservation):
            raise DecisionError("prices must contain CloseObservation")
        if observation.observed_at != closes[-1] or observation.available_at > end:
            raise DecisionError("prices must be current-session observations available by as_of")
        observations[code] = observation
    ledger = replay_ledger(
        initial_cash_cents / 100,
        prefix,
        marks={code: observation.raw_close_cents / 100 for code, observation in observations.items()},
        max_positions=max_positions,
    )
    holdings = {
        attempt["code"]: HeldAttempt(
            attempt_id=attempt["id"],
            qty=ledger["positions"][attempt["code"]],
            entry_at=event_times[attempt["entry_event_index"]],
            completed_closes=sum(close >= event_times[attempt["entry_event_index"]] for close in closes),
        )
        for attempt in ledger["open_attempts"]
        if attempt["code"] in ledger["positions"]
    }
    capital_receivable = sum(_cents(item["amount"], "unpaid capital return") for item in ledger["capital_return_entitlements"] if not item["paid"])
    receivable = capital_receivable + sum(_cents(item["amount"], "unpaid dividend") for item in ledger["dividend_entitlements"] if not item["paid"])
    claim_value = mark_share_claims_cents(ledger, {code: observation.raw_close_cents / 100 for code, observation in observations.items()})
    equity = cash + receivable + claim_value + sum(qty * observations[code].raw_close_cents for code, qty in ledger["positions"].items())
    if not math.isclose(cash / 100, ledger["cash"], rel_tol=0, abs_tol=1e-8) or not math.isclose(
        equity / 100, ledger["marked_equity"], rel_tol=0, abs_tol=1e-8
    ):
        raise DecisionError("exact-cent state does not reconcile with ledger replay")
    return DecisionSnapshot(
        as_of=end,
        calendar_id=calendar_id,
        event_count=len(prefix),
        cash_cents=cash,
        receivable_cents=receivable,
        equity_cents=equity,
        cash_basis=cash_basis,
        execution_checkpoint_id=execution_checkpoint_id,
        evidence_basis="caller_asserted_prefix_and_calendar",
        holdings=MappingProxyType(holdings),
        prices=MappingProxyType(observations),
        capital_return_receivable_cents=capital_receivable,
        occupied_issuer_codes=frozenset(ledger["positions"]) | frozenset(ledger["outstanding_share_codes"]),
        share_claim_value_cents=claim_value,
    )


def build_execution_account_snapshot(
    *,
    initial_cash_cents: int,
    history_start: datetime,
    as_of: datetime,
    events: Sequence[Mapping[str, Any]],
    trading_dates: Sequence[date],
    calendar_id: str,
    execution_complete: bool,
    execution_checkpoint_id: str,
    cash_basis: str,
    unresolved_order_ids: Sequence[str],
    max_positions: int,
) -> ExecutionAccountSnapshot:
    """Replay a complete actual prefix into an immutable pre-auction account state.

    This deliberately supplies no marks: it describes trade-date cash, positions,
    and receivables before an auction, not buying power or a recommendation.
    """
    if isinstance(max_positions, bool) or not isinstance(max_positions, int) or max_positions <= 0:
        raise DecisionError("max_positions must be a positive integer")
    start, end = _time(history_start, "history_start"), _time(as_of, "as_of")
    if start >= end:
        raise DecisionError("history_start must precede as_of")
    _text(calendar_id, "calendar_id")
    _text(execution_checkpoint_id, "execution_checkpoint_id")
    if cash_basis != "trade_date_cash":
        raise DecisionError("this replay supports trade_date_cash only, not certified buying power")
    if isinstance(initial_cash_cents, bool) or not isinstance(initial_cash_cents, int) or initial_cash_cents <= 0:
        raise DecisionError("initial_cash_cents must be a positive integer")
    if execution_complete is not True:
        raise DecisionError("execution evidence must be complete")
    if not isinstance(unresolved_order_ids, Sequence) or isinstance(unresolved_order_ids, (str, bytes)):
        raise DecisionError("unresolved_order_ids must be a sequence")
    if unresolved_order_ids:
        raise DecisionError("unresolved orders require lifecycle reconciliation")
    if not isinstance(trading_dates, Sequence) or isinstance(trading_dates, (str, bytes)) or not trading_dates:
        raise DecisionError("trading_dates must be a nonempty sequence")
    dates = tuple(trading_dates)
    if any(not isinstance(value, date) or isinstance(value, datetime) for value in dates):
        raise DecisionError("trading_dates must contain datetime.date values, not datetimes")
    if any(value < start.date() or value > end.date() for value in dates):
        raise DecisionError("trading_dates must lie within history_start..as_of")
    if any(left >= right for left, right in zip(dates, dates[1:])):
        raise DecisionError("trading_dates require strictly increasing unique dates")
    if dates[-1] != end.date():
        raise DecisionError("as_of date must be present in supplied trading_dates")
    prefix, cash, _event_times = _exact_cash_prefix(
        initial_cash_cents=initial_cash_cents,
        events=events,
        start=start,
        end=end,
        fill_dates=set(dates),
    )
    ledger = replay_ledger(initial_cash_cents / 100, prefix, max_positions=max_positions)
    capital_receivable = sum(_cents(item["amount"], "unpaid capital return") for item in ledger["capital_return_entitlements"] if not item["paid"])
    receivable = capital_receivable + sum(_cents(item["amount"], "unpaid dividend") for item in ledger["dividend_entitlements"] if not item["paid"])
    if not math.isclose(cash / 100, ledger["cash"], rel_tol=0, abs_tol=1e-8):
        raise DecisionError("exact-cent state does not reconcile with ledger replay")
    return ExecutionAccountSnapshot(
        account=AccountState(cash, dict(ledger["positions"]), end, "trade_date_cash", reserved_position_codes=frozenset(ledger["outstanding_share_codes"])),
        event_count=len(prefix),
        receivable_cents=receivable,
        calendar_id=calendar_id,
        execution_checkpoint_id=execution_checkpoint_id,
        evidence_basis="caller_asserted_prefix_and_calendar",
        capital_return_receivable_cents=capital_receivable,
    )
