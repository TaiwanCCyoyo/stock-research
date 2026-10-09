"""Pure frame projection of canonical retrospective opportunity intervals."""

from __future__ import annotations

import logging
import math
from bisect import bisect_left
from typing import Any

from research_core.opportunity_history_catalog import _barrier_indices, _finite, _flags

LOGGER = logging.getLogger(__name__)


class GainIndex:
    """Index continuity blockers while preserving ``gain_at`` priority.

    Store sparse blocker positions once per series, and only the earliest
    chronological blocker per queried baseline. Native run mismatches remain
    endpoint comparisons, after chronological blockers, just as in gain_at.
    """

    def __init__(self, series: dict[str, Any], dates: list[str]) -> None:
        self.series = series
        prices = series["adjusted"]
        numeric = [index for index in range(len(prices)) if _flags(series, index)]
        missing = [index for index, value in enumerate(prices) if not _finite(value) or value <= 0]
        barriers = sorted(_barrier_indices(series, dates))
        jumps = []
        if series.get("source_run_indices") is None:
            for index in range(1, len(prices)):
                current, previous = prices[index], prices[index - 1]
                if _finite(current) and _finite(previous) and current > 0 and previous > 0 and abs(math.log(current) - math.log(previous)) > math.log(1.35):
                    jumps.append(index)
        self._blockers = (
            (numeric, 0, "numeric_blocker"),
            (missing, 0, "missing_continuity"),
            (barriers, 1, "action_barrier"),
            (jumps, 1, "continuity_jump"),
        )
        self._cache: dict[int, tuple[int, str] | None] = {}

    def at(self, base: int, index: int) -> tuple[float | None, str | None]:
        prices = self.series["adjusted"]
        if base < 0 or index < base or index >= len(prices):
            return None, "outside_series"
        # Endpoints override even an earlier chronological continuity blocker.
        if not _finite(prices[base]) or not _finite(prices[index]) or prices[base] <= 0 or prices[index] <= 0:
            return None, "missing_or_invalid_endpoint"
        if base not in self._cache:
            candidates = []
            for priority, (positions, offset, reason) in enumerate(self._blockers):
                position = bisect_left(positions, base + offset)
                if position < len(positions):
                    candidates.append((positions[position], priority, reason))
            first = min(candidates) if candidates else None
            self._cache[base] = (first[0], first[2]) if first else None
        blocker = self._cache[base]
        if blocker is not None and blocker[0] <= index:
            return None, blocker[1]
        runs = self.series.get("source_run_indices")
        if runs is not None and runs[base] != runs[index]:
            return None, "continuity_jump"
        return prices[index] / prices[base] - 1, None


def build_frame(catalog: dict[str, Any], date: str) -> dict[str, Any]:
    """Project one source-calendar date without inferring membership or launches."""
    dates = catalog["dates"]
    index = dates.index(date)
    rows: list[dict[str, Any]] = []

    def day(position: int | None) -> str | None:
        return dates[position] if position is not None else None

    for code, security in catalog["securities"].items():
        if security.get("stock_opportunity_eligible") is not True:
            continue
        security_id = security["security_id"]
        interval = next(
            (row for row in catalog["intervals"].get(security_id, []) if row["start_index"] <= index < row["end_exclusive_index"]),
            None,
        )
        if interval is None:
            continue
        wave = catalog["waves"][interval["wave_id"]]
        series = catalog["series"][code]
        if wave["security_id"] != security_id or interval["series_id"] != series["series_id"]:
            raise ValueError("interval/wave/series identity mismatch")
        gain, reason = catalog["gains"][code].at(interval["gain_base_index"], index)
        peak_gain, _ = catalog["gains"][code].at(wave["start"], wave["peak"])
        classification = catalog["classifications"].get(code) or {}
        snapshot = classification.get("official_industry_snapshot") or {}
        label = snapshot.get("label")
        industry = {
            "id": label if label else "unknown",
            "label": label if label else "分類待補",
            "basis": "current-snapshot" if label else "unknown",
            "snapshotAt": snapshot.get("fetched_at") if label else None,
        }
        rows.append({
            "securityId": security_id,
            "code": code,
            "name": security.get("name") or code,
            "seriesId": series["series_id"],
            "waveId": wave["id"],
            "start": day(wave["start"]),
            "peakDate": day(wave["peak"]),
            "endConfirmedAt": day(wave["end"]),
            "observedThrough": day(wave["observedThrough"]),
            "leftCensored": wave["leftCensored"],
            "rightCensored": wave["rightCensored"],
            "scale": wave["scale"],
            "gain": gain * 100 if gain is not None else None,
            "peakGain": peak_gain * 100 if peak_gain is not None else None,
            "raw": series["raw"][index],
            "adjusted": series["adjusted"][index],
            "reason": reason,
            "industry": industry,
            "earliestCandidateId": interval["earliest_candidate_id"],
            "phase": None,
        })
    from research_core.opportunity_history_display import augment_frame_row

    for row in rows:
        augment_frame_row(catalog, row, index)
    LOGGER.debug("Projected catalog %s at %s: %d rows", catalog["id"], date, len(rows))
    return {"schema": "opportunity-history-web.v1", "catalogId": catalog["id"], "date": date, "rows": rows}
