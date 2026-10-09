"""Synthetic parity tests; no actual market or forward-result data."""

import ast
import hashlib
import json
import sys
import types
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_rule_source import load_rule
from scripts.validate_hhhl_rule_source import COLUMNS, dated_events, main, validate

SOURCES = Path(__file__).resolve().parents[2] / "tasks/20261009-hhhl-pattern-probability/sources"


def source_bytes(name: str) -> bytes:
    with zipfile.ZipFile(SOURCES / "hhhl_rule_v1.zip") as archive:
        return archive.read(name)


@pytest.fixture
def bars() -> pd.DataFrame:
    t = np.arange(200)
    close = 100 + 0.35 * t + 7 * np.sin(t * 2 * np.pi / 24)
    volume = np.full(200, 100.0)
    for i in range(20, 200):
        if close[i] > close[i - 20 : i].max():
            volume[i] = 2 * volume[i - 20 : i].mean()
    return pd.DataFrame({
        "asof_date": pd.date_range("2020-01-01", periods=200),
        "Open": close - 0.2,
        "High": close + 0.7,
        "Low": close - 0.7,
        "Close": close,
        "VolumeLots": volume,
        "atr14_pct": 1 / close,
        "base_eligible": True,
    })


def original_detect() -> Callable[[pd.DataFrame], list[dict[str, Any]]]:
    tree = ast.parse(source_bytes("detect.py").decode("utf-8"))
    pivot = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "pivots_atr")
    namespace: dict[str, Any] = {"np": np}
    exec(compile(ast.Module(body=[pivot], type_ignores=[]), "detect.py", "exec"), namespace)
    module = types.ModuleType("detect")
    module.__dict__["pivots_atr"] = namespace["pivots_atr"]
    direct: dict[str, Any] = {}
    with patch.dict(sys.modules, {"detect": module}):
        exec(compile(source_bytes("hhhl_rule_v1.py"), "hhhl_rule_v1.py", "exec"), direct)
    return direct["detect"]


def test_wrapper_equals_original_and_prefix_consistency(bars: pd.DataFrame) -> None:
    rule = load_rule(SOURCES, "hhhl_rule_v1")
    direct = original_detect()
    expected = direct(bars)
    assert expected and any(event["pattern"] for event in expected)
    assert rule.detect(bars) == expected
    for stop in (70, 120, 160):
        assert rule.detect(bars.iloc[:stop]) == [event for event in expected if event["t"] < stop]


def test_ohlc_drop_reset_maps_exact_date(bars: pd.DataFrame) -> None:
    rule = load_rule(SOURCES, "hhhl_rule_v1")
    bars.loc[5, "Open"] = np.nan
    cleaned = bars.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)
    expected = original_detect()(cleaned)
    actual = dated_events(bars, rule)
    assert actual
    for event, original in zip(actual, expected, strict=True):
        assert {key: event[key] for key in original} == original
        assert event["date"] == cleaned.asof_date.iloc[original["t"]].strftime("%Y-%m-%d")
        assert event["calendar_index"] == original["t"] + 1


def test_invalid_rule_and_changed_source_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unregistered"):
        load_rule(SOURCES, "hhhl_rule_v2")
    with zipfile.ZipFile(tmp_path / "hhhl_rule_v1.zip", "w") as archive:
        archive.writestr("detect.py", source_bytes("detect.py"))
        archive.writestr("hhhl_rule_v1.py", source_bytes("hhhl_rule_v1.py") + b"\n# changed\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_rule(tmp_path, "hhhl_rule_v1")


def test_validation_projects_only_inputs_and_rejects_hash_change(tmp_path: Path, bars: pd.DataFrame) -> None:
    path = tmp_path / "stock.parquet"
    bars.assign(label_126=1).to_parquet(path, index=False)
    manifest: dict[str, Any] = {
        "dataset_id": "synthetic",
        "tables": [{"security_id": "TW:1234", "path": path.name, "rows": len(bars), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    date = dated_events(bars, load_rule(SOURCES, "hhhl_rule_v1"))[0]["date"]
    cases = {
        "rule_events": [{"code": "1234", "date": date}],
        "review_events": [],
        "expected_pattern": 20,
        "expected_inside": 10,
        "expected_owner_split": {"pattern_yes": 14, "pattern_no": 6, "inside_yes": 2, "inside_no": 8},
    }
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    read = pd.read_parquet
    with patch("scripts.validate_hhhl_rule_source.pd.read_parquet", wraps=read) as spy:
        report = validate(tmp_path, SOURCES, cases_path)
    assert spy.call_args.kwargs["columns"] == COLUMNS
    assert report["rule_events"][0]["found"]
    assert not report["passed"]  # Synthetic case count cannot pass real-case gates.
    manifest["tables"][0]["sha256"] = "0" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        validate(tmp_path, SOURCES, cases_path)


def test_cli_missing_fixture_is_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = main(["--dataset", str(tmp_path), "--sources", str(SOURCES), "--cases", str(tmp_path / "missing.json")])
    assert result == 1
    assert not json.loads(capsys.readouterr().out)["passed"]
