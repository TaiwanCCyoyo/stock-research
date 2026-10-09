"""One validated 2316 capital-refund event; not a general corporate-action engine."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any

from research_core.chronology import CorporateEvidence

TAIPEI = timezone(timedelta(hours=8))
_DETAIL_FIELDS = (
    "股票代號：",
    "股票名稱：",
    "停止買賣日期：",
    "每壹仟股換發新股票：",
    "每股退還股款：",
    "原股每股配發現金股利：",
    "減資並(有償)現金增資：",
    "每股認購金額：",
    "a. 公開承銷：",
    "b. 員工認購：",
    "c. 原股東認購：",
    "按股東持股比例每千股認購：",
)
_DETAIL_ROW = ("2316  ", "楠梓電", "108/09/26", "900.00000000 股", "1.000000 元/股", "0 元/股", "0 股", "0 元/股", "0 股", "0 股", "0 股", "0 股")


class CapitalEventError(ValueError):
    """The one observed capital-refund source pair did not match its declared contract."""


@dataclass(frozen=True)
class FixedCapitalEvent:
    code: str
    stopped_on: date
    resumed_on: date
    ratio: Fraction
    refund_per_share: Decimal
    source_id: str

    @property
    def source_identity(self) -> str:
        return self.source_id


def _taiwan_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        year, month, day = value.replace("年", "/").replace("月", "/").replace("日", "").split("/")
        return date(int(year) + 1911, int(month), int(day))
    except ValueError:
        return None


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if payload.get("stat") != "OK" or not isinstance(payload.get("data"), list):
        raise CapitalEventError("official annual payload must be stat OK with data")
    data = payload["data"]
    if data and isinstance(data[0], Mapping):
        return list(data)
    fields = payload.get("fields")
    if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
        raise CapitalEventError("annual row payload requires named fields")
    if any(not isinstance(row, list) or len(row) != len(fields) for row in data):
        raise CapitalEventError("annual rows do not match named fields")
    return [dict(zip(fields, row, strict=True)) for row in data]


def bind_capital_event(detail_payload: Mapping[str, Any], annual_payload: Mapping[str, Any]) -> FixedCapitalEvent:
    """Validate exactly the frozen TWSE detail and annual rows for 2316, or fail closed."""
    if detail_payload.get("stat") != "OK" or tuple(detail_payload.get("fields", ())) != _DETAIL_FIELDS or detail_payload.get("data") != [list(_DETAIL_ROW)]:
        raise CapitalEventError("capital-refund detail does not match the exact 2316 observation")
    rows = _rows(annual_payload)
    matches = [
        (index, row)
        for index, row in enumerate(rows)
        if str(row.get("股票代號", "")).strip() == "2316" and _taiwan_date(row.get("恢復買賣日期")) == date(2019, 10, 7)
    ]
    if len(matches) != 1 or matches[0][0] != 12:
        raise CapitalEventError("expected exactly one annual 2316 resume row")
    annual = matches[0][1]
    if annual.get("減資原因") != "退還股款" or annual.get("詳細資料") != "2316  ,20190925":
        raise CapitalEventError("annual 2316 row has a different capital-event identity")
    return FixedCapitalEvent(
        "2316", date(2019, 9, 26), date(2019, 10, 7), Fraction(9, 10), Decimal("1"), "frozen-inputs:twtavu-detail-2316-20190925|twtauu-row-12"
    )


validate_fixed_capital_event = bind_capital_event


def build_capital_composer(
    cash_provider: Callable[..., CorporateEvidence], event: FixedCapitalEvent, coverage_begin: datetime, coverage_end: datetime
) -> Callable[..., CorporateEvidence]:
    """Compose this refund entitlement before its 07:01 share reduction, then ordinary cash."""
    if event.code != "2316" or event.ratio != Fraction(9, 10) or event.refund_per_share != Decimal("1"):
        raise CapitalEventError("only the validated 2316 fixed capital event is supported")
    capital = importlib.import_module("capital_returns")
    providers = importlib.import_module("prototype.providers")
    entitlement_at = datetime.combine(event.resumed_on, time(7), TAIPEI)
    split_at = datetime.combine(event.resumed_on, time(7, 1), TAIPEI)
    payment_at = entitlement_at + timedelta(days=45)
    term = capital.CapitalReturn(
        "2316-capital-refund-2019",
        event.code,
        event.refund_per_share,
        entitlement_at,
        payment_at,
        entitlement_at,
        event.source_identity,
        "modeled-2316-refund-45-calendar-days",
        "assumed",
    )
    capital_provider = capital.build_capital_return_provider(
        (term,),
        (capital.CashCoverage(coverage_begin, coverage_end, True, "fixed-2316-capital-domain"),),
        initial_cash_cents=200_000_000,
        max_positions=5,
        rounding_policy="account-cent-half-up",
    )
    split_provider = providers.build_corporate_provider(
        (providers.CorporateFact("SPLIT", event.code, split_at, event.source_identity, ratio=event.ratio, time_basis="assumed", available_at=split_at),),
        (providers.CorporateCoverage(coverage_begin, coverage_end, True, "fixed-2316-split-domain"),),
        initial_cash_cents=200_000_000,
        max_positions=5,
    )

    def moment(item: Mapping[str, Any]) -> datetime:
        return datetime.fromisoformat(str(item["date"]))

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        cuts = [since] + ([split_at] if since < split_at < until else []) + [until]
        emitted: list[Mapping[str, Any]] = []
        notices: list[Mapping[str, Any]] = []
        backdated: list[Mapping[str, Any]] = []
        for start, end in zip(cuts[:-1], cuts[1:], strict=True):
            full = [*prefix, *emitted]
            results = (cash_provider(start, end, full), capital_provider(start, end, full))
            if not all(result.complete for result in results):
                return CorporateEvidence("fixed-2316-capital-incomplete", (), False)
            for result in results:
                emitted.extend(result.events)
                notices.extend(result.share_count_notices)
                backdated.extend(result.backdated)
            split = split_provider(start, end, [*prefix, *emitted])
            if not split.complete:
                return CorporateEvidence("fixed-2316-split-incomplete", (), False)
            emitted.extend(split.events)
            notices.extend(split.share_count_notices)
            backdated.extend(split.backdated)
        return CorporateEvidence(
            "fixed-2316-capital-composer", tuple(sorted(emitted, key=moment)), True, tuple(sorted(notices, key=moment)), tuple(sorted(backdated, key=moment))
        )

    return provide


__all__ = ["CapitalEventError", "FixedCapitalEvent", "bind_capital_event", "build_capital_composer", "validate_fixed_capital_event"]
