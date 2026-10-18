"""Close-time technical indicators and confirmed ATR pivots for one adjusted symbol.

`technical-daily.v1` is stored inside each `adjusted-daily-v1` generation (see
`maintained_adjusted_daily`), computed from that generation's `reference_factor_adjusted`
rows, one output row per price row. It adds no new formula: every column delegates to
an existing shared kernel, and the three gap-reset rules agree (every invalid row
restarts all state):

- `derived-features.v1` (`derived_features`): ATR14, atr14_pct, SMA5..120, EMA5..60,
  BB20 bands and the 1.5/4 ATR pivots. ATR and pivots call its kernels; `_derived_daily`
  repeats its SMA/EMA/BB arithmetic on plain floats because its per-row pandas indexing
  would roughly triple a full update's compute time. `derived_features.py` itself
  is SHA-pinned by stored evidence and stays byte-identical; the tests assert equality.
- `feature_atlas_features` (`rsi14`, `adx14`, `bb_width20`): RSI14, ADX14 and BBWidth.
  `_atlas_three` repeats only those three formulas of its `_segment`, in the same order
  with the same `_smooth` kernel, instead of all ~48 atlas features; equality is tested.
- SMA240 is a whole-series 240-row rolling mean (NaN whenever the window holds an invalid
  row) and MACDHist uses the atlas EMA kernel, matching the PR17 pattern-scan values.

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


def _derived_daily(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`derived_features.compute_features`, bit for bit, without per-row pandas indexing.

    Same validation, ATR and pivot kernels; SMA/EMA/BB repeat `derived_features._convenience`
    per valid segment with the same pandas rolling calls and the same EMA arithmetic order.
    """
    prices, valid = derived_features._validate(data)
    atr = derived_features._atr(prices, valid)
    close = prices[:, 3]
    columns: dict[str, np.ndarray] = {"ATR14": atr, "atr14_pct": atr / close}
    names = [*(f"SMA{n}" for n in derived_features.SMA_PERIODS), *(f"EMA{n}" for n in derived_features.EMA_PERIODS), "BB20_Middle", "BB20_Upper", "BB20_Lower"]
    columns.update({name: np.full(len(close), np.nan) for name in names})
    starts = np.flatnonzero(valid & ~np.r_[False, valid[:-1]]) if len(valid) else np.array([], dtype=int)
    stops = np.flatnonzero(valid & ~np.r_[valid[1:], False]) + 1 if len(valid) else np.array([], dtype=int)
    for start, stop in zip(starts, stops):
        segment = close[start:stop]
        values = pd.Series(segment)
        for n in derived_features.SMA_PERIODS:
            columns[f"SMA{n}"][start:stop] = np.asarray(values.rolling(n).mean())
        for n in derived_features.EMA_PERIODS:
            if len(segment) >= n:
                ema = columns[f"EMA{n}"][start:stop]
                ema[n - 1] = float(values.iloc[:n].mean())
                alpha = 2 / (n + 1)
                for i in range(n, len(segment)):
                    ema[i] = alpha * segment[i] + (1 - alpha) * ema[i - 1]
        middle, std = values.rolling(20).mean(), values.rolling(20).std(ddof=0)
        for name, feature in (("BB20_Middle", middle), ("BB20_Upper", middle + 2 * std), ("BB20_Lower", middle - 2 * std)):
            columns[name][start:stop] = np.asarray(feature)
    pivots = derived_features._pivots(prices, valid, atr, cast(pd.DatetimeIndex, data.index))
    return pd.DataFrame(columns, index=data.index), pivots


def _atlas_three(data: pd.DataFrame) -> pd.DataFrame:
    """`feature_atlas_features.compute_features` rsi14/adx14/bb_width20, bit for bit.

    Same segmentation (any missing OHLC splits; segments shorter than 14 rows stay NaN)
    and the same pandas expressions as its `_segment`.
    """
    prices = data.loc[:, list(OHLC)].astype(float)
    output = pd.DataFrame(np.nan, index=data.index, columns=pd.Index(["bb_width20", "rsi14", "adx14"]))
    valid = cast(pd.Series, prices.notna().all(axis=1))
    for _, segment in prices.loc[valid].groupby((~valid).cumsum().loc[valid], sort=False):
        if len(segment) < 14:
            continue
        h, low, c = (cast(pd.Series, segment[column]) for column in ("High", "Low", "Close"))
        ma20 = cast(pd.Series, c.rolling(20).mean())
        width = 4 * cast(pd.Series, c.rolling(20).std(ddof=0)) / ma20
        tr = cast(pd.Series, pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1))
        atr = _smooth(tr, 14, 1 / 14)
        delta = cast(pd.Series, c.diff())
        gain = _smooth(cast(pd.Series, delta.clip(lower=0)), 14, 1 / 14)
        loss = _smooth(cast(pd.Series, (-delta).clip(lower=0)), 14, 1 / 14)
        rsi = 100 * gain / (gain + loss).replace(0, np.nan)
        rsi = rsi.mask((gain == 0) & (loss == 0), 50)
        hd, ld = cast(pd.Series, h.diff()), -cast(pd.Series, low.diff())
        plus = hd.where((hd > ld) & (hd > 0), 0).where(hd.notna())
        minus = ld.where((ld > hd) & (ld > 0), 0).where(ld.notna())
        pdi, mdi = _smooth(plus, 14, 1 / 14) / atr, _smooth(minus, 14, 1 / 14) / atr
        dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
        dx = dx.mask((pdi == 0) & (mdi == 0), 0)
        output.loc[segment.index, "bb_width20"] = width.to_numpy()
        output.loc[segment.index, "rsi14"] = rsi.to_numpy()
        output.loc[segment.index, "adx14"] = _smooth(dx, 14, 1 / 14).to_numpy()
    return output


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
    indexed by sorted unique dates, with OHLC and Quality. Rows are neither
    dropped nor filled; the daily frame has the same index.
    """
    data = _valid_prices(prepared)
    daily, pivots = _derived_daily(data)
    atlas = _atlas_three(data)
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
