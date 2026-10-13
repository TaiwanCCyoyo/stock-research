"""Small scratch-only Q4 orchestration and full resume verification cases."""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.artifact_store import canonical, describe_file, file_digest, read_json, write_json
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_episode_run_v1 import run_episodes


def fixture(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]]:
    # Test only the orchestration: the parent separately owns sealed-source
    # verification, and this fixture never supplies a real source or market path.
    monkeypatch.setattr("research_core.pattern_scan_episode_run_v1.verify_source", lambda source: None)
    dates = pd.bdate_range("2010-01-04", periods=160)
    directory = root / "stock"
    directory.mkdir()
    prices = pd.DataFrame({"Close": np.r_[np.full(80, 100.0), np.full(80, 130.0)], "quality_reason": None}, index=dates)
    labels = pd.DataFrame({
        "security_id": ["TW:0050"],
        "t0": [dates[10].strftime("%Y-%m-%d")],
        "calendar_index": [10],
        "horizon": [126],
        "label": ["hit"],
        "calendar_full": [True],
        "main_eligible": [False],
    })
    for name, frame in (("prices", prices), ("base_labels", labels)):
        frame.to_parquet(directory / f"{name}.parquet")
    source = {"source_id": "synthetic-source"}
    artifacts = [describe_file(directory, directory / f"{name}.parquet") for name in ("prices", "base_labels")]
    write_json(directory / "receipt.json", {"complete": True, "source_id": source["source_id"], "input_id": "synthetic-input", "artifacts": artifacts})
    global_path = root / "global.parquet"
    pd.DataFrame({"MKT": "up"}, index=dates).to_parquet(global_path)
    barrier = {
        "complete": True,
        "source_id": source["source_id"],
        "input_id": "synthetic-input",
        "calendar": dates.strftime("%Y-%m-%d").tolist(),
        "global_files": {"0050": {"path": str(global_path), "sha256": file_digest(global_path)}},
    }
    event_parts: dict[str, dict[str, Path]] = {}
    for target in PATTERNS:
        event_dir = root / f"event-{target}"
        event_dir.mkdir()
        indices = tuple(dict.fromkeys((10, 42, *range(0, 160, 21))))
        event_rows = [
            {
                "security_id": "TW:0050",
                "event_id": f"synthetic-{index}",
                "t0": dates[index].strftime("%Y-%m-%d"),
                "calendar_index": index,
                "horizon": 126,
                "base_eligible": True,
            }
            for index in indices
        ]
        events = pd.DataFrame(event_rows)
        memberships = [{"event_id": f"synthetic-{index}", "group_id": "C-base-all"} for index in range(0, 160, 21)]
        memberships.append({"event_id": "synthetic-42", "group_id": "C-52w"})
        if target == "B1":
            memberships.append({"event_id": "synthetic-10", "group_id": "pattern:union"})
        conditions = pd.DataFrame({"event_id": events.event_id, "MKT": "up"})
        daily = pd.DataFrame({
            "t0": dates.strftime("%Y-%m-%d"),
            "pattern:union": np.zeros(160, dtype=np.int8),
            "C-52w": np.zeros(160, dtype=np.int8),
            "C-base-daily": np.ones(160, dtype=np.int8),
        })
        daily.loc[42, "C-52w"] = 1
        if target == "B1":
            daily.loc[10, "pattern:union"] = 1
        tables = {"events": events, "conditions": conditions, "group_memberships": pd.DataFrame(memberships), "daily_groups": daily}
        for name, frame in tables.items():
            frame.to_parquet(event_dir / f"{name}.parquet", index=False)
        write_json(
            event_dir / "receipt.json",
            {
                "complete": True,
                "identity": {"source_id": source["source_id"], "input_id": "synthetic-input"},
                "artifacts": [describe_file(event_dir, event_dir / f"{name}.parquet") for name in tables],
            },
        )
        event_parts[target] = {"0050": event_dir}
    selections: dict[str, Any] = {target: {"candidates": []} for target in PATTERNS}
    return {"0050": directory}, barrier, event_parts, selections, source


def execute(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], Path, tuple[Any, ...]]:
    arguments = fixture(root, monkeypatch)
    parts, barrier, event_parts, selections, source = arguments
    output = root / "episodes-output"
    receipt = run_episodes(parts, barrier, event_parts, selections, {}, output, source=source, input_id="synthetic-input")
    return receipt, output, arguments


def test_original_union_controls_quota_daily_and_zero_cells(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt, output, _ = execute(tmp_path, monkeypatch)
    assert receipt["complete"] is True
    assert receipt["files"] == {record["path"]: str(output / record["path"]) for record in receipt["artifacts"]}
    assert all(Path(path).is_file() for path in receipt["files"].values())
    observed = pd.read_parquet(output / "observations.parquet")
    assert observed.loc[observed.group_id.eq("B1:original"), "observed_coverage_status"].iloc[0] == "matched"
    assert observed.loc[observed.group_id.eq("B1:original:C-52w"), "observed_coverage_status"].iloc[0] == "matched"
    assert "C-base-daily" in set(observed.group_id)
    assert "C-base-all" not in set(observed.group_id)
    coverage = pd.read_parquet(output / "coverage.parquet")
    assert len(coverage) == len(receipt["group_registry"]) * 48
    assert set(coverage.split) == {"development", "cross-check"}
    quota_file = next(path for path in output.iterdir() if path.name.endswith("-B1-quotas.parquet"))
    quota = pd.read_parquet(quota_file)
    assert quota.quota_n.sum() == 1 and quota.drawn_n.sum() == 1
    assert quota.pool_pin.map(lambda value: isinstance(value, str) and len(value) == 64).all()
    episode_file = next(path for path in output.iterdir() if path.name.endswith("-episodes.parquet"))
    assert len(pd.read_parquet(episode_file)) == 1  # main_eligible=False is not an S6 admission gate.


def test_complete_resume_checks_ancestors_and_every_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt, output, arguments = execute(tmp_path, monkeypatch)
    parts, barrier, event_parts, selections, source = arguments
    previous = file_digest(output / "receipt.json")
    resumed = run_episodes(parts, barrier, event_parts, selections, {}, output, source=source, input_id="synthetic-input")
    assert resumed == read_json(output / "receipt.json") == receipt
    assert file_digest(output / "receipt.json") == previous
    path = output / "coverage.parquet"
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError):
        run_episodes(parts, barrier, event_parts, selections, {}, output, source=source, input_id="synthetic-input")
    assert file_digest(output / "receipt.json") == previous


def test_input_ancestor_change_rejected_without_replacing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, output, arguments = execute(tmp_path, monkeypatch)
    parts, barrier, event_parts, selections, source = arguments
    with (parts["0050"] / "prices.parquet").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError):
        run_episodes(parts, barrier, event_parts, selections, {}, output, source=source, input_id="synthetic-input")
    assert read_json(output / "receipt.json")["complete"] is True


def test_jump_exclusion_keeps_fixed_zero_group_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts, barrier, event_parts, selections, source = fixture(tmp_path, monkeypatch)
    path = parts["0050"] / "prices.parquet"
    prices = pd.read_parquet(path)
    prices.loc[prices.index[30], "quality_reason"] = "unexplained_jump"
    prices.to_parquet(path)
    stock_receipt = read_json(parts["0050"] / "receipt.json")
    stock_receipt["artifacts"] = [describe_file(parts["0050"], parts["0050"] / f"{name}.parquet") for name in ("prices", "base_labels")]
    # This test intentionally replaces its own synthetic ancestor receipt after
    # changing the fixture payload, before the orchestration first observes it.
    (parts["0050"] / "receipt.json").write_bytes(canonical(stock_receipt))
    output = tmp_path / "episodes-output"
    receipt = run_episodes(parts, barrier, event_parts, selections, {}, output, source=source, input_id="synthetic-input")
    assert receipt["episode_observation_n"] == 0
    coverage = pd.read_parquet(output / "coverage.parquet")
    assert len(coverage) == len(receipt["group_registry"]) * 48 and coverage.episode_n.eq(0).all()
    admission_path = next(path for path in output.iterdir() if path.name.endswith("-admission.parquet"))
    assert "result_window_unexplained_jump" in pd.read_parquet(admission_path).exclusion_reasons.iloc[0]


def test_unselected_top_id_rejected_before_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts, barrier, event_parts, selections, source = fixture(tmp_path, monkeypatch)
    output = tmp_path / "episodes-output"
    with pytest.raises(ValueError, match="top IDs"):
        run_episodes(parts, barrier, event_parts, selections, {"B1": ("not-selected",)}, output, source=source, input_id="synthetic-input")
    assert not output.exists()


def test_midrun_payload_drift_has_no_final_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_episode_run_v1 as module

    parts, barrier, event_parts, selections, source = fixture(tmp_path, monkeypatch)
    original = module.observe_group
    changed = False

    def modifying_observer(*args: Any, **kwargs: Any) -> pd.DataFrame:
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            with (parts["0050"] / "prices.parquet").open("ab") as stream:
                stream.write(b"synthetic-midrun-drift")
            changed = True
        return result

    monkeypatch.setattr(module, "observe_group", modifying_observer)
    output = tmp_path / "episodes-output"
    with pytest.raises(ValueError):
        run_episodes(parts, barrier, event_parts, selections, {}, output, source=source, input_id="synthetic-input")
    assert changed
    assert not output.exists() and not (output / "receipt.json").exists()
    assert not list(tmp_path.glob(".staging-episodes-output-*/receipt.json"))
