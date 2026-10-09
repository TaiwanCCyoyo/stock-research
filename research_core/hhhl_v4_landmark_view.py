"""Explicit coordinate-only correction view for preserved HHHL v4 landmarks."""

from __future__ import annotations

from typing import cast

import pandas as pd

from research_core.hhhl_probability import OUTCOME_COLUMNS

VIEW_VERSION = "hhhl-v4-observed-landmark-coordinates.v1"
AUDIT_LANDMARK_COLUMNS = (
    "event_id",
    "security_id",
    "base_eligible",
    "anchor_date",
    "breakout_date",
    "year",
    "landmark",
    "status",
    "reason",
    "group",
    "rise_bin",
    "rise_ratio",
    "cross_old",
    "cross_recent_far",
    "first_cross_old_index",
    "first_cross_recent_far_index",
    "landmark_date",
    "landmark_index",
    "Z2",
    "target_close",
    "deadline_index",
    "first_cross_old_date",
    "first_cross_recent_far_date",
    "wait_from_landmark",
    *[c for c in OUTCOME_COLUMNS if c.endswith("_126")],
)


def attach_l20_audit(sample: pd.DataFrame, landmarks: pd.DataFrame) -> pd.DataFrame:
    """Join saved L20 fields onto the same deterministic event sample, without relabeling."""
    event_ids = cast(pd.Series, sample["event_id"])
    if len(sample) > 10 or event_ids.isna().any() or event_ids.duplicated().any():
        raise ValueError("audit sample must contain at most ten unique event IDs")
    if not cast(pd.Series, sample["pattern"]).eq(True).all() or not cast(pd.Series, sample["base_eligible"]).eq(True).all():
        raise ValueError("audit sample must contain eligible true events")
    if any(str(column).startswith("l20_") for column in sample.columns):
        raise ValueError("audit sample already contains L20 fields")
    selected = landmarks.loc[landmarks["landmark"].eq(20) & landmarks["event_id"].isin(sample["event_id"]), list(AUDIT_LANDMARK_COLUMNS)]
    if len(selected) != len(sample) or selected["event_id"].duplicated().any():
        raise ValueError("each audit event requires exactly one saved L20 row")
    view = observed_landmark_coordinates(selected)
    joined = sample.merge(view.add_prefix("l20_").rename(columns={"l20_event_id": "event_id"}), on="event_id", how="left", validate="one_to_one", sort=False)
    for column in ("security_id", "base_eligible", "breakout_date", "year", "Z2"):
        if not cast(pd.Series, joined[column]).eq(cast(pd.Series, joined[f"l20_{column}"])).all():
            raise ValueError(f"audit event and L20 disagree on {column}")
    joined.attrs.update(view.attrs)
    return joined


def observed_landmark_coordinates(frame: pd.DataFrame) -> pd.DataFrame:
    """A null landmark date has no observable baseline index; never mutate input.

    The original run accidentally stored planned indices for censored dates.
    This explicit view changes coordinates only, never status, reason or outcomes.
    """
    if not {"landmark_date", "landmark_index"}.issubset(frame.columns):
        raise ValueError("landmark coordinate view requires date and index columns")
    unobserved = frame["landmark_date"].isna()
    changed = int((unobserved & frame["landmark_index"].notna()).sum())
    view = frame.copy()
    view.loc[unobserved, "landmark_index"] = None
    view["landmark_index"] = view["landmark_index"].astype("Int64")
    view.attrs.update({"coordinate_view_version": VIEW_VERSION, "censored_indices_nullified": changed})
    return view
