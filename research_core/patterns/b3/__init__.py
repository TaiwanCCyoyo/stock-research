"""B3 platforms: shortest valid structure independently for each subtype."""

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan, prior_mean, prior_min


def scan(bars: Bars) -> DetectorScan:
    h, low, c, v = (bars.values(key) for key in ("High", "Low", "Close", "Volume"))
    prior_low, volume = prior_min(c, 60), prior_mean(v, 50)
    subtypes = ("B3a", "B3b", "B3c")
    states = np.zeros((len(bars), 3), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    for t in range(len(bars)):
        uncertain = [False] * 3
        for n in range(25, 66):
            start = t - n
            if not bars.complete(start - 60, t) or not bars.complete(t - 50, t, columns=("Volume",)):
                uncertain = [True] * 3
                continue
            high, bottom = float(h[start:t].max()), float(low[start:t].min())
            base = c[start] >= prior_low[start] * 1.25 and (high - bottom) / high <= 0.15 and c[t] > high and v[t] >= volume[t] * 1.5
            if not base:
                continue
            third = n // 3
            tight = (h[t - third : t].max() - low[t - third : t].min()) < (h[start : start + third].max() - low[start : start + third].min()) * 0.6
            volume_known = bars.complete(start, t - 1, columns=("Volume",))
            dry = volume_known and v[t - 10 : t].mean() <= v[start:t].mean() * 0.8
            if not volume_known:
                uncertain[1] = True
            for col, valid in enumerate((True, dry, bool(tight))):
                if valid and states[t, col] != 1:
                    states[t, col] = 1
                    events.append(
                        DetectorEvent(
                            "B3",
                            subtypes[col],
                            t,
                            min(start - 60, t - 50),
                            high,
                            bottom,
                            bottom,
                            (("platform_start", start), ("platform_length", n), ("confirmation_index", t)),
                        )
                    )
        for col, subtype in enumerate(subtypes):
            if states[t, col] != 1 and uncertain[col]:
                states[t, col] = -1
                unknown.append((subtype, t, "incomplete_platform_search"))
    return finish_scan("B3", subtypes, states, events, unknown)
