"""Close-time condition values for one adjusted symbol (`daily-conditions.v1`).

Stored in each `adjusted-daily-v1` generation beside `technical_daily`, one row per
`reference_factor_adjusted` row. The values are the per-stock ingredients of the
PR17 pattern-scan condition inventory (`pattern_scan_conditions_v1`): ratios, counts
and flags, never a study's bins or thresholds. A study keeps its own cut points
(for example PR17's `C3 >= 0.60` or `raw_return1 >= 0.095`) and applies them to
these columns.

Every formula repeats the PR17 implementation in `hhhl_variants_daily.
calculate_daily_features` and `pattern_scan_daily_values_v1.calculate_common_values`
on the same inputs, reusing their helpers where they exist, so the values are equal
to the ones PR17 stored. The tests and `scripts.check_daily_conditions` compare
against both. Indicators PR17 also used (SMA20/60/120/240, atr14_pct, BB20 bands,
BBWidth) come from the same generation's `technical_daily` columns, which
`technical_daily_v1` already proves equal to the PR17 kernels.

Left out on purpose: cross-sectional ranks (H, K3, J) and market context need the
whole eligible universe or 0050; pattern flags (F22..F25 and KL_c, PAT_other_*) and
future outcome labels stay with the studies; RSI14, ADX14, MACDHist, atr14_pct and
the raw close are already columns of `technical_daily` or the price tables.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from research_core.hhhl_variants_daily import _weekly_signal
from research_core.pattern_scan_daily_values_v1 import _any_window, _boolean, _profile, _support_resistance

LOGGER = logging.getLogger(__name__)
DEFINITION_VERSION = "daily-conditions.v1"
OHLC = ("Open", "High", "Low", "Close")
FLOAT_COLUMNS = (
    "ma_alignment",
    "sma240_change20",
    "close_to_sma240",
    "close_to_prior250_high",
    "close_to_prior250_low",
    "atr_ratio120",
    "volume_ratio20",
    "raw_return1",
    "close_location",
    "return120",
    "volume20_prior",
    "turnover20_prior",
    "close_to_sma20",
    "bb_percent_b",
    "bb_width_rank125",
    "resistance_gap_k15",
    "support_gap_k15",
    "candle_body_ratio",
    "candle_upper_shadow_ratio",
    "volume10_to_60_prior",
)
BOOL_COLUMNS = ("weekly_ma10_up", "bb_squeeze_within5", "no_resistance_k15")
STRING_COLUMNS = ("volume_profile120",)
TECHNICAL_INPUTS = ("SMA20", "SMA60", "SMA120", "SMA240", "atr14_pct", "BB20_Upper", "BB20_Lower", "BBWidth")
SCHEMA = pa.schema([
    ("Code", pa.string()),
    ("Date", pa.timestamp("ns")),
    *((name, pa.float64()) for name in FLOAT_COLUMNS),
    *((name, pa.bool_()) for name in BOOL_COLUMNS),
    *((name, pa.string()) for name in STRING_COLUMNS),
])

COLUMNS: dict[str, dict[str, str]] = {
    "ma_alignment": {
        "formula": "Count of Close>SMA20, SMA20>SMA60, SMA60>SMA120, SMA120>SMA240 (0..4); NaN unless all five are known.",
        "unit": "count",
        "pr17": "C",
    },
    "sma240_change20": {
        "formula": "SMA240 / SMA240 twenty rows earlier - 1; NaN unless the last 260 closes are all valid.",
        "unit": "fraction",
        "pr17": "C2",
    },
    "close_to_sma240": {"formula": "Close / SMA240 - 1.", "unit": "fraction", "pr17": "C3"},
    "weekly_ma10_up": {
        "formula": (
            "Previous completed ISO week: weekly close > 10-week MA of weekly closes and that MA rose; a week counts only when every row in it is valid."
        ),
        "unit": "bool",
        "pr17": "C4",
    },
    "close_to_prior250_high": {"formula": "Close / max(Close over the previous 250 rows), today excluded.", "unit": "ratio", "pr17": "D"},
    "close_to_prior250_low": {"formula": "Close / min(Close over the previous 250 rows), today excluded.", "unit": "ratio", "pr17": "D2"},
    "atr_ratio120": {
        "formula": "atr14_pct of the previous row / median(atr14_pct over the 120 rows before today); NaN when the median is not positive.",
        "unit": "ratio",
        "pr17": "F",
    },
    "volume_ratio20": {
        "formula": "VolumeLots / mean(VolumeLots over the previous 20 rows); volume is used when finite and >= 0, independent of price validity.",
        "unit": "ratio",
        "pr17": "G (non-H1 families; H1 kept its detector's own vx)",
    },
    "raw_return1": {
        "formula": "RawClose / previous row's RawClose - 1, both positive. PR17's limit-up proxy G2_limit is raw_return1 >= 0.095.",
        "unit": "fraction",
        "pr17": "G2_limit (threshold stays with the study)",
    },
    "close_location": {
        "formula": "(Close - Low) / (High - Low) on valid rows with High > Low. PR17's G2_position is close_location >= 0.75.",
        "unit": "fraction 0..1",
        "pr17": "G2_position (threshold stays with the study)",
    },
    "return120": {"formula": "Close / Close 120 rows earlier - 1; NaN unless all 121 closes are valid.", "unit": "fraction", "pr17": "ret120"},
    "volume20_prior": {
        "formula": "mean(VolumeLots over the previous 20 rows), volume counted only on rows with valid raw and research prices.",
        "unit": "lots (1,000 shares)",
        "pr17": "prior_volume20",
    },
    "turnover20_prior": {
        "formula": "mean(RawClose * VolumeLots over the previous 20 rows), same validity as volume20_prior. PR17's eligibility used >= 1,000.",
        "unit": "thousand TWD",
        "pr17": "turnover20",
    },
    "close_to_sma20": {"formula": "Close / SMA20 - 1 (SMA20 > 0).", "unit": "fraction", "pr17": "MA_a"},
    "bb_percent_b": {"formula": "(Close - BB20_Lower) / (BB20_Upper - BB20_Lower); NaN on a zero-width band.", "unit": "fraction", "pr17": "BB_a"},
    "bb_width_rank125": {
        "formula": "Share of the previous 125 BBWidth values <= today's BBWidth, x100; needs 126 consecutive known widths.",
        "unit": "percent 0..100",
        "pr17": "BB_b",
    },
    "bb_squeeze_within5": {
        "formula": (
            "True if on any of the previous 5 rows BBWidth <= min(BBWidth over the 125 rows before that row); False only when all 5 are known and none was."
        ),
        "unit": "bool",
        "pr17": "BB_c",
    },
    "resistance_gap_k15": {
        "formula": "min(confirmed 1.5 ATR high prices above Close, confirmed on or before today) / Close - 1; NaN when there is none or Close is missing.",
        "unit": "fraction",
        "pr17": "SR_a (numeric part)",
    },
    "no_resistance_k15": {
        "formula": "True when no confirmed 1.5 ATR high so far is above Close; null when Close is missing.",
        "unit": "bool",
        "pr17": "SR_a == 'none'",
    },
    "support_gap_k15": {
        "formula": "Close / max(confirmed 1.5 ATR low prices below Close, confirmed on or before today) - 1; NaN when there is none or Close is missing.",
        "unit": "fraction",
        "pr17": "SR_b",
    },
    "volume_profile120": {
        "formula": (
            "Previous 120 rows' closes split into 20 equal price bands, raw volume summed per band;"
            " 'above'/'inside'/'below' today's Close vs the heaviest band (ties: lower band)."
            " Null if any of the 120 rows or today is missing, or the range is flat."
        ),
        "unit": "category",
        "pr17": "SR_c",
    },
    "candle_body_ratio": {"formula": "|Close - Open| / (High - Low); NaN when High == Low.", "unit": "fraction 0..1", "pr17": "KL_a"},
    "candle_upper_shadow_ratio": {
        "formula": "(High - max(Open, Close)) / (High - Low); NaN when High == Low.",
        "unit": "fraction 0..1",
        "pr17": "KL_b",
    },
    "volume10_to_60_prior": {
        "formula": "mean(VolumeLots over the previous 10 rows) / mean(VolumeLots over the previous 60 rows); volume as in volume_ratio20.",
        "unit": "ratio",
        "pr17": "VOL_a",
    },
}


def definition_metadata() -> dict[str, Any]:
    """Serializable column definitions, recorded in every generation's status.json."""
    return {
        "version": DEFINITION_VERSION,
        "basis": "reference_factor_adjusted (Close, Open, High, Low); RawClose and VolumeLots from the same rows",
        "rows": "one row per reference_factor_adjusted row (same Code, Date); join on both",
        "availability": "every column at that day's close; 'previous N rows' excludes today; pivots count from confirmed_at",
        "gap_policy": (
            "An invalid row is NaN/null and every window containing it is unknown; nothing is filled or carried over."
            " NaN means unknown or warming up, never 0 or False."
        ),
        "source": "PR17 pattern-scan conditions: hhhl_variants_daily.calculate_daily_features and pattern_scan_daily_values_v1.calculate_common_values",
        "columns": COLUMNS,
    }


def _valid_rows(prepared: pd.DataFrame) -> np.ndarray:
    prices = prepared.loc[:, list(OHLC)].to_numpy(dtype=float, na_value=np.nan)
    valid = prepared["Quality"].eq(True).fillna(False).to_numpy(dtype=bool)
    valid &= np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    opening, high, low, close = prices.T
    return cast(np.ndarray, valid & (high >= low) & (opening >= low) & (opening <= high) & (close >= low) & (close <= high))


def _pivot_positions(index: pd.DatetimeIndex, pivots: pd.DataFrame) -> pd.DataFrame:
    """Technical pivots in `_support_resistance`'s positional schema."""
    frame = pivots.loc[:, ["k", "kind", "extreme_date", "confirmed_at", "price"]].copy()
    frame["extreme_index"] = index.get_indexer(pd.DatetimeIndex(frame["extreme_date"]))
    frame["confirmation_index"] = index.get_indexer(pd.DatetimeIndex(frame["confirmed_at"]))
    if (frame[["extreme_index", "confirmation_index"]] < 0).any().any():
        raise ValueError("pivot dates must be rows of the symbol's frame")
    return frame


def compute_conditions(code: str, prepared: pd.DataFrame, technical: pd.DataFrame, pivots: pd.DataFrame) -> pd.DataFrame:
    """Condition values for one symbol.

    `prepared` is one symbol's `reference_factor_adjusted` rows indexed by date (OHLC,
    Quality, RawClose, VolumeLots); `technical` and `pivots` are that symbol's
    `technical_daily_v1.compute_technical` outputs for the same rows. Rows are
    neither dropped nor filled.
    """
    index = cast(pd.DatetimeIndex, prepared.index)
    daily = technical.set_index("Date") if "Date" in technical.columns else technical
    if not daily.index.equals(index):
        raise ValueError("technical rows must match the prepared rows")
    valid = _valid_rows(prepared)
    masked = prepared.loc[:, list(OHLC)].astype(float).where(pd.Series(valid, index=index), axis=0)
    opening, high, low = (cast(pd.Series, masked[name]) for name in ("Open", "High", "Low"))
    close = cast(pd.Series, masked["Close"])
    ma20, ma60, ma120, ma240 = (cast(pd.Series, daily[name]).astype(float) for name in ("SMA20", "SMA60", "SMA120", "SMA240"))
    atr_pct = cast(pd.Series, daily["atr14_pct"]).astype(float).where(valid)
    out = pd.DataFrame(index=index)

    # hhhl_variants_daily.calculate_daily_features (C, C2, C3, C4, D, D2, F, G2_*, ret120, prior_volume20, turnover20)
    complete = pd.concat([close, ma20, ma60, ma120, ma240], axis=1).notna().all(axis=1)
    count = (close > ma20).astype(int) + (ma20 > ma60).astype(int) + (ma60 > ma120).astype(int) + (ma120 > ma240).astype(int)
    out["ma_alignment"] = count.where(complete).astype(float)
    out["sma240_change20"] = (ma240 / ma240.shift(20) - 1).where(close.rolling(260, min_periods=260).count().eq(260))
    out["close_to_sma240"] = close / ma240 - 1
    out["weekly_ma10_up"] = _weekly_signal(index, close)
    previous = close.shift(1)
    out["close_to_prior250_high"] = close / previous.rolling(250, min_periods=250).max()
    out["close_to_prior250_low"] = close / previous.rolling(250, min_periods=250).min()
    median = cast(pd.Series, atr_pct.shift(1).rolling(120, min_periods=120).median())
    out["atr_ratio120"] = (atr_pct.shift(1) / median).where(median > 0)
    raw_close = cast(pd.Series, prepared["RawClose"]).astype(float)
    raw_valid = pd.Series(np.isfinite(raw_close.to_numpy()) & (raw_close.to_numpy() > 0), index=index)
    raw_close = raw_close.where(raw_valid)
    out["raw_return1"] = (raw_close / raw_close.shift(1) - 1).where(raw_close.notna() & raw_close.shift(1).notna())
    spread = high - low
    out["close_location"] = ((close - low) / spread.where(spread > 0)).where(pd.Series(valid, index=index) & (spread > 0))
    out["return120"] = (close / close.shift(120) - 1).where(close.rolling(121, min_periods=121).count().eq(121))
    lots = cast(pd.Series, prepared["VolumeLots"]).astype(float)
    counted = lots.where(np.isfinite(lots) & (lots >= 0) & raw_valid & pd.Series(valid, index=index))
    out["volume20_prior"] = counted.shift(1).rolling(20, min_periods=20).mean()
    out["turnover20_prior"] = (raw_close * counted).shift(1).rolling(20, min_periods=20).mean()

    # pattern_scan_daily_values_v1.calculate_common_values (G, MA_a, BB_a..c, SR_a..c, KL_a/b, VOL_a)
    volume = lots.where(np.isfinite(lots) & lots.ge(0))
    prior20 = cast(pd.Series, volume.shift().rolling(20, min_periods=20).mean())
    out["volume_ratio20"] = volume / prior20.where(prior20 > 0)
    out["close_to_sma20"] = close / ma20.where(ma20 > 0) - 1
    upper, lower = cast(pd.Series, daily["BB20_Upper"]).astype(float), cast(pd.Series, daily["BB20_Lower"]).astype(float)
    band = upper - lower
    out["bb_percent_b"] = (close - lower) / band.where(band > 0)
    width = cast(pd.Series, daily["BBWidth"]).astype(float)
    out["bb_width_rank125"] = width.rolling(126, min_periods=126).apply(lambda values: np.count_nonzero(values[:-1] <= values[-1]) / 125 * 100, raw=True)
    prior_min = width.shift().rolling(125, min_periods=125).min()
    squeeze = _boolean(cast(pd.Series, width <= prior_min), cast(pd.Series, width.notna() & prior_min.notna()))
    out["bb_squeeze_within5"] = _any_window(cast(pd.Series, squeeze.shift()), 5)
    above, below = _support_resistance(pd.DataFrame({"Close": close}, index=index), _pivot_positions(index, pivots))
    out["resistance_gap_k15"] = cast(pd.Series, pd.to_numeric(above.where(above.ne("none")), errors="coerce")).astype(float)
    out["no_resistance_k15"] = pd.Series(above.eq("none"), index=index, dtype="boolean").where(above.notna())
    out["support_gap_k15"] = below
    closes, volumes = close.to_numpy(dtype=float, na_value=np.nan), volume.to_numpy(dtype=float, na_value=np.nan)
    profile: list[str | None] = [None] * len(index)
    for position in range(120, len(index)):
        profile[position] = _profile(closes[position - 120 : position], volumes[position - 120 : position], closes[position])
    out["volume_profile120"] = pd.Series(profile, index=index, dtype=object)
    candle = high - low
    denominator = candle.where(candle > 0)
    out["candle_body_ratio"] = (close - opening).abs() / denominator
    out["candle_upper_shadow_ratio"] = (high - pd.concat([opening, close], axis=1).max(axis=1)) / denominator
    prior60 = cast(pd.Series, volume.shift().rolling(60, min_periods=60).mean())
    out["volume10_to_60_prior"] = volume.shift().rolling(10, min_periods=10).mean() / prior60.where(prior60 > 0)

    frame = out.loc[:, [*FLOAT_COLUMNS, *BOOL_COLUMNS, *STRING_COLUMNS]].rename_axis("Date").reset_index()
    frame.insert(0, "Code", code)
    LOGGER.debug("Computed %s for %s rows=%d", DEFINITION_VERSION, code, len(frame))
    return frame
