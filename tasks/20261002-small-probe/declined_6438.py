"""Source-bound refusal of two explicitly approved TPEx paid-rights offers."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from research_core.chronology import CorporateEvidence
from research_core.ledger import replay_ledger

event_limits = importlib.import_module("event_limits")
if Path(event_limits.__file__ or "").resolve() != Path(__file__).resolve().parent.parent / "20260921-evening-pilot/event_limits.py":
    raise ImportError("paid-offer limits resolved outside the preserved explicit source")

CODE = "6438"
DAY = date(2019, 12, 24)
AT = datetime.fromisoformat("2019-12-24T07:00:00+08:00")
EVENT_ID = "annual:exdailyq:6438:2019-12-24:774"
RAW_SHA = "80bd1b2077cfe26e5337c613b92a73f1379a6d09ad01417897d1b99cec00aa15"
RAW_PATH = r"D:\Project\Stock\shioaji_stock_prices\data\raw\tpex\exdailyq\20190101_20191231.json"
POLICY_ID = "standing-no-paid-subscriptions-irrevocable-on-ex-date-v1"
RATIO = Fraction("32.43944637") / 1000
PRICE = "68.00"
SOURCE_ID = f"{EVENT_ID}|raw:{RAW_SHA}"

_FIELDS = [
    "除權息日期",
    "代號",
    "名稱",
    "除權息前收盤價",
    "除權息參考價",
    "權值",
    "息值",
    "權值+息值",
    "權/息",
    "漲停價",
    "跌停價",
    "開始交易基準價",
    "減除股利參考價",
    "現金股利",
    "每仟股無償配股",
    "現金增資股數",
    "現金增資認購價",
    "公開承銷股數",
    "員工認購股數",
    "原股東認購股數",
    "按持股比例仟股認購",
]
_ROW = [
    "108/12/24",
    "6438",
    "迅得              ",
    "     82.30",
    "     81.71",
    "      0.59",
    "            0.00000000",
    "      0.59",
    "除權",
    "     90.50",
    "     73.60",
    "     82.30",
    "     82.30",
    "            0.00000000",
    "            0.00000000",
    "2500000",
    "     68.00",
    "250000",
    "375000",
    "1875000",
    "     32.43944637",
]
_LITERAL_FIELDS = dict(zip(_FIELDS, _ROW, strict=True))


@dataclass(frozen=True)
class BoundOffer:
    event_id: str
    code: str
    at: datetime
    shares_per_old_share: Fraction
    subscription_price_twd: str
    source_id: str
    limits: Any


def bind_offer(raw_payload: bytes, factor_records: Sequence[Mapping[str, Any]]) -> BoundOffer:
    """Bind the exact frozen TPEx table row and annual factor identity."""
    if not isinstance(raw_payload, bytes) or hashlib.sha256(raw_payload).hexdigest() != RAW_SHA:
        raise ValueError("6438 annual raw checksum differs from the authoritative source")
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("6438 annual raw is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("6438 annual raw table schema differs")
    tables = payload.get("tables")
    if payload.get("date") != "20190101~20191231" or not isinstance(tables, list) or len(tables) != 1:
        raise ValueError("6438 annual raw table schema differs")
    table = tables[0]
    if not isinstance(table, Mapping) or table.get("fields") != _FIELDS or not isinstance(table.get("data"), list):
        raise ValueError("6438 annual raw named fields differ")
    if len(table["data"]) != 777 or table["data"][774] != _ROW:
        raise ValueError("6438 annual raw source row index differs")
    rows = [row for row in table["data"] if isinstance(row, list) and len(row) == len(_FIELDS) and row[0] == "108/12/24" and row[1] == CODE]
    if len(rows) != 1 or rows[0] != _ROW:
        raise ValueError("6438 annual raw literal paid-rights row differs")
    matching = [
        record for record in factor_records if isinstance(record, Mapping) and record.get("code") == CODE and record.get("effective_date") == DAY.isoformat()
    ]
    if len(matching) != 1:
        raise ValueError("expected exactly one frozen annual 6438 factor row")
    record = matching[0]
    if (
        record.get("event_id") != EVENT_ID
        or record.get("source") != "annual/exdailyq"
        or record.get("market") != "TPEx"
        or record.get("source_row_index") != 774
        or record.get("raw_path") != RAW_PATH
        or record.get("raw_sha256") != RAW_SHA
        or record.get("literal_fields") != _LITERAL_FIELDS
    ):
        raise ValueError("6438 factor row differs from the frozen annual paid-rights record")
    limits = event_limits.bind_named_rights_execution_limits(factor_records, {(DAY, CODE): EVENT_ID})[(DAY, CODE)]
    offer = BoundOffer(EVENT_ID, CODE, AT, RATIO, PRICE, SOURCE_ID, limits)
    if not _is_exact_offer(offer):
        raise ValueError("6438 bound offer is not the exact approved paid-rights offer")
    return offer


def build_declining_provider(base: Callable[..., CorporateEvidence], offer: BoundOffer, decisions: list[dict[str, Any]]) -> Callable[..., CorporateEvidence]:
    """Record fixed refusal, retaining native base evidence without ledger rewrites."""
    if not _is_exact_offer(offer):
        raise ValueError("only exact source-bound approved paid offers are supported")

    def moment(event: Mapping[str, Any]) -> datetime:
        return datetime.fromisoformat(str(event["date"]))

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        result = base(since, until, prefix)
        if not result.complete:
            return result
        if since < offer.at <= until:
            before = sorted((event for event in (*prefix, *result.events) if moment(event) < offer.at), key=moment)
            ledger = replay_ledger(2_000_000, before, max_positions=5)
            if offer.code in ledger["outstanding_share_codes"]:
                return CorporateEvidence("paid-offer-pending-share-qualification-unknown", result.events, False, result.share_count_notices, result.backdated)
            quantity = ledger["positions"].get(offer.code, 0)
            if quantity:
                decision = {
                    "reason": "modeled_paid_subscription_declined",
                    "date": offer.at.isoformat(),
                    "code": offer.code,
                    "event_id": offer.event_id,
                    "qualified_old_shares": quantity,
                    "offer_ratio_numerator": offer.shares_per_old_share.numerator,
                    "offer_ratio_denominator": offer.shares_per_old_share.denominator,
                    "subscription_price_twd": offer.subscription_price_twd,
                    "cash_debit_twd": 0,
                    "new_shares": 0,
                    "time_basis": "assumed",
                    "source_id": offer.source_id,
                    "policy_id": POLICY_ID,
                    "note": "opportunity deliberately declined; not a claim of zero right value",
                }
                if decision not in decisions:
                    decisions.append(decision)
        return CorporateEvidence(f"{result.evidence_id}|{POLICY_ID}", result.events, True, result.share_count_notices, result.backdated)

    return provide


def _is_exact_offer(offer: object) -> bool:
    if not isinstance(offer, BoundOffer):
        return False
    identity = (
        offer.event_id,
        offer.code,
        offer.at,
        offer.shares_per_old_share,
        offer.subscription_price_twd,
        offer.source_id,
    )
    if identity == (EVENT_ID, CODE, AT, RATIO, PRICE, SOURCE_ID):
        expected_bounds = (Decimal("73.60"), Decimal("90.50"))
    elif identity == (
        "annual:exdailyq:2641:2021-07-06:265",
        "2641",
        datetime.fromisoformat("2021-07-06T07:00:00+08:00"),
        Fraction("188.68432829") / 1000,
        "28.00",
        "annual:exdailyq:2641:2021-07-06:265|raw:a28800d9eb11714706e74167b31064beec9df6e07aec8a97d3a4c41394be2359",
    ):
        expected_bounds = (Decimal("29.10"), Decimal("36.60"))
    else:
        return False
    if not isinstance(offer.limits, event_limits.EventLimits) or offer.limits.source_id != offer.event_id or offer.limits.exchange != "TPEX":
        return False
    bounds = offer.limits.resolve()
    return (bounds.lower, bounds.upper) == expected_bounds


__all__ = ["BoundOffer", "bind_offer", "build_declining_provider"]
