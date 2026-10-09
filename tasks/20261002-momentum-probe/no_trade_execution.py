"""Execution provider with one source-bound TPEx regular-session no-trade proof."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import isfinite, isnan
from typing import Any, Final

from research_core.auction import RoutedOrder
from research_core.chronology import ExecutionEvidence, ExecutionProvider, ExecutionWindow
from research_core.decision import ExecutionAccountSnapshot
from research_core.execution_prices import PriceError, round_stock_price

_model = importlib.import_module("modeled_execution")
_policy = importlib.import_module("prototype.execution_policy")
_providers = importlib.import_module("prototype.providers")
EndOfWindowTermination = _model.EndOfWindowTermination
build_modeled_execution_provider = _model.build_modeled_execution_provider
CapacityPolicy, bounded_band = _policy.CapacityPolicy, _policy.bounded_band
SessionExecutionEvidence, SessionQuote = _providers.SessionExecutionEvidence, _providers.SessionQuote

_BAND = Fraction(1, 10)
_BAND_BASIS = "modeled: ordinary +/-10% band from strictly previous market-session close"
_CAPACITY_BASIS = "modeled: assumed full small-order allocation; adverse locked limit receives no allocation; not observed queue"
_AFTERHOURS_CAPACITY_BASIS = (
    "modeled: assumed full afterhours odd-lot allocation at regular-close proxy; adverse locked limit receives no allocation; not observed queue"
)
_TERMINATION = "modeled: expiry at the supplied execution-window cutoff with no further intraday fills"
_NO_TRADE_MARKET: Final = "TPEx"
_NO_TRADE_CODE: Final = "4192"
_NO_TRADE_DAY: Final = date(2021, 10, 21)
_RAW_PRICE_FIELDS: Final = ("開盤", "收盤", "最高", "最低")
_RAW_TRADE_FIELDS: Final = ("成交股數", "成交筆數", "成交金額(元)")


@dataclass(frozen=True)
class NoTradeEvidence:
    exchange: str
    source_id: str
    dataset_sha: str
    code: str
    day: date


def _no_trade_source_id(dataset_sha: str, day: date, code: str) -> str:
    return f"tpex-official:{dataset_sha}|no-trade:{day.isoformat()}:{code}"


def bind_no_trade_source(payload: Mapping[str, object], expected_dataset_sha: str) -> NoTradeEvidence:
    """Bind the sole named raw TPEx placeholder row; missing data is never inferred."""
    if not isinstance(expected_dataset_sha, str) or not expected_dataset_sha:
        raise ValueError("expected_dataset_sha must be nonempty")
    if not isinstance(payload, Mapping):
        raise ValueError("no-trade payload must be a mapping")
    if payload.get("market") != _NO_TRADE_MARKET:
        raise ValueError("no-trade payload market must be TPEx")
    if payload.get("code") != _NO_TRADE_CODE:
        raise ValueError("no-trade payload code is not the verified issuer")
    if payload.get("date") != _NO_TRADE_DAY.isoformat():
        raise ValueError("no-trade payload date is not the verified session")
    if payload.get("source_dataset_sha") != expected_dataset_sha:
        raise ValueError("no-trade payload dataset SHA does not match the expected source")
    if payload.get("open") is not None or payload.get("close") is not None:
        raise ValueError("no-trade payload normalized prices must be null")
    volume = payload.get("volume")
    if isinstance(volume, bool) or not isinstance(volume, int) or volume != 0:
        raise ValueError("no-trade payload normalized volume must be integer zero")
    raw_fields = payload.get("raw_fields")
    if not isinstance(raw_fields, Mapping):
        raise ValueError("no-trade payload raw_fields must be a mapping")
    if any(raw_fields.get(field) != "----" for field in _RAW_PRICE_FIELDS):
        raise ValueError("no-trade payload raw price placeholders do not match")
    if any(raw_fields.get(field) != "0" for field in _RAW_TRADE_FIELDS):
        raise ValueError("no-trade payload raw trade fields do not match")
    if raw_fields.get("代號") != _NO_TRADE_CODE:
        raise ValueError("no-trade payload raw issuer does not match")
    return NoTradeEvidence(
        exchange="TPEX",
        source_id=_no_trade_source_id(expected_dataset_sha, _NO_TRADE_DAY, _NO_TRADE_CODE),
        dataset_sha=expected_dataset_sha,
        code=_NO_TRADE_CODE,
        day=_NO_TRADE_DAY,
    )


def _cents(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float) and not isfinite(value):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite() or decimal <= 0:
        return None
    try:
        if round_stock_price(decimal, "down") != decimal:
            return None
    except PriceError:
        return None
    cents = decimal * 100
    if cents != cents.to_integral_value():
        return None
    return int(cents)


def _finite_positive(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return decimal.is_finite() and decimal > 0


def _is_verified_regular_no_trade(row: Mapping[str, Any], evidence: NoTradeEvidence, day: date, route: RoutedOrder) -> bool:
    if route.batch.venue != "regular_open":
        return False
    if evidence.day != day or evidence.code != route.order.code:
        return False
    if evidence.exchange != route.batch.exchange or evidence.exchange != "TPEX":
        return False
    if not isinstance(evidence.dataset_sha, str) or not evidence.dataset_sha:
        return False
    if evidence.source_id != _no_trade_source_id(evidence.dataset_sha, day, route.order.code):
        return False
    source_id = row.get("source_id")
    if not isinstance(source_id, str) or not source_id.startswith(f"tpex-official:{evidence.dataset_sha}|"):
        return False
    if not _is_missing_normalized_price(row.get("Open")) or not _is_missing_normalized_price(row.get("Close")):
        return False
    volume = row.get("Volume")
    return not isinstance(volume, bool) and isinstance(volume, (int, float)) and isfinite(volume) and volume == 0


def _is_missing_normalized_price(value: object) -> bool:
    return value is None or (isinstance(value, float) and isnan(value))


def build_execution(
    raw_by_key: Mapping[tuple[date, str], Mapping[str, Any]],
    previous_session: Mapping[date, date],
    corporate_keys: frozenset[tuple[date, str]],
    diagnostics: list[dict[str, Any]],
    *,
    event_limits: Mapping[tuple[date, str], Any] | None = None,
    confirmed_halts: Mapping[tuple[date, str], str] | None = None,
    verified_regular_no_trades: Mapping[tuple[date, str], NoTradeEvidence] | None = None,
    max_positions: int = 5,
) -> ExecutionProvider:
    """Return the preserved provider plus one source-bound regular no-trade branch."""
    policy = EndOfWindowTermination("ordinary-open-expiry-v1", _TERMINATION, max_positions)

    def incomplete(day: date, code: str, reason: str, source_id: Any = None) -> Any:
        diagnostics.append({
            "date": day.isoformat(),
            "code": code,
            "reason": reason,
            "source_id": source_id,
        })
        return SessionQuote("UNKNOWN", None, None, None, "")

    def quote_for(day: date, route: RoutedOrder) -> Any:
        code = route.order.code
        row = raw_by_key.get((day, code))
        source_id = row.get("source_id") if row is not None else None
        afterhours_odd = route.batch.venue == "afterhours_odd"
        halt_source = None if confirmed_halts is None else confirmed_halts.get((day, code))
        if halt_source is not None:
            if route.batch.exchange != "TWSE":
                return incomplete(day, code, "confirmed_halt_applies_only_to_twse", halt_source)
            if (day, code) in corporate_keys:
                return incomplete(day, code, "confirmed_halt_conflicts_with_corporate_event", halt_source)
            if not isinstance(halt_source, str) or not halt_source:
                return incomplete(day, code, "missing_confirmed_halt_source_id", halt_source)
            price_field = "Close" if afterhours_odd else "Open"
            if row is not None and _finite_positive(row.get(price_field)):
                return incomplete(day, code, "confirmed_halt_conflicts_with_observed_open", source_id)
            return SessionQuote("HALT", None, None, None, halt_source)
        if row is None:
            return incomplete(day, code, "missing_current_session_row")
        no_trade = None if verified_regular_no_trades is None else verified_regular_no_trades.get((day, code))
        if isinstance(no_trade, NoTradeEvidence) and _is_verified_regular_no_trade(row, no_trade, day, route):
            return SessionQuote("NO_TRADE", None, None, None, no_trade.source_id)
        if not isinstance(source_id, str) or not source_id:
            return incomplete(day, code, "missing_current_session_source_id", source_id)
        price_field = "Close" if afterhours_odd else "Open"
        price_cents = _cents(row.get(price_field))
        if price_cents is None:
            reason = "missing_nonfinite_nonpositive_or_offgrid_close" if afterhours_odd else "missing_nonfinite_nonpositive_or_offgrid_open"
            return incomplete(day, code, reason, source_id)
        quote_source_id = f"modeled:afterhours-regular-close-proxy-v1|reference:{source_id}" if afterhours_odd else source_id
        capacity_basis = _AFTERHOURS_CAPACITY_BASIS if afterhours_odd else _CAPACITY_BASIS
        event_band = None if event_limits is None else event_limits.get((day, code))
        if (day, code) in corporate_keys:
            if event_band is None:
                return incomplete(day, code, "corporate_event_requires_verified_cash_event_limits", source_id)
            if getattr(event_band, "exchange", None) != route.batch.exchange:
                return incomplete(day, code, "verified_cash_event_limits_market_mismatch", source_id)
            try:
                limits = event_band.resolve()
            except (AttributeError, PriceError):
                return incomplete(day, code, "invalid_verified_cash_event_limits", source_id)
            open_price = Decimal(price_cents) / 100
            if open_price < limits.lower or (limits.upper is not None and open_price > limits.upper):
                return incomplete(day, code, "open_outside_verified_cash_event_bounds", source_id)
            adverse_limit = (route.order.side == "BUY" and open_price == limits.upper) or (route.order.side == "SELL" and open_price == limits.lower)
            return SessionQuote(
                "TRADED",
                price_cents,
                event_band,
                CapacityPolicy(0 if adverse_limit else route.order.qty, capacity_basis),
                quote_source_id,
            )
        prior_day = previous_session.get(day)
        prior = raw_by_key.get((prior_day, code)) if prior_day is not None else None
        prior_source_id = prior.get("source_id") if prior is not None else None
        if prior is not None and (not isinstance(prior_source_id, str) or not prior_source_id):
            return incomplete(day, code, "missing_previous_session_source_id", prior_source_id)
        close_cents = _cents(prior.get("Close")) if prior is not None else None
        if close_cents is None:
            return incomplete(
                day,
                code,
                "missing_strictly_previous_session_finite_positive_close",
                source_id,
            )
        band = bounded_band(reference_price=Decimal(close_cents) / 100, band=_BAND, basis=_BAND_BASIS)
        limits = band.resolve()
        assert limits is not None
        open_price = Decimal(price_cents) / 100
        if open_price < limits.lower or (limits.upper is not None and open_price > limits.upper):
            return incomplete(day, code, "open_outside_modeled_ordinary_band", source_id)
        adverse_limit = (route.order.side == "BUY" and open_price == limits.upper) or (route.order.side == "SELL" and open_price == limits.lower)
        return SessionQuote(
            "TRADED",
            price_cents,
            band,
            CapacityPolicy(0 if adverse_limit else route.order.qty, capacity_basis),
            quote_source_id,
        )

    def provide(
        window: ExecutionWindow,
        snapshot: ExecutionAccountSnapshot,
        routes: Sequence[RoutedOrder],
    ) -> ExecutionEvidence:
        if not routes:
            day = window.sessions[0].batch.auction_at.date()
            return ExecutionEvidence(f"modeled-empty-{day.isoformat()}", {}, (), True, True)
        day = window.sessions[0].batch.auction_at.date()
        quotes = {route.order.code: quote_for(day, route) for route in routes}
        session = SessionExecutionEvidence(f"modeled-open-{day.isoformat()}", quotes)
        return build_modeled_execution_provider({day: session}, policy)(window, snapshot, routes)

    return provide


__all__ = ["NoTradeEvidence", "bind_no_trade_source", "build_execution"]
