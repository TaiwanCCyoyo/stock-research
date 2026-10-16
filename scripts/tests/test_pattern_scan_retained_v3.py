"""Synthetic explicit-retention inventory and deterministic Q4 examples."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.pattern_scan_retained_v3 import collect_retained_files, select_q4_examples


@pytest.fixture
def inventory(tmp_path: Path) -> dict[str, Any]:
    def file(name: str) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic retained-file inventory fixture")
        return path

    return {
        "summaries": {"files": {name: file(f"q1/{name}") for name in ("summary/a.parquet", "annual/a.parquet", "candidate-coverage/a.parquet")}},
        "followup": {
            "files": {
                name: file(f"q5/{name}")
                for name in (
                    "B4/path_summary.parquet",
                    "B4/flag_summary.parquet",
                    "B4/exclusions.parquet",
                    "observations/B4/stock/paths.parquet",
                    "holding_context.parquet",
                )
            },
            "episodes": {
                "files": {
                    name: file(f"q4/{name}")
                    for name in (
                        "coverage.parquet",
                        "examples.parquet",
                        "stock-B4-draws.parquet",
                        "stock-B4-quotas.parquet",
                        "stock-H1-draws.parquet",
                        "stock-H1-quotas.parquet",
                        "observations.parquet",
                        "stock-B4-observed.parquet",
                        "stock-episodes.parquet",
                        "stock-admission.parquet",
                    )
                }
            },
        },
        "audits": {
            "files": {
                name: file(f"audit/{name}")
                for name in (
                    "raw_events.parquet",
                    "cold_events.parquet",
                    "conditions.parquet",
                    "candidates.parquet",
                    "pivots.parquet",
                    "legacy-overlap.parquet",
                    "legacy-reference.json",
                )
            }
        },
        "selection_path": file("selection.json"),
        "execution_files": {"execution/request.json": file("request.json"), "execution/run-receipt.json": file("run-receipt.json")},
    }


def test_collects_full_summaries_and_bounded_audits_without_detailed_tables(inventory: dict[str, Any]) -> None:
    retained = collect_retained_files(**inventory)
    expected = {
        **{f"q1-q3/{name}": path for name, path in inventory["summaries"]["files"].items()},
        **{
            f"q5-q6/{name}": path
            for name, path in inventory["followup"]["files"].items()
            if not name.startswith("observations/") and name != "holding_context.parquet"
        },
        "q4/coverage.parquet": inventory["followup"]["episodes"]["files"]["coverage.parquet"],
        **{
            f"audits/q4/{name}": path
            for name, path in inventory["followup"]["episodes"]["files"].items()
            if name == "examples.parquet" or name.endswith(("-draws.parquet", "-quotas.parquet"))
        },
        **{f"audits/events/{name}": path for name, path in inventory["audits"]["files"].items()},
        "selection.json": inventory["selection_path"],
        **inventory["execution_files"],
    }
    assert retained == expected
    excluded = {path for name, path in inventory["followup"]["files"].items() if name.startswith("observations/") or name == "holding_context.parquet"}
    excluded.update(
        path
        for name, path in inventory["followup"]["episodes"]["files"].items()
        if name not in {"coverage.parquet", "examples.parquet"} and not name.endswith(("-draws.parquet", "-quotas.parquet"))
    )
    assert not excluded.intersection(retained.values())
    assert all(path.is_file() for path in excluded)  # Collection neither moves nor deletes.


@pytest.mark.parametrize("mutation", ("name", "case", "prefix", "path", "unsafe_name", "unsafe_path", "relative_path", "missing_examples"))
def test_collisions_and_unsafe_inventory_fail(inventory: dict[str, Any], mutation: str) -> None:
    execution = inventory["execution_files"]
    value = execution["execution/request.json"]
    if mutation == "name":
        execution["selection.json"] = value
    elif mutation == "case":
        execution["SELECTION.JSON"] = value
    elif mutation == "prefix":
        execution["selection.json/child"] = value
    elif mutation == "path":
        execution["another-name.json"] = inventory["selection_path"]
    elif mutation == "unsafe_name":
        execution["../escape.json"] = value
    elif mutation == "unsafe_path":
        execution["safe.json"] = value.parent / ".." / value.name
    elif mutation == "relative_path":
        execution["safe.json"] = Path("relative.json")
    else:
        inventory["followup"]["episodes"]["files"].pop("examples.parquet")
    with pytest.raises(ValueError, match="collision|unsafe|traversal|absolute|examples"):
        collect_retained_files(**inventory)


def _rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "group_id": group,
            "coverage_status": status,
            "security_id": f"TW:{index // 3:04}",
            "anchor_t0": f"2020-01-0{index % 3 + 1}",
            "anchor_index": index % 3,
            "episode_id": f"{group}:{status}:{index}",
            "matching_indices": [index, index + 2],
            "observed_coverage_status": "matched" if status == "unknown" else status,
            "quota_shortfall": status == "unknown",
            "diagnostic_value": float(index),
        }
        for group in ("R1:original", "R1:candidate:one")
        for status in ("matched", "unmatched", "unknown")
        for index in range(7)
    ])


def test_q4_examples_bound_effective_status_stable_identity_order_and_preserve_full_rows() -> None:
    original = _rows()
    expected = select_q4_examples(original)
    actual = select_q4_examples(original.sample(frac=1, random_state=37))
    pd.testing.assert_frame_equal(actual, expected)
    assert len(actual) == 2 * 3 * 3
    assert bool(actual.groupby(["group_id", "coverage_status"]).size().eq(3).all())
    assert actual.columns.tolist() == original.columns.tolist()
    for _, group in actual.groupby(["group_id", "coverage_status"]):
        assert group.security_id.tolist() == ["TW:0000"] * 3
        assert group.anchor_t0.tolist() == ["2020-01-01", "2020-01-02", "2020-01-03"]
    unknown = actual.loc[actual.coverage_status.eq("unknown")]
    assert bool(unknown.observed_coverage_status.eq("matched").all()) and bool(unknown.quota_shortfall.all())
    selected = original.set_index("episode_id").loc[actual.episode_id].reset_index()[actual.columns]
    pd.testing.assert_frame_equal(actual, selected)


def test_q4_empty_examples_keep_schema_and_invalid_identities_fail() -> None:
    empty = _rows().iloc[:0]
    pd.testing.assert_frame_equal(select_q4_examples(empty), empty.reset_index(drop=True))
    duplicate = pd.concat([_rows(), _rows().iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        select_q4_examples(duplicate)
    invalid = _rows()
    invalid.loc[0, "coverage_status"] = "invented"
    with pytest.raises(ValueError, match="coverage status"):
        select_q4_examples(invalid)
