"""Confirmed RSI divergence and subsequent bounded failure swings."""

from __future__ import annotations

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan


def scan(bars: Bars) -> DetectorScan:
    states = np.zeros((len(bars), 2), dtype=np.int8)
    events: list[DetectorEvent] = []
    close, low, rsi = (bars.values(name) for name in ("Close", "Low", "RSI14"))
    pivots: list[int] = []
    structures: dict[int, tuple[int, int, float]] = {}
    for day in range(len(bars)):
        second = day - 3
        unknown = day < 18
        if not bars.complete(second - 5, day) or not np.isfinite(rsi[second]):
            unknown = True
        elif int(np.argmin(low[second - 5 : day + 1])) == 5:
            for first in reversed(pivots):
                distance = second - first
                if distance > 60:
                    break
                if distance < 10:
                    continue
                if not bars.complete(first - 5, day) or not np.isfinite(rsi[first : second + 1]).all():
                    unknown = True
                    continue
                if low[second] < low[first] and rsi[second] > rsi[first] and rsi[first] <= 30:
                    threshold = float(rsi[first + 1 : second].max())
                    structures[day] = (first, second, threshold)
                    if close[day] > close[second]:
                        states[day, 0] = 1
                        events.append(
                            DetectorEvent(
                                "R3",
                                "R3a",
                                day,
                                first - 5,
                                float(close[second]),
                                float(low[second]),
                                float(low[second]),
                                (
                                    ("p1_index", first),
                                    ("p2_index", second),
                                    ("p1_confirmed_index", first + 3),
                                    ("p2_confirmed_index", day),
                                    ("confirmation_index", day),
                                    ("rsi_threshold", threshold),
                                    ("threshold_window_start", first + 1),
                                    ("threshold_window_end", second - 1),
                                ),
                            )
                        )
                    break
            # Unobserved older pivot alternatives are unknown, unless a known
            # pair has already established the positive candidate.
            if not bars.complete(max(0, second - 65), day, columns=("RSI14",)):
                unknown = True
            pivots.append(second)
        if states[day, 0] != 1 and unknown:
            states[day, 0] = -1

        unknown = day < 19
        for confirmed in range(day - 1, max(-1, day - 21), -1):
            if states[confirmed, 0] == -1:
                unknown = True
            structure = structures.get(confirmed)
            if structure is None:
                continue
            first, second, threshold = structure
            if not bars.complete(first - 5, day, columns=("RSI14",)):
                unknown = True
                continue
            if rsi[day] > threshold and not np.any(rsi[confirmed + 1 : day] > threshold):
                states[day, 1] = 1
                events.append(
                    DetectorEvent(
                        "R3",
                        "R3b",
                        day,
                        first - 5,
                        float(close[second]),
                        float(low[second]),
                        float(low[second]),
                        (
                            ("p1_index", first),
                            ("p2_index", second),
                            ("p1_confirmed_index", first + 3),
                            ("p2_confirmed_index", confirmed),
                            ("confirmation_index", day),
                            ("rsi_threshold", threshold),
                            ("threshold_window_start", first + 1),
                            ("threshold_window_end", second - 1),
                        ),
                    )
                )
                break
        if states[day, 1] != 1 and unknown:
            states[day, 1] = -1
    reasons = [(subtype, int(day), "warmup_or_missing_required_window") for day, col in np.argwhere(states == -1) for subtype in (("R3a", "R3b")[int(col)],)]
    return finish_scan("R3", ("R3a", "R3b"), states, events, reasons)
