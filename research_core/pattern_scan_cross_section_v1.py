"""Validated full-pool barriers and causal recent-pattern union conditions."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core.hhhl_variants_run import cross_section as legacy_cross_section
from research_core.pattern_scan_conditions_v1 import PATTERNS

LOGGER = logging.getLogger(__name__)


def cross_section(frame: pd.DataFrame, *, expected_security_ids: Sequence[str]) -> pd.DataFrame:
    """Adapt approved H/K3/J only after verifying the declared complete pool.

    The caller declares the fixed input universe, including every padded missing
    row. This verifies completeness against that declaration, not against an
    independently discovered market universe. Calendar positions start at zero;
    neither an incomplete security slice nor a truncated calendar suffix passes.
    Legacy liquidity is an adapter alias for already liquid base eligibility.
    """
    if isinstance(expected_security_ids, str):
        raise ValueError("expected_security_ids must be an explicit sequence")
    expected = tuple(expected_security_ids)
    if (
        not expected
        or any(not isinstance(value, str) or not value.strip() or value != value.strip() for value in expected)
        or len(set(expected)) != len(expected)
    ):
        raise ValueError("expected_security_ids must be unique nonblank security identities")
    required = {"security_id", "t0", "calendar_index", "base_eligible", "ret120", "turnover20", "industry_ref", "is_cnh"}
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or not required.issubset(frame):
        raise ValueError("complete cross-sectional input columns are required")
    if frame.empty or frame.security_id.isna().any() or set(frame.security_id) != set(expected):
        raise ValueError("security pool differs from expected_security_ids")
    if not pd.api.types.is_integer_dtype(frame.calendar_index) or pd.api.types.is_bool_dtype(frame.calendar_index) or frame.calendar_index.isna().any():
        raise ValueError("calendar_index must contain integer session positions")
    if frame.duplicated(["security_id", "calendar_index"]).any():
        raise ValueError("duplicate security/session rows")
    if not frame.t0.map(lambda value: isinstance(value, str)).astype(bool).all():
        raise ValueError("t0 must contain canonical ISO dates")
    try:
        dates = pd.to_datetime(frame.t0, format="%Y-%m-%d", errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("t0 must contain canonical ISO dates") from exc
    if dates.isna().any() or not dates.dt.strftime("%Y-%m-%d").eq(frame.t0).all():
        raise ValueError("t0 must contain canonical ISO dates")
    calendar = cast(pd.DataFrame, frame[["calendar_index", "t0"]]).drop_duplicates().sort_values("calendar_index")
    if calendar.calendar_index.duplicated().any() or calendar.t0.duplicated().any():
        raise ValueError("every session requires exactly one distinct date")
    if not np.array_equal(calendar.calendar_index.to_numpy(), np.arange(len(calendar))) or not calendar.t0.is_monotonic_increasing:
        raise ValueError("common calendar must be sorted contiguous sessions starting at zero")
    counts = frame.groupby("security_id", sort=False, observed=True).size()
    if not cast(bool, counts.eq(len(calendar)).all()):
        raise ValueError("each security must retain every common-calendar row")
    for column in ("base_eligible", "is_cnh"):
        if not pd.api.types.is_bool_dtype(frame[column]) or (column == "base_eligible" and cast(bool, frame[column].isna().any())):
            raise ValueError(f"{column} must contain boolean states")
    for column in ("ret120", "turnover20"):
        if not pd.api.types.is_numeric_dtype(frame[column]) or pd.api.types.is_bool_dtype(frame[column]):
            raise ValueError(f"{column} must be numeric")
    adapted = frame.reset_index(drop=True).copy(deep=True)
    adapted["code"] = adapted["security_id"]
    adapted["Date"] = dates.to_numpy()
    adapted["legacy_liquid"] = adapted["base_eligible"].copy()
    calculated, _ = legacy_cross_section(adapted)
    result = frame.copy(deep=True)
    for column in ("H", "H_applicable", "H_unknown_reason", "K3", "K3_applicable", "K3_unknown_reason", "J", "J_unknown_reason"):
        result[column] = calculated[column].to_numpy()
    LOGGER.debug("Computed complete scan barrier securities=%d sessions=%d rows=%d", len(expected), len(calendar), len(result))
    return result


def recent_pattern_values(states: Mapping[str, NDArray[np.int8]], own_pattern: str) -> Mapping[str, NDArray[np.int8]]:
    """Return other-family PAT flags over t0 and its previous ten sessions.

    Inputs are raw union states (-1 unknown, 0 false, 1 true), not cooled event
    cohorts. Observed true absorbs unknown and early-calendar warmup; absent
    true needs eleven fully known observations before it can be false.
    """
    if own_pattern not in PATTERNS or set(states) != set(PATTERNS):
        raise ValueError("states must supply exactly the twelve approved pattern families")
    shape: tuple[int, ...] | None = None
    for pattern in PATTERNS:
        values = states[pattern]
        if not isinstance(values, np.ndarray) or values.dtype != np.int8 or values.ndim != 2 or not np.isin(values, (-1, 0, 1)).all():
            raise ValueError("pattern states require two-dimensional int8 -1/0/1 arrays")
        if shape is None:
            shape = values.shape
        elif values.shape != shape:
            raise ValueError("all pattern states must share stock/calendar shape")
    result: dict[str, NDArray[np.int8]] = {}
    for pattern in PATTERNS:
        if pattern == own_pattern:
            continue
        values = states[pattern]
        n = values.shape[1]
        cumulative_true = np.pad(np.cumsum(values == 1, axis=1, dtype=np.int64), ((0, 0), (1, 0)))
        cumulative_unknown = np.pad(np.cumsum(values == -1, axis=1, dtype=np.int64), ((0, 0), (1, 0)))
        ends = np.arange(1, n + 1)
        starts = np.maximum(0, ends - 11)
        observed_true = cumulative_true[:, ends] - cumulative_true[:, starts] > 0
        unknown = (cumulative_unknown[:, ends] - cumulative_unknown[:, starts] > 0) | (ends < 11)
        output = np.where(observed_true, 1, np.where(unknown, -1, 0)).astype(np.int8)
        result[f"PAT_other_{pattern}"] = output
    LOGGER.debug("Computed recent PAT conditions own_pattern=%s shape=%s", own_pattern, shape)
    return result
