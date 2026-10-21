"""Exact F33 pending-break adapter; supplied flags are checked, never altered."""

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan


def scan(bars: Bars) -> DetectorScan:
    flags, low, close = (bars.values(name) for name in ("F33", "Low", "Close"))
    states = np.zeros((len(bars), 1), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    level: float | None = None
    break_index = 0
    expires = 0
    for t in range(len(bars)):
        if not bars.complete(t - 20, t):
            level = None
            states[t, 0] = -1
            unknown.append(("L3", t, "prior20_or_OHLC_gap_unknown"))
            continue
        prior_low = float(low[t - 20 : t].min())
        expected = 0
        event: DetectorEvent | None = None
        if low[t] < prior_low:
            level, break_index, expires = prior_low, t, 5
        elif level is not None:
            expires -= 1
            if close[t] > level:
                expected = 1
                event = DetectorEvent("L3", "L3", t, break_index - 20, level, level, float(low[break_index : t + 1].min()), (("break_index", break_index),))
                level = None
            elif expires <= 0:
                level = None
        if not np.isfinite(flags[t]):
            states[t, 0] = -1
            unknown.append(("L3", t, "supplied_F33_unknown"))
            continue
        if flags[t] != expected:
            raise ValueError(f"F33 parity mismatch at {t}")
        states[t, 0] = expected
        if event is not None:
            events.append(event)
    return finish_scan("L3", ("L3",), states, events, unknown)
