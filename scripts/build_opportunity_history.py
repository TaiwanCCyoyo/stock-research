"""Bounded native-method orchestration and deterministic compact catalog export."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.opportunity_history_catalog import RULE, SELECTOR, adapt_security
from scripts.opportunity_history_native_validation import validate_native_semantics
from scripts.query_opportunity_history import validate_calendar_identity, validate_series_identity

ROOT = Path(__file__).resolve().parents[1]
TASK = "20261004-sector-wave-full-history-preview"
NODE = Path(shutil.which("node") or "node")
PAIRS = {(method, scale) for method in ("segments", "filter") for scale in ("fine", "balanced", "coarse")}
PINNED = {
    "analysis": "550c277df28c7ac0b2d4deb69b67eb137b500c0f8b2c80c78880fda79aef1a25",
    "types": "9ee6c25365f2acbaf889151fa29727457e70319277aa60cca64bcadd38a675cb",
}
LOGGER = logging.getLogger(__name__)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return _read_json_identity(path)[0]


def _read_json_identity(path: Path, expected_sha256: str | None = None) -> tuple[Any, str]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(f"Input artifact hash mismatch: {path}")
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data), digest


def write_json(path: Path, value: Any) -> None:
    data = canonical(value)
    if path.suffix == ".gz":
        data = gzip.compress(data, mtime=0)
    with path.open("xb") as stream:
        stream.write(data)


def emit_progress(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def descriptor(path: Path, root: Path, count: int | None = None) -> dict[str, Any]:
    return _fixed_descriptor(path, root, sha(path), count)


def _fixed_descriptor(path: Path, root: Path, digest: str, count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": Path(os.path.relpath(path, root)).as_posix(), "sha256": digest}
    if count is not None:
        result["count"] = count
    return result


def checked_reference(root: Path, ref: dict[str, Any]) -> Path:
    path = root / ref["path"]
    if sha(path) != ref["sha256"]:
        raise ValueError(f"Input artifact hash mismatch: {path}")
    return path


def resolve_params_artifact(manifest_path: Path, manifest: dict[str, Any], params_path: Path | None = None) -> Path:
    """Resolve declared raw params, explicit legacy path, or the original sibling."""
    if "params_artifact" in manifest:
        reference = manifest["params_artifact"]
        if not isinstance(reference, dict):
            raise ValueError("Invalid params_artifact descriptor")
        relative = reference.get("path")
        expected = reference.get("sha256")
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError("params_artifact requires a nonempty path")
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None:
            raise ValueError("params_artifact requires a 64-hex sha256")
        resolved = (manifest_path.parent / relative).resolve()
        if params_path is not None and params_path.resolve() != resolved:
            raise ValueError("Explicit params path conflicts with declared params_artifact")
        if sha(resolved) != expected.lower():
            raise ValueError("params_artifact hash mismatch")
        return resolved
    return (params_path if params_path is not None else manifest_path.parent.parent / "params.json").resolve()


def code_identity() -> dict[str, Any]:
    snapshot = ROOT / "tasks" / TASK / "method-snapshot"
    source = {key: sha(snapshot / f"{key}.ts") for key in PINNED}
    if source != PINNED:
        raise ValueError("Pinned native source hash mismatch")
    return {"source": source, "method": RULE, "wrapper": {"sha256": sha(ROOT / "scripts/opportunity_history_methods.mjs")}}


def run_node(series_path: Path, calendar_path: Path, output_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node unavailable for native method runner: cannot locate node on PATH")
    try:
        subprocess.run(
            [
                node,
                "--experimental-strip-types",
                str(ROOT / "scripts/opportunity_history_methods.mjs"),
                "--series",
                str(series_path),
                "--calendar",
                str(calendar_path),
                "--output",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as error:
        raise RuntimeError(f"Node unavailable for native method runner ({node}): {error}") from error


def validate_native(native: dict[str, Any], series: dict[str, Any], expected_input: dict[str, str], identity: dict[str, Any]) -> None:
    if native.get("schema", native.get("schema_version")) != "opportunity-native-results.v1":
        raise ValueError("Native schema mismatch")
    for field in ("security_id", "series_id", "calendar_id"):
        if native.get(field) != series[field]:
            raise ValueError(f"Native identity mismatch: {field}")
    if native.get("input_identity") != expected_input or native.get("code_identity") != identity:
        raise ValueError("Native input/code identity mismatch")
    records = native.get("native", [])
    if (
        not isinstance(records, list)
        or len(records) != 6
        or any(not isinstance(record, dict) for record in records)
        or any(not isinstance(record.get("method"), str) or not isinstance(record.get("scale"), str) for record in records)
        or {(record["method"], record["scale"]) for record in records} != PAIRS
    ):
        raise ValueError("Native must contain exactly six method/scale records")
    for record in records:
        if record.get("status") != "ok" or not isinstance(record.get("result"), dict) or record.get("error") is not None:
            raise ValueError(f"Native publication requires all six successful scopes: {record['method']}/{record['scale']} is incomplete")
    canonical(native)  # Reject nonfinite JSON, including dense fit outputs.


def _process_stream(value: str | bytes | None) -> str | dict[str, str] | None:
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    return value


def build_catalog(
    series_manifest_path: Path,
    native_dir: Path,
    *,
    params_path: Path | None = None,
    workers: int = 2,
    chunk_rows: int = 2000,
    resume: bool = False,
    runner: Callable[[Path, Path, Path], None] | None = None,
    progress: Callable[[str], None] | None = None,
    extras: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Publish only complete successes; resume hash-verified successful native artifacts.

    Process failures write exclusive *.failure.json diagnostics and preserve any
    failed native bytes. Retry failures with a new native destination.
    Publication rechecks fixed input and output identities; changed artifacts
    retain publication.failure.json diagnostics and require a new catalog root.
    """
    if workers < 1 or chunk_rows < 1:
        raise ValueError("workers and chunk_rows must be positive")
    root = series_manifest_path.parent
    publication_failure_path = root / "publication.failure.json"
    if publication_failure_path.exists():
        raise FileExistsError(f"Publication failure evidence exists; retry with a new catalog root: {publication_failure_path}")
    fixed_extras = deepcopy(extras or {})
    try:
        os.path.relpath(native_dir, root)
    except ValueError as error:
        raise ValueError(f"Native directory cannot be referenced relative to catalog root: {native_dir} (root: {root})") from error
    if (root / "manifest.json").exists() or (root / "chunks").exists():
        raise FileExistsError("Completed or partial catalog output exists; use a new empty table destination")
    source, series_manifest_sha = _read_json_identity(series_manifest_path)
    if source["schema_version"] != "opportunity-series-manifest.v1" or type(source["count"]) is not int or source["count"] != len(source["rows"]):
        LOGGER.error("Publication rejected series manifest schema/count source=%s", series_manifest_path)
        raise ValueError("Invalid series manifest schema/count")
    codes = [row["code"] for row in source["rows"]]
    if len(set(codes)) != len(codes) or any(not code.isascii() or not code.isalnum() for code in codes):
        raise ValueError("Duplicate or unsafe security code")
    security_ids = [row.get("security_id") for row in source["rows"]]
    # JS trim also treats BOM as whitespace; blankness checks must not normalize stored IDs.
    if any(not isinstance(value, str) or not value.replace("\ufeff", "").strip() for value in security_ids) or len(set(security_ids)) != len(security_ids):
        LOGGER.error("Publication rejected invalid or duplicate security IDs source=%s", series_manifest_path)
        raise ValueError("Invalid or duplicate security_id in series manifest")
    calendar_path = root / source["calendar"]["path"]
    calendar, _ = _read_json_identity(calendar_path, source["calendar"]["sha256"])
    validate_calendar_identity(calendar)
    if not calendar["dates"]:
        LOGGER.error("Publication rejected empty calendar source=%s calendar=%s resume=%s", series_manifest_path, calendar_path, resume)
        raise ValueError("Empty history calendar")
    if (
        source["calendar_id"] != calendar["calendar_id"]
        or type(source["calendar"]["count"]) is not int
        or source["calendar"]["count"] != len(calendar["dates"])
    ):
        LOGGER.error("Publication rejected calendar identity/count source=%s calendar=%s", series_manifest_path, calendar_path)
        raise ValueError("Calendar identity/count mismatch")
    params_path = params_path or ROOT / "tasks" / TASK / "params.json"
    try:
        params_relative_path = Path(os.path.relpath(params_path.resolve(), root)).as_posix()
    except ValueError as error:
        raise ValueError(f"Params artifact requires a relative reference on the same Windows drive as catalog output: {error}") from error
    params, params_sha = _read_json_identity(params_path)
    params_artifact = {"path": params_relative_path, "sha256": params_sha}
    if params != read_json(ROOT / "tasks" / TASK / "params.json"):
        raise ValueError("Config differs from frozen native numerical settings")
    if set(params["methods"]) != {"segments", "filter"} or set(params["scales"]) != {"fine", "balanced", "coarse"}:
        raise ValueError("Config must preserve six native methods/scales")
    identity = code_identity()
    for row in source["rows"]:
        series, _ = _read_json_identity(root / row["path"], row["sha256"])
        validate_series_identity(series)
        if series["calendar_id"] != calendar["calendar_id"]:
            raise ValueError("Series calendar identity mismatch")
        for field in ("code", "series_id", "security_id", "cohort", "instrument_role"):
            if row[field] != series[field]:
                raise ValueError(f"Series manifest identity mismatch: {field}")
    for reference in fixed_extras.values():
        checked_reference(root, reference)
    context = {
        "series_manifest_sha256": series_manifest_sha,
        "input_receipt_sha256": hashlib.sha256(canonical(source["input_receipt"])).hexdigest(),
        "calendar_sha256": source["calendar"]["sha256"],
        "config_sha256": params_sha,
        "code_identity": identity,
        "producer_sha256": sha(Path(__file__)),
        "adapter_sha256": sha(ROOT / "research_core/opportunity_history_catalog.py"),
    }
    native_dir.mkdir(parents=True, exist_ok=True)
    run = runner or run_node
    emit = progress or emit_progress

    def process(row: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        path = root / row["path"]
        series, _ = _read_json_identity(path, row["sha256"])
        for field in ("code", "series_id", "security_id", "cohort", "instrument_role"):
            if row[field] != series[field]:
                raise ValueError(f"Series manifest identity mismatch: {field}")
        if series["calendar_id"] != source["calendar_id"]:
            raise ValueError("Series calendar identity mismatch")
        eligible = series["instrument_role"] == "stock" and series["cohort"] in ("metadata_stock", "innovation_board")
        expected_input = {"series_sha256": row["sha256"], "calendar_sha256": source["calendar"]["sha256"]}
        ref = None
        if eligible:
            output = native_dir / f"{row['code']}.json.gz"
            receipt_path = native_dir / f"{row['code']}.receipt.json"
            failure_path = native_dir / f"{row['code']}.failure.json"
            if failure_path.exists():
                raise FileExistsError(f"Native failure evidence exists; retry with a new native destination: {failure_path}")
            if output.exists() or receipt_path.exists():
                if not resume or not output.exists() or not receipt_path.exists():
                    raise FileExistsError(f"Native output exists without authorized verified resume: {output}")
                receipt, receipt_sha = _read_json_identity(receipt_path)
                native, native_sha = _read_json_identity(output, receipt["sha256"])
                if (
                    receipt.get("schema_version") != "opportunity-native-receipt.v1"
                    or receipt.get("security_id") != series["security_id"]
                    or receipt.get("series_id") != series["series_id"]
                    or receipt["context"] != context
                    or receipt["sha256"] != native_sha
                ):
                    raise ValueError(f"Native resume receipt/hash mismatch: {output}")
                try:
                    validate_native(native, series, expected_input, identity)
                    validate_native_semantics(native, series, calendar)
                except (ValueError, RuntimeError):
                    LOGGER.exception("Native resume rejected code=%s output=%s", row["code"], output)
                    raise
            else:
                try:
                    run(path, calendar_path, output)
                except subprocess.CalledProcessError as error:
                    failure = {
                        "schema_version": "opportunity-native-process-failure.v1",
                        "code": row["code"],
                        **{field: series[field] for field in ("security_id", "series_id", "calendar_id")},
                        "input_identity": expected_input,
                        "code_identity": identity,
                        "context": context,
                        "process": {
                            "command": [str(item) for item in error.cmd] if isinstance(error.cmd, (list, tuple)) else str(error.cmd),
                            "returncode": error.returncode,
                            "stdout": _process_stream(error.stdout),
                            "stderr": _process_stream(error.stderr),
                        },
                        "retained_output": ({"path": output.name, "sha256": sha(output), "size_bytes": output.stat().st_size} if output.exists() else None),
                    }
                    LOGGER.error("Native runner failed code=%s returncode=%s diagnostic=%s", row["code"], error.returncode, failure_path)
                    try:
                        write_json(failure_path, failure)
                    except FileExistsError:
                        LOGGER.warning("Existing native failure diagnostic retained: %s", failure_path)
                    raise
                native, native_sha = _read_json_identity(output)
                try:
                    validate_native(native, series, expected_input, identity)
                    validate_native_semantics(native, series, calendar)
                except (ValueError, RuntimeError):
                    LOGGER.exception("Native publication rejected code=%s output=%s", row["code"], output)
                    raise
                receipt = {
                    "schema_version": "opportunity-native-receipt.v1",
                    "context": context,
                    "sha256": native_sha,
                    "security_id": series["security_id"],
                    "series_id": series["series_id"],
                }
                receipt_sha = hashlib.sha256(canonical(receipt)).hexdigest()
                write_json(receipt_path, receipt)
            ref = _fixed_descriptor(output, root, native_sha, 6) | {"receipt": _fixed_descriptor(receipt_path, root, receipt_sha)}
        else:
            native = {
                **{field: series[field] for field in ("security_id", "series_id", "calendar_id")},
                "input_identity": expected_input,
                "native": [],
                "support_records": [],
            }
        tables = adapt_security(series, calendar, native)
        tables["securities"][0]["stock_opportunity_eligible"] = eligible
        tables["securities"][0]["method_eligibility_reason"] = "stock_cohort" if eligible else "excluded_role_or_identity"
        tables["securities"][0]["coverage"] = series.get("coverage", {})
        return row["code"], tables, ref

    results = {}
    ordered_rows = sorted(source["rows"], key=lambda row: row["code"])
    first = next((row for row in ordered_rows if row["instrument_role"] == "stock" and row["cohort"] in ("metadata_stock", "innovation_board")), None)
    preflight = None
    if first is not None:
        started = time.perf_counter()
        code, tables, ref = process(first)
        results[code] = (tables, ref)
        preflight = {
            "code": code,
            "selection": "lexicographically_first_eligible_code",
            "elapsed_seconds": time.perf_counter() - started,
            "reused_in_full_output": True,
        }
        emit(json.dumps({"completed": 1, "total": len(codes), "code": code, "preflight": preflight}, ensure_ascii=True))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, row): row["code"] for row in ordered_rows if row["code"] not in results}
        try:
            for future in as_completed(futures):
                code, tables, ref = future.result()
                results[code] = (tables, ref)
                emit(json.dumps({"completed": len(results), "total": len(codes), "code": code}, ensure_ascii=True))
        except BaseException:
            for future in futures:
                future.cancel()
            raise

    def postflight(stage: str) -> None:
        try:
            for path, expected in (
                (series_manifest_path, series_manifest_sha),
                (params_path, params_sha),
                (Path(__file__), context["producer_sha256"]),
                (ROOT / "research_core/opportunity_history_catalog.py", context["adapter_sha256"]),
            ):
                if sha(path) != expected:
                    raise ValueError(f"Publication artifact hash changed: {path}")
            for reference in (source["calendar"], *source["rows"], *fixed_extras.values()):
                checked_reference(root, reference)
            if code_identity() != identity:
                raise ValueError("Publication code identity changed")
            for code, (_, native_reference) in results.items():
                if native_reference is None:
                    continue
                checked_reference(root, native_reference)
                receipt_reference = native_reference["receipt"]
                receipt, _ = _read_json_identity(root / receipt_reference["path"], receipt_reference["sha256"])
                if receipt.get("sha256") != native_reference["sha256"] or receipt.get("context") != context:
                    raise ValueError(f"Publication native receipt identity changed: {code}")
            if stage == "before_manifest":
                for references in descriptors.values():
                    for reference in references:
                        checked_reference(root, reference)
        except (ValueError, OSError) as error:
            failure = error if isinstance(error, ValueError) else ValueError(f"Publication artifact unavailable: {error}")
            LOGGER.exception("Publication postflight failed stage=%s diagnostic=%s", stage, publication_failure_path)
            try:
                write_json(
                    publication_failure_path,
                    {
                        "schema_version": "opportunity-publication-failure.v1",
                        "stage": stage,
                        "context": context,
                        "error": {"name": type(failure).__name__, "message": str(failure)},
                    },
                )
            except FileExistsError:
                LOGGER.warning("Existing publication failure diagnostic retained: %s", publication_failure_path)
            if failure is error:
                raise
            raise failure from error

    postflight("after_native")
    table_dir = root / "chunks"
    table_dir.mkdir()
    descriptors: dict[str, list[dict[str, Any]]] = {}
    names = (
        next(iter(results.values()))[0].keys()
        if results
        else (
            "securities",
            "methods",
            "baseline_waves",
            "source_phases",
            "candidates",
            "support_records",
            "relations",
            "representative_intervals",
            "transitions",
        )
    )
    for name in names:
        rows = [row for code in sorted(results) for row in results[code][0][name]]
        rows.sort(key=canonical)
        descriptors[name] = []
        for offset in range(0, max(1, len(rows)), chunk_rows):
            part = rows[offset : offset + chunk_rows]
            path = table_dir / f"{name}-{offset // chunk_rows:05}.json.gz"
            write_json(path, {"rows": part})
            descriptors[name].append(descriptor(path, root, len(part)))
    manifest = {
        "schema_version": "opportunity-local-history-preview.v1",
        "task": TASK,
        "window": {
            "start": calendar.get("start", calendar["dates"][0] if calendar["dates"] else None),
            "end": calendar.get("end", calendar["dates"][-1] if calendar["dates"] else None),
        },
        "status": "初步辨識，規則未定",
        "rule": RULE,
        "selector": SELECTOR,
        "price_basis": source["price_basis"],
        "code_identity": identity,
        "producer_identity": context,
        "adapter_revision": context["adapter_sha256"],
        "gain_policy": "exact_pinned_js_run.preview.v2",
        "config": params,
        "params_artifact": params_artifact,
        "input_receipt": source["input_receipt"],
        "calendar_id": source["calendar_id"],
        "calendar": source["calendar"],
        "series_manifest": _fixed_descriptor(series_manifest_path, root, series_manifest_sha, len(codes)),
        "series": {r["code"]: {key: r[key] for key in ("path", "sha256", "series_id", "security_id")} for r in sorted(source["rows"], key=lambda r: r["code"])},
        "tables": descriptors,
        "native": {code: results[code][1] for code in sorted(results) if results[code][1] is not None},
        "security_count": len(codes),
        "analyzed_security_count": sum(ref is not None for _, ref in results.values()),
    }
    manifest["extras"] = fixed_extras
    manifest["chunk_rows"] = chunk_rows
    manifest["performance_preflight"] = preflight
    postflight("before_manifest")
    write_json(root / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series-manifest", type=Path, required=True)
    parser.add_argument("--native-dir", type=Path, required=True)
    parser.add_argument("--params", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--chunk-rows", type=int, default=2000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--extras-manifest", type=Path)
    args = parser.parse_args(argv)
    manifest = build_catalog(
        args.series_manifest,
        args.native_dir,
        params_path=args.params,
        workers=args.workers,
        chunk_rows=args.chunk_rows,
        resume=args.resume,
        extras=read_json(args.extras_manifest) if args.extras_manifest else None,
    )
    sys.stdout.write(
        json.dumps(
            {
                "manifest": str(args.series_manifest.parent / "manifest.json"),
                "security_count": manifest["security_count"],
                "analyzed_security_count": manifest["analyzed_security_count"],
            },
            ensure_ascii=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
