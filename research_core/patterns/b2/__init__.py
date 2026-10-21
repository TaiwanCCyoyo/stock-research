"""B2 supplied gap-safe Bollinger breakout, with independent volume subtype."""

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan, prior_mean, prior_min


def scan(bars: Bars) -> DetectorScan:
    c, low, v, upper, width = (bars.values(key) for key in ("Close", "Low", "Volume", "BBUpper", "BBWidth"))
    minimum, volume, support = prior_min(width, 125), prior_mean(v, 20), prior_min(low, 20)
    subtypes = ("B2a", "B2b")
    states = np.zeros((len(bars), 2), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    for t in range(len(bars)):
        complete = bars.complete(t - 130, t) and t >= 130 and bool(np.isfinite(upper[t]))
        squeeze = [i for i in range(max(0, t - 5), t) if np.isfinite(width[i]) and np.isfinite(minimum[i]) and width[i] <= minimum[i]]
        width_known = t >= 130 and bool(np.isfinite(width[t - 130 : t]).all())
        for col, subtype in enumerate(subtypes):
            known = complete and (bool(squeeze) or width_known) and (col == 0 or bars.complete(t - 20, t, columns=("Volume",)))
            if not known:
                states[t, col] = -1
                unknown.append((subtype, t, "incomplete_bollinger_window"))
            elif squeeze and c[t] > upper[t] and (col == 0 or v[t] >= volume[t] * 1.5):
                states[t, col] = 1
                events.append(
                    DetectorEvent(
                        "B2",
                        subtype,
                        t,
                        t - 130,
                        float(upper[t]),
                        float(support[t]),
                        float(support[t]),
                        (("squeeze_index", squeeze[0]), ("confirmation_index", t)),
                    )
                )
    return finish_scan("B2", subtypes, states, events, unknown)
