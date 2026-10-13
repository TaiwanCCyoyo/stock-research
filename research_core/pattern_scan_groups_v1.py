"""Bind one target's independent cohorts and controls without recomputation.

C-nh's numeric window is the prior 20 contiguous good-segment sessions. Its
all-H1-source exclusion is separately retained by the stock-phase source audit.
Daily diagnostic aliases retain the original control event identity.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.pattern_scan_controls_v1 import base_no_pattern
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_stock_v1 import EVENT_COLUMNS

LOGGER = logging.getLogger(__name__)
PRIMARY = {**dict.fromkeys(("H1", "B1", "B2", "B3", "B4", "L1"), "C-52w"), **dict.fromkeys(("R1", "R2", "R3", "L3"), "C-dip"), "P1": "C-trend", "L2": "C-trend"}
LOOKBACK = {"C-base": 0, "C-base-no-pattern": 0, "C-52w": 250, "C-nh": 20, "C-dip": 60, "C-trend": 79, "C-P1-breakout": 60}


@dataclass(frozen=True)
class PatternGroups:
    events: Mapping[str, pd.DataFrame]
    daily_states: Mapping[str, pd.Series]
    formula_states: Mapping[str, pd.Series]


def groups_for_pattern(
    target: str,
    cohort_events: pd.DataFrame,
    controls: pd.DataFrame,
    pattern_states: pd.DataFrame,
    universe: pd.DataFrame,
    dates: Sequence[str] | pd.DatetimeIndex,
    definition_id: str,
    input_id: str,
    *,
    security_id: str,
) -> PatternGroups:
    if target not in PRIMARY:
        raise ValueError("unknown target pattern")
    iso_dates = tuple(cast(pd.Timestamp, pd.Timestamp(day)).strftime("%Y-%m-%d") for day in dates)
    n = len(iso_dates)
    if len(set(iso_dates)) != n or tuple(sorted(iso_dates)) != iso_dates or any(len(frame) != n for frame in (controls, pattern_states, universe)):
        raise ValueError("aligned unique common-calendar tables required")
    if not set(EVENT_COLUMNS).issubset(cohort_events.columns):
        raise ValueError("cohort event schema incomplete")
    for frame in (controls, pattern_states, universe, cohort_events):
        if "security_id" in frame and not cast(pd.Series, frame["security_id"]).eq(security_id).all():
            raise ValueError("stock identity differs")
    eligible = universe["base_eligible"].to_numpy(dtype=bool)
    events: dict[str, pd.DataFrame] = {}
    daily: dict[str, pd.Series] = {}
    formula: dict[str, pd.Series] = {}
    index = pd.Index(iso_dates, name="t0")

    def state(values: Any) -> pd.Series:
        array = np.asarray(values)
        if array.shape != (n,) or not np.isin(array, (-1, 0, 1)).all():
            raise ValueError("aligned tri-state observations required")
        return pd.Series(array.astype(np.int8), index=index)

    subtypes = [name[len(target) + 1 :] for name in pattern_states if name.startswith(f"{target}:")]
    for subtype in ("union", *(subtypes if len(subtypes) > 1 else ())):
        key = f"pattern:{subtype}"
        rows = cohort_events.loc[cohort_events.pattern_id.eq(target) & cohort_events.cohort_id.eq(subtype), list(EVENT_COLUMNS)].copy()
        if not rows.empty and (not rows.definition_id.eq(definition_id).all() or not rows.input_id.eq(input_id).all()):
            raise ValueError("pattern cohort fixed identity differs")
        events[key] = rows.reset_index(drop=True)
        daily[key] = state(pattern_states[target if subtype == "union" else f"{target}:{subtype}"])
        formula[key] = daily[key].copy()

    def bind(key: str, control: str, admitted: Any, numeric: Any, indices: Sequence[int]) -> None:
        daily[key], formula[key] = state(admitted), state(numeric)
        rows: list[dict[str, Any]] = []
        for t in indices:
            if not 0 <= t < n or daily[key].iloc[t] != 1:
                raise ValueError("control candidate differs from admitted daily state")
            identity = EventIdentity(security_id, iso_dates[t], control, control, definition_id, input_id)
            rows.append({
                "security_id": security_id,
                "event_id": identity.event_id,
                "t0": iso_dates[t],
                "calendar_index": t,
                "pattern_id": control,
                "subtype_id": control,
                "cohort_id": key,
                "window_start": max(0, t - LOOKBACK[control]),
                "pivot": None,
                "support": None,
                "lower": None,
                "member_subtype_ids": "[]",
                "member_event_ids": "[]",
                "member_metadata": "[]",
                "details_json": "{}",
                "base_eligible": bool(eligible[t]),
                "eligibility_reason": universe.eligibility_reason.iloc[t],
                "definition_id": definition_id,
                "input_id": input_id,
            })
        events[key] = pd.DataFrame(rows, columns=pd.Index(EVENT_COLUMNS))

    bind(
        "C-base-all", "C-base", controls["C-base"], controls["C-base:formula"], [int(t) for t in np.flatnonzero(controls["C-base:cooled"].to_numpy(dtype=bool))]
    )
    no_pattern = base_no_pattern(eligible, pattern_states[target].to_numpy(dtype=np.int8))
    bind("C-base-no-pattern", "C-base-no-pattern", no_pattern.states, no_pattern.formula_states, no_pattern.cooled_indices)
    for control in (PRIMARY[target], *(name for name in ("C-52w", "C-dip", "C-trend", "C-nh", "C-P1-breakout") if name != PRIMARY[target])):
        bind(
            control,
            control,
            controls[control],
            controls[f"{control}:formula"],
            [int(t) for t in np.flatnonzero(controls[f"{control}:cooled"].to_numpy(dtype=bool))],
        )
    for key, control in (("C-52w-daily", "C-52w"), ("C-base-daily", "C-base")):
        bind(key, control, controls[control], controls[f"{control}:formula"], [int(t) for t in np.flatnonzero(controls[control].to_numpy() == 1)])
    LOGGER.debug("Bound pattern=%s stock=%s groups=%d event_counts=%s", target, security_id, len(events), {key: len(frame) for key, frame in events.items()})
    return PatternGroups(events, daily, formula)
