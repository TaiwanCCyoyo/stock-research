"""Bounded MOPS mixed cash/share distributions; no generic rights inference."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, TypedDict

from event_limits import EventLimits

from research_core.chronology import CorporateEvidence
from research_core.execution_prices import PriceLimits

TAIPEI = timezone(timedelta(hours=8))


class _MixedSpec(TypedDict):
    code: str
    effective_on: date
    event_id: str
    bonus: Fraction
    cash: Decimal
    literal_date: str
    detail: str
    distribution: tuple[str, str, str, str]
    ex_date: str
    fraction_literal: str
    settlement_minute: int | None
    fractional_net: Decimal | None
    policy: str


# pragma: allowlist secret
_SPECS: dict[str, _MixedSpec] = {
    "76419516d342de7e49ee3bbb74eb4c1ea1f235203f010c2a6b1de40240cdaab7": {
        "code": "3588",
        "effective_on": date(2021, 9, 2),
        "event_id": "annual:twt49u:3588:2021-09-02:734",
        "bonus": Fraction(4996046789, 50000000000),
        "cash": Decimal("0.59952561"),
        "literal_date": "110年09月02日",
        "detail": "3588,20210902",
        "distribution": (
            "每壹仟股無償配發盈餘轉增資49.96046789股",
            "每壹仟股無償配發法定盈餘公積、資本公積轉增資49.96046789股",
            "每壹仟股以每股新台幣0.00元認購 普通股 0.00000000股",
            "每壹股配發現金(股利)0.59952561元",
        ),
        "ex_date": "除權/除息交易日：110年9月2日",
        "fraction_literal": "未滿一股之畸零股款，將做為處理帳簿劃撥之費用",
        "settlement_minute": 3,
        "fractional_net": Decimal("0"),
        "policy": "modeled-3588-book-entry-delivery-plus45-calendar-days-zero-net-fraction",
    },
    "e0f79f7e26d306d586c6c5cf65f3e3e8c917c5d19b7edc3a86cc09f4e43841aa": {
        "code": "3617",
        "effective_on": date(2023, 8, 16),
        "event_id": "annual:twt49u:3617:2023-08-16:823",
        "bonus": Fraction(1, 20),
        "cash": Decimal("5"),
        "literal_date": "112年08月16日",
        "detail": "3617,20230816",
        "distribution": (
            "每壹仟股無償配發盈餘轉增資50.00000000股",
            "每壹仟股無償配發法定盈餘公積、資本公積轉增資0.00000000股",
            "每壹仟股以每股新台幣0.00元認購 普通股 0.00000000股",
            "每壹股配發現金(股利)5.00000000元",
        ),
        "ex_date": "除權/除息交易日：112年8月16日",
        "fraction_literal": "按面額折付現金計算至元為止",
        "settlement_minute": None,
        "fractional_net": None,
        "policy": "modeled-3617-delivery-plus45-calendar-days-unknown-fraction-settlement",
    },
}


class MixedRightsError(ValueError):
    pass


@dataclass(frozen=True)
class FixedMixedEvent:
    code: str
    effective_on: date
    bonus_per_share: Fraction
    cash_per_share: Decimal
    source_id: str
    limits: EventLimits


def _bound_mops_payload(raw_payload: bytes) -> _MixedSpec:
    # Public integrity allowlist for the preserved, read-only MOPS response.
    digest = hashlib.sha256(raw_payload).hexdigest() if isinstance(raw_payload, bytes) else ""
    spec = _SPECS.get(digest)
    if spec is None:
        raise MixedRightsError("MOPS response does not match an approved raw checksum")
    try:
        payload = json.loads(raw_payload)
        result = payload["result"]
        titles = result["titles"]
        row = result["data"][0]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise MixedRightsError(f"{spec['code']} MOPS response has an unsupported schema") from None
    if (
        payload.get("code") != 200
        or payload.get("message") != "查詢成功"
        or not isinstance(result, Mapping)
        or result.get("marketName") != "上市公司"
        or result.get("companyId") != spec["code"]
        or result.get("header", {}).get("mainTitle") != ["決定分派股息及紅利或其他利益之基準日公告"]
        or not isinstance(titles, list)
        or len(titles) != 23
        or titles[11] != {"main": "（五）權利分派內容：", "sub": [], "isSub": "1"}
        or titles[14] != {"main": "（八）權利分派基準日：", "sub": [], "isSub": "1"}
        or titles[20] != {"main": "（四）其他：", "sub": [], "isSub": "1"}
        or not isinstance(row, list)
        or len(row) != 23
        or not isinstance(row[11], str)
        or not isinstance(row[14], str)
        or not isinstance(row[20], str)
    ):
        raise MixedRightsError(f"{spec['code']} MOPS company or literal-field identities do not match")
    if any(value not in row[11] for value in spec["distribution"]) or spec["ex_date"] not in row[14] or spec["fraction_literal"] not in row[20]:
        raise MixedRightsError(f"{spec['code']} MOPS stated distribution literals do not match")
    return spec


def bind_mixed_share_event(raw_payload: bytes, factor_records: Sequence[Mapping[str, Any]]) -> FixedMixedEvent:
    """Bind one approved MOPS mixed-distribution response to its annual row."""
    spec = _bound_mops_payload(raw_payload)
    digest = hashlib.sha256(raw_payload).hexdigest()
    same_key = [item for item in factor_records if item.get("code") == spec["code"] and item.get("effective_date") == spec["effective_on"].isoformat()]
    matches = [item for item in same_key if item.get("event_id") == spec["event_id"]]
    if len(same_key) != 1 or len(matches) != 1:
        raise MixedRightsError(f"expected exactly one bound {spec['code']} factor row")
    record = matches[0]
    fields = record.get("literal_fields")
    if (
        record.get("source") != "annual/twt49u"
        or record.get("market") != "TWSE"
        or not isinstance(fields, Mapping)
        or fields.get("權/息") != "權息"
        or fields.get("股票代號") != spec["code"]
        or fields.get("資料日期") != spec["literal_date"]
        or fields.get("詳細資料") != spec["detail"]
    ):
        raise MixedRightsError(f"{spec['code']} factor row does not match the observed mixed-rights identity")
    try:
        limits = EventLimits(PriceLimits(Decimal(str(fields["跌停價格"])), Decimal(str(fields["漲停價格"]))), str(spec["event_id"]), "TWSE")
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise MixedRightsError(f"{spec['code']} factor row lacks explicit grid-valid bounds") from None
    return FixedMixedEvent(spec["code"], spec["effective_on"], spec["bonus"], spec["cash"], f"{spec['event_id']}|mops-sha256:{digest}", limits)


def build_mixed_share_composer(
    base_corporate: Callable[..., CorporateEvidence], event: FixedMixedEvent, coverage_begin: datetime, coverage_end: datetime
) -> Callable[..., CorporateEvidence]:
    """Merge base cash evidence with ordered, separately-owned share events."""
    spec = next(
        (
            item
            for digest, item in _SPECS.items()
            if event.code == item["code"]
            and event.effective_on == item["effective_on"]
            and event.bonus_per_share == item["bonus"]
            and event.cash_per_share == item["cash"]
            and event.source_id == f"{item['event_id']}|mops-sha256:{digest}"
        ),
        None,
    )
    if spec is None:
        raise MixedRightsError("only fixed supported mixed distributions are supported")
    shares = importlib.import_module("shares")
    grant = datetime.combine(event.effective_on, time(7, 1), TAIPEI)
    delivery = datetime.combine(event.effective_on + timedelta(days=45), time(7, 2), TAIPEI)
    settlement = (
        datetime.combine(event.effective_on + timedelta(days=45), time(7, spec["settlement_minute"]), TAIPEI) if spec["settlement_minute"] is not None else None
    )
    term = shares.ShareTerm(
        f"{event.code}-mixed-shares-{event.effective_on.year}",
        event.code,
        event.bonus_per_share,
        grant,
        delivery,
        settlement,
        spec["fractional_net"],
        grant,
        event.source_id,
        spec["policy"],
        "assumed",
        "same-class-raw-close-cent-half-up",
    )
    provider = shares.build_share_provider(
        (term,),
        (shares.ShareCoverage(coverage_begin, coverage_end, True, f"fixed-{event.code}-share-domain"),),
        initial_cash_cents=200_000_000,
        max_positions=5,
    )

    def moment(item: Mapping[str, Any]) -> datetime:
        return datetime.fromisoformat(str(item["date"]))

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        cuts = [since] + [cut for cut in (grant, delivery, settlement) if cut is not None and since < cut < until] + [until]
        emitted: list[Mapping[str, Any]] = []
        notices: list[Mapping[str, Any]] = []
        backdated: list[Mapping[str, Any]] = []
        for start, end in zip(cuts[:-1], cuts[1:], strict=True):
            base = base_corporate(start, end, [*prefix, *emitted])
            if not base.complete:
                return CorporateEvidence(f"fixed-{event.code}-base-incomplete", (), False)
            emitted.extend(base.events)
            notices.extend(base.share_count_notices)
            backdated.extend(base.backdated)
            rights = provider(start, end, [*prefix, *emitted])
            if not rights.complete:
                return CorporateEvidence(f"fixed-{event.code}-rights-incomplete", (), False)
            emitted.extend(rights.events)
            notices.extend(rights.share_count_notices)
            backdated.extend(rights.backdated)
        return CorporateEvidence(
            f"fixed-{event.code}-mixed-share-composer",
            tuple(sorted(emitted, key=moment)),
            True,
            tuple(sorted(notices, key=moment)),
            tuple(sorted(backdated, key=moment)),
        )

    return provide


__all__ = ["FixedMixedEvent", "MixedRightsError", "bind_mixed_share_event", "build_mixed_share_composer"]
