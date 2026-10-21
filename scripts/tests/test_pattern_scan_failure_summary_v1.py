from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_selection import split_for_code
from research_core.pattern_scan_failure_summary_v1 import FIRST_COLUMNS, HOLDING_COLUMNS, PATH_COLUMNS, FailureAccumulator
from research_core.pattern_scan_followup_v1 import FollowupTables


def _inputs(code: str = "TW:0001") -> tuple[FollowupTables, pd.DataFrame]:
    rows = []
    for position, label in enumerate(("hit", "loss", "unknown")):
        rows.append({
            "group_id": "g",
            "target_pattern_id": "R1",
            "security_id": code,
            "event_id": f"{code}:e{position}",
            "t0": f"2020-01-0{position + 2}",
            "calendar_index": position,
            "horizon": 3,
            "mkt": "up",
            "base_label": label,
            "effective_label": label,
            "calendar_full": True,
            "event_main_eligible": label != "unknown",
            "event_eligibility_excluded": False,
            "base_first_hit_offset": 2 if label == "hit" else None,
        })
    paths = pd.DataFrame([
        {
            **row,
            "path_category": ["rise_then_fall", "direct_failure", "unknown"][index],
            "max_return": [1.1, -0.1, None][index],
            "peak_offset": [2, 1, None][index],
        }
        for index, row in enumerate(rows)
    ])
    first = pd.DataFrame([
        {
            **row,
            "first_flag_state": "unknown" if index == 2 else "triggered",
            "first_flag_flag_id": ["X6_10", "Y1", None][index],
            "first_flag_offset": [1, 2, None][index],
            "first_flag_all_flag_ids_json": ['["X6_10","Y1"]', '["Y1"]', "[]"][index],
        }
        for index, row in enumerate(rows)
    ])
    metadata = pd.DataFrame(rows)
    holding = pd.DataFrame([
        {
            "security_id": code,
            "calendar_index": index,
            "horizon": 3,
            "t0": row["t0"],
            "calendar_full": True,
            "observed_sessions": 3,
            "own_return": [-0.2, -0.3, 0.5][index],
            "benchmark_return": [0.1, 0.2, 0.3][index],
            "peer_return": [None, 0.4, 0.5][index],
            "holding_up_fraction": 1 / 3,
            "holding_down_fraction": 0.0,
            "holding_consolidation_fraction": 0.0,
            "holding_mixed_fraction": 1 / 3,
            "holding_unknown_fraction": 1 / 3,
        }
        for index, row in enumerate(rows)
    ])
    return FollowupTables(paths, metadata.copy(), metadata.copy(), first), holding


def _cell(frame: pd.DataFrame, population: str, **fields: Any) -> Any:
    values = {"population": population, "split_id": split_for_code("0001"), "era": "all", "mkt": "all", **fields}
    mask = pd.Series(True, index=frame.index)
    for name, value in values.items():
        mask &= cast(pd.Series, frame[name]).eq(value)
    return cast(Any, frame.loc[mask].iloc[0])


@pytest.fixture(scope="module")
def result() -> Any:
    tables, holding = _inputs()
    accumulator = FailureAccumulator({"g": "R1"}, horizons=(3,))
    accumulator.add_stock(tables, holding)
    return accumulator.finalize()


def test_paths_are_separated_by_effective_population_and_endpoint_never_relabels(result: Any) -> None:
    hit = _cell(result.path_by_outcome, "hit", path_category="rise_then_fall")
    nonhit = _cell(result.path_by_outcome, "nonhit", path_category="direct_failure")
    assert hit["path_n"] == nonhit["path_n"] == 1
    assert hit["max_return_median"] == 1.1 and hit["peak_offset_median"] == 2
    assert nonhit["max_return_median"] == -0.1 and nonhit["peak_offset_median"] == 1
    holding = _cell(result.holding_by_outcome, "hit")
    assert holding["own_return_median"] == -0.2  # An earlier hit can finish below its anchor.
    assert holding["population"] == "hit" and holding["main_eligible_n"] == 1


def test_unknown_outcome_has_independent_metric_known_diagnostics(result: Any) -> None:
    row = _cell(result.holding_by_outcome, "unknown")
    assert row["event_n"] == row["unknown_label_n"] == 1 and row["main_eligible_n"] == 0
    assert row["sample_n"] == row["own_return_known_n"] == 1 and row["own_return_median"] == 0.5
    assert "unknown outcome remains unknown" in row["numeric_sample_scope"]
    path = _cell(result.path_by_outcome, "unknown", path_category="unknown")
    assert path["max_return_known_n"] == 0 and path["max_return_unknown_n"] == 1
    assert pd.isna(path["max_return_median"])


def test_holding_state_proportions_and_missing_peers_remain_independent(result: Any) -> None:
    hit = _cell(result.holding_by_outcome, "hit")
    assert hit["peer_return_known_n"] == 0 and hit["peer_return_unknown_n"] == 1
    assert pd.isna(hit["peer_return_median"])
    assert hit["benchmark_return_median"] == 0.1
    assert hit["holding_unknown_fraction_median"] == pytest.approx(1 / 3)
    assert hit["holding_up_fraction_median"] == pytest.approx(1 / 3)
    assert hit["holding_down_fraction_median"] == 0


def test_first_flag_primary_and_all_same_day_ties_are_not_additive(result: Any) -> None:
    first = _cell(result.first_flag_by_outcome, "hit", flag_id="X6_10", first_state="triggered")
    tie = _cell(result.first_flag_by_outcome, "hit", flag_id="Y1", first_state="triggered")
    assert first["first_n"] == first["same_day_tie_n"] == 1
    assert first["first_day_median"] == 1
    assert tie["first_n"] == 0 and tie["same_day_tie_n"] == 1
    unknown = _cell(result.first_flag_by_outcome, "unknown", flag_id="unknown", first_state="unknown")
    assert unknown["first_day_known_n"] == 0 and unknown["first_day_unknown_n"] == 1


def test_excluded_known_label_and_censored_unknown_never_enter_distributions() -> None:
    tables, holding = _inputs()
    for frame in (tables.paths, tables.first_flags, tables.flags, tables.landmarks):
        frame.loc[1, "event_main_eligible"] = False
        frame.loc[1, "event_eligibility_excluded"] = True
        frame.loc[2, "calendar_full"] = False
    holding.loc[2, "calendar_full"] = False
    holding.loc[2, "observed_sessions"] = 2
    accumulator = FailureAccumulator({"g": "R1"}, horizons=(3,))
    accumulator.add_stock(tables, holding)
    output = accumulator.finalize()
    nonhit = _cell(output.path_by_outcome, "nonhit", path_category="direct_failure")
    assert nonhit["event_n"] == nonhit["excluded_n"] == 1
    assert nonhit["sample_n"] == nonhit["path_n"] == 0 and pd.isna(nonhit["max_return_median"])
    unknown = _cell(output.holding_by_outcome, "unknown")
    assert unknown["event_n"] == unknown["censored_n"] == 1
    assert unknown["sample_n"] == unknown["own_return_known_n"] == 0


def test_exact_streaming_quantiles_use_raw_numeric_samples_not_stock_medians() -> None:
    second_code = next(code for code in ("0002", "0003", "0004") if split_for_code(code) == split_for_code("0001"))
    first, holding = _inputs()
    second, second_holding = _inputs("TW:" + second_code)
    new_paths: list[dict[str, Any]] = []
    new_first: list[dict[str, Any]] = []
    new_metadata: list[dict[str, Any]] = []
    for index, value in enumerate((3.0, 4.0, 5.0)):
        identifier = f"TW:{second_code}:extra{index}"
        for frame, target in ((second.paths, new_paths), (second.first_flags, new_first), (second.flags, new_metadata)):
            record = cast(dict[str, Any], frame.iloc[0].to_dict())
            record["event_id"] = identifier
            if "max_return" in record:
                record["max_return"] = value
            target.append(record)
    feed = FollowupTables(
        pd.concat([second.paths, pd.DataFrame(new_paths)], ignore_index=True),
        pd.concat([second.flags, pd.DataFrame(new_metadata)], ignore_index=True),
        pd.concat([second.landmarks, pd.DataFrame(new_metadata)], ignore_index=True),
        pd.concat([second.first_flags, pd.DataFrame(new_first)], ignore_index=True),
    )
    feed.paths.loc[0, "max_return"] = 2
    accumulator = FailureAccumulator({"g": "R1"}, horizons=(3,))
    accumulator.add_stock(first, holding)
    accumulator.add_stock(feed, second_holding)
    row = _cell(accumulator.finalize().path_by_outcome, "hit", path_category="rise_then_fall")
    assert row["max_return_known_n"] == 5
    assert row["max_return_median"] == 3
    assert row["distinct_stock_n"] == 2
    assert accumulator.memory_nbytes > 0 and accumulator.memory_nbytes % 8 == 0
    with pytest.raises(AttributeError):
        setattr(accumulator, "memory_nbytes", 0)


def test_duplicate_and_invalid_feed_rollback_before_registering_stock() -> None:
    tables, holding = _inputs()
    accumulator = FailureAccumulator({"g": "R1"}, horizons=(3,))
    accumulator.add_stock(tables, holding)
    before = accumulator.finalize()
    memory = accumulator.memory_nbytes
    with pytest.raises(ValueError, match="duplicate stock/group"):
        accumulator.add_stock(tables, holding)
    invalid, invalid_holding = _inputs("TW:0009")
    invalid_holding.loc[2, "t0"] = "2020-01-09"
    with pytest.raises(ValueError, match="matching fixed-clock"):
        accumulator.add_stock(invalid, invalid_holding)
    assert accumulator.memory_nbytes == memory
    pd.testing.assert_frame_equal(accumulator.finalize().holding_by_outcome, before.holding_by_outcome)
    invalid_holding.loc[2, "t0"] = "2020-01-04"
    accumulator.add_stock(invalid, invalid_holding)


@pytest.mark.parametrize("change", ["duplicate_holding", "projection_mismatch", "future_trigger", "first_unknown_with_day"])
def test_join_and_first_clock_mismatches_fail_closed(change: str) -> None:
    tables, holding = _inputs()
    if change == "duplicate_holding":
        holding = pd.concat([holding, holding.iloc[[0]]], ignore_index=True)
    elif change == "projection_mismatch":
        tables.first_flags.loc[0, "effective_label"] = "unknown"
        tables.first_flags.loc[0, "event_main_eligible"] = False
    elif change == "future_trigger":
        tables.first_flags.loc[0, "first_flag_offset"] = 4
    else:
        tables.first_flags.loc[2, "first_flag_offset"] = 1
    accumulator = FailureAccumulator({"g": "R1"}, horizons=(3,))
    with pytest.raises(ValueError):
        accumulator.add_stock(tables, holding)
    assert accumulator.memory_nbytes == 0


def test_empty_finalization_registers_three_populations_and_zero_schemas() -> None:
    accumulator = FailureAccumulator({"empty": "R3"}, horizons=(3,))
    output = accumulator.finalize()
    assert tuple(output.path_by_outcome.columns) == PATH_COLUMNS
    assert tuple(output.first_flag_by_outcome.columns) == FIRST_COLUMNS
    assert tuple(output.holding_by_outcome.columns) == HOLDING_COLUMNS
    assert len(output.holding_by_outcome) == 48 * 3
    assert set(output.holding_by_outcome["population"]) == {"hit", "nonhit", "unknown"}
    assert np.asarray(output.path_by_outcome["event_n"]).sum() == 0
    assert pd.isna(_cell(output.holding_by_outcome, "hit")["own_return_median"])
