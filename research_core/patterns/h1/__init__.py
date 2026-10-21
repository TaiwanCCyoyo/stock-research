"""Common-calendar adapter over the byte-preserved HHHL v4 detector."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.patterns.hhhl.source import load_detector
from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan, finish_scan

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def source_detector() -> Callable[[pd.DataFrame], list[dict[str, Any]]]:
    """Only the registered trusted pure source; source hashes are checked there."""
    return cast(Callable[[pd.DataFrame], list[dict[str, Any]]], load_detector("v4"))


def scan_with_sources(bars: Bars) -> tuple[DetectorScan, tuple[dict[str, Any], ...]]:
    """Keep all source events for C-nh; split numeric gaps before detection.

    The source's t/restart/seq indices are remapped to the common calendar.
    Pattern=False source events remain in the source audit/C-nh exclusion table.
    This adapter has no independent HHHL geometry or volume override.
    """
    subtypes = ("P-clean", "P-over")
    states = np.zeros((len(bars), 2), dtype=np.int8)
    events: list[DetectorEvent] = []
    reasons: list[tuple[str, int, str]] = []
    originals: list[dict[str, Any]] = []
    price_valid = np.diff(bars.invalid_prefix) == 0
    atr = bars.values("ATR14")
    good = price_valid & np.isfinite(atr) & (atr > 0)
    raw = bars.values("RawClose")
    volume = bars.values("Volume")
    good &= np.isfinite(raw) & (raw > 0) & np.isfinite(volume) & (volume >= 0)
    starts = np.flatnonzero(good & ~np.r_[False, good[:-1]])
    ends = np.flatnonzero(good & ~np.r_[good[1:], False])
    for day in np.flatnonzero(~good):
        states[day, :] = -1
    for start, end in zip(starts, ends, strict=True):
        positions = np.arange(start, end + 1)
        frame = pd.DataFrame({
            "asof_date": [bars.dates[int(day)] for day in positions],
            **{name: bars.values(name)[positions] for name in ("Open", "High", "Low", "Close")},
            "RawClose": raw[positions],
            "VolumeLots": volume[positions],
            "atr14_pct": atr[positions] / bars.values("Close")[positions],
        })
        states[start : min(end + 1, start + 20), :] = -1
        for original in source_detector()(frame):
            record = json.loads(json.dumps(original))
            for key in ("t", "restart", "leg_start"):
                record[key] = int(record[key]) + int(start)
            for point in record["seq"]:
                point["i"] = int(point["i"]) + int(start)
            record["segment_start"] = int(start)
            originals.append(record)
            t = int(record["t"])
            if not record["pattern"]:
                continue
            col = int(bool(record["bonus_levels"]))
            seq = record["seq"]
            lows = [point for point in seq if point["k"] == "L"]
            if not lows:
                raise ValueError("frozen v4 event has no Z2 low")
            z2 = float(lows[-1]["p"])
            restart = int(record["restart"])
            lower = float(bars.values("Low")[restart])
            states[t, col] = 1
            events.append(
                DetectorEvent(
                    "H1",
                    subtypes[col],
                    t,
                    int(start),
                    float(record["hz_top"]),
                    z2,
                    lower,
                    (("confirmation_index", t), ("restart_index", restart), ("source_event_json", json.dumps(record, sort_keys=True, separators=(",", ":")))),
                )
            )
    for day, col in np.argwhere(states == -1):
        reasons.append((subtypes[int(col)], int(day), "v4_input_or_segment_warmup"))
    LOGGER.debug("H1 raw source events=%d pattern candidates=%d", len(originals), len(events))
    return finish_scan("H1", subtypes, states, events, reasons), tuple(originals)


def scan(bars: Bars) -> DetectorScan:
    return scan_with_sources(bars)[0]
