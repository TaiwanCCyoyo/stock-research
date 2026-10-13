"""Bind approved condition values to event identities without global calculation."""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_conditions_v1 import FEATURES, PATTERNS, classify_column, selection_atoms
from research_core.pattern_scan_stock_v1 import h1_values

LOGGER = logging.getLogger(__name__)
H1_FIELDS = frozenset(name for name, definition in FEATURES.items() if definition.pattern_only and name != "SR_support")


def atoms_for_pattern(target: str) -> tuple[Atom, ...]:
    """Exclude the target's PAT condition and unrelated H1-only fields."""
    if target not in PATTERNS:
        raise ValueError("target must be an approved pattern")
    return tuple(atom for atom in selection_atoms() if atom.feature_id != f"PAT_other_{target}" and (target == "H1" or atom.feature_id not in H1_FIELDS))


def event_conditions(events: pd.DataFrame, indicators: pd.DataFrame, common_values: pd.DataFrame, *, target_pattern: str) -> pd.DataFrame:
    """Return event-local wide value/bin/status/reason columns.

    The caller has already computed complete-pool H/J/K3/MKT and raw PAT union
    states. Every feature reads only its event's t0 row, except the public H1
    formatter which uses the preserved source metadata and causal restart low.
    Controls retain common conditions but have no event support or H1 structure.
    """
    if target_pattern not in PATTERNS:
        raise ValueError("target_pattern must be approved")
    if not isinstance(indicators.index, pd.DatetimeIndex) or not common_values.index.equals(indicators.index):
        raise ValueError("indicators and common values must share the same DatetimeIndex")
    calendar = cast(pd.DatetimeIndex, indicators.index)
    if (
        calendar.tz is not None
        or calendar.hasnans
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or any(day != day.normalize() for day in calendar)
    ):
        raise ValueError("calendar must be unique sorted timezone-naive midnight dates")
    required = {"event_id", "security_id", "t0", "calendar_index", "pattern_id", "support"}
    if (
        not events.columns.is_unique
        or not required.issubset(events)
        or not indicators.columns.is_unique
        or not common_values.columns.is_unique
        or not {"Close", "Low"}.issubset(indicators)
    ):
        raise ValueError("unique event and source columns are required")
    event_rows = events.reset_index(drop=True).copy(deep=True)
    if event_rows.event_id.duplicated().any() or not event_rows.event_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise ValueError("events require unique nonblank identities")
    if not event_rows.security_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all() or event_rows.security_id.nunique() > 1:
        raise ValueError("events must belong to one explicit stock")
    positions: list[int] = []
    for supplied in event_rows.itertuples(index=False):
        row = cast(Any, supplied)
        index = row.calendar_index
        if isinstance(index, (bool, np.bool_)) or not isinstance(index, (int, np.integer)) or not 0 <= index < len(calendar):
            raise ValueError("event calendar_index must be a valid integer")
        if row.t0 != cast(pd.Timestamp, calendar[int(index)]).strftime("%Y-%m-%d"):
            raise ValueError("event t0 does not match calendar_index")
        for source in (common_values, indicators):
            if "security_id" in source and source["security_id"].iloc[int(index)] != row.security_id:
                raise ValueError("event security differs from supplied stock")
            if "t0" in source and source["t0"].iloc[int(index)] != row.t0:
                raise ValueError("source t0 differs from common calendar")
        positions.append(int(index))
    selected = common_values.iloc[positions].reset_index(drop=True)
    is_h1 = cast(pd.Series, event_rows.pattern_id.eq("H1"))
    is_pattern = cast(pd.Series, event_rows.pattern_id.isin(PATTERNS))
    h1 = h1_values(cast(pd.DataFrame, event_rows.loc[is_h1]), indicators) if is_h1.any() else pd.DataFrame()
    pieces: list[pd.DataFrame] = [cast(pd.DataFrame, event_rows[["event_id"]])]
    for feature in FEATURES:
        present = feature in selected
        values = cast(pd.Series, selected[feature]).astype(object).copy() if present else pd.Series(None, index=event_rows.index, dtype=object)
        allowed = pd.Series(True, index=event_rows.index, dtype=bool)
        reasons = (
            cast(pd.Series, selected[f"{feature}_unknown_reason"]).copy()
            if f"{feature}_unknown_reason" in selected
            else pd.Series(None, index=event_rows.index, dtype=object)
        )
        if not present:
            reasons[:] = "missing_source_column"
        if f"{feature}_applicable" in selected:
            supplied_allowed = cast(pd.Series, selected[f"{feature}_applicable"])
            if not pd.api.types.is_bool_dtype(supplied_allowed) or supplied_allowed.isna().any():
                raise ValueError("source applicability must be known boolean")
            allowed = supplied_allowed.astype(bool).copy()
        if feature in H1_FIELDS:
            allowed = is_h1.copy()
            values[:] = None
            reasons[:] = None
        if feature in H1_FIELDS or feature == "G":
            if is_h1.any():
                values.loc[is_h1] = h1[feature]
                reasons.loc[is_h1] = h1[f"{feature}_unknown_reason"] if f"{feature}_unknown_reason" in h1 else None
                if f"{feature}_applicable" in h1:
                    allowed.loc[is_h1] = h1[f"{feature}_applicable"]
        if feature == "SR_support":
            allowed = is_pattern.copy()
            reasons[:] = None
            values[:] = None
            for index in event_rows.index:
                if not allowed.iloc[index]:
                    continue
                support = event_rows.support.iloc[index]
                anchor = indicators["Close"].iloc[positions[index]]
                if pd.isna(support):
                    reasons.iloc[index] = "missing_event_support"
                elif (
                    not isinstance(support, (int, float, np.integer, np.floating))
                    or isinstance(support, (bool, np.bool_))
                    or not np.isfinite(support)
                    or support <= 0
                ):
                    reasons.iloc[index] = "invalid_event_support"
                elif pd.isna(anchor) or not np.isfinite(anchor) or anchor <= 0:
                    reasons.iloc[index] = "invalid_anchor"
                else:
                    values.iloc[index] = float(anchor) / float(support) - 1
        if feature.startswith("PAT_other_"):
            if feature == f"PAT_other_{target_pattern}":
                allowed[:] = False
            elif present:
                missing = values.isna()
                states = values.loc[~missing]
                integers = states.map(lambda state: isinstance(state, (int, np.integer)) and not isinstance(state, (bool, np.bool_)))
                if not integers.all() or not states.isin((-1, 0, 1)).all():
                    raise ValueError("PAT source states must be integer -1/0/1")
                unknown = missing | values.eq(-1)
                values.loc[~unknown] = values.loc[~unknown].eq(1)
                values.loc[unknown] = None
                reasons.loc[unknown] = "pattern_window_unknown"
        if feature == "MKT":
            reasons.loc[values.eq("unknown")] = "market_context_unknown"
        values.loc[~allowed] = None
        classified = classify_column(feature, values, applicable=allowed, unknown_reason=reasons)
        classified = classified.rename(columns={"bin_id": f"{feature}_bin", "status": f"{feature}_status", "reason": f"{feature}_reason"})
        pieces.append(pd.concat([values.rename(feature), classified], axis=1))
    result = pd.concat(pieces, axis=1)
    LOGGER.debug("Bound scan conditions target=%s events=%d H1=%d features=%d", target_pattern, len(events), int(is_h1.sum()), len(FEATURES))
    return result
