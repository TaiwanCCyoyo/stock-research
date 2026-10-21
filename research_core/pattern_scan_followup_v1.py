"""Pure per-event path and failure observations over pinned calendar inputs."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from numbers import Integral
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_observations import classify_window, flag_history
from research_core.pattern_scan_events_v1 import describe_price_path
from research_core.pattern_scan_flags_v1 import FLAG_IDS, event_flag_observations, event_flags

LOGGER = logging.getLogger(__name__)
COMMON_COLUMNS = (
    "security_id",
    "event_id",
    "t0",
    "calendar_index",
    "horizon",
    "pattern_id",
    "subtype_id",
    "cohort_id",
    "base_label",
    "effective_label",
    "calendar_full",
    "base_main_eligible",
    "event_main_eligible",
    "event_eligibility_excluded",
    "base_label_version_id",
    "base_label_manifest_sha256",
    "detection_quality_reasons_json",
    "result_quality_reasons_json",
    "event_eligibility_reasons_json",
    "effective_unknown_reasons_json",
)
PATH_COLUMNS = COMMON_COLUMNS + (
    "path_category",
    "path_reason",
    "max_return",
    "min_return",
    "peak_offset",
    "first_minus_10_offset",
    "first_plus_10_offset",
    "base_first_hit_offset",
    "first_lower_high_json",
    "first_observed_lower_high_json",
    "information_scope",
)
OBSERVATION_COLUMNS = COMMON_COLUMNS + (
    "landmark",
    "scope",
    "flag_id",
    "flag_state",
    "first_trigger_offset",
    "unknown_reason",
    "through_offset",
    "trigger_return",
    "raw_flag_state",
    "raw_first_trigger_offset",
    "raw_unknown_reason",
    "riskset_id",
    "riskset_state",
    "riskset_reason",
    "riskset_decision_offset",
    "riskset_eligible",
    "rise_ratio",
    "rise_bin",
    "clock_label",
    "clock_calendar_full",
    "clock_first_hit_offset",
    "outcome_unknown_reason",
)
FIRST_FIELDS = (
    "state",
    "unknown_reason",
    "offset",
    "flag_id",
    "flag_id_certain",
    "all_flag_ids_json",
    "same_day_unknown_flag_ids_json",
    "first_observed_offset",
    "first_observed_flag_id",
    "all_first_observed_flag_ids_json",
)
FIRST_COLUMNS = COMMON_COLUMNS + tuple(f"{prefix}_{field}" for prefix in ("first_flag", "before_hit_first_flag") for field in FIRST_FIELDS)


@dataclass(frozen=True)
class FollowupTables:
    paths: pd.DataFrame
    flags: pd.DataFrame
    landmarks: pd.DataFrame
    first_flags: pd.DataFrame


def _positive(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _optional(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _first(daily: pd.DataFrame, horizon: int, *, first_hit: int | None = None) -> dict[str, Any]:
    flags: list[bool | None] = [None]
    true_ids: dict[int, list[str]] = {}
    unknown_ids: dict[int, list[str]] = {}
    for offset, supplied in enumerate(daily.itertuples(index=False, name=None), 1):
        row = dict(zip(FLAG_IDS, supplied, strict=True))
        true_ids[offset] = sorted(name for name, value in row.items() if not pd.isna(value) and bool(value))
        unknown_ids[offset] = sorted(name for name, value in row.items() if pd.isna(value))
        flags.append(True if true_ids[offset] else None if unknown_ids[offset] else False)
    history = flag_history(flags, horizon, first_hit)
    cutoff = history.through_offset
    observed = next((offset for offset in range(1, min(len(flags) - 1, cutoff) + 1) if true_ids[offset]), None)
    selected_offset = history.first_trigger_offset
    ties = true_ids.get(selected_offset, []) if selected_offset is not None else []
    unknown = unknown_ids.get(selected_offset, []) if selected_offset is not None else []
    identity_certain = bool(ties) and not any(name < ties[0] for name in unknown)
    observed_ties = true_ids.get(observed, []) if observed is not None else []
    return {
        "state": history.state,
        "unknown_reason": history.reason,
        "offset": selected_offset,
        "flag_id": ties[0] if identity_certain else None,
        "flag_id_certain": identity_certain,
        "all_flag_ids_json": _json(ties),
        "same_day_unknown_flag_ids_json": _json(unknown),
        "first_observed_offset": observed,
        "first_observed_flag_id": observed_ties[0] if observed_ties else None,
        "all_first_observed_flag_ids_json": _json(observed_ties),
    }


def followup_values(
    events: pd.DataFrame,
    frame: pd.DataFrame,
    pivots: pd.DataFrame,
    *,
    horizons: Sequence[int] = (126, 252),
    landmarks: Sequence[int] = (5, 10, 20, 40),
) -> FollowupTables:
    """Observe supplied event/horizon overlays without inventing populations.

    One stock uses its complete common calendar and prepared indicators. Event
    rows supply immutable base labels and their own effective labels/eligibility;
    a mismatching base clock fails closed. Missing full price paths produce an
    unknown path diagnostic, without relabelling base or effective outcomes.
    Raw flag clocks ignore price-quality exclusions; eligibility and quality
    reasons remain beside each diagnostic. NEW landmark risksets do not exclude
    support breaks, and each endpoint remains t0+H rather than L+H.
    """
    required = {
        "security_id",
        "event_id",
        "t0",
        "calendar_index",
        "horizon",
        "base_label",
        "effective_label",
        "calendar_full",
        "event_main_eligible",
        "event_eligibility_excluded",
    }
    if not events.columns.is_unique or not required.issubset(events.columns):
        raise ValueError("events require unique canonical event/overlay columns")
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is not None
        or frame.index.hasnans
        or not frame.index.is_unique
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("frame requires the sorted unique naive common calendar")
    if any(day != day.normalize() for day in frame.index) or not frame.columns.is_unique or not {"Close", "SMA20", "SMA60", "BBLower"}.issubset(frame.columns):
        raise ValueError("frame requires midnight dates and prepared indicator columns")
    requested = tuple(_positive(value, "horizon") for value in horizons)
    landmark_values = tuple(_positive(value, "landmark") for value in landmarks)
    if not requested or len(set(requested)) != len(requested) or len(set(landmark_values)) != len(landmark_values):
        raise ValueError("horizons must be nonempty unique and landmarks unique")
    if len(set(events["security_id"])) > 1 or bool(events.duplicated(["event_id", "horizon"]).any()):
        raise ValueError("followup requires one stock and unique event/horizon rows")
    paths: list[dict[str, Any]] = []
    full_flags: list[dict[str, Any]] = []
    landmark_flags: list[dict[str, Any]] = []
    first_flags: list[dict[str, Any]] = []
    closes = cast(pd.Series, frame["Close"]).to_numpy(dtype=float, na_value=np.nan).tolist()
    for supplied in events.to_dict(orient="records"):
        row = cast(dict[str, Any], supplied)
        horizon = _positive(row["horizon"], "event horizon")
        if horizon not in requested:
            continue
        t0 = _positive(row["calendar_index"], "calendar_index", minimum=0)
        if t0 >= len(frame) or row["t0"] != cast(pd.Timestamp, frame.index[t0]).date().isoformat():
            raise ValueError("event t0 must match the supplied calendar position")
        if any(not isinstance(row[name], str) or not row[name].strip() for name in ("security_id", "event_id")):
            raise ValueError("event and security identities must be nonblank strings")
        for name in ("calendar_full", "event_main_eligible", "event_eligibility_excluded"):
            if not isinstance(row[name], (bool, np.bool_)):
                raise ValueError(f"{name} must be boolean")
        if row["base_label"] not in {"hit", "loss", "flat-win", "unknown"} or row["effective_label"] not in {"hit", "loss", "flat-win", "unknown"}:
            raise ValueError("invalid base/effective label")
        if row["event_main_eligible"] and (not row["calendar_full"] or row["effective_label"] == "unknown" or row["event_eligibility_excluded"]):
            raise ValueError("event eligibility contradicts the effective population")
        clock = classify_window(closes[t0:], horizon)
        if row["base_label"] != clock.outcome or row["calendar_full"] != clock.calendar_full:
            raise ValueError("base label or calendar fullness differs from the pinned price clock")
        if "base_first_hit_offset" in row:
            supplied_hit = None if pd.isna(row["base_first_hit_offset"]) else _positive(row["base_first_hit_offset"], "base_first_hit_offset")
            if supplied_hit != clock.first_hit_offset:
                raise ValueError("base first-hit offset differs from the pinned price clock")
        common = {name: row.get(name) for name in COMMON_COLUMNS}
        for name in COMMON_COLUMNS:
            if name.endswith("_reasons_json") and common[name] is None:
                common[name] = "[]"
        common["base_main_eligible"] = row.get("base_main_eligible", clock.main_eligible)
        path = describe_price_path(closes, t0, horizon=horizon)
        stop = min(len(frame), t0 + horizon + 1)
        bounded = frame.iloc[:stop]
        bounded_pivots = pivots.loc[cast(pd.Series, pivots["confirmation_index"]).lt(stop)]
        levels = {name: _optional(row.get(name)) for name in ("support", "lower", "confirmed_support")}
        daily = event_flags(bounded, bounded_pivots, t0, **levels)
        paths.append({
            **common,
            **{f"path_{key}" if key in {"category", "reason"} else key: value for key, value in asdict(path).items()},
            "base_first_hit_offset": clock.first_hit_offset,
            "first_lower_high_json": _json(daily.attrs["first_lower_high"]),
            "first_observed_lower_high_json": _json(daily.attrs["first_observed_lower_high"]),
            "information_scope": "retrospective_path_diagnostic",
        })
        first = {**common}
        for prefix, hit in (("first_flag", None), ("before_hit_first_flag", clock.first_hit_offset)):
            first.update({f"{prefix}_{key}": value for key, value in _first(daily, horizon, first_hit=hit).items()})
        first_flags.append(first)
        observations = event_flag_observations(bounded, bounded_pivots, t0, horizons=(horizon,), landmarks=landmark_values, **levels)
        for supplied_observation in observations.to_dict(orient="records"):
            observation = cast(dict[str, Any], supplied_observation)
            for original, renamed in (("label", "clock_label"), ("calendar_full", "clock_calendar_full"), ("first_hit_offset", "clock_first_hit_offset")):
                observation[renamed] = observation.pop(original)
            target = full_flags if observation["scope"] == "full" else landmark_flags
            target.append({**observation, **common})
    LOGGER.debug("Followup paths=%d full_flags=%d landmarks=%d", len(paths), len(full_flags), len(landmark_flags))
    return FollowupTables(
        pd.DataFrame(paths, columns=pd.Index(PATH_COLUMNS)),
        pd.DataFrame(full_flags, columns=pd.Index(OBSERVATION_COLUMNS)),
        pd.DataFrame(landmark_flags, columns=pd.Index(OBSERVATION_COLUMNS)),
        pd.DataFrame(first_flags, columns=pd.Index(FIRST_COLUMNS)),
    )
