"""Expose saved L20 evidence for the original ten cases; never rerun market outcomes."""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import zipfile
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.bounded_parquet import read_evidence_parquet
from research_core.hhhl_v4_landmark_view import AUDIT_LANDMARK_COLUMNS, VIEW_VERSION, attach_l20_audit
from research_core.jobs import confined, file_digest
from scripts.build_hhhl_v4_probability import EVENT_COLUMNS
from scripts.publish_hhhl_v4_probability import (
    MAX_TRANSPORT_METADATA_BYTES,
    _assemble_transport_bundle,
    _json_object,
    _read_transport_metadata,
    _require_sha,
    _sha,
    _validate_source_manifest,
    _zip_bytes,
)
from scripts.supplement_hhhl_v4_diagnostics import _assert_file_identity, _read_run_manifest, _validated_publication

LOGGER = logging.getLogger(__name__)
SCHEMA = "hhhl-v4-l20-audit-supplement.v1"
MAX_BYTES = 500_000
SOURCE_FILES = ("audit-sample.parquet", "landmarks.parquet")
LIMITATION = (
    "This is the same first-ten event sample, not a representative or success-selected sample. "
    "L20 fields are saved original observations, not a new price evaluation. The portable join is recomputable; "
    "source hashes identify original files but do not authenticate a maliciously substituted projection. "
    "Independent source checking requires the original hash-verified landmarks.parquet. "
    "JSON preserves nullable scalar values; original Parquet bytes and outcomes are not replaced."
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = frame.astype(object).where(frame.notna(), None).to_dict(orient="records")
    return [{key: value.isoformat() if isinstance(value, pd.Timestamp) else value for key, value in row.items()} for row in rows]


def _publication_audit(publication: Path) -> tuple[dict[str, Any], dict[str, Any], bytes, pd.DataFrame]:
    metadata, manifest, manifest_bytes, _ = _validated_publication(publication)
    bundle = _assemble_transport_bundle(publication, metadata)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        audit_bytes = archive.read("outputs/audit-sample.parquet")
    artifacts, _ = _validate_source_manifest(manifest)
    descriptor = artifacts["audit-sample.parquet"]
    if descriptor != {"sha256": _sha(audit_bytes), "bytes": len(audit_bytes)}:
        raise ValueError("published audit identity mismatch")
    # This supplement binds the original completed run's exact ten-case schema.
    audit = read_evidence_parquet(audit_bytes, 10, EVENT_COLUMNS, timestamp_columns=("asof_date",))
    return metadata, manifest, manifest_bytes, audit


def _landmark_rows(value: Any) -> pd.DataFrame:
    if not isinstance(value, list) or len(value) != 10:
        raise ValueError("audit requires exactly ten L20 source rows")
    if any(not isinstance(row, dict) or set(row) != set(AUDIT_LANDMARK_COLUMNS) for row in value):
        raise ValueError("audit L20 source columns mismatch")
    frame = pd.DataFrame(value, columns=pd.Index(AUDIT_LANDMARK_COLUMNS))
    if not cast(pd.Series, frame["landmark"]).map(lambda item: type(item) is int and item == 20).all():
        raise ValueError("audit source must be L20")
    if not cast(pd.Series, frame["status"]).isin(["active", "early_hit", "early_failed", "unknown"]).all():
        raise ValueError("audit source has an invalid landmark status")
    return frame


def create_supplement(run: Path, publication: Path, output: Path) -> dict[str, Any]:
    """Add a portable join of existing tables with pre/post source identity checks."""
    run, publication, output = Path(run), Path(publication), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"audit supplement already exists: {output}")
    confined(output.parent, output.name)
    if any(root.resolve() in output.resolve().parents for root in (run, publication)):
        raise ValueError("audit supplement must be outside original run and publication")
    metadata, manifest, manifest_bytes, audit = _publication_audit(publication)
    _read_run_manifest(run, metadata, manifest_bytes)
    artifacts, _ = _validate_source_manifest(manifest)
    sources = {name: artifacts[name] for name in SOURCE_FILES}
    for name, descriptor in sources.items():
        _assert_file_identity(confined(run, name), descriptor["sha256"], descriptor["bytes"], name)
    landmarks = pd.read_parquet(
        confined(run, "landmarks.parquet"),
        columns=list(AUDIT_LANDMARK_COLUMNS),
        filters=[("event_id", "in", audit["event_id"].tolist()), ("landmark", "=", 20)],
    )
    # Preserve raw planned coordinates in source rows; corrected coordinates are explicitly prefixed in the view.
    source_rows = _records(landmarks)
    joined = attach_l20_audit(audit, _landmark_rows(source_rows))
    helper = Path(__file__).resolve().parents[1] / "research_core" / "hhhl_v4_landmark_view.py"
    packet = {
        "schema_version": SCHEMA,
        "complete": True,
        "original_run_manifest_sha256": metadata["run_manifest_sha256"],
        "original_bundle_sha256": metadata["bundle_sha256"],
        "source_artifacts": sources,
        "code_sha256": {"script": file_digest(Path(__file__)), "helper": file_digest(helper)},
        "coordinate_view_version": VIEW_VERSION,
        "limitation": LIMITATION,
        "landmark_rows": source_rows,
        "audit_rows": _records(joined),
    }
    data = _json_bytes(packet)
    if len(data) > MAX_BYTES:
        raise ValueError("audit supplement exceeds its byte limit")
    for name, descriptor in sources.items():
        _assert_file_identity(confined(run, name), descriptor["sha256"], descriptor["bytes"], name)
    _assert_file_identity(confined(run, "manifest.json"), _sha(manifest_bytes), len(manifest_bytes), "manifest.json")
    with output.open("xb") as stream:
        stream.write(data)
    LOGGER.info("Saved ten original HHHL cases with L20 evidence bytes=%d", len(data))
    return verify_supplement(output, publication)


def verify_supplement(path: Path, publication: Path) -> dict[str, Any]:
    """Bounded JSON read, original event comparison and deterministic L20 join; no extraction or prices."""
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError("audit supplement must be a bounded regular file")
    if path.suffix.lower() == ".zip":
        # Existing single-member, bounded ZIP reader; archive code is never executed.
        packet = _read_transport_metadata(path)
    else:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("audit supplement exceeds its byte limit")
        packet = _json_object(data, "audit supplement")
    expected = {
        "schema_version",
        "complete",
        "original_run_manifest_sha256",
        "original_bundle_sha256",
        "source_artifacts",
        "code_sha256",
        "coordinate_view_version",
        "limitation",
        "landmark_rows",
        "audit_rows",
    }
    if set(packet) != expected or packet["schema_version"] != SCHEMA or packet["complete"] is not True:
        raise ValueError("audit supplement schema mismatch")
    metadata, manifest, _, audit = _publication_audit(Path(publication))
    for field, original in (("original_run_manifest_sha256", "run_manifest_sha256"), ("original_bundle_sha256", "bundle_sha256")):
        if packet[field] != metadata[original]:
            raise ValueError("audit supplement publication identity mismatch")
    artifacts, _ = _validate_source_manifest(manifest)
    if packet["source_artifacts"] != {name: artifacts[name] for name in SOURCE_FILES}:
        raise ValueError("audit supplement original source identity mismatch")
    if packet["coordinate_view_version"] != VIEW_VERSION or packet["limitation"] != LIMITATION:
        raise ValueError("audit supplement interpretation mismatch")
    code = packet["code_sha256"]
    if not isinstance(code, dict) or set(code) != {"script", "helper"}:
        raise ValueError("audit supplement code identity mismatch")
    for label, digest in code.items():
        _require_sha(digest, label)
    joined = attach_l20_audit(audit, _landmark_rows(packet["landmark_rows"]))
    if _json_bytes(packet["audit_rows"]) != _json_bytes(_records(joined)):
        raise ValueError("audit supplement differs from the original events and recomputed L20 join")
    LOGGER.info("Verified portable original ten-case L20 audit")
    return {"metadata": {key: value for key, value in packet.items() if key not in {"landmark_rows", "audit_rows"}}, "audit": joined}


def write_transport(source: Path, publication: Path, output: Path) -> dict[str, Any]:
    """Store the exact existing JSON bytes in one bounded publication.json member."""
    source, output = Path(source), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"audit transport already exists: {output}")
    if source.suffix.lower() != ".json" or output.suffix.lower() != ".zip":
        raise ValueError("audit transport requires JSON input and ZIP output")
    before = file_digest(source)
    verify_supplement(source, publication)
    with source.open("rb") as stream:
        data = stream.read(MAX_TRANSPORT_METADATA_BYTES + 1)
    if len(data) > MAX_TRANSPORT_METADATA_BYTES:
        raise ValueError("audit JSON exceeds the single-member ZIP transport limit")
    if _sha(data) != before or file_digest(source) != before:
        raise ValueError("audit JSON changed during transport")
    archive = _zip_bytes({"publication.json": data})
    if len(archive) > MAX_TRANSPORT_METADATA_BYTES:
        raise ValueError("audit ZIP exceeds the transport limit")
    confined(output.parent, output.name)
    with output.open("xb") as stream:
        stream.write(archive)
    LOGGER.info("Packed unchanged HHHL audit JSON bytes=%d ZIP bytes=%d", len(data), len(archive))
    return verify_supplement(output, publication)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--pack", type=Path, help="existing audit JSON to losslessly wrap as ZIP")
    args = parser.parse_args(argv)
    try:
        if args.pack and args.output:
            result = write_transport(args.pack, args.publication, args.output)
        elif args.verify:
            result = verify_supplement(args.verify, args.publication)
        elif args.run and args.output:
            result = create_supplement(args.run, args.publication, args.output)
        else:
            parser.error("provide --verify or --run and --output")
        sys.stdout.write(json.dumps({"passed": True, "rows": len(result["audit"]), "metadata": result["metadata"]}, ensure_ascii=False) + "\n")
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        LOGGER.error("HHHL L20 audit supplement failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
