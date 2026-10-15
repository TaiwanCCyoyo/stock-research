"""Synthetic Git provenance and normal-import worker dispatch regressions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from research_core import pattern_scan_execution_v1 as execution
from research_core import pattern_scan_git_source_v2 as git_source
from research_core.artifact_store import object_digest, read_json, write_json


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setattr(git_source, "code_identity", lambda root: {"commit": "a" * 40, "dirty": True})
    return git_source.git_source_identity(tmp_path)


def _resign(identity: dict[str, Any]) -> None:
    identity["source_id"] = object_digest({key: value for key, value in identity.items() if key != "source_id"})


def test_historical_identity_does_not_check_checkout_or_hash_files(identity: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Git receipt verification must not inspect checkout or source files")

    monkeypatch.setattr(git_source, "code_identity", forbidden)
    monkeypatch.setattr(execution, "file_digest", forbidden)
    monkeypatch.setattr(execution, "source_identity", forbidden)
    monkeypatch.setattr(execution, "write_source_archive", forbidden)
    git_source.verify_git_source(identity)
    execution.verify_source(identity)
    execution._verify_loaded(identity)
    assert set(identity) == {"schema", "code", "runtime", "platform", "numerical_thread_limits", "source_id"}
    monkeypatch.setattr(git_source, "code_identity", lambda root: {"commit": "b" * 40, "dirty": True})
    with pytest.raises(ValueError, match="active Git source checkout differs"):
        git_source.assert_current_code(identity, tmp_path)
    git_source.verify_git_source(identity)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("code", {"commit": "not-a-commit", "dirty": False}, "code identity"),
        ("code", {"commit": "a" * 40, "dirty": 1}, "code identity"),
        ("runtime", {}, "runtime"),
        ("platform", "invented-platform", "runtime"),
        ("numerical_thread_limits", {}, "thread limits"),
        ("sources", {}, "source identity"),
    ],
)
def test_invalid_identity_rejected(identity: dict[str, Any], field: str, value: Any, error: str) -> None:
    changed = deepcopy(identity)
    changed[field] = value
    _resign(changed)
    with pytest.raises(ValueError, match=error):
        git_source.verify_git_source(changed)


def test_git_stock_reuse_skips_legacy_loaded_source_gate(identity: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from research_core import cache_execution

    output = tmp_path / "part"
    output.mkdir()
    request = {"source": identity}
    receipt = {"request_id": object_digest(request), "complete": True, "artifacts": []}
    write_json(output / "receipt.json", receipt)
    monkeypatch.setattr(execution, "_request", lambda packet: (None, None, output))

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("normally imported Git stock must not require legacy loaded-source hashes")

    monkeypatch.setattr(cache_execution, "require_loaded", forbidden)
    assert execution._execute_stock_in_process(request) == receipt


def test_active_entry_checks_code_once_and_reports_no_loaded_hashes(identity: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = tmp_path / "run"
    directory = run / "workers" / "one"
    directory.mkdir(parents=True)
    request_path, response = directory / "request.json", directory / "response.json"
    write_json(request_path, {"source": identity, "stocks": [{"source": identity, "run_root": str(run)}], "response_path": str(response)})
    calls = []

    def current(root: Path) -> dict[str, Any]:
        calls.append(root)
        return identity["code"]

    monkeypatch.setattr(git_source, "code_identity", current)
    monkeypatch.setattr(execution, "_execute_stock_in_process", lambda packet: {"code": "0001"})
    for name, value in execution.NUMERICAL_THREADS.items():
        monkeypatch.setenv(name, value)
    execution.worker_main(request_path)
    assert calls == [execution.ROOT]
    receipt = read_json(response)
    assert receipt["complete"] is True
    assert receipt["loaded_project_sources"] == {}
    assert "no-loaded-module-hashes" in receipt["source_verification_policy"]
    stale_path = directory / "stale.json"
    packet = read_json(request_path)
    packet["response_path"] = str(directory / "stale-response.json")
    write_json(stale_path, packet)
    monkeypatch.setattr(git_source, "code_identity", lambda root: {"commit": "b" * 40, "dirty": True})
    with pytest.raises(ValueError, match="active Git source checkout differs"):
        execution.worker_main(stale_path)
    assert not Path(packet["response_path"]).exists()


@pytest.mark.parametrize("git", [True, False])
def test_pool_dispatch_keeps_legacy_bootstrap_and_uses_normal_import_for_git(
    identity: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git: bool,
) -> None:
    source = identity if git else {"schema": "pattern-scan-source.v1"}
    run = tmp_path / "run"
    launched = []
    monkeypatch.setattr(execution, "host_resources", lambda: {"physical_available_bytes": 8 * 1024**3})
    monkeypatch.setattr(execution, "_request", lambda *args, **kwargs: None)
    if not git:
        monkeypatch.setattr(execution, "verify_source", lambda source: None)

    class Process:
        def poll(self) -> int:
            return 0

    class Job:
        def __init__(self, limit: int) -> None:
            self.limit = limit

        def start(self, command: list[str], cwd: Path) -> Process:
            launched.append((command, cwd))
            packet = read_json(Path(command[-1]))
            write_json(Path(packet["response_path"]), {"complete": True, "results": [{"code": row["code"]} for row in packet["stocks"]]})
            return Process()

        def memory_receipt(self) -> dict[str, int]:
            return {"limit_bytes": self.limit}

        def close(self) -> None:
            pass

    monkeypatch.setattr(execution, "_MemoryBoundJob", Job)
    result = execution.run_requests(
        [{"source": source, "run_root": str(run), "code": code} for code in ("0020", "0001")],
        workers=1,
        memory_bytes=1024**3,
        estimated_worker_bytes=256 * 1024**2,
    )
    expected = execution.GIT_BOOTSTRAP if git else execution.BOOTSTRAP
    assert all(command[2] == expected and command[3] == str(execution.ROOT) and cwd == execution.ROOT for command, cwd in launched)
    assert [row["code"] for row in result["results"]] == ["0001", "0020"]
    if git:
        assert "SourceFinder" not in expected and "read_bytes" not in expected and "hashlib" not in expected
        assert "sys.dont_write_bytecode=True" in expected
        assert "from research_core.pattern_scan_execution_v1 import worker_main" in expected
    else:
        assert "_SourceFinder" in expected
