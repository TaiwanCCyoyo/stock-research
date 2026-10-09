"""Source-bound binding for the approved 2641 TPEx paid-rights offer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import PureWindowsPath
from typing import Any

from declined_6438 import BoundOffer, build_declining_provider, event_limits

CODE = "2641"
DAY = date(2021, 7, 6)
AT = datetime.fromisoformat("2021-07-06T07:00:00+08:00")
EVENT_ID = "annual:exdailyq:2641:2021-07-06:265"
RAW_SHA = "a28800d9eb11714706e74167b31064beec9df6e07aec8a97d3a4c41394be2359"
RAW_PATH = r"D:\Project\Stock\shioaji_stock_prices\data\raw\tpex\exdailyq\20210101_20211231.json"
RATIO = Fraction("188.68432829") / 1000
PRICE = "28.00"
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
    "110/07/06",
    "2641",
    "正德              ",
    "33.30",
    "32.29",
    "1.011472",
    "0.000000",
    "1.011472",
    "除權",
    "36.60",
    "29.10",
    "33.30",
    "33.30",
    "0.00000000",
    "0.00000000",
    "36000000",
    "28.00",
    "3600000",
    "3600000",
    "28800000",
    "188.68432829",
]
_LITERAL_FIELDS = dict(zip(_FIELDS, _ROW, strict=True))


def bind_offer(raw_payload: bytes, factor_records: Sequence[Mapping[str, Any]]) -> BoundOffer:
    """Bind the exact frozen 2641 annual TPEx paid-rights row."""
    if not isinstance(raw_payload, bytes) or hashlib.sha256(raw_payload).hexdigest() != RAW_SHA:
        raise ValueError("2641 annual raw checksum differs from the authoritative source")
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("2641 annual raw is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("2641 annual raw table schema differs")
    tables = payload.get("tables")
    if payload.get("date") != "20210101~20211231" or not isinstance(tables, list) or len(tables) != 1:
        raise ValueError("2641 annual raw table schema differs")
    table = tables[0]
    if not isinstance(table, Mapping) or table.get("fields") != _FIELDS or not isinstance(table.get("data"), list):
        raise ValueError("2641 annual raw named fields differ")
    if len(table["data"]) != 966 or table["data"][265] != _ROW:
        raise ValueError("2641 annual raw source row index differs")
    rows = [row for row in table["data"] if isinstance(row, list) and len(row) == len(_FIELDS) and row[0] == "110/07/06" and row[1] == CODE]
    if len(rows) != 1 or rows[0] != _ROW:
        raise ValueError("2641 annual raw literal paid-rights row differs")
    matching = [
        record for record in factor_records if isinstance(record, Mapping) and record.get("code") == CODE and record.get("effective_date") == DAY.isoformat()
    ]
    if len(matching) != 1:
        raise ValueError("expected exactly one frozen annual 2641 factor row")
    record = matching[0]
    if (
        record.get("event_id") != EVENT_ID
        or record.get("source") != "annual/exdailyq"
        or record.get("market") != "TPEx"
        or record.get("source_row_index") != 265
        or not isinstance(record.get("raw_path"), str)
        or PureWindowsPath(record["raw_path"]) != PureWindowsPath(RAW_PATH)
        or record.get("raw_sha256") != RAW_SHA
        or record.get("literal_fields") != _LITERAL_FIELDS
    ):
        raise ValueError("2641 factor row differs from the frozen annual paid-rights record")
    limits = event_limits.bind_named_rights_execution_limits(factor_records, {(DAY, CODE): EVENT_ID})[(DAY, CODE)]
    offer = BoundOffer(EVENT_ID, CODE, AT, RATIO, PRICE, SOURCE_ID, limits)
    if (
        offer.limits.source_id != EVENT_ID
        or offer.limits.exchange != "TPEX"
        or offer.limits.resolve().lower != Decimal("29.10")
        or offer.limits.resolve().upper != Decimal("36.60")
    ):
        raise ValueError("2641 bound offer lacks the exact official TPEx bounds")
    return offer


__all__ = ["RAW_PATH", "BoundOffer", "bind_offer", "build_declining_provider"]
