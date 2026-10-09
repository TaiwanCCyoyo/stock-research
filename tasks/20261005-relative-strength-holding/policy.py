"""Thin close-review advice over supplied, current-session features.

Limits are fixed after-close advice, not exchange bounds or guaranteed fills.
Execution, expiry and account state belong to the shared chronology engine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast

from research_core.auction import CostSchedule, OrderIntent, buy_quantity_for_budget
from research_core.chronology import DecisionContext, PriorCloseRequest
from research_core.decision import CloseObservation, DecisionSnapshot
from research_core.execution_prices import PriceError, round_stock_price
from research_core.signals import SignalIdentity

LOGGER = logging.getLogger(__name__)
BUY_BUDGET_CENTS = 40_000_000
MAX_POSITIONS = 5
MAX_COMPLETED_CLOSES = 252


class PolicyError(ValueError):
    """The supplied close cannot support this fixed policy's advice."""


def _time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise PolicyError("timestamp must be an aware +08:00 datetime")


@dataclass(frozen=True)
class PolicyFeature:
    exchange: str
    available_at: datetime
    source_id: str
    eligible: bool | None
    rs60: Decimal | None
    ret60: Decimal | None
    ma20: Decimal | None
    ma60: Decimal | None
    review_status: str = "observed"
    review_status_source_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.exchange, str) or self.exchange not in {"TWSE", "TPEX"}:
            raise PolicyError("feature requires TWSE or TPEX exchange")
        _time(self.available_at)
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise PolicyError("feature source_id must be nonempty")
        if not isinstance(self.review_status, str) or self.review_status not in {"observed", "confirmed_halt", "resumed_rewarming"}:
            raise PolicyError("review_status must be observed, confirmed_halt or resumed_rewarming")
        if self.review_status == "observed":
            if self.review_status_source_id is not None:
                raise PolicyError("observed review_status cannot carry review_status_source_id")
        elif not isinstance(self.review_status_source_id, str) or not self.review_status_source_id.strip():
            raise PolicyError("non-observed review_status requires a nonempty review_status_source_id")
        if self.eligible is not None and type(self.eligible) is not bool:
            raise PolicyError("eligible must be bool or None")
        for name in ("rs60", "ret60", "ma20", "ma60"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise PolicyError(f"{name} must be finite Decimal or None")
        if self.rs60 is not None and not Decimal(0) <= self.rs60 <= Decimal(1):
            raise PolicyError("rs60 must be within [0, 1]")
        for name in ("ma20", "ma60"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise PolicyError(f"{name} must be positive")


@dataclass(frozen=True)
class RequestAudit:
    code: str
    side: str
    order_id: str
    reason: str
    reserved_budget_cents: int = 0


@dataclass(frozen=True)
class CandidateSkip:
    code: str
    reason: str


@dataclass(frozen=True)
class ReviewAudit:
    as_of: datetime
    absent: bool
    requests: tuple[RequestAudit, ...]
    skipped: tuple[CandidateSkip, ...]
    error: str | None = None


class CloseReviewPolicy:
    """Stateless portfolio rule; only review audit records accumulate.

    Each successful buy reserves its entire budget for this night's planning;
    lot-rounding spare cash is deliberately not reallocated to another buy.
    Instantiate afresh for every scenario. An absence produces no advice, and
    returning reviews evaluate only the latest supplied snapshot and features.
    """

    def __init__(
        self,
        *,
        exit_ma_days: int,
        feature_provider: Callable[[datetime], Mapping[str, PolicyFeature]],
        costs: CostSchedule,
        absent_dates: frozenset[date] = frozenset(),
    ) -> None:
        if type(exit_ma_days) is not int or exit_ma_days not in (20, 60):
            raise PolicyError("exit_ma_days must be 20 or 60")
        if not callable(feature_provider) or not isinstance(costs, CostSchedule):
            raise PolicyError("feature provider and fixed CostSchedule are required")
        if not isinstance(absent_dates, frozenset) or any(not isinstance(day, date) or isinstance(day, datetime) for day in absent_dates):
            raise PolicyError("absent_dates must be a frozenset of date-only values")
        self.exit_ma_days = exit_ma_days
        self.feature_provider = feature_provider
        self.costs = costs
        self.absent_dates = absent_dates
        self._reviews: list[ReviewAudit] = []

    @property
    def reviews(self) -> tuple[ReviewAudit, ...]:
        return tuple(self._reviews)

    @property
    def profile(self) -> str:
        return f"rs-ma{self.exit_ma_days}"

    def _request(self, snapshot: DecisionSnapshot, code: str, feature: PolicyFeature, side: str, quantity: int, limit: int) -> PriorCloseRequest:
        identity = f"{self.profile}:{snapshot.as_of.isoformat()}:{code}:{side}"
        return PriorCloseRequest(
            OrderIntent(f"order:{identity}", code, side, quantity, limit, snapshot.as_of),
            feature.exchange,
            "regular_open",
            SignalIdentity(f"signal:{identity}", code, side, snapshot.as_of),
        )

    @staticmethod
    def _limit(observation: CloseObservation, side: str) -> int:
        with localcontext() as context:
            context.prec = 40
            raw = Decimal(observation.raw_close_cents) / 100
            price = raw * (Decimal("1.02") if side == "BUY" else Decimal("0.90"))
            try:
                return int(round_stock_price(price, "down" if side == "BUY" else "up") * 100)
            except PriceError as error:
                raise PolicyError(f"{side}: advice price outside supported stock grid") from error

    def __call__(self, context: DecisionContext) -> tuple[PriorCloseRequest, ...]:
        if not isinstance(context, DecisionContext) or not isinstance(context.snapshot, DecisionSnapshot):
            raise PolicyError("DecisionContext with DecisionSnapshot required")
        snapshot = context.snapshot
        _time(snapshot.as_of)
        requests: list[PriorCloseRequest] = []
        reasons: list[RequestAudit] = []
        skips: list[CandidateSkip] = []
        absent = snapshot.as_of.date() in self.absent_dates
        error_reason = None
        try:
            if context.pending:
                raise PolicyError("pending requests unsupported: requires extra_delay=0 and daily expiry")
            if absent:
                return ()
            if type(snapshot.cash_cents) is not int or snapshot.cash_cents < 0:
                raise PolicyError("cash_cents must be a nonnegative integer")
            features = self.feature_provider(snapshot.as_of)
            if not isinstance(features, Mapping):
                raise PolicyError("feature provider must return a code mapping")
            for code, supplied_feature in features.items():
                if not isinstance(code, str) or not code.strip() or not isinstance(supplied_feature, PolicyFeature):
                    raise PolicyError("feature mapping requires nonempty codes and PolicyFeature")
                if supplied_feature.available_at.date() != snapshot.as_of.date() or supplied_feature.available_at > snapshot.as_of:
                    raise PolicyError(f"{code}: feature must be current-session and available by as_of")
            for code, supplied_price in snapshot.prices.items():
                if (
                    not isinstance(supplied_price, CloseObservation)
                    or supplied_price.observed_at.date() != snapshot.as_of.date()
                    or supplied_price.observed_at > snapshot.as_of
                    or supplied_price.available_at > snapshot.as_of
                ):
                    raise PolicyError(f"{code}: price must be current-session and available by as_of")
            # Exits do not free a slot or add projected proceeds before filling.
            occupied = set(snapshot.holdings) | set(snapshot.occupied_issuer_codes)
            for code in sorted(snapshot.holdings):
                held = snapshot.holdings[code]
                if type(held.qty) is not int or held.qty <= 0 or held.qty % 1000:
                    raise PolicyError(f"{code}: unsupported residual shares; whole lots required")
                if type(held.completed_closes) is not int or held.completed_closes < 0:
                    raise PolicyError(f"{code}: completed_closes must be a nonnegative integer")
                feature, price = features.get(code), snapshot.prices.get(code)
                if feature is None or price is None:
                    raise PolicyError(f"{code}: held position requires current feature and price")
                if feature.review_status == "confirmed_halt":
                    skips.append(CandidateSkip(code, "confirmed_halt_no_advice"))
                    continue
                moving_average = getattr(feature, f"ma{self.exit_ma_days}")
                if moving_average is None:
                    if feature.review_status != "resumed_rewarming":
                        raise PolicyError(f"{code}: held position requires ma{self.exit_ma_days}")
                    request = self._request(snapshot, code, feature, "SELL", held.qty, self._limit(price, "SELL"))
                    requests.append(request)
                    reasons.append(RequestAudit(code, "SELL", request.intent.order_id, "named_interruption_unavailable_exit_average"))
                    continue
                age_exit = held.completed_closes >= MAX_COMPLETED_CLOSES
                if age_exit or price.signal_close < moving_average:
                    exit_reason = "max_completed_closes" if age_exit else f"signal_close_below_ma{self.exit_ma_days}"
                    request = self._request(snapshot, code, feature, "SELL", held.qty, self._limit(price, "SELL"))
                    requests.append(request)
                    reasons.append(RequestAudit(code, "SELL", request.intent.order_id, exit_reason))
            candidates: list[tuple[str, PolicyFeature, CloseObservation]] = []
            for code in sorted(set(features) | set(snapshot.prices)):
                feature, price = features.get(code), snapshot.prices.get(code)
                reason = None
                if code in occupied:
                    reason = "occupied_no_add"
                elif feature is None:
                    reason = "missing_feature"
                elif feature.review_status != "observed":
                    reason = f"{feature.review_status}_no_entry"
                elif price is None:
                    reason = "missing_price"
                elif feature.eligible is not True:
                    reason = "ineligible_or_unknown"
                elif feature.rs60 is None or feature.ret60 is None or feature.ma20 is None:
                    reason = "missing_entry_feature"
                elif feature.rs60 < Decimal("0.8"):
                    reason = "rs60_below_threshold"
                elif feature.ret60 <= 0:
                    reason = "ret60_not_positive"
                elif price.signal_close <= feature.ma20:
                    reason = "signal_close_not_above_ma20"
                if reason is not None:
                    skips.append(CandidateSkip(code, reason))
                elif feature is not None and price is not None:
                    candidates.append((code, feature, price))
            # Entry validation above establishes nonmissing ranks and returns.
            candidates.sort(key=lambda item: (-cast(Decimal, item[1].rs60), -cast(Decimal, item[1].ret60), item[0]))
            remaining = snapshot.cash_cents
            slots = max(0, MAX_POSITIONS - len(occupied))
            for code, feature, price in candidates:
                if not slots:
                    skips.append(CandidateSkip(code, "no_empty_slot"))
                    continue
                budget = min(BUY_BUDGET_CENTS, remaining)
                limit = self._limit(price, "BUY")
                quantity = buy_quantity_for_budget(budget_cents=budget, price_cents=limit, costs=self.costs, venue="regular_open")
                if not quantity:
                    skips.append(CandidateSkip(code, "budget_cannot_fund_cost_inclusive_lot"))
                    continue
                request = self._request(snapshot, code, feature, "BUY", quantity, limit)
                requests.append(request)
                reasons.append(RequestAudit(code, "BUY", request.intent.order_id, "entry_conditions_met", budget))
                remaining -= budget
                slots -= 1
            return tuple(requests)
        except PolicyError as error:
            error_reason = str(error)
            LOGGER.warning("Close review failed profile=ma%d date=%s reason=%s", self.exit_ma_days, snapshot.as_of.date(), error)
            raise
        finally:
            self._reviews.append(ReviewAudit(snapshot.as_of, absent, tuple(reasons), tuple(skips), error_reason))
            LOGGER.info(
                "Close review profile=ma%d date=%s absent=%s requests=%d skipped=%d",
                self.exit_ma_days,
                snapshot.as_of.date(),
                absent,
                len(requests),
                len(skips),
            )
