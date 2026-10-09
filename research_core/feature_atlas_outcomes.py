"""Calendar-aligned hindsight outcomes and descriptive feature comparisons.

Close is the caller's event-factor-adjusted research price, not total return.
The caller supplies the shared exchange calendar; missing rows are never filled.
"""

from __future__ import annotations

import logging
import math
from typing import Any, cast

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
HORIZONS = (20, 63, 126)
TARGETS = {63: 1.5, 126: 2.0}


def labels(frame: pd.DataFrame) -> pd.DataFrame:
    """Return outcomes at exchange-calendar offsets, preserving the input index.

    Drawdown is a positive peak-to-trough loss fraction, including the anchor.
    Observed sessions count usable future closes, excluding the anchor. All
    primary metrics and labels are unknown unless the entire path is usable.
    An invalid observed path takes precedence over end-of-window censorship.
    """
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
        raise ValueError("frame requires a nonmissing DatetimeIndex")
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("exchange-calendar index must be unique and increasing")
    numeric_close = cast(pd.Series, pd.to_numeric(frame["Close"], errors="coerce"))
    close = numeric_close.to_numpy(dtype=float, na_value=np.nan)
    quality = frame["Quality"]
    if any(not isinstance(value, (bool, np.bool_)) for value in quality.dropna()):
        raise ValueError("Quality must contain booleans or missing values")
    valid = quality.fillna(False).to_numpy(dtype=bool) & np.isfinite(close) & (close > 0)
    result = pd.DataFrame(index=frame.index)
    for horizon in HORIZONS:
        terminal = np.full(len(frame), np.nan)
        maximum = terminal.copy()
        minimum = terminal.copy()
        drawdown = terminal.copy()
        wait = terminal.copy()
        outcome = terminal.copy()
        observed = np.zeros(len(frame), dtype=int)
        complete = np.zeros(len(frame), dtype=bool)
        reasons: list[str | None] = []
        for anchor in range(len(frame)):
            stop = min(anchor + horizon + 1, len(frame))
            path_valid = valid[anchor:stop]
            observed[anchor] = int(path_valid[1:].sum())
            if not path_valid.all():
                reasons.append("missing_or_invalid_path")
                continue
            if stop - anchor != horizon + 1:
                reasons.append("window_end")
                continue
            reasons.append(None)
            complete[anchor] = True
            path = close[anchor:stop]
            relative = path[1:] / path[0]
            terminal[anchor] = relative[-1] - 1
            maximum[anchor] = relative.max() - 1
            minimum[anchor] = relative.min() - 1
            drawdown[anchor] = np.max(1 - path / np.maximum.accumulate(path))
            if horizon in TARGETS:
                hits = np.flatnonzero(relative >= TARGETS[horizon])
                outcome[anchor] = int(bool(len(hits)))
                if len(hits):
                    wait[anchor] = int(hits[0]) + 1
        for name, values in (
            ("forward_return", terminal),
            ("max_return", maximum),
            ("min_return", minimum),
            ("max_drawdown", drawdown),
            ("observed_sessions", observed),
            ("complete", complete),
            ("unknown_reason", reasons),
        ):
            result[f"{name}_{horizon}"] = values
        if horizon in TARGETS:
            result[f"wait_to_threshold_{horizon}"] = wait
            result[f"label_{horizon}"] = outcome
        logger.debug("Outcome horizon=%d anchors=%d complete=%d", horizon, len(frame), int(complete.sum()))
    return result


def _fraction(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _json_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _comparison(group: pd.DataFrame, feature: str, label: str) -> dict[str, Any]:
    feature_known = group[feature].notna()
    label_known = group[label].notna()
    jointly_known = feature_known & label_known
    selected = group[feature].eq(1).fillna(False)
    winner = group[label].eq(1).fillna(False)
    tp = int((jointly_known & selected & winner).sum())
    fp = int((jointly_known & selected & ~winner).sum())
    fn = int((jointly_known & ~selected & winner).sum())
    tn = int((jointly_known & ~selected & ~winner).sum())
    selected_unknown = int((selected & ~label_known).sum())
    precision = _fraction(tp, tp + fp)
    base_rate = _fraction(tp + fn, tp + fp + fn + tn)
    result: dict[str, Any] = {
        "feature": feature,
        "label": label,
        "n_eligible": len(group),
        "n_feature_known": int(feature_known.sum()),
        "n_feature_missing": int((~feature_known).sum()),
        "n_label_known": int(label_known.sum()),
        "n_label_unknown": int((~label_known).sum()),
        "selected_known": tp + fp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "selected_unknown": selected_unknown,
        "winner_coverage": _fraction(tp, tp + fn),
        "nonwinner_among_selected": _fraction(fp, tp + fp),
        "precision": precision,
        "same_context_base_rate": base_rate,
        "lift": precision / base_rate if precision is not None and base_rate else None,
        "precision_lower": _fraction(tp, tp + fp + selected_unknown),
        "precision_upper": _fraction(tp + selected_unknown, tp + fp + selected_unknown),
        "descriptive_not_independent": True,
    }
    for column, output in (("security_id", "n_distinct_securities"), ("asof_date", "n_distinct_dates")):
        if column in group:
            result[output] = int(group[column].nunique(dropna=True))
    return result


def binary_comparison(
    frame: pd.DataFrame,
    feature_columns: list[str],
    context_columns: list[str],
) -> list[dict[str, Any]]:
    """Compare binary features with each label, pooled and by one context at a time.

    Confusion cells and their base rate use jointly known features and labels.
    Support and marginal known/missing counts use all base-eligible rows.
    Missing context values form their own null-valued group.
    """
    eligible = frame.loc[frame["base_eligible"].eq(True).fillna(False)]
    label_columns = ("label_63", "label_126")
    for column in [*feature_columns, *label_columns]:
        if not eligible[column].dropna().isin([0, 1]).all():
            raise ValueError(f"{column} must contain only 0, 1, or missing values")
    groups: list[tuple[str | None, Any, pd.DataFrame]] = [(None, None, eligible)]
    for context_column in context_columns:
        groups.extend((context_column, value, group) for value, group in eligible.groupby(context_column, dropna=False, sort=False, observed=True))
    output = []
    for context, value, group in groups:
        for feature in feature_columns:
            for label in label_columns:
                row = _comparison(group, feature, label)
                row.update(context_column=context, context_value=_json_scalar(value))
                output.append(row)
    logger.debug("Feature comparisons eligible=%d features=%d context_groups=%d rows=%d", len(eligible), len(feature_columns), len(groups), len(output))
    return output
