"""Synthetic bounded-worker and owned-process lifecycle checks; no market IO."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_recovery_pilot_v1 as pilot
from research_core.artifact_store import canonical
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.scratch_runs import ScratchRunError
from scripts import run_l1_recovery_pilot as cli

EXECUTOR = {"commit": "a" * 40, "dirty": False}


def _json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(body))


def _descriptor(path: Path, *, name: str | None = None) -> dict[str, Any]:
    body = path.read_bytes()
    return {"path": str(path) if name is None else name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _tamper_same_length(path: Path) -> None:
    """Change bytes while preserving size and mtime, so stamps alone cannot win."""
    before = path.stat()
    body = path.read_bytes()
    assert body
    path.write_bytes(bytes([body[0] ^ 1]) + body[1:])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.fixture
def worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    stock, repo, output = tmp_path / "inputs", tmp_path / "repo", tmp_path / "output"
    repo.mkdir()
    for name in ("phase-stock-result.json", "derived-preparation.json", "global/receipt.json"):
        _json(stock / name, {"synthetic": True})
    stock_dir = stock / "parts" / "0001"
    _json(stock_dir / "receipt.json", {"synthetic": True})
    for name in ("cohort_events", "base_labels", "indicators", "common_values"):
        (stock_dir / f"{name}.parquet").write_bytes(b"synthetic fingerprint-only input; reader is mocked")
    global_path = stock / "global" / "0001.parquet"
    global_path.write_bytes(b"synthetic fingerprint-only global; reader is mocked")
    calls: list[str] = []
    metrics = {"full_sweeps": 1, "scoped_sweeps": 0, "file_observations": 0, "directory_observations": 0, "ancestor_observations": 0}

    def unchanged() -> None:
        # load_recovery_inventory owns the first global gate; this mock starts
        # after that gate and records the two worker-level gates.
        calls.append("unchanged")
        metrics["full_sweeps"] += 1

    reads = SimpleNamespace(unchanged=unchanged, metrics=metrics)
    inventory = SimpleNamespace(
        measurement={"synthetic": True},
        retained={},
        _reads=reads,
        rows={"0001": {"output_path": str(stock_dir)}},
        barrier={"global_files": {"0001": {"path": str(global_path)}}},
        runtime_audit={"runtime_differs": True, "original_runtime_reexecuted": False, "synthetic": True},
    )
    events = pd.DataFrame([
        {
            "security_id": "TW:0001",
            "event_id": "synthetic-event",
            "t0": "2020-01-06",
            "horizon": horizon,
            "pattern_id": "L1",
            "cohort_id": "union",
            "effective_label": "hit",
            "calendar_full": True,
            "event_main_eligible": True,
            "event_eligibility_excluded": False,
        }
        for horizon in (126, 252)
    ])
    conditions = pd.DataFrame([
        {
            "event_id": "synthetic-event",
            "G_bin": "150to200",
            "G_status": "known",
            "G_reason": None,
            "VOL_a_bin": "le070",
            "VOL_a_status": "known",
            "VOL_a_reason": None,
        }
    ])

    def recover(found: Any, code: str) -> SimpleNamespace:
        assert found is inventory
        calls.append(code)
        return SimpleNamespace(
            events=events,
            conditions=conditions,
            memberships=pd.DataFrame({"group_id": ["pattern:union"], "event_id": ["synthetic-event"]}),
            markets=pd.Series(["mixed"], index=["2020-01-06"]),
            audit={"code": code, "event_count": 1, "historical_parity_verified": False},
        )

    monkeypatch.setattr(pilot, "load_recovery_inventory", lambda *args, **kwargs: inventory)
    monkeypatch.setattr(pilot, "recover_stock", recover)
    arguments = {
        "requested_codes": ("0001",),
        "expected_input_id": "SYNTH-input",
        "expected_source_id": "SYNTH-source",
        "expected_label_version_id": "SYNTH-label",
        "expected_calendar_n": 1,
        "expected_stock_n": 1,
        "expected_retained_n": 0,
        "repo_root": repo,
        "run_id": "synthetic-pilot",
        "expected_code": EXECUTOR,
    }
    return SimpleNamespace(stock=stock, repo=repo, output=output, calls=calls, arguments=arguments, inventory=inventory)


def test_worker_preserves_selected_rows_and_does_not_claim_full_parity(worker: SimpleNamespace) -> None:
    before = {str(path): path.read_bytes() for path in worker.stock.rglob("*") if path.is_file()}
    audit = pilot.run_pilot_worker(worker.stock, worker.output, **worker.arguments)
    assert worker.calls == ["0001", "unchanged", "unchanged"]
    assert audit["selected_codes"] == ["0001"]
    assert audit["full_q1_parity"] == audit["full_marginal_parity"] == "not_run"
    assert audit["runtime_provenance"] == {"runtime_differs": True, "original_runtime_reexecuted": False, "synthetic": True}
    assert set(audit["input_fingerprint"]["inputs"]) == {
        "stock_index",
        "preparation",
        "global",
        "0001:stock_receipt",
        "0001:cohort_events",
        "0001:base_labels",
        "0001:indicators",
        "0001:common_values",
        "0001:global",
    }
    assert audit["stocks"] == [{"code": "0001", "event_count": 1, "historical_parity_verified": False}]
    assert audit["stability_checks"]["full_sweeps"] == 3
    assert audit["stability_checks"] == worker.inventory._reads.metrics
    assert audit["stability_checks"] is not worker.inventory._reads.metrics
    assert {item["path"] for item in audit["payload_descriptors"]} == {
        "0001-events.parquet",
        "0001-conditions.parquet",
        "q1-summary.parquet",
        "q1-annual.parquet",
        "marginal-summary.parquet",
        "marginal-annual.parquet",
    }
    for descriptor in audit["payload_descriptors"]:
        assert descriptor == _descriptor(worker.output / descriptor["path"], name=descriptor["path"])
    assert {path.name for path in worker.output.iterdir()} == {
        "0001-events.parquet",
        "0001-conditions.parquet",
        "q1-summary.parquet",
        "q1-annual.parquet",
        "marginal-summary.parquet",
        "marginal-annual.parquet",
        "audit.json",
    }
    assert read_frame(worker.output / "0001-events.parquet").horizon.tolist() == [126, 252]
    assert before == {str(path): path.read_bytes() for path in worker.stock.rglob("*") if path.is_file()}


@pytest.mark.parametrize("kind", ["existing", "inside_input", "input_ancestor", "inside_repo", "repo_ancestor"])
def test_worker_rejects_existing_or_overlapping_output_before_inventory(worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    targets = {
        "existing": worker.output,
        "inside_input": worker.stock / "new-output",
        "input_ancestor": worker.stock.parent,
        "inside_repo": worker.repo / "new-output",
        "repo_ancestor": worker.repo.parent,
    }
    if kind == "existing":
        worker.output.mkdir()
        (worker.output / "keep.txt").write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(pilot, "load_recovery_inventory", lambda *args, **kwargs: pytest.fail("unsafe output reached inventory"))
    with pytest.raises(ValueError, match="fresh|separate"):
        pilot.run_pilot_worker(worker.stock, targets[kind], **worker.arguments)
    if kind == "existing":
        assert (worker.output / "keep.txt").read_text(encoding="utf-8") == "preserve"


def test_outside_pool_does_not_recover_or_publish(worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: Any, **kwargs: Any) -> None:
        raise ValueError("requested code outside stock pool")

    monkeypatch.setattr(pilot, "load_recovery_inventory", reject)
    with pytest.raises(ValueError, match="outside stock pool"):
        pilot.run_pilot_worker(worker.stock, worker.output, **worker.arguments)
    assert worker.calls == []
    assert not worker.output.exists()


def test_serialized_output_budget_fails_before_publication(worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pilot, "OUTPUT_LIMIT", 2 * 1024**2 + 10)
    with pytest.raises(ValueError, match="output budget"):
        pilot.run_pilot_worker(worker.stock, worker.output, **worker.arguments)
    assert not worker.output.exists()


@pytest.mark.parametrize("target", ["0001-events.parquet", "audit.json"])
def test_worker_rejects_same_length_tamper_after_shared_publication(worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    publish = pilot.publish_generated_bytes
    attacked: list[Path] = []

    def corrupt(path: Path, body: bytes, **kwargs: Any) -> None:
        publish(path, body, **kwargs)
        if path.name == target:
            _tamper_same_length(path)
            attacked.append(path)

    monkeypatch.setattr(pilot, "publish_generated_bytes", corrupt)
    with pytest.raises(ValueError, match="hash/size mismatch"):
        pilot.run_pilot_worker(worker.stock, worker.output, **worker.arguments)
    assert attacked == [worker.output / target]
    if target != "audit.json":
        assert not (worker.output / "audit.json").exists()


@pytest.mark.parametrize("replacement", ["directory", "symlink", "junction"])
def test_worker_rejects_output_directory_replacement_after_first_publication(
    worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    publish, lstat = pilot.publish_generated_bytes, Path.lstat
    attacked: list[Path] = []

    def replaced_lstat(path: Path, *args: Any, **kwargs: Any) -> Any:
        info = lstat(path, *args, **kwargs)
        if attacked and path == worker.output and replacement != "directory":
            # Native Windows junction coverage lives with the path-guard tests;
            # these two cases inject its actual lstat contract at the pilot gate.
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            if replacement == "symlink":
                fields["st_mode"] = stat.S_IFLNK | 0o777
            else:
                fields["st_file_attributes"] = getattr(info, "st_file_attributes", 0) | stat.FILE_ATTRIBUTE_REPARSE_POINT
            return SimpleNamespace(**fields)
        return info

    def replace(path: Path, body: bytes, **kwargs: Any) -> None:
        publish(path, body, **kwargs)
        if not attacked:
            if replacement == "directory":
                original = worker.output.with_name("preserved-original-output")
                worker.output.rename(original)
                shutil.copytree(original, worker.output)
            attacked.append(path)

    monkeypatch.setattr(Path, "lstat", replaced_lstat)
    monkeypatch.setattr(pilot, "publish_generated_bytes", replace)
    with pytest.raises(ValueError, match="changed|linked|reparse|symlink"):
        pilot.run_pilot_worker(worker.stock, worker.output, **worker.arguments)
    assert len(attacked) == 1
    assert not (worker.output / "audit.json").exists()


@pytest.mark.parametrize("gate", ["before_output", "after_output"])
def test_worker_input_consistency_gates_prevent_audit_publication(worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, gate: str) -> None:
    original = pilot.assert_inputs_unchanged
    observations = []

    def check(fingerprint: dict[str, Any]) -> None:
        exists = worker.output.exists()
        observations.append(exists)
        if exists == (gate == "after_output"):
            raise ValueError("synthetic global input stability rejection")
        original(fingerprint)

    monkeypatch.setattr(pilot, "assert_inputs_unchanged", check)
    with pytest.raises(ValueError, match="global input stability"):
        pilot.run_pilot_worker(worker.stock, worker.output, **worker.arguments)
    assert observations == ([False] if gate == "before_output" else [False, True])
    assert not (worker.output / "audit.json").exists()


@pytest.fixture
def supervisor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    stock, repo, scratch = tmp_path / "stock", tmp_path / "repo", tmp_path / "scratch"
    stock.mkdir()
    repo.mkdir()
    scratch.mkdir()
    state = SimpleNamespace(
        mode="success",
        held=False,
        created=0,
        started=0,
        terminated=0,
        closed=0,
        memory=None,
        command=None,
        heartbeats=[],
        marks=[],
        seconds=0.0,
        sleep_step=0.5,
        after_receipt=None,
        after_start=None,
    )
    target = scratch / pilot.TASK / "synthetic-pilot"

    class Run:
        path = target

        def __enter__(self) -> Any:
            state.held = True
            return self

        def __exit__(self, *args: Any) -> None:
            state.held = False

        def heartbeat(self, *, progress: dict[str, Any]) -> None:
            assert state.held
            state.heartbeats.append(progress)

        def mark(self, status: str) -> None:
            assert state.held
            state.marks.append(status)

    def create(*args: Any, **kwargs: Any) -> Run:
        state.created += 1
        assert kwargs["depends_on"] == (str(stock.resolve()),)
        if state.mode == "busy":
            raise ScratchRunError("synthetic scratch lock already held")
        target.mkdir(parents=True)
        return Run()

    class Process:
        returncode: int | None = None
        args = ["synthetic-child"]

        def poll(self) -> int | None:
            if state.mode == "timeout" or (state.mode == "heartbeat" and state.seconds < 21):
                return None
            self.returncode = 7 if state.mode == "failed" else 0
            return self.returncode

    class Job:
        def __init__(self, memory: int) -> None:
            state.memory = memory

        def start(self, command: list[str], cwd: Path) -> Process:
            assert state.held
            state.started += 1
            state.command = command
            assert cwd == repo
            if state.mode == "start_failed":
                raise RuntimeError("synthetic assignment failed")
            request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            state.request = request
            if state.mode not in ("timeout", "failed"):
                output = Path(request["output"])
                output.mkdir()
                names = {f"{code}-{kind}.parquet" for code in request["codes"] for kind in ("events", "conditions")} | {
                    "q1-summary.parquet",
                    "q1-annual.parquet",
                    "marginal-summary.parquet",
                    "marginal-annual.parquet",
                }
                for name in sorted(names):
                    (output / name).write_bytes(b"synthetic supervisor-only serialized output: " + name.encode())
                _json(
                    output / "audit.json",
                    {
                        "selected_codes": request["codes"],
                        "expected_code": EXECUTOR,
                        "input_fingerprint": {"inputs": {}},
                        "full_q1_parity": "not_run",
                        "full_marginal_parity": "not_run",
                        "payload_descriptors": [_descriptor(output / name, name=name) for name in sorted(names)],
                        "stability_checks": {"full_sweeps": 3},
                    },
                )
                if state.after_start is not None:
                    state.after_start(output)
            return Process()

        def memory_receipt(self) -> dict[str, Any]:
            return {"memory_limit_bytes": state.memory, "synthetic": True}

        def terminate_and_confirm(self) -> None:
            assert state.held
            state.terminated += 1
            if state.mode == "teardown_failed":
                raise RuntimeError("owned Windows job teardown could not be confirmed")

        def close(self) -> None:
            state.closed += 1

    def sleep(seconds: float) -> None:
        state.seconds += state.sleep_step

    def receipt(path: Path, **kwargs: Any) -> dict[str, Any]:
        state.receipt = kwargs
        body = {"complete": True, "results": {name: _descriptor(result) for name, result in sorted(kwargs["results"].items())}}
        path.write_bytes(canonical(body))
        if state.after_receipt is not None:
            state.after_receipt(path, body, kwargs)
        return body

    monkeypatch.setattr(pilot, "sys", SimpleNamespace(platform="win32", executable=sys.executable))
    monkeypatch.setattr(pilot, "time", SimpleNamespace(monotonic=lambda: state.seconds, sleep=sleep))
    monkeypatch.setattr(pilot, "code_identity", lambda root: EXECUTOR)
    monkeypatch.setattr(pilot.scratch_runs, "scratch_root", lambda **kwargs: scratch)
    monkeypatch.setattr(pilot.scratch_runs, "create_run", create)
    monkeypatch.setattr(pilot, "_MemoryBoundJob", Job)
    monkeypatch.setattr(pilot, "write_run_receipt", receipt)
    state.stock, state.repo, state.target = stock, repo, target
    return state


def _launch(state: SimpleNamespace, codes: tuple[str, ...] = ("0001",)) -> Path:
    return pilot.launch_pilot(state.stock, codes=codes, run_id="synthetic-pilot", owner="synthetic-test", repo_root=state.repo)


def test_supervisor_owns_one_bounded_child_and_retains_reviewable_run(supervisor: SimpleNamespace) -> None:
    result = _launch(supervisor)
    assert result == supervisor.target
    assert supervisor.memory == 2 * 1024**3
    assert supervisor.started == supervisor.terminated == supervisor.closed == 1
    assert supervisor.marks == ["complete"]
    assert supervisor.held is False
    assert supervisor.request["codes"] == ["0001"]
    assert supervisor.receipt["parameters"]["full_q1_parity"] == "not_run"
    assert supervisor.receipt["parameters"]["full_marginal_parity"] == "not_run"
    assert supervisor.heartbeats[-1]["step"] == supervisor.heartbeats[-1]["total"] == 1
    assert (result / "request.json").is_file()
    assert (result / "job-memory.json").is_file()
    assert (result / "receipt.json").is_file()


@pytest.mark.parametrize("codes", [(), ("0001", "0001"), ("",), tuple(str(i) for i in range(6))])
def test_supervisor_rejects_invalid_codes_before_any_input_or_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, codes: tuple[str, ...]) -> None:
    monkeypatch.setattr(pilot, "code_identity", lambda *args: pytest.fail("invalid selection reached code or inputs"))
    with pytest.raises(ValueError, match="one to five"):
        pilot.launch_pilot(tmp_path / "absent", codes=codes, run_id="synthetic-pilot", owner="synthetic-test", repo_root=tmp_path / "absent-repo")


@pytest.mark.parametrize(
    "mode,error", [("failed", subprocess.CalledProcessError), ("timeout", TimeoutError), ("start_failed", RuntimeError), ("teardown_failed", RuntimeError)]
)
def test_failed_owned_job_never_leaves_success_receipt(supervisor: SimpleNamespace, mode: str, error: type[Exception]) -> None:
    supervisor.mode = mode
    supervisor.sleep_step = 301.0
    with pytest.raises(error):
        _launch(supervisor)
    assert supervisor.terminated >= 1 and supervisor.closed == 1
    assert supervisor.marks == []
    assert not (supervisor.target / "receipt.json").exists()
    assert supervisor.held is False
    if mode == "timeout":
        failure = json.loads((supervisor.target / "job-failure.json").read_text(encoding="utf-8"))
        assert failure["timed_out"] is True
        assert failure["wall_seconds"] >= 600


def test_scratch_lock_failure_prevents_child_start(supervisor: SimpleNamespace) -> None:
    supervisor.mode = "busy"
    with pytest.raises(ScratchRunError, match="lock"):
        _launch(supervisor)
    assert supervisor.started == supervisor.closed == 0


def test_existing_run_is_not_overwritten(supervisor: SimpleNamespace) -> None:
    supervisor.target.mkdir(parents=True)
    saved = supervisor.target / "keep.txt"
    saved.write_text("owned elsewhere", encoding="utf-8")
    with pytest.raises(FileExistsError):
        _launch(supervisor)
    assert saved.read_text(encoding="utf-8") == "owned elsewhere"
    assert supervisor.started == 0


def test_heartbeat_is_written_while_job_lock_is_held(supervisor: SimpleNamespace) -> None:
    supervisor.mode = "heartbeat"
    supervisor.sleep_step = 10.5
    _launch(supervisor)
    assert len(supervisor.heartbeats) >= 3
    assert supervisor.heartbeats[0]["label"] == "pilot worker running"
    assert supervisor.heartbeats[-1]["step"] == 1


def test_supervisor_total_output_budget_does_not_publish_success(supervisor: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pilot, "OUTPUT_LIMIT", 1024**2)
    with pytest.raises(ValueError, match="output budget"):
        _launch(supervisor)
    assert not (supervisor.target / "receipt.json").exists()
    assert supervisor.marks == []
    assert supervisor.terminated == supervisor.closed == 1


def test_changed_executor_does_not_publish_success(supervisor: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    identities = iter([EXECUTOR, {"commit": "b" * 40, "dirty": False}])
    monkeypatch.setattr(pilot, "code_identity", lambda root: next(identities))
    with pytest.raises(ValueError, match="identity differs"):
        _launch(supervisor)
    assert not (supervisor.target / "receipt.json").exists()
    assert supervisor.marks == []
    assert supervisor.terminated == supervisor.closed == 1


@pytest.mark.parametrize("mutation", ["same_length", "extra_file", "missing_file", "duplicate_descriptor"])
def test_supervisor_rejects_payload_mutation_before_receipt(supervisor: SimpleNamespace, mutation: str) -> None:
    def attack(output: Path) -> None:
        if mutation == "same_length":
            _tamper_same_length(output / "0001-events.parquet")
        elif mutation == "extra_file":
            (output / "unclaimed.parquet").write_bytes(b"synthetic unexpected output")
        elif mutation == "missing_file":
            (output / "0001-events.parquet").unlink()
        else:
            audit_path = output / "audit.json"
            audit = json.loads(audit_path.read_bytes())
            audit["payload_descriptors"][0] = audit["payload_descriptors"][1].copy()
            _json(audit_path, audit)

    supervisor.after_start = attack
    with pytest.raises((ValueError, FileNotFoundError)):
        _launch(supervisor)
    assert supervisor.marks == []
    assert not (supervisor.target / "receipt.json").exists()
    assert not hasattr(supervisor, "receipt")
    assert supervisor.terminated == supervisor.closed == 1


@pytest.mark.parametrize("mutation", ["audit_after_read", "output_directory"])
def test_supervisor_audit_read_has_a_following_stability_gate(supervisor: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    read = pilot._Reads.json
    attacked: list[Path] = []

    def unstable_read(guard: Any, path: Path, **kwargs: Any) -> dict[str, Any]:
        result = read(guard, path, **kwargs)
        if path.name == "audit.json" and not attacked:
            if mutation == "audit_after_read":
                _tamper_same_length(path)
            else:
                original = path.parent.with_name("preserved-original-payload")
                path.parent.rename(original)
                shutil.copytree(original, path.parent)
            attacked.append(path)
        return result

    monkeypatch.setattr(pilot._Reads, "json", unstable_read)
    with pytest.raises(ValueError, match="changed|hash/size mismatch"):
        _launch(supervisor)
    assert len(attacked) == 1
    assert supervisor.marks == []
    assert not (supervisor.target / "receipt.json").exists()
    assert not hasattr(supervisor, "receipt")


def test_supervisor_checks_job_memory_against_original_canonical_bytes(supervisor: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    write = pilot.write_json
    attacked = []

    def unstable_write(path: Path, body: Any) -> None:
        write(path, body)
        if path.name == "job-memory.json":
            _tamper_same_length(path)
            attacked.append(path)

    monkeypatch.setattr(pilot, "write_json", unstable_write)
    with pytest.raises(ValueError, match="hash/size mismatch"):
        _launch(supervisor)
    assert len(attacked) == 1
    assert supervisor.marks == []
    assert not (supervisor.target / "receipt.json").exists()
    assert not hasattr(supervisor, "receipt")


@pytest.mark.parametrize(
    "mutation",
    [
        "result_hash",
        "result_bytes",
        "result_path",
        "result_inventory",
        "staged_receipt_bytes",
        "payload_after_receipt",
        "audit_after_receipt",
        "job_after_receipt",
    ],
)
def test_staging_receipt_failure_cannot_publish_or_mark_complete(supervisor: SimpleNamespace, mutation: str) -> None:
    attacked = []

    def attack(path: Path, body: dict[str, Any], kwargs: dict[str, Any]) -> None:
        assert path.name == ".staging-receipt.json"
        assert not (path.parent / "receipt.json").exists()
        selected = next(iter(body["results"]))
        if mutation == "result_hash":
            body["results"][selected]["sha256"] = "0" * 64
        elif mutation == "result_bytes":
            body["results"][selected]["bytes"] += 1
        elif mutation == "result_path":
            body["results"][selected]["path"] = str(path.parent / "unrelated-result")
        elif mutation == "result_inventory":
            body["results"].pop(selected)
        elif mutation == "staged_receipt_bytes":
            _tamper_same_length(path)
        else:
            name = {"payload_after_receipt": "0001-events.parquet", "audit_after_receipt": "audit.json", "job_after_receipt": "job-memory.json"}[mutation]
            _tamper_same_length(kwargs["results"][name])
        if mutation.startswith("result_"):
            # Return bytes-consistent but false descriptors: comparison to the
            # pre-write expected descriptors must reject this independently.
            path.write_bytes(canonical(body))
        attacked.append(path)

    supervisor.after_receipt = attack
    with pytest.raises(ValueError, match="receipt|hash/size mismatch"):
        _launch(supervisor)
    assert attacked == [supervisor.target / ".staging-receipt.json"]
    assert supervisor.marks == []
    assert not (supervisor.target / "receipt.json").exists()
    assert (supervisor.target / ".staging-receipt.json").exists()
    assert supervisor.terminated == supervisor.closed == 1


@pytest.mark.parametrize("gate", ["before_receipt", "after_receipt"])
def test_supervisor_input_consistency_gates_leave_no_final_receipt(supervisor: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, gate: str) -> None:
    observations = []

    def check(fingerprint: dict[str, Any]) -> None:
        assert fingerprint == {"inputs": {}}
        staged = (supervisor.target / ".staging-receipt.json").exists()
        observations.append(staged)
        if staged == (gate == "after_receipt"):
            raise ValueError("synthetic final input stability rejection")

    monkeypatch.setattr(pilot, "assert_inputs_unchanged", check)
    with pytest.raises(ValueError, match="input stability"):
        _launch(supervisor)
    assert observations == ([False] if gate == "before_receipt" else [False, True])
    assert supervisor.marks == []
    assert not (supervisor.target / "receipt.json").exists()


@pytest.mark.parametrize("target", ["0001-events.parquet", "audit.json", "job-memory.json", "receipt.json"])
def test_post_publication_mutation_is_retained_as_failure_without_marking_complete(
    supervisor: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    publish = pilot.publish_noreplace
    attacked = []

    def unstable_publish(source: Path, destination: Path) -> None:
        publish(source, destination)
        if destination.name == "receipt.json":
            root = destination.parent if target in ("job-memory.json", "receipt.json") else destination.parent / "payload"
            _tamper_same_length(root / target)
            attacked.append(root / target)

    monkeypatch.setattr(pilot, "publish_noreplace", unstable_publish)
    with pytest.raises(ValueError, match="hash/size mismatch"):
        _launch(supervisor)
    assert len(attacked) == 1
    assert supervisor.marks == []
    # Publication already happened. Keep its bytes and failure record; the
    # terminal gate prevents a success mark rather than undoing publication.
    assert (supervisor.target / "receipt.json").exists()
    assert (supervisor.target / "job-failure.json").exists()
    assert not (supervisor.target / ".staging-receipt.json").exists()
    assert supervisor.terminated == supervisor.closed == 1


def test_cli_passes_explicit_selection_to_bounded_launcher(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    observed: dict[str, Any] = {}

    def capture(stock_root: Path, **kwargs: Any) -> Path:
        observed.update(stock_root=stock_root, **kwargs)
        return Path("synthetic-scratch-run")

    monkeypatch.setattr(cli, "launch_pilot", capture)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_l1_recovery_pilot",
            "--stock-root",
            "synthetic-input",
            "--code",
            "0001",
            "--code",
            "0002",
            "--run-id",
            "synthetic-pilot",
            "--owner",
            "synthetic-test",
        ],
    )
    cli.main()
    assert observed == {
        "stock_root": Path("synthetic-input"),
        "codes": ("0001", "0002"),
        "run_id": "synthetic-pilot",
        "owner": "synthetic-test",
        "repo_root": Path(cli.__file__).resolve().parents[1],
    }
    assert capsys.readouterr().out.strip() == "synthetic-scratch-run"


def test_cli_requires_explicit_codes_before_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "launch_pilot", lambda *args, **kwargs: pytest.fail("missing selection launched a worker"))
    monkeypatch.setattr(sys, "argv", ["run_l1_recovery_pilot", "--stock-root", "synthetic-input", "--run-id", "synthetic-pilot", "--owner", "synthetic-test"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_bootstrap_sets_thread_limits_before_importing_worker(tmp_path: Path) -> None:
    # Execute only the tiny bootstrap in a child with a stub package: no numerical
    # imports, no real worker and no market paths are available in this probe.
    package = tmp_path / "research_core"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "pattern_scan_recovery_pilot_v1.py").write_text(
        "import os,sys\n"
        "assert 'numpy' not in sys.modules and 'pandas' not in sys.modules\n"
        "assert all(os.environ.get(k)=='1' for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS'))\n"
        "def worker_main(path):\n    path.write_text('stub-worker-only',encoding='utf-8')\n",
        encoding="utf-8",
    )
    result_path = tmp_path / "probe-result.txt"
    result = subprocess.run(
        [sys.executable, "-B", "-c", pilot.PILOT_BOOTSTRAP, str(tmp_path), str(result_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result_path.read_text(encoding="utf-8") == "stub-worker-only"
