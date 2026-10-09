"""Explicit single-job execution with verified reuse; not a security seal.

Only reviewed local Python programs belong in packets. They execute with the
caller's permissions. Input completeness and scientific design require review;
hashes cannot discover undeclared reads or prove PIT/executable-fill correctness.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from research_core.evidence import EvidenceError, date_window, finite_json, read_json, safe_identifier, text_field

PACKET_VERSION = "research-job.v1"
RECEIPT_VERSION = "research-receipt.v1"


def digest(value: Any) -> str:
    finite_json(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def confined(root: Path, relative: str) -> Path:
    """Reject traversal, Windows aliases and links, including existing ancestors."""
    text_field(relative, "path")
    win = PureWindowsPath(relative)
    if win.is_absolute() or win.drive or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise EvidenceError(f"not a normalized relative path: {relative}")
    if any(re.search(r'[<>:"|?*]', part) or part.endswith((" ", ".")) or PureWindowsPath(part).is_reserved() for part in relative.split("/")):
        raise EvidenceError("unsupported path component")
    base = root.absolute()
    target = base / relative
    for path in (base, *[base.joinpath(*Path(relative).parts[:i]) for i in range(1, len(Path(relative).parts) + 1)]):
        if path.exists() or path.is_symlink():
            attrs = getattr(path.lstat(), "st_file_attributes", 0)
            if path.is_symlink() or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                raise EvidenceError(f"linked/reparse path forbidden: {path}")
    if not target.resolve().is_relative_to(base.resolve()):
        raise EvidenceError("path escaped root")
    return target


def runtime_identity() -> dict[str, Any]:
    """Record installed package versions without reading env vars or contacting services."""
    packages = sorted([dist.metadata.get("Name", "unknown"), dist.version] for dist in importlib.metadata.distributions())
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable_sha256": file_digest(Path(sys.executable)),
        "packages_sha256": digest(packages),
    }


def validate_packet(packet: Any) -> dict[str, Any]:
    if not isinstance(packet, dict) or packet.get("schema_version") != PACKET_VERSION:
        raise EvidenceError(f"packet must use {PACKET_VERSION}")
    finite_json(packet)
    for key in ("job_id", "task_id"):
        safe_identifier(packet.get(key), key)
    if packet.get("phase") not in {"exploration", "discovery", "confirmation", "holdout", "replication"}:
        raise EvidenceError("phase must be explicit")
    date_window(packet.get("window"))
    for key in ("candidate_id", "owner_contract_id", "metric_contract_id", "execution_contract_id", "scenario_id"):
        text_field(packet.get(key), key)
    if not isinstance(packet.get("params"), dict) or not isinstance(packet.get("runtime"), dict) or not packet["runtime"]:
        raise EvidenceError("params and runtime objects required")
    timeout = packet.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise EvidenceError("timeout_seconds must be an integer in [1, 86400]")
    inputs = packet.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {"code", "data", "contracts"}:
        raise EvidenceError("inputs must declare code, data and contracts")
    seen: set[str] = set()
    for group in inputs.values():
        if not isinstance(group, dict) or not group:
            raise EvidenceError("each input group must contain explicit file hashes")
        for path, sha in group.items():
            text_field(path, "input path")
            canonical = PureWindowsPath(path).as_posix().casefold()
            if canonical in seen or not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
                raise EvidenceError("duplicate input or invalid SHA256")
            seen.add(canonical)
    script = text_field(packet.get("script"), "script")
    if not script.endswith(".py") or script not in inputs["code"]:
        raise EvidenceError("the Python entrypoint must be among hashed code inputs")
    args = packet.get("args")
    if not isinstance(args, list) or any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise EvidenceError("args must be a string list")
    if "{output_dir}" not in args:
        raise EvidenceError("args must contain a literal {output_dir} token for a fresh output root")
    outputs = packet.get("outputs")
    if not isinstance(outputs, list) or not outputs or any(not isinstance(output, str) for output in outputs):
        raise EvidenceError("unique JSON output paths required")
    canonical_outputs = [PureWindowsPath(output).as_posix().casefold() for output in outputs]
    if len(canonical_outputs) != len(set(canonical_outputs)):
        raise EvidenceError("duplicate output path")
    for output in outputs:
        first_component = PureWindowsPath(output).parts[0].casefold() if output else ""
        if not output.endswith(".json") or first_component in {"receipt.json", "state.json", "receipt.pending", "process.log"}:
            raise EvidenceError("invalid output name")
    if packet.get("summary") not in outputs:
        raise EvidenceError("summary must name one declared output")
    return packet


def verify_inputs(root: Path, packet: dict[str, Any]) -> None:
    for group in packet["inputs"].values():
        for relative, expected in group.items():
            path = confined(root, relative)
            if not path.is_file() or file_digest(path) != expected:
                raise EvidenceError(f"input identity mismatch: {relative}")
    if runtime_identity() != packet["runtime"]:
        raise EvidenceError("runtime identity mismatch")


def validate_summary(value: Any) -> None:
    """Structural completion only, compatible with existing backtest summary v1."""
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise EvidenceError("summary schema_version must be 1.0")
    for key in ("run", "strategy", "data", "metrics", "portfolio"):
        if not isinstance(value.get(key), dict):
            raise EvidenceError(f"summary.{key}: required object")
    for key in ("trades", "warnings"):
        if not isinstance(value.get(key), list):
            raise EvidenceError(f"summary.{key}: required list")
    text_field(value.get("generated_at"), "summary.generated_at")
    finite_json(value)


def output_hashes(job_root: Path, packet: dict[str, Any]) -> dict[str, str]:
    hashes = {}
    for relative in packet["outputs"]:
        path = confined(job_root, relative)
        value = read_json(path)
        if relative == packet["summary"]:
            validate_summary(value)
        hashes[relative] = file_digest(path)
    return hashes


def job_directory(root: Path, packet: dict[str, Any]) -> Path:
    return confined(root, f"tasks/{packet['task_id']}/runs/registered/{packet['job_id']}")


def verify_reuse(root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    validate_packet(packet)
    verify_inputs(root, packet)
    job_root = job_directory(root, packet)
    receipt = read_json(confined(job_root, "receipt.json"))
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != RECEIPT_VERSION
        or receipt.get("status") != "completed"
        or receipt.get("packet_sha256") != digest(packet)
        or receipt.get("outputs") != output_hashes(job_root, packet)
    ):
        raise EvidenceError("completion receipt mismatch; preserve files and use a new job_id after diagnosis")
    return receipt


def _write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    # The job root is exclusively created. Never overwrite outputs or a receipt.
    with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_job(root: Path, packet: dict[str, Any], *, expected_digest: str, execute: bool = False) -> dict[str, Any]:
    """Run one approved packet; default is a read-only preflight, never a sweep."""
    validate_packet(packet)
    identity = digest(packet)
    if expected_digest != identity:
        raise EvidenceError("packet differs from the explicitly supplied approved digest")
    verify_inputs(root, packet)
    job_root = job_directory(root, packet)
    for relative in packet["outputs"]:
        confined(job_root, relative)
    if not execute:
        return {"status": "preflight_only", "packet_sha256": identity, "output_dir": str(job_root)}
    if not confined(root, f"tasks/{packet['task_id']}").is_dir():
        raise EvidenceError("task must already exist; this runner never creates a study")
    # Exclusive mkdir is also the single-writer lock. An interrupted directory is
    # retained; it is never guessed complete or silently overwritten on retry.
    try:
        job_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise EvidenceError("job root exists; verify reuse or choose a new job_id, never overwrite") from error
    argv = [sys.executable, str(confined(root, packet["script"])), *[str(job_root) if arg == "{output_dir}" else arg for arg in packet["args"]]]
    state: dict[str, Any] = {
        "schema_version": RECEIPT_VERSION,
        "packet_sha256": identity,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(confined(job_root, "state.json"), state, exclusive=True)
    started = time.monotonic()
    try:
        with confined(job_root, "process.log").open("xb") as log:
            proc = subprocess.run(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=packet["timeout_seconds"], check=False, shell=False)
        if proc.returncode != 0:
            raise EvidenceError(f"process failed with exit code {proc.returncode}; inspect process.log locally")
        verify_inputs(root, packet)
        hashes = output_hashes(job_root, packet)
        receipt = {**state, "status": "completed", "elapsed_seconds": time.monotonic() - started, "outputs": hashes}
        temporary = confined(job_root, "receipt.pending")
        _write_json(temporary, receipt, exclusive=True)
        # Windows/POSIX: destination absent under this exclusively-owned root.
        if confined(job_root, "receipt.json").exists():
            raise EvidenceError("entrypoint wrote a reserved receipt")
        temporary.rename(job_root / "receipt.json")
        _write_json(confined(job_root, "state.json"), receipt)
        return receipt
    except (EvidenceError, OSError, subprocess.SubprocessError) as error:
        _write_json(
            confined(job_root, "state.json"), {**state, "status": "failed", "elapsed_seconds": time.monotonic() - started, "error_type": type(error).__name__}
        )
        raise
