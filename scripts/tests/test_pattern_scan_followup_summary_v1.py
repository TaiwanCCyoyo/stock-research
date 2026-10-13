from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_selection import split_for_code
from research_core.pattern_scan_flags_v1 import FLAG_IDS
from research_core.pattern_scan_followup_summary_v1 import (
    EXCLUSION_COLUMNS,
    FIRST_COLUMNS,
    FLAG_COLUMNS,
    LANDMARK_COLUMNS,
    PATH_COLUMNS,
    TRADEOFF_COLUMNS,
    FollowupAccumulator,
    summarize_followup,
)
from research_core.pattern_scan_followup_v1 import FollowupTables


def _tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    common = []
    for index, label in enumerate(("loss", "flat-win", "hit", "hit", "unknown", "loss")):
        common.append({
            "group_id": "group",
            "target_pattern_id": "R1",
            "security_id": "0001",
            "event_id": f"e{index}",
            "t0": "2020-01-02",
            "horizon": 5,
            "mkt": "up",
            "effective_label": label,
            "event_main_eligible": index < 4,
            "calendar_full": True,
            "event_eligibility_excluded": index == 5,
            "result_quality_reasons_json": '["unexplained_jump"]' if index == 4 else "[]",
        })
    paths = pd.DataFrame([
        {**row, "path_category": "unknown" if index == 3 else "sideways", "max_return": [0.1, 0.2, 0.3, None, 0.8, 0.9][index]}
        for index, row in enumerate(common)
    ])
    first = pd.DataFrame([
        {
            **row,
            "first_flag_state": "unknown" if index in (1, 3) else "triggered",
            "first_flag_flag_id": None if index in (1, 3) else "Y1",
            "first_flag_offset": None if index in (1, 3) else 1,
            "first_flag_all_flag_ids_json": "[]" if index in (1, 3) else '["Y1","X6_10"]',
        }
        for index, row in enumerate(common)
    ])
    flags, landmarks = [], []
    for index, row in enumerate(common):
        for flag in FLAG_IDS:
            state = "unknown" if index in (1, 3) and flag == "Y1" else "triggered" if flag == "Y1" else "all_false"
            record = {
                **row,
                "flag_id": flag,
                "flag_state": state,
                "raw_flag_state": "triggered",
                "trigger_return": [-0.1, None, 0.02, None, 0.5, 0.8][index] if state == "triggered" else None,
            }
            flags.append(record)
            landmarks.append({
                **record,
                "landmark": 2,
                "riskset_id": "new_no_hit_valid_prefix",
                "riskset_eligible": True,
                "rise_bin": ["lt1", "b1_1p10", "b1p10_1p25", "ge1p25", None, "lt1"][index],
            })
    return paths, first, pd.DataFrame(flags), pd.DataFrame(landmarks)


@pytest.fixture(scope="module")
def summaries() -> Any:
    return summarize_followup(*_tables(), groups={"group": "R1"}, horizons=(5,), landmarks_at=(2,))


def _cell(table: pd.DataFrame, **extra: Any) -> Any:
    values = {"split_id": split_for_code("0001"), "era": "all", "mkt": "all", **extra}
    mask = pd.Series(True, index=table.index)
    for name, value in values.items():
        mask &= cast(pd.Series, table[name]).eq(value)
    return cast(Any, table.loc[mask].iloc[0])


def test_full_nonhit_and_hit_cost_rates_keep_unknown_bounds_and_effective_population(summaries: Any) -> None:
    row = _cell(summaries.flag_summary, flag_id="Y1")
    assert row["event_n"] == 6 and row["known_n"] == 4
    assert row["unknown_label_n"] == row["excluded_n"] == 1
    assert row["nonhit_triggered_n"] == row["nonhit_unknown_n"] == 1
    assert row["nonhit_known_rate"] == 1 and row["nonhit_lower"] == 0.5 and row["nonhit_upper"] == 1
    assert row["hit_cost_triggered_n"] == row["hit_cost_unknown_n"] == 1
    assert row["hit_cost_known_rate"] == 1 and row["hit_cost_lower"] == 0.5
    assert row["trigger_return_n"] == 2 and row["trigger_return_median"] == pytest.approx(-0.04)
    false_flag = _cell(summaries.flag_summary, flag_id="X6_10")
    assert false_flag["nonhit_known_rate"] == false_flag["hit_cost_known_rate"] == 0
    assert false_flag["nonhit_all_false_n"] == 2  # Raw triggered fields never requalify or replace before-hit history.


def test_path_quantiles_and_unknown_diagnostic_counts_are_separate(summaries: Any) -> None:
    known = _cell(summaries.path_summary, path_category="sideways")
    assert known["path_n"] == known["max_gain_known_n"] == 3
    assert known["max_gain_median"] == 0.2 and known["max_gain_q25"] == pytest.approx(0.15)
    assert known["max_gain_q75"] == pytest.approx(0.25)
    unknown = _cell(summaries.path_summary, path_category="unknown")
    assert unknown["path_n"] == unknown["max_gain_unknown_n"] == 1
    assert pd.isna(unknown["max_gain_median"])


def test_first_flag_ties_do_not_multiply_primary_event_counts(summaries: Any) -> None:
    first = _cell(summaries.first_flag_summary, flag_id="Y1", first_state="triggered")
    tie = _cell(summaries.first_flag_summary, flag_id="X6_10", first_state="triggered")
    assert first["first_n"] == 2 and first["same_day_tie_n"] == 2
    assert tie["first_n"] == 0 and tie["same_day_tie_n"] == 2
    unknown = _cell(summaries.first_flag_summary, flag_id="unknown", first_state="unknown")
    assert unknown["first_n"] == 2


def test_landmark_state_return_and_unknown_outcome_are_independent(summaries: Any) -> None:
    pooled = _cell(summaries.landmark_summary, flag_id="Y1", landmark=2, flag_state="triggered", return_bin="pooled")
    assert pooled["hit_n"] == pooled["loss_n"] == pooled["unknown_n"] == 1
    assert pooled["excluded_n"] == 1
    assert pooled["hit_rate"] == 0.5
    assert pooled["hit_lower"] == pytest.approx(1 / 3) and pooled["hit_upper"] == pytest.approx(2 / 3)
    assert pooled["unknown_return_n"] == 1
    exact = _cell(summaries.landmark_summary, flag_id="Y1", landmark=2, flag_state="triggered", return_bin="b1p10_1p25")
    assert exact["hit_n"] == 1 and exact["loss_n"] == 0


def test_tradeoff_points_share_full_population_and_x6_axes(summaries: Any) -> None:
    point = _cell(summaries.tradeoff_points, flag_id="Y1")
    assert point["nonhit_trigger_rate"] == point["hit_before_target_cost"] == 1
    assert point["nonhit_population_n"] == point["hit_population_n"] == 2
    assert len(summaries.tradeoff_points) == 48 * 9
    assert set(summaries.tradeoff_points["flag_id"]) == set(FLAG_IDS)


def test_zero_facets_include_unknown_market_and_both_splits_without_all_split(summaries: Any) -> None:
    zero = _cell(summaries.flag_summary, flag_id="Y1", mkt="unknown", era="2010-2012")
    assert zero["event_n"] == zero["nonhit_all_n"] == 0
    assert pd.isna(zero["nonhit_known_rate"]) and pd.isna(zero["nonhit_lower"])
    assert set(summaries.flag_summary["split_id"]) == {"development", "cross-check"}
    assert len(summaries.landmark_summary) == 48 * 9 * 3 * 5


def test_exclusions_keep_reason_scope_and_deduplicate_full_flag_event_copies(summaries: Any) -> None:
    reason = _cell(summaries.exclusions, source_table="flags", reason_scope="result_quality", reason="unexplained_jump")
    assert reason["event_n"] == 1
    excluded = _cell(summaries.exclusions, source_table="flags", reason_scope="population", reason="event_eligibility_excluded")
    assert excluded["event_n"] == 1


def test_empty_registry_tables_keep_exact_schemas_and_registered_zero_cells() -> None:
    empty = tuple(table.iloc[:0] for table in _tables())
    result = summarize_followup(*empty, groups={"empty": "R3"}, horizons=(5,), landmarks_at=())
    assert tuple(result.path_summary.columns) == PATH_COLUMNS
    assert tuple(result.first_flag_summary.columns) == FIRST_COLUMNS
    assert tuple(result.flag_summary.columns) == FLAG_COLUMNS
    assert tuple(result.landmark_summary.columns) == LANDMARK_COLUMNS and result.landmark_summary.empty
    assert tuple(result.tradeoff_points.columns) == TRADEOFF_COLUMNS
    assert tuple(result.exclusions.columns) == EXCLUSION_COLUMNS
    assert len(result.flag_summary) == 48 * 9
    assert np.asarray(result.flag_summary["event_n"]).sum() == 0


def test_riskset_excludes_a_hit_before_landmark_without_changing_full_hit_cost() -> None:
    paths, first, flags, landmarks = _tables()
    mask = cast(pd.Series, landmarks["event_id"]).eq("e2")
    landmarks.loc[mask, "riskset_eligible"] = False
    result = summarize_followup(paths, first, flags, landmarks, groups={"group": "R1"}, horizons=(5,), landmarks_at=(2,))
    landmark = _cell(result.landmark_summary, flag_id="Y1", landmark=2, flag_state="triggered", return_bin="pooled")
    assert landmark["hit_n"] == 0
    assert _cell(result.flag_summary, flag_id="Y1")["hit_cost_triggered_n"] == 1


@pytest.mark.parametrize("change", ["legacy_riskset", "duplicate", "eligible_unknown", "bad_bin"])
def test_invalid_population_or_clock_contract_fails_closed(change: str) -> None:
    paths, first, flags, landmarks = _tables()
    if change == "legacy_riskset":
        landmarks.loc[0, "riskset_id"] = "legacy_active"
    elif change == "duplicate":
        flags = pd.concat([flags, flags.iloc[[0]]], ignore_index=True)
    elif change == "eligible_unknown":
        flags.loc[0, "effective_label"] = "unknown"
    else:
        landmarks.loc[0, "rise_bin"] = "invented_bin"
    with pytest.raises(ValueError):
        summarize_followup(paths, first, flags, landmarks, groups={"group": "R1"}, horizons=(5,), landmarks_at=(2,))


def test_flag_diagnostic_cannot_requalify_a_different_event_projection() -> None:
    paths, first, flags, landmarks = _tables()
    excluded = cast(pd.Series, flags["event_id"]).eq("e5")
    flags.loc[excluded, "event_main_eligible"] = True
    flags.loc[excluded, "event_eligibility_excluded"] = False
    with pytest.raises(ValueError, match="change population"):
        summarize_followup(paths, first, flags, landmarks, groups={"group": "R1"}, horizons=(5,), landmarks_at=(2,))


def _stock_tables(code: str, *, extra_triggers: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tables = list(_tables())
    for table_index, table in enumerate(tables):
        table["security_id"] = code
        if extra_triggers:
            for event, value in (("e0", 1.0), ("e2", 2.0)):
                mask = cast(pd.Series, table["event_id"]).eq(event)
                if "trigger_return" in table:
                    mask &= cast(pd.Series, table["flag_id"]).eq("Y1")
                    table.loc[mask, "trigger_return"] = value
            additions = []
            for index, value in enumerate((3.0, 4.0, 5.0)):
                addition = table.loc[cast(pd.Series, table["event_id"]).eq("e0")].copy()
                addition["event_id"] = f"extra{index}"
                if "trigger_return" in addition:
                    addition.loc[cast(pd.Series, addition["flag_id"]).eq("Y1"), "trigger_return"] = value
                additions.append(addition)
            table = pd.concat([table, *additions], ignore_index=True)
        table["event_id"] = code + ":" + cast(pd.Series, table["event_id"]).astype(str)
        tables[table_index] = table
    return tables[0], tables[1], tables[2], tables[3]


def _as_feed(tables: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> FollowupTables:
    paths, first, flags, landmarks = tables
    return FollowupTables(paths=paths, flags=flags, landmarks=landmarks, first_flags=first)


def _canonical(frame: pd.DataFrame) -> pd.DataFrame:
    keys = [
        name
        for name in (
            "group_id",
            "target_pattern_id",
            "horizon",
            "split_id",
            "era",
            "mkt",
            "path_category",
            "flag_id",
            "first_state",
            "landmark",
            "flag_state",
            "return_bin",
            "source_table",
            "reason_scope",
            "reason",
        )
        if name in frame.columns
    ]
    return frame.sort_values(keys, kind="stable").reset_index(drop=True)


@pytest.fixture(scope="module")
def streaming_result() -> tuple[Any, Any, FollowupAccumulator]:
    second_code = next(code for code in ("0002", "0003", "0004") if split_for_code(code) == split_for_code("0001"))
    first, second = _stock_tables("0001"), _stock_tables(second_code, extra_triggers=True)
    joined = tuple(pd.concat([left, right], ignore_index=True) for left, right in zip(first, second, strict=True))
    oracle = summarize_followup(joined[0], joined[1], joined[2], joined[3], groups={"group": "R1"}, horizons=(5,), landmarks_at=(2,))
    accumulator = FollowupAccumulator({"group": "R1"}, horizons=(5,), landmarks_at=(2,))
    accumulator.add_stock(_as_feed(first))
    accumulator.add_stock(_as_feed(second))
    return oracle, accumulator.finalize(), accumulator


def test_streaming_two_stocks_matches_concatenated_oracle_including_zeros(streaming_result: tuple[Any, Any, FollowupAccumulator]) -> None:
    oracle, streamed, _ = streaming_result
    for name in ("path_summary", "first_flag_summary", "flag_summary", "landmark_summary", "tradeoff_points", "exclusions"):
        pd.testing.assert_frame_equal(_canonical(getattr(streamed, name)), _canonical(getattr(oracle, name)))


def test_streaming_retains_exact_uneven_trigger_samples_not_averaged_medians(streaming_result: tuple[Any, Any, FollowupAccumulator]) -> None:
    _, streamed, _ = streaming_result
    row = _cell(streamed.flag_summary, flag_id="Y1")
    assert row["trigger_return_n"] == 7
    assert row["trigger_return_median"] == 2
    assert row["distinct_stock_n"] == 2
    assert row["nonhit_triggered_n"] == 5


def test_streaming_numeric_memory_measurement_is_read_only(streaming_result: tuple[Any, Any, FollowupAccumulator]) -> None:
    _, _, accumulator = streaming_result
    assert accumulator.memory_nbytes > 0 and accumulator.memory_nbytes % 8 == 0
    with pytest.raises(AttributeError):
        setattr(accumulator, "memory_nbytes", 0)


def test_duplicate_feed_and_invalid_feed_leave_accumulated_state_unchanged() -> None:
    accumulator = FollowupAccumulator({"group": "R1"}, horizons=(5,), landmarks_at=())
    initial = list(_stock_tables("0001"))
    initial[3] = initial[3].iloc[:0]
    accumulator.add_stock(_as_feed((initial[0], initial[1], initial[2], initial[3])))
    before = accumulator.finalize()
    memory = accumulator.memory_nbytes
    with pytest.raises(ValueError, match="duplicate stock/group"):
        accumulator.add_stock(_as_feed((initial[0], initial[1], initial[2], initial[3])))
    invalid = list(_stock_tables("0009"))
    invalid[3] = invalid[3].iloc[:0]
    invalid[1].loc[0, "first_flag_all_flag_ids_json"] = '["invalid"]'
    with pytest.raises(ValueError, match="ties"):
        accumulator.add_stock(_as_feed((invalid[0], invalid[1], invalid[2], invalid[3])))
    assert accumulator.memory_nbytes == memory
    after = accumulator.finalize()
    pd.testing.assert_frame_equal(after.flag_summary, before.flag_summary)
    invalid[1].loc[0, "first_flag_all_flag_ids_json"] = '["Y1","X6_10"]'
    accumulator.add_stock(_as_feed((invalid[0], invalid[1], invalid[2], invalid[3])))
    assert accumulator.memory_nbytes > memory


def test_streaming_empty_finalization_has_registered_zero_schema() -> None:
    accumulator = FollowupAccumulator({"group": "R1"}, horizons=(5,), landmarks_at=())
    tables = tuple(table.iloc[:0] for table in _tables())
    accumulator.add_stock(_as_feed((tables[0], tables[1], tables[2], tables[3])))
    result = accumulator.finalize()
    assert tuple(result.flag_summary.columns) == FLAG_COLUMNS
    assert len(result.flag_summary) == 48 * 9
    assert np.asarray(result.flag_summary["event_n"]).sum() == 0
    assert accumulator.memory_nbytes == 0


def test_streaming_partial_flag_feed_is_rejected_without_registration() -> None:
    accumulator = FollowupAccumulator({"group": "R1"}, horizons=(5,), landmarks_at=(2,))
    tables = list(_stock_tables("0001"))
    tables[2] = tables[2].iloc[1:]
    with pytest.raises(ValueError, match="complete registered"):
        accumulator.add_stock(_as_feed((tables[0], tables[1], tables[2], tables[3])))
    assert accumulator.memory_nbytes == 0
    accumulator.add_stock(_as_feed(_stock_tables("0001")))


@pytest.mark.parametrize("prefix", ["TW:", "TW"])
def test_tw_identity_crc_uses_original_code_and_preserves_leading_zeros(prefix: str) -> None:
    plain = list(_stock_tables("0001"))
    namespaced = list(_stock_tables(prefix + "0001"))
    plain[3], namespaced[3] = plain[3].iloc[:0], namespaced[3].iloc[:0]
    original = summarize_followup(*plain, groups={"group": "R1"}, horizons=(5,), landmarks_at=())
    projected = summarize_followup(*namespaced, groups={"group": "R1"}, horizons=(5,), landmarks_at=())
    for field in ("path_summary", "first_flag_summary", "flag_summary", "landmark_summary", "tradeoff_points", "exclusions"):
        pd.testing.assert_frame_equal(_canonical(getattr(projected, field)), _canonical(getattr(original, field)))
    expected = split_for_code("0001")
    nonzero = projected.flag_summary.loc[cast(pd.Series, projected.flag_summary["event_n"]).gt(0)]
    assert set(nonzero["split_id"]) == {expected}


def test_mixed_tw_identities_keep_original_crc_in_streaming_and_full_oracle() -> None:
    code = next(candidate for candidate in ("0002", "0003", "0004") if split_for_code(candidate) == split_for_code("0001"))
    first, second = list(_stock_tables("TW:0001")), list(_stock_tables("TW" + code))
    first[3], second[3] = first[3].iloc[:0], second[3].iloc[:0]
    joined = tuple(pd.concat([left, right], ignore_index=True) for left, right in zip(first, second, strict=True))
    oracle = summarize_followup(joined[0], joined[1], joined[2], joined[3], groups={"group": "R1"}, horizons=(5,), landmarks_at=())
    accumulator = FollowupAccumulator({"group": "R1"}, horizons=(5,), landmarks_at=())
    accumulator.add_stock(_as_feed((first[0], first[1], first[2], first[3])))
    accumulator.add_stock(_as_feed((second[0], second[1], second[2], second[3])))
    streamed = accumulator.finalize()
    for field in ("path_summary", "first_flag_summary", "flag_summary", "landmark_summary", "tradeoff_points", "exclusions"):
        pd.testing.assert_frame_equal(_canonical(getattr(streamed, field)), _canonical(getattr(oracle, field)))
    expected = split_for_code("0001")
    assert set(streamed.flag_summary.loc[cast(pd.Series, streamed.flag_summary["event_n"]).gt(0), "split_id"]) == {expected}
    row = _cell(streamed.flag_summary, flag_id="Y1")
    assert row["known_n"] == 8 and row["distinct_stock_n"] == 2


@pytest.mark.parametrize("identity", ["TW:", "TW"])
def test_empty_original_code_after_tw_prefix_is_rejected(identity: str) -> None:
    tables = list(_stock_tables(identity))
    tables[3] = tables[3].iloc[:0]
    with pytest.raises(ValueError, match="empty original code"):
        summarize_followup(*tables, groups={"group": "R1"}, horizons=(5,), landmarks_at=())
