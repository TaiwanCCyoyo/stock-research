"""Publish and verify a small reason-preserving supplement to a v4 publication."""

from __future__ import annotations

import argparse
import io
import json
import logging
import stat
import sys
import zipfile
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pandas as pd

from research_core.hhhl_v4_summary import _missing_key, landmark_census
from research_core.jobs import confined, file_digest
from scripts.publish_hhhl_v4_probability import (
    TRANSPORT_SCHEMA,
    _assemble_transport_bundle,
    _json_object,
    _json_value,
    _require_bytes,
    _require_sha,
    _sha,
    _validate_member_name,
    _validate_source_manifest,
    _zip_bytes,
    verify_publication,
)

LOGGER = logging.getLogger(__name__)
SUPPLEMENT_SCHEMA = "hhhl-v4-diagnostics-supplement.v2"
HELPER_CODE_ARTIFACT = "code/research_core/hhhl_v4_summary.py"
SCRIPT_CODE_ARTIFACT = "code/scripts/supplement_hhhl_v4_diagnostics.py"
SUPPLEMENT_ARTIFACT = "reason-census.json"
SOURCE_PROJECTION_ARTIFACT = "landmarks.parquet"
MANIFEST_NAME = "manifest.json"
MAX_SUPPLEMENT_COMPRESSED_BYTES = 4_000_000
MAX_SUPPLEMENT_EXPANDED_BYTES = 32_000_000
MAX_SOURCE_MANIFEST_BYTES = 20_000_000
LANDMARK_COLUMNS = ("security_id", "landmark", "base_eligible", "status", "reason")
LANDMARK_PATH = "landmarks.parquet"
LEGACY_LANDMARKS = (10, 20, 40)
LEGACY_STATUSES = ("active", "early_hit", "early_failed", "unknown")
CORRECTION_REASON = (
    "Preserve the existing landmark status/L/eligibility census while adding reason-level counts, "
    "including missing_before_landmark and window_end as distinct unknown reasons."
)
PORTABLE_VERIFICATION_NOTE = (
    "The bundled five-column landmark projection is hash-bound to this supplement and its source identity is "
    "bound to the published run manifest. Portable recomputation proves internal consistency, not authenticity "
    "against a maliciously rewritten source projection; independently verify the original landmarks.parquet hash."
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _identity_digest(identities: dict[str, str], suffix: str) -> str:
    matches = []
    for original, digest in identities.items():
        normalized = original.replace("\\", "/")
        is_absolute = Path(original).is_absolute() or PurePosixPath(original).is_absolute() or PureWindowsPath(original).is_absolute()
        if is_absolute and normalized.endswith(suffix):
            matches.append(digest)
    if len(matches) != 1:
        raise ValueError(f"source identity must contain one absolute {suffix} path")
    return matches[0]


def _validated_publication(publication_root: Path) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    verified = verify_publication(publication_root)
    metadata = verified["metadata"]
    if metadata.get("transport_schema") != TRANSPORT_SCHEMA:
        raise ValueError("diagnostics supplement requires an existing v2 publication")
    bundle = _assemble_transport_bundle(publication_root, metadata)
    try:
        with zipfile.ZipFile(io.BytesIO(bundle), mode="r") as archive:
            source_manifest = archive.read("outputs/manifest.json")
            diagnostics = archive.read("outputs/diagnostics.json")
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ValueError("v2 publication lacks verified manifest or diagnostics bytes") from exc
    if _sha(source_manifest) != metadata.get("run_manifest_sha256"):
        raise ValueError("publication source manifest hash mismatch")
    manifest = _json_object(source_manifest, "published source manifest")
    artifacts, _ = _validate_source_manifest(manifest)
    diagnostic_descriptor = artifacts.get("diagnostics.json")
    if diagnostic_descriptor is None or len(diagnostics) != diagnostic_descriptor["bytes"] or _sha(diagnostics) != diagnostic_descriptor["sha256"]:
        raise ValueError("published diagnostics do not match source artifact identity")
    return metadata, manifest, source_manifest, diagnostics


def _read_run_manifest(run: Path, publication_metadata: dict[str, Any], published_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    path = confined(run, "manifest.json")
    if not path.is_file() or path.is_symlink():
        raise ValueError("completed run manifest is missing or not a regular file")
    size_before = path.stat().st_size
    if size_before > MAX_SOURCE_MANIFEST_BYTES:
        raise ValueError("completed run manifest exceeds the source manifest size limit")
    sha_before = file_digest(path)
    if sha_before != publication_metadata.get("run_manifest_sha256"):
        raise ValueError("run manifest does not match the saved publication")
    with path.open("rb") as stream:
        data = stream.read(MAX_SOURCE_MANIFEST_BYTES + 1)
    if len(data) > MAX_SOURCE_MANIFEST_BYTES or len(data) != size_before or _sha(data) != sha_before:
        raise ValueError("run manifest changed while being read")
    if file_digest(path) != sha_before or data != published_bytes:
        raise ValueError("run manifest changed or differs from the published identity")
    return data, _json_object(data, "completed run manifest")


def _source_artifact(manifest: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], int]:
    descriptor = artifacts.get(LANDMARK_PATH)
    if descriptor is None:
        raise ValueError(f"source run manifest lacks {LANDMARK_PATH}")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("source run manifest counts are required")
    row_count = counts.get("landmarks")
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
        raise ValueError("source run manifest counts.landmarks must be a nonnegative integer")
    return descriptor, row_count


def _assert_file_identity(path: Path, expected_sha: str, expected_bytes: int, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"source file is missing or not a regular file: {label}")
    if path.stat().st_size != expected_bytes or file_digest(path) != expected_sha:
        raise ValueError(f"source file hash/byte mismatch: {label}")


def _legacy_census(diagnostics: dict[str, Any]) -> dict[tuple[int, str, bool], dict[str, int]]:
    raw = diagnostics.get("landmark_census")
    if not isinstance(raw, list):
        raise ValueError("published diagnostics lack the legacy landmark_census")
    expected_keys = {(landmark, status, eligible) for landmark in LEGACY_LANDMARKS for status in LEGACY_STATUSES for eligible in (True, False)}
    result: dict[tuple[int, str, bool], dict[str, int]] = {}
    for index, row in enumerate(raw):
        if not isinstance(row, dict) or set(row) != {"landmark", "status", "eligible", "events", "securities"}:
            raise ValueError(f"legacy landmark census row {index} has an invalid shape")
        landmark, status, eligible = row["landmark"], row["status"], row["eligible"]
        if not isinstance(landmark, int) or isinstance(landmark, bool) or not isinstance(status, str) or not isinstance(eligible, bool):
            raise ValueError(f"legacy landmark census row {index} has invalid key types")
        key = (landmark, status, eligible)
        if key not in expected_keys or key in result:
            raise ValueError(f"legacy landmark census row {index} has an invalid or duplicate key")
        counts: dict[str, int] = {}
        for field in ("events", "securities"):
            value = row[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"legacy landmark census {field} must be a nonnegative integer")
            counts[field] = value
        result[key] = counts
    if set(result) != expected_keys:
        raise ValueError("legacy landmark census does not contain its fixed 3x4x2 grid")
    return result


def _verify_census_totals(
    census: list[dict[str, Any]],
    legacy: dict[tuple[int, str, bool], dict[str, int]],
    source: pd.DataFrame,
    expected_rows: int,
) -> None:
    _verify_reason_event_cells(census, legacy)
    if sum(row["rows"] for row in census) != expected_rows or len(source) != expected_rows:
        raise ValueError("reason census, source landmarks, and manifest landmark count disagree")

    for key, expected in legacy.items():
        landmark, status, eligible = key
        subset = source.loc[
            source["landmark"].eq(landmark) & source["status"].map(_missing_key).eq(status) & source["base_eligible"].eq(eligible).fillna(False)
        ]
        if len(subset) != expected["events"] or int(subset["security_id"].nunique()) != expected["securities"]:
            raise ValueError(f"source landmarks do not reconstruct legacy census totals for {key}")


def _serialize_landmark_projection(landmarks: pd.DataFrame) -> tuple[bytes, dict[str, Any]]:
    if tuple(landmarks.columns) != LANDMARK_COLUMNS:
        raise ValueError("landmark source projection columns do not match the fixed five-column schema")
    buffer = io.BytesIO()
    landmarks.to_parquet(buffer, index=False)
    data = buffer.getvalue()
    # Verify the exact stored representation that a portable reader will consume.
    round_trip = pd.read_parquet(io.BytesIO(data))
    if tuple(round_trip.columns) != LANDMARK_COLUMNS or len(round_trip) != len(landmarks):
        raise ValueError("serialized landmark source projection changed its row or column identity")
    if not round_trip.equals(landmarks.reset_index(drop=True)):
        raise ValueError("serialized landmark source projection changed its values")
    identity = {
        "rows": len(round_trip),
        "columns": list(LANDMARK_COLUMNS),
        "dtypes": {column: str(round_trip[column].dtype) for column in LANDMARK_COLUMNS},
    }
    return data, identity


def _read_landmark_projection(data: bytes, expected_rows: int, identity: Any) -> pd.DataFrame:
    if not isinstance(identity, dict) or set(identity) != {"rows", "columns", "dtypes"}:
        raise ValueError("supplement landmark projection identity has an invalid shape")
    rows = identity["rows"]
    columns = identity["columns"]
    dtypes = identity["dtypes"]
    if not isinstance(rows, int) or isinstance(rows, bool) or rows != expected_rows:
        raise ValueError("supplement landmark projection row identity does not match source manifest")
    if columns != list(LANDMARK_COLUMNS):
        raise ValueError("supplement landmark projection columns do not match the fixed five-column schema")
    if not isinstance(dtypes, dict) or set(dtypes) != set(LANDMARK_COLUMNS) or any(not isinstance(value, str) for value in dtypes.values()):
        raise ValueError("supplement landmark projection dtype identity has an invalid shape")
    try:
        from research_core.bounded_parquet import read_evidence_parquet

        frame = read_evidence_parquet(data, expected_rows, LANDMARK_COLUMNS)
    except Exception as exc:
        raise ValueError("supplement landmark projection is not readable Parquet") from exc
    if tuple(frame.columns) != LANDMARK_COLUMNS or len(frame) != expected_rows:
        raise ValueError("supplement landmark projection rows or columns do not match its identity")
    actual_dtypes = {column: str(frame[column].dtype) for column in LANDMARK_COLUMNS}
    if actual_dtypes != dtypes:
        raise ValueError("supplement landmark projection dtypes do not match its identity")
    return frame


def _verify_reason_event_cells(census: list[dict[str, Any]], legacy: dict[tuple[int, str, bool], dict[str, int]]) -> None:
    reason_totals: Counter[tuple[int, str, bool]] = Counter()
    for index, row in enumerate(census):
        eligibility = row.get("eligibility")
        if not isinstance(eligibility, str) or eligibility not in {"eligible", "ineligible"}:
            raise ValueError(f"reason census row {index} has an invalid eligibility label")
        eligible = eligibility == "eligible"
        landmark, status = row.get("landmark"), row.get("status")
        if not isinstance(landmark, int) or isinstance(landmark, bool) or not isinstance(status, str):
            raise ValueError(f"reason census row {index} has invalid key types")
        key = (landmark, status, eligible)
        if key not in legacy:
            raise ValueError(f"reason census row {index} has an invalid L/status/eligibility key")
        rows = row.get("rows")
        if not isinstance(rows, int) or isinstance(rows, bool) or rows <= 0:
            raise ValueError(f"reason census row {index} has an invalid row count")
        reason_totals[key] += rows
    for key, expected in legacy.items():
        if reason_totals[key] != expected["events"]:
            raise ValueError(f"reason census does not reconstruct legacy event total for {key}")


def create_supplement(run: Path, publication_root: Path, output: Path) -> dict[str, Any]:
    """Build a byte-bound reason census supplement without modifying the source run."""
    run = Path(run)
    publication_root = Path(publication_root)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"supplement output already exists: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"supplement output parent directory must exist: {output.parent}")
    confined(output.parent, output.name)
    output_absolute = output.resolve()
    for source_root in (run.resolve(), publication_root.resolve()):
        if output_absolute == source_root or source_root in output_absolute.parents:
            raise ValueError("supplement output must be outside source run and publication")

    publication_metadata, published_manifest, published_manifest_bytes, published_diagnostics_bytes = _validated_publication(publication_root)
    run_manifest_bytes, manifest = _read_run_manifest(run, publication_metadata, published_manifest_bytes)
    artifacts, identities = _validate_source_manifest(manifest)
    landmark_descriptor, manifest_row_count = _source_artifact(manifest, artifacts)
    landmark_sha = _require_sha(landmark_descriptor.get("sha256"), LANDMARK_PATH)
    landmark_bytes = _require_bytes(landmark_descriptor.get("bytes"), LANDMARK_PATH)
    legacy_diagnostics = _json_object(published_diagnostics_bytes, "published diagnostics")
    legacy = _legacy_census(legacy_diagnostics)

    landmark_path = confined(run, LANDMARK_PATH)
    _assert_file_identity(landmark_path, landmark_sha, landmark_bytes, LANDMARK_PATH)
    landmarks = pd.read_parquet(landmark_path, columns=list(LANDMARK_COLUMNS))
    _assert_file_identity(landmark_path, landmark_sha, landmark_bytes, LANDMARK_PATH)
    census = landmark_census(landmarks)
    _verify_census_totals(census, legacy, landmarks, manifest_row_count)
    projection_bytes, projection_identity = _serialize_landmark_projection(landmarks)

    summary_helper_path = Path(__file__).resolve().parents[1] / "research_core" / "hhhl_v4_summary.py"
    summary_helper_sha = file_digest(summary_helper_path)
    summary_identity_sha = _identity_digest(identities, "research_core/hhhl_v4_summary.py")
    producer_sha = _identity_digest(identities, "scripts/build_hhhl_v4_probability.py")
    supplement_sha = file_digest(Path(__file__).resolve())
    helper_code = summary_helper_path.read_bytes()
    script_code = Path(__file__).read_bytes()
    if _sha(helper_code) != summary_helper_sha or _sha(script_code) != supplement_sha:
        raise ValueError("supplement code changed while being captured")

    census_bytes = _json_bytes(census)
    if len(census_bytes) + len(projection_bytes) >= MAX_SUPPLEMENT_EXPANDED_BYTES:
        raise ValueError(f"diagnostics supplement contents must be smaller than {MAX_SUPPLEMENT_EXPANDED_BYTES} bytes")
    metadata: dict[str, Any] = {
        "schema_version": SUPPLEMENT_SCHEMA,
        "complete": True,
        "original_run_manifest_sha256": _sha(run_manifest_bytes),
        "original_bundle_sha256": publication_metadata["bundle_sha256"],
        "source_landmark_path": LANDMARK_PATH,
        "source_landmark_sha256": landmark_sha,
        "source_landmark_bytes": landmark_bytes,
        "producer_code_sha256": producer_sha,
        "supplement_script_sha256": supplement_sha,
        "summary_helper_sha256": summary_helper_sha,
        "source_summary_helper_sha256": summary_identity_sha,
        "correction_reason": CORRECTION_REASON,
        "portable_verification_note": PORTABLE_VERIFICATION_NOTE,
        "landmark_projection": projection_identity,
        "artifacts": {
            SUPPLEMENT_ARTIFACT: {"sha256": _sha(census_bytes), "bytes": len(census_bytes)},
            SOURCE_PROJECTION_ARTIFACT: {"sha256": _sha(projection_bytes), "bytes": len(projection_bytes)},
            HELPER_CODE_ARTIFACT: {"sha256": summary_helper_sha, "bytes": len(helper_code)},
            SCRIPT_CODE_ARTIFACT: {"sha256": supplement_sha, "bytes": len(script_code)},
        },
    }
    _assert_file_identity(confined(run, "manifest.json"), _sha(run_manifest_bytes), len(run_manifest_bytes), "manifest.json")
    _assert_file_identity(landmark_path, landmark_sha, landmark_bytes, LANDMARK_PATH)
    archive_bytes = _zip_bytes({
        SUPPLEMENT_ARTIFACT: census_bytes,
        SOURCE_PROJECTION_ARTIFACT: projection_bytes,
        HELPER_CODE_ARTIFACT: helper_code,
        SCRIPT_CODE_ARTIFACT: script_code,
        MANIFEST_NAME: _json_bytes(metadata),
    })
    if len(archive_bytes) >= MAX_SUPPLEMENT_COMPRESSED_BYTES:
        raise ValueError(f"diagnostics supplement must be smaller than {MAX_SUPPLEMENT_COMPRESSED_BYTES} bytes")
    with output.open("xb") as stream:
        stream.write(archive_bytes)
    LOGGER.info("Created HHHL v4 diagnostics supplement landmark_rows=%d census_rows=%d at %s", len(landmarks), len(census), output)
    return metadata


def _read_supplement_archive(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("diagnostics supplement is missing or not a regular file")
    if path.stat().st_size >= MAX_SUPPLEMENT_COMPRESSED_BYTES:
        raise ValueError(f"diagnostics supplement must be smaller than {MAX_SUPPLEMENT_COMPRESSED_BYTES} bytes")
    with path.open("rb") as stream:
        archive_bytes = stream.read(MAX_SUPPLEMENT_COMPRESSED_BYTES)
    if len(archive_bytes) >= MAX_SUPPLEMENT_COMPRESSED_BYTES:
        raise ValueError(f"diagnostics supplement must be smaller than {MAX_SUPPLEMENT_COMPRESSED_BYTES} bytes")

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            required = {MANIFEST_NAME, SUPPLEMENT_ARTIFACT, SOURCE_PROJECTION_ARTIFACT, HELPER_CODE_ARTIFACT, SCRIPT_CODE_ARTIFACT}
            if len(names) != len(set(names)):
                raise ValueError("supplement ZIP contains duplicate member names")
            if set(names) == {MANIFEST_NAME, SUPPLEMENT_ARTIFACT}:
                raise ValueError("legacy v1 diagnostics supplement lacks source rows and cannot verify current reason cells")
            if set(names) != required:
                raise ValueError("v2 supplement ZIP must contain manifest, reason census, source rows and two code snapshots")
            contents: dict[str, bytes] = {}
            total_uncompressed = 0
            for info in infos:
                _validate_member_name(info.filename)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError(f"supplement ZIP directories and links are not allowed: {info.filename}")
                if info.file_size >= MAX_SUPPLEMENT_EXPANDED_BYTES:
                    raise ValueError("supplement ZIP member exceeds the size limit")
                total_uncompressed += info.file_size
                if total_uncompressed >= MAX_SUPPLEMENT_EXPANDED_BYTES:
                    raise ValueError("supplement ZIP contents exceed the size limit")
                with archive.open(info, "r") as member:
                    data = member.read(MAX_SUPPLEMENT_EXPANDED_BYTES)
                if len(data) != info.file_size or len(data) >= MAX_SUPPLEMENT_EXPANDED_BYTES:
                    raise ValueError(f"supplement ZIP member byte count mismatch: {info.filename}")
                contents[info.filename] = data
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ValueError("invalid diagnostics supplement ZIP") from exc
    metadata = _json_object(contents[MANIFEST_NAME], "supplement manifest")
    return metadata, contents


def _validate_reason_census(value: Any, expected_total: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("reason census must be a JSON array")
    seen: set[tuple[Any, ...]] = set()
    total = 0
    for index, row in enumerate(value):
        required = {"landmark", "eligibility", "status", "reason", "rows", "securities"}
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError(f"reason census row {index} has an invalid shape")
        landmark = row["landmark"]
        if not isinstance(landmark, int) or isinstance(landmark, bool) or landmark not in LEGACY_LANDMARKS:
            raise ValueError(f"reason census row {index} has an invalid landmark")
        if (
            not isinstance(row["eligibility"], str)
            or row["eligibility"] not in {"eligible", "ineligible"}
            or not isinstance(row["status"], str)
            or row["status"] not in {*LEGACY_STATUSES, "(missing)"}
        ):
            raise ValueError(f"reason census row {index} has an invalid eligibility or status")
        if not isinstance(row["reason"], str):
            raise ValueError(f"reason census row {index} has an invalid reason")
        rows = row["rows"]
        if not isinstance(rows, int) or isinstance(rows, bool) or rows <= 0:
            raise ValueError(f"reason census row {index} has an invalid row count")
        securities = row["securities"]
        if securities is not None and (not isinstance(securities, int) or isinstance(securities, bool) or securities < 0):
            raise ValueError(f"reason census row {index} has an invalid security count")
        key = (landmark, row["eligibility"], row["status"], row["reason"])
        if key in seen:
            raise ValueError(f"duplicate reason census key at row {index}")
        seen.add(key)
        total += rows
    if total != expected_total:
        raise ValueError("reason census total does not match source manifest landmarks count")
    return value


def verify_supplement(path: Path, publication_root: Path) -> dict[str, Any]:
    """Verify a portable supplement against its existing v2 publication, without extraction."""
    metadata, contents = _read_supplement_archive(Path(path))
    publication_metadata, manifest, _, diagnostics_bytes = _validated_publication(Path(publication_root))
    if metadata.get("schema_version") != SUPPLEMENT_SCHEMA or metadata.get("complete") is not True:
        raise ValueError("diagnostics supplement must be complete hhhl-v4-diagnostics-supplement.v2")
    artifacts = metadata.get("artifacts")
    expected_artifacts = {SUPPLEMENT_ARTIFACT, SOURCE_PROJECTION_ARTIFACT, HELPER_CODE_ARTIFACT, SCRIPT_CODE_ARTIFACT}
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        raise ValueError("supplement artifact map must list reason census, source rows and code snapshots")
    for name in sorted(expected_artifacts):
        descriptor = artifacts[name]
        if not isinstance(descriptor, dict):
            raise ValueError(f"invalid supplement artifact descriptor: {name}")
        data = contents[name]
        if len(data) != _require_bytes(descriptor.get("bytes"), name):
            raise ValueError(f"supplement artifact byte count mismatch: {name}")
        if _sha(data) != _require_sha(descriptor.get("sha256"), name):
            raise ValueError(f"supplement artifact hash mismatch: {name}")

    if metadata.get("original_run_manifest_sha256") != publication_metadata.get("run_manifest_sha256"):
        raise ValueError("supplement run manifest identity does not match publication")
    if metadata.get("original_bundle_sha256") != publication_metadata.get("bundle_sha256"):
        raise ValueError("supplement bundle identity does not match publication")
    source_artifacts, source_identity = _validate_source_manifest(manifest)
    landmark_descriptor, row_count = _source_artifact(manifest, source_artifacts)
    if metadata.get("source_landmark_path") != LANDMARK_PATH:
        raise ValueError("supplement source landmark path mismatch")
    if _require_sha(metadata.get("source_landmark_sha256"), LANDMARK_PATH) != landmark_descriptor["sha256"]:
        raise ValueError("supplement source landmark hash does not match publication identity")
    if _require_bytes(metadata.get("source_landmark_bytes"), LANDMARK_PATH) != landmark_descriptor["bytes"]:
        raise ValueError("supplement source landmark byte count does not match publication identity")
    if metadata.get("producer_code_sha256") != _identity_digest(source_identity, "scripts/build_hhhl_v4_probability.py"):
        raise ValueError("supplement producer code identity does not match publication")
    if metadata.get("source_summary_helper_sha256") != _identity_digest(source_identity, "research_core/hhhl_v4_summary.py"):
        raise ValueError("supplement original summary helper identity does not match publication")
    if _require_sha(metadata.get("summary_helper_sha256"), "supplement helper") != _sha(contents[HELPER_CODE_ARTIFACT]):
        raise ValueError("supplement helper snapshot identity mismatch")
    if _require_sha(metadata.get("supplement_script_sha256"), "supplement script") != _sha(contents[SCRIPT_CODE_ARTIFACT]):
        raise ValueError("supplement script snapshot identity mismatch")
    if metadata.get("correction_reason") != CORRECTION_REASON:
        raise ValueError("supplement correction reason mismatch")
    if metadata.get("portable_verification_note") != PORTABLE_VERIFICATION_NOTE:
        raise ValueError("supplement portability limitation note mismatch")

    source_rows = _read_landmark_projection(contents[SOURCE_PROJECTION_ARTIFACT], row_count, metadata.get("landmark_projection"))
    census = _validate_reason_census(_json_value(contents[SUPPLEMENT_ARTIFACT], SUPPLEMENT_ARTIFACT), row_count)
    legacy = _legacy_census(_json_object(diagnostics_bytes, "published diagnostics"))
    recomputed_census = landmark_census(source_rows)
    _verify_census_totals(recomputed_census, legacy, source_rows, row_count)
    if census != recomputed_census:
        raise ValueError("reason census does not exactly match recomputed landmark source rows")
    LOGGER.info("Verified HHHL v4 diagnostics supplement rows=%d", sum(row["rows"] for row in census))
    return {"metadata": metadata, "census": census}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="completed v4 run directory")
    parser.add_argument("--publication", type=Path, required=True, help="existing verified v2 publication directory")
    parser.add_argument("--output", type=Path, required=True, help="new supplement ZIP path")
    args = parser.parse_args(argv)
    try:
        metadata = create_supplement(args.run, args.publication, args.output)
        sys.stdout.write(json.dumps(metadata, ensure_ascii=False, allow_nan=False) + "\n")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        LOGGER.error("HHHL v4 diagnostics supplement failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
