"""F10 adapter with fixed prior-window support metadata."""

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan, prior_max, prior_min


def scan(bars: Bars) -> DetectorScan:
    flags = bars.values("F10")
    high, low = prior_max(bars.values("High"), 60), prior_min(bars.values("Low"), 60)
    states = np.zeros((len(bars), 1), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    for t in range(len(bars)):
        if not bars.complete(t - 60, t) or not np.isfinite(flags[t]):
            states[t, 0] = -1
            unknown.append(("L1", t, "prior60_or_supplied_F10_unknown"))
            continue
        expected = int(bars.values("Close")[t] > high[t])
        if flags[t] != expected:
            raise ValueError(f"F10 parity mismatch at {t}")
        states[t, 0] = expected
        if expected:
            events.append(DetectorEvent("L1", "L1", t, t - 60, float(high[t]), float(high[t]), float(low[t])))
    return finish_scan("L1", ("L1",), states, events, unknown)
