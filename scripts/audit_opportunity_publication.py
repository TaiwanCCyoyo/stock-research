"""Audit externally trusted publication bytes and their native artifact hash chain."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import query_opportunity_history as trust_module


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _check_hash(payload: bytes, expected: Any, label: str) -> None:
    _require(isinstance(expected, str) and _sha(payload) == expected.lower(), f"Publication hash mismatch: {label}")


def _read_reference(root: Path, reference: Any, label: str) -> bytes:
    _require(isinstance(reference, dict), f"Invalid publication descriptor: {label}")
    path = reference.get("path")
    _require(isinstance(path, str) and bool(path.strip()), f"Invalid publication path: {label}")
    raw = (root / path).read_bytes()
    _check_hash(raw, reference.get("sha256"), label)
    return raw


def audit_publication(
    manifest_path: Path,
    bundle_index_path: Path | None = None,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Read only; prove publication reconstruction and every native/receipt byte hash."""
    manifest_bytes = manifest_path.read_bytes()
    trust = trust_module.validate_manifest_trust(manifest_bytes, expected_manifest_sha256)
    index_path = bundle_index_path if bundle_index_path is not None else manifest_path.with_name("bundle-index.json")
    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes)
    _require(isinstance(index, dict), "Invalid publication bundle index")
    primary = index.get("primary_manifest")
    _require(isinstance(primary, dict), "Missing primary publication manifest")
    parts = primary.get("parts")
    _require(isinstance(parts, list) and bool(parts), "Missing publication manifest parts")
    original = bytearray()
    part_identities = []
    for position, part in enumerate(parts):
        _require(isinstance(part, dict), f"Invalid publication part: {position}")
        offset, length = part.get("raw_offset"), part.get("raw_length")
        _require(type(offset) is int and offset == len(original), f"Publication part offset/order mismatch: {position}")
        _require(type(length) is int and length > 0, f"Invalid publication part length: {position}")
        compressed = _read_reference(index_path.parent, part, f"part[{position}]")
        if "size_bytes" in part:
            _require(type(part["size_bytes"]) is int and part["size_bytes"] == len(compressed), f"Publication part size mismatch: {position}")
        decoded = gzip.decompress(compressed)
        _require(len(decoded) == length, f"Publication decoded part length mismatch: {position}")
        _check_hash(decoded, part.get("decoded_sha256"), f"decoded part[{position}]")
        part_identities.append({
            "path": part["path"],
            "sha256": _sha(compressed),
            "decoded_sha256": _sha(decoded),
            "raw_offset": offset,
            "raw_length": len(decoded),
        })
        original.extend(decoded)
    size = primary.get("original_size_bytes")
    _require(type(size) is int and size == len(original), "Publication original size mismatch")
    original_bytes = bytes(original)
    _check_hash(original_bytes, primary.get("original_sha256"), "original manifest")
    _check_hash(original_bytes, primary.get("decoded_sha256"), "decoded manifest")
    _require(original_bytes == manifest_bytes, "Publication reconstructed bytes differ from trusted manifest")
    manifest = json.loads(manifest_bytes)
    _require(isinstance(manifest, dict) and isinstance(manifest.get("native"), dict), "Invalid publication native registry")
    native_count = receipt_count = native_size = 0
    for code, reference in manifest["native"].items():
        raw = _read_reference(manifest_path.parent, reference, f"native[{code}]")
        native_count += 1
        native_size += len(raw)
        raw_receipt = _read_reference(manifest_path.parent, reference.get("receipt"), f"receipt[{code}]")
        receipt = json.loads(raw_receipt)
        _require(isinstance(receipt, dict), f"Invalid publication native receipt: {code}")
        _require(receipt.get("sha256") == _sha(raw), f"Publication receipt payload hash mismatch: {code}")
        receipt_count += 1
    _require(manifest_path.read_bytes() == manifest_bytes, "Publication manifest changed during audit")
    entrypoint_sha = _sha(Path(__file__).read_bytes())
    return {
        "schema_version": "opportunity-native-publication-anchor-audit.v3",
        "status": "verified",
        **trust,
        "manifest_parts_verified": len(parts),
        "bundle_identity": {"index_sha256": _sha(index_bytes), "parts": part_identities},
        "native_security_count": native_count,
        "native_receipt_count": receipt_count,
        "native_size_bytes": native_size,
        "comparison_basis": "externally_trusted_manifest_raw_bytes_to_all_native_and_receipt_file_sha256",
        "audit_script_sha256": entrypoint_sha,
        "audit_program_identity": {
            "entrypoint_sha256": entrypoint_sha,
            "trust_module_sha256": _sha(Path(trust_module.__file__).read_bytes()),
            "registered_manifest_sha256": trust_module.REGISTERED_MANIFEST_SHA256,
        },
        "curve_fit_recomputed": False,
        "pure_wave_launch_phase_recomputed": False,
        "source_cache_written": False,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bundle-index", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit_publication(args.manifest, args.bundle_index, expected_manifest_sha256=args.expected_manifest_sha256)
        encoded = json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False)
        if args.receipt is not None:
            with args.receipt.open("x", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"opportunity publication audit failed: {error}\n")
    sys.stdout.write(encoded + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
