"""Portable saved atlas aggregates; never validates or reconstructs bulk samples."""

from __future__ import annotations

import hashlib
import json
import logging
import lzma
import re
from pathlib import Path
from typing import Any

from research_core.evidence import finite_json, text_field
from research_core.feature_atlas_io import digest_json
from research_core.jobs import confined, digest

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = "feature-atlas-publication.v2"
SOURCE_SCHEMA = "feature-discrimination-atlas.v1"
FILES = ("comparisons.json.xz", "definitions.json", "summary.json", "source-manifest.json")
CAPABILITIES = {
    "supplied": ["complete_saved_comparisons", "feature_definitions", "original_summary", "source_manifest_provenance"],
    "bulk_only": ["per_security_samples", "exact_sample_joins", "comparison_recomputation", "continuous_distributions", "inventory", "benchmark_prices"],
    "bulk_validated": False,
    "full_catalog_supplied": False,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    result = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    finite_json(result)
    if not isinstance(result, dict) or not result:
        raise ValueError("required nonempty JSON object")
    return result


def _read(root: Path, name: str) -> bytes:
    path = confined(root, name)
    # confined checks the root; also reject linked ancestors above it.
    for ancestor in root.absolute().parents:
        confined(ancestor, root.absolute().relative_to(ancestor).as_posix())
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing or empty file: {name}")
    return path.read_bytes()


def _source(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("schema_version") != SOURCE_SCHEMA:
        raise ValueError(f"source manifest must use {SOURCE_SCHEMA}")
    text_field(manifest.get("dataset_id"), "dataset_id")
    text_field(manifest.get("run_id"), "run_id")
    if not isinstance(manifest.get("identity"), dict) or not manifest["identity"]:
        raise ValueError("source producer identity required")
    if manifest["dataset_id"] != "fda-" + digest_json(manifest["identity"]):
        raise ValueError("source dataset_id identity mismatch")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("source artifacts required")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("artifact descriptor must be an object")
        name = text_field(entry.get("path"), "path")
        # Validate paths without opening any bulk data.
        confined(Path.cwd(), name)
        sha = entry.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
            raise ValueError("invalid source SHA256")
        if name.casefold() in {key.casefold() for key in result}:
            raise ValueError("duplicate source artifact path")
        result[name] = entry
    for name in ("comparisons.json", "definitions.json", "summary.json"):
        if name not in result:
            raise ValueError(f"required source artifact missing: {name}")
    return result


def _counts(comparisons: dict[str, Any], definitions: dict[str, Any], summary: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    rows = comparisons.get("comparisons")
    features = definitions.get("features")
    if comparisons.get("dataset_id") != dataset_id or summary.get("run", {}).get("dataset_id") != dataset_id:
        raise ValueError("artifact dataset identity mismatch")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("nonempty comparison rows required")
    if not isinstance(features, dict) or not features or any(not isinstance(spec, dict) for spec in features.values()):
        raise ValueError("nonempty feature definitions required")
    continuous = definitions.get("continuous")
    if not isinstance(continuous, list) or not continuous or len(set(continuous)) != len(continuous):
        raise ValueError("nonempty unique continuous component definitions required")
    for value in continuous:
        text_field(value, "continuous component")
    for row in rows:
        if (
            row.get("feature") not in features
            or row.get("panel") not in {"daily", "grid126"}
            or row.get("context_column") not in {None, "year", "regime", "industry_ref"}
        ):
            raise ValueError("invalid comparison feature/panel/context")
    metrics = summary.get("metrics", {})
    if metrics.get("comparison_rows") != len(rows) or metrics.get("feature_count") != len(features):
        raise ValueError("summary count mismatch")
    return {
        "comparisons": len(rows),
        "features": len(features),
        "continuous_components": len(continuous),
        "panels": {panel: sum(row["panel"] == panel for row in rows) for panel in ("daily", "grid126")},
    }


def _identity(source: dict[str, Any], source_sha: str, hashes: dict[str, str]) -> str:
    return (
        SCHEMA_VERSION
        + "-"
        + digest({
            "schema_version": SCHEMA_VERSION,
            "dataset_id": source["dataset_id"],
            "run_id": source["run_id"],
            "producer_identity": source["identity"],
            "source_manifest_sha256": source_sha,
            "artifact_sha256": hashes,
        })
    )


def publish_feature_atlas(dataset: Path, output: Path, bulk_locations: list[str] | None = None) -> dict[str, Any]:
    """Copy hash-pinned aggregates once, preserving exact comparison JSON bytes."""
    if output.exists() or output.is_symlink():
        raise ValueError(f"publication output already exists: {output}")
    source_bytes = _read(dataset, "manifest.json")
    source = _json(source_bytes)
    entries = _source(source)
    originals = {name: _read(dataset, name) for name in ("comparisons.json", "definitions.json", "summary.json")}
    for name, data in originals.items():
        if _sha(data) != entries[name]["sha256"]:
            raise ValueError(f"source SHA256 mismatch: {name}")
    counts = _counts(_json(originals["comparisons.json"]), _json(originals["definitions.json"]), _json(originals["summary.json"]), source["dataset_id"])
    contents = {
        "comparisons.json.xz": lzma.compress(originals["comparisons.json"], format=lzma.FORMAT_XZ),
        "definitions.json": originals["definitions.json"],
        "summary.json": originals["summary.json"],
        "source-manifest.json": source_bytes,
    }
    hashes = {name: _sha(data) for name, data in contents.items()}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "publication_id": _identity(source, _sha(source_bytes), hashes),
        "dataset_id": source["dataset_id"],
        "run_id": source["run_id"],
        "source_manifest_sha256": _sha(source_bytes),
        "comparison_original_sha256": _sha(originals["comparisons.json"]),
        "files": [{"path": name, "sha256": hashes[name], "bytes": len(contents[name])} for name in FILES],
        "counts": counts,
        "capabilities": CAPABILITIES,
        "interpretation": (
            "Preserved descriptive exploration; missing-outcome bounds are not confidence intervals; "
            "price-path metrics are not account performance. Original warnings and model stage remain "
            "in summary.json and definitions.json."
        ),
        "bulk_locations": [
            {
                "path": text_field(path, "bulk location"),
                "availability": "local_same_drive_nonportable",
                "off_machine_backup": False,
                "verified_by_publication": False,
            }
            for path in (bulk_locations or [])
        ],
    }
    confined(output.parent, output.name)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in contents.items():
        (output / name).write_bytes(data)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    LOGGER.info("Published saved atlas dataset=%s comparisons=%d output=%s", source["dataset_id"], counts["comparisons"], output)
    return manifest


def load_publication(root: Path) -> dict[str, Any]:
    """Verify every supplied file and identity, explicitly excluding bulk validation."""
    manifest = _json(_read(root, "manifest.json"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"publication must use {SCHEMA_VERSION}")
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != len(FILES):
        raise ValueError("required publication file descriptors missing")
    contents: dict[str, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid file descriptor")
        name = text_field(entry.get("path"), "path")
        data = _read(root, name)
        if name not in FILES or name in contents:
            raise ValueError("unexpected or duplicate publication path")
        if _sha(data) != entry.get("sha256") or len(data) != entry.get("bytes"):
            raise ValueError(f"publication SHA256/byte count mismatch: {name}")
        contents[name] = data
    source = _json(contents["source-manifest.json"])
    source_entries = _source(source)
    source_sha = _sha(contents["source-manifest.json"])
    if manifest.get("source_manifest_sha256") != source_sha:
        raise ValueError("source manifest SHA256 mismatch")
    try:
        raw = lzma.decompress(contents["comparisons.json.xz"], format=lzma.FORMAT_XZ)
    except lzma.LZMAError as error:
        raise ValueError("invalid comparison XZ") from error
    originals = {"comparisons.json": raw, "definitions.json": contents["definitions.json"], "summary.json": contents["summary.json"]}
    for name, data in originals.items():
        if _sha(data) != source_entries[name]["sha256"]:
            raise ValueError(f"source artifact SHA256 mismatch: {name}")
    if _sha(raw) != manifest.get("comparison_original_sha256"):
        raise ValueError("original comparison SHA256 mismatch")
    values = {name: _json(data) for name, data in originals.items()}
    counts = _counts(values["comparisons.json"], values["definitions.json"], values["summary.json"], source["dataset_id"])
    if manifest.get("counts") != counts:
        raise ValueError("publication count mismatch")
    hashes = {name: _sha(data) for name, data in contents.items()}
    if manifest.get("publication_id") != _identity(source, source_sha, hashes) or any(manifest.get(key) != source[key] for key in ("dataset_id", "run_id")):
        raise ValueError("publication identity mismatch")
    if manifest.get("capabilities") != CAPABILITIES:
        raise ValueError("publication capability scope mismatch")
    locations = manifest.get("bulk_locations")
    if not isinstance(locations, list):
        raise ValueError("bulk locations must be explicit")
    for location in locations:
        if (
            not isinstance(location, dict)
            or location.get("availability") != "local_same_drive_nonportable"
            or location.get("off_machine_backup") is not False
            or location.get("verified_by_publication") is not False
        ):
            raise ValueError("invalid bulk availability claim")
        text_field(location.get("path"), "bulk location")
    LOGGER.debug("Verified portable atlas publication=%s", manifest["publication_id"])
    return {
        "manifest": manifest,
        "comparisons": values["comparisons.json"]["comparisons"],
        "definitions": values["definitions.json"],
        "summary": values["summary.json"],
        "source_manifest": source,
    }


def verify_publication(root: Path) -> dict[str, Any]:
    manifest = load_publication(root)["manifest"]
    return {
        "publication_id": manifest["publication_id"],
        "dataset_id": manifest["dataset_id"],
        "counts": manifest["counts"],
        "verified_files": len(FILES),
        "capabilities": manifest["capabilities"],
    }


def query_comparisons(root: Path, feature: str | None = None, panel: str = "daily", context: str = "pooled") -> list[dict[str, Any]]:
    """Apply the original saved-comparison CLI's panel/feature/context semantics."""
    publication = load_publication(root)
    if panel not in {"daily", "grid126"} or context not in {"pooled", "year", "regime", "industry_ref"}:
        raise ValueError("invalid panel or context")
    if feature is not None and feature not in publication["definitions"]["features"]:
        raise ValueError("unknown feature")
    return [
        row
        for row in publication["comparisons"]
        if row["panel"] == panel and (feature is None or row["feature"] == feature) and row["context_column"] == (None if context == "pooled" else context)
    ]
