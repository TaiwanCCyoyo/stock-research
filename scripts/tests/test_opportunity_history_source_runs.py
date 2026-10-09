from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import opportunity_history_source_runs as source_runs
from scripts.build_opportunity_history import code_identity, descriptor, read_json, write_json


def fixture(root: Path) -> Path:
    root.mkdir()
    calendar = {"calendar_id": "synthetic-calendar", "dates": [f"D{i}" for i in range(8)]}
    write_json(root / "calendar.json", calendar)
    references = {}
    for code, values in {"ONE": [6.02, 8.127, None, 6, 7, 8, 0, 9], "TWO": [4, 5.4, None, 6, 7, 8, None, 9]}.items():
        series = {
            "schema_version": "opportunity-series.v1",
            "code": code,
            "security_id": f"synthetic:{code}",
            "series_id": f"series:{code}",
            "calendar_id": calendar["calendar_id"],
            "instrument_role": "stock",
            "cohort": "metadata_stock",
            "raw": values,
            "adjusted": values,
            "numeric_flags": {"4": ["synthetic barrier"]},
            "coverage_caveats": ["does_not_block"],
        }
        path = root / f"{code}.json.gz"
        write_json(path, series)
        references[code] = descriptor(path, root) | {"security_id": series["security_id"], "series_id": series["series_id"]}
    path = root / "manifest.json"
    write_json(
        path,
        {
            "calendar_id": calendar["calendar_id"],
            "calendar": descriptor(root / "calendar.json", root, 8),
            "series": references,
            "native": {code: {"path": "not-read-process-failure.json.gz"} for code in references},
            "code_identity": code_identity(),
        },
    )
    return path


def test_real_javascript_boundaries_nulls_flags_and_single_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = fixture(tmp_path / "合成 fixture with spaces")
    calls: list[list[str]] = []
    actual_run = source_runs.subprocess.run

    def tracked(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["encoding"] == "utf-8"
        return actual_run(command, **kwargs)

    monkeypatch.setattr(source_runs.subprocess, "run", tracked)
    assert source_runs.expected_source_runs(path) == {
        "ONE": [0, 0, None, 1, None, 2, None, 3],
        "TWO": [0, 1, None, 2, None, 3, None, 4],
    }
    assert len(calls) == 1
    assert not (path.parent / "not-read-process-failure.json.gz").exists()


def test_selected_code_reads_only_selected_series_with_exact_floating_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = fixture(tmp_path / "selected")
    # A corrupt unselected reference must not be opened by selected-code queries.
    manifest = read_json(path)
    (path.parent / manifest["series"]["TWO"]["path"]).unlink()
    calls: list[list[str]] = []
    actual_run = source_runs.subprocess.run

    def tracked(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(source_runs.subprocess, "run", tracked)
    result = source_runs.expected_source_runs(path, {"ONE"})
    assert result == {"ONE": [0, 0, None, 1, None, 2, None, 3]}
    assert result["ONE"][:2] == [0, 0]  # JS retains 6.02 -> 8.127 at the pinned floating boundary.
    assert len(calls) == 1 and calls[0][-2:] == ["--code", "ONE"]
    assert not (path.parent / "not-read-process-failure.json.gz").exists()


def test_multiple_selected_codes_have_precise_response_and_stable_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = fixture(tmp_path / "selected")
    calls: list[list[str]] = []
    actual_run = source_runs.subprocess.run

    def tracked(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(source_runs.subprocess, "run", tracked)
    assert set(source_runs.expected_source_runs(path, {"TWO", "ONE"})) == {"ONE", "TWO"}
    assert calls[0][-4:] == ["--code", "ONE", "--code", "TWO"]


def test_selected_javascript_accepts_uppercase_valid_dependency_hashes(tmp_path: Path) -> None:
    path = fixture(tmp_path / "uppercase")
    manifest = read_json(path)
    manifest["calendar"]["sha256"] = manifest["calendar"]["sha256"].upper()
    manifest["series"]["ONE"]["sha256"] = manifest["series"]["ONE"]["sha256"].upper()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert source_runs.expected_source_runs(path, {"ONE"}) == {"ONE": [0, 0, None, 1, None, 2, None, 3]}


def test_unknown_selected_code_rejected_before_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = fixture(tmp_path / "selected")

    def reject_process(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Unknown selected code must be refused before Node")

    monkeypatch.setattr(source_runs.subprocess, "run", reject_process)
    with pytest.raises(ValueError, match="selected code set"):
        source_runs.expected_source_runs(path, {"UNKNOWN"})


def test_selected_response_cannot_include_unselected_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = fixture(tmp_path / "selected")
    payload = {"schema": "opportunity-expected-source-runs.v1", "calendar_count": 8, "results": {"ONE": [0] * 8, "TWO": [0] * 8}}
    monkeypatch.setattr(source_runs.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, json.dumps(payload), ""))
    with pytest.raises(ValueError, match="response code mismatch"):
        source_runs.expected_source_runs(path, {"ONE"})


@pytest.mark.parametrize("mutation", ["identity", "series_hash", "calendar_hash"])
def test_real_javascript_rejects_code_and_input_hash_mismatch(tmp_path: Path, mutation: str) -> None:
    path = fixture(tmp_path / "catalog")
    manifest = read_json(path)
    if mutation == "identity":
        manifest["code_identity"]["wrapper"]["sha256"] = "0" * 64
    elif mutation == "series_hash":
        manifest["series"]["ONE"]["sha256"] = "0" * 64
    else:
        manifest["calendar"]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity mismatch|input hash mismatch"):
        source_runs.expected_source_runs(path)


def test_node_unavailable_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = fixture(tmp_path / "catalog")

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("synthetic missing Node")

    monkeypatch.setattr(source_runs.subprocess, "run", unavailable)
    with pytest.raises(RuntimeError, match="Node is unavailable"):
        source_runs.expected_source_runs(path)


@pytest.mark.parametrize("mutation", ["json", "schema", "count", "codes", "length", "bool", "negative"])
def test_response_shape_is_validated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    path = fixture(tmp_path / "catalog")
    payload: dict[str, Any] = {"schema": "opportunity-expected-source-runs.v1", "calendar_count": 8, "results": {"ONE": [0] * 8, "TWO": [0] * 8}}
    if mutation == "schema":
        payload["schema"] = "wrong"
    elif mutation == "count":
        payload["calendar_count"] = 7
    elif mutation == "codes":
        payload["results"].pop("TWO")
    elif mutation == "length":
        payload["results"]["ONE"].pop()
    elif mutation == "bool":
        payload["results"]["ONE"][0] = True
    elif mutation == "negative":
        payload["results"]["ONE"][0] = -1
    stdout = "not JSON" if mutation == "json" else json.dumps(payload)
    monkeypatch.setattr(source_runs.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout, ""))
    with pytest.raises(ValueError):
        source_runs.expected_source_runs(path)


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    (tmp_path / "calendar.json").write_text(json.dumps({"dates": ["2020-01-02", "2020-01-03"]}), encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"calendar": {"path": "calendar.json"}, "native": {"1111": {}}}), encoding="utf-8")
    return path


def test_source_runs_uses_path_node_in_nonstandard_directory_with_spaces(manifest_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    node = "C:/Users/Research User/AppData/Local/Volta/bin/node.exe"

    def find_node(command: str) -> str:
        assert command == "node"
        return node

    def run_node(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command == [node, "--experimental-strip-types", str(source_runs.SCRIPT), "--manifest", str(manifest_path.resolve()), "--code", "1111"]
        assert kwargs == {"check": True, "capture_output": True, "text": True, "encoding": "utf-8"}
        payload = {"schema": "opportunity-expected-source-runs.v1", "calendar_count": 2, "results": {"1111": [0, None]}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(source_runs.shutil, "which", find_node)
    monkeypatch.setattr(source_runs.subprocess, "run", run_node)

    assert source_runs.expected_source_runs(manifest_path, {"1111"}) == {"1111": [0, None]}


def test_source_runs_reports_missing_node_on_path(manifest_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source_runs.shutil, "which", lambda command: None)
    monkeypatch.setattr(source_runs.subprocess, "run", lambda *args, **kwargs: pytest.fail("subprocess called without Node"))

    with pytest.raises(RuntimeError, match="Node is unavailable on PATH"):
        source_runs.expected_source_runs(manifest_path, {"1111"})


def test_source_runs_empty_selection_does_not_probe_node(manifest_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source_runs.shutil, "which", lambda command: pytest.fail("empty selection probed Node"))
    monkeypatch.setattr(source_runs.subprocess, "run", lambda *args, **kwargs: pytest.fail("empty selection called subprocess"))

    assert source_runs.expected_source_runs(manifest_path, set()) == {}


def test_source_runs_preserves_subprocess_stderr_diagnostic(manifest_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source_runs.shutil, "which", lambda command: "C:/Tools/node.exe")

    def fail_node(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, command, stderr="source wrapper failed")

    monkeypatch.setattr(source_runs.subprocess, "run", fail_node)

    with pytest.raises(RuntimeError, match="Exact JavaScript source run validation failed: source wrapper failed"):
        source_runs.expected_source_runs(manifest_path, {"1111"})
