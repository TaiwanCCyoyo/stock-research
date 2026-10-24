"""Contemporaneous official-industry breadth and trading-size ranks (T3--T5).

This is a daily S6 peer reduction, unlike PR17's retrospective industry holding
return. Metadata is today's official category, not historical PIT membership.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_run import UNKNOWN_INDUSTRIES

DEFINITION_ID = "industry-breadth.v1"


@dataclass(frozen=True)
class IndustryDaily:
    breadth: pd.DataFrame
    known_peer_n: pd.DataFrame
    size_percentile: pd.DataFrame
    hot: pd.DataFrame
    small: pd.DataFrame


def prior_turnover(raw_amount: pd.Series) -> pd.Series:
    """Preceding 20 sessions' actual source amount in TWD, excluding t.

    `official_daily_price.value` supplies this amount. PR61's S6 qualification
    retains its own unchanged raw-close times volume liquidity approximation.
    """
    amount = cast(pd.Series, raw_amount.where(np.isfinite(raw_amount) & raw_amount.ge(0)))
    rolling_mean = cast(pd.Series, amount.rolling(20, min_periods=20).mean())
    return cast(pd.Series, rolling_mean.shift(1))


def industry_daily(
    eligible: pd.DataFrame,
    a4: pd.DataFrame,
    turnover20: pd.DataFrame,
    industries: Mapping[str, str],
) -> IndustryDaily:
    """Reduce the full same-day reference grid; every subject excludes itself.

    Breadth's denominator contains eligible peers with known A4, at least five.
    Size ranks include the subject among eligible, finite turnover names, with
    average percentile ranks for ties, exactly the convention of PR61's A4.
    Unknown classifications, ineligible subjects and missing values stay unknown.
    """
    if not eligible.index.equals(a4.index) or not eligible.columns.equals(a4.columns):
        raise ValueError("eligible and A4 grids must align exactly")
    if not eligible.index.equals(turnover20.index) or not eligible.columns.equals(turnover20.columns):
        raise ValueError("turnover grid must align exactly")
    if not eligible.index.is_unique or not eligible.columns.is_unique or set(industries) != set(eligible.columns):
        raise ValueError("unique full grid and complete industry metadata required")
    if eligible.isna().to_numpy().any() or not all(pd.api.types.is_bool_dtype(dtype) for dtype in eligible.dtypes):
        raise ValueError("eligibility must be a known boolean grid")
    if not np.isin(a4.to_numpy(), (-1, 0, 1)).all():
        raise ValueError("A4 states must be -1/0/1")
    breadth = pd.DataFrame(np.nan, index=eligible.index, columns=eligible.columns)
    peers = pd.DataFrame(0, index=eligible.index, columns=eligible.columns, dtype="int64")
    size = breadth.copy()
    for category in sorted(set(industries.values())):
        if category in UNKNOWN_INDUSTRIES or not category.strip():
            continue
        codes = [code for code in eligible if industries[code] == category]
        admitted = eligible[codes]
        known = admitted & a4[codes].ne(-1)
        high = known & a4[codes].eq(1)
        denominator = known.sum(axis=1).to_numpy()[:, None] - known.to_numpy(dtype=np.int64)
        numerator = high.sum(axis=1).to_numpy()[:, None] - high.to_numpy(dtype=np.int64)
        values = np.full(denominator.shape, np.nan)
        np.divide(numerator, denominator, out=values, where=(denominator >= 5) & admitted.to_numpy())
        breadth.loc[:, codes] = values
        peers.loc[:, codes] = denominator
        liquidity = turnover20[codes].where(admitted & np.isfinite(turnover20[codes]) & turnover20[codes].ge(0))
        size.loc[:, codes] = liquidity.rank(axis=1, method="average", pct=True) * 100
    hot = pd.DataFrame(np.where(breadth.notna(), breadth.ge(0.25), -1), index=breadth.index, columns=breadth.columns, dtype="int8")
    small = pd.DataFrame(np.where(size.notna(), size.lt(50), -1), index=size.index, columns=size.columns, dtype="int8")
    return IndustryDaily(breadth, peers, size, hot, small)
