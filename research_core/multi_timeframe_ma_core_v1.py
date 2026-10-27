"""Pure S7 cutoff mathematics; no reader, calendar inference or cross-stock state.

``completed_weekly`` is a caller assertion, not calendar verification. Each input
is a private snapshot, and MA consumers require the exact originating object.
Past daily bull states must be preserved by the caller at their own cutoffs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

import numpy as np
import pandas as pd
from numpy.typing import NDArray

PERIODS = (20, 60, 120)
UNKNOWN, FALSE, TRUE = -1, 0, 1
_Scalar = TypeVar("_Scalar", bound=np.generic)


def _readonly(values: NDArray[_Scalar]) -> NDArray[_Scalar]:
    result = values.copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True, eq=False)
class CutoffSeries:
    security_id: str
    generation: str
    decision_cutoff: pd.Timestamp
    price_basis: str
    bar_kind: str
    bar_dates: pd.DatetimeIndex
    close: NDArray[np.float64]
    valid: NDArray[np.bool_]

    def __post_init__(self) -> None:
        for name in ("security_id", "generation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be nonempty, unpadded text")
        if self.price_basis != "reference_factor_adjusted":
            raise ValueError("price_basis must be reference_factor_adjusted")
        if self.bar_kind not in ("daily", "completed_weekly"):
            raise ValueError("bar_kind must be daily or completed_weekly")
        cutoff = self.decision_cutoff
        if not isinstance(cutoff, pd.Timestamp) or pd.isna(cutoff) or cutoff.tz is not None or cutoff != cutoff.normalize():
            raise ValueError("decision_cutoff must be a timezone-naive normalized daily Timestamp")
        dates = self.bar_dates
        if not isinstance(dates, pd.DatetimeIndex) or dates.tz is not None or dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing:
            raise ValueError("bar_dates must be unique, increasing, timezone-naive and nonmissing")
        if any(day != day.normalize() for day in dates):
            raise ValueError("bar_dates must be normalized daily labels")
        if len(dates) and dates[-1] > cutoff:
            raise ValueError("bar_dates extend beyond decision_cutoff")
        for name, dtype in (("close", np.dtype("float64")), ("valid", np.dtype("bool"))):
            values = getattr(self, name)
            if type(values) is not np.ndarray or values.dtype != dtype or values.ndim != 1 or len(values) != len(dates):
                raise ValueError(f"{name} must be a one-dimensional {dtype} ndarray aligned to bar_dates")
        object.__setattr__(self, "bar_dates", dates.copy(deep=True))
        object.__setattr__(self, "close", _readonly(self.close))
        object.__setattr__(self, "valid", _readonly(self.valid))


@dataclass(frozen=True, eq=False)
class MovingAverages:
    sma: dict[int, NDArray[np.float64]]
    ema: dict[int, NDArray[np.float64]]
    valid: NDArray[np.bool_]
    reasons: dict[str, NDArray[np.bool_]]
    _source: CutoffSeries | None = field(default=None, init=False, repr=False)


@dataclass(frozen=True)
class BullState:
    state: int
    strong_state: int
    reasons: tuple[str, ...]
    strong_reasons: tuple[str, ...]


@dataclass(frozen=True, eq=False)
class RatioCross:
    ratio: NDArray[np.float64]
    previous_ratio: NDArray[np.float64]
    cross50: NDArray[np.int8]
    cross70: NDArray[np.int8]
    reasons: dict[str, NDArray[np.bool_]]


@dataclass(frozen=True)
class DensityState:
    # Fixed order: SMA20/60/120, EMA20/60/120; unknown operands use None.
    values: tuple[float | None, ...]
    denominator: float | None
    density: float | None
    known: bool
    reasons: tuple[str, ...]


def moving_averages(series: CutoffSeries) -> MovingAverages:
    """All-history, gap-reset SMA/EMA in the public oracle's arithmetic order.

    Input validity supplies OHLC/factor eligibility. Finite positive close is
    checked here too. A numeric failure stays unknown until the recurrence can
    produce a finite value or an invalid bar resets its state; it never seeds
    from a shorter history or becomes zero.
    """
    if not isinstance(series, CutoffSeries):
        raise TypeError("series must be CutoffSeries")
    close = series.close
    valid = series.valid & np.isfinite(close) & (close > 0)
    reasons = {"invalid_upstream": ~series.valid, "invalid_close": ~np.isfinite(close) | (close <= 0)}
    sma = {n: np.full(len(close), np.nan, dtype=np.float64) for n in PERIODS}
    ema = {n: np.full(len(close), np.nan, dtype=np.float64) for n in PERIODS}
    starts = np.flatnonzero(valid & ~np.r_[False, valid[:-1]]) if len(valid) else np.array([], dtype=int)
    stops = np.flatnonzero(valid & ~np.r_[valid[1:], False]) + 1 if len(valid) else np.array([], dtype=int)
    for n in PERIODS:
        warmup = np.zeros(len(close), dtype=np.bool_)
        with np.errstate(over="ignore", invalid="ignore"):
            for start, stop in zip(starts, stops):
                segment = close[start:stop]
                values = pd.Series(segment)
                sma[n][start:stop] = np.asarray(values.rolling(n).mean())
                warmup[start : min(stop, start + n - 1)] = True
                if len(segment) >= n:
                    current = ema[n][start:stop]
                    current[n - 1] = float(values.iloc[:n].mean())
                    alpha = 2 / (n + 1)
                    for i in range(n, len(segment)):
                        current[i] = alpha * segment[i] + (1 - alpha) * current[i - 1]
        for kind, output in (("sma", sma[n]), ("ema", ema[n])):
            reasons[f"{kind}_warmup_{n}"] = warmup.copy()
            reasons[f"{kind}_nonfinite_{n}"] = valid & ~warmup & ~np.isfinite(output)
            output[~np.isfinite(output)] = np.nan
    result = MovingAverages(
        sma={n: _readonly(sma[n]) for n in PERIODS},
        ema={n: _readonly(ema[n]) for n in PERIODS},
        valid=_readonly(valid),
        reasons={name: _readonly(mask) for name, mask in reasons.items()},
    )
    object.__setattr__(result, "_source", series)
    return result


def _check_lineage(series: CutoffSeries, ma: MovingAverages) -> None:
    if not isinstance(series, CutoffSeries) or not isinstance(ma, MovingAverages) or ma._source is not series:
        raise ValueError("MA lineage must be the exact originating CutoffSeries object")


def _close_reasons(series: CutoffSeries, ma: MovingAverages, position: int, name: str) -> list[str]:
    if position < 0:
        return [f"{name}:insufficient_history"]
    return [f"{name}:{cause}" for cause in ("invalid_upstream", "invalid_close") if ma.reasons[cause][position]]


def _average_reasons(ma: MovingAverages, kind: str, n: int, position: int, name: str) -> list[str]:
    if position < 0:
        return [f"{name}:insufficient_history"]
    causes = ("invalid_upstream", "invalid_close", f"{kind}_warmup_{n}", f"{kind}_nonfinite_{n}")
    return [f"{name}:{cause}" for cause in causes if ma.reasons[cause][position]]


def bull_at_cutoff(series: CutoffSeries, ma: MovingAverages) -> BullState:
    """Describe only the last supplied bar; every operand must be known first."""
    _check_lineage(series, ma)
    if not len(series.close):
        return BullState(UNKNOWN, UNKNOWN, ("empty_series",), ("empty_series",))
    last = len(series.close) - 1
    reasons = _close_reasons(series, ma, last, "close") + _close_reasons(series, ma, last - 20, "lag20_close")
    reasons += _average_reasons(ma, "sma", 20, last, "sma20")
    reasons += _average_reasons(ma, "ema", 20, last, "ema20") + _average_reasons(ma, "ema", 20, last - 1, "previous_ema20")
    state = (
        UNKNOWN
        if reasons
        else int(series.close[last] > ma.sma[20][last] and series.close[last] > series.close[last - 20] and ma.ema[20][last] > ma.ema[20][last - 1])
    )
    strong_reasons = reasons + _average_reasons(ma, "sma", 60, last, "sma60") + _average_reasons(ma, "sma", 120, last, "sma120")
    strong = UNKNOWN if strong_reasons else int(state == TRUE and ma.sma[20][last] > ma.sma[60][last] > ma.sma[120][last])
    return BullState(state, strong, tuple(reasons), tuple(strong_reasons))


def ratio_cross(states: NDArray[np.int8]) -> RatioCross:
    """Consume preserved per-cutoff D states in the caller's common-session order.

    Integer arrays with only -1/0/1 are accepted; bool and floats are rejected.
    No price history is accepted or reconstructed here.
    """
    if type(states) is not np.ndarray or states.ndim != 1 or not np.issubdtype(states.dtype, np.integer) or not np.isin(states, (UNKNOWN, FALSE, TRUE)).all():
        raise ValueError("states must be a one-dimensional integer ndarray containing only -1/0/1 (not bool)")
    ratio = np.full(len(states), np.nan, dtype=np.float64)
    short = np.arange(len(states)) < 19
    unknown = np.zeros(len(states), dtype=np.bool_)
    for i in range(19, len(states)):
        window = states[i - 19 : i + 1]
        unknown[i] = bool(np.any(window == UNKNOWN))
        if not unknown[i]:
            ratio[i] = np.count_nonzero(window == TRUE) / 20
    previous = np.full(len(states), np.nan, dtype=np.float64)
    previous[1:] = ratio[:-1]
    comparable = np.isfinite(ratio) & np.isfinite(previous)
    crosses = {}
    for threshold in (0.50, 0.70):
        cross = np.full(len(states), UNKNOWN, dtype=np.int8)
        cross[comparable] = ((previous[comparable] < threshold) & (ratio[comparable] >= threshold)).astype(np.int8)
        crosses[threshold] = _readonly(cross)
    return RatioCross(
        _readonly(ratio),
        _readonly(previous),
        crosses[0.50],
        crosses[0.70],
        {
            name: _readonly(mask)
            for name, mask in {
                "insufficient_history": short,
                "unknown_in_window": unknown,
                "current_ratio_unknown": ~np.isfinite(ratio),
                "previous_ratio_unknown": ~np.isfinite(previous),
            }.items()
        },
    )


def weekly_turn(*, confirmed_today: int, previous: int, current: int) -> int:
    """Pure confirmation gate; calendar and once-only confirmation are upstream."""
    for value in (confirmed_today, previous, current):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value not in (UNKNOWN, FALSE, TRUE):
            raise ValueError("weekly states must be integers -1/0/1, not bool")
    if confirmed_today != TRUE:
        return int(confirmed_today)
    if previous == UNKNOWN or current == UNKNOWN:
        return UNKNOWN
    return int(previous == FALSE and current == TRUE)


def density_at_cutoff(series: CutoffSeries, ma: MovingAverages) -> DensityState:
    """Population std of the last six weekly MAs / same-cutoff WeeklyClose."""
    _check_lineage(series, ma)
    if series.bar_kind != "completed_weekly":
        raise ValueError("density requires caller-confirmed completed_weekly bars")
    if not len(series.close):
        return DensityState((None,) * 6, None, None, False, ("empty_series",))
    last = len(series.close) - 1
    reasons = _close_reasons(series, ma, last, "denominator")
    denominator = float(series.close[last]) if not reasons else None
    values: list[float | None] = []
    for kind, averages in (("sma", ma.sma), ("ema", ma.ema)):
        for n in PERIODS:
            missing = _average_reasons(ma, kind, n, last, f"{kind}{n}")
            reasons += missing
            values.append(None if missing else float(averages[n][last]))
    if reasons:
        return DensityState(tuple(values), denominator, None, False, tuple(reasons))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        density = float(np.std(np.asarray(values, dtype=np.float64), ddof=0) / series.close[last])
    if not np.isfinite(density):
        return DensityState(tuple(values), denominator, None, False, ("density_nonfinite",))
    return DensityState(tuple(values), denominator, density, True, ())
