"""Small hand-checkable denominator and event-order regressions; no market data."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import ModuleType
from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_probability import describe, first_per_security
from research_core.hhhl_rule_source import FrozenRule, load_rule
from scripts import build_hhhl_probability as builder


def frame() -> pd.DataFrame:
    return pd.DataFrame({
        "security_id": ["TW:1", "TW:1", "TW:2", "TW:3"],
        "anchor_date": ["2020-01-01", "2020-01-02", "2020-01-01", "2020-01-01"],
        "breakout_date": ["2020-01-01", "2020-01-02", "2020-01-01", "2020-01-01"],
        "base_eligible": [True, True, True, False],
        "label_126": [None, 1, 0, 1],
        "min_return_126": [None, -0.1, -0.3, -0.8],
        "max_drawdown_126": [None, 0.2, 0.4, 0.9],
        "wait_to_threshold_126": [None, 20, None, 1],
    })


def test_eligibility_unknown_bounds_and_nonhit_price_path() -> None:
    summary = describe(frame(), 126)
    assert (summary["eligible"], summary["ineligible"], summary["known"], summary["hits"], summary["unknown"]) == (3, 1, 2, 1, 1)
    assert summary["rate"] == 0.5
    assert summary["unknown_lower"] == pytest.approx(1 / 3)
    assert summary["unknown_upper"] == pytest.approx(2 / 3)
    assert summary["nonhit_min_return_median"]["value"] == -0.3
    assert summary["hit_wait_median"]["value"] == 20


def test_first_per_stock_never_replaces_unknown_with_later_known() -> None:
    firsts = first_per_security(frame())
    assert len(firsts) == 2
    summary = describe(firsts, 126)
    assert (summary["hits"], summary["known"], summary["unknown"]) == (0, 1, 1)
    assert summary["rate"] == 0


def test_empty_denominator_remains_null() -> None:
    summary = describe(frame().iloc[:0], 126)
    assert summary["rate"] is None
    assert summary["unknown_lower"] is None
    assert summary["nonhit_min_return_median"]["value"] is None


def test_parallel_original_detector_equals_serial_in_source_order(tmp_path: Path) -> None:
    sources = Path(__file__).parents[2] / "tasks/20261009-hhhl-pattern-probability/sources"
    t = np.arange(200)
    close = 100 + 0.35 * t + 7 * np.sin(t * 2 * np.pi / 24)
    volume = np.full(200, 100.0)
    for i in range(20, 200):
        if close[i] > close[i - 20 : i].max():
            volume[i] = 2 * volume[i - 20 : i].mean()
    bars = pd.DataFrame({"Open": close - 0.2, "High": close + 0.7, "Low": close - 0.7, "Close": close, "VolumeLots": volume, "atr14_pct": 1 / close})
    paths = [tmp_path / f"{i}.parquet" for i in range(2)]
    for i, path in enumerate(paths):
        different = bars.copy()
        different[["Open", "High", "Low", "Close"]] *= i + 1
        different.to_parquet(path, index=False)
    serial = list(builder.detections(paths, sources, "hhhl_rule_v1", 1))
    assert serial[0] and any(event["pattern"] for event in serial[0])
    assert serial[0] != serial[1]
    assert list(builder.detections(paths, sources, "hhhl_rule_v1", 4)) == serial


@pytest.fixture
def versioned_builder(tmp_path: Path) -> ModuleType:
    """Use exact code bytes in a real disposable Git repo, never fabricate project HEAD."""
    source = Path(__file__).parents[2]
    code = tmp_path / "versioned code with spaces"
    code.mkdir()
    files = [
        "scripts/build_hhhl_probability.py",
        "research_core/hhhl_probability.py",
        "research_core/hhhl_rule_source.py",
        "research_core/hhhl_transition.py",
        "uv.lock",
    ]
    for relative in files:
        target = code / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
        assert builder.digest(target) == builder.digest(source / relative)
    for args in [
        ["init", "--quiet"],
        ["add", "--", *files],
        [
            "-c",
            "user.name=HHHL Test Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Version exact synthetic-test code closure",
        ],
    ]:
        subprocess.run(["git", "-C", str(code), *args], check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location("versioned_hhhl_builder_fixture", code / files[0])
    assert spec is not None and spec.loader is not None
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    return isolated


def test_builder_retains_unknowns_and_uses_actual_transition_anchor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, versioned_builder: ModuleType) -> None:
    builder = versioned_builder
    assert builder.__file__ is not None
    dataset = tmp_path / "atlas"
    dataset.mkdir()
    task = tmp_path / "task"
    task.mkdir()
    real_task = Path(__file__).parents[2] / "tasks/20261009-hhhl-pattern-probability"
    shutil.copytree(real_task / "sources", task / "sources")
    for name in ("mission.md", "data-contract.md"):
        shutil.copyfile(real_task / name, task / name)
    original = load_rule(task / "sources", "hhhl_rule_v1")
    n = 85
    f = pd.DataFrame({
        "security_id": ["TW:9999"] * n,
        "asof_date": pd.bdate_range("2020-01-01", periods=n),
        "year": [2020] * n,
        "base_eligible": [True] * n,
        "eligibility_reason": [""] * n,
        "regime": ["mixed"] * n,
        "industry_ref": ["unknown"] * n,
        "Open": [10.0] * n,
        "High": [11.0] * n,
        "Low": [9.0] * n,
        "Close": [10.0] * n,
        "VolumeLots": [100.0] * n,
        "atr14_pct": [0.1] * n,
        "corporate_action_types": [""] * n,
    })
    for column in builder.OUTCOME_COLUMNS:
        f[column] = None if column.startswith("unknown_reason") else 0.0
    f.loc[31, "corporate_action_types"] = "CASH_DIVIDEND"
    f.loc[70, "label_126"] = float("nan")
    f.loc[70, "unknown_reason_126"] = "window_end"
    f.loc[71, "label_126"] = 1.0
    f.to_parquet(dataset / "9999.parquet", index=False)
    manifest = {"tables": [{"path": "9999.parquet", "security_id": "TW:9999", "sha256": builder.digest(dataset / "9999.parquet")}]}
    (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    detected = [
        {
            "t": t,
            "restart": 30,
            "seq": [{"i": 30, "k": "L", "p": 9.0, "rel": "first"}],
            "cat": "hhhl",
            "context": context,
            "pattern": pattern,
            "vx": 2.0,
            "hz_top": 11.0,
        }
        for t, context, pattern in [(60, "inside_big_range", False), (70, "clears", True)]
    ]
    rule = FrozenRule(original.rule_id, lambda _: detected, original.pivots, original.k, original.source_hashes)
    monkeypatch.setattr(builder, "verify_dataset", lambda _: {"dataset_id": builder.DATASET_ID})
    monkeypatch.setattr(builder, "load_rule", lambda *_: rule)
    output = tmp_path / "run"
    result = builder.build(dataset, task, output, "hhhl_rule_v1")
    assert result["complete"] is True
    assert result["code_commit"] == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(builder.__file__).parents[1], text=True).strip()
    assert "manifest.json" not in result["artifacts"]
    assert "attempt.json" in result["artifacts"]
    for name, entry in result["artifacts"].items():
        assert builder.digest(output / name) == entry["sha256"]
    events = pd.read_parquet(output / "events.parquet")
    assert len(events) == 2
    assert bool(cast(pd.Series, events["structure_cash_dividend"]).all())
    assert bool(cast(pd.Series, events["z1_status"].eq("failed")).all())
    states = pd.read_parquet(output / "transitions.parquet")
    failed = states.loc[states["zone_name"].eq("z1") & states["pattern"].eq(True)].iloc[0]
    assert failed["anchor_date"] == f.asof_date.iloc[71].strftime("%Y-%m-%d")
    assert failed["label_126"] == 1
    assert states.loc[states["zone_name"].eq("z2"), "anchor_date"].isna().all()
    summaries = json.loads((output / "summaries.json").read_text(encoding="utf-8"))
    main = next(s for s in summaries if s["family"] == "pattern" and s["slice"] == "pooled" and s["horizon"] == 126 and s["sampling"] == "all_events")
    assert (main["known"], main["unknown"], main["rate"]) == (0, 1, None)
    state_summary = next(
        s for s in summaries if s["family"] == "z1_failed_pattern" and s["slice"] == "pooled" and s["horizon"] == 126 and s["sampling"] == "all_events"
    )
    assert (state_summary["known"], state_summary["hits"], state_summary["rate"]) == (1, 1, 1)
    assert len(summaries) == 558  # Fixed slices, including unsupported cells.
    with pytest.raises(FileExistsError):
        builder.build(dataset, task, output, "hhhl_rule_v1")
