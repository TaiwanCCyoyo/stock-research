"""Exact source-bound refusal evidence for the 3680 paid subscription."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path, PureWindowsPath
from typing import Any

_SOURCE_TASK = Path(__file__).resolve().parent.parent / "20261002-small-probe"
_PILOT_TASK = _SOURCE_TASK.parent / "20260921-evening-pilot"
if str(_PILOT_TASK) not in sys.path:
    sys.path.insert(0, str(_PILOT_TASK))
if str(_SOURCE_TASK) not in sys.path:
    sys.path.insert(0, str(_SOURCE_TASK))
_source = importlib.import_module("declined_6438")
if Path(_source.__file__ or "").resolve() != (_SOURCE_TASK / "declined_6438.py").resolve():
    raise ImportError("paid-offer types resolved outside the preserved source")
BoundOffer, event_limits = _source.BoundOffer, _source.event_limits

from research_core.chronology import CorporateEvidence  # noqa: E402
from research_core.ledger import replay_ledger  # noqa: E402

CODE, DAY = "3680", date(2019, 11, 20)
AT = datetime.fromisoformat("2019-11-20T07:00:00+08:00")
EVENT_ID = "annual:exdailyq:3680:2019-11-20:731"
RAW_SHA = "80bd1b2077cfe26e5337c613b92a73f1379a6d09ad01417897d1b99cec00aa15"
RAW_PATH = r"D:\Project\Stock\shioaji_stock_prices\data\raw\tpex\exdailyq\20190101_20191231.json"
RATIO, PRICE = Fraction("37.77816495") / 1000, "110.00"
SOURCE_ID = f"{EVENT_ID}|raw:{RAW_SHA}"
POLICY_ID = "standing-no-paid-subscriptions-irrevocable-on-ex-date-v1"
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
    "108/11/20",
    "3680",
    "家登              ",
    "    125.00",
    "    124.28",
    "      0.72",
    "            0.00000000",
    "      0.72",
    "除權",
    "    137.50",
    "    112.00",
    "    125.00",
    "    125.00",
    "            0.00000000",
    "            0.00000000",
    "3500000",
    "    110.00",
    "350000",
    "525000",
    "2625000",
    "     37.77816495",
]
_LITERAL_FIELDS = dict(zip(_FIELDS, _ROW, strict=True))


def bind_offer(raw_payload: bytes, factor_records: Sequence[Mapping[str, Any]]) -> Any:
    if not isinstance(raw_payload, bytes) or hashlib.sha256(raw_payload).hexdigest() != RAW_SHA:
        raise ValueError("3680 annual raw checksum differs from the authoritative source")
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("3680 annual raw is not valid JSON") from error
    tables = payload.get("tables") if isinstance(payload, Mapping) else None
    if not isinstance(payload, Mapping) or payload.get("date") != "20190101~20191231" or not isinstance(tables, list) or len(tables) != 1:
        raise ValueError("3680 annual raw table schema differs")
    table = tables[0]
    if not isinstance(table, Mapping) or table.get("fields") != _FIELDS or not isinstance(table.get("data"), list):
        raise ValueError("3680 annual raw named fields differ")
    if len(table["data"]) != 777 or table["data"][731] != _ROW:
        raise ValueError("3680 annual raw source row index differs")
    rows = [row for row in table["data"] if isinstance(row, list) and len(row) == len(_FIELDS) and row[:2] == _ROW[:2]]
    if len(rows) != 1 or rows[0] != _ROW:
        raise ValueError("3680 annual raw literal paid-rights row differs")
    matching = [
        record for record in factor_records if isinstance(record, Mapping) and record.get("code") == CODE and record.get("effective_date") == DAY.isoformat()
    ]
    if len(matching) != 1:
        raise ValueError("expected exactly one frozen annual 3680 factor row")
    record = matching[0]
    if (
        (
            record.get("event_id"),
            record.get("source"),
            record.get("market"),
            record.get("source_row_index"),
            record.get("raw_sha256"),
            record.get("literal_fields"),
        )
        != (EVENT_ID, "annual/exdailyq", "TPEx", 731, RAW_SHA, _LITERAL_FIELDS)
        or not isinstance(record.get("raw_path"), str)
        or PureWindowsPath(record["raw_path"]) != PureWindowsPath(RAW_PATH)
    ):
        raise ValueError("3680 factor row differs from the frozen annual paid-rights record")
    limits = event_limits.bind_named_rights_execution_limits(factor_records, {(DAY, CODE): EVENT_ID})[(DAY, CODE)]
    offer = BoundOffer(EVENT_ID, CODE, AT, RATIO, PRICE, SOURCE_ID, limits)
    if (
        not isinstance(limits, event_limits.EventLimits)
        or limits.source_id != EVENT_ID
        or limits.exchange != "TPEX"
        or (limits.resolve().lower, limits.resolve().upper) != (Decimal("112.00"), Decimal("137.50"))
    ):
        raise ValueError("3680 bound offer lacks exact official TPEx bounds")
    return offer


def build_declining_provider(base: Callable[..., CorporateEvidence], offer: Any, decisions: list[dict[str, Any]]) -> Callable[..., CorporateEvidence]:
    if not _exact(offer):
        raise ValueError("only exact source-bound 3680 offer is supported")

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        result = base(since, until, prefix)
        if not result.complete or not (since < offer.at <= until):
            return result
        before = sorted(
            (event for event in (*prefix, *result.events) if datetime.fromisoformat(str(event["date"])) < offer.at),
            key=lambda event: datetime.fromisoformat(str(event["date"])),
        )
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


def _exact(offer: Any) -> bool:
    if not isinstance(offer, BoundOffer):
        return False
    if (offer.event_id, offer.code, offer.at, offer.shares_per_old_share, offer.subscription_price_twd, offer.source_id) != (
        EVENT_ID,
        CODE,
        AT,
        RATIO,
        PRICE,
        SOURCE_ID,
    ):
        return False
    return (
        isinstance(offer.limits, event_limits.EventLimits)
        and offer.limits.source_id == EVENT_ID
        and offer.limits.exchange == "TPEX"
        and (offer.limits.resolve().lower, offer.limits.resolve().upper) == (Decimal("112.00"), Decimal("137.50"))
    )


__all__ = ["RAW_PATH", "BoundOffer", "bind_offer", "build_declining_provider"]
