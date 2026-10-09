"""Explicit, opt-in research price bases calculated only from supplied frames.

Factor restatement is neither captured/reinvested total return nor certification
of point-in-time availability. Cutoff bounds event inclusion, not knowledge time.
Legacy loaders and their historical outputs are deliberately independent.
"""

from __future__ import annotations

import logging
from typing import Literal, cast

import numpy as np
import pandas as pd

from StockProject.engine.data_loader import CASH_WINDOW_EVENTS, PERMANENT_FACTOR_EVENTS

LOGGER = logging.getLogger(__name__)
PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
DEFINITION_VERSION = "price-basis.v2"
PriceBasis = Literal["raw", "permanent_adjusted", "reference_factor_adjusted"]


def _event_factor(events: pd.DataFrame) -> float | None:
    """Require one known kind and a consistent factor with its stated direction."""
    kinds = set(events["event_type"].astype(str))
    if len(kinds) != 1 or not kinds <= PERMANENT_FACTOR_EVENTS | CASH_WINDOW_EVENTS:
        return None
    values = cast(pd.Series, pd.to_numeric(events["price_factor"], errors="coerce"))
    if not (np.isfinite(values) & values.gt(0)).all() or values.nunique() != 1:
        return None
    factor = float(values.iloc[0])
    kind = next(iter(kinds))
    if (kind in CASH_WINDOW_EVENTS | {"ETF_SPLIT", "EX_RIGHT"} and factor > 1) or (kind == "ETF_REVERSE_SPLIT" and factor < 1):
        return None
    return factor


def _explained_jumps(changes: pd.Series, event_factors: pd.Series) -> pd.Series:
    """An event must explain the jump's direction and leave a sub-threshold residual."""
    return event_factors.notna() & ((event_factors - 1) * changes).gt(0) & ((1 + changes) / event_factors - 1).abs().lt(0.4)


def _daily_dates(values: pd.Series | pd.DatetimeIndex | list[str | pd.Timestamp], label: str) -> pd.DatetimeIndex:
    """Reject missing, timezone-aware and intraday input rather than normalize."""
    try:
        dates = pd.DatetimeIndex(pd.to_datetime(values))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must contain naive midnight dates") from error
    if dates.tz is not None or dates.hasnans or any(day != day.normalize() for day in dates):
        raise ValueError(f"{label} must contain naive midnight dates")
    return dates


def prepare_prices(
    raw: pd.DataFrame,
    actions: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    basis: PriceBasis,
    cutoff: str | pd.Timestamp,
) -> pd.DataFrame:
    """Align one symbol to a strict calendar, preserving unknowns and evidence.

    Only actions on/before cutoff are considered; later quote rows are excluded.
    Factors apply strictly before ex-date. Unusable selected actions invalidate
    adjusted history through ex-date because that boundary is also unverified.
    Metadata on a noncalendar event is attached to the next calendar session,
    but it never explains that session's jump.
    """
    if basis not in {"raw", "permanent_adjusted", "reference_factor_adjusted"}:
        raise ValueError(f"Unknown price basis: {basis}")
    if not isinstance(calendar, pd.DatetimeIndex):
        raise ValueError("Calendar must be a DatetimeIndex")
    _daily_dates(calendar, "Calendar")
    if not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("Calendar must be sorted and unique")
    cutoff_day = _daily_dates([cutoff], "Cutoff")[0]
    if bool((calendar > cutoff_day).any()):
        raise ValueError("Calendar contains dates after cutoff")
    for frame, columns, label in (
        (raw, ["Code", "Date", *PRICE_COLUMNS, "Volume"], "Raw prices"),
        (actions, ["code", "ex_date", "event_type", "price_factor"], "Actions"),
    ):
        missing = set(columns) - set(frame.columns)
        if missing:
            raise ValueError(f"{label} missing columns: {sorted(missing)}")
    if bool(raw["Code"].isna().any()) or int(raw["Code"].astype(str).nunique()) > 1:
        raise ValueError("Raw prices must contain one nonmissing symbol")
    quotes = raw.copy()
    quotes["Date"] = _daily_dates(cast(pd.Series, raw["Date"]), "Raw dates")
    events = actions.copy()
    events["ex_date"] = _daily_dates(cast(pd.Series, actions["ex_date"]), "Action dates")
    if bool(events["code"].isna().any()):
        raise ValueError("Action codes must be nonmissing")
    code = str(raw["Code"].iloc[0]) if len(raw) else None
    events = events.loc[events["code"].astype(str).eq(code) & events["ex_date"].le(cutoff_day)]
    quotes = quotes.loc[quotes["Date"].le(cutoff_day)]
    duplicates = quotes.loc[quotes["Date"].duplicated(keep=False), "Date"]
    frame = quotes.sort_values("Date", kind="stable").drop_duplicates("Date").set_index("Date").reindex(calendar)
    numeric = frame[[*PRICE_COLUMNS, "Volume"]].apply(pd.to_numeric, errors="coerce")
    raw_prices = numeric[PRICE_COLUMNS]
    valid = pd.Series(np.isfinite(raw_prices.to_numpy()).all(axis=1), index=calendar) & raw_prices.gt(0).all(axis=1)
    valid &= numeric["High"].ge(raw_prices.max(axis=1)) & numeric["Low"].le(raw_prices.min(axis=1))
    reasons = pd.Series("", index=calendar, dtype=object)
    reasons.loc[frame["Code"].isna()] = "missing_official_quote"
    reasons.loc[~valid & frame["Code"].notna()] = "invalid_ohlc"
    factors = pd.Series(1.0, index=calendar)
    kinds_by_position: list[set[str]] = [set() for _ in calendar]
    raw_event_factors = pd.Series(np.nan, index=calendar)
    unrestated_cash_factors = pd.Series(np.nan, index=calendar)

    def mark(mask: pd.Series | np.ndarray, reason: str) -> None:
        reasons.loc[mask] = reasons.loc[mask].map(lambda old: f"{old}|{reason}" if old else reason)
        valid.loc[mask] = False

    mark(calendar.isin(duplicates), "duplicate_date")
    selected_kinds = PERMANENT_FACTOR_EVENTS.copy()
    if basis == "reference_factor_adjusted":
        selected_kinds |= CASH_WINDOW_EVENTS
    for day, day_events in events.groupby("ex_date", sort=True):
        kinds = set(day_events["event_type"].astype(str))
        position = int(calendar.searchsorted(day))
        if position < len(calendar):
            kinds_by_position[position].update(kinds)
            if calendar[position] == day:
                event_factor = _event_factor(day_events)
                if event_factor is not None:
                    raw_event_factors.iloc[position] = event_factor
                    if kinds <= CASH_WINDOW_EVENTS - PERMANENT_FACTOR_EVENTS:
                        unrestated_cash_factors.iloc[position] = event_factor
        unknown = kinds - (PERMANENT_FACTOR_EVENTS | CASH_WINDOW_EVENTS)
        affected = calendar <= day
        event_position = np.zeros(len(calendar), dtype=bool)
        if position < len(calendar):
            event_position[position] = True
            affected[position] = True
        if unknown:
            mark(event_position if basis == "raw" else affected, "unsupported_action")
            if basis != "raw":
                factors.loc[affected] = np.nan
        if basis == "raw":
            continue
        selected = day_events.loc[day_events["event_type"].isin(selected_kinds)]
        if selected.empty:
            continue
        selected_factor = _event_factor(selected)
        reason = None
        if selected["event_type"].nunique() > 1:
            reason = "ambiguous_same_day_actions"
        elif selected_factor is None:
            reason = "ambiguous_or_missing_action_factor"
        if reason:
            mark(affected, reason)
            factors.loc[affected] = np.nan
        else:
            factors.loc[calendar < day] *= cast(float, selected_factor)
    adjusted = raw_prices.mul(factors, axis=0)
    finite_adjusted = pd.Series(np.isfinite(adjusted.to_numpy()).all(axis=1), index=calendar) & adjusted.gt(0).all(axis=1)
    mark(valid & ~finite_adjusted, "invalid_adjusted_ohlc")
    changes = adjusted["Close"].where(valid).pct_change(fill_method=None)
    explained = _explained_jumps(changes, raw_event_factors if basis == "raw" else unrestated_cash_factors) & (basis != "reference_factor_adjusted")
    mark(changes.abs().ge(0.4) & ~explained, "unexplained_raw_jump" if basis == "raw" else "unexplained_adjusted_jump")
    output = adjusted.where(valid, np.nan)
    for column in PRICE_COLUMNS:
        output[f"Raw{column}"] = numeric[column]
    volume = numeric["Volume"]
    good_volume = np.isfinite(volume) & volume.ge(0)
    output["VolumeLots"] = volume.where(good_volume)
    output["Turnover"] = (numeric["Close"] * volume).where(good_volume & valid)
    output["Quality"] = valid
    output["quality_reason"] = reasons.where(reasons.ne(""), None)
    output["volume_status"] = np.where(~good_volume, "missing_or_invalid", np.where(volume.eq(0), "zero", "observed"))
    output["corporate_action_types"] = [",".join(sorted(kinds)) for kinds in kinds_by_position]
    output["restatement_factor"] = factors
    LOGGER.debug("Prepared basis=%s cutoff=%s rows=%d invalid=%d actions=%d", basis, cutoff_day, len(output), int((~valid).sum()), len(events))
    return output
