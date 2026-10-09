"""Exact source-bound refusal evidence for the 6443 paid subscription."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path, PureWindowsPath
from typing import Any

TASK = Path(__file__).resolve().parent
SOURCE_TASK = TASK.parent / "20261002-small-probe"
PILOT_TASK = TASK.parent / "20260921-evening-pilot"
ROOT = TASK.parents[1]
DETAIL_PATH = ROOT / ".tmp/6443-detail-capture-20261002/raw-001.json"
DETAIL_EVENT_PATH = ROOT / ".tmp/6443-detail-capture-20261002/events.jsonl"
for path in (ROOT, PILOT_TASK, SOURCE_TASK, TASK):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from declined_3680 import BoundOffer, event_limits  # noqa: E402

from research_core.chronology import CorporateEvidence  # noqa: E402
from research_core.ledger import replay_ledger  # noqa: E402

CODE = "6443"
DAY = date(2020, 11, 11)
AT = datetime.fromisoformat("2020-11-11T07:00:00+08:00")
EVENT_ID = "annual:twt49u:6443:2020-11-11:845"
RAW_SHA = "e0e2a2dfbd554e3ce6b6eded52ea27b51978baf8ad1f0bdc607ece5117fb9290"
RAW_PATH = r"D:\Project\Stock\shioaji_stock_prices\data\raw\twse\twt49u\20200101_20201231.json"
DETAIL_SHA = "89353dbe30f37816464fe509bdb103416a45732ff549151df2d312876885bc73"
DETAIL_EVENT_SHA = "b034ca34ad3264e3d0587849543ebd5593848cf1b6009c0398fab65a1d84ed3f"
SOURCE_ID = f"{EVENT_ID}|annual:{RAW_SHA}|detail:{DETAIL_SHA}"
POLICY_ID = "standing-no-paid-subscriptions-irrevocable-on-ex-date-v1"
RATIO = Fraction("140.95420009") / 1000
PRICE = "25.80"

_FIELDS = [
    "資料日期",
    "股票代號",
    "股票名稱",
    "除權息前收盤價",
    "除權息參考價",
    "權值+息值",
    "權/息",
    "漲停價格",
    "跌停價格",
    "開盤競價基準",
    "減除股利參考價",
    "詳細資料",
    "最近一次申報資料 季別/日期",
    "最近一次申報每股 (單位)淨值",
    "最近一次申報每股 (單位)盈餘",
]
_ROW = [
    "109年11月11日",
    "6443",
    "元晶",
    "36.50",
    "34.89",
    "1.602852",
    "權",
    "40.15",
    "31.45",
    "36.50",
    "36.50",
    "6443,20201111",
    "115年第2季(https://mops.twse.com.tw/mops/web/t163sb01)",
    "6.50",
    "-0.60",
]
_LITERAL_FIELDS = dict(zip(_FIELDS, _ROW, strict=True))
_DETAIL_FIELDS = [
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
]
_DETAIL_ROW = [
    "6443  ",
    "元晶            ",
    "0 元／股",
    "",
    "0 股",
    "0 股",
    "66,780,000 股",
    "25.8 元／股",
    "6,678,000 股",
    "6,678,000 股",
    "53,424,000 股",
    "140.95420009 股",
]
_DETAIL_LITERAL_FIELDS = dict(zip(_DETAIL_FIELDS, _DETAIL_ROW, strict=True))
_DETAIL_KEY = "6443,20201111"
_REQUEST_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail?STK_NO=6443&T1=20201111&response=json"


def _require_sha(payload: bytes, expected: str, name: str) -> None:
    if not isinstance(payload, bytes) or hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"6443 {name} checksum differs from the authoritative source")


def _parse_mapping(payload: bytes, name: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"6443 {name} is not valid JSON") from error
    if not isinstance(parsed, Mapping):
        raise ValueError(f"6443 {name} schema differs")
    return parsed


def bind_offer(annual_payload: bytes, detail_payload: bytes, detail_event_payload: bytes, factor_records: Sequence[Mapping[str, Any]]) -> Any:
    """Bind the exact TWSE annual row, detail reply, and receipt identity."""
    _require_sha(annual_payload, RAW_SHA, "annual raw")
    annual = _parse_mapping(annual_payload, "annual raw")
    if (
        set(annual) != {"stat", "title", "fields", "data", "extraNotes", "notes", "formula", "strDate", "endDate"}
        or annual.get("stat") != "OK"
        or (annual.get("strDate"), annual.get("endDate")) != ("20200101", "20201231")
    ):
        raise ValueError("6443 annual raw table schema differs")
    if annual.get("fields") != _FIELDS or not isinstance(annual.get("data"), list) or len(annual["data"]) != 888 or annual["data"][845] != _ROW:
        raise ValueError("6443 annual raw source row index differs")
    rows = [row for row in annual["data"] if isinstance(row, list) and len(row) == len(_FIELDS) and row[:2] == _ROW[:2]]
    if len(rows) != 1 or rows[0] != _ROW:
        raise ValueError("6443 annual raw literal paid-rights row differs")

    _require_sha(detail_payload, DETAIL_SHA, "detail raw")
    detail = _parse_mapping(detail_payload, "detail raw")
    if detail.get("stat") != "ok" or detail.get("fields") != _DETAIL_FIELDS or detail.get("data") != [_DETAIL_ROW]:
        raise ValueError("6443 detail raw named fields differ")

    _require_sha(detail_event_payload, DETAIL_EVENT_SHA, "detail receipt")
    try:
        receipt_rows = [json.loads(line) for line in detail_event_payload.decode("utf-8").splitlines() if line]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("6443 detail receipt is not valid JSONL") from error
    if len(receipt_rows) != 1 or not isinstance(receipt_rows[0], Mapping):
        raise ValueError("6443 detail receipt schema differs")
    receipt = receipt_rows[0]
    expected_receipt = {
        "source": "twt49u",
        "code": CODE,
        "effective_date_from_annual_row": DAY.isoformat(),
        "detail_key": _DETAIL_KEY,
        "request_key_date": "20201111",
        "request_url": _REQUEST_URL,
        "annual_raw_path": RAW_PATH,
        "annual_raw_sha256": RAW_SHA,
        "annual_row_index": 845,
        "response_sha256": DETAIL_SHA,
        "literal_fields": _DETAIL_LITERAL_FIELDS,
        "historical_availability": None,
        "public_availability": None,
        "delivery_time": None,
    }
    if dict(receipt) != expected_receipt:
        raise ValueError("6443 detail receipt differs from the frozen official lookup")

    matching = [
        record for record in factor_records if isinstance(record, Mapping) and record.get("code") == CODE and record.get("effective_date") == DAY.isoformat()
    ]
    if len(matching) != 1:
        raise ValueError("expected exactly one frozen annual 6443 factor row")
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
        != (EVENT_ID, "annual/twt49u", "TWSE", 845, RAW_SHA, _LITERAL_FIELDS)
        or not isinstance(record.get("raw_path"), str)
        or PureWindowsPath(record["raw_path"]) != PureWindowsPath(RAW_PATH)
    ):
        raise ValueError("6443 factor row differs from the frozen annual paid-rights record")
    limits = event_limits.bind_named_rights_execution_limits(factor_records, {(DAY, CODE): EVENT_ID})[(DAY, CODE)]
    offer = BoundOffer(EVENT_ID, CODE, AT, RATIO, PRICE, SOURCE_ID, limits)
    if not _exact(offer):
        raise ValueError("6443 bound offer lacks exact official TWSE bounds")
    return offer


def build_declining_provider(base: Callable[..., CorporateEvidence], offer: Any, decisions: list[dict[str, Any]]) -> Callable[..., CorporateEvidence]:
    """Record refusal while retaining the native event stream and ledger."""
    if not _exact(offer):
        raise ValueError("only exact source-bound 6443 offer is supported")

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
    return (
        isinstance(offer, BoundOffer)
        and (offer.event_id, offer.code, offer.at, offer.shares_per_old_share, offer.subscription_price_twd, offer.source_id)
        == (EVENT_ID, CODE, AT, RATIO, PRICE, SOURCE_ID)
        and isinstance(offer.limits, event_limits.EventLimits)
        and offer.limits.source_id == EVENT_ID
        and offer.limits.exchange == "TWSE"
        and (offer.limits.resolve().lower, offer.limits.resolve().upper) == (Decimal("31.45"), Decimal("40.15"))
    )


__all__ = ["BoundOffer", "bind_offer", "build_declining_provider"]
