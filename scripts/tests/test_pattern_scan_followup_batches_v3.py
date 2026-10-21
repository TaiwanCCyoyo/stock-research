"""Synthetic differential coverage; never reads producer or research artifacts."""

from __future__ import annotations

import weakref
from collections.abc import Iterator
from dataclasses import fields
from typing import Any, cast

import pandas as pd
import pytest

from research_core import pattern_scan_followup_batches_v3 as batches
from research_core.pattern_scan_failure_summary_v1 import FailureAccumulator, FailureSummaryTables
from research_core.pattern_scan_flags_v1 import FLAG_IDS
from research_core.pattern_scan_followup_summary_v1 import FollowupAccumulator, FollowupSummaryTables
from research_core.pattern_scan_followup_v1 import FollowupTables


def _stock(code: str) -> tuple[FollowupTables, pd.DataFrame]:
    paths, first, flags, landmarks, holding = [], [], [], [], []
    labels = ("hit", "loss", "unknown", "loss", "hit", "flat-win")
    dates = ("2011-01-04", "2015-06-01", "2021-02-03", "2021-02-04", "2021-02-05", "2021-02-08")
    for horizon in (126, 252):
        # Keep a deliberately nonchronological sample order, including -0.0.
        for index in (2, 0, 5, 1, 4, 3):
            full, excluded = index != 3, index == 4
            common = {
                "security_id": f"TW:{code}",
                "event_id": f"{code}:event:{index}",
                "t0": dates[index],
                "calendar_index": index,
                "horizon": horizon,
                "base_label": labels[index],
                "effective_label": labels[index],
                "calendar_full": full,
                "event_main_eligible": full and not excluded and labels[index] != "unknown",
                "event_eligibility_excluded": excluded,
                "mkt": "unknown" if index == 2 else "up",
                "base_first_hit_offset": 2 if labels[index] == "hit" else None,
                "result_quality_reasons_json": '["z_quality","a_quality"]' if index == 2 else "[]",
                "detection_quality_reasons_json": '["synthetic_detection"]' if index == 1 else "[]",
            }
            value = None if index == 2 else ((-0.0, 0.125, 0.25, -0.5, 0.75, 0.375)[index] + (0.01 if code == "0002" else -0.0))
            paths.append({**common, "path_category": "unknown" if index == 2 else "sideways", "max_return": value, "peak_offset": 2})
            state = "unknown" if index == 2 else "all_false" if index == 5 else "triggered"
            first.append({
                **common,
                "first_flag_state": state,
                "first_flag_flag_id": "Y1" if state == "triggered" else None,
                "first_flag_offset": 1 if state == "triggered" else None,
                "first_flag_all_flag_ids_json": '["Y1","X6_10"]' if state == "triggered" else "[]",
            })
            for flag in FLAG_IDS:
                flag_state = state if flag == "Y1" else "all_false"
                record = {**common, "flag_id": flag, "flag_state": flag_state, "trigger_return": value if flag_state == "triggered" else None}
                flags.append(record)
                for landmark in (5, 10, 20, 40):
                    landmarks.append({
                        **record,
                        "landmark": landmark,
                        "riskset_id": "new_no_hit_valid_prefix",
                        "riskset_eligible": index != 4,
                        "rise_bin": None if index == 2 else "lt1",
                    })
            holding.append({
                "security_id": common["security_id"],
                "calendar_index": index,
                "horizon": horizon,
                "t0": dates[index],
                "calendar_full": full,
                "observed_sessions": horizon if full else horizon - 1,
                "own_return": value,
                "benchmark_return": 0.1,
                "peer_return": None,
                "holding_up_fraction": 0.25,
                "holding_down_fraction": 0.25,
                "holding_consolidation_fraction": 0.0,
                "holding_mixed_fraction": 0.25,
                "holding_unknown_fraction": 0.25,
            })
    return FollowupTables(pd.DataFrame(paths), pd.DataFrame(flags), pd.DataFrame(landmarks), pd.DataFrame(first)), pd.DataFrame(holding)


def _bound(base: FollowupTables, group: str, horizon: int | None = None) -> FollowupTables:
    chunks = []
    for field in fields(base):
        frame = getattr(base, field.name)
        selected = frame.event_id.str.endswith((":0", ":1", ":2")) if group == "a-overlap" else frame.event_id.notna()
        if group == "z-empty":
            selected &= False
        if horizon is not None:
            selected &= frame.horizon.eq(horizon)
        frame = frame.loc[selected].copy()
        frame["group_id"], frame["target_pattern_id"] = group, "R1"
        chunks.append(frame)
    return FollowupTables(*chunks)


def _snapshot(accumulator: Any) -> dict[tuple[Any, ...], Any]:
    return {
        key: {
            "counts": dict(cell.counts),
            "samples": {name: sample.tobytes() for name, sample in cell.samples.items()},
            "stock_events": dict(getattr(cell, "stock_events", {})),
            "stocks": set(getattr(cell, "stocks", set())),
            "sample_stocks": set(getattr(cell, "sample_stocks", set())),
        }
        for key, cell in accumulator._cells.items()
    }


def test_batches_equal_all_group_oracle_including_raw_order_dtypes_and_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = {"z-empty": "R1", "R1": "R1", "a-overlap": "R1"}
    stocks = {code: _stock(code) for code in ("0001", "0002")}
    oracle = FollowupAccumulator(groups)
    failure_oracle = FailureAccumulator(groups)
    for base, holding in stocks.values():
        bound = [_bound(base, group) for group in groups if group != "z-empty"]
        combined = FollowupTables(*(pd.concat([getattr(part, field.name) for part in bound], ignore_index=True) for field in fields(base)))
        oracle.add_stock(combined)
        failure_oracle.add_stock(combined, holding)
    expected_cells = {"followup": _snapshot(oracle), "failure": _snapshot(failure_oracle)}
    expected_bytes = oracle.memory_nbytes + failure_oracle.memory_nbytes
    expected = oracle.finalize(), failure_oracle.finalize()
    del oracle, failure_oracle
    cells: dict[str, dict[tuple[Any, ...], Any]] = {"followup": {}, "failure": {}}
    references: list[weakref.ReferenceType[Any]] = []
    constructed = []

    class ObservedFollowup(FollowupAccumulator):
        def __init__(self, registered: Any, *, horizons: Any) -> None:
            assert all(reference() is None for reference in references), "previous raw accumulators survived into the next batch"
            assert len(registered) == len(horizons) == 1
            constructed.append((dict(registered), tuple(horizons)))
            super().__init__(registered, horizons=horizons)
            references.append(weakref.ref(self))

        def finalize(self) -> Any:
            cells["followup"].update(_snapshot(self))
            return super().finalize()

    class ObservedFailure(FailureAccumulator):
        def __init__(self, registered: Any, *, horizons: Any) -> None:
            assert (dict(registered), tuple(horizons)) == constructed[-1]
            super().__init__(registered, horizons=horizons)
            references.append(weakref.ref(self))

        def finalize(self) -> Any:
            cells["failure"].update(_snapshot(self))
            return super().finalize()

    monkeypatch.setattr(batches, "FollowupAccumulator", ObservedFollowup)
    monkeypatch.setattr(batches, "FailureAccumulator", ObservedFailure)
    clock = iter(range(12))
    monkeypatch.setattr(batches, "resource_sample", lambda: {"wall": next(clock), "cpu": 0.0, "native": None})
    calls = []

    def feeds(group: str, horizon: int) -> Iterator[tuple[FollowupTables, pd.DataFrame]]:
        assert sum(reference() is not None for reference in references) == 2
        calls.append((group, horizon))
        for base, holding in stocks.values():
            bound = _bound(base, group, horizon)
            if not bound.paths.empty:
                yield bound, holding.loc[holding.horizon.eq(horizon)].copy()

    actual_followup, actual_failure, measurements = batches.summarize_followup_batches(groups, feeds)
    assert cells == expected_cells  # Includes exact double-array bytes in original feed order.
    assert calls == [(group, horizon) for group in sorted(groups) for horizon in (126, 252)]
    assert constructed == [({group: "R1"}, (horizon,)) for group, horizon in calls]
    assert all(reference() is None for reference in references)
    assert sum(row["total_raw_sample_bytes"] for row in measurements) == expected_bytes
    assert max(row["total_raw_sample_bytes"] for row in measurements) < expected_bytes
    for row in measurements:
        assert row["total_raw_sample_bytes"] == row["followup_raw_sample_bytes"] + row["failure_raw_sample_bytes"]
        assert row["stock_feed_n"] == (0 if row["group_id"] == "z-empty" else 2)
        assert row["phase"]["wall_seconds"] == 1
        assert row["phase"]["native"] is None
    for actual, original in zip((actual_followup, actual_failure), expected, strict=True):
        for field in fields(cast(FollowupSummaryTables | FailureSummaryTables, original)):
            pd.testing.assert_frame_equal(getattr(actual, field.name), getattr(original, field.name), check_dtype=True, check_exact=True, obj=field.name)
    assert actual_failure.holding_by_outcome.peer_return_median.dtype == object
    assert actual_failure.holding_by_outcome.own_return_median.dtype.kind == "f"
    assert set(actual_followup.exclusions.reason) >= {"z_quality", "a_quality", "synthetic_detection", "censored", "event_eligibility_excluded"}
    empty = actual_followup.path_summary.loc[actual_followup.path_summary.group_id.eq("z-empty")]
    assert empty.path_n.eq(0).all() and empty.max_gain_median.isna().all()


def test_no_groups_preserves_existing_empty_table_schemas_without_feeds() -> None:
    def forbidden(*args: Any) -> Any:
        pytest.fail("empty group registry must not read any stock feeds")

    actual_followup, actual_failure, measurements = batches.summarize_followup_batches({}, forbidden)
    assert measurements == []
    for actual, expected in ((actual_followup, FollowupAccumulator({}).finalize()), (actual_failure, FailureAccumulator({}).finalize())):
        for field in fields(cast(FollowupSummaryTables | FailureSummaryTables, expected)):
            pd.testing.assert_frame_equal(getattr(actual, field.name), getattr(expected, field.name), check_exact=True)


def test_invalid_group_is_rejected_before_feed_access() -> None:
    def forbidden(*args: Any) -> Any:
        pytest.fail("invalid identity must be rejected before feed access")

    with pytest.raises(ValueError, match="identities"):
        batches.summarize_followup_batches({" ": "R1"}, forbidden)
