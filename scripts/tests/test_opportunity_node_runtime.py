from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def load_runtime(component: str, node: str | None, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(shutil, "which", lambda name: node if name == "node" else None)
    path = Path(__file__).resolve().parents[1] / f"{component}.py"
    spec = importlib.util.spec_from_file_location(f"test_runtime_{component}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(module: ModuleType, component: str, root: Path) -> str | None:
    if component == "build_opportunity_history":
        module.run_node(root / "series.json.gz", root / "calendar.json", root / "output.json.gz")
        return None
    return module._call_source("{}", "--verify")


@pytest.mark.parametrize("component", ["build_opportunity_history", "opportunity_history_native_validation"])
def test_path_node_in_space_directory_is_executed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: str) -> None:
    directory = tmp_path / "fake node with spaces"
    directory.mkdir()
    node = directory / ("node.cmd" if os.name == "nt" else "node")
    if os.name == "nt":
        node.write_text('@echo off\n@echo {"fake_node":"executed"}\n', encoding="ascii")
    else:
        node.write_text('#!/bin/sh\nprintf \'{"fake_node":"executed"}\\n\'\n', encoding="ascii")
        node.chmod(0o755)
    initial_node = tmp_path / "initial node location"
    module = load_runtime(component, str(initial_node), monkeypatch)
    assert module.NODE == initial_node
    monkeypatch.setattr(shutil, "which", lambda name: str(node) if name == "node" else None)
    original_run = subprocess.run
    observed: list[list[str]] = []

    def capture(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed.append(argv)
        completed = original_run(argv, **kwargs)
        assert json.loads(completed.stdout) == {"fake_node": "executed"}
        return completed

    monkeypatch.setattr(module.subprocess, "run", capture)
    invoke(module, component, tmp_path)
    assert len(observed) == 1 and observed[0][0] == str(node)


@pytest.mark.parametrize("component", ["build_opportunity_history", "opportunity_history_native_validation"])
def test_missing_node_is_explicit_runtime_error_without_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: str) -> None:
    module = load_runtime(component, None, monkeypatch)
    calls: list[list[str]] = []

    def unavailable(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        raise FileNotFoundError("synthetic node unavailable")

    monkeypatch.setattr(module.subprocess, "run", unavailable)
    with pytest.raises(RuntimeError, match="Node unavailable.*PATH"):
        invoke(module, component, tmp_path)
    assert calls == []


@pytest.mark.parametrize("component", ["build_opportunity_history", "opportunity_history_native_validation"])
def test_resolved_node_execution_error_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: str) -> None:
    resolved = str(tmp_path / "removed node executable")
    module = load_runtime(component, resolved, monkeypatch)

    def unavailable(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert argv[0] == resolved
        raise FileNotFoundError("synthetic node unavailable")

    monkeypatch.setattr(module.subprocess, "run", unavailable)
    with pytest.raises(RuntimeError, match="Node unavailable.*synthetic node unavailable"):
        invoke(module, component, tmp_path)


@pytest.mark.parametrize("component", ["build_opportunity_history", "opportunity_history_native_validation"])
def test_node_process_failure_retains_existing_exception_semantics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: str) -> None:
    module = load_runtime(component, str(tmp_path / "node executable"), monkeypatch)
    process_error = subprocess.CalledProcessError(7, "node", stderr="source rejected fixture")

    def failed(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise process_error

    monkeypatch.setattr(module.subprocess, "run", failed)
    if component == "build_opportunity_history":
        with pytest.raises(subprocess.CalledProcessError) as caught:
            invoke(module, component, tmp_path)
        assert caught.value is process_error
    else:
        with pytest.raises(ValueError, match="source rejected fixture") as caught_value:
            invoke(module, component, tmp_path)
        assert caught_value.value.__cause__ is process_error
