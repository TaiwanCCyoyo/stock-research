"""Synthetic regressions for vectorized variants paths and event histories."""

from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_observations import classify_window, flag_history
from research_core.hhhl_variants_paths import event_flag_records, outcomes_for_closes


@pytest.mark.parametrize("horizon", [1, 5, 126, 252])
def test_all_anchors_match_shared_reference(horizon: int) -> None:
    rng = np.random.default_rng(37)
    prices = rng.choice([0.0, 30.0, 80.0, 100.0, 200.0, 250.0, np.nan, np.inf], 280)
    result = outcomes_for_closes(prices, horizon)
    for t0, row in enumerate(result.to_dict("records")):
        expected = classify_window(prices[t0:].tolist(), horizon)
        assert row["label"] == expected.outcome
        assert row["calendar_full"] == expected.calendar_full
        assert row["full_path"] == expected.full_path
        assert row["main_eligible"] == expected.main_eligible
        assert row["unknown_reason"] == expected.reason
        assert (None if pd.isna(row["first_hit_offset"]) else row["first_hit_offset"]) == expected.first_hit_offset
        assert (None if pd.isna(row["first_missing_offset"]) else row["first_missing_offset"]) == expected.first_missing_offset


@pytest.mark.parametrize("horizon", [126, 252])
def test_full_horizon_terminal_and_censored_hit(horizon: int) -> None:
    path = np.full(horizon + 1, 100.0)
    path[2], path[-1] = 200.0, 80.0
    full = outcomes_for_closes(path, horizon).iloc[0]
    assert full["hit_then_below_anchor"] and not full["hit_endpoint_unknown"]
    path[3] = np.nan
    missing = outcomes_for_closes(path, horizon).iloc[0]
    assert missing["label"] == "hit" and missing["main_eligible"] and not missing["full_path"]
    path[-1] = np.nan
    assert outcomes_for_closes(path, horizon).iloc[0]["hit_endpoint_unknown"]
    censored = outcomes_for_closes(path[:5], horizon).iloc[0]
    assert censored["label"] == "hit" and not censored["main_eligible"]
    assert censored["hit_endpoint_unknown"]


@pytest.mark.parametrize(
    "prices", [[100, np.nan, 200, 70], [100, 90, np.nan, 70], [100, 200, np.nan, 70], [100, 80, 200, np.nan], [100, 200, 80, 100], [0, 80, 200, 50]]
)
def test_drawdown_history_matches_shared_reference(prices: list[float]) -> None:
    values = np.asarray(prices, dtype=float)
    horizon = 5
    result = outcomes_for_closes(values, horizon)
    for t0, row in enumerate(result.to_dict("records")):
        anchor = values[t0]
        path = values[t0:]
        hit = classify_window(path.tolist(), horizon).first_hit_offset
        for threshold, name, pre in ((0.9, "drawdown10", "before_hit10"), (0.8, "drawdown20", "before_hit20")):
            flags = [bool(value <= threshold * anchor) if np.isfinite(value) and value > 0 and np.isfinite(anchor) and anchor > 0 else None for value in path]
            for state_name, first_name, cutoff_hit in (
                (f"{name}_full_state", f"{name}_full_first_trigger_offset", None),
                (f"{pre}_state", f"{pre}_first_trigger_offset", hit),
            ):
                expected = flag_history(flags, horizon, cutoff_hit)
                assert row[state_name] == expected.state
                assert (None if pd.isna(row[first_name]) else row[first_name]) == expected.first_trigger_offset


def _records(prices: list[float], **kwargs: Any) -> list[dict]:
    values = np.asarray(prices, dtype=float)
    return event_flag_records(values, np.full(len(values), 95.0), np.full(len(values), 90.0), 0, 80.0, 110.0, 60.0, **kwargs)


def _flag(records: list[dict], name: str, landmark: int) -> dict:
    return next(record for record in records if record["flag_id"] == name and record["landmark"] == landmark)


def test_support_failure_kept_in_new_riskset_and_legacy_distinct() -> None:
    records = _records([100, 70, 110, 100], low_pivots=[], horizons=(3,), landmarks=(1, 2))
    row = _flag(records, "X2", 2)
    assert row["flag_state"] == "triggered" and row["first_trigger_offset"] == 1
    assert row["riskset_eligible"] and row["legacy_state"] == "early_failed"
    assert row["rise_ratio"] == 1.1 and row["rise_bin"] == "b1p10_1p25"
    assert row["trigger_return"] == pytest.approx(-0.3)


def test_same_day_hit_and_flag_never_precedes_it() -> None:
    records = _records([100, 120, 200, 100], low_pivots=[(0, 2, 70.0)], horizons=(3,), landmarks=(2,))
    row = _flag(records, "X4", 2)
    assert row["raw_flag_state"] == "triggered"
    assert row["flag_state"] == "all_false" and row["through_offset"] == 1
    assert row["riskset_state"] == "early_hit"


def test_confirmation_after_t0_accepts_earlier_extreme_and_missing_daily_close() -> None:
    records = _records([100, np.nan, 110, 100], low_pivots=[(0, 2, 70.0)], horizons=(3,), landmarks=(2,))
    x4 = _flag(records, "X4", 2)
    x2 = _flag(records, "X2", 2)
    assert x4["flag_state"] == "triggered" and x4["first_trigger_offset"] == 2
    assert x2["flag_state"] == "unknown" and x2["unknown_reason"] == "missing_before_trigger"
    assert x4["riskset_state"] == "early_unknown"


def test_landmark_endpoint_counts_and_t0_is_ignored() -> None:
    records = _records([100, 110, 85, 200], low_pivots=[], horizons=(3,), landmarks=(2,))
    row = _flag(records, "X6_15", 2)
    assert row["flag_state"] == "triggered" and row["first_trigger_offset"] == 2
    assert _flag(records, "X1", 2)["first_trigger_offset"] == 2
    assert _flag(records, "X6_15", 3)["first_trigger_offset"] == 2


def test_full_126_and_252_flag_scopes_and_missing_support() -> None:
    prices = np.full(253, 100.0)
    records = event_flag_records(prices, prices, prices, 0, np.nan, 100.0, 80.0, [])
    assert len(records) == 80
    assert {(row["horizon"], row["landmark"]) for row in records if row["scope"] == "full"} == {(126, 126), (252, 252)}
    assert all(row["riskset_eligible"] for row in records)
    assert all(row["flag_state"] == "unknown" for row in records if row["flag_id"] in {"X2", "X4"})
    assert all(row["legacy_reason"] == "invalid_support" for row in records)


def test_empty_and_invalid_inputs() -> None:
    assert outcomes_for_closes(np.array([]), 126).empty
    with pytest.raises(ValueError, match="horizon"):
        outcomes_for_closes(np.ones(3), True)
    with pytest.raises(ValueError, match="one-dimensional"):
        outcomes_for_closes(np.ones((2, 2)), 2)
    with pytest.raises(ValueError, match="equal length"):
        event_flag_records(np.ones(3), np.ones(2), np.ones(3), 0, 1, 1, 1, [])
    with pytest.raises(ValueError, match="invalid supplied"):
        _records([100, 100], low_pivots=[(1, 0, 70.0)])
