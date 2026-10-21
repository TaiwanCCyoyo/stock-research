"""Pure event, condition and cohort-membership binding at the stock barrier."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import pandas as pd

from research_core.pattern_scan_classification_cache_v1 import ConditionClassificationCache
from research_core.pattern_scan_event_conditions_v1 import event_conditions
from research_core.pattern_scan_groups_v1 import PatternGroups, groups_for_pattern
from research_core.pattern_scan_projection_v1 import project_outcomes
from research_core.pattern_scan_stock_v1 import EVENT_COLUMNS

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventTables:
    events: pd.DataFrame
    conditions: pd.DataFrame
    group_memberships: pd.DataFrame
    daily_groups: Mapping[str, pd.Series]
    formula_groups: Mapping[str, pd.Series]


@dataclass(frozen=True)
class ProjectedGroups:
    raw_events: pd.DataFrame
    events: pd.DataFrame
    group_memberships: pd.DataFrame


def project_group_outcomes(
    groups: PatternGroups,
    base_labels: pd.DataFrame,
    quality_reason: pd.Series,
    *,
    base_label_version_id: str,
    base_label_manifest_sha256: str,
) -> ProjectedGroups:
    """Bind existing groups/outcomes without calculating any condition columns.

    This is the same canonical binding used by full EventTables. Q1 may reduce
    it immediately in memory instead of retaining expanded event/condition files.
    """
    memberships: list[dict[str, str]] = []
    pieces = []
    for group_id, supplied in groups.events.items():
        rows = supplied.copy(deep=True)
        is_control = rows.pattern_id.str.startswith("C-") if not rows.empty else pd.Series(False, index=rows.index)
        rows.loc[is_control, "cohort_id"] = rows.loc[is_control, "pattern_id"]
        pieces.append(rows)
        memberships.extend({"group_id": group_id, "event_id": event_id} for event_id in rows.event_id)
    combined = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=pd.Index(EVENT_COLUMNS))
    duplicates = combined.loc[combined.event_id.duplicated(keep=False)]
    for _, copies in duplicates.groupby("event_id", sort=False):
        first = copies.iloc[0]
        if not cast(pd.Series, copies.eq(first).fillna(False).where(copies.notna() | first.notna(), True).all()).all():
            raise ValueError("duplicate canonical event identity has differing metadata")
    unique = combined.drop_duplicates("event_id", keep="first").reset_index(drop=True)
    projected = project_outcomes(
        unique,
        base_labels,
        quality_reason,
        base_label_version_id=base_label_version_id,
        base_label_manifest_sha256=base_label_manifest_sha256,
    )
    if not projected.empty and (not projected.horizon.isin((126, 252)).all() or not projected.groupby("event_id").horizon.nunique().eq(2).all()):
        raise ValueError("events require both fixed horizon base labels")
    membership_frame = pd.DataFrame(memberships, columns=pd.Index(("group_id", "event_id"))).drop_duplicates().reset_index(drop=True)
    return ProjectedGroups(unique, projected, membership_frame)


def build_event_tables(
    target: str,
    tables: Mapping[str, pd.DataFrame],
    global_values: pd.DataFrame,
    *,
    security_id: str,
    definition_id: str,
    input_id: str,
    base_label_version_id: str,
    base_label_manifest_sha256: str,
    classification_cache: ConditionClassificationCache | None = None,
) -> EventTables:
    required = {"prices", "indicators", "pivots", "common_values", "universe", "pattern_states", "cohort_events", "controls", "base_labels"}
    if not required.issubset(tables):
        raise ValueError("complete stock-phase tables required")
    calendar = tables["prices"].index
    if not isinstance(calendar, pd.DatetimeIndex) or not global_values.index.equals(calendar):
        raise ValueError("global and stock common calendar differ")
    dates = calendar.strftime("%Y-%m-%d").tolist()
    for name in ("prices", "indicators", "common_values", "universe", "pattern_states", "controls"):
        frame = tables[name]
        if not frame.index.equals(calendar) or not frame.columns.is_unique:
            raise ValueError("stock-phase calendar or columns differ")
        if "t0" in frame and frame.t0.tolist() != dates:
            raise ValueError("stock-phase t0 differs from common calendar")
        if "calendar_index" in frame and frame.calendar_index.tolist() != list(range(len(calendar))):
            raise ValueError("stock-phase calendar positions differ")
    for frame in (*tables.values(), global_values):
        if "security_id" in frame and not frame.security_id.eq(security_id).all():
            raise ValueError("stock identity differs")
        for name, expected in (("definition_id", definition_id), ("input_id", input_id)):
            if name in frame and not cast(pd.Series, frame[name]).eq(expected).all():
                raise ValueError("fixed definition/input identity differs")
    if not {"security_id", "t0", "calendar_index"}.issubset(global_values):
        raise ValueError("global values require explicit stock/calendar identity")
    if global_values.t0.tolist() != dates or global_values.calendar_index.tolist() != list(range(len(calendar))):
        raise ValueError("global values common-calendar identity differs")
    common = tables["common_values"].copy(deep=True)
    for name in global_values:
        if name.split("_", 1)[0] in {"H", "J", "K3", "MKT"} or name.startswith("PAT_other_"):
            common[name] = global_values[name]
        elif name not in {"security_id", "t0", "calendar_index", "definition_id", "input_id"}:
            raise ValueError("global values contain a non-global condition column")
    groups = groups_for_pattern(
        target,
        tables["cohort_events"],
        tables["controls"],
        tables["pattern_states"],
        tables["universe"],
        calendar,
        definition_id,
        input_id,
        security_id=security_id,
    )
    projected = project_group_outcomes(
        groups,
        tables["base_labels"],
        cast(pd.Series, tables["prices"]["quality_reason"]),
        base_label_version_id=base_label_version_id,
        base_label_manifest_sha256=base_label_manifest_sha256,
    )
    conditions = event_conditions(projected.raw_events, tables["indicators"], common, target_pattern=target, classification_cache=classification_cache)
    LOGGER.debug(
        "Bound event tables target=%s stock=%s events=%d projected=%d memberships=%d",
        target,
        security_id,
        len(projected.raw_events),
        len(projected.events),
        len(projected.group_memberships),
    )
    return EventTables(projected.events, conditions, projected.group_memberships, groups.daily_states, groups.formula_states)
