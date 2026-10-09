from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research_core.feature_atlas_outcomes import binary_comparison, labels


def series(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": values, "Quality": True}, index=pd.bdate_range("2024-01-01", periods=len(values)))


def test_exact_horizon_includes_last_session_and_excludes_anchor_from_extrema() -> None:
    frame = series([100.0] + [80.0] * 19 + [90.0] + [500.0] * 106)
    result = labels(frame)
    first = result.iloc[0]
    assert first["complete_20"]
    assert first["forward_return_20"] == pytest.approx(-0.1)
    assert first["max_return_20"] == pytest.approx(-0.1)
    assert first["min_return_20"] == pytest.approx(-0.2)
    assert first["max_drawdown_20"] == pytest.approx(0.2)
    assert first["observed_sessions_20"] == 20
    assert result.index.equals(frame.index)
    assert first["wait_to_threshold_63"] == 21
    assert first["label_63"] == 1
    assert first["complete_126"]
    assert not result.iloc[1]["complete_126"]


def test_threshold_at_exact_horizon_and_future_peak_to_trough() -> None:
    frame = series([100.0] * 63 + [150.0] + [100.0] * 62 + [200.0])
    first = labels(frame).iloc[0]
    assert first["wait_to_threshold_63"] == 63
    assert first["wait_to_threshold_126"] == 126
    assert first["label_63"] == first["label_126"] == 1
    assert first["max_drawdown_126"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("invalid", [np.nan, np.inf, 0.0, -1.0])
def test_delisting_or_invalid_gap_is_unknown_not_shifted_stock_bars(invalid: float) -> None:
    frame = series([100.0] * 127)
    frame.iloc[20, frame.columns.get_loc("Close")] = invalid
    first = labels(frame).iloc[0]
    assert first["unknown_reason_63"] == "missing_or_invalid_path"
    assert first["observed_sessions_63"] == 62
    for name in ("forward_return", "max_return", "min_return", "max_drawdown", "wait_to_threshold", "label"):
        assert pd.isna(first[f"{name}_63"])


def test_quality_anchor_and_tail_censorship_are_unknown() -> None:
    frame = series([100.0] * 127)
    frame.iloc[0, frame.columns.get_loc("Quality")] = False
    result = labels(frame)
    assert result.iloc[0]["unknown_reason_63"] == "missing_or_invalid_path"
    assert result.iloc[-1]["unknown_reason_63"] == "window_end"
    assert result.iloc[-1]["observed_sessions_63"] == 0
    assert pd.isna(result.iloc[-1]["label_63"])
    assert result.iloc[1]["label_63"] == 0
    assert pd.isna(result.iloc[1]["wait_to_threshold_63"])


def test_threshold_hit_does_not_override_later_unsupported_event() -> None:
    frame = series([100.0] + [200.0] * 126)
    frame.iloc[50, frame.columns.get_loc("Quality")] = False
    first = labels(frame).iloc[0]
    assert not first["complete_63"]
    assert pd.isna(first["label_63"])
    assert pd.isna(first["wait_to_threshold_63"])
    assert first["unknown_reason_63"] == "missing_or_invalid_path"
    flat = labels(series([100.0] * 127)).iloc[0]
    assert flat["complete_126"]
    assert flat["label_126"] == 0


def comparison_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "base_eligible": [True] * 7 + [False],
        "F01": pd.array([1, 1, 0, 0, 1, None, None, 1], dtype="Int64"),
        "label_63": pd.array([1, 0, 1, 0, None, 1, None, 1], dtype="Int64"),
        "label_126": pd.array([0] * 8, dtype="Int64"),
        "year": [2024] * 4 + [2025] * 4,
        "regime": ["up", "up", "down", "down", "up", "up", None, "up"],
        "security_id": ["A", "A", "B", "B", "C", "D", "E", "Z"],
        "asof_date": ["2024-01-01"] * 4 + ["2025-01-01"] * 4,
    })


def test_hand_checked_confusion_counts_missing_features_and_bounds() -> None:
    row = binary_comparison(comparison_frame(), ["F01"], [])[0]
    assert {key: row[key] for key in ("tp", "fp", "fn", "tn")} == dict(tp=1, fp=1, fn=1, tn=1)
    assert row["n_eligible"] == 7
    assert row["n_feature_known"] == 5
    assert row["n_feature_missing"] == 2
    assert row["n_label_known"] == 5
    assert row["n_label_unknown"] == 2
    assert row["selected_known"] == 2
    assert row["selected_unknown"] == 1
    assert row["winner_coverage"] == row["precision"] == row["nonwinner_among_selected"] == 0.5
    assert row["same_context_base_rate"] == 0.5
    assert row["lift"] == 1
    assert row["precision_lower"] == pytest.approx(1 / 3)
    assert row["precision_upper"] == pytest.approx(2 / 3)
    assert row["n_distinct_securities"] == 5
    assert row["n_distinct_dates"] == 2


def test_individual_contexts_zero_denominators_and_json_safety() -> None:
    output = binary_comparison(comparison_frame(), ["F01"], ["year", "regime"])
    assert len(output) == (1 + 2 + 3) * 2
    assert all(row["descriptive_not_independent"] for row in output)
    year_2025 = next(row for row in output if row["context_column"] == "year" and row["context_value"] == 2025 and row["label"] == "label_63")
    assert year_2025["precision"] is None
    assert year_2025["same_context_base_rate"] is None
    assert year_2025["precision_lower"] == 0
    assert year_2025["precision_upper"] == 1
    up = next(row for row in output if row["context_column"] == "regime" and row["context_value"] == "up" and row["label"] == "label_63")
    assert up["precision"] == up["same_context_base_rate"] == 0.5
    assert up["winner_coverage"] == 1
    assert up["selected_unknown"] == 1
    zero_winners = next(row for row in output if row["context_column"] is None and row["label"] == "label_126")
    assert zero_winners["winner_coverage"] is None
    assert zero_winners["lift"] is None
    assert zero_winners["precision"] == 0
    json.dumps(output, allow_nan=False)


def test_empty_eligible_pool_and_invalid_binary_values() -> None:
    frame = comparison_frame()
    frame["base_eligible"] = False
    row = binary_comparison(frame, ["F01"], ["year"])[0]
    assert row["n_eligible"] == 0
    assert row["precision_upper"] is None
    frame.loc[0, "base_eligible"] = True
    frame.loc[0, "F01"] = 2
    with pytest.raises(ValueError, match="F01"):
        binary_comparison(frame, ["F01"], [])
