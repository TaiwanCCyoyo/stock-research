"""Fresh-source, bounded, resumable stock-phase execution protocol.

This reuses the cache SourceFinder and owned Windows Job Object boundary. Source
and input identities are checked before work and again before success receipts.
No global ranking, selection or complete-study publication occurs in a worker.
"""

from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import fields
from pathlib import Path
from typing import Any

from research_core.artifact_store import (
    describe_file,
    file_digest,
    object_digest,
    publish_noreplace,
    read_json,
    relative_name,
    verify_files,
    write_json,
)
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.research_data_paths import DataRoots, _checked_path
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample
from research_core.stock_feature_pool_v1 import runtime_identity
from research_core.windows_process_job import WindowsProcessJob

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).absolute().parents[1]
NUMERICAL_THREADS = {name: "1" for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
BOOTSTRAP = """
import hashlib,logging,os,sys,types
from pathlib import Path
sys.dont_write_bytecode=True
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
root=Path(sys.argv[1]); sys.path.insert(0,str(root))
path=root/'research_core/cache_execution.py'; data=path.read_bytes()
module=types.ModuleType('research_core.cache_execution'); module.__file__=str(path)
module.__package__='research_core'; sys.modules[module.__name__]=module
exec(compile(data,str(path),'exec',dont_inherit=True),module.__dict__)
module._LOADED_SOURCES[path.resolve()]=hashlib.sha256(data).hexdigest()
sys.meta_path.insert(0,module._SourceFinder())
from research_core.pattern_scan_execution_v1 import worker_main
worker_main(Path(sys.argv[2]))
"""
GIT_BOOTSTRAP = """
import logging,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
root=Path(sys.argv[1]); sys.path.insert(0,str(root))
from research_core.pattern_scan_execution_v1 import worker_main
worker_main(Path(sys.argv[2]))
"""


def _git_source(identity: dict[str, Any]) -> bool:
    return identity.get("schema") == "pattern-scan-source.git.v2"


class _MemoryBoundJob(WindowsProcessJob):
    """Owned job commit limit; native working-set observations are separate.

    See the Win32 JobMemoryLimit contract in Microsoft's documentation:
    https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information
    """

    def __init__(self, limit_bytes: int) -> None:
        super().__init__()
        try:
            info = self._api.QueryInformationJobObject(self._handle, self._api.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= self._api.JOB_OBJECT_LIMIT_JOB_MEMORY
            info["JobMemoryLimit"] = limit_bytes
            self._api.SetInformationJobObject(self._handle, self._api.JobObjectExtendedLimitInformation, info)
            observed = self._api.QueryInformationJobObject(self._handle, self._api.JobObjectExtendedLimitInformation)
            if observed["JobMemoryLimit"] != limit_bytes or not observed["BasicLimitInformation"]["LimitFlags"] & self._api.JOB_OBJECT_LIMIT_JOB_MEMORY:
                raise ValueError("owned Windows job memory limit could not be established")
        except BaseException:
            self.close()
            raise

    def memory_receipt(self) -> dict[str, int | str]:
        info = self._api.QueryInformationJobObject(self._handle, self._api.JobObjectExtendedLimitInformation)
        return {
            "limit_bytes": int(info["JobMemoryLimit"]),
            "peak_committed_bytes": int(info["PeakJobMemoryUsed"]),
            "scope": "virtual memory committed across this owned Windows job",
        }


def source_identity(entry_points: tuple[str, ...]) -> dict[str, Any]:
    """Raw-byte closure of project imports, including lazy imports in functions."""
    pending = [relative_name(name) for name in entry_points]
    pending.append("research_core/pattern_scan_execution_v1.py")
    visited: set[str] = set()

    def module_files(module: str) -> list[str]:
        if module.split(".", 1)[0] not in {"research_core", "StockProject", "scripts"}:
            return []
        parts = module.split(".")
        candidates = ["/".join(parts) + ".py", "/".join(parts) + "/__init__.py"]
        candidates.extend("/".join(parts[:i]) + "/__init__.py" for i in range(1, len(parts)))
        return [name for name in candidates if (ROOT / name).is_file()]

    while pending:
        name = pending.pop()
        if name in visited:
            continue
        path = _checked_path(ROOT / name)
        if not path.is_file() or not path.is_relative_to(ROOT):
            raise ValueError("source entry must be an existing file in implementation checkout")
        visited.add(name)
        if path.suffix != ".py":
            continue
        package = list(path.relative_to(ROOT).parent.parts)
        for node in ast.walk(ast.parse(path.read_bytes())):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = ".".join(package[: len(package) - node.level + 1]) if node.level else ""
                module = ".".join(part for part in (base, node.module) if part)
                modules = [module, *(module + "." + alias.name for alias in node.names)]
            for module in modules:
                pending.extend(module_files(module))
    visited.update((
        "pyproject.toml",
        "uv.lock",
        "tasks/20261013-pattern-scan/mission.md",
        "tasks/20261013-pattern-scan/params/input-pins-v1.json.gz",
        "research_core/patterns/hhhl/sources.json",
        "research_core/patterns/hhhl/v4/sources.zip",
    ))
    body = {
        "schema": "pattern-scan-source.v1",
        "sources": {name: file_digest(_checked_path(ROOT / name)) for name in sorted(visited)},
        "runtime": runtime_identity(),
        "platform": sys.platform,
        "numerical_thread_limits": NUMERICAL_THREADS,
    }
    return {**body, "source_id": object_digest(body)}


def verify_source(identity: dict[str, Any]) -> None:
    if _git_source(identity):
        from research_core.pattern_scan_git_source_v2 import verify_git_source

        verify_git_source(identity)
        return
    body = {key: value for key, value in identity.items() if key != "source_id"}
    if identity.get("schema") != "pattern-scan-source.v1" or object_digest(body) != identity.get("source_id"):
        raise ValueError("invalid fixed source identity")
    if identity["runtime"] != runtime_identity() or identity["platform"] != sys.platform:
        raise ValueError("fixed source runtime differs")
    if identity.get("numerical_thread_limits") != NUMERICAL_THREADS:
        raise ValueError("fixed numerical thread limits differ")
    for name, digest in identity["sources"].items():
        if file_digest(_checked_path(ROOT / relative_name(name))) != digest:
            raise ValueError(f"fixed source changed: {name}")


def write_source_archive(path: Path, identity: dict[str, Any]) -> str:
    """Retain executed raw bytes, with deterministic ZIP transport metadata."""
    verify_source(identity)
    with _checked_path(path).open("xb") as stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(identity["sources"]):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / name).read_bytes())
    verify_source(identity)
    return file_digest(path)


def _request(request: dict[str, Any], *, source_verified: bool = False) -> tuple[DataRoots, Path, Path]:
    if request.get("calculation_authorized") is not True:
        raise PermissionError("explicit approved calculation authorization required")
    if not source_verified:
        verify_source(request["source"])
    roots = DataRoots(Path(request["primary"]), Path(request["data"]))
    run_root = _checked_path(Path(request["run_root"]))
    if run_root.parent != roots.primary / ".tmp" / "pattern-scan-execution" or not run_root.is_dir():
        raise ValueError("run root must be an existing primary task-owned scratch directory")
    prepared = _checked_path(Path(request["prepared_path"]))
    prepared_root = run_root / "prepared"
    if prepared.parent != prepared_root and prepared.parent.parent != prepared_root or prepared.suffix != ".parquet" or not prepared.is_file():
        raise ValueError("fixed prepared input outside run scratch")
    if file_digest(prepared) != request["prepared_sha256"]:
        raise ValueError("prepared input identity changed")
    if not isinstance(request["code"], str) or not request["code"].strip() or relative_name(request["code"]) != request["code"] or "/" in request["code"]:
        raise ValueError("one original string stock code required")
    output = _checked_path(run_root / "parts" / object_digest(request))
    return roots, prepared, output


def _verify_loaded(source: dict[str, Any]) -> None:
    if _git_source(source):
        verify_source(source)
        return
    from research_core.cache_execution import _LOADED_SOURCES, require_loaded

    for path in _LOADED_SOURCES:
        name = path.relative_to(ROOT).as_posix()
        if name not in source["sources"]:
            raise ValueError(f"unsealed imported project dependency: {name}")
    require_loaded({str(path): path for path in _LOADED_SOURCES})


def _execute_stock_in_process(request: dict[str, Any]) -> dict[str, Any]:
    """Process one sealed stock request; reused receipts must verify every file."""

    from research_core.pattern_scan_stock_v1 import StockPhase, stock_phase

    _, prepared, output = _request(request)
    if not _git_source(request["source"]):
        from research_core.cache_execution import require_loaded

        require_loaded({"execution": Path(__file__), "stock": ROOT / "research_core/pattern_scan_stock_v1.py"})
    if output.exists():
        receipt = read_json(output / "receipt.json")
        if receipt.get("request_id") != object_digest(request) or receipt.get("complete") is not True:
            raise ValueError("existing stock receipt differs or incomplete")
        verify_files(output, receipt["artifacts"])
        _request(request)
        return receipt
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = _checked_path(output.parent / f".staging-{output.name}-{uuid.uuid4().hex}")
    staging.mkdir()
    before = resource_sample()
    frame = read_frame(prepared)
    loaded = resource_sample()
    phase = stock_phase(
        frame,
        security_id=f"TW:{request['code']}",
        industry_ref=request["industry_ref"],
        ordinary_reference=True,
        definition_id=request["source"]["source_id"],
        input_id=request["input_id"],
    )
    computed = resource_sample()
    artifacts = []
    rows: dict[str, int] = {}
    for field in fields(StockPhase):
        table = getattr(phase, field.name)
        path = staging / f"{field.name}.parquet"
        with path.open("xb") as stream:
            write_frame(table, stream, index=True)
        artifacts.append(describe_file(staging, path))
        rows[field.name] = len(table)
    serialized = resource_sample()
    _request(request)
    _verify_loaded(request["source"])
    receipt = {
        "schema": "pattern-scan-stock-receipt.v1",
        "complete": True,
        "request_id": object_digest(request),
        "source_id": request["source"]["source_id"],
        "input_id": request["input_id"],
        "code": request["code"],
        "artifacts": artifacts,
        "rows": rows,
        "measurements": [
            phase_receipt("load_prepared", before, loaded),
            phase_receipt("stock_calculation", loaded, computed),
            phase_receipt("serialize", computed, serialized),
        ],
        "output_path": str(output),
    }
    write_json(staging / "receipt.json", receipt)
    verify_files(staging, artifacts)
    publish_noreplace(staging, output)
    LOGGER.info("Completed scan stock=%s rows=%s", request["code"], rows)
    return receipt


def worker_main(request_path: Path) -> None:
    """Protocol entry for sealed v1 or normally imported Git v2 execution."""
    request = read_json(_checked_path(request_path))
    if request.get("schema") == "pattern-scan-coordinator-request.v2":
        from research_core.pattern_scan_run_v2 import coordinator_main

        coordinator_main(request_path)
        return
    if request.get("schema") == "pattern-scan-coordinator-request.v1":
        from research_core.pattern_scan_run_v1 import coordinator_main

        coordinator_main(request_path)
        return
    output = _checked_path(Path(request["response_path"]))
    if output.parent != request_path.parent or output.exists():
        raise ValueError("exclusive worker response beside owned request required")
    source = request["source"]
    verify_source(source)
    if _git_source(source):
        from research_core.pattern_scan_git_source_v2 import assert_current_code

        assert_current_code(source, ROOT)
    if any(os.environ.get(name) != value for name, value in NUMERICAL_THREADS.items()):
        raise ValueError("worker numerical thread environment differs from fixed identity")
    if not request["stocks"] or any(packet["source"] != source for packet in request["stocks"]):
        raise ValueError("one nonempty sealed worker source required")
    run_root = _checked_path(Path(request["stocks"][0]["run_root"]))
    if not _checked_path(request_path).is_relative_to(run_root / "workers"):
        raise ValueError("worker request outside owned run scratch")
    started = resource_sample()
    results = [_execute_stock_in_process(packet) for packet in request["stocks"]]
    verify_source(source)
    _verify_loaded(source)
    if _git_source(source):
        loaded_sources: dict[str, str] = {}
        source_policy = {"source_verification_policy": "git-commit-and-dirty; normal-import; no-loaded-module-hashes"}
    else:
        from research_core.cache_execution import _LOADED_SOURCES

        loaded_sources = {path.relative_to(ROOT).as_posix(): digest for path, digest in _LOADED_SOURCES.items()}
        source_policy = {}
    write_json(
        output,
        {
            "schema": "pattern-scan-worker.v1",
            "complete": True,
            "results": results,
            "measurement": phase_receipt("worker_total", started, resource_sample()),
            "loaded_project_sources": loaded_sources,
            **source_policy,
        },
    )


def run_requests(
    requests: list[dict[str, Any]], *, workers: int, memory_bytes: int, estimated_worker_bytes: int, timeout_seconds: float = 600.0, stocks_per_process: int = 1
) -> dict[str, Any]:
    """At most four owned workers and at most workers requests in flight."""
    if not requests or len({request["code"] for request in requests}) != len(requests):
        raise ValueError("nonempty unique stock requests required")
    if type(stocks_per_process) is not int or not 1 <= stocks_per_process <= 8:
        raise ValueError("finite stock batch size from one through eight required")
    if (
        type(workers) is not int
        or not 1 <= workers <= 4
        or type(memory_bytes) is not int
        or type(estimated_worker_bytes) is not int
        or estimated_worker_bytes < 1
        or memory_bytes > 8 * 1024**3
        or memory_bytes < workers * estimated_worker_bytes
    ):
        raise ValueError("finite approved worker/memory limits required")
    host = host_resources()
    available = host["physical_available_bytes"]
    if available is None or available - memory_bytes < 4 * 1024**3:
        raise ValueError("cannot establish memory cap and four GiB host reserve")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds < 86400:
        raise ValueError("bounded worker timeout required")
    source = requests[0]["source"]
    verify_source(source)
    for request in requests:
        if request["source"] != source or request["run_root"] != requests[0]["run_root"]:
            raise ValueError("one source and run identity required at stock barrier")
        _request(request, source_verified=True)
    scratch = _checked_path(Path(requests[0]["run_root"]) / "workers" / uuid.uuid4().hex)
    scratch.mkdir(parents=True)
    packets = []
    ordered = sorted(requests, key=lambda value: value["code"])
    for index in range(0, len(ordered), stocks_per_process):
        directory = scratch / f"{index:06}"
        directory.mkdir()
        path = directory / "request.json"
        response = directory / "response.json"
        write_json(path, {"source": source, "stocks": ordered[index : index + stocks_per_process], "response_path": str(response)})
        packets.append((path, response))
    active: list[tuple[_MemoryBoundJob, subprocess.Popen[Any], Path, float]] = []
    completed = []
    next_index = 0
    peak_inflight = 0
    before = resource_sample()
    try:
        while next_index < len(packets) or active:
            while next_index < len(packets) and len(active) < workers:
                path, response = packets[next_index]
                job = _MemoryBoundJob(memory_bytes // workers)
                try:
                    bootstrap = GIT_BOOTSTRAP if _git_source(source) else BOOTSTRAP
                    process = job.start([sys.executable, "-c", bootstrap, str(ROOT), str(path)], ROOT)
                except BaseException:
                    job.close()
                    raise
                active.append((job, process, response, time.monotonic()))
                next_index += 1
                peak_inflight = max(peak_inflight, len(active))
            for item in list(active):
                job, process, response, started = item
                code = process.poll()
                if code is None:
                    if time.monotonic() - started > timeout_seconds:
                        raise TimeoutError("owned stock worker exceeded fixed timeout")
                    continue
                if code != 0:
                    raise ValueError(f"owned stock worker failed exit={code} response={response}")
                result = read_json(response)
                if result.get("complete") is not True:
                    raise ValueError("incomplete worker receipt")
                result["job_memory"] = job.memory_receipt()
                result["process_wall_seconds"] = time.monotonic() - started
                completed.append(result)
                job.close()
                active.remove(item)
            if active:
                time.sleep(0.05)
        verify_source(source)
    finally:
        for job, process, _, _ in active:
            try:
                job.terminate_and_confirm()
                process.wait(timeout=5)
            finally:
                job.close()
    results = sorted((row for receipt in completed for row in receipt["results"]), key=lambda value: value["code"])
    if [row["code"] for row in results] != sorted(request["code"] for request in requests):
        raise ValueError("incomplete stock barrier")
    return {
        "schema": "pattern-scan-pool.v1",
        "complete": True,
        "workers": workers,
        "stocks_per_process": stocks_per_process,
        "peak_inflight": peak_inflight,
        "memory_cap_bytes": memory_bytes,
        "estimated_worker_bytes": estimated_worker_bytes,
        "host_before": host,
        "coordinator_measurement": phase_receipt("pool", before, resource_sample()),
        "workers_receipts": completed,
        "results": results,
    }
