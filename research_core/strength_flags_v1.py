"""Batch PR17 weakening flags without changing its first-decision clocks.

Prepare indicators/pivots with ``pattern_scan_indicators_v1.prepare_detector_frame``.
The whole-stock independent series is evaluated once through the original public
API. Only the t0-fixed Y3/X6 levels need anchor-relative comparisons afterwards.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core.hhhl_variants_observations import flag_history
from research_core.multiple_observations_v1 import classify_window, landmark_riskset, positive_offset, target_value
from research_core.pattern_scan_flags_v1 import FLAG_IDS, event_flags

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "strength-flags.v1"
APPLICABLE_FLAGS = tuple(flag for flag in FLAG_IDS if flag not in {"Y1", "Y2"})
LANDMARKS = (5, 10, 20, 40)
RISE_BINS = ("lt1", "b1_1p10", "b1p10_1p25", "ge1p25")
FLAG_STATES = ("triggered", "all_false", "unknown", "not_applicable")


def rise_bin(ratio: float | None) -> str | None:
    return None if ratio is None else RISE_BINS[0] if ratio < 1 else RISE_BINS[1] if ratio < 1.1 else RISE_BINS[2] if ratio < 1.25 else RISE_BINS[3]


class BatchFlagIndex:
    """One stock, validated once; next true/unknown indexes preserve absorption.

    Arrays use -1 unknown, 0 false, 1 true. Unknown before the first true makes
    the history unknown forever; a later true does not repair missing evidence.
    Y1/Y2 have no pattern levels and are explicitly not_applicable.
    """

    def __init__(self, frame: pd.DataFrame, pivots: pd.DataFrame, *, max_horizon: int = 504) -> None:
        self.max_horizon = positive_offset(max_horizon, "max_horizon")
        if frame.empty:
            raise ValueError("frame must contain at least one common-calendar row")
        reference = event_flags(frame, pivots, 0)
        self.frame, self.pivots = frame, pivots
        self.close = frame["Close"].to_numpy(dtype=float, na_value=np.nan)
        self.valid = np.isfinite(self.close) & (self.close > 0)
        self.n = len(frame)
        self.positions = np.arange(self.n)
        self.next_missing = self._next(np.where(self.valid, 0, 1).astype(np.int8), 1)
        self.independent: dict[str, NDArray[np.int8]] = {}
        self.next_true: dict[str, NDArray[np.int64]] = {}
        self.next_unknown: dict[str, NDArray[np.int64]] = {}
        for flag in ("X5_MA20", "X5_MA60", "X7", "X8"):
            values = np.full(self.n, -1, dtype=np.int8)
            values[1:] = reference[flag].to_numpy(dtype=np.int8, na_value=-1)
            self.independent[flag] = values
            self.next_true[flag], self.next_unknown[flag] = self._next(values, 1), self._next(values, -1)
        lows = pivots.loc[(pivots["kind"] == "low") & (pivots["k"] == 1.5)]
        low_prices = lows["price"].to_numpy(dtype=float)
        low_confirmed = lows["confirmation_index"].to_numpy(dtype=np.int64)
        self.support = np.full(self.n, np.nan)
        for t0 in range(self.n):
            eligible = low_prices[(low_confirmed <= t0) & (low_prices < self.close[t0])]
            if len(eligible) and self.valid[t0]:
                self.support[t0] = float(eligible.max())
        self.fixed_first: dict[str, tuple[NDArray[np.int64], NDArray[np.int64]]] = {}
        for flag, levels, inclusive in (
            ("Y3", self.support, False),
            ("X6_10", self.close * 0.9, True),
            ("X6_15", self.close * 0.85, True),
        ):
            first_true = np.full(self.n, self.n, dtype=np.int64)
            first_unknown = np.full(self.n, self.n, dtype=np.int64)
            for offset in range(1, min(self.max_horizon, self.n - 1) + 1):
                stop = self.n - offset
                known = self.valid[offset:] & np.isfinite(levels[:stop]) & (levels[:stop] > 0)
                trigger = self.close[offset:] <= levels[:stop] if inclusive else self.close[offset:] < levels[:stop]
                first_true[:stop] = np.where((first_true[:stop] == self.n) & known & trigger, offset, first_true[:stop])
                first_unknown[:stop] = np.where((first_unknown[:stop] == self.n) & ~known, offset, first_unknown[:stop])
            self.fixed_first[flag] = first_true, first_unknown
        LOGGER.debug("Indexed flag clocks sessions=%d max_horizon=%d", self.n, self.max_horizon)

    def _next(self, values: NDArray[np.int8], state: int) -> NDArray[np.int64]:
        positions = np.where(values == state, np.arange(len(values)), self.n)
        return np.minimum.accumulate(positions[::-1])[::-1].astype(np.int64)

    def first_decisions(self, flag: str, t0s: NDArray[np.int64]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        if flag not in APPLICABLE_FLAGS:
            raise ValueError("first_decisions requires an applicable flag")
        if flag in self.fixed_first:
            trigger, unknown = self.fixed_first[flag]
            return trigger[t0s], unknown[t0s]
        start = np.minimum(t0s + 1, self.n - 1)
        true = np.where(t0s + 1 < self.n, self.next_true[flag][start] - t0s, self.n)
        unknown = np.where(t0s + 1 < self.n, self.next_unknown[flag][start] - t0s, self.n)
        # A sentinel absolute index must not become a false observation near EOF.
        true = np.where(self.next_true[flag][start] == self.n, self.n, true)
        unknown = np.where(self.next_unknown[flag][start] == self.n, self.n, unknown)
        return true.astype(np.int64), unknown.astype(np.int64)

    def histories(self, flag: str, t0s: NDArray[np.int64], cutoffs: NDArray[np.int64]) -> tuple[NDArray[np.int8], NDArray[np.int64]]:
        """State 0=triggered, 1=all_false, 2=unknown, 3=not_applicable."""
        if t0s.ndim != 1 or cutoffs.shape != t0s.shape or np.any((t0s < 0) | (t0s >= self.n)) or np.any((cutoffs < 0) | (cutoffs > self.max_horizon)):
            raise ValueError("anchors and cutoffs must align within the indexed calendar/horizon")
        if flag in {"Y1", "Y2"}:
            return np.full(len(t0s), 3, dtype=np.int8), np.full(len(t0s), -1, dtype=np.int64)
        true, unknown = self.first_decisions(flag, t0s)
        available = self.n - t0s - 1
        triggered = (true <= cutoffs) & (true < unknown) & (true <= available)
        missing = ((unknown <= cutoffs) & (unknown <= true) & (unknown <= available)) | ((available < cutoffs) & ~triggered)
        states = np.where(triggered, 0, np.where(missing, 2, 1)).astype(np.int8)
        return states, np.where(triggered, true, -1)

    def vectors(self, t0: int, stop: int) -> dict[str, list[bool | None]]:
        """Bounded vectors for field-for-field public-API parity diagnostics."""
        t0 = positive_offset(t0, "t0", minimum=0)
        if t0 >= self.n:
            raise ValueError("t0 must be within the common calendar")
        vectors: dict[str, list[bool | None]] = {}
        for flag in APPLICABLE_FLAGS:
            if flag in self.independent:
                observed_values = self.independent[flag][t0 + 1 : stop]
                observations: list[bool | None] = [
                    None,
                    *[None if value == -1 else bool(value) for value in observed_values],
                ]
                vectors[flag] = observations
                continue
            level = self.support[t0] if flag == "Y3" else self.close[t0] * (0.9 if flag == "X6_10" else 0.85)
            observations = []
            for day in range(t0 + 1, stop):
                known = self.valid[day] and np.isfinite(level) and level > 0
                observations.append(None if not known else bool(self.close[day] <= level if flag.startswith("X6") else self.close[day] < level))
            vectors[flag] = [None, *observations]
        return vectors

    def observations(
        self, t0s: Sequence[int], *, targets: Sequence[float] = (2.0,), horizons: Sequence[int] = (126, 252), landmarks: Sequence[int] = LANDMARKS
    ) -> pd.DataFrame:
        """Long diagnostic table; production counts use compact history arrays."""
        target_values = tuple(target_value(value) for value in targets)
        horizon_values = tuple(positive_offset(value, "horizon") for value in horizons)
        landmark_values = tuple(positive_offset(value, "landmark") for value in landmarks)
        if any(len(values) != len(set(values)) for values in (target_values, horizon_values, landmark_values)):
            raise ValueError("targets, horizons and landmarks must each be unique")
        if max(horizon_values, default=0) > self.max_horizon:
            raise ValueError("requested horizon exceeds the indexed maximum")
        rows: list[dict[str, Any]] = []
        for t0 in t0s:
            t0 = positive_offset(t0, "t0", minimum=0)
            if t0 >= self.n:
                raise ValueError("t0 must be within the common calendar")
            stop = min(self.n, t0 + max(horizon_values, default=0) + 1)
            vectors = self.vectors(t0, stop)
            closes = self.close[t0:stop].tolist()
            for target in target_values:
                for horizon in horizon_values:
                    outcome = classify_window(closes, horizon, target)
                    for landmark in (*[value for value in landmark_values if value < horizon], horizon):
                        riskset = landmark_riskset(closes, landmark, target_multiple=target)
                        ratio = float(closes[landmark] / closes[0]) if landmark < len(closes) and self.valid[t0] and self.valid[t0 + landmark] else None
                        for flag in FLAG_IDS:
                            values = vectors.get(flag, [None] * len(closes))
                            raw = flag_history(values, landmark)
                            before = flag_history(values, landmark, outcome.first_hit_offset)
                            offset = before.first_trigger_offset
                            applicable = flag not in {"Y1", "Y2"}
                            rows.append({
                                "t0_index": t0,
                                "target_multiple": target,
                                "horizon": horizon,
                                "landmark": landmark,
                                "scope": "full" if landmark == horizon else "landmark",
                                "flag_id": flag,
                                "flag_state": before.state if applicable else "not_applicable",
                                "first_trigger_offset": offset if applicable else None,
                                "unknown_reason": before.reason if applicable else "no_pattern_level",
                                "through_offset": before.through_offset,
                                "trigger_return": float(closes[offset] / closes[0] - 1)
                                if offset is not None and self.valid[t0] and self.valid[t0 + offset] and applicable
                                else None,
                                "raw_flag_state": raw.state if applicable else "not_applicable",
                                "raw_first_trigger_offset": raw.first_trigger_offset if applicable else None,
                                "raw_unknown_reason": raw.reason if applicable else "no_pattern_level",
                                "riskset_id": riskset.riskset_id,
                                "riskset_state": riskset.state,
                                "riskset_reason": riskset.reason,
                                "riskset_decision_offset": riskset.decision_offset,
                                "riskset_eligible": riskset.eligible,
                                "rise_ratio": ratio,
                                "rise_bin": rise_bin(ratio),
                                "calendar_full": outcome.calendar_full,
                                "label": outcome.outcome,
                                "first_hit_offset": outcome.first_hit_offset,
                                "outcome_unknown_reason": outcome.reason,
                            })
        return pd.DataFrame(rows)


def batch_event_observations(frame: pd.DataFrame, pivots: pd.DataFrame, t0s: Sequence[int], **kwargs: Any) -> pd.DataFrame:
    """Convenient diagnostic API; retain BatchFlagIndex for repeated queries."""
    horizons = kwargs.get("horizons", (126, 252))
    return BatchFlagIndex(frame, pivots, max_horizon=max(horizons)).observations(t0s, **kwargs)
