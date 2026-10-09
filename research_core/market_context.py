"""Fixed, descriptive 0050 context over caller-supplied calendar observations.

Past-only computation is conditional on the input vintage, not PIT certification.
Centered retrospective rows use future prices and are not trading features.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from fractions import Fraction
from typing import Any

LOGGER = logging.getLogger(__name__)
VERSION = "benchmark-context.rules.v1"
SECURITY_ID = "TW:0050"
UP_THRESHOLD = Fraction(3, 100)
DOWN_THRESHOLD = Fraction(-3, 100)
RANGE_THRESHOLD = Fraction(8, 100)


def definition() -> dict[str, Any]:
    """Return a fresh JSON-compatible description of the fixed provisional rules."""
    return {
        "version": VERSION,
        "security_id": SECURITY_ID,
        "provisional": True,
        "intervals": 20,
        "observations": 21,
        "layers": {
            "past_only": {"start_offset": -20, "end_offset": 0, "information_cutoff_offset": 0},
            "retrospective": {"start_offset": -10, "end_offset": 10, "information_cutoff_offset": 10},
        },
        "window_return": "last / first - 1",
        "window_range": "max / min - 1",
        "units": "fraction",
        "thresholds": {"up_return_min": 0.03, "down_return_max": -0.03, "consolidation_range_max": 0.08},
        "state_precedence": ["up", "down", "consolidation", "mixed"],
        "threshold_comparison": "exact fractions of decimal input representations; inclusive boundaries",
        "usable_observations": "all 21 closes finite and strictly positive; no filling",
        "missing_reasons": ["warmup", "future_unavailable", "unusable_observations"],
        "missing_reason_precedence": ["future_unavailable", "warmup", "unusable_observations"],
        "events": {
            "order": "observation-date order separately per layer",
            "launch": "first up after a known non-up state without resumption history",
            "resumption": "first up after a known non-up state with earlier up then consolidation since last down or unknown",
            "first_known_up": "no event immediately after unknown; establishes up history",
            "reset": "down or unknown clears up and consolidation history",
            "mixed": "does not establish consolidation",
            "continuing_up": "no event",
        },
        "smoothing": None,
        "timing_caveat": "past_only is conditional on source vintage, not certified historical availability",
        "retrospective_caveat": "exploratory hindsight descriptor; cannot be consumed as a trading feature",
    }


def _validate(dates: list[str], closes: list[float | None], layer: str) -> None:
    if layer not in ("past_only", "retrospective"):
        raise ValueError("layer must be past_only or retrospective")
    if len(dates) != len(closes):
        raise ValueError("dates and closes must have equal lengths")
    previous = ""
    for value in dates:
        if not isinstance(value, str):
            raise ValueError("dates must be ISO YYYY-MM-DD strings")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("dates must be ISO YYYY-MM-DD strings") from exc
        if parsed.isoformat() != value:
            raise ValueError("dates must be ISO YYYY-MM-DD strings")
        if value <= previous:
            raise ValueError("dates must be ordered and unique")
        previous = value
    for close in closes:
        if close is not None and (isinstance(close, bool) or not isinstance(close, (int, float))):
            raise ValueError("closes must be numeric or None")


def _usable(close: float | None) -> bool:
    return close is not None and math.isfinite(close) and close > 0


def compute_context_rows(dates: list[str], closes: list[float | None], *, layer: str) -> list[dict[str, Any]]:
    """Calculate fixed windows and descriptive events without reading market data.

    Dates represent shared calendar slots; absent dates are not inferred or filled.
    Callers must convert source numeric flags and barriers into unusable closes.
    """
    _validate(dates, closes, layer)
    LOGGER.debug("Calculating benchmark context: layer=%s observations=%d", layer, len(dates))
    rows: list[dict[str, Any]] = []
    previous_state = "unknown"
    had_up = False
    had_consolidation_after_up = False
    for index, asof_date in enumerate(dates):
        start = index - (20 if layer == "past_only" else 10)
        end = index + (0 if layer == "past_only" else 10)
        missing_reason = None
        if end >= len(dates):
            missing_reason = "future_unavailable"
        elif start < 0:
            missing_reason = "warmup"
        elif not all(_usable(close) for close in closes[start : end + 1]):
            missing_reason = "unusable_observations"
        state = "unknown"
        window_return = None
        window_range = None
        if missing_reason is None:
            # Decimal-string fractions preserve exact declared boundaries without
            # a tolerance that could move a neighboring observation across them.
            window = [Fraction(str(close)) for close in closes[start : end + 1]]
            return_fraction = window[-1] / window[0] - 1
            range_fraction = max(window) / min(window) - 1
            window_return = float(return_fraction)
            window_range = float(range_fraction)
            if return_fraction >= UP_THRESHOLD:
                state = "up"
            elif return_fraction <= DOWN_THRESHOLD:
                state = "down"
            elif range_fraction <= RANGE_THRESHOLD:
                state = "consolidation"
            else:
                state = "mixed"
        event = None
        if state in ("unknown", "down"):
            had_up = False
            had_consolidation_after_up = False
        elif state == "up":
            if previous_state not in ("unknown", "up"):
                event = "resumption" if had_up and had_consolidation_after_up else "launch"
            had_up = True
        elif state == "consolidation" and had_up:
            had_consolidation_after_up = True
        rows.append({
            "security_id": SECURITY_ID,
            "asof_date": asof_date,
            "layer": layer,
            "state": state,
            "event": event,
            "information_cutoff": dates[end] if end < len(dates) else None,
            "missing_reason": missing_reason,
            "window_return": window_return,
            "window_range": window_range,
            "window_start": dates[start] if start >= 0 else None,
            "window_end": dates[end] if end < len(dates) else None,
        })
        previous_state = state
    LOGGER.debug("Calculated benchmark context: layer=%s rows=%d", layer, len(rows))
    return rows
