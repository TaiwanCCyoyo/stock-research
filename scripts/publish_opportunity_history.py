"""Publish immutable byte-exact JSON mirrors without exporting local prices."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
MAX_MIRROR_BYTES = 450_000
PART_RAW_BYTES = 256 * 1024
INDEX_SCHEMA = "opportunity-publication-index.v2"
LOCAL_ONLY = ["chunks/**", "inputs/**", "../inputs/**", "series/**", "native/**", "../runs/native/**"]
RECOVERY_GAPS = [
    "Publication mirrors restore root JSON metadata only; schemas and original relative references are unchanged.",
    "Local physical inputs, aligned price/calendar series and dense native results are excluded; Git publication cannot recover them.",
    "Full compact event tables remain local only; restoring root metadata does not restore chunks, prices or fits. "
    "A complete query requires separately retained hash-matching tables, series and calendar artifacts.",
    "Historical identity and first availability gaps remain unknown; publication does not reconstruct unavailable data.",
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)


def publish_catalog(catalog_root: Path) -> dict[str, Any]:
    """Mirror root JSON as whole gzip or explicit ordered raw-byte gzip parts."""
    index_path = catalog_root / "bundle-index.json"
    if index_path.exists():
        raise FileExistsError(f"Publication index already exists: {index_path}")
    originals = sorted(path for path in catalog_root.glob("*.json") if path.name != index_path.name)
    names = {path.name for path in originals}
    if not {"manifest.json", "series-manifest.json"}.issubset(names):
        raise ValueError("Publication requires root manifest.json and series-manifest.json")
    manifest = json.loads((catalog_root / "manifest.json").read_bytes())
    if manifest.get("schema_version") != "opportunity-local-history-preview.v1":
        raise ValueError("Primary catalog schema mismatch")
    if not isinstance(manifest.get("extras"), dict):
        raise ValueError("Primary manifest must identify its extras")
    for name, extra_reference in manifest["extras"].items():
        path = Path(extra_reference["path"])
        if path.name not in names or path.parent != Path("."):
            raise ValueError(f"Required extra is not a root JSON publication: {name}")
        if _sha((catalog_root / path).read_bytes()) != extra_reference["sha256"]:
            raise ValueError(f"Required extra hash mismatch: {name}")
    # Preflight ALL mirrors before any write, so size refusal cannot partially publish.
    payloads: list[tuple[Path, bytes]] = []
    references: list[dict[str, Any]] = []
    planned_paths: set[Path] = set()
    for original in originals:
        mirror = original.with_suffix(".json.gz")
        if mirror.exists() or list(catalog_root.glob(f"{original.stem}.part-*.json.gz")):
            raise FileExistsError(f"Publication mirror already exists: {mirror}")
        raw = original.read_bytes()
        decoded = json.loads(raw)
        compressed = gzip.compress(raw, mtime=0)
        reference: dict[str, Any] = {
            "decoded_sha256": _sha(raw),
            "original_path": original.name,
            "original_sha256": _sha(raw),
            "original_size_bytes": len(raw),
            "schema_version": decoded.get("schema_version", decoded.get("schema")) if isinstance(decoded, dict) else None,
        }
        if len(compressed) <= MAX_MIRROR_BYTES:
            reference.update({"format": "gzip-json", "restore_required": False, "path": mirror.name, "sha256": _sha(compressed), "size_bytes": len(compressed)})
            pieces = [(mirror, compressed)]
        else:
            reference.update({"format": "gzip-multipart-rawbytes", "restore_required": True, "parts": []})
            pieces = []
            for number, offset in enumerate(range(0, len(raw), PART_RAW_BYTES)):
                part_raw = raw[offset : offset + PART_RAW_BYTES]
                part = gzip.compress(part_raw, mtime=0)
                path = catalog_root / f"{original.stem}.part-{number:05}.json.gz"
                if len(part) > MAX_MIRROR_BYTES:
                    raise ValueError(f"Publication part exceeds {MAX_MIRROR_BYTES} bytes: {path.name} has {len(part)} bytes")
                reference["parts"].append({
                    "path": path.name,
                    "sha256": _sha(part),
                    "size_bytes": len(part),
                    "decoded_sha256": _sha(part_raw),
                    "raw_offset": offset,
                    "raw_length": len(part_raw),
                    "encoding": "gzip-raw-byte-part",
                })
                pieces.append((path, part))
        for path, _ in pieces:
            if path in planned_paths or path.exists():
                raise FileExistsError(f"Duplicate or existing publication path: {path}")
            planned_paths.add(path)
        references.append(reference)
        payloads.extend(pieces)
    primary = next(ref for ref in references if ref["original_path"] == "manifest.json")
    index = {
        "schema_version": INDEX_SCHEMA,
        "primary_manifest": primary,
        "publications": references,
        "metadata_file_count": len(references),
        "mirror_file_count": len(payloads),
        "multipart_metadata_count": sum(ref["format"] == "gzip-multipart-rawbytes" for ref in references),
        "local_only_patterns": LOCAL_ONLY,
        "local_only_artifacts_available_from_publication": False,
        "recovery_gaps": RECOVERY_GAPS,
    }
    index_bytes = json.dumps(index, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    for path, payload in payloads:
        _write_exclusive(path, payload)
    _write_exclusive(index_path, index_bytes)
    LOGGER.info("Published %d root JSON mirrors at %s", len(references), catalog_root)
    return index


def restore_catalog(bundle_index_path: Path, target_root: Path) -> dict[str, Any]:
    """Restore exact root JSON into a NEW directory; local data stays missing."""
    if target_root.exists():
        raise FileExistsError(f"Restore requires a new target directory: {target_root}")
    index = json.loads(bundle_index_path.read_bytes())
    if index.get("schema_version") != INDEX_SCHEMA:
        raise ValueError("Publication index schema mismatch")
    primary = next((ref for ref in index["publications"] if ref["original_path"] == "manifest.json"), None)
    if primary is None or primary != index["primary_manifest"]:
        raise ValueError("Publication primary manifest descriptor mismatch")
    restored: list[str] = []
    payloads: list[tuple[Path, bytes]] = []
    seen: set[str] = set()
    for ref in index["publications"]:
        original = Path(ref["original_path"])
        if original.parent != Path(".") or original.suffix != ".json" or original.name in seen:
            raise ValueError("Invalid or duplicate root publication path")
        seen.add(original.name)
        if ref["format"] == "gzip-json":
            parts = [ref | {"raw_offset": 0, "raw_length": ref["original_size_bytes"]}]
        elif ref["format"] == "gzip-multipart-rawbytes" and ref.get("parts"):
            parts = ref["parts"]
        else:
            raise ValueError("Unsupported or empty publication format")
        decoded_parts = []
        offset = 0
        for number, part in enumerate(parts):
            mirror = Path(part["path"])
            expected_name = original.name + ".gz" if ref["format"] == "gzip-json" else f"{original.stem}.part-{number:05}.json.gz"
            if mirror.parent != Path(".") or mirror.name != expected_name or part["raw_offset"] != offset:
                raise ValueError("Invalid publication part path/order/offset")
            if ref["format"] != "gzip-json" and part.get("encoding") != "gzip-raw-byte-part":
                raise ValueError("Invalid multipart encoding")
            compressed = (bundle_index_path.parent / mirror).read_bytes()
            if len(compressed) != part["size_bytes"] or len(compressed) > MAX_MIRROR_BYTES or _sha(compressed) != part["sha256"]:
                raise ValueError(f"Publication mirror hash/size mismatch: {mirror}")
            decoded_part = gzip.decompress(compressed)
            if len(decoded_part) != part["raw_length"] or _sha(decoded_part) != part["decoded_sha256"]:
                raise ValueError(f"Decoded publication part hash/size mismatch: {mirror}")
            if ref["format"] == "gzip-multipart-rawbytes" and (
                len(decoded_part) > PART_RAW_BYTES or (number < len(parts) - 1 and len(decoded_part) != PART_RAW_BYTES)
            ):
                raise ValueError("Invalid multipart raw-byte partition length")
            offset += len(decoded_part)
            decoded_parts.append(decoded_part)
        raw = b"".join(decoded_parts)
        if len(raw) != ref["original_size_bytes"] or _sha(raw) != ref["decoded_sha256"] or _sha(raw) != ref["original_sha256"]:
            raise ValueError(f"Decoded original hash/size mismatch: {original}")
        decoded = json.loads(raw)
        schema = decoded.get("schema_version", decoded.get("schema")) if isinstance(decoded, dict) else None
        if schema != ref["schema_version"]:
            raise ValueError(f"Decoded original schema mismatch: {original}")
        payloads.append((original, raw))
    if not {"manifest.json", "series-manifest.json"}.issubset(seen):
        raise ValueError("Publication lacks required manifests")
    target_root.mkdir(parents=True, exist_ok=False)
    for path, raw in payloads:
        _write_exclusive(target_root / path, raw)
        restored.append(path.as_posix())
    LOGGER.info("Restored %d metadata JSON files to %s", len(restored), target_root)
    return {
        "restored": restored,
        "metadata_file_count": len(restored),
        "tables_restored": False,
        "prices_restored": False,
        "fits_restored": False,
        "local_only_artifacts_available": False,
        "local_only_patterns": index["local_only_patterns"],
        "recovery_gaps": index["recovery_gaps"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--catalog-root", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--bundle-index", type=Path, required=True)
    restore.add_argument("--target-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = publish_catalog(args.catalog_root) if args.command == "publish" else restore_catalog(args.bundle_index, args.target_root)
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
