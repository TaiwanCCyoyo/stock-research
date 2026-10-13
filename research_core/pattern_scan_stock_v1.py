"""One-stock causal phase; global ranks and event overlays are later barriers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_paths import outcomes_for_closes
from research_core.hhhl_variants_pattern import pattern_feature_values
from research_core.pattern_scan_cohorts_v1 import build_pattern_cohorts
from research_core.pattern_scan_controls_v1 import scan_controls
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame
from research_core.pattern_scan_inputs_v1 import daily_qualification
from research_core.patterns import b1, b2, b3, b4, h1, l1, l2, l3, p1, r1, r2, r3
from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan

LOGGER = logging.getLogger(__name__)
EVENT_COLUMNS = (
    "security_id",
    "event_id",
    "t0",
    "calendar_index",
    "pattern_id",
    "subtype_id",
    "cohort_id",
    "window_start",
    "pivot",
    "support",
    "lower",
    "member_subtype_ids",
    "member_event_ids",
    "member_metadata",
    "details_json",
    "base_eligible",
    "eligibility_reason",
    "definition_id",
    "input_id",
)


@dataclass(frozen=True)
class StockPhase:
    prices: pd.DataFrame
    indicators: pd.DataFrame
    pivots: pd.DataFrame
    common_values: pd.DataFrame
    universe: pd.DataFrame
    pattern_states: pd.DataFrame
    detector_unknowns: pd.DataFrame
    raw_events: pd.DataFrame
    cohort_events: pd.DataFrame
    controls: pd.DataFrame
    base_labels: pd.DataFrame
    h1_source_events: pd.DataFrame
    control_unknowns: pd.DataFrame
    control_pairs: pd.DataFrame


def _row(
    event: DetectorEvent,
    bars: Bars,
    security_id: str,
    definition_id: str,
    input_id: str,
    qualification: pd.DataFrame,
    *,
    cohort_id: str,
    subtype_id: str | None = None,
    members: tuple[DetectorEvent, ...] | None = None,
) -> dict[str, Any]:
    sub = event.subtype_id if subtype_id is None else subtype_id
    identity = EventIdentity(security_id, bars.dates[event.t0], event.pattern_id, sub, definition_id, input_id)
    members = (event,) if members is None else members
    member_rows = [
        {
            "subtype_id": member.subtype_id,
            "event_id": EventIdentity(security_id, bars.dates[member.t0], member.pattern_id, member.subtype_id, definition_id, input_id).event_id,
            "window_start": member.window_start,
            "pivot": member.pivot,
            "support": member.support,
            "lower": member.lower,
            "details": dict(member.details),
        }
        for member in members
    ]
    return {
        "security_id": security_id,
        "event_id": identity.event_id,
        "t0": bars.dates[event.t0],
        "calendar_index": event.t0,
        "pattern_id": event.pattern_id,
        "subtype_id": sub,
        "cohort_id": cohort_id,
        "window_start": event.window_start,
        "pivot": event.pivot,
        "support": event.support,
        "lower": event.lower,
        "details_json": json.dumps(dict(event.details), sort_keys=True),
        "member_subtype_ids": json.dumps([member.subtype_id for member in members]),
        "member_event_ids": json.dumps([row["event_id"] for row in member_rows]),
        "member_metadata": json.dumps(member_rows, sort_keys=True),
        "base_eligible": bool(qualification.base_eligible.iloc[event.t0]),
        "eligibility_reason": qualification.eligibility_reason.iloc[event.t0],
        "definition_id": definition_id,
        "input_id": input_id,
    }


def assemble_cohorts(
    scans: tuple[DetectorScan, ...], bars: Bars, security_id: str, definition_id: str, input_id: str, qualification: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All raw members, independent clocks and fixed listed-order representative.

    Single-subtype families have one union row, avoiding duplicate Q1 cohorts.
    Multi-subtype families retain each subtype plus their independent union.
    Eligibility is an overlay; it does not rewrite raw detection or its clock.
    """
    raw_rows: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    for scan in scans:
        by_subtype = {subtype: tuple(event.t0 for event in scan.events if event.subtype_id == subtype) for subtype in scan.subtype_ids}
        cohorts = build_pattern_cohorts(by_subtype)
        kept = {cohort.subtype_id: set(cohort.retained_indices) for cohort in cohorts.subtype_cohorts}
        union_kept = set(cohorts.union_indices)
        order = {subtype: i for i, subtype in enumerate(scan.subtype_ids)}
        by_day: dict[int, list[DetectorEvent]] = {}
        for event in scan.events:
            by_day.setdefault(event.t0, []).append(event)
            row = _row(event, bars, security_id, definition_id, input_id, qualification, cohort_id=event.subtype_id)
            raw_rows.append({**row, "subtype_retained": event.t0 in kept[event.subtype_id], "union_day_retained": event.t0 in union_kept})
            if len(scan.subtype_ids) > 1 and event.t0 in kept[event.subtype_id]:
                retained.append(row)
        for day in cohorts.union_indices:
            members = tuple(sorted(by_day[day], key=lambda event: order[event.subtype_id]))
            retained.append(
                _row(
                    members[0],
                    bars,
                    security_id,
                    definition_id,
                    input_id,
                    qualification,
                    cohort_id="union",
                    subtype_id="union" if len(scan.subtype_ids) > 1 else None,
                    members=members,
                )
            )
    raw = pd.DataFrame(raw_rows, columns=pd.Index((*EVENT_COLUMNS, "subtype_retained", "union_day_retained")))
    events = pd.DataFrame(retained, columns=pd.Index(EVENT_COLUMNS))
    if events["event_id"].duplicated().any():
        raise ValueError("assembled event identity collision")
    return raw, events


def h1_values(events: pd.DataFrame, indicators: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct the public formatter input from the preserved source audit."""
    calendar = cast(pd.DatetimeIndex, indicators.index)
    originals: list[dict[str, Any]] = []
    for event in events.to_dict("records"):
        source = json.loads(json.loads(event["details_json"])["source_event_json"])
        seq = [{**point, "date": cast(pd.Timestamp, calendar[int(point["i"])]).date().isoformat()} for point in source["seq"]]
        originals.append({
            "calendar_index": int(event["calendar_index"]),
            "restart_date": cast(pd.Timestamp, calendar[int(source["restart"])]).date().isoformat(),
            "Z2": event["support"],
            "hz_top": event["pivot"],
            "bonus_levels": json.dumps(source["bonus_levels"]),
            "pivot_sequence": json.dumps(seq),
            "cat": source["cat"],
            "big_hhhl": bool(source["big_hhhl"]),
            "vx": source["vx"],
            "has_old": False,
            "has_recent_far": False,
        })
    from research_core.hhhl_variants_pattern import REQUIRED_COLUMNS

    source_frame = pd.DataFrame(originals, columns=pd.Index(REQUIRED_COLUMNS), index=events.index)
    return pattern_feature_values(source_frame, calendar, indicators["Low"].to_numpy(dtype=float), indicators["Close"].to_numpy(dtype=float))


def stock_phase(prepared: pd.DataFrame, *, security_id: str, industry_ref: str, ordinary_reference: bool, definition_id: str, input_id: str) -> StockPhase:
    """Compute fixed inputs only; this phase never ranks partial stock pools."""
    if not security_id.startswith("TW:") or not security_id[3:].strip() or not isinstance(industry_ref, str):
        raise ValueError("explicit security and reference industry required")
    prepared = prepared.copy(deep=True)
    indicators, pivots = prepare_detector_frame(prepared)
    bars = Bars.from_frame(indicators)
    h1_scan, sources = h1.scan_with_sources(bars)
    scans = (h1_scan, *(module.scan(bars) for module in (b1, b2, b3, b4, r1, r2, r3, p1, l1, l2, l3)))
    qualification = daily_qualification(prepared, ordinary_reference=ordinary_reference)
    common = calculate_common_values(indicators, pivots)
    raw, events = assemble_cohorts(scans, bars, security_id, definition_id, input_id, qualification)
    control_scans = scan_controls(bars, base_eligible=qualification.base_eligible.to_numpy(dtype=bool), h1_source_events=sources, p1_events=scans[8].events)
    states = pd.DataFrame({"security_id": security_id, "t0": bars.dates, "calendar_index": np.arange(len(bars))}, index=prepared.index)
    unknowns: list[dict[str, Any]] = []
    for scan in scans:
        # A true subtype proves the union; absent true needs every subtype known.
        union = np.where((scan.states == 1).any(axis=1), 1, np.where((scan.states == -1).any(axis=1), -1, 0)).astype(np.int8)
        states[scan.pattern_id] = union
        for col, subtype in enumerate(scan.subtype_ids):
            states[f"{scan.pattern_id}:{subtype}"] = scan.states[:, col]
        unknowns.extend(
            {"pattern_id": scan.pattern_id, "subtype_id": subtype, "calendar_index": day, "reason": reason} for subtype, day, reason in scan.unknown_reasons
        )
    controls = pd.DataFrame({"security_id": security_id, "t0": bars.dates, "calendar_index": np.arange(len(bars))}, index=prepared.index)
    for control, scan in control_scans.items():
        controls[control] = scan.admitted_states
        controls[f"{control}:formula"] = scan.formula_states
        controls[f"{control}:cooled"] = np.isin(np.arange(len(bars)), scan.cooled_indices)
    source_rows = []
    for source in sources:
        clean_source = {**source, "vx": source["vx"] if np.isfinite(source["vx"]) else None}
        source_rows.append({
            "security_id": security_id,
            "calendar_index": source["t"],
            "pattern": bool(source["pattern"]),
            "source_event_json": json.dumps(clean_source, sort_keys=True, allow_nan=False),
        })
    control_unknowns = [
        {"control_id": control, "calendar_index": day, "reason": reason} for control, scan in control_scans.items() for day, reason in scan.unknown_reasons
    ]
    control_pairs = [
        {"control_id": control, "breakout_index": breakout, "confirmation_index": confirmation}
        for control, scan in control_scans.items()
        for breakout, confirmation in scan.paired_events
    ]
    labels = []
    for horizon in (126, 252):
        frame = outcomes_for_closes(indicators["Close"].to_numpy(dtype=float), horizon)
        frame.insert(0, "security_id", security_id)
        frame.insert(1, "t0", np.asarray(bars.dates, dtype=object))
        frame.insert(2, "calendar_index", np.arange(len(bars)))
        frame.insert(3, "horizon", horizon)
        labels.append(frame)
    common["security_id"], common["t0"], common["calendar_index"], common["industry_ref"] = security_id, bars.dates, np.arange(len(bars)), industry_ref
    common["base_eligible"] = qualification.base_eligible
    common["is_cnh"] = pd.array([None if value == -1 else bool(value) for value in control_scans["C-nh"].states], dtype="boolean")
    LOGGER.info(
        "Scan stock phase %s sessions=%d eligible=%d raw=%d retained=%d", security_id, len(bars), int(qualification.base_eligible.sum()), len(raw), len(events)
    )
    result = StockPhase(
        prepared,
        indicators,
        pivots,
        common,
        qualification,
        states,
        pd.DataFrame(unknowns, columns=pd.Index(["pattern_id", "subtype_id", "calendar_index", "reason"])),
        raw,
        events,
        controls,
        pd.concat(labels, ignore_index=True),
        pd.DataFrame(source_rows, columns=pd.Index(["security_id", "calendar_index", "pattern", "source_event_json"])),
        pd.DataFrame(control_unknowns, columns=pd.Index(["control_id", "calendar_index", "reason"])),
        pd.DataFrame(control_pairs, columns=pd.Index(["control_id", "breakout_index", "confirmation_index"])),
    )
    # Every reusable table carries explicit stock/session identity; the file's
    # enclosing path is supplementary provenance rather than an implicit key.
    for table in (result.prices, result.indicators, result.universe, result.pattern_states):
        table["security_id"] = security_id
        table["calendar_index"] = np.arange(len(bars))
        table["asof_date"] = np.asarray(bars.dates, dtype=object)
    for table in (result.detector_unknowns, result.control_unknowns):
        table["security_id"] = security_id
        table["asof_date"] = np.asarray(bars.dates, dtype=object)[table["calendar_index"].to_numpy(dtype=int)]
    result.pivots["security_id"] = security_id
    result.pivots["asof_date"] = result.pivots["confirmed_at"]
    result.control_pairs["security_id"] = security_id
    result.control_pairs["asof_date"] = np.asarray(bars.dates, dtype=object)[result.control_pairs["confirmation_index"].to_numpy(dtype=int)]
    return result
