"""Immutable extension decisions and exact replay over the selected v1 API.

The frozen numerical API exposes no state checkpoint. Appending therefore
replays the complete calendar, not just new rows, then retains only new daily
rows and newly confirmed pivots. No input or previously stored bytes are edited.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable
from typing import Any

import pandas as pd

from research_core.derived_features_selective_v1 import (
    ALL_FEATURES,
    DAILY_FEATURES,
    compute_selected,
)

LOGGER = logging.getLogger(__name__)


def _equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(left, right, check_exact=True)
    except AssertionError:
        return False
    return True


def _prefix(old: pd.DataFrame, new: pd.DataFrame) -> bool:
    return len(new) >= len(old) and _equal(old, new.iloc[: len(old)])


def _requests(features: Iterable[str]) -> tuple[str, ...]:
    if isinstance(features, (str, bytes)):
        raise TypeError("features must be an iterable of names, not a string")
    names = tuple(features)
    if any(not isinstance(name, str) for name in names):
        raise TypeError("feature names must be strings")
    if len(set(names)) != len(names):
        raise ValueError("duplicate feature requests")
    unknown = set(names) - set(ALL_FEATURES)
    if unknown:
        raise ValueError(f"unknown feature requests: {sorted(unknown)}")
    return tuple(name for name in ALL_FEATURES if name in names)


def plan_extension(
    old_inputs: dict[str, pd.DataFrame],
    new_inputs: dict[str, pd.DataFrame],
    old_definition: dict[str, Any],
    new_definition: dict[str, Any],
    *,
    retrospective_tail: int = 252,
    factor_changed: Collection[str] = (),
) -> dict[str, Any]:
    """Classify each stock without computing features or mutating inputs.

    tail_start is the earliest old row to revisit for retrospective labels;
    it is not an indicator warmup or a promise of finalized future labels.
    A changed definition or historical/factor correction requires a new version.
    """
    if isinstance(retrospective_tail, bool) or not isinstance(retrospective_tail, int) or retrospective_tail < 0:
        raise ValueError("retrospective_tail must be a nonnegative integer")
    removed = set(old_inputs) - set(new_inputs)
    if removed:
        raise ValueError(f"stock deletion is not an extension: {sorted(removed)}")
    if isinstance(factor_changed, (str, bytes)):
        raise TypeError("factor_changed must be a collection of stock identifiers")
    changed_factors = set(factor_changed)
    if changed_factors - set(new_inputs):
        raise ValueError("factor_changed contains unknown stock identifiers")
    definition_changed = old_definition != new_definition
    stocks: dict[str, Any] = {}
    for code, new in new_inputs.items():
        compute_selected(new, [])
        old = old_inputs.get(code)
        old_rows = 0 if old is None else len(old)
        if old is not None:
            compute_selected(old, [])
        if definition_changed:
            action, reason = "rebuild_all_definition", "definition_changed"
        elif code in changed_factors:
            action, reason = "rebuild_stock", "factor_changed"
        elif old is None:
            action, reason = "append", "new_stock"
        elif not _prefix(old, new):
            action, reason = "rebuild_stock", "historical_calendar_or_values_changed"
        elif len(new) > old_rows:
            action, reason = "append", "strict_calendar_extension"
        else:
            action, reason = "unchanged", "exact_same_input"
        stocks[code] = {
            "action": action,
            "reason": reason,
            "old_rows": old_rows,
            "new_rows": len(new),
            "appended_rows": max(0, len(new) - old_rows),
            "tail_start": max(0, old_rows - retrospective_tail),
        }
        LOGGER.debug("Extension decision stock=%s action=%s reason=%s", code, action, reason)
    return {"definition_changed": definition_changed, "stocks": stocks}


def extend_selected(
    old_prepared: pd.DataFrame,
    new_prepared: pd.DataFrame,
    old_daily: pd.DataFrame,
    old_pivots: pd.DataFrame,
    features: Iterable[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Replay exact v1 state and append outputs, verifying old output identity.

    Verification also replays the old calendar. CPU work is not limited to the
    appended rows: state_replay_rows and verification_replay_rows report both
    calls separately. A pivot may have an old extreme and a new confirmation.
    """
    names = _requests(features)
    compute_selected(old_prepared, [])
    compute_selected(new_prepared, [])
    if not _prefix(old_prepared, new_prepared):
        raise ValueError("append requires exact historical timestamps and values")
    expected_daily, expected_pivots = compute_selected(old_prepared, names)
    if not _equal(old_daily, expected_daily) or not _equal(old_pivots, expected_pivots):
        raise ValueError("old outputs differ from the selected numerical definition")
    replay_daily, replay_pivots = compute_selected(new_prepared, names)
    old_rows = len(old_prepared)
    daily = pd.concat([old_daily, replay_daily.iloc[old_rows:]])
    new_pivots = replay_pivots.loc[replay_pivots.confirmation_index >= old_rows]
    pivots = pd.concat([old_pivots, new_pivots], ignore_index=True)
    pivots = pivots.sort_values(["k", "confirmation_index"], kind="stable").reset_index(drop=True)
    receipt = {
        "mode": "exact_state_replay",
        "state_replay_rows": len(new_prepared),
        "verification_replay_rows": old_rows,
        "appended_rows": len(new_prepared) - old_rows,
        "appended_pivots": len(new_pivots),
        "features": list(names),
    }
    LOGGER.debug("Selected extension receipt=%s", receipt)
    return daily, pivots, receipt


def add_selected(
    prepared: pd.DataFrame,
    existing_daily: pd.DataFrame,
    features: Iterable[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Compute missing columns only; preserve caller-supplied existing values.

    Existing outputs must have the selected daily schema and exact calendar.
    Their numerical provenance cannot be established without recomputation;
    callers must supply trusted outputs. No failed validation triggers repair.
    Pivot requests are computed because this API takes no existing pivot table.
    """
    names = _requests(features)
    compute_selected(prepared, [])
    if not isinstance(existing_daily, pd.DataFrame):
        raise TypeError("existing_daily must be a DataFrame")
    if not existing_daily.columns.is_unique or set(existing_daily.columns) - set(DAILY_FEATURES):
        raise ValueError("existing_daily has duplicate or unknown daily columns")
    try:
        pd.testing.assert_index_equal(existing_daily.index, prepared.index, exact=True)
    except AssertionError as error:
        raise ValueError("existing_daily calendar differs from prepared") from error
    if any(existing_daily[name].dtype != "float64" for name in existing_daily.columns):
        raise ValueError("existing_daily requires float64 selected output columns")
    reused = [name for name in names if name in existing_daily.columns]
    missing = [name for name in names if name not in existing_daily.columns]
    computed, pivots = compute_selected(prepared, missing)
    daily = existing_daily.copy(deep=True)
    for name in computed.columns:
        daily[name] = computed[name]
    daily = daily.loc[:, [name for name in DAILY_FEATURES if name in daily.columns]]
    receipt = {
        "computed_features": missing,
        "reused_features": reused,
        "reused_values_verified": False,
    }
    LOGGER.debug("Selected column addition receipt=%s", receipt)
    return daily, pivots, receipt
