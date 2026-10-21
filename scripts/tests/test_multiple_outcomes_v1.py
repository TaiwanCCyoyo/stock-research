"""Synthetic checks for multiple-target outcomes against the fixed 2x reference."""

from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_paths import outcomes_for_closes
from research_core.multiple_outcomes_v1 import COLUMNS, DEFINITION_ID, outcomes_for_targets

TARGETS = (2.0, 3.0, 5.0, 10.0)


def _row(close: list[float], horizon: int, target: float) -> dict[str, Any]:
    frame = outcomes_for_targets(np.asarray(close, dtype=float), horizon, (target,))[target]
    return frame.to_dict("records")[0]


@pytest.mark.parametrize("horizon", [1, 5, 126, 252, 504])
def test_target_two_equals_fixed_reference(horizon: int) -> None:
    rng = np.random.default_rng(20261021)
    prices = rng.choice([0.0, 30.0, 80.0, 100.0, 200.0, 250.0, 1000.0, np.nan, np.inf], 620)
    expected = outcomes_for_closes(prices, horizon).loc[:, list(COLUMNS)]
    result = outcomes_for_targets(prices, horizon, TARGETS)[2.0]
    pd.testing.assert_frame_equal(result, expected)


def test_joint_scan_equals_separate_scans() -> None:
    rng = np.random.default_rng(7)
    prices = np.cumprod(rng.choice([0.8, 1.0, 1.25, 1.6, np.nan], 700))
    joint = outcomes_for_targets(prices, 504, TARGETS)
    for target in TARGETS:
        pd.testing.assert_frame_equal(joint[target], outcomes_for_targets(prices, 504, (target,))[target])


@pytest.mark.parametrize(("target", "label", "offset"), [(2.0, "hit", 1), (5.0, "hit", 3), (10.0, "loss", None)])
def test_each_target_takes_its_own_first_crossing(target: float, label: str, offset: int | None) -> None:
    row = _row([10.0, 25.0, 40.0, 50.0, 9.0], 4, target)
    assert row["label"] == label
    assert (None if pd.isna(row["first_hit_offset"]) else row["first_hit_offset"]) == offset


def test_exact_multiple_is_a_hit() -> None:
    row = _row([10.0, 100.0, 1.0], 2, 10.0)
    assert row["label"] == "hit" and row["first_hit_offset"] == 1
    assert row["hit_then_below_anchor"] and not row["hit_endpoint_unknown"]


def test_missing_before_hit_is_unknown_but_hit_before_missing_stays() -> None:
    missing_first = _row([10.0, np.nan, 50.0, 50.0], 3, 5.0)
    assert missing_first["label"] == "unknown" and missing_first["unknown_reason"] == "missing_before_hit"
    assert not missing_first["main_eligible"]
    hit_first = _row([10.0, 50.0, np.nan, 50.0], 3, 5.0)
    assert hit_first["label"] == "hit" and hit_first["main_eligible"] and not hit_first["full_path"]


def test_loss_flat_win_censored_and_invalid_anchor() -> None:
    assert _row([10.0, 20.0, 9.9], 2, 3.0)["label"] == "loss"
    assert _row([10.0, 20.0, 10.0], 2, 3.0)["label"] == "flat-win"
    censored = _row([10.0, 20.0], 3, 3.0)
    assert censored["label"] == "unknown" and censored["unknown_reason"] == "window_end" and not censored["calendar_full"]
    censored_hit = _row([10.0, 40.0], 3, 3.0)
    assert censored_hit["label"] == "hit" and not censored_hit["main_eligible"]
    invalid = _row([0.0, 40.0, 40.0], 2, 3.0)
    assert invalid["label"] == "unknown" and invalid["unknown_reason"] == "invalid_anchor"


@pytest.mark.parametrize("targets", [(), (1.0,), (0.5,), (np.inf,), (np.nan,), (True,), (2.0, 2.0), "2", ("3",)])
def test_invalid_targets_are_rejected(targets: object) -> None:
    with pytest.raises(ValueError):
        outcomes_for_targets(np.array([10.0, 20.0]), 1, targets)  # type: ignore[arg-type]


def test_definition_identity_is_versioned() -> None:
    assert DEFINITION_ID == "multiple-outcomes.v1"
