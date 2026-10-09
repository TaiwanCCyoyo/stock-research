"""Fixed descriptive summaries for the HHHL v4 probability study."""

from __future__ import annotations

from collections import Counter
from typing import Any, cast

import pandas as pd

from research_core.hhhl_probability import describe, first_per_security, quantile

HORIZONS = (63, 126)
BASES = ("adjusted_reference_factor", "atlas_original")
OUTCOME_FIELDS = (
    "label",
    "complete",
    "unknown_reason",
    "max_return",
    "min_return",
    "max_drawdown",
    "forward_return",
    "wait_to_threshold",
)
EVENT_FAMILIES = (
    "E-all",
    "E-clean",
    "E-overhead",
    "E-overhead-old-only",
    "E-overhead-recent-far-only",
    "E-overhead-both",
    "X-inside",
)
LANDMARKS = (10, 20, 40)
RISE_BINS = ("lt1", "b1_1p10", "b1p10_1p25", "ge1p25")
LANDMARK_GROUPS = (
    "cross_old_only",
    "cross_recent_far_only",
    "cross_both",
    "uncrossed_overhead",
    "clean_reference",
)
_CROSS_GROUPS = frozenset(LANDMARK_GROUPS[:3])
_MISSING = "(missing)"

_COMMON_COLUMNS = ("security_id", "base_eligible", "anchor_date", "breakout_date", "year")
_EVENT_COLUMNS = ("pattern", "scale", "cat", "limit_up", "has_old", "has_recent_far")


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], name: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(missing)}")


def _basis_prefix(basis: str) -> str:
    if basis == "adjusted_reference_factor":
        return "adjusted"
    if basis == "atlas_original":
        return "atlas"
    raise ValueError(f"unsupported outcome basis: {basis}")


def _outcome_columns(horizon: int, basis: str, *, landmark: bool = False) -> tuple[str, ...]:
    if landmark:
        prefix = ""
    else:
        prefix = f"{_basis_prefix(basis)}_"
    return tuple(f"{prefix}{field}_{horizon}" for field in OUTCOME_FIELDS)


def _project_outcomes(frame: pd.DataFrame, horizon: int, basis: str, *, landmark: bool = False) -> pd.DataFrame:
    """Map one immutable outcome basis to the legacy describe() column contract."""
    columns = list(_COMMON_COLUMNS)
    source_columns = dict(zip(OUTCOME_FIELDS, _outcome_columns(horizon, basis, landmark=landmark), strict=True))
    _require_columns(frame, tuple(source_columns.values()), "outcome frame")

    projected = frame.loc[:, columns].copy()
    for field, source in source_columns.items():
        projected[f"{field}_{horizon}"] = frame[source].to_numpy(copy=True)
    return projected


def _missing_key(value: Any) -> str:
    return _MISSING if pd.isna(value) else str(value)


def _describe_v4(frame: pd.DataFrame, horizon: int, basis: str, *, landmark: bool = False) -> dict[str, Any]:
    projected = _project_outcomes(frame, horizon, basis, landmark=landmark)
    summary = describe(projected, horizon)
    eligible = projected.loc[projected["base_eligible"].eq(True).fillna(False)]
    labels = eligible[f"label_{horizon}"]
    winners = eligible.loc[labels.eq(1).fillna(False)]
    wait = winners[f"wait_to_threshold_{horizon}"]

    reason_column = f"unknown_reason_{horizon}"
    unknown_reasons = Counter(_missing_key(reason) for reason in eligible.loc[labels.isna(), reason_column].tolist())
    summary.update({
        "basis": basis,
        "hit_wait_p10": quantile(wait, 0.1),
        "hit_wait_p90": quantile(wait, 0.9),
        "unknown_reasons": dict(sorted(unknown_reasons.items())),
        "small_sample": summary["known"] < 30 or summary["known_securities"] < 10,
    })
    return summary


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _comparison_fields(
    rate: float | None,
    all_day_base_rate: float | None,
    no_event_control_rate: float | None,
) -> dict[str, float | None]:
    return {
        "all_day_base_rate": all_day_base_rate,
        "no_event_control_rate": no_event_control_rate,
        "lift_all_days": _ratio(rate, all_day_base_rate),
        "lift_no_event_control": _ratio(rate, no_event_control_rate),
    }


def _event_selections(events: pd.DataFrame) -> dict[str, pd.Series]:
    pattern = events["pattern"].eq(True).fillna(False)
    old = events["has_old"].eq(True).fillna(False)
    recent_far = events["has_recent_far"].eq(True).fillna(False)
    no_old = events["has_old"].eq(False).fillna(False)
    no_recent_far = events["has_recent_far"].eq(False).fillna(False)
    any_bonus = old | recent_far
    return {
        "E-all": pattern,
        "E-clean": pattern & no_old & no_recent_far,
        "E-overhead": pattern & any_bonus,
        "E-overhead-old-only": pattern & old & no_recent_far,
        "E-overhead-recent-far-only": pattern & recent_far & no_old,
        "E-overhead-both": pattern & old & recent_far,
        "X-inside": events["pattern"].eq(False).fillna(False) & events["scale"].eq("inside_big_range").fillna(False),
    }


def _event_cells(events: pd.DataFrame) -> list[tuple[str, str, str, pd.DataFrame]]:
    cells: list[tuple[str, str, str, pd.DataFrame]] = []
    selections = _event_selections(events)
    for family in EVENT_FAMILIES:
        selected = events.loc[selections[family]]
        cells.append((family, "pooled", "all", selected))
        for category in ("hhhl", "bottom", "range"):
            cells.append((family, "cat", category, selected.loc[selected["cat"].eq(category).fillna(False)]))
        for value in (False, True):
            cells.append((family, "limit_up", str(value).lower(), selected.loc[selected["limit_up"].eq(value).fillna(False)]))
        for year in range(2019, 2027):
            cells.append((family, "year", str(year), selected.loc[selected["year"].eq(year).fillna(False)]))
    return cells


def _scoped(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "pooled":
        return frame
    return frame.loc[frame["year"].eq(int(scope)).fillna(False)]


def first_noise_per_security(noise: pd.DataFrame) -> pd.DataFrame:
    """Select each security's earliest eligible original event, not shifted noise date."""
    _require_columns(noise, _COMMON_COLUMNS, "noise")
    eligible = noise.loc[noise["base_eligible"].eq(True).fillna(False)].copy()
    if eligible.empty:
        return eligible

    row_order = "__hhhl_v4_noise_row_order__"
    while row_order in eligible.columns:
        row_order += "_"
    eligible[row_order] = range(len(eligible))
    sort_columns = ["security_id", "breakout_date"]
    if "event_id" in eligible.columns:
        sort_columns.append("event_id")
    sort_columns.append(row_order)
    selected = eligible.sort_values(sort_columns, kind="mergesort", na_position="last").drop_duplicates("security_id", keep="first")
    return selected.drop(columns=[row_order])


def _append_summary(
    output: list[dict[str, Any]],
    *,
    family: str,
    slice_name: str,
    value: str,
    sampling: str,
    horizon: int,
    basis: str,
    frame: pd.DataFrame,
    all_day_base_rate: float | None = None,
    no_event_control_rate: float | None = None,
    landmark: int | None = None,
    landmark_outcome: bool = False,
) -> dict[str, Any]:
    description = _describe_v4(frame, horizon, basis, landmark=landmark_outcome)
    record: dict[str, Any] = {
        "family": family,
        "slice": slice_name,
        "value": value,
        "sampling": sampling,
        "horizon": horizon,
        **description,
        **_comparison_fields(description["rate"], all_day_base_rate, no_event_control_rate),
    }
    if landmark is not None:
        record["landmark"] = landmark
    output.append(record)
    return record


def _landmark_column(landmarks: pd.DataFrame) -> str:
    for column in ("landmark", "landmark_days", "landmark_n", "L"):
        if column in landmarks.columns:
            return column
    raise ValueError("landmarks missing required L column (landmark, landmark_days, landmark_n, or L)")


def _landmark_selections(landmarks: pd.DataFrame) -> dict[str, pd.Series]:
    group = cast(pd.Series, landmarks["group"])
    cross_any = cast(pd.Series, group.isin(list(_CROSS_GROUPS)))
    return {
        "cross_any": cross_any,
        **{name: cast(pd.Series, group.eq(name).fillna(False)) for name in LANDMARK_GROUPS},
    }


def landmark_census(landmarks: pd.DataFrame) -> list[dict[str, Any]]:
    """Count normalized E-event landmark status/reason by L and eligibility."""
    l_column = _landmark_column(landmarks)
    _require_columns(landmarks, ("base_eligible", "status", "reason"), "landmarks")
    census: list[dict[str, Any]] = []
    for landmark in LANDMARKS:
        at_l = landmarks.loc[landmarks[l_column].eq(landmark).fillna(False)]
        for eligible, label in ((True, "eligible"), (False, "ineligible")):
            subset = at_l.loc[at_l["base_eligible"].eq(eligible).fillna(False)]
            counts = Counter(
                (_missing_key(status), _missing_key(reason)) for status, reason in zip(subset["status"].tolist(), subset["reason"].tolist(), strict=True)
            )
            for (status, reason), count in sorted(counts.items()):
                census.append({
                    "landmark": landmark,
                    "eligibility": label,
                    "status": status,
                    "reason": reason,
                    "rows": count,
                    "securities": int(
                        subset.loc[
                            subset["status"].map(_missing_key).eq(status) & subset["reason"].map(_missing_key).eq(reason),
                            "security_id",
                        ].nunique()
                    )
                    if "security_id" in subset.columns
                    else None,
                })
    return census


def summarize_v4(
    events: pd.DataFrame,
    baseline: pd.DataFrame,
    controls: pd.DataFrame,
    noise: pd.DataFrame,
    landmarks: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Build the complete fixed v4 summary grid, retaining unsupported cells."""
    for name, frame in (("events", events), ("baseline", baseline), ("controls", controls), ("noise", noise)):
        _require_columns(frame, _COMMON_COLUMNS, name)
    _require_columns(events, _EVENT_COLUMNS, "events")
    _require_columns(controls, ("control_no_event", "control_no_pattern"), "controls")
    _require_columns(landmarks, (*_COMMON_COLUMNS, "group", "rise_bin", "status", "reason"), "landmarks")
    landmark_column = _landmark_column(landmarks)

    for name, frame in (("events", events), ("baseline", baseline), ("controls", controls), ("noise", noise)):
        for basis in BASES:
            for horizon in HORIZONS:
                _require_columns(frame, _outcome_columns(horizon, basis), f"{name} outcomes")
    _require_columns(landmarks, _outcome_columns(126, "adjusted_reference_factor", landmark=True), "landmark outcomes")

    output: list[dict[str, Any]] = []
    event_cells = _event_cells(events)

    # Matched all-day and high-volume/no-event rates are calculated independently
    # for every outcome basis and time scope.
    base_rates: dict[tuple[str, str], float | None] = {}
    no_event_rates: dict[tuple[str, str], float | None] = {}
    for scope in ("pooled", *(str(year) for year in range(2019, 2027))):
        base_scope = _scoped(baseline, scope)
        control_scope = _scoped(controls, scope)
        no_event = control_scope.loc[control_scope["control_no_event"].eq(True).fillna(False)]
        no_pattern = control_scope.loc[control_scope["control_no_pattern"].eq(True).fillna(False)]
        for horizon in HORIZONS:
            for basis in BASES:
                base_description = _describe_v4(base_scope, horizon, basis)
                no_event_description = _describe_v4(no_event, horizon, basis)
                no_pattern_description = _describe_v4(no_pattern, horizon, basis)
                base_rate = base_description["rate"]
                no_event_rate = no_event_description["rate"]
                base_rates[(scope, f"{horizon}:{basis}")] = base_rate
                no_event_rates[(scope, f"{horizon}:{basis}")] = no_event_rate

                scope_slice = "pooled" if scope == "pooled" else "year"
                scope_value = "all" if scope == "pooled" else scope
                for family, description in (
                    ("all_stock_days", base_description),
                    ("high_volume_no_event", no_event_description),
                    ("high_volume_no_pattern", no_pattern_description),
                ):
                    output.append({
                        "family": family,
                        "slice": scope_slice,
                        "value": scope_value,
                        "sampling": "all_observations",
                        "horizon": horizon,
                        **description,
                        **_comparison_fields(description["rate"], base_rate, no_event_rate),
                    })

    for family, slice_name, value, group in event_cells:
        scope = value if slice_name == "year" else "pooled"
        for horizon in HORIZONS:
            for basis in BASES:
                match_key = (scope, f"{horizon}:{basis}")
                for sampling, selected in (
                    ("all_events", group),
                    ("first_per_security", first_per_security(group)),
                ):
                    _append_summary(
                        output,
                        family=family,
                        slice_name=slice_name,
                        value=value,
                        sampling=sampling,
                        horizon=horizon,
                        basis=basis,
                        frame=selected,
                        all_day_base_rate=base_rates[match_key],
                        no_event_control_rate=no_event_rates[match_key],
                    )

    for sampling, selected in (
        ("all_events", noise),
        ("first_per_security", first_noise_per_security(noise)),
    ):
        for horizon in HORIZONS:
            for basis in BASES:
                _append_summary(
                    output,
                    family="noise",
                    slice_name="pooled",
                    value="all",
                    sampling=sampling,
                    horizon=horizon,
                    basis=basis,
                    frame=selected,
                    all_day_base_rate=base_rates[("pooled", f"{horizon}:{basis}")],
                    no_event_control_rate=no_event_rates[("pooled", f"{horizon}:{basis}")],
                )

    active_landmarks = landmarks.loc[landmarks["status"].eq("active").fillna(False)]
    landmark_cells = _landmark_selections(active_landmarks)
    for family, mask in landmark_cells.items():
        family_rows = active_landmarks.loc[mask]
        for slice_name, value, cell_rows in (
            ("pooled", "all", family_rows),
            *[("rise_bin", rise_bin, family_rows.loc[family_rows["rise_bin"].eq(rise_bin).fillna(False)]) for rise_bin in RISE_BINS],
        ):
            for landmark in LANDMARKS:
                at_l = cell_rows.loc[cell_rows[landmark_column].eq(landmark).fillna(False)]
                for sampling, selected in (
                    ("all_events", at_l),
                    ("first_per_security", first_per_security(at_l)),
                ):
                    _append_summary(
                        output,
                        family=family,
                        slice_name=slice_name,
                        value=value,
                        sampling=sampling,
                        horizon=126,
                        basis="adjusted_reference_factor",
                        frame=selected,
                        landmark=landmark,
                        landmark_outcome=True,
                    )

    expected_rows = 1080
    if len(output) != expected_rows:
        raise AssertionError(f"fixed v4 summary grid produced {len(output)} rows; expected {expected_rows}")
    return output
