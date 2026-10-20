"""Q4 daily candidate states; unavailable conditions retain episode uncertainty.

The historical v1 caller retains its strict applicability contract. This version
uses the mission's tri-state episode rule: an unavailable conjunction on a raw
true day is unknown, never a false observation or a reason to drop the episode.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern, event_conditions
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_reporting_v1 import candidate_membership
from research_core.patterns.scan_contract_v1 import StateArray

LOGGER = logging.getLogger(__name__)


def daily_candidate_states(
    target: str,
    raw_events: pd.DataFrame,
    indicators: pd.DataFrame,
    common_plus_global: pd.DataFrame,
    pattern_raw_union: StateArray,
    *,
    security_id: str,
    definition_id: str,
    input_id: str,
    candidates: Mapping[str, tuple[Atom, ...]],
) -> Mapping[str, StateArray]:
    allowed = frozenset(atoms_for_pattern(target))
    calendar = indicators.index
    if not isinstance(calendar, pd.DatetimeIndex) or not common_plus_global.index.equals(calendar):
        raise ValueError("daily candidate sources must share the common calendar")
    n = len(calendar)
    if pattern_raw_union.shape != (n,) or pattern_raw_union.dtype != np.int8 or not np.isin(pattern_raw_union, (-1, 0, 1)).all():
        raise ValueError("aligned raw union int8 states required")
    dates = calendar.strftime("%Y-%m-%d").tolist()
    for frame in (indicators, common_plus_global):
        if "security_id" in frame and not frame.security_id.eq(security_id).all():
            raise ValueError("daily stock identity differs")
        if "t0" in frame and frame.t0.tolist() != dates:
            raise ValueError("daily source dates differ")
        if "calendar_index" in frame and frame.calendar_index.tolist() != list(range(n)):
            raise ValueError("daily source positions differ")
        for name, expected in (("definition_id", definition_id), ("input_id", input_id)):
            if name in frame and not cast(pd.Series, frame[name]).eq(expected).all():
                raise ValueError("daily source fixed identity differs")
    required = {"event_id", "security_id", "t0", "calendar_index", "pattern_id", "subtype_id", "definition_id", "input_id", "support", "pivot", "details_json"}
    if not raw_events.columns.is_unique or not required.issubset(raw_events):
        raise ValueError("raw events require canonical metadata")
    target_rows = raw_events.loc[raw_events.pattern_id.eq(target)]
    representatives: dict[int, dict[str, Any]] = {}
    for supplied in target_rows.to_dict("records"):
        row = dict(supplied)
        t = row["calendar_index"]
        if isinstance(t, (bool, np.bool_)) or not isinstance(t, (int, np.integer)) or not 0 <= t < n or pattern_raw_union[int(t)] != 1:
            raise ValueError("raw event does not match true union observation")
        t = int(t)
        identity = EventIdentity(security_id, dates[t], target, row["subtype_id"], definition_id, input_id)
        if any(
            row[name] != value
            for name, value in (
                ("security_id", security_id),
                ("t0", dates[t]),
                ("definition_id", definition_id),
                ("input_id", input_id),
                ("event_id", identity.event_id),
            )
        ):
            raise ValueError("raw event fixed identity differs")
        representatives.setdefault(t, row)
    if set(representatives) != set(int(t) for t in np.flatnonzero(pattern_raw_union == 1)):
        raise ValueError("every true raw union day requires its source event")
    daily_rows = []
    for t, date in enumerate(dates):
        if t in representatives:
            daily_rows.append(representatives[t])
        else:
            identity = EventIdentity(security_id, date, "C-base", "C-base", definition_id, input_id)
            daily_rows.append({
                "event_id": identity.event_id,
                "security_id": security_id,
                "t0": date,
                "calendar_index": t,
                "pattern_id": "C-base",
                "subtype_id": "C-base",
                "definition_id": definition_id,
                "input_id": input_id,
                "support": None,
                "pivot": None,
                "details_json": "{}",
            })
    daily = pd.DataFrame(daily_rows, columns=pd.Index(sorted(required)))
    conditions = event_conditions(daily, indicators, common_plus_global, target_pattern=target)
    result: dict[str, StateArray] = {}
    for candidate_id, atoms in candidates.items():
        if not isinstance(candidate_id, str) or not candidate_id.strip() or not atoms or any(atom not in allowed for atom in atoms):
            raise ValueError("candidate must use approved target atoms")
        membership = candidate_membership(conditions, atoms)
        # N/A is a valid event-level status (for example H outside its
        # eligible pool, or H1 A without bonus levels). For Q4 it cannot prove
        # absence of a candidate; preserve it as an undecidable daily state.
        resolved = np.where(membership == -2, -1, membership)
        values = np.where((pattern_raw_union == 0) | (resolved == 0), 0, np.where((pattern_raw_union == 1) & (resolved == 1), 1, -1)).astype(np.int8)
        values.setflags(write=False)
        result[candidate_id] = values
    LOGGER.debug("Daily candidate target=%s stock=%s rows=%d raw_true=%d candidates=%d", target, security_id, n, len(representatives), len(result))
    return result
