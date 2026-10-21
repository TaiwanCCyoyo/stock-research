"""Approved finite cup search, with independent handle/no-handle candidates.

B1b length n fixes the left rim at t0-n and ends the cup at t0-1.
Ascending n chooses the nearer rim when equal-price rims both qualify.
"""

import numpy as np

from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan, prior_mean, prior_min


def scan(bars: Bars) -> DetectorScan:
    h, low, c, v = (bars.values(key) for key in ("High", "Low", "Close", "Volume"))
    prior_low, volume = prior_min(c, 120), prior_mean(v, 50)
    subtypes = ("B1a", "B1b")
    states = np.zeros((len(bars), 2), dtype=np.int8)
    events: list[DetectorEvent] = []
    unknown: list[tuple[str, int, str]] = []
    for t in range(len(bars)):
        uncertain = [False, False]
        for handle in range(5, 16):
            start = t - handle
            search_start, search_end = start - 250, start - 30
            if not bars.complete(search_start, t) or not bars.complete(t - 50, t, columns=("Volume",)):
                uncertain[0] = True
                continue
            left = search_start + int(np.flatnonzero(c[search_start : search_end + 1] == c[search_start : search_end + 1].max())[-1])
            if not bars.complete(left - 120, t):
                uncertain[0] = True
                continue
            bottom, rim = float(low[left:start].min()), float(h[left])
            top = float(h[start:t].max())
            top_index = start + int(np.argmax(h[start:t]))
            handle_low = float(low[start:t].min())
            if (
                c[left] >= prior_low[left] * 1.3
                and 0.12 <= (rim - bottom) / rim <= 0.35
                and top_index < start + 3
                and rim * 0.9 <= top <= rim * 1.05
                and (top - handle_low) / top <= 0.12
                and handle_low > bottom + 0.5 * (rim - bottom)
                and c[t] > top
                and v[t] >= volume[t] * 1.4
            ):
                states[t, 0] = 1
                events.append(
                    DetectorEvent(
                        "B1",
                        "B1a",
                        t,
                        min(search_start, left - 120, t - 50),
                        top,
                        handle_low,
                        bottom,
                        (("left_index", left), ("handle_start", start), ("handle_length", handle), ("handle_high_index", top_index), ("confirmation_index", t)),
                    )
                )
                break
        for length in range(30, 251):
            left = t - length
            if not bars.complete(left - 120, t):
                uncertain[1] = True
                continue
            bottom, rim = float(low[left:t].min()), float(h[left])
            if c[left] >= prior_low[left] * 1.3 and 0.12 <= (rim - bottom) / rim <= 0.35 and c[t] > rim:
                states[t, 1] = 1
                events.append(
                    DetectorEvent("B1", "B1b", t, left - 120, rim, bottom, bottom, (("left_index", left), ("cup_length", length), ("confirmation_index", t)))
                )
                break
        for col, subtype in enumerate(subtypes):
            if states[t, col] != 1 and uncertain[col]:
                states[t, col] = -1
                unknown.append((subtype, t, "incomplete_cup_search"))
    return finish_scan("B1", subtypes, states, events, unknown)
