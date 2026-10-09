"""Bind supplied H05 observations to the current shared chronology contracts.

No fills, economic events, calendar completeness or last-known marks are inferred.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from research_core.attempt_stress import StressInputs
from research_core.auction import AuctionBatch, CostSchedule, RoutedOrder
from research_core.chronology import (
    CorporateProvider,
    DayFrame,
    DecisionContext,
    ExecutionEvidence,
    ExecutionProvider,
    ExecutionWindow,
    PriorCloseRequest,
    SessionRoute,
)
from research_core.decision import CloseObservation, ExecutionAccountSnapshot

_SPEC = importlib.util.spec_from_file_location("_h05_close_review_policy", Path(__file__).with_name("policy.py"))
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("H05 policy source is unavailable")
_POLICY = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _POLICY
_SPEC.loader.exec_module(_POLICY)

_SESSIONS_PATH = Path(__file__).with_name("sessions.py").resolve()
_SESSIONS_NAME = "_h05_close_review_sessions"
if _SESSIONS_NAME in sys.modules:
    _SESSIONS = sys.modules[_SESSIONS_NAME]
    if Path(str(getattr(_SESSIONS, "__file__", ""))).resolve() != _SESSIONS_PATH:
        raise ImportError("H05 session module origin differs")
else:
    _SESSION_SPEC = importlib.util.spec_from_file_location(_SESSIONS_NAME, _SESSIONS_PATH)
    if _SESSION_SPEC is None or _SESSION_SPEC.loader is None:
        raise ImportError("H05 session source is unavailable")
    _SESSIONS = importlib.util.module_from_spec(_SESSION_SPEC)
    sys.modules[_SESSIONS_NAME] = _SESSIONS
    _SESSION_SPEC.loader.exec_module(_SESSIONS)

LOGGER = logging.getLogger(__name__)
TAIPEI = timezone(timedelta(hours=8))
RAW_COLUMNS = {"Market", "Code", "Date", "Open", "High", "Low", "Close", "Volume", "available_at", "source_id"}
PANEL_COLUMNS = {
    "Market",
    "Code",
    "Date",
    "signal_close",
    "ma20",
    "ma60",
    "ret60",
    "rs60",
    "consecutive_usable",
    "rank_eligible",
    "liquidity_twd",
    "eligible",
    "eligibility_reason",
    "available_at",
    "source_id",
    "panel_source_id",
}


class RuntimeBindingError(ValueError):
    """Supplied identities or availability cannot support an H05 account."""


def _stamp(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=TAIPEI)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeBindingError(f"{label} must be nonempty text")
    return value


def _at(value: Any, label: str) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise RuntimeBindingError(f"{label} must be an aware +08:00 datetime")
    return value


def _day(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        timestamp = pd.Timestamp(value)
    except (ValueError, TypeError) as error:
        raise RuntimeBindingError("Date must identify a calendar day") from error
    if not isinstance(timestamp, pd.Timestamp) or timestamp.tzinfo is not None or timestamp.time() != time():
        raise RuntimeBindingError("Date must be a date-only value or naive midnight")
    return timestamp.date()


def _decimal(value: Any, label: str) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        raise RuntimeBindingError(f"{label} must be numeric, not bool")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise RuntimeBindingError(f"{label} must be numeric") from error
    if not number.is_finite():
        raise RuntimeBindingError(f"{label} must be finite")
    return number


def _market(value: Any) -> str:
    market = "TPEX" if value == "TPEx" else value
    if market not in {"TWSE", "TPEX"}:
        raise RuntimeBindingError("Market must be TWSE or TPEX")
    return market


def _records(table: pd.DataFrame, required: set[str], label: str) -> dict[tuple[date, str], dict[str, Any]]:
    if not isinstance(table, pd.DataFrame) or not required.issubset(table.columns):
        raise RuntimeBindingError(f"{label} columns missing")
    records: dict[tuple[date, str], dict[str, Any]] = {}
    selected = table.loc[:, sorted(required)]
    if not isinstance(selected, pd.DataFrame):
        raise RuntimeBindingError(f"{label} columns must form a table")
    for row in selected.to_dict("records"):
        key = (_day(row["Date"]), _text(row["Code"], f"{label} Code"))
        if key in records:
            raise RuntimeBindingError(f"duplicate {label} key: {key}")
        records[key] = row
    return records


class _ReviewRule:
    def __init__(self, policy: Any, last_day: date, residual_exits_supported: bool = False) -> None:
        self.policy = policy
        self.last_day = last_day
        self.residual_exits_supported = residual_exits_supported

    def __call__(self, context: DecisionContext) -> tuple[PriorCloseRequest, ...]:
        if self.residual_exits_supported:
            for code, held in context.snapshot.holdings.items():
                if type(held.qty) is not int or held.qty <= 0:
                    raise _POLICY.PolicyError(f"{code}: holding quantity must be a positive integer")
        if context.snapshot.as_of.date() == self.last_day:
            if context.pending:
                raise _POLICY.PolicyError("terminal review has unresolved pending requests")
            for code, held in context.snapshot.holdings.items():
                if type(held.qty) is not int or held.qty <= 0 or (held.qty % 1000 and not self.residual_exits_supported):
                    raise _POLICY.PolicyError(f"{code}: unsupported residual shares; whole lots required")
            return ()
        return self.policy(context)


def prepare_inputs(
    raw: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    calendar: tuple[date, ...],
    costs: CostSchedule,
    execution_factory: Callable[[], ExecutionProvider],
    corporate_factory: Callable[[], CorporateProvider],
    calendar_id: str,
    calendar_complete: bool,
    history_start: datetime,
    exit_ma_days: int,
    absent_dates: frozenset[date] = frozenset(),
    session_plan: Any = None,
    odd_lot_adapter: Any = None,
) -> StressInputs:
    """Freeze observations and delegate execution/accounting to shared core."""
    if not isinstance(calendar, tuple) or not calendar or any(type(day) is not date for day in calendar):
        raise RuntimeBindingError("calendar must be a nonempty tuple of date-only values")
    if any(left >= right for left, right in zip(calendar, calendar[1:])):
        raise RuntimeBindingError("calendar must be strictly increasing")
    if calendar_complete is not True:
        raise RuntimeBindingError("caller must explicitly declare a complete calendar")
    _text(calendar_id, "calendar_id")
    history_start = _at(history_start, "history_start")
    if history_start >= _stamp(calendar[0], time(13, 30)):
        raise RuntimeBindingError("history_start must precede the first supplied close")
    if not isinstance(costs, CostSchedule) or not callable(execution_factory) or not callable(corporate_factory):
        raise RuntimeBindingError("CostSchedule and explicit domain factories are required")
    if odd_lot_adapter is not None and (
        not callable(getattr(odd_lot_adapter, "residual_exit_factory", None)) or not callable(getattr(odd_lot_adapter, "with_afterhours_odd_windows", None))
    ):
        raise RuntimeBindingError("odd_lot_adapter requires explicit decision and window callables")
    if session_plan is not None and (not isinstance(session_plan, _SESSIONS.SessionPlan) or session_plan.calendar != calendar):
        raise RuntimeBindingError("session_plan must be a SessionPlan with the same calendar")
    raw_rows = _records(raw, RAW_COLUMNS, "raw")
    panel_rows = _records(panel, PANEL_COLUMNS, "panel")
    if set(raw_rows) != set(panel_rows):
        raise RuntimeBindingError("raw and panel keys must align exactly")
    calendar_days = frozenset(calendar)
    outside = next((day for day, _code in raw_rows if day not in calendar_days), None)
    if outside is not None:
        raise RuntimeBindingError(f"input rows outside supplied calendar: {outside}")
    features_by_day: dict[date, dict[str, Any]] = {}
    prices_by_day: dict[date, dict[str, CloseObservation]] = {}
    routes_by_day: dict[date, dict[str, str]] = {}
    for (day, code), row in raw_rows.items():
        feature = panel_rows[(day, code)]
        market = _market(row["Market"])
        if _market(feature["Market"]) != market:
            raise RuntimeBindingError(f"{day}/{code}: raw/panel market mismatch")
        source = _text(row["source_id"], "raw source_id")
        feature_source = _text(feature["source_id"], "panel source_id")
        if feature_source != source:
            raise RuntimeBindingError(f"{day}/{code}: raw/panel source mismatch")
        panel_source = _text(feature["panel_source_id"], "panel_source_id")
        available = _at(row["available_at"], "raw available_at")
        feature_available = _at(feature["available_at"], "panel available_at")
        if not _stamp(day, time(13, 30)) <= available <= feature_available <= _stamp(day, time(20)):
            raise RuntimeBindingError(f"{day}/{code}: inconsistent or future availability")
        if type(feature["eligible"]) is not bool:
            raise RuntimeBindingError(f"{day}/{code}: eligible must be bool")
        features_by_day.setdefault(day, {})[code] = _POLICY.PolicyFeature(
            exchange=market,
            available_at=feature_available,
            source_id=f"{panel_source}|{feature_source}",
            eligible=feature["eligible"],
            rs60=_decimal(feature["rs60"], "rs60"),
            ret60=_decimal(feature["ret60"], "ret60"),
            ma20=_decimal(feature["ma20"], "ma20"),
            ma60=_decimal(feature["ma60"], "ma60"),
        )
        routes_by_day.setdefault(day, {})[code] = market
        close, signal = _decimal(row["Close"], "raw Close"), _decimal(feature["signal_close"], "signal_close")
        if (close is not None and close <= 0) or (signal is not None and signal <= 0):
            raise RuntimeBindingError(f"{day}/{code}: close prices must be positive")
        if close is not None and signal is not None:
            cents = close * 100
            if cents != cents.to_integral_value():
                raise RuntimeBindingError(f"{day}/{code}: raw Close is not integral cents")
            prices_by_day.setdefault(day, {})[code] = CloseObservation(
                int(cents),
                signal,
                _stamp(day, time(13, 30)),
                available,
                source,
            )
    if session_plan is not None:

        def plan_key(key: Any) -> tuple[date, str]:
            if not isinstance(key, tuple) or len(key) != 2 or type(key[0]) is not date or key[0] not in calendar_days:
                raise RuntimeBindingError("session plan key must identify a supplied calendar date and code")
            return key[0], _text(key[1], "session plan code")

        if set(session_plan.marks) != set(session_plan.confirmed_halts):
            raise RuntimeBindingError("session marks and confirmed halt identities must align exactly")
        for key, status_binding in session_plan.statuses.items():
            day, code = plan_key(key)
            if not isinstance(status_binding, tuple) or len(status_binding) != 2:
                raise RuntimeBindingError("session status requires a status and source identity")
            status, status_source = status_binding
            if status not in ("confirmed_halt", "resumed_rewarming"):
                raise RuntimeBindingError("unknown session status")
            _text(status_source, "session status source_id")
            existing = features_by_day.get(day, {}).get(code)
            if status == "resumed_rewarming":
                if key not in raw_rows or key not in panel_rows or code not in prices_by_day.get(day, {}) or existing is None:
                    raise RuntimeBindingError("resumed status requires actual raw/panel observations and price")
            elif key not in session_plan.marks or session_plan.confirmed_halts[key] != status_source:
                raise RuntimeBindingError("confirmed halt status requires matching mark and source identity")
            if existing is None:
                features_by_day.setdefault(day, {})[code] = _POLICY.PolicyFeature(
                    exchange="TWSE",
                    available_at=_stamp(day, time(20)),
                    source_id=f"session-status:{status_source}",
                    eligible=False,
                    rs60=None,
                    ret60=None,
                    ma20=None,
                    ma60=None,
                    review_status=status,
                    review_status_source_id=status_source,
                )
            else:
                if status == "confirmed_halt" and existing.exchange != "TWSE":
                    raise RuntimeBindingError("confirmed halt proof requires a TWSE route")
                features_by_day[day][code] = replace(existing, review_status=status, review_status_source_id=status_source)
        for key, mark in session_plan.marks.items():
            day, code = plan_key(key)
            source = _text(session_plan.confirmed_halts[key], "confirmed halt source_id")
            if session_plan.statuses.get(key) != ("confirmed_halt", source):
                raise RuntimeBindingError("valuation mark requires the matching confirmed halt status")
            if not isinstance(mark, CloseObservation):
                raise RuntimeBindingError("session mark must be CloseObservation")
            if getattr(mark, "kind", None) != "modeled_valuation_only" or getattr(mark, "halt_evidence_id", None) != source:
                raise RuntimeBindingError("session mark requires modeled valuation kind and matching halt evidence")
            if (
                mark.observed_at.date() != day
                or mark.available_at.date() != day
                or _at(mark.observed_at, "session mark observed_at") > _stamp(day, time(20))
                or _at(mark.available_at, "session mark available_at") > _stamp(day, time(20))
            ):
                raise RuntimeBindingError("session mark must be current-day and available by review")
            reference = _at(getattr(mark, "reference_observed_at", None), "session mark reference_observed_at")
            if reference >= mark.observed_at:
                raise RuntimeBindingError("session mark reference must precede its modeled observation")
            halt_raw_row = raw_rows.get(key)
            if halt_raw_row is not None:
                if any(_decimal(halt_raw_row[field], f"halt raw {field}") is not None for field in ("Open", "High", "Low", "Close")):
                    raise RuntimeBindingError("session mark cannot replace an actual raw observation")
                if _decimal(halt_raw_row["Volume"], "halt raw Volume") != Decimal(0):
                    raise RuntimeBindingError("confirmed halt raw volume must be known zero")
            if code in prices_by_day.get(day, {}):
                raise RuntimeBindingError("session mark cannot replace an actual observation")
            prices_by_day.setdefault(day, {})[code] = mark
            routes_by_day.setdefault(day, {})[code] = "TWSE"
    frozen_features = {day: MappingProxyType(values) for day, values in features_by_day.items()}
    frozen_routes = {day: MappingProxyType(values) for day, values in routes_by_day.items()}

    def feature_provider(as_of: datetime) -> Mapping[str, Any]:
        as_of = _at(as_of, "feature as_of")
        if as_of.date() not in calendar:
            raise RuntimeBindingError("feature as_of is outside the supplied calendar")
        supplied = frozen_features.get(as_of.date(), MappingProxyType({}))
        if any(feature.available_at > as_of for feature in supplied.values()):
            raise RuntimeBindingError("feature is unavailable at requested as_of")
        return supplied

    # Validate profile/absence configuration without constructing execution providers.
    _POLICY.CloseReviewPolicy(exit_ma_days=exit_ma_days, feature_provider=feature_provider, costs=costs, absent_dates=absent_dates)

    def decision_factory() -> _ReviewRule:
        rule = _POLICY.CloseReviewPolicy(exit_ma_days=exit_ma_days, feature_provider=feature_provider, costs=costs, absent_dates=absent_dates)
        decision_rule = rule if odd_lot_adapter is None else odd_lot_adapter.residual_exit_factory(lambda: rule)()
        return _ReviewRule(decision_rule, calendar[-1], residual_exits_supported=odd_lot_adapter is not None)

    def checked_execution_factory() -> ExecutionProvider:
        provider = execution_factory()
        if not callable(provider):
            raise RuntimeBindingError("execution_factory must create a provider")

        def provide(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, orders: tuple[RoutedOrder, ...]) -> ExecutionEvidence:
            for routed in orders:
                day = routed.batch.auction_at.date()
                daily_routes: Mapping[str, str] = frozen_routes.get(day, MappingProxyType({}))
                market = daily_routes.get(routed.order.code)
                if market is None or market != routed.batch.exchange:
                    raise RuntimeBindingError(f"{day}/{routed.order.code}: missing or mismatched execution route")
            return provider(window, snapshot, orders)

        return provide

    frames: list[DayFrame] = []
    for index, day in enumerate(calendar):
        windows: tuple[ExecutionWindow, ...] = ()
        if index:
            sessions = tuple(
                SessionRoute(
                    AuctionBatch(
                        market,
                        "regular_open",
                        _stamp(day, time(8, 55)),
                        _stamp(day, time(9)),
                        f"{calendar_id}:{market}:{day}:open",
                    ),
                    costs,
                )
                for market in ("TWSE", "TPEX")
            )
            windows = (
                ExecutionWindow(
                    f"{calendar_id}:{day}:open",
                    sessions,
                    _stamp(day, time(13, 30)),
                    _stamp(day, time(13, 30)),
                ),
            )
        frames.append(DayFrame(day, _stamp(day, time(13, 30)), _stamp(day, time(20)), prices_by_day.get(day, {}), windows))
    prepared_frames = tuple(frames) if odd_lot_adapter is None else odd_lot_adapter.with_afterhours_odd_windows(frames, costs)
    LOGGER.info("Bound H05 runtime profile=ma%d days=%d observations=%d calendar=%s", exit_ma_days, len(frames), len(raw_rows), calendar_id)
    return StressInputs(
        initial_cash_cents=200_000_000,
        max_positions=5,
        history_start=history_start,
        initial_checkpoint_id=f"{calendar_id}:initial-cash-only",
        frames=prepared_frames,
        calendar_id=calendar_id,
        calendar_complete=calendar_complete,
        decision_factory=decision_factory,
        execution_factory=checked_execution_factory,
        corporate_factory=corporate_factory,
    )
