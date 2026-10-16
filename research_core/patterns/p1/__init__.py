"""Raw breakout/retest confirmations with earliest-breakout representation."""

import json

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan, prior_max, prior_mean


def scan(bars: Bars) -> DetectorScan:
    close, high, low, volume = (bars.values(name) for name in ("Close", "High", "Low", "Volume"))
    resistance, mean_volume = prior_max(high, 60), prior_mean(volume, 20)
    states = np.zeros((len(bars), 1), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    for t in range(len(bars)):
        candidates: list[tuple[int, int, float]] = []
        incomplete = t < 85
        for b in range(max(60, t - 25), t - 3):
            if not bars.complete(b - 60, b) or not bars.complete(b - 20, b, columns=("Volume",)):
                incomplete = True
                continue
            r = float(resistance[b])
            if close[b] <= r or volume[b] < mean_volume[b] * 1.5:
                continue
            if not bars.complete(b, t):
                incomplete = True
                continue
            retest: int | None = None
            for day in range(b + 1, min(b + 20, t) + 1):
                if close[day] < r * 0.97:
                    break
                if day >= b + 3 and r * 0.97 <= close[day] <= r * 1.03:
                    retest = day
                    break
            if retest is None:
                continue
            confirmation = next((day for day in range(retest + 1, min(retest + 5, t) + 1) if close[day] > high[day - 1]), None)
            if confirmation == t:
                candidates.append((b, retest, r))
        if candidates:
            b, retest, r = candidates[0]
            states[t, 0] = 1
            details = (
                ("breakout_index", b),
                ("retest_index", retest),
                ("paired_control_index", b),
                (
                    "alternate_ancestors",
                    json.dumps([{"breakout_index": i, "retest_index": j, "resistance": level} for i, j, level in candidates[1:]], sort_keys=True),
                ),
            )
            events.append(DetectorEvent("P1", "P1", t, b - 60, r, r, float(low[retest : t + 1].min()), details))
        elif incomplete:
            states[t, 0] = -1
            unknown.append(("P1", t, "possible_breakout_ancestry_unknown"))
    return finish_scan("P1", ("P1",), states, events, unknown)
