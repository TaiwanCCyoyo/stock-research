"""Re-export compact tables from verified frozen native evidence, without fitting."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.opportunity_history_catalog import adapt_security
from scripts.build_opportunity_history import (
    _fixed_descriptor,
    _read_json_identity,
    canonical,
    checked_reference,
    resolve_params_artifact,
    sha,
    validate_native,
    write_json,
)
from scripts.opportunity_artifact_publication import publish_json_manifest, require_publication_support
from scripts.query_opportunity_history import validate_calendar_identity, validate_series_identity

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "37cb418"
CHUNK_ROWS = 2000


def _eligible(series: dict[str, Any]) -> bool:
    return series["instrument_role"] == "stock" and series["cohort"] in ("metadata_stock", "innovation_board")


def _local_path(root: Path, reference: dict[str, Any]) -> Path:
    path = checked_reference(root, reference)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Copied metadata/series path escapes source catalog: {path}")
    return path


def _verify_source(
    source_path: Path, params_path: Path | None = None, *, expected_manifest_sha256: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source, _ = _read_json_identity(source_path, expected_manifest_sha256)
    root = source_path.parent
    if source.get("schema_version") != "opportunity-local-history-preview.v1":
        raise ValueError("Source catalog schema mismatch")
    context = source["producer_identity"]
    if context["code_identity"] != source["code_identity"]:
        raise ValueError("Frozen code identity mismatch")
    calendar_path = _local_path(root, source["calendar"])
    calendar, _ = _read_json_identity(calendar_path, source["calendar"]["sha256"])
    validate_calendar_identity(calendar)
    if calendar["calendar_id"] != source["calendar_id"] or len(calendar["dates"]) != source["calendar"]["count"]:
        raise ValueError("Source calendar identity/count mismatch")
    if context["calendar_sha256"] != source["calendar"]["sha256"]:
        raise ValueError("Frozen calendar context mismatch")
    series_manifest_path = _local_path(root, source["series_manifest"])
    series_manifest, _ = _read_json_identity(series_manifest_path, source["series_manifest"]["sha256"])
    rows = series_manifest["rows"]
    codes = [row["code"] for row in rows]
    if (
        len(set(codes)) != len(codes)
        or source["security_count"] != len(codes)
        or series_manifest["count"] != len(codes)
        or set(codes) != set(source["series"])
        or series_manifest["calendar_id"] != source["calendar_id"]
        or series_manifest["calendar"] != source["calendar"]
        or series_manifest["input_receipt"] != source["input_receipt"]
        or context["series_manifest_sha256"] != source["series_manifest"]["sha256"]
    ):
        raise ValueError("Frozen series manifest identity/count mismatch")
    receipt_hash = hashlib.sha256(canonical(source["input_receipt"])).hexdigest()
    if context["input_receipt_sha256"] != receipt_hash:
        raise ValueError("Frozen input receipt context mismatch")
    input_root = root.parent / "inputs"
    for item in source["input_receipt"]["files"]:
        name = item["name"]
        if Path(name).name != name or sha(input_root / name) != item["snapshot_sha256"]:
            raise ValueError(f"Frozen physical input hash mismatch: {name}")
    resolved_params = resolve_params_artifact(source_path, source, params_path)
    params, _ = _read_json_identity(resolved_params, context["config_sha256"])
    if params != source["config"]:
        raise ValueError("Frozen resolved config mismatch")
    for name, expected in source["code_identity"]["source"].items():
        if sha(root.parent / "method-snapshot" / f"{name}.ts") != expected:
            raise ValueError(f"Frozen method source hash mismatch: {name}")
    for ref in source["extras"].values():
        _local_path(root, ref)
    for refs in source["tables"].values():
        for ref in refs:
            chunk, _ = _read_json_identity(checked_reference(root, ref), ref["sha256"])
            if len(chunk["rows"]) != ref["count"]:
                raise ValueError("Source table count mismatch")
    if sum(ref["count"] for ref in source["tables"]["securities"]) != len(codes):
        raise ValueError("Source securities count mismatch")
    eligible_codes = set()
    for row in rows:
        ref = source["series"][row["code"]]
        if any(row[key] != ref[key] for key in ("path", "sha256", "security_id", "series_id")):
            raise ValueError("Source per-code descriptor mismatch")
        series, _ = _read_json_identity(_local_path(root, ref), ref["sha256"])
        validate_series_identity(series)
        if any(series[key] != row[key] for key in ("code", "security_id", "series_id", "cohort", "instrument_role")):
            raise ValueError("Source per-code series identity mismatch")
        if series["calendar_id"] != source["calendar_id"]:
            raise ValueError("Source series calendar mismatch")
        if not _eligible(series):
            continue
        eligible_codes.add(row["code"])
        native_ref = source["native"][row["code"]]
        native, _ = _read_json_identity(checked_reference(root, native_ref), native_ref["sha256"])
        receipt, _ = _read_json_identity(checked_reference(root, native_ref["receipt"]), native_ref["receipt"]["sha256"])
        if (
            native_ref["count"] != 6
            or receipt["schema_version"] != "opportunity-native-receipt.v1"
            or receipt["context"] != context
            or receipt["sha256"] != native_ref["sha256"]
            or receipt["security_id"] != series["security_id"]
            or receipt["series_id"] != series["series_id"]
        ):
            raise ValueError("Frozen native receipt identity/hash mismatch")
        expected_input = {"series_sha256": ref["sha256"], "calendar_sha256": source["calendar"]["sha256"]}
        validate_native(native, series, expected_input, source["code_identity"])
    if set(source["native"]) != eligible_codes or source["analyzed_security_count"] != len(eligible_codes):
        raise ValueError("Source analyzed security count mismatch")
    LOGGER.info("Verified frozen source: %d securities, %d native results", len(codes), len(eligible_codes))
    return source, series_manifest, calendar


def _copy_reference(root: Path, output_root: Path, reference: dict[str, Any]) -> None:
    source = _local_path(root, reference)
    target = output_root / reference["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    if sha(target) != reference["sha256"]:
        raise ValueError(f"Physical copy hash mismatch: {target}")


def _source_identities(source_path: Path, source: dict[str, Any], source_sha256: str, params: Path) -> dict[Path, str]:
    """Retain declared source identities instead of hashing mutable paths again."""
    root = source_path.parent
    identities: dict[Path, str] = {}

    def retain(path: Path, digest: str) -> None:
        # Normalize relative/dot segments without following an alias that the
        # mandatory guard must inspect and reject in the declared namespace.
        absolute = Path(os.path.abspath(path))
        if absolute in identities and identities[absolute] != digest:
            raise ValueError(f"Conflicting frozen source identities: {absolute}")
        identities[absolute] = digest

    retain(source_path, source_sha256)
    retain(params, source["producer_identity"]["config_sha256"])
    if "params_artifact" in source:
        retain(root / source["params_artifact"]["path"], source["producer_identity"]["config_sha256"])
    references = [source["calendar"], source["series_manifest"], *source["series"].values(), *source["extras"].values()]
    references.extend(reference for chunks in source["tables"].values() for reference in chunks)
    for native in source["native"].values():
        references.extend((native, native["receipt"]))
    for reference in references:
        retain(root / reference["path"], reference["sha256"])
    for item in source["input_receipt"]["files"]:
        retain(root.parent / "inputs" / item["name"], item["snapshot_sha256"])
    for name, expected in source["code_identity"]["source"].items():
        retain(root.parent / "method-snapshot" / f"{name}.ts", expected)
    return identities


def _check_identities(identities: dict[Path, str]) -> None:
    for path, expected in identities.items():
        try:
            actual = sha(path)
        except OSError as error:
            raise ValueError(f"Saved rebuild artifact unavailable before publication: {path}") from error
        if actual != expected:
            raise ValueError(f"Saved rebuild artifact changed before publication: {path}")


def rebuild_saved_catalog(source_manifest_path: Path, output_root: Path, params_path: Path | None = None) -> dict[str, Any]:
    """Rebuild compact v2 from saved evidence with Windows mandatory guards."""
    if output_root.exists():
        raise FileExistsError(f"Compact revision requires a new physical directory: {output_root}")
    require_publication_support()
    LOGGER.info("Validating saved native evidence and unchanged inputs")
    source_sha256 = sha(source_manifest_path)
    export_identity = {
        "script_sha256": sha(Path(__file__)),
        "adapter_sha256": sha(ROOT / "research_core/opportunity_history_catalog.py"),
        "publication_guard_sha256": sha(ROOT / "scripts/opportunity_artifact_publication.py"),
    }
    source, series_manifest, calendar = _verify_source(source_manifest_path, params_path, expected_manifest_sha256=source_sha256)
    root = source_manifest_path.parent
    # External native evidence stays in place. Resolve every relative reference
    # before creating a target: Windows cannot express these across drives.
    native_refs = {}
    try:
        source_manifest_ref = _fixed_descriptor(source_manifest_path, output_root, source_sha256)
        resolved_params = resolve_params_artifact(source_manifest_path, source, params_path)
        params_artifact = _fixed_descriptor(resolved_params, output_root, source["producer_identity"]["config_sha256"])
        for code, old_ref in source["native"].items():
            native_refs[code] = old_ref | _fixed_descriptor(root / old_ref["path"], output_root, old_ref["sha256"], 6)
            native_refs[code]["receipt"] = old_ref["receipt"] | _fixed_descriptor(root / old_ref["receipt"]["path"], output_root, old_ref["receipt"]["sha256"])
    except ValueError as error:
        raise ValueError(f"Saved-only rebuild requires relative evidence references on the same Windows drive as output: {error}") from error
    identities = _source_identities(source_manifest_path, source, source_sha256, resolved_params)
    identities[Path(__file__).resolve()] = export_identity["script_sha256"]
    identities[(ROOT / "research_core/opportunity_history_catalog.py").resolve()] = export_identity["adapter_sha256"]
    identities[(ROOT / "scripts/opportunity_artifact_publication.py").resolve()] = export_identity["publication_guard_sha256"]
    _check_identities(identities)
    output_root.mkdir(parents=True, exist_ok=False)
    try:
        copied = set()
        for reference in [source["calendar"], source["series_manifest"], *source["series"].values(), *source["extras"].values()]:
            if reference["path"] not in copied:
                _copy_reference(root, output_root, reference)
                copied.add(reference["path"])
        tables: dict[str, list[dict[str, Any]]] = {}
        for completed, row in enumerate(sorted(series_manifest["rows"], key=lambda item: item["code"]), 1):
            code = row["code"]
            series, _ = _read_json_identity(root / row["path"], row["sha256"])
            if code in source["native"]:
                old_ref = source["native"][code]
                native_path = root / old_ref["path"]
                native, _ = _read_json_identity(native_path, old_ref["sha256"])
            else:
                native = {
                    **{field: series[field] for field in ("security_id", "series_id", "calendar_id")},
                    "input_identity": {"series_sha256": row["sha256"], "calendar_sha256": source["calendar"]["sha256"]},
                    "native": [],
                    "support_records": [],
                }
            adapted = adapt_security(series, calendar, native)
            adapted["securities"][0].update({
                "stock_opportunity_eligible": _eligible(series),
                "method_eligibility_reason": "stock_cohort" if _eligible(series) else "excluded_role_or_identity",
                "coverage": series.get("coverage", {}),
            })
            for name, rows in adapted.items():
                tables.setdefault(name, []).extend(rows)
            if completed % 50 == 0:
                LOGGER.info("Saved-only compact revision: %d/%d securities", completed, series_manifest["count"])
        chunks = output_root / "chunks"
        chunks.mkdir()
        table_refs: dict[str, list[dict[str, Any]]] = {}
        for name, rows in sorted(tables.items()):
            LOGGER.info("Writing compact table %s with %d rows", name, len(rows))
            rows.sort(key=canonical)
            table_refs[name] = []
            for offset in range(0, max(1, len(rows)), CHUNK_ROWS):
                part = rows[offset : offset + CHUNK_ROWS]
                path = chunks / f"{name}-{offset // CHUNK_ROWS:05}.json.gz"
                # Bind the descriptor to the bytes prepared for writing, not
                # a later read that could re-sign concurrently changed output.
                expected_chunk_sha = hashlib.sha256(gzip.compress(canonical({"rows": part}), mtime=0)).hexdigest()
                write_json(path, {"rows": part})
                table_refs[name].append(_fixed_descriptor(path, output_root, expected_chunk_sha, len(part)))
        manifest = source.copy()
        manifest.update({
            "params_artifact": params_artifact,
            "tables": table_refs,
            "native": native_refs,
            "catalog_revision": "gain-continuity-v2",
            "source_manifest": source_manifest_ref,
            "adapter_revision": export_identity["adapter_sha256"],
            "analysis_recomputed": False,
            "gain_policy": "exact_pinned_js_run.preview.v2",
            "chunk_rows": CHUNK_ROWS,
            "compact_export_identity": {
                **export_identity,
                "source_code_commit": source.get("source_code_commit", SOURCE_COMMIT),
                "source_manifest_sha256": source_sha256,
            },
        })
        for reference in [source["calendar"], source["series_manifest"], *source["series"].values(), *source["extras"].values()]:
            identities[Path(os.path.abspath(output_root / reference["path"]))] = reference["sha256"]
        for references in table_refs.values():
            for reference in references:
                identities[Path(os.path.abspath(output_root / reference["path"]))] = reference["sha256"]
        LOGGER.info("Checking %d retained source/output identities before publication", len(identities))
        publish_json_manifest(output_root / "manifest.json", manifest, identities, writer=write_json)
        LOGGER.info("Re-exported compact revision at %s without method execution", output_root)
        return manifest
    except (OSError, ValueError) as error:
        failure_path = output_root / "publication.failure.json"
        LOGGER.exception("Saved-only rebuild rejected; retaining partial evidence at %s", output_root)
        failure = {
            "schema_version": "opportunity-saved-rebuild-failure.v1",
            "source_manifest": source_manifest_ref,
            "compact_export_identity": export_identity,
            "error": {"type": type(error).__name__, "message": str(error)},
        }
        try:
            write_json(failure_path, failure)
        except OSError:
            LOGGER.exception("Could not write exclusive saved rebuild diagnostic: %s", failure_path)
        if isinstance(error, OSError):
            raise ValueError(f"Saved rebuild artifact unavailable during publication: {error}") from error
        raise


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--params", type=Path)
    args = parser.parse_args(argv)
    manifest = rebuild_saved_catalog(args.source_manifest, args.output_root, params_path=args.params)
    sys.stdout.write(json.dumps({"catalog_revision": manifest["catalog_revision"], "analysis_recomputed": False}, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
