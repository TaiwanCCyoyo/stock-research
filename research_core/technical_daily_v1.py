"""Close-time technical indicators and confirmed ATR pivots for one adjusted symbol.

`technical-daily.v1` is stored inside each `adjusted-daily-v1` generation (see
`maintained_adjusted_daily`), computed from that generation's `reference_factor_adjusted`
rows, one output row per price row. It adds no new formula: every column delegates to
an existing shared kernel, and the three gap-reset rules agree (every invalid row
restarts all state):

- `derived_features.compute_features` (`derived-features.v1`): ATR14, atr14_pct,
  SMA5..120, EMA5..60, BB20 bands and the 1.5/4 ATR pivots.
- `feature_atlas_features.compute_features`: RSI14, ADX14 and BBWidth, unchanged.
- SMA240 and the raw MACD histogram follow the same segment reset with the atlas EMA
  kernel, matching the PR17 pattern-scan indicators exactly.

Every value is known at that day's close. Pivots are known only from `confirmed_at`;
`extreme_date` is where the extreme was, found afterwards. The daily pivot columns
therefore only say what was known that evening: whether a high/low was confirmed today,
and the price of the latest confirmed one so far.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from research_core import derived_features
from research_core.feature_atlas_features import _smooth
from research_core.feature_atlas_features import compute_features as compute_atlas

LOGGER = logging.getLogger(__name__)
DEFINITION_VERSION = "technical-daily.v1"
BASIS = "reference_factor_adjusted"
OHLC = derived_features.OHLC
PIVOT_LABELS = {1.5: "k15", 4.0: "k40"}
INDICATOR_COLUMNS = (
    "ATR14",
    "atr14_pct",
    *(f"SMA{n}" for n in derived_features.SMA_PERIODS),
    "SMA240",
    *(f"EMA{n}" for n in derived_features.EMA_PERIODS),
    "BB20_Middle",
    "BB20_Upper",
    "BB20_Lower",
    "BBWidth",
    "RSI14",
    "ADX14",
    "MACDHist",
)
PIVOT_FLAG_COLUMNS = tuple(f"Confirmed{kind}_{label}" for label in PIVOT_LABELS.values() for kind in ("High", "Low"))
PIVOT_PRICE_COLUMNS = tuple(f"Last{kind}_{label}" for label in PIVOT_LABELS.values() for kind in ("High", "Low"))
DAILY_SCHEMA = pa.schema([
    ("Code", pa.string()),
    ("Date", pa.timestamp("ns")),
    *((name, pa.float64()) for name in INDICATOR_COLUMNS),
    *((name, pa.bool_()) for name in PIVOT_FLAG_COLUMNS),
    *((name, pa.float64()) for name in PIVOT_PRICE_COLUMNS),
])
PIVOTS_SCHEMA = pa.schema([
    ("Code", pa.string()),
    ("k", pa.float64()),
    ("kind", pa.string()),
    ("extreme_date", pa.timestamp("ns")),
    ("confirmed_at", pa.timestamp("ns")),
    ("price", pa.float64()),
])


def definition_metadata() -> dict[str, Any]:
    """Serializable column definitions, recorded in every generation's status.json."""
    shared = derived_features.definition_metadata()
    return {
        "version": DEFINITION_VERSION,
        "basis": BASIS,
        "rows": "one row per reference_factor_adjusted row (same Code, Date); join on both",
        "availability": "every daily column at that day's close; pivots from confirmed_at, never extreme_date",
        "gap_policy": shared["gap_policy"] + " Values never carry over an invalid row, except Last* pivot prices (a confirmed pivot stays known).",
        "validity": shared["validity"],
        "columns": {
            "ATR14": shared["ATR14"],
            "atr14_pct": shared["atr14_pct"],
            "SMA5..SMA120": shared["SMA"]["formula"],
            "SMA240": "Arithmetic mean of 240 closes including today; requires 240 consecutive valid rows.",
            "EMA5..EMA60": shared["EMA"]["formula"],
            "BB20_Middle/Upper/Lower": shared["BB20"],
            "BBWidth": "4 * population std of 20 closes / SMA20 (fraction), feature_atlas_features bb_width20.",
            "RSI14": "Wilder RSI: gain/loss smoothed alpha=1/14 after a 14-change mean seed; 50 when both are 0 (feature_atlas_features rsi14).",
            "ADX14": "Wilder ADX14 on ATR14-normalized DI (feature_atlas_features adx14); first value after 28 valid rows.",
            "MACDHist": "EMA12-EMA26 minus its EMA9, SMA-seeded EMAs, raw price units (not divided by Close).",
            "Confirmed{High,Low}_{k15,k40}": "True on the day a high/low is confirmed at k=1.5 or 4 ATR; False otherwise (no confirmation that day).",
            "Last{High,Low}_{k15,k40}": "Price of the latest high/low confirmed on or before this day; NaN before the first confirmation.",
        },
        "pivots": shared["pivots"],
    }


def _valid_prices(prepared: pd.DataFrame) -> pd.DataFrame:
    """Mask invalid rows to NaN OHLC with Quality False, as every kernel below expects."""
    data = prepared.copy()
    prices = data.loc[:, list(OHLC)].to_numpy(dtype=float, na_value=np.nan)
    valid = data["Quality"].eq(True).fillna(False).to_numpy(dtype=bool)
    valid &= np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    opening, high, low, close = prices.T
    valid &= (high >= low) & (opening >= low) & (opening <= high) & (close >= low) & (close <= high)
    data.loc[~valid, list(OHLC)] = np.nan
    data["Quality"] = valid
    return data


def _sma240_and_macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Both over the whole quality-masked close series, as PR17 computed them.

    A 240-row window holding any NaN is NaN, so SMA240 still needs 240 consecutive valid
    closes; rolling once over the whole series (not per segment) keeps pandas' running
    sum, and so every float, identical to the PR17 values. `_smooth` resets at each NaN.
    """
    sma240 = cast(pd.Series, close.rolling(240, min_periods=240).mean())
    macd = cast(pd.Series, _smooth(close, 12, 2 / 13) - _smooth(close, 26, 2 / 27))
    return sma240, cast(pd.Series, macd - _smooth(macd, 9, 2 / 10))


def compute_technical(code: str, prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily indicators and confirmed pivots for one symbol's prepared rows.

    `prepared` is one symbol from `price_basis.prepare_prices` (or a stored basis row set),
    indexed by sorted unique dates, with OHLC, Quality and Turnover. Rows are neither
    dropped nor filled; the daily frame has the same index.
    """
    data = _valid_prices(prepared)
    daily, pivots = derived_features.compute_features(data)
    atlas_input = data.loc[:, [*OHLC, "Turnover"]].copy()
    turnover = cast(pd.Series, atlas_input["Turnover"])
    atlas_input["Turnover"] = turnover.where(np.isfinite(turnover) & (turnover >= 0))
    atlas = compute_atlas(atlas_input)
    sma240, hist = _sma240_and_macd(cast(pd.Series, data["Close"]))
    result = pd.DataFrame(index=data.index)
    for column in INDICATOR_COLUMNS:
        result[column] = daily[column] if column in daily.columns else np.nan
    result["SMA240"], result["MACDHist"] = sma240, hist
    result["BBWidth"], result["RSI14"], result["ADX14"] = atlas["bb_width20"], atlas["rsi14"], atlas["adx14"]
    for k, label in PIVOT_LABELS.items():
        for kind, name in (("high", "High"), ("low", "Low")):
            chosen = pivots.loc[(pivots["k"] == k) & (pivots["kind"] == kind)]
            confirmed = pd.Series(chosen["price"].to_numpy(), index=pd.DatetimeIndex(chosen["confirmed_at"]))
            result[f"Confirmed{name}_{label}"] = result.index.isin(confirmed.index)
            result[f"Last{name}_{label}"] = confirmed.reindex(result.index).ffill()
    frame = result.rename_axis("Date").reset_index()
    frame.insert(0, "Code", code)
    stored = pivots.loc[:, ["k", "kind", "extreme_date", "confirmed_at", "price"]].copy()
    stored.insert(0, "Code", code)
    LOGGER.debug("Computed %s for %s rows=%d pivots=%d", DEFINITION_VERSION, code, len(frame), len(stored))
    return frame, stored
