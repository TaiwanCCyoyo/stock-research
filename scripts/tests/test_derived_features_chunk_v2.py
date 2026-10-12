"""Invented-input tests for bounded v2 identity and serializable checkpoints."""

import copy
import json
from typing import Any
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from research_core import derived_features_chunk_v2 as chunk
from research_core import derived_features_selective_v1 as v1
from research_core.artifact_store import object_digest


def frame(seed: int = 0, length: int = 160) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + 12 * np.sin(np.arange(length) / 5) + rng.uniform(-0.1, 0.1, length)
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True},
        index=pd.bdate_range("2020-01-01", periods=length, name="calendar"),
    )


def join_pivots(parts: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(parts, ignore_index=True).sort_values(["k", "confirmation_index"], kind="stable").reset_index(drop=True)


@pytest.mark.parametrize("seed", [0, 7, 33])
@pytest.mark.parametrize("cuts", [[0, 1, 13, 14, 60, 159, 160], [0, 55, 56, 57, 120, 160]])
@pytest.mark.parametrize("gap", [None, 55, 56])
def test_full_v2_equals_chunks_exactly_with_json_roundtrip(seed: int, cuts: list[int], gap: int | None):
    prepared = frame(seed)
    if gap is not None:
        prepared.loc[prepared.index[gap], "Quality"] = False
    original = prepared.copy(deep=True)
    expected_daily, expected_pivots, expected_state = chunk.compute_selected_full(prepared, v1.ALL_FEATURES)
    daily_parts, pivot_parts = [], []
    state: dict[str, Any] | None = None
    for start, stop in zip(cuts, cuts[1:]):
        previous: dict[str, Any] | None = copy.deepcopy(state)
        daily, pivots, next_state = chunk.compute_selected_chunk(prepared.iloc[start:stop], reversed(v1.ALL_FEATURES), state=state)
        assert state == previous
        assert pivots.empty or (pivots.confirmation_index >= start).all()
        daily_parts.append(daily)
        pivot_parts.append(pivots)
        state = json.loads(json.dumps(next_state, allow_nan=False))
    pd.testing.assert_frame_equal(pd.concat(daily_parts), expected_daily, check_exact=True)
    pd.testing.assert_frame_equal(join_pivots(pivot_parts), expected_pivots, check_exact=True)
    assert state == expected_state
    pd.testing.assert_frame_equal(prepared, original, check_exact=True)


@pytest.mark.parametrize("seed", [0, 7, 33])
@pytest.mark.parametrize("invalid", [None, "quality", "missing", "zero"])
def test_ema_atr_pivots_match_frozen_v1_exactly(seed: int, invalid: str | None):
    prepared = frame(seed)
    if invalid == "quality":
        prepared.loc[prepared.index[75], "Quality"] = False
    elif invalid == "missing":
        prepared.loc[prepared.index[75], "Close"] = np.nan
    elif invalid == "zero":
        prepared.loc[prepared.index[75], "Low"] = 0.0
    names = ["ATR14", "atr14_pct", "EMA5", "EMA10", "EMA20", "EMA60", "pivots_1p5", "pivots_4"]
    expected_daily, expected_pivots = v1.compute_selected(prepared, names)
    daily, pivots, state = chunk.compute_selected_full(prepared, names)
    pd.testing.assert_frame_equal(daily, expected_daily, check_exact=True)
    pd.testing.assert_frame_equal(pivots, expected_pivots, check_exact=True)
    assert state["rolling_window"] == []


def test_equal_extrema_old_extreme_new_confirmation_and_global_indices():
    close = np.r_[np.full(14, 100), 100, 96, 96, 100, 100]
    prepared = frame(length=len(close))
    for name, offset in (("Open", 0), ("Close", 0), ("High", 1), ("Low", -1)):
        prepared[name] = close + offset
    _, old_pivots, state = chunk.compute_selected_chunk(prepared.iloc[:15], ["pivots_1p5"])
    assert old_pivots.empty
    _, pivots, _ = chunk.compute_selected_chunk(prepared.iloc[15:], ["pivots_1p5"], state=state)
    assert pivots.extreme_index.tolist() == [14, 16]
    assert pivots.confirmation_index.tolist() == [15, 17]
    assert pivots.price.tolist() == [101.0, 95.0]
    _, expected = v1.compute_selected(prepared, ["pivots_1p5"])
    pd.testing.assert_frame_equal(pivots, expected, check_exact=True)


def test_rolling_distinct_identity_with_close_numeric_diagnostic():
    prepared = frame(seed=123, length=240)
    names = ["SMA5", "SMA20", "BB20_Middle", "BB20_Upper", "BB20_Lower"]
    expected, _ = v1.compute_selected(prepared, names)
    actual, _, _ = chunk.compute_selected_full(prepared, names)
    np.testing.assert_allclose(actual.to_numpy(), expected.to_numpy(), rtol=1e-12, atol=1e-12, equal_nan=True)
    # Restarted pandas accumulation has a separate last-bit identity even when
    # economic formulas are unchanged. Do not label this output as frozen v1.
    finite = np.isfinite(expected.to_numpy())
    assert np.any(actual.to_numpy()[finite] != expected.to_numpy()[finite])
    metadata = chunk.definition_metadata()
    assert metadata["version"] == "derived-features-checkpoint.v2"
    assert "last bits" in metadata["rolling_execution"]


def test_only_bounded_context_processed_for_new_rows(monkeypatch: pytest.MonkeyPatch):
    prepared = frame(length=150)
    _, _, state = chunk.compute_selected_chunk(prepared.iloc[:140], ["SMA120", "EMA10"])
    compute = Mock(wraps=v1.compute_selected)
    monkeypatch.setattr(v1, "compute_selected", compute)
    daily, _, final_state = chunk.compute_selected_chunk(prepared.iloc[140:], ["SMA120", "EMA10"], state=state)
    assert len(daily) == 10
    assert compute.call_count == 10
    assert all(len(call.args[0]) == 120 and call.args[1] == ["SMA120"] for call in compute.call_args_list)
    assert len(final_state["rolling_window"]) == 120
    assert len(final_state["ema"]["10"]["seed_values"]) == 10


def test_each_feature_has_exact_same_values_alone_or_with_all_features():
    prepared = frame(seed=27, length=145)
    prepared.loc[prepared.index[30], "Quality"] = False
    all_daily, all_pivots, _ = chunk.compute_selected_full(prepared, v1.ALL_FEATURES)
    for name in v1.ALL_FEATURES:
        daily, pivots, _ = chunk.compute_selected_full(prepared, [name])
        columns = [name] if name in v1.DAILY_FEATURES else []
        pd.testing.assert_frame_equal(daily, all_daily.loc[:, columns], check_exact=True)
        ks = [v1.PIVOT_FEATURES[name]] if name in v1.PIVOT_FEATURES else []
        expected = all_pivots.loc[all_pivots.k.isin(ks)].reset_index(drop=True)
        pd.testing.assert_frame_equal(pivots, expected, check_exact=True)


def test_rolling_periods_use_independent_windows(monkeypatch: pytest.MonkeyPatch):
    prepared = frame(length=130)
    names = ["SMA5", "SMA120", "BB20_Middle", "BB20_Upper", "BB20_Lower"]
    _, _, state = chunk.compute_selected_chunk(prepared.iloc[:129], names)
    compute = Mock(wraps=v1.compute_selected)
    monkeypatch.setattr(v1, "compute_selected", compute)
    chunk.compute_selected_chunk(prepared.iloc[129:], names, state=state)
    assert [(len(call.args[0]), call.args[1]) for call in compute.call_args_list] == [
        (5, ["SMA5"]),
        (120, ["SMA120"]),
        (20, ["BB20_Middle", "BB20_Upper", "BB20_Lower"]),
    ]


def test_empty_chunks_full_wrapper_and_gap_resets(monkeypatch: pytest.MonkeyPatch):
    prepared = frame(length=30)
    compute = Mock(wraps=chunk.compute_selected_chunk)
    monkeypatch.setattr(chunk, "compute_selected_chunk", compute)
    _, _, state = chunk.compute_selected_full(prepared, v1.ALL_FEATURES)
    assert compute.call_count == 1 and compute.call_args.kwargs == {"state": None}
    daily, pivots, same = chunk.compute_selected_chunk(prepared.iloc[:0], v1.ALL_FEATURES, state=state)
    assert daily.empty and pivots.empty and same == state
    invalid = frame(length=31).iloc[-1:].copy()
    invalid["Quality"] = False
    daily, pivots, reset = chunk.compute_selected_chunk(invalid, v1.ALL_FEATURES, state=state)
    assert np.isnan(daily.to_numpy()).all() and pivots.empty
    assert reset["row_count"] == 31 and reset["valid_run_rows"] == 0
    assert reset["rolling_window"] == [] and reset["atr"]["count"] == 0
    assert all(item["mode"] == 0 for item in reset["pivots"].values())
    assert all(item["seed_values"] == [] for item in reset["ema"].values())


def resign(state: dict) -> None:
    state["state_digest"] = object_digest({key: value for key, value in state.items() if key != "state_digest"})


@pytest.mark.parametrize(
    "case",
    [
        "version",
        "features",
        "row_type",
        "run_count",
        "last_date",
        "window_length",
        "window_order",
        "ohlc",
        "atr_count",
        "atr_seed",
        "ema_seed",
        "pivot_mode",
        "pivot_index",
        "pivot_date",
        "extra_field",
    ],
)
def test_forged_checkpoint_rejected_even_with_recomputed_digest(case: str):
    prepared = frame()
    _, _, state = chunk.compute_selected_chunk(prepared.iloc[:80], v1.ALL_FEATURES)
    if case == "version":
        state["version"] = "v1"
    elif case == "features":
        state["features"] = []
    elif case == "row_type":
        state["row_count"] = True
    elif case == "run_count":
        state["valid_run_rows"] = 1000
    elif case == "last_date":
        state["calendar_last_date"] = "2020-02-02T01:00"
    elif case == "window_length":
        state["rolling_window"].pop()
    elif case == "window_order":
        state["rolling_window"].reverse()
    elif case == "ohlc":
        state["rolling_window"][-1]["ohlc"][0] = -1
    elif case == "atr_count":
        state["atr"]["count"] = 79
    elif case == "atr_seed":
        state["atr"]["sum_tr"] = -1
    elif case == "ema_seed":
        state["ema"]["5"]["seed_values"].append(100.0)
    elif case == "pivot_mode":
        state["pivots"]["pivots_1p5"]["mode"] = 2
    elif case == "pivot_index":
        state["pivots"]["pivots_1p5"]["extreme_index"] = -1
    elif case == "pivot_date":
        state["pivots"]["pivots_1p5"]["extreme_date"] = "2099-01-01"
    else:
        state["unexpected"] = 1
    resign(state)
    with pytest.raises(ValueError, match="checkpoint"):
        chunk.compute_selected_chunk(prepared.iloc[80:], v1.ALL_FEATURES, state=state)


def test_nonfinite_checkpoint_and_digest_changes_rejected():
    prepared = frame()
    _, _, state = chunk.compute_selected_chunk(prepared.iloc[:80], ["EMA10", "ATR14"])
    state["ema"]["10"]["previous_ema"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        chunk.compute_selected_chunk(prepared.iloc[80:], ["EMA10", "ATR14"], state=state)
    _, _, state = chunk.compute_selected_chunk(prepared.iloc[:80], ["EMA10", "ATR14"])
    state["ema"]["10"]["previous_ema"] += 1
    with pytest.raises(ValueError, match="digest"):
        chunk.compute_selected_chunk(prepared.iloc[80:], ["EMA10", "ATR14"], state=state)


def test_overflow_fails_without_checkpoint_output_or_state_mutation():
    prepared = frame(length=2)
    prepared["Open"] = prepared["Close"] = 5e307
    prepared["High"] = 1e308
    prepared["Low"] = 1.0
    _, _, state = chunk.compute_selected_chunk(prepared.iloc[:1], ["ATR14"])
    original = copy.deepcopy(state)
    output = None
    with pytest.raises(ArithmeticError, match="ATR14 seed.*no checkpoint returned"):
        output = chunk.compute_selected_chunk(prepared.iloc[1:], ["ATR14"], state=state)
    assert output is None and state == original
    assert state["atr"]["previous_atr"] is None  # Genuine seed warmup only.


def test_feature_changes_and_nonappend_calendars_rejected():
    prepared = frame()
    _, _, state = chunk.compute_selected_chunk(prepared.iloc[:80], ["EMA10"])
    with pytest.raises(ValueError, match="configuration"):
        chunk.compute_selected_chunk(prepared.iloc[80:], ["EMA10", "SMA5"], state=state)
    for repeated in (prepared.iloc[79:81], prepared.iloc[:2]):
        with pytest.raises(ValueError, match="strictly later"):
            chunk.compute_selected_chunk(repeated, ["EMA10"], state=state)
    with pytest.raises(ValueError, match="calendar"):
        chunk.compute_selected_chunk(prepared.iloc[80:82].iloc[::-1], ["EMA10"], state=state)
    with pytest.raises(ValueError, match="duplicate"):
        chunk.compute_selected_full(prepared, ["EMA10", "EMA10"])


@pytest.mark.parametrize("names", [[], ["SMA5"], ["EMA10"], ["ATR14"], ["pivots_4"]])
def test_selective_configuration_and_empty_initial_state(names: list[str]):
    prepared = frame(length=20)
    empty_daily, empty_pivots, initial = chunk.compute_selected_chunk(prepared.iloc[:0], names)
    assert empty_daily.empty and empty_pivots.empty
    assert initial["row_count"] == 0 and initial["calendar_last_date"] is None
    resumed = chunk.compute_selected_chunk(prepared, names, state=json.loads(json.dumps(initial)))
    full = chunk.compute_selected_full(prepared, names)
    pd.testing.assert_frame_equal(resumed[0], full[0], check_exact=True)
    pd.testing.assert_frame_equal(resumed[1], full[1], check_exact=True)
    assert resumed[2] == full[2]
