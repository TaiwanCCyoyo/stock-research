"""Exact oracle parity and disabled-debug cost of streaming finalization."""

from __future__ import annotations

import logging
from dataclasses import fields
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_failure_summary_v1 as failure
from research_core import pattern_scan_followup_summary_v1 as followup
from research_core.hhhl_variants_selection import split_for_code
from research_core.pattern_scan_flags_v1 import FLAG_IDS
from research_core.pattern_scan_followup_v1 import FollowupTables


def _feed(code: str, values: tuple[float | None, ...]) -> FollowupTables:
    paths, first, flags, landmarks = [], [], [], []
    for index, value in enumerate(values):
        label = "unknown" if value is None else "hit" if index == 1 else "loss"
        common = {
            "group_id": "z",
            "target_pattern_id": "R1",
            "security_id": code,
            "event_id": f"{code}:{index}",
            "t0": "2011-01-03" if value is None else "2020-01-02",
            "calendar_index": index,
            "horizon": 5,
            "mkt": "unknown" if value is None else "up",
            "effective_label": label,
            "base_label": label,
            "event_main_eligible": value is not None,
            "calendar_full": True,
            "event_eligibility_excluded": False,
            "result_quality_reasons_json": '["synthetic_unknown"]' if value is None else "[]",
        }
        paths.append({**common, "path_category": "unknown" if value is None else "sideways", "max_return": value, "peak_offset": 1})
        first.append({
            **common,
            "first_flag_state": "unknown" if value is None else "triggered",
            "first_flag_flag_id": None if value is None else "Y1",
            "first_flag_offset": None if value is None else index % 3 + 1,
            "first_flag_all_flag_ids_json": "[]" if value is None else '["Y1","X6_10"]',
        })
        for flag in FLAG_IDS:
            state = "unknown" if value is None else "triggered" if flag == "Y1" else "all_false"
            record = {**common, "flag_id": flag, "flag_state": state, "trigger_return": value if state == "triggered" else None}
            flags.append(record)
            landmarks.append({
                **record,
                "landmark": 2,
                "riskset_id": "new_no_hit_valid_prefix",
                "riskset_eligible": True,
                "rise_bin": None if value is None else "lt1" if index % 2 == 0 else "ge1p25",
            })
    return FollowupTables(pd.DataFrame(paths), pd.DataFrame(flags), pd.DataFrame(landmarks), pd.DataFrame(first))


def _oracle(feeds: list[FollowupTables], *, groups: dict[str, str], landmarks_at: tuple[int, ...]) -> followup.FollowupSummaryTables:
    return followup.summarize_followup(
        *(pd.concat([getattr(feed, name) for feed in feeds], ignore_index=True) for name in ("paths", "first_flags", "flags", "landmarks")),
        groups=groups,
        horizons=(5,),
        landmarks_at=landmarks_at,
    )


def _assert_exact(actual: followup.FollowupSummaryTables, expected: followup.FollowupSummaryTables) -> None:
    for field in fields(followup.FollowupSummaryTables):
        left, right = getattr(actual, field.name), getattr(expected, field.name)
        if field.name == "exclusions":
            # The accumulator already publishes this table in canonical reason order.
            order = ["group_id", "horizon", "split_id", "era", "mkt", "source_table", "reason_scope", "reason"]
            right = right.sort_values(order, kind="stable").reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right, check_dtype=True, check_exact=True)


def test_registry_defers_each_family_until_consumed(monkeypatch: pytest.MonkeyPatch) -> None:
    original_product = followup.product
    calls = []

    def product(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return original_product(*args, **kwargs)

    monkeypatch.setattr(followup, "product", product)
    registry = followup._registered_followup_rows({"z": "R1", "a": "R3"}, (252, 126), (5, 10, 20, 40))
    assert calls == []
    assert all(iter(rows) is rows for rows in registry.values())
    first = next(registry["path"])
    assert len(calls) == 1
    assert first["group_id"] == "a" and first["horizon"] == 252
    assert first["path_category"] == followup.PATHS[0]
    # Starting another table traverses only its own product; unused families stay lazy.
    assert next(registry["flag"])["flag_id"] == FLAG_IDS[0]
    assert len(calls) == 2


@pytest.fixture(scope="module")
def uneven() -> tuple[list[FollowupTables], followup.FollowupSummaryTables]:
    second = next(code for code in ("0002", "0003", "0004") if split_for_code(code) == split_for_code("0001"))
    feeds = [_feed("0001", (-0.1, 0.02)), _feed(second, (1.0, 2.0, 3.0, 4.0, 5.0, None))]
    return feeds, _oracle(feeds, groups={"z": "R1", "a-empty": "R3"}, landmarks_at=(5, 2))


def test_uneven_stock_samples_match_independent_oracle_in_exact_order_and_dtype(uneven: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    feeds, expected = uneven
    accumulator = followup.FollowupAccumulator({"z": "R1", "a-empty": "R3"}, horizons=(5,), landmarks_at=(5, 2))
    for feed in feeds:
        accumulator.add_stock(feed)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("finalize must not invoke the batch oracle or pandas facet slicing")

    monkeypatch.setattr(followup, "summarize_followup", forbidden)
    monkeypatch.setattr(followup, "_facet", forbidden)
    actual = accumulator.finalize()
    _assert_exact(actual, expected)
    _assert_exact(accumulator.finalize(), expected)
    row = actual.flag_summary.loc[
        (actual.flag_summary["group_id"] == "z")
        & (actual.flag_summary["split_id"] == split_for_code("0001"))
        & (actual.flag_summary["era"] == "all")
        & (actual.flag_summary["mkt"] == "all")
        & (actual.flag_summary["flag_id"] == "Y1")
    ].iloc[0]
    assert row["trigger_return_n"] == 7
    assert row["trigger_return_median"] == 2.0
    assert row["distinct_stock_n"] == 2
    assert accumulator.memory_nbytes > 0


@pytest.mark.parametrize("landmarks_at", [(), (5,), (2, 5)])
def test_zero_cells_keep_schema_order_dtypes_and_missing_value_semantics(landmarks_at: tuple[int, ...]) -> None:
    feed = _feed("0001", (0.1,))
    empty = FollowupTables(*(getattr(feed, field.name).iloc[:0] for field in fields(FollowupTables)))
    groups = {"z": "R1", "a": "R3"}
    expected = _oracle([empty], groups=groups, landmarks_at=landmarks_at)
    accumulator = followup.FollowupAccumulator(groups, horizons=(5,), landmarks_at=landmarks_at)
    # No feed and a validated empty feed must both preserve every registered cell.
    _assert_exact(accumulator.finalize(), expected)
    accumulator.add_stock(empty)
    actual = accumulator.finalize()
    _assert_exact(actual, expected)
    assert actual.flag_summary["event_n"].sum() == 0
    assert bool(actual.flag_summary["trigger_return_median"].isna().all())
    assert bool(actual.flag_summary["nonhit_known_rate"].isna().all())
    assert accumulator.memory_nbytes == 0


@pytest.mark.parametrize("family", ["followup", "failure"])
def test_disabled_debug_never_evaluates_sample_memory_property(family: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = followup if family == "followup" else failure
    cls: Any = followup.FollowupAccumulator if family == "followup" else failure.FailureAccumulator
    accumulator = cls({"z": "R1"}, horizons=(5,)) if family == "failure" else cls({"z": "R1"}, horizons=(5,), landmarks_at=(2,))
    memory_property = cls.memory_nbytes
    calls: list[Any] = []

    def memory(self: Any) -> int:
        calls.append(self)
        assert memory_property.fget is not None
        return memory_property.fget(self)

    monkeypatch.setattr(cls, "memory_nbytes", property(memory))
    monkeypatch.setattr(module.LOGGER, "isEnabledFor", lambda level: level != logging.DEBUG)
    feed = _feed("0001", (0.1, 0.2))
    if family == "followup":
        accumulator.add_stock(feed)
    else:
        holding = pd.DataFrame([
            {
                "security_id": row["security_id"],
                "calendar_index": row["calendar_index"],
                "horizon": 5,
                "t0": row["t0"],
                "calendar_full": True,
                "observed_sessions": 5,
                **{metric: 0.2 for metric in failure.METRICS},
            }
            for row in feed.paths.to_dict(orient="records")
        ])
        accumulator.add_stock(feed, holding)
    assert calls == []
    # Explicit final resource observations retain the real property and sample bytes.
    assert accumulator.memory_nbytes > 0
    assert calls == [accumulator]
