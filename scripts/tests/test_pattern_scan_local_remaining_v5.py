"""Target completion, retained results and owned scratch boundaries."""

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_local_remaining_v5 as module
from research_core.artifact_store import read_json, write_json
from research_core.hhhl_variants_selection import Atom


@pytest.mark.parametrize(
    ("corruption", "recovery"),
    [(None, False)] + [(kind, recovered) for kind in ("same-size", "truncate", "scope") for recovered in (False, True)],
)
def test_only_final_results_are_receipted_and_completed_phases_are_not_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str | None, recovery: bool
) -> None:
    repo = tmp_path / "repo"
    output = repo / ".tmp" / "remaining"
    original = tmp_path / "original"
    original.mkdir()
    stock = original / "stock.json"
    stock.write_text("{}", encoding="utf-8")
    calls: list[str] = []
    receipt_results: list[list[str]] = []

    class Inputs:
        def __init__(self, stock_result: Path, temporary: Path) -> None:
            self.stock_result, self.temporary, self.run = stock_result, temporary, original
            self.source_id, self.input_id, self.original_code = "original-source", "original-input", {"commit": "old"}
            self.codes, self.shared_record = ("1101",), {"generation": "held-original"}
            temporary.mkdir(parents=True, exist_ok=True)

        def cache_target(self, target: str, directory: Path) -> None:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "unhashed-intermediate").write_text("temporary", encoding="utf-8")

    def final(name: str, destination: Path) -> list[Path]:
        calls.append(name)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / "final.parquet"
        pd.DataFrame({"count": [1]}).to_parquet(path, index=False)
        return [path]

    def conditions(inputs: Inputs, target: str, destination: Path) -> tuple[dict, dict, list[Path]]:
        return {}, {}, final("conditions", destination)

    def receipt(path: Path, **kwargs: object) -> None:
        results = kwargs["results"]
        assert isinstance(results, dict)
        receipt_results.append(list(results))
        write_json(
            path,
            {
                "schema": "run-receipt.v1",
                "definition": kwargs["definition"],
                "parameters": kwargs["parameters"],
                "code": {"commit": "new", "dirty": False},
                "results": {
                    name: {"path": str(result), "bytes": result.stat().st_size, "sha256": module.file_digest(result)} for name, result in results.items()
                },
            },
        )

    monkeypatch.setattr(module, "LocalInputs", Inputs)
    monkeypatch.setattr(module, "code_identity", lambda root: {"commit": "new", "dirty": False})
    monkeypatch.setattr(module, "fingerprint_inputs", lambda specs: {"inputs": {}})
    monkeypatch.setattr(module, "run_conditions", conditions)
    monkeypatch.setattr(module, "run_q4", lambda inputs, target, candidates, destination: final("q4", destination))
    monkeypatch.setattr(module, "run_followup", lambda inputs, target, candidates, destination: final("followup", destination))
    monkeypatch.setattr(module, "write_run_receipt", receipt)
    monkeypatch.setattr(module, "PATTERNS", ("H1",))
    result = module.run_remaining(stock, output, repo_root=repo, targets=("H1",))
    assert result["complete"] and result["release_pending"]
    assert calls == ["conditions", "q4", "followup"]
    assert receipt_results == [["final.parquet", "top-candidates.json"], ["final.parquet"], ["final.parquet"]]
    assert not (output / "_temporary/events/H1").exists()
    assert stock.read_text(encoding="utf-8") == "{}"
    for phase in module.PHASES:
        saved = read_json(output / "H1" / phase / "run-receipt.json")
        assert all(Path(item["path"]).is_file() for item in saved["results"].values())
    module.run_remaining(stock, output, repo_root=repo, targets=("H1",))
    assert calls == ["conditions", "q4", "followup"]
    if corruption is None:
        return
    payload = output / "H1/conditions/final.parquet"
    if corruption == "same-size":
        data = payload.read_bytes()
        payload.write_bytes(bytes((data[0] ^ 1,)) + data[1:])
    elif corruption == "truncate":
        payload.write_bytes(payload.read_bytes()[:-1])
    else:
        receipt_path = output / "H1/conditions/run-receipt.json"
        damaged = read_json(receipt_path)
        damaged["parameters"]["original_input_id"] = "foreign-input"
        module.write_progress(receipt_path, damaged)
    if recovery:
        progress = read_json(output / "progress.json")
        del progress["completed"]["H1"]["conditions"]
        module.write_progress(output / "progress.json", progress)
    module._VERIFIED_FINALS.clear()  # The launcher starts a new worker process.
    import subprocess

    from research_core import pattern_scan_execution_v1, research_measurement_v1

    errors: list[str] = []
    releases: list[list[str]] = []

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 8 * 1024**3

        def start(self, command: list[str], root: Path) -> SimpleNamespace:
            status = 0
            try:
                module.run_remaining(stock, output, repo_root=repo, targets=("H1",))
            except ValueError as error:
                errors.append(str(error))
                status = 1
            return SimpleNamespace(poll=lambda: status, returncode=status, args=command)

        def memory_receipt(self) -> dict[str, int]:
            return {"peak_committed_bytes": 10}

        def close(self) -> None:
            pass

    def release(command: list[str], **kwargs: Any) -> SimpleNamespace:
        releases.append(command)
        return SimpleNamespace(stdout="released")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", Job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    monkeypatch.setattr(subprocess, "run", release)
    with pytest.raises(subprocess.CalledProcessError):
        module.launch_remaining([], repo, output, timeout_seconds=10)
    assert errors and not releases
    assert calls == ["conditions", "q4", "followup"]
    assert not (output / ".active").exists()


@pytest.mark.parametrize("metadata", ("truncated", "mismatch", "valid", "denied"))
def test_unreceipted_top_candidates_repair_reuses_completed_conditions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: str) -> None:
    repo = tmp_path / "repo"
    output = repo / ".tmp/remaining"
    original = tmp_path / "original"
    original.mkdir()
    stock = original / "stock.json"
    stock.write_text("{}", encoding="utf-8")
    atom = Atom("MA", "MA_b", "true")
    candidates = {"selected": (atom,)}
    expected = {name: [asdict(member) for member in members] for name, members in candidates.items()}
    group_computations: list[str] = []
    q4_candidates: list[dict[str, tuple[Atom, ...]]] = []
    metadata_writes: list[Path] = []
    final_hashes: list[Path] = []
    valid_before: list[tuple[bytes, int]] = []

    class Inputs:
        def __init__(self, stock_result: Path, temporary: Path) -> None:
            self.stock_result, self.temporary, self.run = stock_result, temporary, original
            self.source_id, self.input_id, self.original_code = "source", "input", {"commit": "original"}
            self.codes, self.shared_record = ("1101",), {"generation": "held-original"}
            temporary.mkdir(parents=True, exist_ok=True)

        def cache_target(self, target: str, directory: Path) -> None:
            directory.mkdir(parents=True, exist_ok=True)

    def conditions(inputs: Inputs, target: str, directory: Path) -> tuple[dict, dict, list[Path]]:
        directory.mkdir(parents=True, exist_ok=True)
        completed = directory / "completed-group.parquet"
        if not completed.exists():
            group_computations.append(target)
            pd.DataFrame({"count": [1]}).to_parquet(completed, index=False)
        top = directory / "top-candidates.json"
        if metadata in {"valid", "denied"} and not top.exists():
            top.write_text(json.dumps(expected, indent=4) + "\n", encoding="utf-8")
            valid_before.append((top.read_bytes(), top.stat().st_mtime_ns))
        return {}, candidates, [completed]

    def q4(inputs: Inputs, target: str, selected: dict[str, tuple[Atom, ...]], directory: Path) -> list[Path]:
        assert read_json(output / target / "conditions/top-candidates.json") == expected
        q4_candidates.append(selected)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "final.parquet"
        pd.DataFrame({"count": [1]}).to_parquet(path, index=False)
        return [path]

    digest = module.file_digest

    def final_digest(path: Path) -> str:
        final_hashes.append(path)
        return digest(path)

    def receipt(path: Path, **kwargs: Any) -> None:
        if kwargs["parameters"]["phase"] == "conditions":
            assert read_json(path.parent / "top-candidates.json") == expected
        write_json(
            path,
            {
                "schema": "run-receipt.v1",
                "definition": kwargs["definition"],
                "parameters": kwargs["parameters"],
                "code": kwargs["expected_code"],
                "results": {
                    name: {"path": str(result), "bytes": result.stat().st_size, "sha256": module.file_digest(result)}
                    for name, result in kwargs["results"].items()
                },
            },
        )

    save = module.write_progress

    def interrupt_top_write(path: Path, value: dict[str, Any]) -> None:
        if path.name == "top-candidates.json":
            metadata_writes.append(path)
            if metadata in {"truncated", "mismatch"} and len(metadata_writes) == 1:
                # Reproduce a prior interrupted direct write. Retry must repair
                # just this unreceipted metadata, using the completed group.
                path.write_text('{"selected":' if metadata == "truncated" else '{"unexpected":[]}', encoding="utf-8")
                raise OSError("synthetic interrupted top candidates write")
        save(path, value)

    load = module.read_json

    def denied_top_read(path: Path, **kwargs: Any) -> dict[str, Any]:
        if metadata == "denied" and path.name == "top-candidates.json":
            raise PermissionError("synthetic top metadata access denied")
        return load(path, **kwargs)

    monkeypatch.setattr(module, "LocalInputs", Inputs)
    monkeypatch.setattr(module, "code_identity", lambda root: {"commit": "executor", "dirty": False})
    monkeypatch.setattr(module, "fingerprint_inputs", lambda specs: {"inputs": {}})
    monkeypatch.setattr(module, "run_conditions", conditions)
    monkeypatch.setattr(module, "run_q4", q4)
    monkeypatch.setattr(module, "write_run_receipt", receipt)
    monkeypatch.setattr(module, "write_progress", interrupt_top_write)
    monkeypatch.setattr(module, "read_json", denied_top_read)
    monkeypatch.setattr(module, "file_digest", final_digest)
    monkeypatch.setattr(module, "PATTERNS", ("H1",))
    phases = ("conditions", "q4")
    if metadata == "denied":
        with pytest.raises(PermissionError, match="access denied"):
            module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=phases)
        top = output / "H1/.staging-conditions/top-candidates.json"
        assert (top.read_bytes(), top.stat().st_mtime_ns) == valid_before[0]
        assert not metadata_writes and not final_hashes and not q4_candidates
        return
    if metadata in {"truncated", "mismatch"}:
        with pytest.raises(OSError, match="interrupted top"):
            module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=phases)
        assert group_computations == ["H1"] and not final_hashes
    module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=phases)
    top = output / "H1/conditions/top-candidates.json"
    assert read_json(top) == expected
    assert group_computations == ["H1"]  # Selection/group results were reused.
    assert q4_candidates == [candidates]
    assert len(final_hashes) == 3  # The two conditions results and Q4 final only.
    if metadata == "valid":
        assert (top.read_bytes(), top.stat().st_mtime_ns) == valid_before[0]
        assert not metadata_writes
    else:
        assert len(metadata_writes) == 2


@pytest.mark.parametrize(
    ("phase", "crash_point"),
    [(phase, point) for phase in module.PHASES for point in ("after_receipt", "staged-same-size", "staged-truncate")]
    + [(phase, point) for phase in ("q4", "followup") for point in ("before_receipt", "partial")],
)
def test_publication_retry_reuses_finished_phase_and_original_executor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, crash_point: str) -> None:
    repo = tmp_path / "repo"
    output = repo / ".tmp" / "remaining"
    original = tmp_path / "original"
    original.mkdir()
    stock = original / "stock.json"
    stock.write_text("{}", encoding="utf-8")
    executor: dict[str, Any] = {"commit": "first-executor", "dirty": False}
    calls: list[str] = []
    receipt_calls: list[str] = []
    digest_calls: list[Path] = []
    digest = module.file_digest
    names = {
        "conditions": ("final",),
        "q4": ("coverage", "timing", "examples", "admission-counts", "draws", "quotas"),
        "followup": (
            "path_summary",
            "first_flag_summary",
            "flag_summary",
            "landmark_summary",
            "tradeoff_points",
            "exclusions",
            "path_by_outcome",
            "first_flag_by_outcome",
            "holding_by_outcome",
        ),
    }

    def record_digest(path: Path) -> str:
        digest_calls.append(path)
        return digest(path)

    def complete_tables(name: str, directory: Path) -> list[Path] | None:
        paths = [directory / f"{stem}.parquet" for stem in names[name]]
        return paths if all(path.is_file() for path in paths) else None

    class Inputs:
        def __init__(self, stock_result: Path, temporary: Path) -> None:
            self.stock_result, self.temporary, self.run = stock_result, temporary, original
            self.source_id, self.input_id, self.original_code = "original-source", "original-input", {"commit": "old"}
            self.codes, self.shared_record = ("1101",), {"generation": "held-original"}
            temporary.mkdir(parents=True, exist_ok=True)

        def cache_target(self, target: str, directory: Path) -> None:
            directory.mkdir(parents=True, exist_ok=True)

    def final(name: str, destination: Path) -> list[Path]:
        calls.append(name)
        # The original Q4 runner refuses an existing working directory.
        if name == "q4" and destination.exists() and complete_tables(name, destination) is not None:
            raise FileExistsError(destination)
        destination.mkdir(parents=True, exist_ok=True)
        paths = [destination / f"{stem}.parquet" for stem in names[name]]
        for path in paths:
            if not path.exists():
                pd.DataFrame({"count": [1]}).to_parquet(path, index=False)
                if name == phase and crash_point == "partial" and executor["commit"] == "first-executor":
                    raise OSError("synthetic partial final write")
        return paths

    def conditions(inputs: Inputs, target: str, destination: Path) -> tuple[dict, dict, list[Path]]:
        return {}, {}, final("conditions", destination)

    def receipt(path: Path, **kwargs: Any) -> None:
        if kwargs["parameters"]["phase"] == phase and crash_point == "before_receipt" and executor["commit"] == "first-executor":
            raise OSError("synthetic interruption before final receipt")
        receipt_calls.append(kwargs["run_id"])
        write_json(
            path,
            {
                "schema": "run-receipt.v1",
                "definition": kwargs["definition"],
                "parameters": kwargs["parameters"],
                "code": dict(kwargs["expected_code"]),
                "results": {
                    name: {"path": str(result), "bytes": result.stat().st_size, "sha256": module.file_digest(result)}
                    for name, result in kwargs["results"].items()
                },
            },
        )

    monkeypatch.setattr(module, "LocalInputs", Inputs)
    monkeypatch.setattr(module, "code_identity", lambda root: dict(executor))
    monkeypatch.setattr(module, "fingerprint_inputs", lambda specs: {"inputs": {}})
    monkeypatch.setattr(module, "run_conditions", conditions)
    monkeypatch.setattr(module, "run_q4", lambda inputs, target, candidates, destination: final("q4", destination))
    monkeypatch.setattr(module, "run_followup", lambda inputs, target, candidates, destination: final("followup", destination))
    monkeypatch.setattr(module, "write_run_receipt", receipt)
    monkeypatch.setattr(module, "file_digest", record_digest)
    monkeypatch.setattr(module, "completed_q4_results", lambda directory: complete_tables("q4", directory))
    monkeypatch.setattr(module, "completed_followup_results", lambda directory: complete_tables("followup", directory))
    monkeypatch.setattr(module, "PATTERNS", ("H1",))
    if phase != "conditions":
        module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=("conditions",))
    working, destination = output / "H1" / f".staging-{phase}", output / "H1" / phase
    publish = module.publish_noreplace

    def fail_after_receipt_relocation(source: Path, target: Path) -> None:
        if source == working and crash_point in {"after_receipt", "staged-same-size", "staged-truncate"}:
            saved = read_json(source / "run-receipt.json")
            assert all(Path(row["path"]).is_relative_to(destination) for row in saved["results"].values())
            raise OSError("synthetic failure after receipt relocation")
        publish(source, target)

    monkeypatch.setattr(module, "publish_noreplace", fail_after_receipt_relocation)
    with pytest.raises(OSError, match="synthetic (failure|interruption|partial)"):
        module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=(phase,))
    saved_before = read_json(working / "run-receipt.json") if (working / "run-receipt.json").exists() else None
    payload_before = {path.relative_to(working): path.read_bytes() for path in working.rglob("*") if path.is_file() and path.name != "run-receipt.json"}
    calls_before, receipt_calls_before = list(calls), list(receipt_calls)
    digests_before = len(digest_calls)
    executor["commit"] = "retry-executor"
    module._VERIFIED_FINALS.clear()  # Simulate a new process checking retained finals once.
    if crash_point == "after_receipt":
        # The completed receipt, rather than later start metadata, is authority.
        module.write_progress(output / "H1" / f".phase-start-{phase}.json", {"code": executor})
    monkeypatch.setattr(module, "publish_noreplace", publish)
    if crash_point in {"staged-same-size", "staged-truncate"}:
        damaged = next(working.glob("*.parquet"))
        data = damaged.read_bytes()
        damaged.write_bytes(bytes((data[0] ^ 1,)) + data[1:] if crash_point == "staged-same-size" else data[:-1])
        with pytest.raises(ValueError, match="SHA-256|size"):
            module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=(phase,))
        assert calls == calls_before and receipt_calls == receipt_calls_before
        assert working.is_dir() and not destination.exists()
        return
    progress = module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=(phase,))
    if crash_point == "partial":
        assert calls == [*calls_before, phase]  # Only incomplete tables need the runner.
    else:
        assert calls == calls_before  # Complete tables skip every phase runner.
    saved_after = read_json(destination / "run-receipt.json")
    if saved_before is not None:
        assert receipt_calls == receipt_calls_before  # Never recreate the final receipt.
        assert saved_after == saved_before
    else:
        assert len(receipt_calls) == len(receipt_calls_before) + 1
        if crash_point == "partial":
            assert saved_after["execution_codes"] == [{"commit": "first-executor", "dirty": False}, executor]
            assert "finalized_by_code" not in saved_after
        else:
            assert saved_after["finalized_by_code"] == executor
            assert "execution_codes" not in saved_after
    assert len(digest_calls) - digests_before == len(saved_after["results"])  # Final-only, once per new process.
    assert progress["completed"]["H1"][phase]["executor"] == {"commit": "first-executor", "dirty": False}
    assert not working.exists()
    assert all((destination / relative).read_bytes() == data for relative, data in payload_before.items())
    verified = len(digest_calls)
    module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=(phase,))
    assert len(digest_calls) == verified  # Process-local verified final reuse.


def test_phase_start_keeps_original_executor_and_rejects_unknown_legacy_work(tmp_path: Path) -> None:
    target = tmp_path / "H1"
    target.mkdir()
    working = target / ".staging-q4"
    path = target / ".phase-start-q4.json"
    parameters = {"target": "H1", "phase": "q4", "original_source_id": "source", "original_input_id": "input"}
    original = {"commit": "original-executor", "dirty": False}
    first = module._phase_start(path, working, parameters, original)
    assert module._phase_start(path, working, parameters, {"commit": "retry-executor", "dirty": False}) == first
    assert read_json(path)["code"] == original
    with pytest.raises(ValueError, match="phase-start scope"):
        module._phase_start(path, working, {**parameters, "original_input_id": "other-input"}, original)
    legacy = target / ".staging-followup"
    legacy.mkdir()
    (legacy / "finished.parquet").write_bytes(b"legacy-final-bytes")
    with pytest.raises(ValueError, match="original executor record"):
        module._phase_start(target / ".phase-start-followup.json", legacy, {**parameters, "phase": "followup"}, original)
    assert not (target / ".phase-start-followup.json").exists()


@pytest.mark.parametrize("root", ("working", "final"))
@pytest.mark.parametrize("relative_path", (False, True))
def test_finished_receipt_path_mapping_is_idempotent(tmp_path: Path, root: str, relative_path: bool) -> None:
    repo = tmp_path / "repo"
    working, final = repo / ".tmp/.staging-q4", repo / ".tmp/q4"
    working.mkdir(parents=True)
    payload = working / "result.json"
    payload.write_text("{}", encoding="utf-8")
    recorded = payload if root == "working" else final / payload.name
    if relative_path:
        recorded = recorded.relative_to(repo)
    parameters = {"target": "H1", "phase": "q4", "original_source_id": "source", "original_input_id": "input"}
    receipt_path = working / "run-receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "run-receipt.v1",
            "definition": module.DEFINITION,
            "parameters": parameters,
            "code": {"commit": "original-executor", "dirty": False},
            "results": {"result": {"path": str(recorded), "bytes": payload.stat().st_size, "sha256": "retained-result-hash"}},
        },
    )
    mapped, files = module._staged_receipt(receipt_path, working, final, repo, parameters)
    assert mapped["results"]["result"]["path"] == str(final / payload.name)
    assert files == [payload]
    module.write_progress(receipt_path, mapped)
    assert module._staged_receipt(receipt_path, working, final, repo, parameters) == (mapped, files)


@pytest.mark.parametrize(
    "defect", ("definition", "target", "phase", "original_source_id", "original_input_id", "outside", "lexical-escape", "bytes", "missing")
)
def test_staged_receipt_rejects_scope_and_staging_mismatches(tmp_path: Path, defect: str) -> None:
    repo = tmp_path / "repo"
    working, final = repo / ".tmp/.staging-q4", repo / ".tmp/q4"
    working.mkdir(parents=True)
    payload = working / "result.json"
    payload.write_text("{}", encoding="utf-8")
    parameters = {"target": "H1", "phase": "q4", "original_source_id": "source", "original_input_id": "input"}
    receipt: dict[str, Any] = {
        "schema": "run-receipt.v1",
        "definition": module.DEFINITION,
        "parameters": dict(parameters),
        "code": {"commit": "original-executor", "dirty": False},
        "results": {"result": {"path": str(payload), "bytes": payload.stat().st_size, "sha256": "retained-result-hash"}},
    }
    if defect == "definition":
        receipt["definition"] = "other-definition"
    elif defect in parameters:
        receipt["parameters"][defect] = "other-scope"
    elif defect == "outside":
        outside = repo / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        receipt["results"]["result"]["path"] = str(outside)
    elif defect == "lexical-escape":
        outside = working.parent / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        receipt["results"]["result"]["path"] = str(working / ".." / outside.name)
    elif defect == "bytes":
        receipt["results"]["result"]["bytes"] += 1
    elif defect == "missing":
        receipt["results"]["result"]["path"] = str(final / "missing.json")
    receipt_path = working / "run-receipt.json"
    write_json(receipt_path, receipt)
    with pytest.raises(ValueError, match="scope|outside|missing|size|path traversal"):
        module._staged_receipt(receipt_path, working, final, repo, parameters)
    assert read_json(receipt_path) == receipt


def test_scratch_cleanup_refuses_original_or_result_paths(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = output / "H1/conditions"
    result.mkdir(parents=True)
    original = tmp_path / "original"
    original.mkdir()
    for path in (output, result, original):
        with pytest.raises(ValueError, match="scratch cleanup"):
            module._remove_owned_temporary(path, output)
        assert path.exists()


def test_job_initialization_failure_removes_active_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp/run"

    def fail_job(limit: int) -> None:
        raise OSError("synthetic Job Object initialization failure")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", fail_job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    with pytest.raises(OSError, match="Job Object initialization"):
        module.launch_remaining([], repo, output, timeout_seconds=10)
    assert not (output / ".active").exists()


@pytest.mark.parametrize("finished", (False, True))
def test_launcher_releases_only_after_all_original_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finished: bool) -> None:
    import subprocess

    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp" / "run"
    output.mkdir(parents=True)
    completed: dict[str, dict[str, dict[str, str]]] = {"H1": dict.fromkeys(module.PHASES if finished else ("conditions",), {})}
    # Even an accidentally true completion flag cannot release a partial run.
    write_json(output / "progress.json", {"complete": True, "release_pending": True, "completed": completed})
    calls: list[list[str]] = []

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 8 * 1024**3

        def start(self, command: list[str], root: Path) -> SimpleNamespace:
            return SimpleNamespace(poll=lambda: 0, returncode=0, args=command)

        def memory_receipt(self) -> dict[str, int]:
            return {"peak_committed_bytes": 10}

        def close(self) -> None:
            pass

    def release(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert command[-3:] == ["release", "--holder", "pr17-pattern-scan"]
        calls.append(command)
        return SimpleNamespace(stdout="released")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", Job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    monkeypatch.setattr(subprocess, "run", release)
    monkeypatch.setattr(module, "PATTERNS", ("H1",))
    module.launch_remaining([], repo, output, timeout_seconds=10)
    assert len(calls) == int(finished)
    assert read_json(output / "progress.json")["release_pending"] is (not finished)
