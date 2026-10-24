"""Target completion, retained results and owned scratch boundaries."""

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_local_remaining_v5 as module
from research_core import scratch_runs
from research_core.artifact_store import read_json, write_json
from research_core.hhhl_variants_selection import Atom


def test_new_invocation_default_preserves_every_family_in_owner_order() -> None:
    from scripts.run_pattern_scan_remaining import DEFAULT_TARGET_ORDER

    assert len(DEFAULT_TARGET_ORDER) == len(set(DEFAULT_TARGET_ORDER)) == len(module.PATTERNS)
    assert set(DEFAULT_TARGET_ORDER) == set(module.PATTERNS)
    assert DEFAULT_TARGET_ORDER[2:7] == ("B2", "B4", "B3", "L1", "P1")


def test_output_root_accepts_legacy_tmp_and_exact_registered_scratch_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    legacy = repo / ".tmp" / "remaining"
    assert module.output_run(legacy, repo) is None

    scratch = tmp_path / "shared" / "scratch"
    registered = scratch / "20261024-data-homes-and-scratch" / "continuation-v1"
    registered.mkdir(parents=True)
    record = {
        "schema": scratch_runs.SCHEMA,
        "state": "running",
        "task": "20261024-data-homes-and-scratch",
        "run": "continuation-v1",
    }
    write_json(registered / "run.json", record)
    monkeypatch.setattr(scratch_runs, "scratch_root", lambda **kwargs: scratch)
    assert module.output_run(registered, repo) == record
    with pytest.raises(ValueError, match="registered|scratch run|output"):
        module.output_run(registered / "nested", repo)
    with pytest.raises(scratch_runs.ScratchRunError, match="no run.json"):
        module.output_run(scratch / "20261024-data-homes-and-scratch" / "unregistered", repo)


@pytest.mark.parametrize("outcome", ("complete", "incomplete", "error"))
def test_cli_holds_registered_run_lock_through_launch_and_heartbeats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str) -> None:
    import os
    import sys

    from scripts import run_pattern_scan_remaining as cli

    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        monkeypatch.setenv(name, os.environ.get(name, "test"))
    repo = Path(__file__).resolve().parents[2]
    scratch = tmp_path / "shared" / "scratch"
    scratch.mkdir(parents=True)
    monkeypatch.setattr(scratch_runs, "scratch_root", lambda **kwargs: scratch)
    task, run_id = "20261024-data-homes-and-scratch", f"cli-{outcome}"
    with scratch_runs.create_run(task, run_id, purpose="CLI lock lifecycle", owner="test", root=scratch, repo_root=repo) as created:
        output = created.path
    stock = tmp_path / "stock.json"
    stock.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["run_pattern_scan_remaining.py", "--stock-result", str(stock), "--output", str(output), "--target", "H1", "--workers", "2"]
    )

    reported = {"step": 2, "total": 4, "label": "H1 condition groups"}

    def launch(arguments: list[str], root: Path, target: Path, *, timeout_seconds: int, on_progress: Any) -> dict[str, Any]:
        assert target == output and timeout_seconds == 864000
        with pytest.raises(scratch_runs.ScratchRunError, match="in use"):
            scratch_runs.open_run(task, run_id, root=scratch, repo_root=root)
        assert on_progress is not None
        on_progress(reported)
        if outcome == "error":
            raise RuntimeError("synthetic worker failure")
        return {"complete": outcome == "complete", "release_pending": True}

    monkeypatch.setattr(module, "launch_remaining", launch)
    if outcome == "error":
        with pytest.raises(RuntimeError, match="synthetic worker failure"):
            cli.main()
    else:
        cli.main()

    record = scratch_runs.read_run(output)
    assert record["state"] == ("complete" if outcome == "complete" else "running")
    assert record["progress"] == reported
    # main's context releases the writer lock on normal return and exceptions.
    with scratch_runs.open_run(task, run_id, root=scratch, repo_root=repo) as resumed:
        assert resumed.record["state"] == record["state"]


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
    identity = {"source_id": "original-source", "input_id": "original-input"}

    class Inputs:
        def __init__(self, stock_result: Path, temporary: Path) -> None:
            self.stock_result, self.temporary, self.run = stock_result, temporary, original
            self.source_id, self.input_id, self.original_code = identity["source_id"], identity["input_id"], {"commit": "old"}
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

    def conditions(inputs: Inputs, target: str, destination: Path, *, on_progress: Any = None) -> tuple[dict, dict, list[Path]]:
        if on_progress is not None:
            on_progress(1, 4)
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
    progress_events: list[dict[str, Any]] = []
    result = module.run_remaining(stock, output, repo_root=repo, targets=("H1",), on_progress=progress_events.append)
    assert result["complete"] and result["release_pending"]
    assert progress_events and all({"step", "total", "label"} <= set(item) for item in progress_events)
    assert read_json(output / "progress.json")["progress"] == progress_events[-1]
    assert calls == ["conditions", "q4", "followup"]
    assert receipt_results == [["final.parquet", "top-candidates.json"], ["final.parquet"], ["final.parquet"]]
    assert not (output / "_temporary/events/H1").exists()
    assert stock.read_text(encoding="utf-8") == "{}"
    for phase in module.PHASES:
        saved = read_json(output / "H1" / phase / "run-receipt.json")
        assert all(Path(item["path"]).is_file() for item in saved["results"].values())
    relocated_stock = original / "relocated-stock.json"
    relocated_stock.write_text("{}", encoding="utf-8")
    module.run_remaining(relocated_stock, output, repo_root=repo, targets=("H1",))
    assert calls == ["conditions", "q4", "followup"]
    saved = read_json(output / "progress.json")
    assert saved["stock_result"] == str(relocated_stock.resolve())
    assert saved["source_id"] == identity["source_id"] and saved["input_id"] == identity["input_id"]
    identity["input_id"] = "different-input"
    with pytest.raises(ValueError, match="different original inputs"):
        module.run_remaining(relocated_stock, output, repo_root=repo, targets=("H1",))
    if corruption is None:
        return
    identity["input_id"] = "original-input"
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

        def terminate_and_confirm(self) -> None:
            pass

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

    def conditions(inputs: Inputs, target: str, directory: Path, *, on_progress: Any = None) -> tuple[dict, dict, list[Path]]:
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

    def conditions(inputs: Inputs, target: str, destination: Path, *, on_progress: Any = None) -> tuple[dict, dict, list[Path]]:
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
            assert saved_after["execution_codes"] == [{"commit": "first-executor", "dirty": False}, executor]
    # A partial scoped phase also consumes the one retained fixed-selection
    # result. It does not rehash the other conditions tables.
    upstream_selection = int(phase != "conditions" and crash_point == "partial")
    assert len(digest_calls) - digests_before == len(saved_after["results"]) + upstream_selection
    assert progress["completed"]["H1"][phase]["executor"] == {"commit": "first-executor", "dirty": False}
    assert not working.exists()
    assert all((destination / relative).read_bytes() == data for relative, data in payload_before.items())
    verified = len(digest_calls)
    module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=(phase,))
    assert len(digest_calls) == verified  # Process-local verified final reuse.


@pytest.mark.parametrize("phase", ("q4", "followup"))
@pytest.mark.parametrize("damage", (None, "same-size", "scope", "missing-entry", "path", "missing-receipt"))
def test_scoped_phase_checks_only_its_fixed_selection_before_computing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, damage: str | None) -> None:
    repo = tmp_path / "repo"
    output = repo / ".tmp/remaining"
    original = tmp_path / "original"
    original.mkdir()
    stock = original / "stock.json"
    stock.write_text("{}", encoding="utf-8")
    conditions = output / "H1/conditions"
    conditions.mkdir(parents=True)
    selected = conditions / "top-candidates.json"
    atom = Atom("MA", "C3", "ge60")
    write_json(selected, {"old": [asdict(atom)]})
    other = conditions / "unrelated-final.txt"
    other.write_text("retained final", encoding="utf-8")
    receipt: dict[str, Any] = {
        "schema": "run-receipt.v1",
        "definition": module.DEFINITION,
        "parameters": {"target": "H1", "phase": "conditions", "original_source_id": "source", "original_input_id": "input"},
        "code": {"commit": "original", "dirty": False},
        "results": {path.name: {"path": str(path), "bytes": path.stat().st_size, "sha256": module.file_digest(path)} for path in (selected, other)},
    }
    if damage == "same-size":
        selected.write_bytes(selected.read_bytes().replace(b'"old"', b'"new"'))
    elif damage == "scope":
        receipt["parameters"]["original_input_id"] = "foreign"
    elif damage == "missing-entry":
        del receipt["results"][selected.name]
    elif damage == "path":
        receipt["results"]["../top-candidates.json"] = receipt["results"].pop(selected.name)
    if damage != "missing-receipt":
        write_json(conditions / "run-receipt.json", receipt)
    write_json(
        output / "progress.json",
        {
            "schema": module.DEFINITION,
            "stock_result": str(stock),
            "source_id": "source",
            "input_id": "input",
            "complete": False,
            "completed": {"H1": {"conditions": {"receipt": str(conditions / "run-receipt.json")}}},
        },
    )
    inputs = SimpleNamespace(
        stock_result=stock,
        temporary=output / "_temporary",
        run=original,
        source_id="source",
        input_id="input",
        codes=("1101",),
        cache_target=lambda *args: None,
    )
    monkeypatch.setattr(module, "LocalInputs", lambda *args: inputs)
    monkeypatch.setattr(module, "code_identity", lambda root: {"commit": "current", "dirty": False})
    monkeypatch.setattr(module, "fingerprint_inputs", lambda specs: {})
    digests: list[Path] = []
    digest = module.file_digest

    def selection_digest(path: Path) -> str:
        assert path == selected  # No pass over other final or intermediate files.
        digests.append(path)
        return digest(path)

    calls: list[dict] = []

    def compute(inputs: object, target: str, candidates: dict, destination: Path) -> list[Path]:
        calls.append(candidates)
        raise RuntimeError("synthetic phase reached")

    monkeypatch.setattr(module, "file_digest", selection_digest)
    monkeypatch.setattr(module, "run_q4" if phase == "q4" else "run_followup", compute)
    if damage is None:
        with pytest.raises(RuntimeError, match="synthetic phase reached"):
            module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=(phase,))
        assert calls == [{"old": (atom,)}] and digests == [selected]
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            module.run_remaining(stock, output, repo_root=repo, targets=("H1",), phases=(phase,))
        assert not calls


def test_phase_start_keeps_original_executor_and_appends_retry_executors_idempotently(tmp_path: Path) -> None:
    target = tmp_path / "H1"
    target.mkdir()
    working = target / ".staging-q4"
    path = target / ".phase-start-q4.json"
    parameters = {"target": "H1", "phase": "q4", "original_source_id": "source", "original_input_id": "input"}
    original = {"commit": "original-executor", "dirty": False}
    first = module._phase_start(path, working, parameters, original)
    assert read_json(path)["code"] == original
    retry = {"commit": "retry-executor", "dirty": False}
    module._phase_start(path, working, parameters, retry)
    module._phase_start(path, working, parameters, retry)
    saved_start = read_json(path)
    assert saved_start["code"] == original
    assert saved_start["execution_codes"] == [original, retry]
    assert first["code"] == original
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
    relative_key = Path("pattern%3Aunion-h126") / "result.json"
    payload = working / relative_key
    payload.parent.mkdir(parents=True)
    payload.write_text("{}", encoding="utf-8")
    recorded = payload if root == "working" else final / relative_key
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
            "results": {relative_key.as_posix(): {"path": str(recorded), "bytes": payload.stat().st_size, "sha256": "retained-result-hash"}},
        },
    )
    mapped, files = module._staged_receipt(receipt_path, working, final, repo, parameters)
    assert mapped["results"][relative_key.as_posix()]["path"] == str(final / relative_key)
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
        "results": {"result.json": {"path": str(payload), "bytes": payload.stat().st_size, "sha256": "retained-result-hash"}},
    }
    if defect == "definition":
        receipt["definition"] = "other-definition"
    elif defect in parameters:
        receipt["parameters"][defect] = "other-scope"
    elif defect == "outside":
        outside = repo / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        receipt["results"] = {str(outside): receipt["results"]["result.json"]}
    elif defect == "lexical-escape":
        outside = working.parent / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        receipt["results"] = {"../outside.json": receipt["results"]["result.json"]}
    elif defect == "bytes":
        receipt["results"]["result.json"]["bytes"] += 1
    elif defect == "missing":
        receipt["results"] = {"missing.json": receipt["results"]["result.json"]}
    receipt_path = working / "run-receipt.json"
    write_json(receipt_path, receipt)
    with pytest.raises(ValueError, match="scope|outside|missing|size|path traversal"):
        module._staged_receipt(receipt_path, working, final, repo, parameters)
    assert read_json(receipt_path) == receipt


def test_relocated_nested_receipt_verifies_content_and_detects_tampering(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    working, final = repo / ".tmp/.staging-q4", repo / ".tmp/q4"
    nested = Path("pattern%3Aunion-h126") / "summary.parquet"
    payload = working / nested
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"verified-final-table")
    parameters = {"target": "H1", "phase": "q4", "original_source_id": "source", "original_input_id": "input"}
    receipt_path = working / "run-receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "run-receipt.v1",
            "definition": module.DEFINITION,
            "parameters": parameters,
            "code": {"commit": "original-executor", "dirty": False},
            # Historical absolute path is ignored; the relative results key is authoritative.
            "results": {
                nested.as_posix(): {"path": str(tmp_path / "historical-location"), "bytes": payload.stat().st_size, "sha256": module.file_digest(payload)}
            },
        },
    )
    mapped, staged_files = module._staged_receipt(receipt_path, working, final, repo, parameters)
    assert mapped["results"][nested.as_posix()]["path"] == str(final / nested)
    assert staged_files == [payload]
    relocated = final / nested
    relocated.parent.mkdir(parents=True)
    relocated.write_bytes(payload.read_bytes())
    published = module._published_files(mapped, final, repo, parameters)
    assert published == [relocated]
    module._VERIFIED_FINALS.clear()
    module._verify_final_results(mapped, published)
    relocated.write_bytes(b"tampered-final-table")
    module._VERIFIED_FINALS.clear()
    with pytest.raises(ValueError, match="SHA-256"):
        module._verify_final_results(mapped, published)


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
        marker = read_json(output / ".active")
        assert marker["schema"] == module.ACTIVE_SCHEMA
        assert marker["lock_path"] == str(output / ".active.lock")
        raise OSError("synthetic Job Object initialization failure")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", fail_job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    with pytest.raises(OSError, match="Job Object initialization"):
        module.launch_remaining([], repo, output, timeout_seconds=10)
    assert not (output / ".active").exists()
    with (output / ".active.lock").open("a+b") as handle:
        assert module.try_os_lock(handle)
        module.release_os_lock(handle)


@pytest.mark.parametrize("kind", ("legacy", "malformed", "foreign"))
def test_unknown_active_marker_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp/run"
    output.mkdir(parents=True)
    active = output / ".active"
    contents = {
        "legacy": b"1234\n",
        "malformed": b'{"schema":',
        "foreign": json.dumps({"schema": module.ACTIVE_SCHEMA, "owner": "foreign", "pid": 1, "lock_path": str(output / "other.lock")}).encode(),
    }[kind]
    active.write_bytes(contents)
    before = active.stat().st_mtime_ns

    def unexpected_job(limit: int) -> None:
        raise AssertionError("a protected active marker must not start a Job")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", unexpected_job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    with pytest.raises(RuntimeError, match="active marker"):
        module.launch_remaining([], repo, output, timeout_seconds=10)
    assert active.read_bytes() == contents and active.stat().st_mtime_ns == before
    assert (output / ".active.lock").is_file()
    with (output / ".active.lock").open("a+b") as handle:
        assert module.try_os_lock(handle)
        module.release_os_lock(handle)


def test_first_marker_publication_preserves_interleaved_legacy_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp/run"
    active = output / ".active"
    publish = module.publish_noreplace
    legacy = b"1234\n"
    preserved: list[int] = []

    def interleave(source: Path, destination: Path) -> None:
        if destination == active:
            with active.open("xb") as stream:
                stream.write(legacy)
            preserved.append(active.stat().st_mtime_ns)
        publish(source, destination)

    def unexpected_job(limit: int) -> None:
        pytest.fail("mixed-version marker race must not start another Job")

    monkeypatch.setattr(module, "publish_noreplace", interleave)
    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", unexpected_job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    with pytest.raises(FileExistsError):
        module.launch_remaining([], repo, output, timeout_seconds=10)
    assert active.read_bytes() == legacy
    assert preserved == [active.stat().st_mtime_ns]
    with (output / ".active.lock").open("a+b") as handle:
        assert module.try_os_lock(handle)
        module.release_os_lock(handle)


def test_active_cleanup_preserves_a_different_owner(tmp_path: Path) -> None:
    output = tmp_path / "run"
    output.mkdir()
    with module._active_launch(output):
        marker = read_json(output / ".active")
        foreign = {**marker, "owner": "different-owner"}
        module.write_progress(output / ".active", foreign)
    assert read_json(output / ".active") == foreign
    with (output / ".active.lock").open("a+b") as handle:
        assert module.try_os_lock(handle)
        module.release_os_lock(handle)


@pytest.mark.parametrize("close_failure", (False, True))
def test_os_lock_blocks_live_child_and_recovers_after_child_death(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, close_failure: bool) -> None:
    import subprocess
    import sys
    import time

    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp/run"
    output.mkdir(parents=True)
    active, lock_path, ready = output / ".active", output / ".active.lock", output / "child-ready"
    write_json(output / "progress.json", {"complete": False, "release_pending": False, "completed": {}})
    child_code = """
import os
import sys
import time
from pathlib import Path
from research_core.artifact_store import release_os_lock, try_os_lock, write_json

output, ready = Path(sys.argv[1]), Path(sys.argv[2])
lock = output / ".active.lock"
handle = lock.open("a+b")
if not try_os_lock(handle):
    raise RuntimeError("synthetic child could not acquire OS lock")
try:
    write_json(output / ".active", {
        "schema": "pattern-scan-local-active.v5", "owner": "synthetic-child",
        "pid": os.getpid(), "lock_path": str(lock),
    })
    ready.write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        time.sleep(0.1)
finally:
    release_os_lock(handle)
    handle.close()
"""
    starts: list[dict[str, Any]] = []
    teardown: list[str] = []

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 8 * 1024**3

        def start(self, command: list[str], root: Path) -> SimpleNamespace:
            starts.append(read_json(active))
            return SimpleNamespace(poll=lambda: 0, returncode=0, args=command)

        def memory_receipt(self) -> dict[str, int]:
            return {"peak_committed_bytes": 10}

        def terminate_and_confirm(self) -> None:
            teardown.append("terminate")

        def close(self) -> None:
            teardown.append("close")
            if close_failure:
                raise OSError("synthetic Job close failure")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", Job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(output), str(ready)],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 15.0
        while not ready.is_file():
            if child.poll() is not None:
                stdout, stderr = child.communicate(timeout=5)
                pytest.fail(f"synthetic lock holder exited: {stdout} {stderr}")
            if time.monotonic() >= deadline:
                pytest.fail("synthetic lock holder did not become ready before timeout")
            time.sleep(0.05)
        contents, before, inode = active.read_bytes(), active.stat().st_mtime_ns, lock_path.stat().st_ino
        with pytest.raises(RuntimeError, match="locked"):
            module.launch_remaining([], repo, output, timeout_seconds=1)
        assert active.read_bytes() == contents and active.stat().st_mtime_ns == before
        assert not starts
        child.kill()
        child.wait(timeout=5)
        # Windows releases a dead process's file locks asynchronously; on a busy runner
        # (parallel test workers) that can lag the exit, so wait for the OS release itself.
        release_deadline = time.monotonic() + 10.0
        with lock_path.open("a+b") as probe:
            while not module.try_os_lock(probe):
                if time.monotonic() >= release_deadline:
                    pytest.fail("OS did not release the dead child's lock before timeout")
                time.sleep(0.05)
            module.release_os_lock(probe)
        assert read_json(active)["owner"] == "synthetic-child"
        if close_failure:
            with pytest.raises(OSError, match="Job close failure"):
                module.launch_remaining([], repo, output, timeout_seconds=1)
        else:
            module.launch_remaining([], repo, output, timeout_seconds=1)
        assert len(starts) == 1 and starts[0]["owner"] != "synthetic-child"
        assert starts[0]["schema"] == module.ACTIVE_SCHEMA and starts[0]["lock_path"] == str(lock_path)
        assert teardown == ["terminate", "close"]
        assert not active.exists()
        assert lock_path.is_file() and lock_path.stat().st_ino == inode
        with lock_path.open("a+b") as handle:
            assert module.try_os_lock(handle)
            module.release_os_lock(handle)
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_launcher_relays_child_progress_and_never_releases_hold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp" / "run"
    output.mkdir(parents=True)
    completed: dict[str, dict[str, dict[str, str]]] = {"H1": dict.fromkeys(module.PHASES, {})}
    child_progress = {"step": 1, "total": 3, "label": "conditions group 1/3"}
    write_json(
        output / "progress.json", {"complete": False, "release_pending": True, "completed": completed, "progress": {"step": 0, "total": 3, "label": "starting"}}
    )
    release_calls: list[list[str]] = []
    polls = 0

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 8 * 1024**3

        def start(self, command: list[str], root: Path) -> SimpleNamespace:
            def poll() -> int | None:
                nonlocal polls
                polls += 1
                if polls == 1:
                    module.write_progress(
                        output / "progress.json", {"complete": False, "release_pending": True, "completed": completed, "progress": child_progress}
                    )
                    return None
                return 0

            return SimpleNamespace(poll=poll, returncode=0, args=command)

        def memory_receipt(self) -> dict[str, int]:
            return {"peak_committed_bytes": 10}

        def terminate_and_confirm(self) -> None:
            pass

        def close(self) -> None:
            pass

    def release(command: list[str], **kwargs: Any) -> SimpleNamespace:
        release_calls.append(command)
        raise AssertionError("launcher must leave the external hold for its owner")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", Job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    monkeypatch.setattr(subprocess, "run", release)
    monkeypatch.setattr(module, "PATTERNS", ("H1",))
    observed: list[dict[str, Any]] = []
    final = module.launch_remaining([], repo, output, timeout_seconds=10, on_progress=observed.append)
    assert observed == [child_progress]
    assert final["progress"] == child_progress
    assert final["release_pending"] is True
    assert release_calls == []


@pytest.mark.parametrize("receipt_write_fails", (False, True))
def test_timeout_records_job_peak_and_always_closes_owned_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt_write_fails: bool) -> None:
    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp/run"
    output.mkdir(parents=True)
    calls: list[str] = []
    ticks = iter((0.0, 2.0, 3.0))

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 8 * 1024**3

        def start(self, command: list[str], root: Path) -> SimpleNamespace:
            calls.append("start")
            return SimpleNamespace(poll=lambda: None, returncode=None, args=command)

        def memory_receipt(self) -> dict[str, int]:
            calls.append("memory")
            return {"peak_committed_bytes": 12345}

        def terminate_and_confirm(self) -> None:
            calls.append("terminate")

        def close(self) -> None:
            calls.append("close")

    original_write = module.write_progress

    def write(path: Path, value: dict[str, Any]) -> None:
        if path.name == "job-memory.json" and receipt_write_fails:
            raise OSError("synthetic receipt write failure")
        original_write(path, value)

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", Job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(module, "write_progress", write)
    error = OSError if receipt_write_fails else TimeoutError
    with pytest.raises(error, match="synthetic receipt" if receipt_write_fails else "explicit timeout"):
        module.launch_remaining([], repo, output, timeout_seconds=1)
    assert calls == ["start", "memory", "terminate", "close"]
    assert not (output / ".active").exists()
    if not receipt_write_fails:
        assert read_json(output / "job-memory.json") == {"peak_committed_bytes": 12345, "wall_seconds": 3.0, "exit_code": None, "timed_out": True}
