"""Canonical candle flags plus approved decline gates and next-day confirmation."""

from __future__ import annotations

import json

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan


def scan(bars: Bars) -> DetectorScan:
    subtypes = ("R2a", "R2b", "R2c", "R2d", "R2e")
    states = np.zeros((len(bars), 5), dtype=np.int8)
    events: dict[tuple[int, int], DetectorEvent] = {}
    reasons: list[tuple[str, int, str]] = []
    close, high, low, ma = (bars.values(name) for name in ("Close", "High", "Low", "SMA20"))
    flags = [bars.values(name) for name in ("F22", "F23", "F24", "F25")]
    for day in range(len(bars)):
        for col, flag in enumerate(flags):
            start = day - 60
            # The canonical flag already includes candle geometry and its MA20
            # precondition. A known false flag rules out this AND candidate;
            # unused decline/support history must not turn it into unknown.
            if flag[day] == 0:
                continue
            if np.isfinite(flag[day]) and flag[day] != 1:
                raise ValueError("canonical candle flags must be 0, 1, or NaN")
            decline = bool(close[day - 1] <= close[day - 21] * 0.9) if bars.complete(day - 21, day - 1) else None
            below_ma = bool(close[day - 1] < ma[day - 1]) if bars.complete(day - 1, day - 1) and np.isfinite(ma[day - 1]) else None
            if decline is False or below_ma is False:
                continue
            if not bars.complete(start, day):
                states[day, col] = -1
                continue
            pattern_start = day if col == 3 else day - 1
            lower = float(low[pattern_start : day + 1].min())
            prior_low = float(low[start:day].min())
            if lower > prior_low * 1.03:
                continue
            if decline is None or below_ma is None or not np.isfinite(flag[day]):
                states[day, col] = -1
                continue
            if flag[day] == 1:
                states[day, col] = 1
                events[day, col] = DetectorEvent(
                    "R2",
                    subtypes[col],
                    day,
                    start,
                    float(high[pattern_start : day + 1].max()),
                    lower,
                    lower,
                    (("pattern_start", pattern_start), ("pattern_end", day), ("flag_id", f"F{22 + col}"), ("confirmation_index", day)),
                )
        if day > 0 and np.all(states[day - 1, :4] == 0):
            states[day, 4] = 0
        elif day == 0 or not bars.complete(day - 1, day):
            states[day, 4] = -1
        else:
            # A known positive absorbs other unknown alternatives. Fixed subtype
            # order chooses metadata only; all original subtype events survive.
            states[day, 4] = -1 if np.any(states[day - 1, :4] == -1) else 0
            matches: list[DetectorEvent] = []
            for col in range(4):
                original = events.get((day - 1, col))
                if original is not None and original.pivot is not None and close[day] > original.pivot:
                    matches.append(original)
            if matches:
                original = matches[0]
                states[day, 4] = 1
                events[day, 4] = DetectorEvent(
                    "R2",
                    "R2e",
                    day,
                    original.window_start,
                    original.pivot,
                    original.support,
                    original.lower,
                    original.details
                    + (
                        ("source_subtype", original.subtype_id),
                        ("source_t0", day - 1),
                        ("next_day_confirmation", day),
                        (
                            "matching_sources_json",
                            json.dumps(
                                [
                                    {
                                        "subtype_id": source.subtype_id,
                                        "t0": source.t0,
                                        "pivot": source.pivot,
                                        "support": source.support,
                                        "lower": source.lower,
                                        "details": dict(source.details),
                                    }
                                    for source in matches
                                ],
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    ),
                )
        for col, subtype in enumerate(subtypes):
            if states[day, col] == -1:
                reasons.append((subtype, day, "warmup_or_missing_required_window"))
    return finish_scan("R2", subtypes, states, tuple(events.values()), reasons)
