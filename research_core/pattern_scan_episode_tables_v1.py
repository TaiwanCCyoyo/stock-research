"""Pure Q4 admission, observed coverage, random controls and grouped tables."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from itertools import product
from numbers import Integral
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import object_digest
from research_core.hhhl_variants_selection import split_for_code
from research_core.pattern_scan_episode_coverage_v1 import observe_episode, random_matched_control
from research_core.pattern_scan_events_v1 import Episode, merge_hit_episodes
from research_core.pattern_scan_reporting_v1 import ERAS, MARKETS, SPLITS

LOGGER = logging.getLogger(__name__)
ADMISSION_COLUMNS = ("security_id", "t0", "calendar_index", "label", "calendar_full", "admitted", "exclusion_reasons")
OBSERVATION_COLUMNS = (
    "security_id",
    "group_id",
    "episode_id",
    "start_indices",
    "anchor_t0",
    "anchor_mkt",
    "episode_status",
    "episode_reason",
    "observed_coverage_status",
    "coverage_status",
    "quota_shortfall",
    "anchor_index",
    "window_start",
    "window_end",
    "window_calendar_full",
    "window_states_known",
    "matching_indices",
    "first_matching_index",
    "first_timing_certain",
    "timing_known",
    "observed_offset",
    "entry_return",
    "entry_return_known",
    "remaining_return",
    "remaining_return_known",
    "late",
    "late_known",
)


def _calendar(dates: Sequence[str], size: int) -> tuple[str, ...]:
    values = tuple(dates)
    if len(values) != size or any(not isinstance(value, str) for value in values):
        raise ValueError("calendar dates must align to closes")
    parsed = pd.DatetimeIndex(values)
    if (
        parsed.hasnans
        or parsed.tz is not None
        or not parsed.is_unique
        or not parsed.is_monotonic_increasing
        or any(day.date().isoformat() != value for day, value in zip(parsed, values, strict=True))
    ):
        raise ValueError("calendar requires sorted unique canonical ISO dates")
    return values


def _stock(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or value == "TW":
        raise ValueError("security_id requires nonblank text")


def per_stock_episodes(
    closes: Sequence[float | None], base_labels: pd.DataFrame, quality_reason: Sequence[str | None], security_id: str, *, dates: Sequence[str]
) -> tuple[tuple[Episode, ...], pd.DataFrame]:
    """Admit complete H126 base hits without result jumps, regardless of S6.

    The full result window is inspected even after an early first hit. Ordinary
    missing-price reasons do not rewrite the base hit, and an unavailable peak
    remains an unknown episode from the existing immutable builder.
    """
    _stock(security_id)
    calendar = _calendar(dates, len(closes))
    if len(quality_reason) != len(closes):
        raise ValueError("quality reasons must align to closes")
    jump = np.zeros(len(closes), dtype=bool)
    for index, reason in enumerate(quality_reason):
        if reason is not None:
            if not isinstance(reason, str):
                raise ValueError("quality reasons require text or None")
            jump[index] = bool({token.strip() for token in reason.split("|")} & {"unexplained_jump", "unexplained_adjusted_jump"})
    required = {"calendar_index", "horizon", "calendar_full"}
    if not base_labels.columns.is_unique or not required.issubset(base_labels) or not ({"label", "base_label"} & set(base_labels)):
        raise ValueError("base labels require index/horizon/full and label or base_label")
    if {"label", "base_label"}.issubset(base_labels) and not bool(base_labels.label.eq(base_labels.base_label).all()):
        raise ValueError("label and base_label disagree")
    label_column = "label" if "label" in base_labels else "base_label"
    if base_labels.duplicated(["calendar_index", "horizon"]).any():
        raise ValueError("duplicate base labels")
    admitted: list[int] = []
    records: list[dict[str, Any]] = []
    for supplied in base_labels.to_dict(orient="records"):
        row = cast(dict[str, Any], supplied)
        index, horizon = row["calendar_index"], row["horizon"]
        if isinstance(index, (bool, np.bool_)) or not isinstance(index, Integral) or not 0 <= int(index) < len(closes):
            raise ValueError("base calendar_index is invalid")
        if isinstance(horizon, (bool, np.bool_)) or not isinstance(horizon, Integral) or int(horizon) < 1:
            raise ValueError("base horizon must be a positive integer")
        index = int(index)
        if row.get("security_id", security_id) != security_id or row.get("t0", calendar[index]) != calendar[index]:
            raise ValueError("base identity does not match the stock calendar")
        label, full = row[label_column], row["calendar_full"]
        if label not in ("hit", "loss", "flat-win", "unknown") or not isinstance(full, (bool, np.bool_)):
            raise ValueError("invalid base label/full")
        if int(horizon) != 126:
            continue
        reasons: list[str] = []
        if label != "hit":
            reasons.append("base_unknown" if label == "unknown" else "base_nonhit")
        if not full or index + 126 >= len(closes):
            reasons.append("incomplete_calendar")
        if bool(jump[index + 1 : min(index + 127, len(closes))].any()):
            reasons.append("result_window_unexplained_jump")
        if not reasons:
            admitted.append(index)
        records.append({
            "security_id": security_id,
            "t0": calendar[index],
            "calendar_index": index,
            "label": label,
            "calendar_full": bool(full),
            "admitted": not reasons,
            "exclusion_reasons": tuple(reasons),
        })
    episodes = merge_hit_episodes(admitted, closes)
    LOGGER.debug("Episode admission stock=%s admitted=%d excluded=%d episodes=%d", security_id, len(admitted), len(records) - len(admitted), len(episodes))
    return episodes, pd.DataFrame(records, columns=pd.Index(ADMISSION_COLUMNS))


def admission_counts(admissions: pd.DataFrame) -> dict[str, object]:
    if not set(ADMISSION_COLUMNS).issubset(admissions):
        raise ValueError("missing admission schema")
    reasons: dict[str, int] = {}
    for values in admissions["exclusion_reasons"]:
        for reason in values:
            reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "start_n": len(admissions),
        "admitted_n": int(admissions["admitted"].astype(bool).sum()),
        "excluded_n": int((~admissions["admitted"].astype(bool)).sum()),
        "exclusion_counts": reasons,
    }


def observe_group(
    episodes: Sequence[Episode],
    closes: Sequence[float | None],
    dates: Sequence[str],
    retained_event_indices: Iterable[int],
    daily_states: Sequence[int],
    anchor_regime: Sequence[str],
    security_id: str,
    group_id: str,
) -> pd.DataFrame:
    _stock(security_id)
    calendar = _calendar(dates, len(closes))
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("group_id requires nonblank text")
    if len(anchor_regime) != len(closes) or any(not isinstance(value, str) or value not in MARKETS[1:] for value in anchor_regime):
        raise ValueError("anchor regimes must align with valid market categories")
    states = np.asarray(daily_states)
    if states.shape != (len(closes),) or not np.isin(states, (-1, 0, 1)).all():
        raise ValueError("daily states must align as -1/0/1")
    retained = tuple(retained_event_indices)
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        observed = observe_episode(episode, closes, retained, daily_states)
        anchor = episode.anchor_index
        rows.append({
            **observed,
            "security_id": security_id,
            "group_id": group_id,
            "episode_id": object_digest({"security_id": security_id, "start_indices": episode.start_indices}),
            "start_indices": episode.start_indices,
            "anchor_t0": None if anchor is None else calendar[anchor],
            "anchor_mkt": "unknown" if anchor is None else anchor_regime[anchor],
            "episode_status": episode.status,
            "episode_reason": episode.reason,
            "observed_coverage_status": observed["coverage_status"],
            "quota_shortfall": False,
        })
    return pd.DataFrame(rows, columns=pd.Index(OBSERVATION_COLUMNS))


def random_control_coverage(
    pool: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    group_id: str,
    episodes: Sequence[Episode],
    closes: Sequence[float | None],
    dates: Sequence[str],
    anchor_regime: Sequence[str],
    security_id: str,
    pool_pin: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Keep observed matches but classify a shortfall stock/year as unknown."""
    if not isinstance(pool_pin, str) or not pool_pin.strip():
        raise ValueError("random controls require explicit pool pin")
    drawn, quota = random_matched_control(pool, targets, group_id)
    own_drawn = drawn.loc[drawn.security_id.eq(security_id)]
    retained = tuple(int(value) for value in own_drawn.calendar_index)
    states = np.zeros(len(closes), dtype=np.int8)
    for index, t0 in own_drawn.loc[:, ["calendar_index", "t0"]].itertuples(index=False, name=None):
        if not 0 <= int(index) < len(closes) or dates[int(index)] != t0:
            raise ValueError("random draw does not match stock calendar")
        states[int(index)] = 1
    rows = observe_group(episodes, closes, dates, retained, states.tolist(), anchor_regime, security_id, group_id)
    shortfall_years = {int(row.year) for row in quota.loc[quota.security_id.eq(security_id) & quota.shortfall.astype(bool)].itertuples(index=False)}
    for index, row in rows.iterrows():
        t0 = row["anchor_t0"]
        if isinstance(t0, str) and int(t0[:4]) in shortfall_years:
            rows.loc[index, "coverage_status"] = "unknown"
            rows.loc[index, "quota_shortfall"] = True
    quota = quota.copy()
    quota["pool_pin"] = pool_pin
    return rows, drawn, quota


def daily_base_coverage(
    episodes: Sequence[Episode],
    closes: Sequence[float | None],
    dates: Sequence[str],
    daily_base_states: Sequence[int],
    anchor_regime: Sequence[str],
    security_id: str,
) -> pd.DataFrame:
    """Separate C-base-all diagnostic: daily true events, without cooldown."""
    retained = np.flatnonzero(np.asarray(daily_base_states) == 1).tolist()
    return observe_group(episodes, closes, dates, retained, daily_base_states, anchor_regime, security_id, "C-base-all")


def summarize_coverage(rows: pd.DataFrame) -> dict[str, int | float | None]:
    if not set(OBSERVATION_COLUMNS).issubset(rows) or not bool(rows.coverage_status.isin(("matched", "unmatched", "unknown")).all()):
        raise ValueError("invalid coverage schema/status")
    matched = int(rows.coverage_status.eq("matched").sum())
    unmatched = int(rows.coverage_status.eq("unmatched").sum())
    unknown = int(rows.coverage_status.eq("unknown").sum())
    total, known = len(rows), matched + unmatched
    result: dict[str, int | float | None] = {
        "episode_n": total,
        "distinct_stock_n": int(rows.security_id.nunique()),
        "matched_n": matched,
        "unmatched_n": unmatched,
        "unknown_n": unknown,
        "coverage_rate": matched / known if known else None,
        "coverage_lower_bound": matched / total if total else None,
        "coverage_upper_bound": (matched + unknown) / total if total else None,
        "late_known_n": int(rows.late_known.astype(bool).sum()),
        "late_n": int(rows.late.eq(True).sum()),
    }
    for value_column, known_column, name in (
        ("observed_offset", "first_timing_certain", "timing"),
        ("entry_return", "entry_return_known", "entry_return"),
        ("remaining_return", "remaining_return_known", "remaining_return"),
    ):
        values = rows.loc[rows[known_column].astype(bool), value_column].astype(float)
        if not bool(np.isfinite(values.to_numpy()).all()):
            raise ValueError("known diagnostic requires finite values")
        result[f"{name}_known_n"] = len(values)
        result[f"{name}_unknown_n"] = total - len(values)
        for quantile, suffix in ((0.25, "q25"), (0.5, "median"), (0.75, "q75")):
            result[f"{name}_{suffix}"] = float(values.quantile(quantile)) if len(values) else None
    return result


def grouped_coverage(rows: pd.DataFrame) -> Iterator[dict[str, object]]:
    """Split/era/anchor-background tables; anchor unknown only enters all era."""
    if not set(OBSERVATION_COLUMNS).issubset(rows):
        raise ValueError("missing coverage schema")
    for group_id in sorted(set(rows.group_id)):
        group = rows.loc[rows.group_id.eq(group_id)]
        splits = group.security_id.map(lambda code: split_for_code(code[3:] if code.startswith("TW:") else code[2:] if code.startswith("TW") else code))
        years = group.anchor_t0.map(lambda t0: None if t0 is None else int(t0[:4]))
        for split, era, market in product(SPLITS, ERAS, MARKETS):
            mask = pd.Series(True, index=group.index)
            if split != "all":
                mask &= splits.eq(split)
            if era != "all":
                mask &= years.between(2010, 2012) if era == "2010-2012" else years.between(2013, 2018) if era == "2013-2018" else years.ge(2019)
            if market != "all":
                mask &= group.anchor_mkt.eq(market)
            yield {"group_id": group_id, "split": split, "era": era, "mkt": market, **summarize_coverage(group.loc[mask])}
