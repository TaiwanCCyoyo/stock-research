"""Bind injected raw execution rows to the retained native and resumption leaves.

Quotes retain the leaves' modeled capacity and after-hours close proxy. This
factory reads no market source and must be built before the runtime route guard.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import date
from types import MappingProxyType
from typing import Any

from research_core.chronology import ExecutionProvider

LOGGER = logging.getLogger(__name__)
EventKey = tuple[date, str]


class ExecutionBindingError(ValueError):
    """Injected execution inputs do not fit the declared session calendar."""


def _key(value: Any) -> EventKey:
    if not isinstance(value, tuple) or len(value) != 2 or type(value[0]) is not date or not isinstance(value[1], str) or not value[1].strip():
        raise ExecutionBindingError("execution key requires a date-only value and nonempty code")
    return value


def build_execution_factory(
    modules: Mapping[str, Any],
    *,
    raw_by_key: Mapping[EventKey, Mapping[str, Any]],
    calendar: tuple[date, ...],
    economics: Any,
    halt_cases: tuple[Any, ...],
    no_trade: Any,
    confirmed_halts: Mapping[EventKey, str],
    diagnostics: list[dict[str, Any]],
    resumption_audit: list[dict[str, Any]],
) -> Callable[[], ExecutionProvider]:
    """Freeze supplied rows and construct a fresh native/resumption closure.

    Economic event domains are preserved, including unsupported issuer events.
    Named resumptions outside this calendar are ignored; an included resumption
    requires both its reference and halt session in the calendar. Only the single
    supplied source-bound no-trade case is eligible for the native exception.
    """
    if (
        not isinstance(calendar, tuple)
        or not calendar
        or any(type(day) is not date for day in calendar)
        or any(left >= right for left, right in zip(calendar, calendar[1:]))
    ):
        raise ExecutionBindingError("calendar must be a nonempty strictly increasing date tuple")
    if "no_trade_execution" not in modules or "resumption_execution" not in modules:
        raise ExecutionBindingError("native no-trade and resumption modules required")
    native, resumption = modules["no_trade_execution"], modules["resumption_execution"]
    sessions = frozenset(calendar)
    rows: dict[EventKey, Mapping[str, Any]] = {}
    for supplied_key, row in raw_by_key.items():
        key = _key(supplied_key)
        if key[0] not in sessions:
            raise ExecutionBindingError(f"raw source key outside calendar: {key}")
        if not isinstance(row, Mapping):
            raise ExecutionBindingError(f"raw source row must be a mapping: {key}")
        rows[key] = MappingProxyType(dict(row))
    frozen_rows = MappingProxyType(rows)
    previous_session = MappingProxyType(dict(zip(calendar[1:], calendar[:-1], strict=True)))
    corporate_keys = frozenset(_key(key) for key in economics.corporate_keys)
    event_limits = MappingProxyType({_key(key): value for key, value in economics.event_limits.items()})
    halts: dict[EventKey, str] = {}
    for supplied_key, source in confirmed_halts.items():
        key = _key(supplied_key)
        if not isinstance(source, str) or not source.strip():
            raise ExecutionBindingError(f"confirmed halt requires a source identity: {key}")
        if key[0] in sessions:
            halts[key] = source
    frozen_halts = MappingProxyType(halts)
    if not isinstance(halt_cases, tuple) or any(not isinstance(case, resumption.ResumptionCase) for case in halt_cases):
        raise ExecutionBindingError("halt_cases must be a tuple of bound ResumptionCase values")
    cases = tuple(case for case in halt_cases if case.resumed_day in sessions)
    for case in cases:
        if case.reference_day not in sessions or case.halt_day not in sessions:
            raise ExecutionBindingError(f"named resumption requires reference and halt sessions: {case.code}/{case.resumed_day}")
    verified_no_trades: dict[EventKey, Any] = {}
    if no_trade is not None:
        if not isinstance(no_trade, native.NoTradeEvidence):
            raise ExecutionBindingError("no_trade must be the single bound NoTradeEvidence or None")
        key = _key((no_trade.day, no_trade.code))
        if key[0] in sessions:
            verified_no_trades[key] = no_trade
    frozen_no_trades = MappingProxyType(verified_no_trades)
    LOGGER.info("Bound execution: sessions=%d rows=%d resumptions=%d no_trade=%d", len(calendar), len(rows), len(cases), len(verified_no_trades))

    def native_factory() -> ExecutionProvider:
        return native.build_execution(
            frozen_rows,
            previous_session,
            corporate_keys,
            diagnostics,
            event_limits=event_limits,
            confirmed_halts=frozen_halts,
            verified_regular_no_trades=frozen_no_trades,
            max_positions=5,
        )

    # The extension inspects the native closure. A runtime route guard cannot
    # precede it without hiding that closure and violating its retained contract.
    return resumption.extend_factory(native_factory, cases, native_module=native, audit=resumption_audit)
