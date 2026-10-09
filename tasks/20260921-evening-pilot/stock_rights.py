"""Bound free-share events; no generic rights inference."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, NotRequired, TypedDict

from event_limits import EventLimits

from research_core.chronology import CorporateEvidence
from research_core.execution_prices import PriceLimits

TAIPEI = timezone(timedelta(hours=8))
_FIELDS = (
    "股票代號",
    "股票名稱",
    "(每股配發現金股利)除息",
    "(增資配股) 除權",
    "A. 按普通股股東持股比例每千股無償配股",
    "B. 員工紅利轉增資",
    "C. (有償) 現金增資",
    "每股認購金額",
    "a. 公開承銷",
    "b. 員工認購",
    " c. 原股東認購",
    "按股東持股比例每千股認購",
)


class _ShareSpec(TypedDict):
    effective_on: date
    event_id: str
    row: NotRequired[tuple[str, ...]]
    bonus: Fraction
    source_id: str
    fractional_net_per_share: NotRequired[Decimal]


_TWSE_EVENTS: dict[str, _ShareSpec] = {
    "2915": {
        "effective_on": date(2021, 10, 4),
        "event_id": "annual:twt49u:2915:2021-10-04:883",
        "row": ("2915  ", "潤泰全          ", "0 元／股", "", "300 股", "0 股", "0 股", "0 元／股", "0 股", "0 股", "0 股", "0.00000000 股"),
        "bonus": Fraction(3, 10),
        "source_id": "frozen-inputs:twt49u-2915-2021-10-04-883|rights-detail-2915",
    },
    "2823": {
        "effective_on": date(2021, 10, 25),
        "event_id": "annual:twt49u:2823:2021-10-25:916",
        "row": ("2823  ", "中壽            ", "0 元／股", "", "40 股", "0 股", "0 股", "0 元／股", "0 股", "0 股", "0 股", "0.00000000 股"),
        "bonus": Fraction(1, 25),
        "source_id": "annual:twt49u:2823:2021-10-25:916|rights-detail-2823",
    },
}
_TPEX_EVENT_ID = "annual:exdailyq:6472:2022-08-30:797"
# pragma: allowlist secret
_TPEX_RAW_SHA256 = "22c92069fbf135b476a9892a55ec08e246e93771bedb49874b762a50a457c4d1"
_EVENTS: dict[str, _ShareSpec] = {
    **_TWSE_EVENTS,
    "6472": {
        "effective_on": date(2022, 8, 30),
        "event_id": _TPEX_EVENT_ID,
        "bonus": Fraction(627683965, 6250000000),
        "source_id": f"{_TPEX_EVENT_ID}|mops-sha256:{_TPEX_RAW_SHA256}",
        "fractional_net_per_share": Decimal("10"),
    },
}


class ShareEventError(ValueError):
    pass


@dataclass(frozen=True)
class FixedShareEvent:
    code: str
    effective_on: date
    bonus_per_share: Fraction
    source_id: str
    limits: EventLimits
    fractional_net_per_share: Decimal | None = None


def bind_share_event(detail_payload: Mapping[str, Any], factor_records: Sequence[Mapping[str, Any]]) -> FixedShareEvent:
    """Bind only the two exact annual TWSE free-share rows to official details."""
    matches_detail = [
        (code, item)
        for code, item in _TWSE_EVENTS.items()
        if detail_payload.get("stat") == "ok"
        and tuple(detail_payload.get("fields", ())) == _FIELDS
        and detail_payload.get("data") == [list(item.get("row", ()))]
    ]
    if len(matches_detail) != 1:
        raise ShareEventError("official rights detail is not an exact supported free-share row")
    code, spec = matches_detail[0]
    effective_on = spec["effective_on"]
    same_key = [record for record in factor_records if record.get("code") == code and record.get("effective_date") == effective_on.isoformat()]
    matches = [record for record in same_key if record.get("event_id") == spec["event_id"]]
    if len(same_key) != 1 or len(matches) != 1:
        raise ShareEventError(f"expected exactly one bound {code} factor row")
    record = matches[0]
    fields = record.get("literal_fields")
    if (
        record.get("source") != "annual/twt49u"
        or record.get("market") != "TWSE"
        or record.get("code") != code
        or record.get("effective_date") != effective_on.isoformat()
        or not isinstance(fields, Mapping)
        or fields.get("權/息") != "權"
        or fields.get("股票代號") != code
        or fields.get("資料日期") != f"{effective_on.year - 1911:03d}年{effective_on.month:02d}月{effective_on.day:02d}日"
        or fields.get("詳細資料") != f"{code},{effective_on:%Y%m%d}"
    ):
        raise ShareEventError(f"{code} factor row does not match the observed rights identity")
    try:
        limits = EventLimits(PriceLimits(Decimal(str(fields["跌停價格"])), Decimal(str(fields["漲停價格"]))), str(record["event_id"]), "TWSE")
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise ShareEventError(f"{code} factor row lacks explicit grid-valid bounds") from None
    return FixedShareEvent(code, effective_on, spec["bonus"], spec["source_id"], limits)


def bind_tpex_share_event(raw_payload: bytes, factor_records: Sequence[Mapping[str, Any]]) -> FixedShareEvent:
    """Bind only the preserved 6472 MOPS detail to its exact TPEx annual row."""
    if not isinstance(raw_payload, bytes) or hashlib.sha256(raw_payload).hexdigest() != _TPEX_RAW_SHA256:
        raise ShareEventError("6472 MOPS response does not match the approved raw checksum")
    try:
        payload = json.loads(raw_payload)
        result = payload["result"]
        row = result["data"][0]
        named = {title["main"]: value for title, value in zip(result["titles"], row, strict=True)}
        distribution = named["（五）權利分派內容："]
        effective = named["（八）權利分派基準日："]
        disposition = named["七、其他應公告事項："]
        capital = named["（二）原（定）發行股數總額及每股金額："]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ShareEventError("6472 MOPS response has an unsupported schema") from None
    if (
        payload.get("code") != 200
        or payload.get("message") != "查詢成功"
        or not isinstance(result, Mapping)
        or result.get("marketName") != "上市公司"
        or result.get("companyId") != "6472"
        or result.get("header", {}).get("mainTitle") != ["決定分派股息及紅利或其他利益之基準日公告"]
        or not isinstance(row, list)
        or not all(isinstance(value, str) for value in (distribution, effective, disposition, capital))
        or "每壹仟股無償配發盈餘轉增資100.42943440股" not in distribution
        or "每壹仟股無償配發法定盈餘公積、資本公積轉增資0.00000000股" not in distribution
        or "每壹仟股以每股新台幣0.00元認購 普通股 0.00000000股" not in distribution
        or "本次增資發行新股之權利義務與原股份相同" not in distribution
        or "除權/除息交易日：111年8月30日" not in effective
        or "折發現金至元為止" not in disposition
        or "股票面額認購" not in disposition
        or "每股面額：新台幣10.0000元" not in capital
    ):
        raise ShareEventError("6472 MOPS company or literal-field identities do not match")
    spec = _EVENTS["6472"]
    same_key = [record for record in factor_records if record.get("code") == "6472" and record.get("effective_date") == "2022-08-30"]
    matches = [record for record in same_key if record.get("event_id") == _TPEX_EVENT_ID]
    if len(same_key) != 1 or len(matches) != 1:
        raise ShareEventError("expected exactly one bound 6472 factor row")
    record = matches[0]
    fields = record.get("literal_fields")
    if (
        record.get("source") != "annual/exdailyq"
        or record.get("market") != "TPEx"
        or not isinstance(fields, Mapping)
        or fields.get("權/息") != "除權"
        or fields.get("代號") != "6472"
        or fields.get("除權息日期") != "111/08/30"
        or fields.get("每仟股無償配股") != "100.42943440"
        or fields.get("現金股利") != "0.00000000"
        or fields.get("現金增資股數") != "0"
        or fields.get("現金增資認購價") != "0.00"
        or fields.get("公開承銷股數") != "0"
        or fields.get("員工認購股數") != "0"
        or fields.get("原股東認購股數") != "0"
        or fields.get("按持股比例仟股認購") != "0.00000000"
    ):
        raise ShareEventError("6472 factor row does not match the observed free-share identity")
    try:
        limits = EventLimits(PriceLimits(Decimal(str(fields["跌停價"])), Decimal(str(fields["漲停價"]))), _TPEX_EVENT_ID, "TPEX")
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise ShareEventError("6472 factor row lacks explicit grid-valid bounds") from None
    return FixedShareEvent("6472", spec["effective_on"], spec["bonus"], spec["source_id"], limits, spec.get("fractional_net_per_share"))


def build_share_composer(
    base_corporate: Callable[..., CorporateEvidence], event: FixedShareEvent, coverage_begin: datetime, coverage_end: datetime
) -> Callable[..., CorporateEvidence]:
    spec = _EVENTS.get(event.code)
    if (
        spec is None
        or event.effective_on != spec["effective_on"]
        or event.bonus_per_share != spec["bonus"]
        or event.source_id != spec["source_id"]
        or event.fractional_net_per_share != spec.get("fractional_net_per_share")
    ):
        raise ShareEventError("only fixed supported share events are supported")
    shares = importlib.import_module("shares")
    grant = datetime.combine(event.effective_on, time(7), TAIPEI)
    delivery = grant + timedelta(days=45, minutes=1)
    settlement = delivery + timedelta(minutes=1) if event.fractional_net_per_share is not None else None
    term = shares.ShareTerm(
        f"{event.code}-free-shares-{event.effective_on.year}",
        event.code,
        event.bonus_per_share,
        grant,
        delivery,
        settlement,
        event.fractional_net_per_share,
        grant,
        event.source_id,
        f"modeled-{event.code}-delivery-plus45-calendar-days",
        "assumed",
        "same-class-raw-close-cent-half-up",
    )
    share_provider = shares.build_share_provider(
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
            rights = share_provider(start, end, [*prefix, *emitted])
            if not rights.complete:
                return CorporateEvidence(f"fixed-{event.code}-rights-incomplete", (), False)
            emitted.extend(rights.events)
            notices.extend(rights.share_count_notices)
            backdated.extend(rights.backdated)
        return CorporateEvidence(
            f"fixed-{event.code}-share-composer",
            tuple(sorted(emitted, key=moment)),
            True,
            tuple(sorted(notices, key=moment)),
            tuple(sorted(backdated, key=moment)),
        )

    return provide


__all__ = ["FixedShareEvent", "ShareEventError", "bind_share_event", "bind_tpex_share_event", "build_share_composer"]
