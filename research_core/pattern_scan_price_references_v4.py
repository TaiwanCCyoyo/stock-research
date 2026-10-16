"""Explicit price-reference handoff for an already completed stock phase.

Original stock receipts remain byte-identical. Missing price files are accepted
only through the exact retained equivalence certificate, never by generic hash
verification or a fallback to current data. Other stock artifacts stay required.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, publish_generated_bytes, verify_files
from research_core.pattern_scan_receipt_io_v2 import read_scan_receipt
from research_core.pattern_scan_result_lifecycle_v3 import ACTIVE, _run, _scratch_inventory
from research_core.pattern_scan_shared_prices_v4 import as_stock_prices, make_price_reference, read_reference_frame
from research_core.research_data_paths import _check_tree, _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)
HANDOFF = "shared-price-handoff.json"
EQUALITY = "shared-price-equivalence.json"
TRANSFER_PLAN = "shared-price-transfer-plan.json"
PLAN = "own-price-retirement-plan.json"
RETIRED = "own-price-retirement-receipt.json"
EXPECTED_STOCKS = 1942
EXPECTED_SESSIONS = 4110
_CACHE: dict[Path, tuple[dict[str, Any], dict[Path, tuple[int, int, int, int]]]] = {}


def _stamp(path: Path) -> tuple[int, int, int, int]:
    info = _checked_path(path).stat()
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


def _publish(run: Path, name: str, body: dict[str, Any]) -> None:
    path = run / name
    if path.exists():
        if read_scan_receipt(path) != body:
            raise ValueError("existing price handoff identity differs")
        return
    scratch = run.parent / f".price-reference-metadata-{uuid.uuid4().hex}"
    try:
        publish_generated_bytes(path, canonical(body), scratch=scratch)
    finally:
        if scratch.is_dir() and not any(scratch.iterdir()):
            scratch.rmdir()


def _pin(path: Path) -> dict[str, Any]:
    return {**describe_file(path.parent, path), "path": str(path)}


def _check_pin(pin: dict[str, Any], *, within: Path) -> Path:
    path = _checked_path(Path(pin["path"]))
    if not path.is_relative_to(within) or path.stat().st_size != pin["bytes"] or file_digest(path) != pin["sha256"]:
        raise ValueError("price handoff ancestor identity changed")
    return path


def _inactive(run: Path, active_owner: str | None = None) -> None:
    if (run / ACTIVE).exists():
        token = read_scan_receipt(run / ACTIVE)
        if active_owner is None or token.get("owner") != active_owner:
            raise ValueError("cannot change price references during actively executing scan")
    _check_tree(run)


def _ancestors(run: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    prepared = read_scan_receipt(run / "derived-preparation.json")
    phase = read_scan_receipt(run / "phase-stock-result.json")
    response = read_scan_receipt(run / "response-stock.json")
    request = read_scan_receipt(run / "request-stock.json")
    receipt = read_scan_receipt(run / "run-stock-receipt.json")
    memory = read_scan_receipt(run / "response-stock.job-memory.json")
    if (
        prepared.get("schema") != "pattern-scan-derived-preparation.v2"
        or prepared.get("scope") != "full_ordinary_reference"
        or prepared.get("calendar_n") != EXPECTED_SESSIONS
        or prepared.get("ordinary_reference_n") != EXPECTED_STOCKS
        or phase.get("phase") != "full_stock_checkpoints"
        or phase.get("global_analysis_admitted") is not False
        or response.get("complete") is not True
        or response.get("result") != phase
        or response.get("request_id") != object_digest(request)
        or request.get("source") != prepared["source"]
        or response.get("source_id") != prepared["source"]["source_id"]
        or response.get("input_id") != prepared["input_id"]
        or response.get("run_receipt_path") != str(run / "run-stock-receipt.json")
        or response.get("run_receipt_sha256") != file_digest(run / "run-stock-receipt.json")
        or receipt.get("code") != prepared["source"]["code"]
        or receipt.get("parameters", {}).get("source_id") != prepared["source"]["source_id"]
        or receipt.get("parameters", {}).get("input_id") != prepared["input_id"]
        or memory.get("complete") is not True
        or memory.get("request_id") != response["request_id"]
        or memory.get("response_sha256") != file_digest(run / "response-stock.json")
    ):
        raise ValueError("completed full stock ancestry required before price handoff")
    for role, name in (("derived_preparation", "derived-preparation.json"), ("phase_result", "phase-stock-result.json")):
        descriptor = receipt["results"][role]
        if Path(descriptor["path"]) != run / name:
            raise ValueError("stock result reference outside this run")
        _check_pin(descriptor, within=run)
    results = phase["pool"]["results"]
    parts = {item["code"]: item for item in results}
    if len(results) != EXPECTED_STOCKS or len(parts) != len(results) or set(parts) != {item["code"] for item in prepared["requests"]}:
        raise ValueError("complete unique original stock universe required")
    names = (
        "derived-preparation.json",
        "producer-read-receipt.json",
        "phase-stock-result.json",
        "response-stock.json",
        "request-stock.json",
        "run-stock-receipt.json",
        "response-stock.job-memory.json",
    )
    return prepared, parts, {name: _pin(run / name) for name in names}


def _owned(run: Path, path: Path, expected_sha: str) -> dict[str, Any]:
    name = path.relative_to(run).as_posix()
    return {**_scratch_inventory(run, [path])[name], "sha256": expected_sha}


def _worker_metadata(run: Path, prepared: dict[str, Any], parts: dict[str, Any]) -> dict[str, Any]:
    """Recognize only worker envelopes proven by the completed pool and requests."""
    workers = run / "workers"
    if not workers.exists():
        return {}
    phase = read_scan_receipt(run / "phase-stock-result.json")
    completed = {
        object_digest({key: value for key, value in packet.items() if key not in {"job_memory", "process_wall_seconds"}})
        for packet in phase["pool"]["workers_receipts"]
    }
    requests = {packet["code"]: packet for packet in prepared["requests"]}
    owned = {}
    observed = set()
    for batch in workers.iterdir():
        if not batch.is_dir() or re.fullmatch(r"[0-9a-f]{32}", batch.name) is None:
            raise ValueError("unknown worker batch ownership")
        for directory in batch.iterdir():
            if not directory.is_dir() or re.fullmatch(r"[0-9]{6}", directory.name) is None:
                raise ValueError("unknown worker packet ownership")
            if {path.name for path in directory.iterdir()} != {"request.json", "response.json"}:
                raise ValueError("unknown file ownership in original worker packet")
            request, response = (read_scan_receipt(directory / name) for name in ("request.json", "response.json"))
            response_id = object_digest(response)
            if (
                response_id not in completed
                or response_id in observed
                or request.get("source") != prepared["source"]
                or request.get("response_path") != str(directory / "response.json")
                or not request.get("stocks")
                or [row["code"] for row in request["stocks"]] != [row["code"] for row in response["results"]]
                or any(packet != requests.get(packet["code"]) for packet in request["stocks"])
                or any(packet != parts.get(packet["code"]) for packet in response["results"])
            ):
                raise ValueError("worker envelopes differ from completed original stock work")
            observed.add(response_id)
            if len(observed) % 100 == 0:
                LOGGER.info("Verified original worker envelopes packets=%d/%d", len(observed), len(completed))
            for name in ("request.json", "response.json"):
                path = directory / name
                owned[path.relative_to(run).as_posix()] = _owned(run, path, file_digest(path))
    if observed != completed:
        raise ValueError("original completed worker envelope set differs")
    return owned


def _finish_handoff(run: Path, plan: dict[str, Any]) -> dict[str, Any]:
    _publish(run, EQUALITY, plan["audit_packet"])
    body = {key: value for key, value in plan.items() if key not in {"schema", "audit_packet"}}
    body.update(schema="pattern-scan-shared-price-handoff.v4", audit=_pin(run / EQUALITY), transfer_plan=_pin(run / TRANSFER_PLAN))
    _publish(run, HANDOFF, body)
    _load(run)
    return {"path": str(run / HANDOFF), "sha256": file_digest(run / HANDOFF)}


def _reuse_completed_transfer(run: Path, reference: dict[str, Any], executor: dict[str, Any]) -> dict[str, Any] | None:
    if not (run / TRANSFER_PLAN).exists():
        return None
    plan = read_scan_receipt(run / TRANSFER_PLAN)
    if (
        plan.get("schema") != "pattern-scan-shared-price-transfer-plan.v4"
        or plan.get("complete") is not True
        or plan.get("run_root") != str(run)
        or plan.get("reference") != reference
        or plan.get("executor") != executor
        or plan.get("reference_sha256") != object_digest(reference)
    ):
        raise ValueError("completed price transfer retry identity differs")
    audit = plan["audit_packet"]
    expected_audit = {
        "complete": True,
        "mismatch_n": 0,
        "all_columns_equal": True,
        "calendar_equal": True,
        "quality_equal": True,
        "reference": reference,
        "executor": executor,
        "reference_source_id": plan["source"]["source_id"],
        "reference_input_id": plan["input_id"],
        "price_files_sha256": object_digest(plan["price_files"]),
        "stock_parts_sha256": object_digest(plan["stock_parts"]),
        "owned_nonprice_sha256": object_digest(plan["owned_nonprice"]),
        "ancestors_sha256": object_digest(plan["ancestors"]),
    }
    if canonical({key: audit.get(key) for key in expected_audit}) != canonical(expected_audit):
        raise ValueError("completed equality certificate differs from transfer inventory")
    for pin in plan["ancestors"].values():
        _check_pin(pin, within=run)
    for name, expected in {**plan["price_files"], **plan["owned_nonprice"]}.items():
        path = _checked_path(run / name)
        if not path.is_relative_to(run) or not path.is_file() or _owned(run, path, expected["sha256"]) != expected:
            raise ValueError("completed transfer owned files changed")
        if name in plan["price_files"] and file_digest(path) != expected["sha256"]:
            raise ValueError("completed equality price bytes changed")
    return _finish_handoff(run, plan)


def create_price_handoff(
    run: Path, reference: dict[str, Any], *, executor: dict[str, Any], calculation_authorized: bool = False, active_owner: str | None = None
) -> dict[str, Any]:
    """Compare actual original prices and transfer references, without deletion."""
    if calculation_authorized is not True:
        raise PermissionError("explicit approved shared-price equivalence required")
    before = resource_sample()
    run = _run(run)
    _inactive(run, active_owner)
    if (run / HANDOFF).exists():
        body = _load(run)
        if body["reference"] != reference:
            raise ValueError("shared price handoff retry generation differs")
        return {"path": str(run / HANDOFF), "sha256": file_digest(run / HANDOFF)}
    reused = _reuse_completed_transfer(run, reference, executor)
    if reused is not None:
        return reused
    prepared, parts, ancestors = _ancestors(run)
    calendar = pd.DatetimeIndex(pd.to_datetime(reference["calendar"]["dates"]), name=reference["calendar"].get("name"))
    if len(calendar) != EXPECTED_SESSIONS or calendar[0] != pd.Timestamp("2010-01-04") or calendar[-1] != pd.Timestamp("2026-10-12"):
        raise ValueError("approved PR17 full calendar required")
    checked_reference = make_price_reference(Path(reference["root"]), reference["generation"], calendar, expected_fingerprint=prepared["producer_fingerprint"])
    if checked_reference != reference:
        raise ValueError("shared reference differs from actual original producer inputs")
    preparation = {item["code"]: item for item in prepared["requests"]}
    codes = [*sorted(preparation), "0050"]
    artifacts = {item["path"]: item for item in prepared["artifacts"]}
    price_files: dict[str, Any] = {}
    other_files: dict[str, Any] = {}
    replacements: dict[str, Any] = {}
    checks: dict[str, Any] = {}
    from research_core.pattern_scan_parquet_v1 import read_frame

    for code in codes:
        path = _checked_path(Path(prepared["benchmark_path"] if code == "0050" else preparation[code]["prepared_path"]))
        if not path.is_relative_to(run / "prepared"):
            raise ValueError("original preparation outside owned run")
        name = path.relative_to(run).as_posix()
        descriptor = artifacts.get(name)
        if descriptor is None:
            raise ValueError("prepared price lacks original descriptor")
        verify_files(run, [descriptor])
        prior = _stamp(path)
        original = read_frame(path)
        replacement = read_reference_frame(reference, code)
        pd.testing.assert_frame_equal(original, replacement, check_exact=True, check_dtype=True, check_freq=True)
        if _stamp(path) != prior:
            raise ValueError("original prepared prices changed during comparison")
        price_files[name] = _owned(run, path, descriptor["sha256"])
        if code != "0050":
            own_receipt = path.with_suffix(".json")
            packet = read_scan_receipt(own_receipt)
            if packet.get("sha256") != descriptor["sha256"] or packet.get("identity", {}).get("input_id") != prepared["input_id"]:
                raise ValueError("original preparation receipt differs")
            price_files[own_receipt.relative_to(run).as_posix()] = _owned(run, own_receipt, file_digest(own_receipt))
            result = parts[code]
            directory = _checked_path(Path(result["output_path"]))
            if directory.parent != run / "parts" or read_scan_receipt(directory / "receipt.json") != result:
                raise ValueError("stock result outside original owned parts")
            if (
                result.get("complete") is not True
                or result.get("source_id") != prepared["source"]["source_id"]
                or result.get("input_id") != prepared["input_id"]
            ):
                raise ValueError("stock part source/input differs")
            verify_files(directory, result["artifacts"])
            stock_path = directory / "prices.parquet"
            part_before = _stamp(stock_path)
            pd.testing.assert_frame_equal(read_frame(stock_path), as_stock_prices(replacement, code), check_exact=True, check_dtype=True, check_freq=True)
            if _stamp(stock_path) != part_before:
                raise ValueError("stock price changed during comparison")
            item = next(item for item in result["artifacts"] if item["path"] == "prices.parquet")
            price_files[stock_path.relative_to(run).as_posix()] = _owned(run, stock_path, item["sha256"])
            receipt_pin = _pin(directory / "receipt.json")
            replacements[code] = {"directory": str(directory), "receipt": receipt_pin, "price": item}
            for item in result["artifacts"]:
                if item["path"] != "prices.parquet":
                    nonprice = directory / item["path"]
                    other_files[nonprice.relative_to(run).as_posix()] = _owned(run, nonprice, item["sha256"])
            other_files[(directory / "receipt.json").relative_to(run).as_posix()] = _owned(run, directory / "receipt.json", receipt_pin["sha256"])
        checks[code] = {
            "columns": list(original.columns),
            "dtypes": {key: str(value) for key, value in original.dtypes.items()},
            "rows": len(original),
            "equal": True,
        }
        if len(checks) % 100 == 0:
            LOGGER.info("Exact shared-price comparison complete securities=%d/%d", len(checks), len(codes))
    for name, pin in ancestors.items():
        _check_pin(pin, within=run)
        other_files[name] = _owned(run, run / name, pin["sha256"])
    for name in (
        "request-prepare.json",
        "response-prepare.json",
        "response-prepare.job-memory.json",
        "phase-prepare-result.json",
        "run-prepare-receipt.json",
        "stock-driver.log",
    ):
        path = run / name
        if path.is_file():
            other_files[name] = _owned(run, path, file_digest(path))
    other_files.update(_worker_metadata(run, prepared, parts))
    equality = {
        "schema": "pattern-scan-price-reader-equivalence.v3",
        "complete": True,
        "reference_source_id": prepared["source"]["source_id"],
        "reference_input_id": prepared["input_id"],
        "generation": reference["generation"],
        "calendar_n": EXPECTED_SESSIONS,
        "security_n": len(codes),
        "cutoff": "2026-10-12",
        "all_columns_equal": True,
        "calendar_equal": True,
        "quality_equal": True,
        "mismatch_n": 0,
        "reference": reference,
        "executor": executor,
        "securities": checks,
        "price_files_sha256": object_digest(price_files),
        "stock_parts_sha256": object_digest(replacements),
        "owned_nonprice_sha256": object_digest(other_files),
        "ancestors_sha256": object_digest(ancestors),
        "measurement": phase_receipt("actual_prepared_and_stock_price_equivalence", before, resource_sample()),
    }
    plan = {
        "schema": "pattern-scan-shared-price-transfer-plan.v4",
        "complete": True,
        "run_root": str(run),
        "source": prepared["source"],
        "input_id": prepared["input_id"],
        "executor": executor,
        "reference": reference,
        "reference_sha256": object_digest(reference),
        "audit_packet": equality,
        "ancestors": ancestors,
        "stock_parts": replacements,
        "price_files": price_files,
        "owned_nonprice": other_files,
        "retirement_authority": (
            "owner 2026-10-16: shared as_of merged, exact equivalence and reference transfer before retiring own prices; retain other checkpoints"
        ),
    }
    _publish(run, TRANSFER_PLAN, plan)
    LOGGER.info("Transferred price references securities=%d stock_parts=%d; original stock/source receipts unchanged", len(codes), len(parts))
    return _finish_handoff(run, plan)


def _load(run: Path) -> dict[str, Any]:
    path = _checked_path(run / HANDOFF)
    cached = _CACHE.get(path)
    if cached is not None and all(_stamp(name) == identity for name, identity in cached[1].items()):
        return cached[0]
    body = read_scan_receipt(path)
    if body.get("schema") != "pattern-scan-shared-price-handoff.v4" or body.get("complete") is not True or body.get("run_root") != str(run):
        raise ValueError("invalid explicit shared-price handoff")
    reference = body["reference"]
    if body.get("reference_sha256") != object_digest(reference):
        raise ValueError("shared price reference identity changed")
    audit_path = _check_pin(body["audit"], within=run)
    if audit_path != run / EQUALITY:
        raise ValueError("shared equivalence evidence outside named handoff")
    audit = read_scan_receipt(audit_path)
    expected = {
        "schema": "pattern-scan-price-reader-equivalence.v3",
        "complete": True,
        "reference_source_id": body["source"]["source_id"],
        "reference_input_id": body["input_id"],
        "generation": reference["generation"],
        "calendar_n": EXPECTED_SESSIONS,
        "security_n": EXPECTED_STOCKS + 1,
        "cutoff": "2026-10-12",
        "all_columns_equal": True,
        "calendar_equal": True,
        "quality_equal": True,
        "mismatch_n": 0,
        "reference": reference,
        "executor": body["executor"],
        "price_files_sha256": object_digest(body["price_files"]),
        "stock_parts_sha256": object_digest(body["stock_parts"]),
        "owned_nonprice_sha256": object_digest(body["owned_nonprice"]),
        "ancestors_sha256": object_digest(body["ancestors"]),
    }
    if canonical({key: audit.get(key) for key in expected}) != canonical(expected) or len(body["stock_parts"]) != EXPECTED_STOCKS:
        raise ValueError("shared equivalence does not authorize this price handoff")
    identities = {path: _stamp(path), audit_path: _stamp(audit_path)}
    transfer = _check_pin(body["transfer_plan"], within=run)
    if transfer != run / TRANSFER_PLAN:
        raise ValueError("price transfer plan reference outside named run")
    plan = read_scan_receipt(transfer)
    expected_plan = {key: value for key, value in body.items() if key not in {"schema", "audit", "transfer_plan"}}
    expected_plan.update(schema="pattern-scan-shared-price-transfer-plan.v4", audit_packet=audit)
    if plan != expected_plan:
        raise ValueError("immutable transfer plan differs from handoff/audit")
    identities[transfer] = _stamp(transfer)
    calendar = pd.DatetimeIndex(pd.to_datetime(reference["calendar"]["dates"]), name=reference["calendar"].get("name"))
    checked = make_price_reference(Path(reference["root"]), reference["generation"], calendar, expected_fingerprint={"inputs": reference["input_fingerprint"]})
    if checked != reference:
        raise ValueError("shared generation no longer matches the transferred reference")
    status_path = Path(reference["root"]) / "derived/adjusted-daily-v1/generations" / reference["generation"] / "status.json"
    identities[status_path] = _stamp(status_path)
    for descriptor in reference["inputs"].values():
        dependency = Path(descriptor["path"])
        identities[dependency] = _stamp(dependency)
    for pin in body["ancestors"].values():
        ancestor = _check_pin(pin, within=run)
        identities[ancestor] = _stamp(ancestor)
    _CACHE[path] = body, identities
    return body


def _replacement(directory: Path) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    directory = _checked_path(directory)
    run = directory.parent.parent
    if directory.parent.name != "parts" or not (run / HANDOFF).exists():
        return None
    body = _load(_run(run))
    matches = [(code, item) for code, item in body["stock_parts"].items() if item["directory"] == str(directory)]
    if len(matches) != 1:
        raise ValueError("stock outside explicit shared price handoff")
    code, item = matches[0]
    if _check_pin(item["receipt"], within=run) != directory / "receipt.json":
        raise ValueError("stock receipt reference changed")
    return body, code, item


def verify_stock_artifacts(directory: Path, receipt: dict[str, Any]) -> None:
    replacement = _replacement(directory)
    if replacement is None:
        verify_files(directory, receipt["artifacts"])
        return
    body, code, item = replacement
    if receipt.get("code") != code or receipt.get("source_id") != body["source"]["source_id"] or receipt.get("input_id") != body["input_id"]:
        raise ValueError("stock receipt source/input differs from shared reference")
    prices = [row for row in receipt["artifacts"] if row["path"] == "prices.parquet"]
    if prices != [item["price"]] or read_scan_receipt(directory / "receipt.json") != receipt:
        raise ValueError("original price descriptor or stock receipt changed")
    verify_files(directory, [row for row in receipt["artifacts"] if row["path"] != "prices.parquet" or (directory / "prices.parquet").exists()])


def read_stock_prices(directory: Path, *, columns: list[str] | None = None) -> pd.DataFrame:
    replacement = _replacement(directory)
    if replacement is None:
        from research_core.pattern_scan_parquet_v1 import read_frame

        return read_frame(directory / "prices.parquet", **({} if columns is None else {"columns": columns}))
    body, code, _ = replacement
    return read_reference_frame(body["reference"], code, stock_part=True, columns=columns)


def read_benchmark(run: Path) -> pd.DataFrame:
    body = _load(_run(run))
    return read_reference_frame(body["reference"], "0050")


def retired_preparation_reference(run: Path) -> dict[str, Any]:
    """Return original numerical lineage and the new explicitly pinned reader."""
    body = _load(_run(run))
    return {key: body[key] for key in ("source", "input_id", "reference", "executor", "ancestors", "audit")}


def retire_own_prices(run: Path, handoff: dict[str, Any], *, retirement_authorized: bool = False, active_owner: str | None = None) -> dict[str, Any]:
    """Retire only explicitly transferred own prices, keeping completed stock work."""
    if retirement_authorized is not True:
        raise PermissionError("explicit owner authorization for own-price retirement required")
    run = _run(run)
    _inactive(run, active_owner)
    if handoff != {"path": str(run / HANDOFF), "sha256": file_digest(run / HANDOFF)}:
        raise ValueError("explicit price handoff pin differs")
    body = _load(run)
    # Prove this exact generation remains readable; never select current/latest.
    read_reference_frame(body["reference"], "0050")
    plan = {"schema": "pattern-scan-own-price-retirement-plan.v4", "run_root": str(run), "handoff": handoff, "price_files": body["price_files"]}
    plan_path = run / PLAN
    resuming = plan_path.exists()
    if resuming and read_scan_receipt(plan_path) != plan:
        raise ValueError("own-price retirement retry identity differs")
    completed_path = run / RETIRED
    completed = read_scan_receipt(completed_path) if completed_path.exists() else None
    allowed = {HANDOFF, EQUALITY, TRANSFER_PLAN, PLAN, RETIRED}
    if active_owner is not None:
        allowed.add(ACTIVE)
    files = []
    for path in run.rglob("*"):
        if not path.is_file():
            continue
        name = path.relative_to(run).as_posix()
        if name in allowed:
            continue
        expected = body["price_files"].get(name, body["owned_nonprice"].get(name))
        if expected is None:
            raise ValueError(f"unknown file ownership blocks own-price retirement: {path}")
        observed: dict[str, Any] = dict(_scratch_inventory(run, [path])[name])
        if {key: value for key, value in expected.items() if key != "sha256"} != observed:
            raise ValueError("owned run file changed before own-price retirement")
        if name in body["price_files"]:
            if file_digest(path) != expected["sha256"]:
                raise ValueError("own price changed after exact equivalence")
            files.append(path)
    missing = [name for name in body["price_files"] if not (run / name).is_file()]
    if missing and not resuming:
        raise ValueError("own prices missing before journaled retirement")
    if any(not (run / name).is_file() for name in body["owned_nonprice"]):
        raise ValueError("completed non-price checkpoint missing before own-price retirement")
    result = {
        "schema": "pattern-scan-own-price-retirement.v4",
        "complete": True,
        "run_root": str(run),
        "handoff": handoff,
        "original_source_id": body["source"]["source_id"],
        "original_input_id": body["input_id"],
        "generation": body["reference"]["generation"],
        "removed_files": len(body["price_files"]),
        "removed_bytes": sum(item["bytes"] for item in body["price_files"].values()),
        "other_stock_artifacts_retained": True,
    }
    if completed is not None:
        if completed != result or files:
            raise ValueError("completed own-price retirement differs")
        return completed
    _publish(run, PLAN, plan)
    for path in files:
        _checked_path(path).unlink()
    prepared = run / "prepared"
    if prepared.is_dir():
        for directory in sorted((path for path in prepared.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
        if not any(prepared.iterdir()):
            prepared.rmdir()
    _publish(run, RETIRED, result)
    LOGGER.info("Retired own price copies files=%d bytes=%d; completed non-price stock work retained", result["removed_files"], result["removed_bytes"])
    return result
