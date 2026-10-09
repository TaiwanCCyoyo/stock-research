"""Pure, hindsight-only helpers for the sector-wave catalog."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from statistics import median
from typing import Any, Iterable, Sequence

DEFINITION_ID = "runaway-126-double-dd25.v1"


class SectorWaveError(ValueError):
    """A supplied catalog series or topology is malformed."""


@dataclass(frozen=True)
class CatalogBar:
    date: str
    close: float
    raw_close: float
    turnover_k_twd: float | None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.date)
        except (TypeError, ValueError) as error:
            raise SectorWaveError("bar date must be ISO calendar date") from error
        for name, value in (("close", self.close), ("raw_close", self.raw_close)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise SectorWaveError(f"{name} must be finite and positive")
        if self.turnover_k_twd is not None and (
            isinstance(self.turnover_k_twd, bool)
            or not isinstance(self.turnover_k_twd, (int, float))
            or not math.isfinite(self.turnover_k_twd)
            or self.turnover_k_twd < 0
        ):
            raise SectorWaveError("turnover_k_twd must be finite, nonnegative or null")
        if not isinstance(self.quality_flags, tuple) or any(not isinstance(flag, str) or not flag for flag in self.quality_flags):
            raise SectorWaveError("quality_flags must be a tuple of nonempty strings")


def _bars(value: Iterable[CatalogBar]) -> tuple[CatalogBar, ...]:
    bars = tuple(value)
    if any(not isinstance(bar, CatalogBar) for bar in bars):
        raise SectorWaveError("bars must contain CatalogBar values")
    dates = [bar.date for bar in bars]
    if any(left >= right for left, right in zip(dates, dates[1:])):
        raise SectorWaveError("bar dates must be strictly increasing")
    return bars


def _security_id(code: str) -> str:
    if not isinstance(code, str) or not code.strip() or code.startswith("TW:"):
        raise SectorWaveError("code must be a nonempty exchange-free code")
    return f"TW:{code}"


def _id(kind: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def _flags(bars: Sequence[CatalogBar]) -> tuple[str, ...]:
    return tuple(sorted({flag for bar in bars for flag in bar.quality_flags}))


def _peak_index(bars: Sequence[CatalogBar], start: int, stop: int) -> int:
    """Maximum close in [start, stop), retaining the earliest tied high."""
    return max(range(start, stop), key=lambda index: (bars[index].close, -index))


def _max_drawdown(bars: Sequence[CatalogBar], start: int, stop: int) -> float:
    high = bars[start].close
    drawdown = 0.0
    for bar in bars[start:stop]:
        high = max(high, bar.close)
        drawdown = max(drawdown, (high - bar.close) / high)
    return drawdown


def detect_episodes(
    code: str,
    bars: Iterable[CatalogBar],
    *,
    lookback_sessions: int = 126,
    qualifying_multiple: float = 2.0,
    closing_drawdown: float = 0.25,
) -> list[dict[str, Any]]:
    """Find non-overlapping completed or right-censored hindsight ascents."""
    security_id = _security_id(code)
    series = _bars(bars)
    if not isinstance(lookback_sessions, int) or lookback_sessions < 1 or isinstance(lookback_sessions, bool):
        raise SectorWaveError("lookback_sessions must be positive")
    if not math.isfinite(qualifying_multiple) or qualifying_multiple <= 1:
        raise SectorWaveError("qualifying_multiple must exceed one")
    if not math.isfinite(closing_drawdown) or not 0 < closing_drawdown < 1:
        raise SectorWaveError("closing_drawdown must be between zero and one")

    episodes: list[dict[str, Any]] = []
    definition_id = (
        DEFINITION_ID
        if (lookback_sessions, qualifying_multiple, closing_drawdown) == (126, 2.0, 0.25)
        else _id("runaway-custom", str(lookback_sessions), str(float(qualifying_multiple)), str(float(closing_drawdown)))
    )
    search_from = 0
    index = 0
    minima: deque[int] = deque()
    while index < len(series):
        left = max(search_from, index - lookback_sessions + 1)
        while minima and minima[0] < left:
            minima.popleft()
        while minima and series[minima[-1]].close > series[index].close:
            minima.pop()
        minima.append(index)
        trough = minima[0]
        if series[index].close < series[trough].close * qualifying_multiple:
            index += 1
            continue
        qualification = index
        endpoint = len(series) - 1
        confirmation: int | None = None
        running_peak = _peak_index(series, trough, qualification + 1)
        for current in range(qualification + 1, len(series)):
            if series[current].close > series[running_peak].close:
                running_peak = current
            if series[current].close <= series[running_peak].close * (1 - closing_drawdown):
                confirmation = current
                endpoint = current
                break
        peak = _peak_index(series, trough, (confirmation if confirmation is not None else len(series)))
        first_25 = next(
            (item for item in range(trough, endpoint + 1) if series[item].close >= series[trough].close * 1.25),
            None,
        )
        start = series[trough]
        peak_bar = series[peak]
        episode_id = _id("episode", security_id, start.date, peak_bar.date, series[qualification].date, definition_id)
        episodes.append({
            "security_id": security_id,
            "episode_id": episode_id,
            "definition_id": definition_id,
            "start_date": start.date,
            "qualification_date": series[qualification].date,
            "peak_date": peak_bar.date,
            "end_date": peak_bar.date,
            "confirmation_date": series[confirmation].date if confirmation is not None else None,
            "right_censored": confirmation is None,
            "first_25pct_date": series[first_25].date if first_25 is not None else None,
            "adjusted_start_close": float(start.close),
            "adjusted_peak_close": float(peak_bar.close),
            "raw_start_close": float(start.raw_close),
            "raw_peak_close": float(peak_bar.raw_close),
            "price_multiple": float(peak_bar.close / start.close),
            "appreciation_fraction": float(peak_bar.close / start.close - 1),
            "sessions_to_peak": peak - trough,
            "ascent_max_drawdown_fraction": float(_max_drawdown(series, trough, peak + 1)),
            "quality_flags": _flags(series[trough : endpoint + 1]),
        })
        if confirmation is None:
            break
        search_from = confirmation
        index = confirmation
        minima.clear()
    return episodes


def cluster_waves(group_id: str, episodes: Iterable[dict[str, Any]], *, onset_gap_days: int = 90) -> list[dict[str, Any]]:
    """Greedily cluster ascents whose common ascent interval remains nonempty."""
    if not isinstance(group_id, str) or not group_id:
        raise SectorWaveError("group_id must be nonempty")
    if isinstance(onset_gap_days, bool) or onset_gap_days < 0:
        raise SectorWaveError("onset_gap_days must be nonnegative")
    prepared = []
    for episode in episodes:
        if not isinstance(episode, dict):
            raise SectorWaveError("episodes must be dictionaries")
        try:
            start = date.fromisoformat(episode["start_date"])
            peak = date.fromisoformat(episode["peak_date"])
            identity = episode["episode_id"]
            security_id = episode["security_id"]
        except (KeyError, TypeError, ValueError) as error:
            raise SectorWaveError("episode has invalid identity or ascent dates") from error
        if not isinstance(identity, str) or not isinstance(security_id, str) or start > peak:
            raise SectorWaveError("episode has invalid identity or ascent dates")
        prepared.append((start, peak, identity, security_id, episode.get("first_25pct_date")))
    prepared.sort(key=lambda item: (item[0], item[2]))
    waves: list[dict[str, Any]] = []
    pending: list[tuple[date, date, str, str, Any]] = []

    def emit(members: Sequence[tuple[date, date, str, str, Any]]) -> None:
        if not members:
            return
        ids = tuple(member[2] for member in members)
        starts = [member[0] for member in members]
        peaks = [member[1] for member in members]
        milestones = sorted((date.fromisoformat(item[4]), item[3]) for item in members if isinstance(item[4], str))
        wave_id = _id("wave", group_id, *ids)
        waves.append({
            "wave_id": wave_id,
            "group_id": group_id,
            "start_date": min(starts).isoformat(),
            "end_date": max(peaks).isoformat(),
            "episode_ids": list(ids),
            "qualifying_security_ids": sorted({member[3] for member in members}),
            "earliest_qualifying_25pct": ({"security_id": milestones[0][1], "date": milestones[0][0].isoformat()} if milestones else None),
        })

    for candidate in prepared:
        if not pending:
            pending.append(candidate)
            continue
        first = pending[0][0]
        common_left = max([member[0] for member in pending] + [candidate[0]])
        common_right = min([member[1] for member in pending] + [candidate[1]])
        if candidate[0] <= first + timedelta(days=onset_gap_days) and common_left <= common_right:
            pending.append(candidate)
        else:
            emit(pending)
            pending = [candidate]
    emit(pending)
    return waves


def compare_peer(
    wave_id: str,
    security_id: str,
    bars: Iterable[CatalogBar],
    start_date: str,
    end_date: str,
    *,
    boundary_tolerance_days: int = 7,
    path_quality_flags: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Measure a peer on a wave's shared calendar window without interpolation."""
    if not isinstance(wave_id, str) or not wave_id or not isinstance(security_id, str) or not security_id:
        raise SectorWaveError("wave_id and security_id must be nonempty")
    try:
        requested_start, requested_end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError) as error:
        raise SectorWaveError("comparison boundaries must be ISO dates") from error
    if requested_start > requested_end or isinstance(boundary_tolerance_days, bool) or boundary_tolerance_days < 0:
        raise SectorWaveError("invalid comparison boundary")
    if not isinstance(path_quality_flags, tuple) or any(not isinstance(flag, str) or not flag for flag in path_quality_flags):
        raise SectorWaveError("path_quality_flags must be a tuple of nonempty strings")
    path_flags = tuple(sorted(set(path_quality_flags)))
    series = _bars(bars)
    base: dict[str, Any] = {
        "wave_id": wave_id,
        "security_id": security_id,
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "actual_start_date": None,
        "actual_end_date": None,
        "common_window_endpoint_appreciation_fraction": None,
        "common_window_peak_appreciation_fraction": None,
        "common_window_peak_date": None,
        "median_turnover_k_twd": None,
        "common_window_max_drawdown_fraction": None,
        "quality_flags": path_flags,
        "comparability_status": "unavailable",
        "null_reason": None,
    }
    if not series:
        base["null_reason"] = "no_bars"
        return base
    start_index = next((item for item, bar in enumerate(series) if date.fromisoformat(bar.date) >= requested_start), None)
    end_index = next((item for item in range(len(series) - 1, -1, -1) if date.fromisoformat(series[item].date) <= requested_end), None)
    if start_index is None or end_index is None or start_index > end_index:
        base["null_reason"] = "no_window_coverage"
        return base
    actual_start = date.fromisoformat(series[start_index].date)
    actual_end = date.fromisoformat(series[end_index].date)
    base["actual_start_date"], base["actual_end_date"] = actual_start.isoformat(), actual_end.isoformat()
    if (actual_start - requested_start).days > boundary_tolerance_days or (requested_end - actual_end).days > boundary_tolerance_days:
        base["null_reason"] = "boundary_tolerance_exceeded"
        return base
    window = series[start_index : end_index + 1]
    peak = _peak_index(window, 0, len(window))
    flags = tuple(sorted(set(_flags(window)) | set(path_flags)))
    turnovers = [bar.turnover_k_twd for bar in window if bar.turnover_k_twd is not None]
    base.update({
        "common_window_endpoint_appreciation_fraction": float(window[-1].close / window[0].close - 1),
        "common_window_peak_appreciation_fraction": float(window[peak].close / window[0].close - 1),
        "common_window_peak_date": window[peak].date,
        "median_turnover_k_twd": float(median(turnovers)) if turnovers else None,
        "common_window_max_drawdown_fraction": float(_max_drawdown(window, 0, len(window))),
        "quality_flags": flags,
        "comparability_status": "quarantined" if flags else "comparable",
    })
    return base


def select_wave_winner(peers: Iterable[dict[str, Any]]) -> str | None:
    """Return the valid peer with greatest shared-window peak appreciation."""
    eligible = []
    for peer in peers:
        if not isinstance(peer, dict):
            raise SectorWaveError("peers must be dictionaries")
        value = peer.get("common_window_peak_appreciation_fraction")
        security_id = peer.get("security_id")
        if peer.get("comparability_status") != "comparable" or peer.get("quality_flags") or not isinstance(security_id, str):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        eligible.append((float(value), security_id))
    return min(eligible, key=lambda item: (-item[0], item[1]))[1] if eligible else None
