from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core import daily_conditions_v1, live_producer, maintained_adjusted_daily, run_receipt, technical_daily_v1
from research_core.artifact_store import read_json, write_json
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame
from research_core.shared_data import ENV_KEY

# daily-conditions.v1 column -> PR17 common_values column it must equal.
NUMERIC = {
    "ma_alignment": "C",
    "sma240_change20": "C2",
    "close_to_sma240": "C3",
    "close_to_prior250_high": "D",
    "close_to_prior250_low": "D2",
    "atr_ratio120": "F",
    "volume_ratio20": "G",
    "return120": "ret120",
    "volume20_prior": "prior_volume20",
    "turnover20_prior": "turnover20",
    "close_to_sma20": "MA_a",
    "bb_percent_b": "BB_a",
    "bb_width_rank125": "BB_b",
    "support_gap_k15": "SR_b",
    "candle_body_ratio": "KL_a",
    "candle_upper_shadow_ratio": "KL_b",
    "volume10_to_60_prior": "VOL_a",
}


def _prepared(days: int = 700, gap: int | None = 450, seed: int = 11) -> pd.DataFrame:
    """One symbol shaped like a stored reference_factor_adjusted row set, with a limit-up day and a flat candle."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=days)
    close = 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.022, days)))
    close[400] = close[399] * 1.099
    high, low = close * (1 + rng.uniform(0, 0.03, days)), close * (1 - rng.uniform(0, 0.03, days))
    high[401] = low[401] = close[401]
    opening = np.clip(close * (1 + rng.normal(0, 0.01, days)), low, high)
    lots = rng.uniform(500, 5000, days)
    lots[420] = 40000.0
    frame = pd.DataFrame(
        {"Open": opening, "High": high, "Low": low, "Close": close, "RawClose": close * 1.0, "VolumeLots": lots, "Turnover": close * lots, "Quality": True},
        index=dates,
    )
    frame["quality_reason"] = None
    if gap is not None:
        frame.iloc[gap, frame.columns.get_loc("Close")] = np.nan
        frame.iloc[gap, frame.columns.get_loc("Quality")] = False
        frame.iloc[gap, frame.columns.get_loc("quality_reason")] = "missing_official_quote"
    return frame


def _conditions(prepared: pd.DataFrame) -> pd.DataFrame:
    daily, pivots = technical_daily_v1.compute_technical("9999", prepared)
    return daily_conditions_v1.compute_conditions("9999", prepared, daily, pivots).set_index("Date")


def _same(left: pd.Series | pd.DataFrame, right: pd.Series | pd.DataFrame) -> bool:
    a, b = left.astype(object).to_numpy(), right.astype(object).to_numpy()
    missing_a, missing_b = pd.isna(a), pd.isna(b)
    return bool((missing_a == missing_b).all() and all(x == y for x, y, m in zip(a, b, missing_a) if not m))


@pytest.mark.parametrize("gap", [None, 450, 80])
def test_values_equal_the_pr17_condition_kernels(gap: int | None) -> None:
    prepared = _prepared(gap=gap)
    shared = _conditions(prepared)
    detector, pivots = prepare_detector_frame(prepared)
    stored = calculate_common_values(detector, pivots)

    assert shared.index.equals(stored.index), "one row per input row"
    for column, legacy in NUMERIC.items():
        assert _same(shared[column], stored[legacy]), column
    assert _same(shared["weekly_ma10_up"], stored["C4"])
    assert _same(shared["bb_squeeze_within5"], stored["BB_c"])
    assert _same(shared["volume_profile120"], stored["SR_c"])
    # PR17's thresholded flags are the shared values with the study's cut points.
    for column, legacy, cut in (("raw_return1", "G2_limit", 0.095), ("close_location", "G2_position", 0.75)):
        implied = pd.Series(shared[column] >= cut, dtype="boolean").where(shared[column].notna())
        assert _same(implied, stored[legacy]), column
    resistance = shared["resistance_gap_k15"].astype(object).where(shared["resistance_gap_k15"].notna())
    resistance = resistance.where(~shared["no_resistance_k15"].fillna(False).astype(bool), "none")
    assert _same(resistance, stored["SR_a"])
    assert shared.loc[shared.index[400], "raw_return1"] >= 0.095, "the fixture's limit-up day is visible"
    assert pd.isna(shared.loc[shared.index[401], "candle_body_ratio"]), "a flat candle is unknown, not 0"


def test_no_column_reads_a_later_day() -> None:
    prepared = _prepared()
    full = _conditions(prepared)
    for cut in (300, 451, 600):
        prefix = _conditions(prepared.iloc[:cut])
        pd.testing.assert_frame_equal(prefix, full.iloc[:cut])


def test_an_invalid_row_is_unknown_and_restarts_windows() -> None:
    shared = _conditions(_prepared(gap=450))
    row = shared.iloc[450]
    for column in ("close_to_sma240", "close_to_sma20", "bb_percent_b", "close_location", "candle_body_ratio", "return120"):
        assert pd.isna(row[column]), column
    assert pd.isna(row["no_resistance_k15"]) and row["volume_profile120"] is None
    # 120 valid closes are needed again after the gap; previous-window values need the gap to leave the window.
    assert shared["return120"].iloc[451:571].isna().all() and shared["return120"].notna().iloc[571]
    assert shared["close_to_prior250_high"].iloc[451:701].isna().all()


OHLC_COLUMNS = ("Open", "High", "Low", "Close")


def _producer(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    prepared = _prepared(days=460, gap=None)
    rows = [
        {"Code": code, "Date": day, **{column: getattr(row, column) * scale for column in OHLC_COLUMNS}, "Volume": row.VolumeLots, "Source": "official"}
        for code, scale in (("2330", 1.0), ("6488", 0.5))
        for day, row in prepared.iterrows()
    ]
    pd.DataFrame(rows).to_parquet(root / "price_daily.parquet", index=False)
    with sqlite3.connect(root / "corporate_actions.sqlite") as connection:
        connection.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
    connection.close()
    return root


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    producer = _producer(tmp_path / "producer data")
    shared = tmp_path / "shared root"
    shared.mkdir()
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(producer))
    monkeypatch.setenv(ENV_KEY, str(shared))
    monkeypatch.setattr(run_receipt, "assert_producer_idle", lambda now=None: None)
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: [])
    return producer


def test_update_stores_conditions_that_join_the_adjusted_prices(environment: Path) -> None:
    published = maintained_adjusted_daily.update(producer_root=environment)

    frame, record = maintained_adjusted_daily.read_technical("conditions", codes=["2330"], columns=["close_to_sma240", "raw_return1"], prices=["Close"])
    prices, _ = maintained_adjusted_daily.read_adjusted_daily("reference_factor_adjusted", codes=["2330"])
    assert record["generation"] == published["generation"] and record["definition"] == daily_conditions_v1.DEFINITION_VERSION
    assert frame[["Code", "Date", "Close"]].equals(prices[["Code", "Date", "Close"]])
    daily, pivots = technical_daily_v1.compute_technical("2330", prices.set_index("Date"))
    expected = daily_conditions_v1.compute_conditions("2330", prices.set_index("Date"), daily, pivots)
    pd.testing.assert_series_equal(frame["close_to_sma240"], expected["close_to_sma240"])
    status = maintained_adjusted_daily.current_generation()
    assert status["technical"]["tables"]["conditions"]["rows"] == status["bases"]["reference_factor_adjusted"]["rows"]
    stored_columns = {*daily_conditions_v1.FLOAT_COLUMNS, *daily_conditions_v1.BOOL_COLUMNS, *daily_conditions_v1.STRING_COLUMNS}
    assert set(status["technical"]["conditions_definition"]["columns"]) == stored_columns


def test_a_generation_without_conditions_is_refused(environment: Path) -> None:
    maintained_adjusted_daily.update(producer_root=environment)
    status = maintained_adjusted_daily.current_generation()
    directory = Path(status["path"])
    recorded = read_json(directory / "status.json")
    del recorded["technical"]["tables"]["conditions"]
    (directory / "status.json").unlink()
    write_json(directory / "status.json", recorded)
    with pytest.raises(ValueError, match="has no 'conditions' table"):
        maintained_adjusted_daily.read_technical("conditions", generation=status["generation"])
