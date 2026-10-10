"""Pure, evidence-preserving cash-term selection for held corporate records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

POLICY_ID = "exchange-cash-first-unanimous-mops-v1"
_CODES = re.compile(r"[0-9]{4}$")
_KINDS = {"TWSE": {"息", "權", "權息"}, "TPEx": {"除息", "除權", "除權息"}}
_CASH_KINDS = {"息", "權息", "除息", "除權息"}
_BASES = {"cash_only_total", "twse_detail_cash_column", "explicit_cash_column", "mops_ordinary_cash_statement"}
_CURRENCIES = {"exchange_TWD", "not_foreign_stated"}


class CashSelectionError(ValueError):
    """A held cash candidate is malformed or outside the fixed selector domain."""


@dataclass(frozen=True)
class CashSelection:
    code: str
    market: str
    effective_date: date
    kind: str
    amount: Decimal | None
    status: str
    selected_sources: tuple[dict[str, Any], ...]
    all_candidates: tuple[dict[str, Any], ...]
    unresolved_reason: str | None
    policy_id: str = POLICY_ID


def _amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str):
        raise CashSelectionError("candidate amount must be a string or null")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise CashSelectionError("candidate amount is malformed") from exc
    if not amount.is_finite() or amount < 0:
        raise CashSelectionError("candidate amount must be finite and nonnegative")
    return amount


def _candidate(value: Any) -> tuple[dict[str, Any], Decimal | None]:
    if not isinstance(value, Mapping):
        raise CashSelectionError("candidate must be a mapping")
    copied = dict(value)
    basis, currency = copied.get("basis"), copied.get("currency_status")
    if basis not in _BASES or currency not in _CURRENCIES:
        raise CashSelectionError("candidate basis or currency status is unsupported")
    for field in ("source_path", "source_sha256"):
        if not isinstance(copied.get(field), str) or not copied[field]:
            raise CashSelectionError(f"candidate {field} is required")
    return copied, _amount(copied.get("amount"))


def _event(event: Mapping[str, Any]) -> tuple[str, str, date, str]:
    code, market, raw_date, kind = (event.get(name) for name in ("code", "market", "effective_date", "event_kind"))
    if not isinstance(code, str) or not _CODES.fullmatch(code):
        raise CashSelectionError("code must be four ASCII digits")
    if market not in _KINDS or kind not in _KINDS[market]:
        raise CashSelectionError("market or event kind is unsupported")
    if not isinstance(raw_date, str):
        raise CashSelectionError("effective_date must be ISO text")
    try:
        return code, market, date.fromisoformat(raw_date), kind
    except ValueError as exc:
        raise CashSelectionError("effective_date must be ISO date") from exc


def _exchange_allowed(market: str, kind: str, candidate: Mapping[str, Any]) -> bool:
    basis = candidate["basis"]
    if candidate["currency_status"] != "exchange_TWD":
        return False
    if market == "TWSE":
        return basis == "twse_detail_cash_column" or (basis == "cash_only_total" and kind == "息")
    return basis == "explicit_cash_column"


def select_cash(event: Mapping[str, Any]) -> CashSelection:
    """Select a stated cash amount without dropping conflicting source evidence."""
    code, market, effective_date, kind = _event(event)
    raw_candidates = event.get("candidates")
    if not isinstance(raw_candidates, list):
        raise CashSelectionError("candidates must be a list")
    parsed = tuple(_candidate(item) for item in raw_candidates)
    candidates = tuple(item for item, _amount_value in parsed)
    if kind not in _CASH_KINDS:
        return CashSelection(code, market, effective_date, kind, None, "noncash_domain", (), candidates, "rights_domain", POLICY_ID)

    exchange = [(item, amount) for item, amount in parsed if amount is not None and _exchange_allowed(market, kind, item)]
    exchange_values = {amount for _item, amount in exchange}
    if len(exchange_values) == 1:
        return CashSelection(
            code,
            market,
            effective_date,
            kind,
            next(iter(exchange_values)),
            "selected_exchange",
            tuple(item for item, _amount_value in exchange),
            candidates,
            None,
            POLICY_ID,
        )
    if len(exchange_values) > 1:
        return CashSelection(code, market, effective_date, kind, None, "unresolved", (), candidates, "conflicting_exchange_cash", POLICY_ID)

    mops = [
        (item, amount)
        for item, amount in parsed
        if amount is not None and item["basis"] == "mops_ordinary_cash_statement" and item["currency_status"] == "not_foreign_stated"
    ]
    values = {amount for _item, amount in mops}
    if len(values) == 1:
        return CashSelection(
            code, market, effective_date, kind, next(iter(values)), "selected_mops", tuple(item for item, _amount_value in mops), candidates, None, POLICY_ID
        )
    reason = "conflicting_mops_cash" if len(values) > 1 else "no_usable_cash_candidate"
    return CashSelection(code, market, effective_date, kind, None, "unresolved", (), candidates, reason, POLICY_ID)


__all__ = ["CashSelection", "CashSelectionError", "POLICY_ID", "select_cash"]
