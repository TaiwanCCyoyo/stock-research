"""Verified, portable queries of the fixed HHHL variants summary publication."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.artifact_store import file_digest, read_json, relative_name, safe_path, verify_files

LOGGER = logging.getLogger(__name__)
CHUNK_BYTES = 480 * 1024
REQUIRED_COLUMNS = frozenset(
    "row_kind candidate_id cohort_id split_id horizon landmark riskset_id "
    "feature_price_basis calendar_full_n hit_n loss_n flat_win_n unknown_n "
    "censored_n known_security_n flag_unknown_n not_applicable_reason".split()
)


def summary_transport(data: bytes, rows: int) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Package one unchanged logical parquet into Git-sized binary chunks."""
    if not data or isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValueError("nonempty summary bytes and nonnegative row count required")
    contents = {f"summary.parquet.part-{index:05d}.bin": data[offset : offset + CHUNK_BYTES] for index, offset in enumerate(range(0, len(data), CHUNK_BYTES))}
    descriptor = {
        "path": "summary.parquet",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": rows,
        "transport": "binary-chunks.v1",
        "chunks": [{"path": name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()} for name, chunk in contents.items()],
    }
    return contents, descriptor


def _summary_bytes(root: Path, descriptor: dict[str, Any]) -> bytes:
    relative_name(descriptor["path"])
    size, digest = descriptor.get("bytes"), descriptor.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0 or not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("invalid logical summary descriptor")
    if "transport" not in descriptor and "chunks" not in descriptor:
        verify_files(root, [descriptor])
        data = safe_path(root / descriptor["path"]).read_bytes()
        verify_files(root, [descriptor])
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("read summary hash/size mismatch")
        return data
    if descriptor.get("transport") != "binary-chunks.v1":
        raise ValueError("unsupported summary transport")
    chunks = descriptor.get("chunks")
    if not isinstance(chunks, list) or not chunks or any(not isinstance(entry, dict) for entry in chunks):
        raise ValueError("ordered summary chunks required")
    for index, entry in enumerate(chunks):
        if entry.get("path") != f"summary.parquet.part-{index:05d}.bin":
            raise ValueError("summary chunk path/order mismatch")
        size = entry.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= CHUNK_BYTES:
            raise ValueError("summary chunk exceeds transport size limit")
    verify_files(root, chunks)
    data = b"".join(safe_path(root / entry["path"]).read_bytes() for entry in chunks)
    verify_files(root, chunks)
    if len(data) != descriptor.get("bytes") or hashlib.sha256(data).hexdigest() != descriptor.get("sha256"):
        raise ValueError("reconstructed summary hash/size mismatch")
    return data


def load_summary(publication: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Verify the receipt's summary bytes and schema without local dataset access."""
    root = safe_path(publication)
    receipt = read_json(root / "receipt.json")
    if receipt.get("schema_version") != "hhhl-variants-publication.v1":
        raise ValueError("unsupported HHHL variants publication schema")
    if not isinstance(receipt.get("dataset_id"), str) or not receipt["dataset_id"]:
        raise ValueError("publication dataset_id must be a nonempty string")
    descriptor = receipt.get("summary")
    if not isinstance(descriptor, dict):
        raise ValueError("publication summary descriptor required")
    if not isinstance(descriptor.get("path"), str):
        raise ValueError("summary descriptor path required")
    rows = descriptor.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValueError("summary rows must be a nonnegative integer")
    data = _summary_bytes(root, descriptor)
    frame = pd.read_parquet(io.BytesIO(data))
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"summary missing required columns: {sorted(missing)}")
    if not frame.columns.is_unique:
        raise ValueError("summary duplicate columns")
    if len(frame) != rows:
        raise ValueError(f"summary row count mismatch: expected {rows}, observed {len(frame)}")
    LOGGER.info("Verified HHHL variants summary: dataset=%s rows=%s", receipt["dataset_id"], rows)
    return frame, receipt


def filter_summary(
    frame: pd.DataFrame,
    *,
    row_kind: str | None = None,
    cohort: str | None = None,
    split: str | None = None,
    horizon: int | None = None,
    candidate: str | None = None,
    feature: str | None = None,
    bin_id: str | None = None,
    flag: str | None = None,
    landmark: int | None = None,
    riskset: str | None = None,
    year: int | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Apply exact filters, retaining publication order and original denominators."""
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("limit must be a nonnegative integer")
    filters = {
        "row_kind": row_kind,
        "cohort_id": cohort,
        "split_id": split,
        "horizon": horizon,
        "candidate_id": candidate,
        "feature_id": feature,
        "bin_id": bin_id,
        "flag_id": flag,
        "landmark": landmark,
        "riskset_id": riskset,
        "year": year,
    }
    result = frame
    for column, value in filters.items():
        if value is not None:
            if column not in frame.columns:
                raise ValueError(f"summary lacks filter column: {column}")
            result = result.loc[result[column].eq(value).fillna(False)]
    return result.head(limit).copy() if limit is not None else result.copy()


def summary_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Serialize missing/nonfinite values as null, never fabricate a zero rate."""
    encoded = frame.to_json(orient="records", date_format="iso", double_precision=15)
    if encoded is None:
        raise ValueError("summary serialization returned no JSON")
    return cast(list[dict[str, Any]], json.loads(encoded))


def load_event(publication: Path, event_id: str, part: str = "observations") -> pd.DataFrame:
    """Query declared local event shards, pinned by the portable publication receipt."""
    if part not in {"observations", "flags"}:
        raise ValueError("event queries support observations or flags only")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("nonempty event_id required")
    _, receipt = load_summary(publication)
    local = receipt.get("local_dataset")
    if not isinstance(local, dict) or not isinstance(local.get("path"), str):
        raise ValueError("publication lacks local dataset location")
    root = Path(local["path"])
    if not root.is_absolute():
        raise ValueError("local dataset location must be an absolute path")
    root = safe_path(root)
    manifest_path = safe_path(root / "manifest.json")
    expected = local.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("local dataset manifest pin required")
    if file_digest(manifest_path) != expected:
        raise ValueError("local dataset manifest hash mismatch")
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != "hhhl-variants-dataset.v1" or manifest.get("dataset_id") != receipt["dataset_id"]:
        raise ValueError("local dataset schema or identity mismatch")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        raise ValueError("local dataset artifacts list required")
    match = re.fullmatch(r"hhhl_rule_v4:TW:([^:]+):\d{4}-\d{2}-\d{2}", event_id)
    code = match.group(1) if match else None
    selected = []
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("invalid local artifact descriptor")
        name = relative_name(entry["path"])
        if name in names:
            raise ValueError(f"duplicate local artifact: {name}")
        names.add(name)
        shard_code = entry.get("code")
        if shard_code is not None and not isinstance(shard_code, str):
            raise ValueError("artifact code must preserve the original string code")
        if name.startswith(f"{part}/") and name.endswith(".parquet") and (code is None or shard_code is None or code == shard_code):
            selected.append(entry)
    if not selected:
        raise ValueError(f"no declared {part} shards for event: {event_id}")
    verify_files(root, selected)
    matches = []
    for entry in selected:
        path = safe_path(root / entry["path"])
        keys = pd.read_parquet(path, columns=["event_id"])
        rows = entry.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0 or len(keys) != rows:
            raise ValueError(f"local shard row count mismatch: {entry['path']}")
        if cast(pd.Series, keys["event_id"]).eq(event_id).to_numpy(dtype=bool).any():
            found = pd.read_parquet(path, filters=[("event_id", "==", event_id)])
            if code is not None and "code" in found.columns and not cast(pd.Series, found["code"]).eq(code).to_numpy(dtype=bool).all():
                raise ValueError("event code mismatch")
            matches.append(found)
    verify_files(root, selected)
    if file_digest(manifest_path) != expected:
        raise ValueError("local dataset manifest changed during query")
    if not matches:
        raise ValueError(f"event not found in {part}: {event_id}")
    result = pd.concat(matches, ignore_index=True)
    LOGGER.info("Verified local HHHL event query: part=%s rows=%s", part, len(result))
    return result
