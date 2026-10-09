"""The point-in-time eligibility rule, in one place.

Two callers have to agree exactly or the study is broken in a way that produces plausible
numbers: `build_rotation_universe.py`, which writes the union pool, and the ranking strategy,
which decides on each bar which symbols may be ranked. Both import from here, so the rule
cannot drift between them.

The rule, evaluated for symbol `s` on date `t`:

  history    at least `MIN_HISTORY` bars strictly before `t`
  liquidity  median (Close x Volume) over the trailing `LIQ_WINDOW` bars before `t`,
             at or above `LIQ_FLOOR`
  traded     a bar exists for `s` on `t`

Nothing at or after `t` is read for the first two conditions, which is what makes this
point-in-time rather than a survivorship filter dressed up as one.

Units: `Volume` in this cache is lots (張, 1000 shares), so `Close x Volume` is turnover in
thousands of TWD. 2330 runs around 70,000,000 on that scale, i.e. NT$70bn a day.

`MIN_HISTORY` is 120 rather than the 1750 the earlier studies used. 1750 bars is about seven
years and was chosen to give every symbol a full history over the study window; it also
excludes every company that listed during the window and every one that delisted early. 120
covers the longest indicator any archetype needs (MA60) with a wide margin, which is all a
per-date rule actually requires.
"""

from __future__ import annotations

from typing import cast

import pandas as pd

MIN_HISTORY = 120
LIQ_WINDOW = 60
# Thousands of TWD. 100,000 is NT$100m of daily turnover, which puts a NT$1m position at 1%
# of a day's trade -- small enough that market impact need not be modelled, and the pool is
# then genuinely tradeable rather than nominally so. It leaves a median of 456 eligible names
# per holdout day, a rich ranking pool without an unusable tail. Run the builder with
# `--sensitivity` to see the alternatives: 200,000 gives 338 a day, 50,000 gives 612.
LIQ_FLOOR = 100_000


def add_eligibility_columns(px: pd.DataFrame) -> pd.DataFrame:
    """Attach `prior_bars` and `liquidity` (trailing median turnover), both shifted.

    `px` needs Code, Date, Close, Volume, sorted by Code then Date. Both outputs are
    computed from bars strictly before the row's own date.
    """
    out = px.copy()
    out["turnover"] = out["Close"] * out["Volume"]
    grouped = out.groupby("Code", sort=False)
    out["prior_bars"] = grouped.cumcount()
    out["liquidity"] = grouped["turnover"].transform(lambda s: s.shift(1).rolling(LIQ_WINDOW, min_periods=LIQ_WINDOW).median())
    return out


def eligible_matrix(
    px: pd.DataFrame,
    start: str,
    end: str,
    *,
    min_history: int = MIN_HISTORY,
    liq_floor: float = LIQ_FLOOR,
) -> pd.DataFrame:
    """Code / Date / eligible, restricted to the window."""
    out = add_eligibility_columns(px)
    out = out[(out["Date"] >= start) & (out["Date"] <= end)]
    out["eligible"] = (out["prior_bars"] >= min_history) & (out["liquidity"] >= liq_floor)
    return cast(pd.DataFrame, out[["Code", "Date", "eligible"]])


def is_eligible(prior_bars: int, trailing_turnovers: list[float]) -> bool:
    """Single-symbol form, for a strategy holding its own bar history.

    `trailing_turnovers` is Close x Volume for the bars strictly before the current one;
    only the last `LIQ_WINDOW` are read, and fewer than that many is not eligible, matching
    `min_periods` in the vectorised path above.
    """
    if prior_bars < MIN_HISTORY:
        return False
    window = trailing_turnovers[-LIQ_WINDOW:]
    if len(window) < LIQ_WINDOW:
        return False
    ordered = sorted(window)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return median >= LIQ_FLOOR
