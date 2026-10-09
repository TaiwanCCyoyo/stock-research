import json
import subprocess
import sys
from pathlib import Path

import pytest

from research_core.evidence import EvidenceError
from research_core.jobs import (
    PACKET_VERSION,
    confined,
    digest,
    file_digest,
    job_directory,
    run_job,
    runtime_identity,
    validate_packet,
    verify_reuse,
)

SUMMARY = {
    "schema_version": "1.0",
    "generated_at": "2026-01-01T00:00:00Z",
    "run": {},
    "strategy": {},
    "data": {},
    "metrics": {"return_rate": -0.5},  # A losing result is still structurally complete.
    "portfolio": {},
    "trades": [],
    "warnings": [],
}


def make_repo(tmp_path: Path, body: str | None = None) -> tuple[Path, dict]:
    root = tmp_path / "repo"
    (root / "tasks" / "demo").mkdir(parents=True)
    (root / "inputs").mkdir()
    code = root / "runner.py"
    code.write_text(
        body
        or (f"import json, sys\nfrom pathlib import Path\nPath(sys.argv[1], 'summary.json').write_text({json.dumps(json.dumps(SUMMARY))}, encoding='utf-8')\n"),
        encoding="utf-8",
    )
    data = root / "inputs" / "data.txt"
    contract = root / "inputs" / "contract.txt"
    data.write_text("synthetic data", encoding="utf-8")
    contract.write_text("synthetic contract", encoding="utf-8")
    packet = {
        "schema_version": PACKET_VERSION,
        "job_id": "job-1",
        "task_id": "demo",
        "phase": "confirmation",
        "window": {"start": "2026-01-01", "end": "2026-01-31"},
        "candidate_id": "candidate-1",
        "owner_contract_id": "owner-1",
        "metric_contract_id": "metric-1",
        "execution_contract_id": "execution-1",
        "scenario_id": "scenario-1",
        "params": {"synthetic": True},
        "runtime": runtime_identity(),
        "timeout_seconds": 2,
        "inputs": {
            "code": {"runner.py": file_digest(code)},
            "data": {"inputs/data.txt": file_digest(data)},
            "contracts": {"inputs/contract.txt": file_digest(contract)},
        },
        "script": "runner.py",
        "args": ["{output_dir}"],
        "outputs": ["summary.json"],
        "summary": "summary.json",
    }
    return root, packet


def test_preflight_never_creates_directory_or_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, packet = make_repo(tmp_path)
    monkeypatch.setattr("research_core.jobs.subprocess.run", lambda *args, **kwargs: pytest.fail("must not execute"))
    result = run_job(root, packet, expected_digest=digest(packet))
    assert result["status"] == "preflight_only"
    assert not job_directory(root, packet).exists()


@pytest.mark.parametrize("outputs", [["STATE.json"], ["Receipt.json"], ["Process.log/data.json"], ["summary.json", "SUMMARY.json"]])
def test_windows_output_aliases_rejected_before_creation(tmp_path: Path, outputs: list[str]) -> None:
    root, packet = make_repo(tmp_path)
    packet["outputs"] = outputs
    packet["summary"] = outputs[0]
    with pytest.raises(EvidenceError):
        run_job(root, packet, expected_digest=digest(packet), execute=True)
    assert not job_directory(root, packet).exists()


def test_windows_cross_group_input_alias_rejected(tmp_path: Path) -> None:
    _, packet = make_repo(tmp_path)
    packet["inputs"]["contracts"] = {"INPUTS/DATA.txt": packet["inputs"]["data"]["inputs/data.txt"]}
    with pytest.raises(EvidenceError, match="duplicate input"):
        validate_packet(packet)


def test_synthetic_run_and_reuse_accepts_losing_summary(tmp_path: Path) -> None:
    root, packet = make_repo(tmp_path)
    receipt = run_job(root, packet, expected_digest=digest(packet), execute=True)
    assert receipt["status"] == "completed"
    assert verify_reuse(root, packet)["outputs"] == receipt["outputs"]
    with pytest.raises(EvidenceError, match="job root exists"):
        run_job(root, packet, expected_digest=digest(packet), execute=True)


@pytest.mark.parametrize("change", ["code", "data", "runtime", "scenario"])
def test_reuse_refuses_changed_identity(tmp_path: Path, change: str) -> None:
    root, packet = make_repo(tmp_path)
    run_job(root, packet, expected_digest=digest(packet), execute=True)
    changed = json.loads(json.dumps(packet))
    if change == "code":
        (root / "runner.py").write_text("# changed", encoding="utf-8")
    elif change == "data":
        (root / "inputs" / "data.txt").write_text("changed", encoding="utf-8")
    elif change == "runtime":
        changed["runtime"]["python"] = "changed"
    else:
        changed["scenario_id"] = "scenario-2"
    with pytest.raises(EvidenceError):
        verify_reuse(root, changed)


@pytest.mark.parametrize("damage", ["missing", "malformed", "modified", "receipt"])
def test_reuse_refuses_bad_outputs_or_receipt(tmp_path: Path, damage: str) -> None:
    root, packet = make_repo(tmp_path)
    run_job(root, packet, expected_digest=digest(packet), execute=True)
    job_root = job_directory(root, packet)
    target = job_root / ("receipt.json" if damage == "receipt" else "summary.json")
    if damage == "missing":
        target.unlink()
    elif damage == "malformed":
        target.write_text("{ bad", encoding="utf-8")
    elif damage == "modified":
        target.write_text(json.dumps({**SUMMARY, "metrics": {"return_rate": -0.4}}), encoding="utf-8")
    else:
        target.write_text("{}", encoding="utf-8")
    with pytest.raises(EvidenceError):
        verify_reuse(root, packet)


@pytest.mark.parametrize(
    "body",
    ["raise SystemExit(7)\n", "import time\ntime.sleep(2)\n"],
)
def test_failed_or_timed_out_process_never_writes_receipt(tmp_path: Path, body: str) -> None:
    root, packet = make_repo(tmp_path, body)
    packet["timeout_seconds"] = 1
    packet["inputs"]["code"]["runner.py"] = file_digest(root / "runner.py")
    with pytest.raises((EvidenceError, subprocess.TimeoutExpired)):
        run_job(root, packet, expected_digest=digest(packet), execute=True)
    assert not (job_directory(root, packet) / "receipt.json").exists()


@pytest.mark.parametrize("relative", ["../escape.json", "C:/escape.json", "dir\\escape.json", "name:ads.json", "con.json"])
def test_confinement_rejects_windows_and_reserved_output_paths(tmp_path: Path, relative: str) -> None:
    root, _ = make_repo(tmp_path)
    with pytest.raises(EvidenceError):
        confined(root, relative)


def test_packet_rejects_reserved_output_name(tmp_path: Path) -> None:
    _, packet = make_repo(tmp_path)
    packet["outputs"] = ["receipt.json"]
    packet["summary"] = "receipt.json"
    with pytest.raises(EvidenceError, match="invalid output"):
        validate_packet(packet)


def test_cli_executes_exactly_one_synthetic_job_with_real_runtime(tmp_path: Path) -> None:
    root, packet = make_repo(tmp_path)
    packet_path = root / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    script = Path(__file__).parents[1] / "run_registered_job.py"
    done = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--packet", str(packet_path), "--approved-sha256", digest(packet), "--execute"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(done.stdout)["status"] == "completed"
    assert (job_directory(root, packet) / "receipt.json").is_file()


def test_one_job_never_auto_dispatches_holdout(tmp_path: Path) -> None:
    body = (
        "import json, sys\nfrom pathlib import Path\n"
        "Path('invocations.txt').open('a', encoding='utf-8').write('one\\n')\n"
        f"Path(sys.argv[1], 'summary.json').write_text({json.dumps(json.dumps(SUMMARY))}, encoding='utf-8')\n"
    )
    root, packet = make_repo(tmp_path, body)
    packet["inputs"]["code"]["runner.py"] = file_digest(root / "runner.py")
    run_job(root, packet, expected_digest=digest(packet), execute=True)
    assert (root / "invocations.txt").read_text(encoding="utf-8") == "one\n"


def test_symlink_path_is_rejected_when_supported(tmp_path: Path) -> None:
    root, _ = make_repo(tmp_path)
    link = root / "linked"
    try:
        link.symlink_to(root / "inputs", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(EvidenceError, match="linked"):
        confined(root, "linked/data.txt")
