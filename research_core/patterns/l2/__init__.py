"""F32 adapter; current SMA60 and six-bar low are event metadata."""

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan


def scan(bars: Bars) -> DetectorScan:
    flags, sma, close, low = (bars.values(name) for name in ("F32", "SMA60", "Close", "Low"))
    states = np.zeros((len(bars), 1), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    for t in range(len(bars)):
        if not bars.complete(t - 59, t) or not np.isfinite(flags[t]) or not np.isfinite(sma[t]):
            states[t, 0] = -1
            unknown.append(("L2", t, "SMA60_or_supplied_F32_unknown"))
            continue
        expected = int(close[t] > sma[t] and close[t] / close[t - 5] - 1 < 0)
        if flags[t] != expected:
            raise ValueError(f"F32 parity mismatch at {t}")
        states[t, 0] = expected
        if expected:
            events.append(DetectorEvent("L2", "L2", t, t - 59, float(sma[t]), float(sma[t]), float(low[t - 5 : t + 1].min())))
    return finish_scan("L2", ("L2",), states, events, unknown)
