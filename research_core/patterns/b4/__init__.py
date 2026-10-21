"""B4 gap breakout, on complete common-session windows."""

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan, prior_max, prior_mean, prior_min


def scan(bars: Bars) -> DetectorScan:
    o, h, low, c, v = (bars.values(key) for key in ("Open", "High", "Low", "Close", "Volume"))
    maximum, volume, support = prior_max(c, 60), prior_mean(v, 20), prior_min(low, 20)
    states = np.zeros((len(bars), 1), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    for t in range(len(bars)):
        if not bars.complete(t - 60, t) or not bars.complete(t - 20, t, columns=("Volume",)):
            states[t, 0] = -1
            unknown.append(("B4", t, "incomplete_60_session_window"))
        elif o[t] >= h[t - 1] * 1.02 and low[t] > h[t - 1] and c[t] >= maximum[t] and v[t] >= volume[t] * 2:
            states[t, 0] = 1
            events.append(
                DetectorEvent(
                    "B4", "B4", t, t - 60, float(h[t - 1]), float(h[t - 1]), float(support[t]), (("previous_index", t - 1), ("confirmation_index", t))
                )
            )
    return finish_scan("B4", ("B4",), states, events, unknown)
