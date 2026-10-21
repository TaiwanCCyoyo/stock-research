"""Past-only mission controls with separate formula and eligibility states."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core.pattern_scan_events_v1 import per_group_cooldown
from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, StateArray, prior_max, prior_mean

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlScan:
    control_id: str
    formula_states: StateArray
    admitted_states: StateArray
    raw_indices: tuple[int, ...]
    cooled_indices: tuple[int, ...]
    unknown_reasons: tuple[tuple[int, str], ...]
    eligibility_excluded: tuple[int, ...]
    paired_events: tuple[tuple[int, int], ...] = ()

    @property
    def states(self) -> StateArray:
        return self.admitted_states


def _eligible(values: NDArray[np.bool_], n: int) -> NDArray[np.bool_]:
    if values.dtype != np.bool_ or values.shape != (n,):
        raise ValueError("base eligibility must be an aligned boolean array")
    return values


def _finish(
    control: str, formula: StateArray, eligible: NDArray[np.bool_], reasons: Sequence[tuple[int, str]], pairs: Sequence[tuple[int, int]] = ()
) -> ControlScan:
    frozen = formula.copy()
    admitted = np.where(eligible, frozen, 0).astype(np.int8)
    frozen.setflags(write=False)
    admitted.setflags(write=False)
    raw = tuple(int(i) for i in np.flatnonzero(admitted == 1))
    return ControlScan(control, frozen, admitted, raw, per_group_cooldown(raw), tuple(reasons), tuple(int(i) for i in np.flatnonzero(~eligible)), tuple(pairs))


def base_no_pattern(base_eligible: NDArray[np.bool_], pattern_raw_union_states: StateArray) -> ControlScan:
    """Unknown raw detection never enters the no-pattern control."""
    if pattern_raw_union_states.ndim != 1 or not np.isin(pattern_raw_union_states, (-1, 0, 1)).all():
        raise ValueError("raw pattern states must be a one-dimensional tri-state array")
    eligible = _eligible(base_eligible, len(pattern_raw_union_states))
    formula = np.where(pattern_raw_union_states == -1, -1, pattern_raw_union_states == 0).astype(np.int8)
    reasons = [(int(i), "pattern_detection_unknown") for i in np.flatnonzero(formula == -1)]
    return _finish("C-base-no-pattern", formula, eligible, reasons)


def scan_controls(
    bars: Bars, *, base_eligible: NDArray[np.bool_], h1_source_events: Sequence[Mapping[str, object]], p1_events: Sequence[DetectorEvent] = ()
) -> Mapping[str, ControlScan]:
    eligible = _eligible(base_eligible, len(bars))
    close, volume = bars.values("Close"), bars.values("Volume")
    maximum250, maximum60 = prior_max(close, 250), prior_max(close, 60)
    mean20 = prior_mean(volume, 20)
    ma60 = cast(pd.Series, pd.Series(close).rolling(60, min_periods=60).mean()).to_numpy(dtype=np.float64)
    atr, raw_close = bars.values("ATR14"), bars.values("RawClose")
    source_days: set[int] = set()
    for source_event in h1_source_events:
        day = source_event.get("t")
        if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day < len(bars):
            raise ValueError("H1 source event requires a common-calendar t index")
        source_days.add(day)
    ids = ("C-52w", "C-nh", "C-dip", "C-trend")
    states = {name: np.zeros(len(bars), dtype=np.int8) for name in ids}
    reasons: dict[str, list[tuple[int, str]]] = {name: [] for name in ids}
    segment_start = 0
    for t in range(len(bars)):
        h1_good = bars.complete(t, t) and bool(
            np.isfinite(atr[t]) and atr[t] > 0 and np.isfinite(raw_close[t]) and raw_close[t] > 0 and np.isfinite(volume[t]) and volume[t] >= 0
        )
        if not h1_good:
            segment_start = t + 1
        known = {
            "C-52w": bars.complete(t - 250, t) and bars.complete(t - 20, t, columns=("Volume",)),
            "C-nh": t - segment_start >= 20 and bars.complete(t - 20, t) and bool(np.isfinite(volume[t])),
            "C-dip": bars.complete(t - 60, t),
            "C-trend": bars.complete(t - 79, t),
        }
        for name in ids:
            if not known[name]:
                states[name][t] = -1
                reasons[name].append((t, "incomplete_control_window"))
        if known["C-52w"]:
            states["C-52w"][t] = close[t] >= maximum250[t] and volume[t] >= mean20[t] * 1.5
        if known["C-nh"]:
            previous = volume[t - 20 : t]
            finite = previous[np.isfinite(previous)]
            if not len(finite):
                states["C-nh"][t] = -1
                reasons["C-nh"].append((t, "missing_prior_volume"))
            else:
                states["C-nh"][t] = t not in source_days and close[t] > close[t - 20 : t].max() and volume[t] >= finite.mean() * 1.5
        if known["C-dip"]:
            states["C-dip"][t] = close[t] <= maximum60[t] * 0.8 and close[t] > close[t - 1]
        if known["C-trend"]:
            states["C-trend"][t] = close[t] > ma60[t] and ma60[t] > ma60[t - 20]
    result = {name: _finish(name, states[name], eligible, reasons[name]) for name in ids}
    result["C-base"] = _finish("C-base", np.ones(len(bars), dtype=np.int8), eligible, ())
    pairs: list[tuple[int, int]] = []
    for event in p1_events:
        details = dict(event.details)
        breakout = details.get("breakout_index")
        if event.pattern_id != "P1" or isinstance(breakout, bool) or not isinstance(breakout, int) or not 0 <= breakout < event.t0 < len(bars):
            raise ValueError("P1 pairing requires its original past breakout_index")
        pairs.append((breakout, event.t0))
        encoded = details.get("alternate_ancestors", "[]")
        if not isinstance(encoded, str):
            raise ValueError("P1 alternate_ancestors must be JSON text")
        try:
            ancestors = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise ValueError("P1 alternate_ancestors contains malformed JSON") from error
        if not isinstance(ancestors, list):
            raise ValueError("P1 alternate_ancestors must contain a JSON list")
        for ancestor in ancestors:
            original = ancestor.get("breakout_index") if isinstance(ancestor, dict) else None
            if isinstance(original, bool) or not isinstance(original, int) or not 0 <= original < event.t0:
                raise ValueError("P1 alternate ancestor requires a past breakout_index")
            pairs.append((original, event.t0))
    p1_states = np.zeros(len(bars), dtype=np.int8)
    for breakout, _ in pairs:
        p1_states[breakout] = 1
    result["C-P1-breakout"] = _finish("C-P1-breakout", p1_states, eligible, (), sorted(set(pairs)))
    LOGGER.debug(
        "Controls rows=%d eligible=%d H1 source events=%d P1 confirmations=%d pairs=%d raw_counts=%s",
        len(bars),
        int(eligible.sum()),
        len(h1_source_events),
        len(p1_events),
        len(set(pairs)),
        {name: len(scan.raw_indices) for name, scan in result.items()},
    )
    return result
