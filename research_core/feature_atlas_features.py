"""Causal, scale-invariant feature proxies, not complete trading methods.

Missing OHLC sessions reset price history; missing turnover affects only
turnover features. EMA uses an SMA seed; Wilder uses an arithmetic-mean seed
followed by alpha=1/period recursion. MACD starts at observation 26, its signal
at 34, and its crossing flag at 35 after every price-history reset.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
INPUT_COLUMNS = ["Open", "High", "Low", "Close", "Turnover"]
CONTINUOUS_COLUMNS = [
    "dist_ma20",
    "dist_ma60",
    "ma60_slope20",
    "ret20",
    "ret60",
    "ret120",
    "near_high120",
    "bb_width20",
    "atr14_pct",
    "turnover_ratio20",
    "turnover_contraction5_20",
    "up_down_turnover20",
    "rsi14",
    "macd_hist_pct",
    "range20_60",
    "adx14",
]
_DEFINITIONS = [
    ("above_ma20", "trend", "Close > SMA20", 20),
    ("above_ma60", "trend", "Close > SMA60", 60),
    ("ma20_above_ma60", "trend", "SMA20 > SMA60", 60),
    ("ma60_rising", "trend", "SMA60 / SMA60.shift(20) - 1 > 0", 80),
    ("golden_cross", "trend", "SMA20 > SMA60 and prior SMA20 <= prior SMA60", 61),
    ("positive_ret20", "momentum", "Close / Close.shift(20) - 1 > 0", 21),
    ("positive_ret60", "momentum", "Close / Close.shift(60) - 1 > 0", 61),
    ("positive_ret120", "momentum", "Close / Close.shift(120) - 1 > 0", 121),
    ("breakout20", "breakout", "Close > max prior 20 High", 21),
    ("breakout60", "breakout", "Close > max prior 60 High", 61),
    ("near_high120", "breakout", "Close >= 0.95 * max 120 Close", 120),
    ("bollinger_squeeze", "volatility", "BB20 width == min width over 125 sessions", 144),
    ("bollinger_two_closes", "breakout", "two closes > contemporaneous BB20 upper", 21),
    ("squeeze_breakout", "breakout", "F13 and F12 in prior 20 sessions", 164),
    ("adx_trend", "trend", "Wilder ADX14 > 25", 28),
    ("low_atr", "volatility", "Wilder ATR14 / Close <= 0.03", 14),
    ("turnover_contraction", "turnover", "mean Turnover5 / mean Turnover20 <= 0.7", 20),
    ("turnover_expansion", "turnover", "Turnover / prior mean Turnover20 >= 1.5", 21),
    ("up_down_turnover", "turnover", "up turnover20 / down turnover20 >= 1.5", 21),
    ("spring_proxy", "recovery", "Low < prior Low20 min and Close > prior Low20 min", 21),
    ("three_session_2b_proxy", "recovery", "support=min Low[t-23:t-4]; min Low[t-3:t-1]<support; prior Close<=support<Close", 24),
    ("bullish_engulfing", "candle", "prior bear; current bull; Open<=prior Close; Close>=prior Open; prior Close<prior SMA20", 21),
    ("piercing", "candle", "prior bear; current bull; Open<prior Low; prior body midpoint<Close<prior Open; prior Close<prior SMA20", 21),
    ("bullish_harami", "candle", "prior bear; current bull; Open>=prior Close; Close<=prior Open; prior Close<prior SMA20", 21),
    ("hammer", "candle", "0<body<=0.35*range; lower wick>=2*body; upper wick<=body; prior Close<prior SMA20", 21),
    ("inside_bar_break", "candle", "prior High<=High[-2]; prior Low>=Low[-2]; Close>High[-2]", 3),
    ("rsi_recovery", "momentum", "RSI14 > 30 and prior RSI14 <= 30", 16),
    ("rsi_strength", "momentum", "50 <= RSI14 <= 70", 15),
    ("macd_cross", "momentum", "MACD > signal EMA9 and prior MACD <= prior signal", 35),
    ("macd_positive", "momentum", "MACD histogram > 0", 34),
    ("range_contraction", "volatility", "range20 / range60 <= 0.5", 60),
    ("trend_pullback", "recovery", "Close > SMA60 and return5 < 0", 60),
]
_METHOD_IDS = (
    ["LEGACY-MA"] * 5
    + ["LEGACY-MOMENTUM"] * 3
    + ["LEGACY-DONCHIAN"] * 3
    + ["M01"] * 4
    + ["LEGACY-ATR"]
    + ["LEGACY-VOLUME"] * 3
    + ["M04"]
    + ["LEGACY-2B-proxy"]
    + ["M05"] * 3
    + ["LEGACY-HAMMER"]
    + ["LEGACY-INSIDE-BAR"]
    + ["M06"] * 2
    + ["MACD-standard"] * 2
    + ["LEGACY-VCP-proxy", "LEGACY-PULLBACK"]
)
FEATURE_SPECS = {
    f"F{i:02}": {"name": name, "family": family, "source_method_ids": [_METHOD_IDS[i - 1]], "formula": formula, "lookback": lookback}
    for i, (name, family, formula, lookback) in enumerate(_DEFINITIONS, 1)
}


def _smooth(series: pd.Series, period: int, alpha: float) -> pd.Series:
    """Seed only after period consecutive observations; reset at every NaN."""
    values = np.full(len(series), np.nan)
    history: list[float] = []
    previous = np.nan
    for i, value in enumerate(series.to_numpy(dtype=float)):
        if np.isnan(value):
            history = []
            previous = np.nan
        elif np.isnan(previous):
            history.append(value)
            if len(history) == period:
                previous = float(np.mean(history))
                values[i] = previous
        else:
            previous += alpha * (value - previous)
            values[i] = previous
    return pd.Series(values, index=series.index)


def _flag(condition: pd.Series, *required: pd.Series) -> pd.Series:
    valid = pd.Series(True, index=condition.index)
    for series in required:
        valid &= series.notna()
    return condition.astype(float).where(valid)


def _series(value: object) -> pd.Series:
    """Narrow pandas' reduction/indexing unions at one-dimensional boundaries."""
    assert isinstance(value, pd.Series)
    return value


def _segment(frame: pd.DataFrame) -> pd.DataFrame:
    o, h, low, c, t = (_series(frame[column]) for column in INPUT_COLUMNS)
    result = pd.DataFrame(index=frame.index)
    ma20, ma60 = _series(c.rolling(20).mean()), _series(c.rolling(60).mean())
    result["dist_ma20"], result["dist_ma60"] = c / ma20 - 1, c / ma60 - 1
    slope = ma60 / ma60.shift(20) - 1
    result["ma60_slope20"] = slope
    for n in (20, 60, 120):
        result[f"ret{n}"] = c / c.shift(n) - 1
    high120 = _series(c.rolling(120).max())
    result["near_high120"] = c / high120
    std = _series(c.rolling(20).std(ddof=0))
    upper = ma20 + 2 * std
    width = 4 * std / ma20
    result["bb_width20"] = width
    tr = _series(pd.concat([h - low, (h - c.shift()).abs(), (low - c.shift()).abs()], axis=1).max(axis=1))
    atr = _smooth(tr, 14, 1 / 14)
    result["atr14_pct"] = atr / c
    ratio = t / _series(t.shift().rolling(20).mean()).replace(0, np.nan)
    contraction = _series(t.rolling(5).mean()) / _series(t.rolling(20).mean()).replace(0, np.nan)
    delta = _series(c.diff())
    direction_valid = delta.notna() & t.notna()
    up = _series(t.where(delta > 0, 0).where(direction_valid).rolling(20).sum())
    down = _series(t.where(delta < 0, 0).where(direction_valid).rolling(20).sum())
    ud = up / down.replace(0, np.nan)
    result["turnover_ratio20"] = ratio
    result["turnover_contraction5_20"] = contraction
    result["up_down_turnover20"] = ud
    gain = _smooth(_series(delta.clip(lower=0)), 14, 1 / 14)
    loss = _smooth(_series((-delta).clip(lower=0)), 14, 1 / 14)
    rsi = 100 * gain / (gain + loss).replace(0, np.nan)
    rsi = rsi.mask((gain == 0) & (loss == 0), 50)
    result["rsi14"] = rsi
    macd = _smooth(c, 12, 2 / 13) - _smooth(c, 26, 2 / 27)
    signal = _smooth(macd, 9, 2 / 10)
    hist = macd - signal
    result["macd_hist_pct"] = hist / c
    ranges = {n: _series(h.rolling(n).max()) - _series(low.rolling(n).min()) for n in (20, 60)}
    range_ratio = ranges[20] / ranges[60].replace(0, np.nan)
    result["range20_60"] = range_ratio
    hd, ld = _series(h.diff()), -_series(low.diff())
    plus = hd.where((hd > ld) & (hd > 0), 0).where(hd.notna())
    minus = ld.where((ld > hd) & (ld > 0), 0).where(ld.notna())
    pdi, mdi = _smooth(plus, 14, 1 / 14) / atr, _smooth(minus, 14, 1 / 14) / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    dx = dx.mask((pdi == 0) & (mdi == 0), 0)
    adx = _smooth(dx, 14, 1 / 14)
    result["adx14"] = adx

    def put(number: int, condition: object, *required: object) -> None:
        result[f"F{number:02}"] = _flag(_series(condition), *(_series(value) for value in required))

    put(1, c > ma20, ma20)
    put(2, c > ma60, ma60)
    put(3, ma20 > ma60, ma20, ma60)
    put(4, slope > 0, slope)
    put(5, (ma20 > ma60) & (ma20.shift() <= ma60.shift()), ma60, ma60.shift())
    for number, n in ((6, 20), (7, 60), (8, 120)):
        ret = result[f"ret{n}"]
        put(number, ret > 0, ret)
    for number, n in ((9, 20), (10, 60)):
        prior = h.shift().rolling(n).max()
        put(number, c > prior, prior)
    put(11, c >= 0.95 * high120, high120)
    minimum = width.rolling(125).min()
    put(12, width == minimum, minimum)
    put(13, (c > upper) & (c.shift() > upper.shift()), upper, upper.shift())
    prior_squeeze = result["F12"].shift().rolling(20).max()
    put(14, (result["F13"] == 1) & (prior_squeeze == 1), result["F13"], prior_squeeze)
    put(15, adx > 25, adx)
    put(16, result["atr14_pct"] <= 0.03, atr)
    put(17, contraction <= 0.7, contraction)
    put(18, ratio >= 1.5, ratio)
    put(19, ud >= 1.5, ud)
    support20 = low.shift().rolling(20).min()
    put(20, (low < support20) & (c > support20), support20)
    support = low.shift(4).rolling(20).min()
    recent_low = low.shift().rolling(3).min()
    put(21, (recent_low < support) & (c.shift() <= support) & (c > support), support, recent_low, c.shift())
    bear, bull = c.shift() < o.shift(), c > o
    trend = c.shift() < ma20.shift()
    body = (c - o).abs()
    candle_range = h - low
    patterns = [
        bear & bull & (o <= c.shift()) & (c >= o.shift()),
        bear & bull & (o < low.shift()) & (c > (o.shift() + c.shift()) / 2) & (c < o.shift()),
        bear & bull & (o >= c.shift()) & (c <= o.shift()),
        (body > 0)
        & (body <= 0.35 * candle_range)
        & (pd.concat([o, c], axis=1).min(axis=1) - low >= 2 * body)
        & (h - pd.concat([o, c], axis=1).max(axis=1) <= body),
    ]
    for number, pattern in enumerate(patterns, 22):
        put(number, pattern & trend, ma20.shift())
    put(26, (h.shift() <= h.shift(2)) & (low.shift() >= low.shift(2)) & (c > h.shift(2)), h.shift(2), low.shift(2))
    put(27, (rsi > 30) & (rsi.shift() <= 30), rsi, rsi.shift())
    put(28, (rsi >= 50) & (rsi <= 70), rsi)
    put(29, (hist > 0) & (hist.shift() <= 0), hist, hist.shift())
    put(30, hist > 0, hist)
    put(31, range_ratio <= 0.5, range_ratio)
    ret5 = c / c.shift(5) - 1
    put(32, (c > ma60) & (ret5 < 0), ma60, ret5)
    return result


def compute_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return aligned continuous values and float 0/1/NaN flags.

    The caller supplies positive, preadjusted OHLC and raw turnover in thousand
    TWD (a turnover adaptation, not share volume). Session rows must already be
    sorted, unique, and include missing days. M01 and M06 are components/proxies,
    not complete Bollinger Method IV or RSI divergence/failure-swing methods.
    """
    if not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError("index must be a sorted unique DatetimeIndex")
    selected = frame[INPUT_COLUMNS]
    assert isinstance(selected, pd.DataFrame)
    data = selected.astype(float)
    if np.isinf(data.to_numpy()).any() or (data[["Open", "High", "Low", "Close"]] <= 0).any().any() or (data["Turnover"] < 0).any():
        raise ValueError("OHLC must be positive and turnover nonnegative; infinity is invalid")
    output = pd.DataFrame(np.nan, index=frame.index, columns=pd.Index(CONTINUOUS_COLUMNS + list(FEATURE_SPECS)))
    prices = data[["Open", "High", "Low", "Close"]]
    assert isinstance(prices, pd.DataFrame)
    valid = _series(prices.notna().all(axis=1))
    groups = (~valid).cumsum()
    LOGGER.debug("Computing feature atlas for %d rows; %d missing sessions", len(data), (~valid).sum())
    for _, segment in data.loc[valid].groupby(groups.loc[valid], sort=False):
        assert isinstance(segment, pd.DataFrame)
        if len(segment) < 3:
            continue
        if len(segment) < 14:
            # F26 alone has enough history before ATR14's first observation.
            high, low, close = (_series(segment[column]) for column in ("High", "Low", "Close"))
            prior_high, prior_low = _series(high.shift(2)), _series(low.shift(2))
            inside_break = (high.shift() <= prior_high) & (low.shift() >= prior_low) & (close > prior_high)
            output.loc[segment.index, "F26"] = _flag(inside_break, prior_high, prior_low)
            continue
        computed = _segment(segment)
        output.loc[segment.index, computed.columns] = computed
    return output
