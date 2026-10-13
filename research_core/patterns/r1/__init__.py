"""Spring recovery and independently observed delayed second tests."""

from __future__ import annotations

import json
import logging

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan

LOGGER = logging.getLogger(__name__)


def scan(bars: Bars) -> DetectorScan:
    states = np.zeros((len(bars), 2), dtype=np.int8)
    events: list[DetectorEvent] = []
    recoveries: dict[int, DetectorEvent] = {}
    close, low, high, atr, opening = (bars.values(name) for name in ("Close", "Low", "High", "ATR14", "Open"))
    expired = 0
    for day in range(len(bars)):
        unknown = day < 61
        # Same recovery date chooses the earliest break without reading outcomes.
        for broken in range(max(60, day - 5), day):
            start = broken - 60
            if not bars.complete(start, day) or not np.isfinite(atr[broken]) or atr[broken] <= 0:
                unknown = True
                continue
            support = float(low[start:broken].min())
            touches = np.flatnonzero(low[start:broken] <= support * 1.03)
            if (float(high[start:broken].max()) - support) > support * 0.35 or len(touches) < 2 or int(touches[-1] - touches[0]) < 10:
                continue
            if close[broken] >= support or support - low[broken] > 1.5 * atr[broken]:
                continue
            if close[day] > support and not np.any(close[broken + 1 : day] > support):
                event = DetectorEvent(
                    "R1",
                    "R1a",
                    day,
                    start,
                    support,
                    support,
                    float(low[broken : day + 1].min()),
                    (("break_index", broken), ("recovery_index", day), ("confirmation_index", day)),
                )
                recoveries[day] = event
                events.append(event)
                states[day, 0] = 1
                break
        if states[day, 0] != 1 and unknown:
            states[day, 0] = -1

        # Retest is first qualifying close 3..15 after recovery. A missing
        # observation anywhere in its active interval is never gap-bridged.
        unknown = day < 65
        matches: list[tuple[DetectorEvent, int]] = []
        for recovered in range(day - 4, max(-1, day - 21), -1):
            if states[recovered, 0] == -1:
                unknown = True
            source = recoveries.get(recovered)
            if source is None:
                continue
            if not bars.complete(recovered, day):
                unknown = True
                continue
            retest_support, retest_lower = source.support, source.lower
            assert retest_support is not None and retest_lower is not None
            end = min(recovered + 15, day - 1)
            tests = np.flatnonzero(close[recovered + 3 : end + 1] <= retest_support * 1.03)
            if len(tests) == 0:
                continue
            retest = recovered + 3 + int(tests[0])
            if np.any(close[recovered + 1 : day + 1] < retest_lower):
                continue
            if day > retest + 5:
                expired += 1
                continue
            if close[day] > opening[day] and not np.any(close[retest + 1 : day] > opening[retest + 1 : day]):
                matches.append((source, retest))
        if matches:
            source, retest = matches[0]
            states[day, 1] = 1
            events.append(
                DetectorEvent(
                    "R1",
                    "R1b",
                    day,
                    source.window_start,
                    source.pivot,
                    source.support,
                    source.lower,
                    source.details
                    + (
                        ("retest_index", retest),
                        ("source_t0", source.t0),
                        ("second_confirmation_index", day),
                        (
                            "matching_sources_json",
                            json.dumps(
                                [
                                    {
                                        "t0": item.t0,
                                        "retest_index": test,
                                        "pivot": item.pivot,
                                        "support": item.support,
                                        "lower": item.lower,
                                        "details": dict(item.details),
                                    }
                                    for item, test in matches
                                ],
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    ),
                )
            )
        if states[day, 1] != 1 and unknown:
            states[day, 1] = -1
    reasons = [(subtype, int(day), "warmup_or_missing_required_window") for day, col in np.argwhere(states == -1) for subtype in (("R1a", "R1b")[int(col)],)]
    LOGGER.debug("R1 expired active retests=%d", expired)
    return finish_scan("R1", ("R1a", "R1b"), states, events, reasons)
