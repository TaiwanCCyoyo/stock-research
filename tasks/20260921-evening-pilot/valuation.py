"""Confirmed one-session halts: accounting marks, never replacement market bars."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from research_core.chronology import DecisionContext
from research_core.decision import CloseObservation

DAY, CODE = date(2019, 3, 13), "2375"
TAIPEI = timezone(timedelta(hours=8))
POLICY = "modeled:last-observed-close-on-confirmed-single-session-halt-v1"
CAPITAL_POLICY = "modeled:last-old-share-value-during-confirmed-capital-suspension-v1"
HALT_SOURCE = "TWSE:TWTAWU:2375:2019-03-13"
APPROVED_HALTS = {
    (DAY, CODE): (date(2019, 3, 12), date(2019, 3, 14), "智寶"),
    (date(2019, 7, 30), "5469"): (date(2019, 7, 29), date(2019, 7, 31), "瀚宇博"),
    (date(2022, 2, 22), "1760"): (date(2022, 2, 21), date(2022, 2, 23), "寶齡富錦"),
}


@dataclass(frozen=True)
class ModeledHaltMark(CloseObservation):
    """CloseObservation-shaped valuation input for the existing account interface.

    In this explicitly modeled subtype, inherited ``observed_at`` is the time
    the accounting mark is calculated, NOT a time of a traded price. The actual
    price's timestamp is retained in ``reference_observed_at``. No market table
    is filled and the decision bridge must strip this type from usable bars.
    """

    reference_observed_at: datetime
    halt_evidence_id: str
    kind: str = "modeled_valuation_only"

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            self.reference_observed_at.tzinfo is None
            or self.reference_observed_at >= self.observed_at
            or not self.halt_evidence_id
            or not self.source_id.startswith((POLICY + "|", CAPITAL_POLICY + "|"))
            or self.kind != "modeled_valuation_only"
        ):
            raise ValueError("modeled halt mark requires an earlier observed source and explicit basis")


def confirmed_halts(payload: Mapping[str, Any]) -> dict[tuple[date, str], str]:
    """Validate one of the explicit located records; never infer gaps as halts."""
    fields = ["編號", "證券代號", "證券名稱", "暫停交易日期", "暫停交易時間", "恢復交易日期", "恢復交易時間"]
    params = payload.get("params", {})
    if not isinstance(params, Mapping):
        raise ValueError("halt query identity differs")
    for (day, code), (_prior_day, resume_day, name) in APPROVED_HALTS.items():
        if params.get("startDate") != day.strftime("%Y%m%d") or params.get("stockNo") != code:
            continue
        roc_day = f"{day.year - 1911:03}/{day.month:02}/{day.day:02}"
        roc_resume = f"{resume_day.year - 1911:03}/{resume_day.month:02}/{resume_day.day:02}"
        expected = [[1, code, name, roc_day, "8:00", roc_resume, "8:00"]]
        if payload.get("stat") != "OK" or payload.get("fields") != fields or payload.get("data") != expected:
            raise ValueError("confirmed one-session halt evidence changed or is ambiguous")
        if params.get("endDate") != day.strftime("%Y%m%d"):
            raise ValueError("halt query identity differs")
        return {(day, code): f"TWSE:TWTAWU:{code}:{day.isoformat()}"}
    raise ValueError("halt query is not on the prospectively approved record list")


def halt_mark(*, prior: CloseObservation, day: date, code: str, source_id: str) -> ModeledHaltMark:
    approved = APPROVED_HALTS.get((day, code))
    if (
        approved is None
        or source_id != f"TWSE:TWTAWU:{code}:{day.isoformat()}"
        or isinstance(prior, ModeledHaltMark)
        or prior.observed_at.date() != approved[0]
    ):
        raise ValueError("halt valuation is limited to the confirmed record and its immediately preceding close")
    return ModeledHaltMark(
        prior.raw_close_cents,
        Decimal(prior.raw_close_cents) / 100,
        datetime.combine(day, time(13, 30), TAIPEI),
        datetime.combine(day, time(18), TAIPEI),
        f"{POLICY}|{source_id}|reference:{prior.source_id}",
        prior.observed_at,
        source_id,
    )


def capital_halt_mark(*, prior: CloseObservation, day: date, source_id: str) -> ModeledHaltMark:
    """Bounded 2316 old-share units until the separately modeled economic exchange."""
    if not date(2019, 9, 26) <= day < date(2019, 10, 7) or prior.observed_at.date() != date(2019, 9, 25) or isinstance(prior, ModeledHaltMark) or not source_id:
        raise ValueError("capital suspension mark requires the exact confirmed interval and old observed price")
    return ModeledHaltMark(
        prior.raw_close_cents,
        Decimal(prior.raw_close_cents) / 100,
        datetime.combine(day, time(13, 30), TAIPEI),
        datetime.combine(day, time(18), TAIPEI),
        f"{CAPITAL_POLICY}|{source_id}|reference:{prior.source_id}",
        prior.observed_at,
        source_id,
    )


def observed_only_factory(factory: Callable[[], Any]) -> Callable[[], Any]:
    """Keep full marked equity/holdings, but expose no modeled mark as a signal bar."""

    def make() -> Any:
        rule = factory()

        def decide(context: DecisionContext) -> Any:
            prices = {code: value for code, value in context.snapshot.prices.items() if not isinstance(value, ModeledHaltMark)}
            snapshot = replace(context.snapshot, prices=MappingProxyType(prices))
            return rule(replace(context, snapshot=snapshot))

        return decide

    return make
