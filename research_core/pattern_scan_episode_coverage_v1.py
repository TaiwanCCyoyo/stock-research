"""Episode observations and reproducible full-period matched random controls."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import date
from numbers import Integral, Real

import numpy as np
import pandas as pd

from research_core.artifact_store import object_digest
from research_core.pattern_scan_events_v1 import Episode

LOGGER = logging.getLogger(__name__)
CONTROL_COLUMNS = ("security_id", "calendar_index", "t0")
QUOTA_COLUMNS = ("security_id", "year", "quota_n", "available_n", "drawn_n", "shortfall_n", "shortfall", "coverage_status", "seed", "pool_digest")


def _index(value: object, length: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError("indices must be integers in the supplied calendar")
    index = int(value)
    if not 0 <= index < length:
        raise ValueError("indices must be integers in the supplied calendar")
    return index


def _price(closes: Sequence[float | None], index: int | None) -> float | None:
    if index is None:
        return None
    value = closes[index]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("closes require real prices or None")
    return float(value) if np.isfinite(value) and value > 0 else None


def observe_episode(
    episode: Episode,
    closes: Sequence[float | None],
    retained_event_indices: Iterable[int],
    raw_daily_states: Sequence[int],
    *,
    candidate_daily_states: Sequence[int] | None = None,
) -> dict[str, object]:
    """Observe one stock/cohort; optional candidate states intersect raw states.

    The caller supplies retained candidates for this exact intersection. Missing
    edges and unknown states cannot erase an observed match. Timing certainty and
    price/peak availability are separate from the coverage classification.
    """
    raw = np.asarray(raw_daily_states)
    if raw.shape != (len(closes),) or not np.isin(raw, (-1, 0, 1)).all():
        raise ValueError("daily states require one -1/0/1 per calendar session")
    states = raw
    if candidate_daily_states is not None:
        candidate = np.asarray(candidate_daily_states)
        if candidate.shape != raw.shape or not np.isin(candidate, (-1, 0, 1)).all():
            raise ValueError("candidate daily states must align to raw states")
        states = np.where((raw == 0) | (candidate == 0), 0, np.where((raw == 1) & (candidate == 1), 1, -1))
    retained = tuple(sorted({_index(value, len(closes)) for value in retained_event_indices}))
    if any(states[index] != 1 for index in retained):
        raise ValueError("retained events require confirmed true combined states")
    anchor = None if episode.anchor_index is None else _index(episode.anchor_index, len(closes))
    peak = None if episode.peak_index is None else _index(episode.peak_index, len(closes))
    matches: tuple[int, ...] = () if anchor is None else tuple(index for index in retained if anchor - 20 <= index <= anchor + 40)
    complete = anchor is not None and anchor >= 20 and anchor + 40 < len(closes)
    window_known = bool(complete and np.all(states[anchor - 20 : anchor + 41] != -1)) if anchor is not None else False
    first = matches[0] if matches else None
    certain = bool(first is not None and anchor is not None and anchor >= 20 and np.all(states[anchor - 20 : first] != -1))
    anchor_price, first_price, peak_price = _price(closes, anchor), _price(closes, first), _price(closes, peak)
    status = "matched" if matches else "unmatched" if window_known else "unknown"
    result: dict[str, object] = {
        "coverage_status": status,
        "anchor_index": anchor,
        "window_start": None if anchor is None else anchor - 20,
        "window_end": None if anchor is None else anchor + 40,
        "window_calendar_full": complete,
        "window_states_known": window_known,
        "matching_indices": matches,
        "first_matching_index": first,
        "first_timing_certain": certain,
        "timing_known": certain,
        "observed_offset": None if first is None or anchor is None else first - anchor,
        "entry_return": None if anchor_price is None or first_price is None else first_price / anchor_price - 1,
        "entry_return_known": anchor_price is not None and first_price is not None,
        "remaining_return": None if peak_price is None or first_price is None else peak_price / first_price - 1,
        "remaining_return_known": peak_price is not None and first_price is not None,
        "late": None if peak is None or first is None else peak < first,
        "late_known": peak is not None and first is not None,
    }
    LOGGER.debug("Episode anchor=%s coverage=%s matches=%d timing_certain=%s", anchor, status, len(matches), certain)
    return result


def _control_rows(frame: pd.DataFrame, *, cooled: bool) -> pd.DataFrame:
    if not frame.columns.is_unique or not set(CONTROL_COLUMNS).issubset(frame.columns):
        raise ValueError("control rows require security_id/calendar_index/t0")
    selected = frame.loc[:, list(CONTROL_COLUMNS)].copy()
    for value in selected["security_id"]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("security_id must remain a nonblank string")
    for value in selected["calendar_index"]:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 0:
            raise ValueError("calendar_index requires nonnegative integers")
    for value in selected["t0"]:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("t0 requires canonical ISO dates")
    if selected.duplicated(["security_id", "calendar_index"]).any() or selected.duplicated(["security_id", "t0"]).any():
        raise ValueError("duplicate control identities")
    selected = selected.sort_values(["security_id", "calendar_index", "t0"], kind="stable").reset_index(drop=True)
    for _, group in selected.groupby("security_id", sort=False):
        if not group["t0"].is_monotonic_increasing:
            raise ValueError("dates must agree with calendar order")
        if cooled and group["calendar_index"].diff().dropna().le(20).any():
            raise ValueError("pool must already be cooled with differences >20")
    selected["year"] = selected["t0"].map(lambda value: date.fromisoformat(value).year)
    return selected


def random_matched_control(pool: pd.DataFrame, targets: pd.DataFrame, group_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Draw without replacement from the caller's full-period cooled pool.

    Each group/stock/year has an independent digest-derived seed. Outcomes and
    episode windows are never read. Shortfalls remain in their original stratum.
    """
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("group_id requires a nonblank string")
    available = _control_rows(pool, cooled=True)
    requested = _control_rows(targets, cooled=False)
    keys = sorted(set(zip(available["security_id"], available["year"], strict=True)) | set(zip(requested["security_id"], requested["year"], strict=True)))
    draws: list[pd.DataFrame] = []
    quotas: list[dict[str, object]] = []
    for stock, year in keys:
        stock_pool = available.loc[available["security_id"].eq(stock) & available["year"].eq(year)]
        quota = int((requested["security_id"].eq(stock) & requested["year"].eq(year)).sum())
        drawn = min(quota, len(stock_pool))
        seed = int(object_digest({"seed": 20261013, "group_id": group_id, "security_id": stock, "year": int(year)})[:16], 16)
        positions = np.random.default_rng(seed).choice(len(stock_pool), size=drawn, replace=False)
        draws.append(stock_pool.iloc[np.sort(positions)].loc[:, list(CONTROL_COLUMNS)])
        records = [
            {"security_id": str(row.security_id), "calendar_index": int(row.calendar_index), "t0": str(row.t0)} for row in stock_pool.itertuples(index=False)
        ]
        quotas.append({
            "security_id": stock,
            "year": int(year),
            "quota_n": quota,
            "available_n": len(stock_pool),
            "drawn_n": drawn,
            "shortfall_n": quota - drawn,
            "shortfall": drawn < quota,
            "coverage_status": "unknown" if drawn < quota else "known",
            "seed": str(seed),
            "pool_digest": object_digest(records),
        })
    drawn_frame = pd.concat(draws, ignore_index=True) if draws else available.loc[:, list(CONTROL_COLUMNS)].iloc[:0]
    drawn_frame = drawn_frame.sort_values(["security_id", "calendar_index", "t0"], kind="stable").reset_index(drop=True)
    quota_frame = pd.DataFrame(quotas, columns=pd.Index(QUOTA_COLUMNS))
    LOGGER.debug("Matched random control group=%s drawn=%d strata=%d", group_id, len(drawn_frame), len(quotas))
    return drawn_frame, quota_frame
