"""Provisional Claude HHHL transitions on complete calendar indices.

These descriptive definitions are not final owner approval. The caller supplies
exact v1 lows mapped from detector rows to the common calendar.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral
from typing import Literal

import numpy as np
from numpy.typing import NDArray

LOGGER = logging.getLogger(__name__)
Status = Literal["stood", "failed", "unresolved", "unknown_missing_close", "unknown_window_end"]


@dataclass(frozen=True)
class Transition:
    status: Status
    anchor_index: int | None = None
    first_low_index: int | None = None
    first_low_confirm_index: int | None = None
    threshold: float | None = None
    confirmation_day_excluded: bool = False


def classify_transition(
    close: NDArray[np.float64],
    breakout_index: int,
    zone: float,
    lows: Sequence[tuple[int, int, float]],
    horizon: int = 126,
) -> Transition:
    """Scan missing, failure, then first-L confirmation in that daily order.

    Failure uses a fixed zone. Standing requires a strict threshold exceedance
    strictly after the first qualifying low's confirmation. Neither later lows nor
    elapsed days can replace that first low or establish standing.
    """
    if not isinstance(close, np.ndarray) or close.ndim != 1:
        raise ValueError("close must be a one-dimensional numpy array")
    if isinstance(breakout_index, bool) or not isinstance(breakout_index, Integral) or not 0 <= breakout_index < len(close):
        raise ValueError("breakout_index must be a valid calendar index")
    if not np.isfinite(zone):
        raise ValueError("zone must be finite")
    if isinstance(horizon, bool) or not isinstance(horizon, Integral) or horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    if not np.isfinite(close[breakout_index]):
        raise ValueError("breakout close must be finite")
    previous_confirm = -1
    first_low: tuple[int, int, float] | None = None
    for low in lows:
        if len(low) != 3:
            raise ValueError("low must contain extreme index, confirmation index, and price")
        i, cf, price = low
        if (
            isinstance(i, bool)
            or isinstance(cf, bool)
            or not isinstance(i, Integral)
            or not isinstance(cf, Integral)
            or not 0 <= i < cf < len(close)
            or cf < previous_confirm
            or not np.isfinite(price)
        ):
            raise ValueError("invalid low mapping or confirmation order")
        previous_confirm = cf
        if first_low is None and i > breakout_index and cf > breakout_index:
            first_low = low

    LOGGER.debug("Classifying HHHL breakout=%d zone=%s horizon=%d lows=%d", breakout_index, zone, horizon, len(lows))
    low_index: int | None = None
    confirm_index: int | None = None
    threshold: float | None = None
    excluded = False

    def result(status: Status, anchor: int | None = None) -> Transition:
        LOGGER.debug(
            "HHHL breakout=%d status=%s anchor=%s first_low=%s confirmation=%s threshold=%s excluded=%s",
            breakout_index,
            status,
            anchor,
            low_index,
            confirm_index,
            threshold,
            excluded,
        )
        return Transition(status, anchor, low_index, confirm_index, threshold, excluded)

    end = min(breakout_index + horizon, len(close) - 1)
    for day in range(breakout_index + 1, end + 1):
        value = close[day]
        if not np.isfinite(value):
            return result("unknown_missing_close")
        if value < zone:
            return result("failed", day)
        if first_low is not None and day == first_low[1]:
            low_index, confirm_index, _ = first_low
            threshold = float(np.max(close[breakout_index : low_index + 1]))
            excluded = bool(value > threshold)
        if threshold is not None and confirm_index is not None and day > confirm_index and value > threshold:
            return result("stood", day)
    return result("unresolved" if end == breakout_index + horizon else "unknown_window_end")
