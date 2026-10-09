"""Add a four-cell correction from saved noise rows; never rerun detection."""

from __future__ import annotations

import argparse
import io
import json
import logging
import math
import stat
import sys
import zipfile
import zlib
from numbers import Real
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.hhhl_v4_summary import BASES, HORIZONS, OUTCOME_FIELDS, _comparison_fields, _describe_v4, first_noise_per_security
from research_core.jobs import confined, file_digest
from scripts.publish_hhhl_v4_probability import _json_object, _json_value, _require_bytes, _require_sha, _sha, _validate_summaries
from scripts.supplement_hhhl_v4_diagnostics import _assert_file_identity, _json_bytes, _read_run_manifest, _validated_publication, _zip_bytes

LOGGER = logging.getLogger(__name__)
SCHEMA = "hhhl-v4-noise-first-correction.v2"
LEGACY_SCHEMA = "hhhl-v4-noise-first-correction.v1"
REASON = "Select the first eligible original breakout_date before evaluating its saved shifted outcome."
SELECTION_ALGORITHM = "first eligible original breakout_date per security; event_id breaks date ties; source row order is final tie-breaker"
PORTABLE_VERIFICATION = (
    "Recompute all four cells from bundled selected rows and validate selection against the bundled source index; "
    "embedded code is hash-checked, never executed. Source-byte provenance is the original run manifest hash and "
    "noise descriptor, not a proof against maliciously rewritten subsets."
)
MAX_COMPRESSED_BYTES = 4_000_000
MAX_EXPANDED_BYTES = 32_000_000
MAX_LEGACY_BYTES = 200_000
TRANSPORT_SCHEMA = "hhhl-v4-noise-first-correction-transport.v1"
TRANSPORT_NAME = "correction-transport.zip"
MAX_TRANSPORT_METADATA_BYTES = 65_536
CELL_NAME = "cells.json"
MANIFEST_NAME = "manifest.json"
SOURCE_NAME = "noise.parquet"
SELECTED_NAME = "selected-noise.parquet"
INDEX_NAME = "selection-index.parquet"
CODE_PREFIX = "code/"
CELL_KEYS = {(horizon, basis) for horizon in HORIZONS for basis in BASES}
INDEX_COLUMNS = ("security_id", "base_eligible", "anchor_date", "breakout_date", "year", "event_id")
NOISE_COLUMNS = (
    *INDEX_COLUMNS,
    *(f"{prefix}_{field}_{horizon}" for prefix in ("adjusted", "atlas") for field in OUTCOME_FIELDS for horizon in HORIZONS),
)
CODE_RELATIVE_PATHS = (
    "scripts/correct_hhhl_v4_noise_first.py",
    "research_core/hhhl_v4_summary.py",
    "research_core/hhhl_probability.py",
)
V2_MEMBERS = {
    MANIFEST_NAME,
    CELL_NAME,
    SELECTED_NAME,
    INDEX_NAME,
    *(f"{CODE_PREFIX}{path}" for path in CODE_RELATIVE_PATHS),
}


def _code_sources() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    return {
        "scripts/correct_hhhl_v4_noise_first.py": Path(__file__).resolve(),
        "research_core/hhhl_v4_summary.py": root / "research_core" / "hhhl_v4_summary.py",
        "research_core/hhhl_probability.py": root / "research_core" / "hhhl_probability.py",
    }


def _member_descriptor(data: bytes) -> dict[str, Any]:
    return {"sha256": _sha(data), "bytes": len(data)}


def _bounded_parquet_bytes(frame: pd.DataFrame, name: str) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    data = buffer.getvalue()
    if len(data) > MAX_EXPANDED_BYTES:
        raise ValueError(f"{name} exceeds the expanded data limit")
    return data


def original_cells(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify exactly the four affected cells, not any other noise sample."""
    if not isinstance(summaries, list) or any(not isinstance(row, dict) for row in summaries):
        raise ValueError("summary cells must be objects")
    cells = [row for row in summaries if row.get("family") == "noise" and row.get("sampling") == "first_per_security"]
    if (
        len(cells) != 4
        or {(row.get("horizon"), row.get("basis")) for row in cells} != CELL_KEYS
        or any(row.get("slice") != "pooled" or row.get("value") != "all" or "landmark" in row for row in cells)
    ):
        raise ValueError("exactly four original noise-first cells required")
    return cells


def recompute_cells(noise: pd.DataFrame, summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reuse saved labels and unchanged descriptive metrics for the fixed cells."""
    selected = first_noise_per_security(noise)
    corrected = []
    for old in original_cells(summaries):
        row = {**old, **_describe_v4(selected, old["horizon"], old["basis"])}
        row.update(_comparison_fields(row["rate"], old["all_day_base_rate"], old["no_event_control_rate"]))
        corrected.append(row)
    return corrected


def create_correction(run: Path, publication: Path, output: Path) -> dict[str, Any]:
    """Write a new byte-bound supplement outside the unchanged source run/package."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("correction output already exists")
    if not output.parent.is_dir():
        raise ValueError("correction output parent must exist")
    confined(output.parent, output.name)
    for root in (run.resolve(), publication.resolve()):
        if output.resolve() == root or root in output.resolve().parents:
            raise ValueError("correction must be outside original run and publication")
    code_sources = _code_sources()
    code_identity = {name: file_digest(path) for name, path in code_sources.items()}
    published, _, published_bytes, _ = _validated_publication(publication)
    manifest_bytes, manifest = _read_run_manifest(run, published, published_bytes)
    descriptor = manifest["artifacts"][SOURCE_NAME]
    source_path = confined(run, SOURCE_NAME)
    _assert_file_identity(source_path, descriptor["sha256"], descriptor["bytes"], SOURCE_NAME)
    noise = pd.read_parquet(source_path, columns=list(NOISE_COLUMNS)).loc[:, list(NOISE_COLUMNS)].reset_index(drop=True)
    if (
        len(noise) != manifest["counts"]["noise"]
        or noise["event_id"].isna().any()
        or noise["event_id"].duplicated().any()
        or not noise["event_id"].map(lambda value: isinstance(value, str) and bool(value)).all()
    ):
        raise ValueError("saved noise count or event identity mismatch")
    # The index is self-consistency evidence; source-byte provenance remains the run manifest's
    # noise.parquet hash and does not authenticate a maliciously rewritten partial subset.
    selection_index = noise.loc[:, list(INDEX_COLUMNS)].copy().reset_index(drop=True)
    first = first_noise_per_security(selection_index)
    selected_ids = sorted(first["event_id"].tolist())
    selected_id_set = set(selected_ids)
    selected = noise.loc[noise["event_id"].isin(selected_id_set), list(NOISE_COLUMNS)].copy().reset_index(drop=True)
    if (
        selected["event_id"].duplicated().any()
        or selected["event_id"].tolist() != selection_index.loc[selection_index["event_id"].isin(selected_id_set), "event_id"].tolist()
    ):
        raise ValueError("selected noise rows do not preserve original source order")
    # Obtain the already verified original summaries, without rereading prices.
    from scripts.publish_hhhl_v4_probability import verify_publication

    summaries = verify_publication(publication)["summaries"]
    old = original_cells(summaries)
    cells = recompute_cells(selected, summaries)
    cells_bytes = _json_bytes(cells)
    selected_bytes = _bounded_parquet_bytes(selected, SELECTED_NAME)
    index_bytes = _bounded_parquet_bytes(selection_index, INDEX_NAME)
    code_bytes = {f"{CODE_PREFIX}{name}": path.read_bytes() for name, path in code_sources.items()}
    if {name: _sha(data) for name, data in code_bytes.items()} != {f"{CODE_PREFIX}{name}": digest for name, digest in code_identity.items()}:
        raise ValueError("embedded correction code bytes changed during collection")
    members = {
        CELL_NAME: cells_bytes,
        SELECTED_NAME: selected_bytes,
        INDEX_NAME: index_bytes,
        **code_bytes,
    }
    metadata = {
        "schema_version": SCHEMA,
        "complete": True,
        "correction_reason": REASON,
        "selection_algorithm": SELECTION_ALGORITHM,
        "portable_verification": PORTABLE_VERIFICATION,
        "original_run_manifest_sha256": _sha(manifest_bytes),
        "original_bundle_sha256": published["bundle_sha256"],
        "original_cells_sha256": _sha(_json_bytes(old)),
        "source_noise": {"path": SOURCE_NAME, **descriptor},
        "source_noise_rows": len(noise),
        "selection_index_rows": len(selection_index),
        "selection_index_columns": list(selection_index.columns),
        "selection_index_dtypes": {name: str(dtype) for name, dtype in selection_index.dtypes.items()},
        "noise_columns": list(selected.columns),
        "noise_dtypes": {name: str(dtype) for name, dtype in selected.dtypes.items()},
        "selected_rows": len(selected),
        "selected_event_ids_sha256": _sha(_json_bytes(selected_ids)),
        "correction_code_identity": code_identity,
        "members": {name: _member_descriptor(data) for name, data in members.items()},
    }
    _assert_file_identity(source_path, descriptor["sha256"], descriptor["bytes"], SOURCE_NAME)
    _assert_file_identity(confined(run, "manifest.json"), _sha(manifest_bytes), len(manifest_bytes), "manifest.json")
    if {name: file_digest(path) for name, path in code_sources.items()} != code_identity:
        raise ValueError("correction code changed during execution")
    payloads = {MANIFEST_NAME: _json_bytes(metadata), **members}
    if sum(map(len, payloads.values())) > MAX_EXPANDED_BYTES:
        raise ValueError("correction archive exceeds expanded size limit")
    archive = _zip_bytes(payloads)
    if len(archive) > MAX_COMPRESSED_BYTES:
        raise ValueError("correction archive exceeds compressed size limit")
    with output.open("xb") as stream:
        stream.write(archive)
    LOGGER.info("Created four-cell noise correction selected=%d source=%d at %s", len(selected), len(noise), output)
    return metadata


def write_correction_transport(packet: Path, output: Path) -> dict[str, Any]:
    """Split unchanged packet bytes into bounded Git files; no statistics change."""
    from scripts.publish_hhhl_v4_probability import MAX_TRANSPORT_PART_BYTES

    if output.exists() or output.is_symlink():
        raise FileExistsError("correction transport output already exists")
    if not output.parent.is_dir() or not packet.is_file() or packet.is_symlink():
        raise ValueError("transport needs a regular packet and existing parent")
    if packet.stat().st_size > MAX_COMPRESSED_BYTES:
        raise ValueError("correction packet exceeds compressed size limit")
    with packet.open("rb") as stream:
        data = stream.read(MAX_COMPRESSED_BYTES + 1)
    if not data or len(data) > MAX_COMPRESSED_BYTES:
        raise ValueError("correction packet exceeds compressed size limit or is empty")
    parts = [data[start : start + MAX_TRANSPORT_PART_BYTES] for start in range(0, len(data), MAX_TRANSPORT_PART_BYTES)]
    metadata: dict[str, Any] = {
        "schema_version": TRANSPORT_SCHEMA,
        "bundle_bytes": len(data),
        "bundle_sha256": _sha(data),
        "bundle_parts": [{"path": f"correction.{index:03}.bin", **_member_descriptor(part)} for index, part in enumerate(parts, 1)],
    }
    output.mkdir()
    for descriptor, part in zip(metadata["bundle_parts"], parts, strict=True):
        with confined(output, descriptor["path"]).open("xb") as stream:
            stream.write(part)
    with confined(output, TRANSPORT_NAME).open("xb") as stream:
        stream.write(_zip_bytes({"publication.json": _json_bytes(metadata)}))
    return metadata


def _read_correction_bytes(path: Path) -> bytes:
    """Read a regular packet or assemble its byte-identical bounded transport."""
    if path.is_symlink():
        raise ValueError("correction path cannot be a link")
    if path.is_dir():
        from scripts.publish_hhhl_v4_probability import TRANSPORT_SCHEMA as PUBLICATION_TRANSPORT_SCHEMA
        from scripts.publish_hhhl_v4_probability import _assemble_transport_bundle, _read_transport_metadata

        metadata_path = confined(path, TRANSPORT_NAME)
        if not metadata_path.is_file() or metadata_path.is_symlink() or metadata_path.stat().st_size > MAX_TRANSPORT_METADATA_BYTES:
            raise ValueError("correction transport metadata is missing or exceeds limit")
        metadata = _read_transport_metadata(metadata_path)
        parts = metadata.get("bundle_parts")
        if (
            metadata.get("schema_version") != TRANSPORT_SCHEMA
            or _require_bytes(metadata.get("bundle_bytes"), "correction") > MAX_COMPRESSED_BYTES
            or not isinstance(parts, list)
            or not 1 <= len(parts) <= 10
            or any(not isinstance(part, dict) or part.get("path") != f"correction.{index:03}.bin" for index, part in enumerate(parts, 1))
        ):
            raise ValueError("invalid correction transport metadata")
        # Reuse the already tested confined/hash-verified 400 KB part assembler.
        return _assemble_transport_bundle(path, {**metadata, "transport_schema": PUBLICATION_TRANSPORT_SCHEMA})
    if not path.is_file() or path.stat().st_size > MAX_COMPRESSED_BYTES:
        raise ValueError("correction must be a bounded regular file or transport directory")
    with path.open("rb") as stream:
        data = stream.read(MAX_COMPRESSED_BYTES + 1)
    if len(data) > MAX_COMPRESSED_BYTES:
        raise ValueError("correction exceeds compressed size limit")
    return data


def read_correction(path: Path, verified: dict[str, Any], publication: Path) -> dict[str, Any]:
    """Apply a portable, fully recomputed v2 overlay to a verified publication."""
    data = _read_correction_bytes(path)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("correction ZIP contains duplicate members")
            legacy_names = {MANIFEST_NAME, CELL_NAME}
            if len(infos) == 2 and set(names) == legacy_names:
                if any(info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) for info in infos):
                    raise ValueError("legacy correction members cannot be links")
                if sum(info.file_size for info in infos) > MAX_LEGACY_BYTES:
                    raise ValueError("legacy correction exceeds its bounded size")
                manifest_info = next(info for info in infos if info.filename == MANIFEST_NAME)
                with archive.open(manifest_info) as member:
                    legacy_manifest = member.read(MAX_LEGACY_BYTES + 1)
                if len(legacy_manifest) != manifest_info.file_size or len(legacy_manifest) > MAX_LEGACY_BYTES:
                    raise ValueError("legacy correction manifest byte mismatch")
                legacy_metadata = _json_object(legacy_manifest, "legacy noise correction")
                if legacy_metadata.get("schema_version") == LEGACY_SCHEMA:
                    raise ValueError("legacy v1 correction is not accepted for current queries; create a portable v2 correction")
                raise ValueError("unsupported two-member noise correction archive")
            if set(names) != V2_MEMBERS:
                raise ValueError("v2 correction ZIP has an unexpected member set")
            total_uncompressed = 0
            for info in infos:
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError(f"correction ZIP directories and links are not allowed: {info.filename}")
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_EXPANDED_BYTES:
                    raise ValueError("correction ZIP exceeds expanded size limit")
            contents: dict[str, bytes] = {}
            for info in infos:
                try:
                    with archive.open(info) as member:
                        value = member.read(MAX_EXPANDED_BYTES + 1)
                except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
                    raise ValueError(f"cannot read correction ZIP member: {info.filename}") from exc
                if len(value) != info.file_size or len(value) > MAX_EXPANDED_BYTES:
                    raise ValueError(f"correction member byte mismatch: {info.filename}")
                contents[info.filename] = value
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ValueError("invalid noise correction ZIP") from exc

    metadata = _json_object(contents[MANIFEST_NAME], "noise correction")
    if metadata.get("schema_version") == LEGACY_SCHEMA:
        raise ValueError("legacy v1 correction is not accepted for current queries; create a portable v2 correction")
    if metadata.get("schema_version") != SCHEMA or metadata.get("complete") is not True or metadata.get("correction_reason") != REASON:
        raise ValueError("unsupported noise correction metadata")
    original = verified["summaries"]
    published = verified["metadata"]
    if published.get("transport_schema") != "hhhl-v4-probability-transport.v2":
        raise ValueError("noise correction requires the original v2 transport")
    member_descriptors = metadata.get("members")
    expected_members = V2_MEMBERS - {MANIFEST_NAME}
    if not isinstance(member_descriptors, dict) or set(member_descriptors) != expected_members:
        raise ValueError("correction member inventory has invalid paths")
    for name in expected_members:
        descriptor = member_descriptors[name]
        if not isinstance(descriptor, dict) or set(descriptor) != {"sha256", "bytes"}:
            raise ValueError(f"invalid correction member descriptor: {name}")
        if _require_sha(descriptor.get("sha256"), name) != _sha(contents[name]) or _require_bytes(descriptor.get("bytes"), name) != len(contents[name]):
            raise ValueError(f"correction member hash or bytes mismatch: {name}")

    code_identity = metadata.get("correction_code_identity")
    if not isinstance(code_identity, dict) or set(code_identity) != set(CODE_RELATIVE_PATHS):
        raise ValueError("correction code identity paths are invalid")
    for relative in CODE_RELATIVE_PATHS:
        embedded = contents[f"{CODE_PREFIX}{relative}"]
        digest = _require_sha(code_identity[relative], relative)
        if digest != _sha(embedded) or digest != member_descriptors[f"{CODE_PREFIX}{relative}"]["sha256"]:
            raise ValueError(f"embedded correction code identity mismatch: {relative}")

    old = original_cells(original)
    if (
        metadata.get("original_bundle_sha256") != published["bundle_sha256"]
        or metadata.get("original_run_manifest_sha256") != published["run_manifest_sha256"]
        or metadata.get("original_cells_sha256") != _sha(_json_bytes(old))
    ):
        raise ValueError("correction does not match original publication")
    _require_sha(metadata.get("original_run_manifest_sha256"), "original run manifest")
    _require_sha(metadata.get("original_cells_sha256"), "original cells")
    _require_sha(metadata.get("selected_event_ids_sha256"), "selected event IDs")

    # The source descriptor is cross-checked against the original bundled manifest.
    from scripts.publish_hhhl_v4_probability import _assemble_transport_bundle

    try:
        with zipfile.ZipFile(io.BytesIO(_assemble_transport_bundle(publication, published))) as archive:
            source_manifest_bytes = archive.read("outputs/manifest.json")
            source = _json_object(source_manifest_bytes, "original source manifest")
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ValueError("cannot read original source manifest from publication") from exc
    if (
        metadata.get("source_noise") != {"path": SOURCE_NAME, **source["artifacts"][SOURCE_NAME]}
        or metadata.get("source_noise_rows") != source["counts"]["noise"]
        or _sha(source_manifest_bytes) != metadata["original_run_manifest_sha256"]
    ):
        raise ValueError("correction noise provenance mismatch")

    if metadata.get("selection_algorithm") != SELECTION_ALGORITHM:
        raise ValueError("correction selection algorithm identity is unsupported")
    if metadata.get("portable_verification") != PORTABLE_VERIFICATION:
        raise ValueError("correction portable verification limits are missing")

    def count(value: Any, label: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"invalid correction row count: {label}")
        return value

    source_rows = count(metadata.get("source_noise_rows"), "source noise")
    selected_rows = count(metadata.get("selected_rows"), "selected noise")
    index_rows = count(metadata.get("selection_index_rows"), "selection index")
    if source_rows != source["counts"]["noise"] or index_rows != source_rows:
        raise ValueError("correction source row counts do not match the published noise source")
    if metadata.get("noise_columns") != list(NOISE_COLUMNS) or metadata.get("selection_index_columns") != list(INDEX_COLUMNS):
        raise ValueError("correction source columns are invalid")

    try:
        from research_core.bounded_parquet import read_evidence_parquet

        selected = read_evidence_parquet(contents[SELECTED_NAME], selected_rows, NOISE_COLUMNS)
        selection_index = read_evidence_parquet(contents[INDEX_NAME], index_rows, INDEX_COLUMNS)
    except Exception as exc:
        raise ValueError("cannot read bundled noise rows") from exc
    if (
        list(selected.columns) != list(NOISE_COLUMNS)
        or list(selection_index.columns) != list(INDEX_COLUMNS)
        or len(selected) != selected_rows
        or len(selection_index) != index_rows
        or not isinstance(selected.index, pd.RangeIndex)
        or selected.index.start != 0
        or selected.index.step != 1
        or selected.index.stop != len(selected)
        or not isinstance(selection_index.index, pd.RangeIndex)
        or selection_index.index.start != 0
        or selection_index.index.step != 1
        or selection_index.index.stop != len(selection_index)
    ):
        raise ValueError("bundled noise column, row, or index identity mismatch")
    selected_dtypes = {name: str(dtype) for name, dtype in selected.dtypes.items()}
    index_dtypes = {name: str(dtype) for name, dtype in selection_index.dtypes.items()}
    if selected_dtypes != metadata.get("noise_dtypes") or index_dtypes != metadata.get("selection_index_dtypes"):
        raise ValueError("bundled noise dtypes do not match their recorded identities")
    for frame in (selected, selection_index):
        for name in ("security_id", "event_id"):
            column = cast(pd.Series, frame[name])
            if column.isna().any() or not column.map(lambda value: isinstance(value, str) and bool(value)).all():
                raise ValueError(f"invalid bundled noise identity values: {name}")
        eligible_column = cast(pd.Series, frame["base_eligible"])
        if not pd.api.types.is_bool_dtype(eligible_column.dtype) or eligible_column.isna().any():
            raise ValueError("invalid bundled base eligibility dtype or values")
        if frame[["anchor_date", "breakout_date", "year"]].isna().to_numpy().any():
            raise ValueError("bundled noise selection index contains missing key values")
    index_event_ids = cast(pd.Series, selection_index["event_id"])
    selected_event_ids = cast(pd.Series, selected["event_id"])
    selected_eligible = cast(pd.Series, selected["base_eligible"])
    selected_security_ids = cast(pd.Series, selected["security_id"])
    if index_event_ids.duplicated().any() or selected_event_ids.duplicated().any():
        raise ValueError("bundled noise contains duplicate event IDs")
    if not pd.api.types.is_integer_dtype(selection_index["year"].dtype):
        raise ValueError("bundled noise year must have an integer dtype")
    for prefix in ("adjusted", "atlas"):
        for horizon in HORIZONS:
            label = cast(pd.Series, selected[f"{prefix}_label_{horizon}"])
            complete = cast(pd.Series, selected[f"{prefix}_complete_{horizon}"])
            reason = cast(pd.Series, selected[f"{prefix}_unknown_reason_{horizon}"]).dropna()
            if not label.dropna().isin([0, 1]).all() or not complete.dropna().isin([True, False]).all():
                raise ValueError("bundled noise outcomes have invalid labels or completion values")
            if not reason.map(lambda value: isinstance(value, str)).all():
                raise ValueError("bundled noise unknown reasons must be strings or null")
            for field in ("max_return", "min_return", "max_drawdown", "forward_return", "wait_to_threshold"):
                for value in selected[f"{prefix}_{field}_{horizon}"].dropna().tolist():
                    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                        raise ValueError(f"bundled noise outcome is not finite numeric data: {field}_{horizon}")

    first = first_noise_per_security(selection_index)
    selected_ids = sorted(first["event_id"].tolist())
    if _sha(_json_bytes(selected_ids)) != metadata["selected_event_ids_sha256"]:
        raise ValueError("selected event ID digest mismatch")
    selected_id_set = set(selected_ids)
    if (
        len(selected_ids) != selected_rows
        or not selected_eligible.eq(True).all()
        or selected_security_ids.duplicated().any()
        or selected_event_ids.tolist() != selection_index.loc[index_event_ids.isin(list(selected_id_set)), "event_id"].tolist()
    ):
        raise ValueError("selected noise rows do not match the earliest eligible source events")
    expected_index_rows = selection_index.loc[index_event_ids.isin(list(selected_id_set)), list(INDEX_COLUMNS)].reset_index(drop=True)
    selected_index_rows = selected.loc[:, list(INDEX_COLUMNS)].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(selected_index_rows, expected_index_rows, check_dtype=True, check_exact=True)
    except AssertionError as exc:
        raise ValueError("selected event rows do not match source selection-index fields") from exc

    corrected = _json_value(contents[CELL_NAME], CELL_NAME)
    if not isinstance(corrected, list) or len(corrected) != 4:
        raise ValueError("exactly four correction cells required")
    cells = original_cells(corrected)
    expected_cells = recompute_cells(selected, original)
    if cells != expected_cells:
        raise ValueError("correction cells do not match recomputation from bundled selected rows")
    by_key = {(row["horizon"], row["basis"]): row for row in cells}
    output = [
        by_key[(row["horizon"], row["basis"])] if row.get("family") == "noise" and row.get("sampling") == "first_per_security" else row for row in original
    ]
    return {"metadata": metadata, "summaries": _validate_summaries(output), "original_summaries": original}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = create_correction(args.run, args.publication, args.output)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        LOGGER.error("Noise correction incomplete: %s", exc)
        return 1
    sys.stdout.write(json.dumps({"complete": True, "selected_rows": result["selected_rows"], "corrected_cells": 4}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
