"""Extract only explicit TWSE/TPEx cash ex-dividend price bounds from preserved rows."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from research_core.execution_prices import PriceError, PriceLimits, round_stock_price

_LITERAL_DATE = re.compile(r"^(?P<year>\d{3})年(?P<month>\d{2})月(?P<day>\d{2})日$")
_ROC_SLASH_DATE = re.compile(r"^(?P<year>\d{3})/(?P<month>\d{2})/(?P<day>\d{2})$")


@dataclass(frozen=True)
class EventLimits:
    """Verified exchange limits attached to one source row, not a signal input."""

    limits: PriceLimits
    source_id: str
    exchange: str = "TWSE"

    def __post_init__(self) -> None:
        if self.exchange not in {"TWSE", "TPEX"}:
            raise ValueError("event limits require a supported execution exchange")

    def resolve(self) -> PriceLimits:
        return self.limits


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _literal_date(value: Any) -> date | None:
    if not isinstance(value, str) or (match := _LITERAL_DATE.fullmatch(value)) is None:
        return None
    try:
        return date(int(match["year"]) + 1911, int(match["month"]), int(match["day"]))
    except ValueError:
        return None


def _roc_slash_date(value: Any) -> date | None:
    if not isinstance(value, str) or (match := _ROC_SLASH_DATE.fullmatch(value)) is None:
        return None
    try:
        return date(int(match["year"]) + 1911, int(match["month"]), int(match["day"]))
    except ValueError:
        return None


def _price(value: Any) -> Decimal | None:
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    try:
        return parsed if round_stock_price(parsed, "down") == parsed else None
    except PriceError:
        return None


def _zero(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return False
    try:
        parsed = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return False
    return parsed.is_finite() and parsed == 0


def _candidate(record: Mapping[str, Any], *, cash_only: bool = True) -> tuple[tuple[date, str], EventLimits | None] | None:
    day, code = _date(record.get("effective_date")), record.get("code")
    if day is None or not isinstance(code, str) or not code:
        return None
    fields = record.get("literal_fields")
    if not isinstance(fields, Mapping):
        return (day, code), None
    if record.get("source") == "annual/twt49u" and record.get("market") == "TWSE":
        # The annual TWT49U contract is exact: no aliases or normalized labels.
        kinds = {"息"} if cash_only else {"權", "權息"}
        valid = fields.get("權/息") in kinds and fields.get("股票代號") == code and _literal_date(fields.get("資料日期")) == day
        lower, upper, exchange = _price(fields.get("跌停價格")), _price(fields.get("漲停價格")), "TWSE"
    elif record.get("source") == "annual/exdailyq" and record.get("market") == "TPEx":
        valid = (
            fields.get("權/息") in ({"除息"} if cash_only else {"除權", "除權息"})
            and fields.get("代號") == code
            and _roc_slash_date(fields.get("除權息日期")) == day
        )
        if cash_only:
            valid = valid and all(_zero(fields.get(name)) for name in ("每仟股無償配股", "現金增資股數", "按持股比例仟股認購"))
        lower, upper, exchange = _price(fields.get("跌停價")), _price(fields.get("漲停價")), "TPEX"
    else:
        return (day, code), None
    if not valid:
        return (day, code), None
    source_id = record.get("event_id")
    if lower is None or upper is None or not isinstance(source_id, str) or not source_id:
        return (day, code), None
    try:
        limits = PriceLimits(lower, upper)
    except PriceError:
        return (day, code), None
    return (day, code), EventLimits(limits, source_id, exchange)


def build_event_limits(events: Sequence[Mapping[str, Any]]) -> dict[tuple[date, str], EventLimits]:
    """Return only unambiguous, cash-only, date/code-bound exchange event limits.

    Any matching malformed, noncash, or duplicate row makes that key unresolved.  The function
    deliberately ignores all financial and factor fields, including current EPS/book columns.
    """
    grouped: dict[tuple[date, str], list[EventLimits | None]] = defaultdict(list)
    for record in events:
        if not isinstance(record, Mapping):
            continue
        candidate = _candidate(record)
        if candidate is not None:
            key, limits = candidate
            grouped[key].append(limits)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1 and values[0] is not None}


def bind_cash_event_limits(
    events: Sequence[Mapping[str, Any]], cash_keys: set[tuple[str, date]], rights_keys: set[tuple[str, date]]
) -> dict[tuple[date, str], EventLimits]:
    """Retain only bounds agreeing with the independent cash/rights domain."""
    allowed = {(day, code) for code, day in cash_keys - rights_keys}
    return {key: value for key, value in build_event_limits(events).items() if key in allowed}


def bind_named_rights_execution_limits(records: Sequence[Mapping[str, Any]], requested: Mapping[tuple[date, str], str]) -> dict[tuple[date, str], EventLimits]:
    """Bind requested named rights rows to explicit, grid-valid execution bounds only."""
    bound: dict[tuple[date, str], EventLimits] = {}
    for key, event_id in requested.items():
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or type(key[0]) is not date
            or not isinstance(key[1], str)
            or not key[1]
            or not isinstance(event_id, str)
            or not event_id
        ):
            raise ValueError("named rights request requires date, code, and event identity")
        day, code = key
        matching = [
            record for record in records if isinstance(record, Mapping) and record.get("code") == code and record.get("effective_date") == day.isoformat()
        ]
        if len(matching) != 1:
            raise ValueError(f"expected exactly one named rights factor row for {code} {day.isoformat()}")
        record = matching[0]
        if record.get("event_id") != event_id:
            raise ValueError(f"named rights factor identity differs for {code} {day.isoformat()}")
        candidate = _candidate(record, cash_only=False)
        if candidate is None or candidate[0] != key or candidate[1] is None:
            raise ValueError(f"named rights factor lacks exact literal identity or explicit grid-valid bounds for {code} {day.isoformat()}")
        bound[key] = candidate[1]
    return bound


__all__ = ["EventLimits", "bind_cash_event_limits", "bind_named_rights_execution_limits", "build_event_limits"]
