"""Create and verify a portable, byte-checked HHHL v4 publication bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import stat
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from research_core.hhhl_v4_summary_validation import validate_summary_comparisons, validate_summary_payload
from research_core.jobs import confined, file_digest
from scripts.validate_hhhl_v4_source import write_json

LOGGER = logging.getLogger(__name__)
RUN_SCHEMA = "hhhl-probability.v4"
PUBLICATION_SCHEMA = "hhhl-v4-probability-publication.v1"
TRANSPORT_SCHEMA = "hhhl-v4-probability-transport.v2"
PUBLICATION_NAME = "publication.json"
PUBLICATION_ARCHIVE_NAME = "publication.zip"
BUNDLE_NAME = "bundle.zip"
MAX_BUNDLE_BYTES = 10_000_000
MAX_MEMBER_EXPANDED_BYTES = 32_000_000
MAX_BUNDLE_EXPANDED_BYTES = 64_000_000
MAX_TRANSPORT_PART_BYTES = 400_000
MAX_TRANSPORT_METADATA_BYTES = 100_000
SCIENTIFIC_CELLS = 1080
OUTPUT_FILES = (
    "manifest.json",
    "summaries.json",
    "diagnostics.json",
    "coverage.json",
    "audit-sample.parquet",
    "label-discordance-63.parquet",
    "label-discordance-126.parquet",
)
OUTPUT_ARTIFACTS = OUTPUT_FILES[1:]
SUMMARY_KEY_FIELDS = ("family", "slice", "value", "sampling", "horizon", "basis")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON in {label}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _json_value(data: bytes, label: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON in {label}") from exc


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"invalid SHA-256 for {label}")
    return value


def _require_bytes(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"invalid byte count for {label}")
    return value


def _expected_summary_keys() -> set[tuple[Any, ...]]:
    """Mirror the preregistered grid in hhhl_v4_summary without reading results."""
    scopes = (("pooled", "all"), *(("year", str(year)) for year in range(2019, 2027)))
    event_slices = (*scopes, *(("cat", cat) for cat in ("hhhl", "bottom", "range")), ("limit_up", "false"), ("limit_up", "true"))
    event_families = ("E-all", "E-clean", "E-overhead", "E-overhead-old-only", "E-overhead-recent-far-only", "E-overhead-both", "X-inside")
    keys: set[tuple[Any, ...]] = set()
    for families, slices, samplings in (
        (("all_stock_days", "high_volume_no_event", "high_volume_no_pattern"), scopes, ("all_observations",)),
        (event_families, event_slices, ("all_events", "first_per_security")),
        (("noise",), (("pooled", "all"),), ("all_events", "first_per_security")),
    ):
        for family in families:
            for slice_name, cell_value in slices:
                for sampling in samplings:
                    for horizon in (63, 126):
                        for basis in ("adjusted_reference_factor", "atlas_original"):
                            keys.add((family, slice_name, cell_value, sampling, horizon, basis, None))
    landmark_families = ("cross_any", "cross_old_only", "cross_recent_far_only", "cross_both", "uncrossed_overhead", "clean_reference")
    landmark_slices = (("pooled", "all"), *(("rise_bin", name) for name in ("lt1", "b1_1p10", "b1p10_1p25", "ge1p25")))
    for family in landmark_families:
        for slice_name, cell_value in landmark_slices:
            for sampling in ("all_events", "first_per_security"):
                for landmark in (10, 20, 40):
                    keys.add((family, slice_name, cell_value, sampling, 126, "adjusted_reference_factor", landmark))
    return keys


def _validate_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != SCIENTIFIC_CELLS:
        raise ValueError(f"summaries must contain exactly {SCIENTIFIC_CELLS} cells")
    seen: set[tuple[Any, ...]] = set()
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or any(field not in row for field in SUMMARY_KEY_FIELDS):
            raise ValueError(f"summary cell {index} is missing key fields")
        if any(type(row[field]) is not str for field in SUMMARY_KEY_FIELDS if field != "horizon") or type(row["horizon"]) is not int:
            raise ValueError(f"summary cell {index} has an invalid key field type")
        if row.get("landmark") is not None and type(row["landmark"]) is not int:
            raise ValueError(f"summary cell {index} has an invalid landmark type")
        key = tuple(row[field] for field in SUMMARY_KEY_FIELDS) + (row.get("landmark"),)
        try:
            duplicate = key in seen
            seen.add(key)
        except TypeError as exc:
            raise ValueError(f"summary cell {index} has an unhashable key field") from exc
        if duplicate:
            raise ValueError(f"duplicate summary key at cell {index}")
        rows.append(row)
    expected = _expected_summary_keys()
    if seen != expected:
        missing, unexpected = len(expected - seen), len(seen - expected)
        LOGGER.warning("HHHL v4 summary grid mismatch missing=%d unexpected=%d", missing, unexpected)
        raise ValueError(f"summary keys do not match fixed v4 grid: missing={missing}, unexpected={unexpected}")
    for index, row in enumerate(rows):
        validate_summary_payload(row, index)
    validate_summary_comparisons(rows)
    return rows


def _artifact_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = manifest.get("artifacts")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("source artifact map is required")
    artifacts: dict[str, dict[str, Any]] = {}
    seen_casefold: set[str] = set()
    for relative, descriptor in raw.items():
        if not isinstance(relative, str) or not relative:
            raise ValueError("source artifact paths must be nonempty strings")
        if relative.casefold() in seen_casefold:
            raise ValueError(f"duplicate source artifact path: {relative}")
        seen_casefold.add(relative.casefold())
        if relative == "manifest.json":
            raise ValueError("source manifest must not list itself as an artifact")
        if not isinstance(descriptor, dict):
            raise ValueError(f"invalid source artifact descriptor: {relative}")
        _require_sha(descriptor.get("sha256"), relative)
        _require_bytes(descriptor.get("bytes"), relative)
        artifacts[relative] = descriptor
    for name in OUTPUT_ARTIFACTS:
        if name not in artifacts:
            raise ValueError(f"required source output artifact missing: {name}")
    return artifacts


def _identity_map(manifest: dict[str, Any]) -> dict[str, str]:
    raw = manifest.get("identity")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("source identity map is required")
    identities: dict[str, str] = {}
    for original, digest in raw.items():
        if not isinstance(original, str) or not original:
            raise ValueError("source identity paths must be nonempty strings")
        if not _identity_path_is_absolute(original):
            _validate_relative_identity_path(original)
        identities[original] = _require_sha(digest, original)
    return identities


def _identity_path_is_absolute(value: str) -> bool:
    return Path(value).is_absolute() or PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _validate_relative_identity_path(value: str) -> None:
    normalized = value.replace("\\", "/")
    _validate_member_name(normalized)
    for part in normalized.split("/"):
        if re.search(r'[<>:"|?*]', part) or part.endswith((" ", ".")) or PureWindowsPath(part).is_reserved():
            raise ValueError(f"unsafe relative source identity path: {value}")


def _validate_source_manifest(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    if manifest.get("schema_version") != RUN_SCHEMA or manifest.get("complete") is not True:
        raise ValueError("source run must be complete hhhl-probability.v4")
    if not isinstance(manifest.get("code_commit"), str) or not manifest["code_commit"]:
        raise ValueError("source code commit is required")
    return _artifact_map(manifest), _identity_map(manifest)


def _read_run_manifest(run: Path) -> tuple[bytes, dict[str, Any]]:
    path = confined(run, "manifest.json")
    if not path.is_file():
        raise ValueError("source run manifest is missing")
    data = path.read_bytes()
    if file_digest(path) != _sha(data):
        raise ValueError("source run manifest changed while being read")
    return data, _json_object(data, "source run manifest")


def _verify_run_artifacts(run: Path, artifacts: dict[str, dict[str, Any]]) -> None:
    for relative, descriptor in artifacts.items():
        path = confined(run, relative)
        if not path.is_file():
            raise ValueError(f"source artifact is missing or not a file: {relative}")
        actual_bytes = path.stat().st_size
        actual_sha = file_digest(path)
        if actual_bytes != descriptor["bytes"] or actual_sha != descriptor["sha256"]:
            raise ValueError(f"source artifact hash/byte mismatch: {relative}")


def _read_verified_artifact(run: Path, relative: str, descriptor: dict[str, Any]) -> bytes:
    path = confined(run, relative)
    data = path.read_bytes()
    if len(data) != descriptor["bytes"] or _sha(data) != descriptor["sha256"] or file_digest(path) != descriptor["sha256"]:
        raise ValueError(f"source artifact changed while being read: {relative}")
    return data


def _identity_name(original: str, index: int) -> str:
    pure_path = PureWindowsPath(original) if PureWindowsPath(original).drive or "\\" in original else PurePosixPath(original)
    if not pure_path.name or pure_path.name in {".", ".."}:
        raise ValueError(f"source identity path has no filename: {original}")
    return f"inputs/{index:02d}-{pure_path.name}"


def _identity_checkout(identities: dict[str, str]) -> Path:
    suffix = "scripts/build_hhhl_v4_probability.py"
    builder_keys = []
    for original in identities:
        pure_path = PureWindowsPath(original) if PureWindowsPath(original).drive or "\\" in original else PurePosixPath(original)
        if _identity_path_is_absolute(original) and pure_path.as_posix().endswith(suffix):
            builder_keys.append(original)
    if len(builder_keys) != 1:
        raise ValueError("source identity must contain one absolute builder script path")
    builder = Path(builder_keys[0])
    if not builder.is_absolute() or not builder.is_file():
        raise ValueError("absolute builder script identity is unavailable")
    if len(builder.parents) < 2:
        raise ValueError("cannot derive checkout root from builder script identity")
    return builder.parents[1]


def _identity_source_path(checkout: Path, original: str) -> Path:
    if _identity_path_is_absolute(original):
        path = Path(original)
        if not path.is_absolute():
            raise ValueError(f"absolute identity path is not native to this host: {original}")
        return path
    return confined(checkout, original.replace("\\", "/"))


def _validate_member_name(name: Any) -> str:
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"unsafe ZIP member name: {name!r}")
    pure = PurePosixPath(name)
    if pure.is_absolute() or pure.as_posix() != name or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError(f"unsafe ZIP member name: {name!r}")
    if PureWindowsPath(name).drive or ":" in name:
        raise ValueError(f"unsafe ZIP member name: {name!r}")
    return name


def _zip_bytes(payloads: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in payloads.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return stream.getvalue()


def publish(run: Path, output: Path) -> dict[str, Any]:
    """Verify a completed run and write an exclusive byte-preserving ZIP publication."""
    run = Path(run)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"publication output already exists: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"publication parent directory must exist: {output.parent}")
    confined(output.parent, output.name)
    run_absolute = run.resolve()
    output_absolute = output.resolve()
    if output_absolute == run_absolute or run_absolute in output_absolute.parents:
        raise ValueError("publication output must be outside the source run")

    run_manifest_bytes, source_manifest = _read_run_manifest(run)
    artifacts, identities = _validate_source_manifest(source_manifest)
    _verify_run_artifacts(run, artifacts)

    summaries_bytes = _read_verified_artifact(run, "summaries.json", artifacts["summaries.json"])
    summaries = _validate_summaries(_json_value(summaries_bytes, "source summaries"))

    # Capture and verify every identity byte sequence before opening the ZIP writer.
    checkout = _identity_checkout(identities)
    identity_payloads: list[tuple[str, str, bytes]] = []
    for index, original in enumerate(sorted(identities)):
        path = _identity_source_path(checkout, original)
        if not path.is_file():
            raise ValueError(f"source identity input is missing: {original}")
        data = path.read_bytes()
        expected_sha = identities[original]
        if _sha(data) != expected_sha or file_digest(path) != expected_sha:
            raise ValueError(f"source identity hash mismatch: {original}")
        identity_payloads.append((_identity_name(original, index), original, data))

    payloads: dict[str, bytes] = {}
    members: dict[str, dict[str, Any]] = {}
    manifest_member = "outputs/manifest.json"
    payloads[manifest_member] = run_manifest_bytes
    members[manifest_member] = {
        "sha256": _sha(run_manifest_bytes),
        "bytes": len(run_manifest_bytes),
        "original_path": "manifest.json",
    }
    for name in OUTPUT_ARTIFACTS:
        data = _read_verified_artifact(run, name, artifacts[name])
        member = f"outputs/{name}"
        payloads[member] = data
        members[member] = {"sha256": _sha(data), "bytes": len(data), "original_path": name}
    for member, original, data in identity_payloads:
        payloads[member] = data
        members[member] = {"sha256": _sha(data), "bytes": len(data), "original_path": original}

    bundle = _zip_bytes(payloads)
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    metadata: dict[str, Any] = {
        "schema_version": PUBLICATION_SCHEMA,
        "bundle_path": BUNDLE_NAME,
        "bundle_sha256": _sha(bundle),
        "bundle_bytes": len(bundle),
        "run_manifest_sha256": _sha(run_manifest_bytes),
        "source_code_commit": source_manifest["code_commit"],
        "bulk_location": str(run_absolute),
        "bulk_location_availability": "local_only",
        "bulk_location_verified": False,
        "scientific_cells": SCIENTIFIC_CELLS,
        "members": members,
    }

    output.mkdir(parents=False, exist_ok=False)
    with (output / BUNDLE_NAME).open("xb") as stream:
        stream.write(bundle)
    write_json(output / PUBLICATION_NAME, metadata)
    LOGGER.info("Published HHHL v4 cells=%d bundle_bytes=%d at %s", len(summaries), len(bundle), output)
    return metadata


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def convert_publication(root: Path, output: Path) -> dict[str, Any]:
    """Convert a verified v1 publication to additive, bounded transport parts."""
    root = Path(root)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"publication output already exists: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"publication parent directory must exist: {output.parent}")
    confined(output.parent, output.name)
    source_absolute = root.resolve()
    output_absolute = output.resolve()
    if output_absolute == source_absolute or source_absolute in output_absolute.parents:
        raise ValueError("transport output must be outside the source publication")

    verified = verify_publication(root)
    source_metadata = verified["metadata"]
    if "transport_schema" in source_metadata:
        raise ValueError("transport conversion requires a v1 publication")
    source_bundle = confined(root, BUNDLE_NAME)
    if not source_bundle.is_file() or source_bundle.is_symlink():
        raise ValueError("source publication bundle is missing or not a regular file")
    if source_bundle.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    with source_bundle.open("rb") as stream:
        bundle = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    if len(bundle) != source_metadata["bundle_bytes"] or _sha(bundle) != source_metadata["bundle_sha256"]:
        raise ValueError("source publication bundle changed during transport conversion")

    parts: list[dict[str, Any]] = []
    part_payloads: list[tuple[str, bytes]] = []
    for start in range(0, len(bundle), MAX_TRANSPORT_PART_BYTES):
        index = len(parts) + 1
        name = f"bundle.{index:03d}.bin"
        data = bundle[start : start + MAX_TRANSPORT_PART_BYTES]
        parts.append({"path": name, "sha256": _sha(data), "bytes": len(data)})
        part_payloads.append((name, data))

    metadata = dict(source_metadata)
    metadata["transport_schema"] = TRANSPORT_SCHEMA
    metadata["bundle_parts"] = parts
    metadata_archive = _zip_bytes({PUBLICATION_NAME: _json_bytes(metadata)})
    if len(metadata_archive) > MAX_TRANSPORT_METADATA_BYTES:
        raise ValueError(f"transport metadata archive exceeds {MAX_TRANSPORT_METADATA_BYTES} bytes")

    output.mkdir(parents=False, exist_ok=False)
    with (output / PUBLICATION_ARCHIVE_NAME).open("xb") as stream:
        stream.write(metadata_archive)
    for name, data in part_payloads:
        part_path = confined(output, name)
        with part_path.open("xb") as stream:
            stream.write(data)
    LOGGER.info(
        "Converted HHHL v4 publication parts=%d bundle_bytes=%d at %s",
        len(parts),
        len(bundle),
        output,
    )
    return metadata


def _expected_members(artifacts: dict[str, dict[str, Any]], identities: dict[str, str]) -> dict[str, str]:
    expected = {"outputs/manifest.json": "manifest.json"}
    for name in OUTPUT_ARTIFACTS:
        if name not in artifacts:
            raise ValueError(f"source manifest lacks bundled output artifact: {name}")
        expected[f"outputs/{name}"] = name
    for index, original in enumerate(sorted(identities)):
        expected[_identity_name(original, index)] = original
    return expected


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, descriptor: dict[str, Any]) -> bytes:
    expected_bytes = _require_bytes(descriptor.get("bytes"), info.filename)
    expected_sha = _require_sha(descriptor.get("sha256"), info.filename)
    if expected_bytes > MAX_MEMBER_EXPANDED_BYTES or info.file_size > MAX_MEMBER_EXPANDED_BYTES:
        raise ValueError(f"publication member exceeds expanded size limit: {info.filename}")
    if info.file_size != expected_bytes:
        raise ValueError(f"ZIP member byte count mismatch: {info.filename}")
    digest = hashlib.sha256()
    byte_count = 0
    captured = bytearray() if info.filename in {"outputs/manifest.json", "outputs/summaries.json"} else None
    try:
        with archive.open(info, "r") as stream:
            while chunk := stream.read(64 * 1024):
                byte_count += len(chunk)
                if byte_count > expected_bytes:
                    raise ValueError(f"ZIP member exceeds declared byte count: {info.filename}")
                digest.update(chunk)
                if captured is not None:
                    captured.extend(chunk)
    except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        raise ValueError(f"cannot read ZIP member: {info.filename}") from exc
    if byte_count != expected_bytes or digest.hexdigest() != expected_sha:
        raise ValueError(f"ZIP member hash/byte mismatch: {info.filename}")
    return bytes(captured) if captured is not None else b""


def _read_transport_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("transport publication archive is missing or not a regular file")
    if path.stat().st_size > MAX_TRANSPORT_METADATA_BYTES:
        raise ValueError(f"transport metadata archive exceeds {MAX_TRANSPORT_METADATA_BYTES} bytes")
    with path.open("rb") as stream:
        archive_bytes = stream.read(MAX_TRANSPORT_METADATA_BYTES + 1)
    if len(archive_bytes) > MAX_TRANSPORT_METADATA_BYTES:
        raise ValueError(f"transport metadata archive exceeds {MAX_TRANSPORT_METADATA_BYTES} bytes")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != PUBLICATION_NAME:
                raise ValueError("transport archive must contain only publication.json")
            info = infos[0]
            _validate_member_name(info.filename)
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("transport metadata member must be a regular file")
            if info.file_size > MAX_TRANSPORT_METADATA_BYTES:
                raise ValueError(f"transport metadata exceeds {MAX_TRANSPORT_METADATA_BYTES} bytes")
            with archive.open(info, "r") as stream:
                metadata_bytes = stream.read(MAX_TRANSPORT_METADATA_BYTES + 1)
            if len(metadata_bytes) != info.file_size or len(metadata_bytes) > MAX_TRANSPORT_METADATA_BYTES:
                raise ValueError("transport metadata byte count mismatch")
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ValueError("invalid transport publication archive") from exc
    return _json_object(metadata_bytes, "transport publication manifest")


def _assemble_transport_bundle(root: Path, metadata: dict[str, Any]) -> bytes:
    if metadata.get("transport_schema") != TRANSPORT_SCHEMA:
        raise ValueError("transport publication schema mismatch")
    raw_parts = metadata.get("bundle_parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValueError("transport bundle parts are required")

    expected_bundle_bytes = _require_bytes(metadata.get("bundle_bytes"), "bundle")
    if expected_bundle_bytes > MAX_BUNDLE_BYTES:
        raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    parts_data: list[bytes] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    for index, descriptor in enumerate(raw_parts):
        if not isinstance(descriptor, dict):
            raise ValueError(f"invalid transport part descriptor at index {index}")
        relative = _validate_member_name(descriptor.get("path"))
        if (
            PurePosixPath(relative).name != relative
            or relative in {PUBLICATION_NAME, PUBLICATION_ARCHIVE_NAME}
            or PureWindowsPath(relative).is_reserved()
            or relative.endswith((" ", "."))
        ):
            raise ValueError(f"transport part path must be a root-level filename: {relative}")
        casefolded = relative.casefold()
        if casefolded in seen_paths:
            raise ValueError(f"duplicate transport part path: {relative}")
        seen_paths.add(casefolded)
        part_bytes = _require_bytes(descriptor.get("bytes"), relative)
        if part_bytes <= 0 or part_bytes > MAX_TRANSPORT_PART_BYTES:
            raise ValueError(f"transport part exceeds {MAX_TRANSPORT_PART_BYTES} bytes: {relative}")
        expected_sha = _require_sha(descriptor.get("sha256"), relative)
        total_bytes += part_bytes
        if total_bytes > MAX_BUNDLE_BYTES:
            raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
        part_path = confined(root, relative)
        if not part_path.is_file() or part_path.is_symlink():
            raise ValueError(f"transport bundle part is missing or not a regular file: {relative}")
        if part_path.stat().st_size != part_bytes:
            raise ValueError(f"transport part byte count mismatch: {relative}")
        with part_path.open("rb") as stream:
            data = stream.read(MAX_TRANSPORT_PART_BYTES + 1)
        if len(data) != part_bytes or _sha(data) != expected_sha:
            raise ValueError(f"transport part hash/byte mismatch: {relative}")
        parts_data.append(data)

    if total_bytes != expected_bundle_bytes:
        raise ValueError("transport part sizes do not match original bundle byte count")
    bundle = b"".join(parts_data)
    if len(bundle) != expected_bundle_bytes or _sha(bundle) != _require_sha(metadata.get("bundle_sha256"), "bundle"):
        raise ValueError("assembled publication bundle hash/byte mismatch")
    return bundle


def _verify_bundle(metadata: dict[str, Any], bundle: bytes, root: Path) -> dict[str, Any]:
    if metadata.get("schema_version") != PUBLICATION_SCHEMA:
        raise ValueError("publication schema mismatch")
    if metadata.get("bundle_path") != BUNDLE_NAME:
        raise ValueError("unsupported publication bundle path")
    bundle_bytes = _require_bytes(metadata.get("bundle_bytes"), "bundle")
    bundle_sha = _require_sha(metadata.get("bundle_sha256"), "bundle")
    if bundle_bytes > MAX_BUNDLE_BYTES:
        raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    if len(bundle) != bundle_bytes or _sha(bundle) != bundle_sha:
        raise ValueError("publication bundle hash/byte mismatch")

    member_descriptors = metadata.get("members")
    if not isinstance(member_descriptors, dict) or not member_descriptors:
        raise ValueError("publication member map is required")
    descriptor_expanded_bytes = 0
    for name, descriptor in member_descriptors.items():
        _validate_member_name(name)
        if not isinstance(descriptor, dict):
            raise ValueError(f"invalid member descriptor: {name}")
        _require_sha(descriptor.get("sha256"), name)
        member_bytes = _require_bytes(descriptor.get("bytes"), name)
        descriptor_expanded_bytes += member_bytes
        if member_bytes > MAX_MEMBER_EXPANDED_BYTES:
            raise ValueError(f"publication member descriptor exceeds expanded size limit: {name}")
        if descriptor_expanded_bytes > MAX_BUNDLE_EXPANDED_BYTES:
            raise ValueError("publication descriptors exceed total expanded size limit")
        if not isinstance(descriptor.get("original_path"), str):
            raise ValueError(f"member original path is required: {name}")

    try:
        with zipfile.ZipFile(io.BytesIO(bundle), mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("duplicate ZIP members")
            header_expanded_bytes = 0
            for info in infos:
                _validate_member_name(info.filename)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError(f"ZIP directories and links are not allowed: {info.filename}")
                header_expanded_bytes += info.file_size
                if info.file_size > MAX_MEMBER_EXPANDED_BYTES:
                    raise ValueError(f"publication ZIP member exceeds expanded size limit: {info.filename}")
                if header_expanded_bytes > MAX_BUNDLE_EXPANDED_BYTES:
                    raise ValueError("publication ZIP exceeds total expanded size limit")
            if set(names) != set(member_descriptors):
                raise ValueError("ZIP membership does not match publication manifest")
            by_name = {info.filename: info for info in infos}
            member_data = {name: _read_member(archive, by_name[name], descriptor) for name, descriptor in member_descriptors.items()}
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid publication ZIP") from exc

    run_manifest_bytes = member_data.get("outputs/manifest.json")
    if not run_manifest_bytes:
        raise ValueError("bundle lacks source run manifest")
    if _sha(run_manifest_bytes) != metadata.get("run_manifest_sha256"):
        raise ValueError("source run manifest hash mismatch")
    source_manifest = _json_object(run_manifest_bytes, "bundled source run manifest")
    artifacts, identities = _validate_source_manifest(source_manifest)
    expected = _expected_members(artifacts, identities)
    if set(member_descriptors) != set(expected):
        raise ValueError("publication members do not match required outputs and source identities")
    for member, original in expected.items():
        if member_descriptors[member]["original_path"] != original:
            raise ValueError(f"publication original path mismatch: {member}")
        if member == "outputs/manifest.json":
            expected_sha = _sha(run_manifest_bytes)
            expected_size = len(run_manifest_bytes)
        elif member.startswith("outputs/"):
            source_descriptor = artifacts[original]
            expected_sha = source_descriptor["sha256"]
            expected_size = source_descriptor["bytes"]
        else:
            expected_sha = identities[original]
            expected_size = member_descriptors[member]["bytes"]
        if member_descriptors[member]["sha256"] != expected_sha or member_descriptors[member]["bytes"] != expected_size:
            raise ValueError(f"publication descriptor does not match source identity: {member}")

    if metadata.get("source_code_commit") != source_manifest["code_commit"]:
        raise ValueError("publication source code commit mismatch")
    if metadata.get("scientific_cells") != SCIENTIFIC_CELLS:
        raise ValueError("publication scientific cell count mismatch")
    bulk_location = metadata.get("bulk_location")
    if not isinstance(bulk_location, str) or not (PureWindowsPath(bulk_location).is_absolute() or PurePosixPath(bulk_location).is_absolute()):
        raise ValueError("publication bulk location must be absolute")
    if metadata.get("bulk_location_availability") != "local_only" or metadata.get("bulk_location_verified") is not False:
        raise ValueError("publication must mark bulk location as local-only and unverified")

    summaries = _validate_summaries(_json_value(member_data["outputs/summaries.json"], "bundled summaries"))
    LOGGER.info("Verified HHHL v4 publication cells=%d at %s", len(summaries), root)
    return {"metadata": metadata, "summaries": summaries}


def verify_publication(root: Path) -> dict[str, Any]:
    """Verify a v1 publication or portable v2 transport without extracting files."""
    root = Path(root)
    publication_path = confined(root, PUBLICATION_NAME)
    transport_path = confined(root, PUBLICATION_ARCHIVE_NAME)
    has_plain_manifest = publication_path.is_file()
    has_transport_archive = transport_path.is_file()
    if has_plain_manifest and has_transport_archive:
        raise ValueError("publication root contains ambiguous v1 and v2 metadata")
    if has_plain_manifest:
        if publication_path.stat().st_size > MAX_TRANSPORT_METADATA_BYTES:
            raise ValueError(f"publication metadata exceeds {MAX_TRANSPORT_METADATA_BYTES} bytes")
        with publication_path.open("rb") as stream:
            metadata_bytes = stream.read(MAX_TRANSPORT_METADATA_BYTES + 1)
        if len(metadata_bytes) > MAX_TRANSPORT_METADATA_BYTES:
            raise ValueError(f"publication metadata exceeds {MAX_TRANSPORT_METADATA_BYTES} bytes")
        metadata = _json_object(metadata_bytes, "publication manifest")
        if "transport_schema" in metadata or "bundle_parts" in metadata:
            raise ValueError("v2 transport metadata must be stored in publication.zip")
        bundle_path = confined(root, BUNDLE_NAME)
        if not bundle_path.is_file() or bundle_path.is_symlink():
            raise ValueError("publication bundle is missing or not a regular file")
        bundle_bytes = _require_bytes(metadata.get("bundle_bytes"), "bundle")
        if bundle_bytes > MAX_BUNDLE_BYTES:
            raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
        if bundle_path.stat().st_size != bundle_bytes:
            raise ValueError("publication bundle hash/byte mismatch")
        with bundle_path.open("rb") as stream:
            bundle = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(bundle) > MAX_BUNDLE_BYTES:
            raise ValueError(f"publication bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    elif has_transport_archive:
        metadata = _read_transport_metadata(transport_path)
        bundle = _assemble_transport_bundle(root, metadata)
    else:
        raise ValueError("publication manifest is missing")
    return _verify_bundle(metadata, bundle, root)


def _query(
    summaries: list[dict[str, Any]],
    *,
    family: str | None = None,
    landmark: int | None = None,
    basis: str | None = None,
    horizon: int | None = None,
    sampling: str | None = None,
) -> list[dict[str, Any]]:
    return [
        row
        for row in summaries
        if (family is None or row.get("family") == family)
        and (landmark is None or row.get("landmark") == landmark)
        and (basis is None or row.get("basis") == basis)
        and (horizon is None or row.get("horizon") == horizon)
        and (sampling is None or row.get("sampling") == sampling)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", type=Path, help="completed local run directory to publish")
    mode.add_argument("--split-publication", type=Path, help="verified v1 publication directory to convert to transport v2")
    mode.add_argument("--publication", type=Path, help="publication directory to verify and query")
    parser.add_argument("--output", type=Path, help="new directory; required with --run or --split-publication")
    parser.add_argument("--family")
    parser.add_argument("--landmark", type=int)
    parser.add_argument("--basis")
    parser.add_argument("--horizon", type=int)
    parser.add_argument("--sampling")
    parser.add_argument("--noise-first-correction", type=Path, help="explicit four-cell overlay; original package remains unchanged")
    args = parser.parse_args(argv)

    try:
        result: Any
        if args.noise_first_correction is not None and args.publication is None:
            parser.error("--noise-first-correction requires --publication")
        if args.run is not None:
            if args.output is None:
                parser.error("--output is required with --run")
            if any(value is not None for value in (args.family, args.landmark, args.basis, args.horizon, args.sampling)):
                parser.error("summary filters require --publication")
            result = publish(args.run, args.output)
        elif args.split_publication is not None:
            if args.output is None:
                parser.error("--output is required with --split-publication")
            if any(value is not None for value in (args.family, args.landmark, args.basis, args.horizon, args.sampling)):
                parser.error("summary filters require --publication")
            result = convert_publication(args.split_publication, args.output)
        else:
            if args.output is not None:
                parser.error("--output is only valid with --run or --split-publication")
            verified = verify_publication(args.publication)
            if args.noise_first_correction is not None:
                from scripts.correct_hhhl_v4_noise_first import read_correction

                verified = read_correction(args.noise_first_correction, verified, args.publication)
            result = _query(
                verified["summaries"],
                family=args.family,
                landmark=args.landmark,
                basis=args.basis,
                horizon=args.horizon,
                sampling=args.sampling,
            )
            if (
                args.noise_first_correction is None
                and verified["metadata"]
                .get("source_code_commit", "")
                .startswith(
                    "70a6872037e9"  # pragma: allowlist secret - public original Git commit prefix, not a credential
                )
                and any(row["family"] == "noise" and row["sampling"] == "first_per_security" for row in result)
            ):
                raise ValueError("original noise-first cells are superseded; supply --noise-first-correction (see task data-contract)")
        sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        LOGGER.error("HHHL v4 publication failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
