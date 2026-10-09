"""Read-only, projected access to a manifest-backed feature atlas dataset."""

from __future__ import annotations

import json
import logging
import re
import stat
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow.parquet as pq

from research_core.feature_atlas_io import digest_json
from research_core.jobs import confined, file_digest

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = "feature-discrimination-atlas.v1"
KEYS = ["security_id", "asof_date"]
FEATURE_COLUMNS = [f"F{i:02}" for i in range(1, 39)]
DEFAULT_COLUMNS = [*KEYS, *FEATURE_COLUMNS, "label_63", "label_126", "base_eligible", "year", "regime", "industry_ref", "calendar_index"]


def _manifest(root: Path, verify_hashes: bool) -> dict[str, Any]:
    for ancestor in (root.absolute(), *root.absolute().parents):
        attrs = getattr(ancestor.lstat(), "st_file_attributes", 0)
        if ancestor.is_symlink() or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError(f"linked/reparse root forbidden: {ancestor}")
    manifest = json.loads(confined(root, "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"manifest must use {SCHEMA_VERSION}")
    for key in ("dataset_id", "run_id"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"manifest requires {key}")
    identity = manifest.get("identity")
    if not isinstance(identity, dict) or not identity:
        raise ValueError("manifest requires nonempty identity object")
    if manifest["dataset_id"] != "fda-" + digest_json(identity):
        raise ValueError("dataset_id identity mismatch")
    tables, cross, artifacts = (manifest.get(key) for key in ("tables", "cross_section", "artifacts"))
    if not isinstance(tables, list) or not tables or not isinstance(cross, dict) or not isinstance(artifacts, list):
        raise ValueError("manifest requires tables, cross_section, and artifacts")
    seen: set[str] = set()
    securities: set[str] = set()
    for entry in tables:
        security = entry.get("security_id") if isinstance(entry, dict) else None
        if not isinstance(security, str) or not security or security in securities:
            raise ValueError("tables require unique security_id")
        securities.add(security)
    for entry in [*tables, cross, *artifacts]:
        if not isinstance(entry, dict):
            raise ValueError("manifest entries must be objects")
        relative = entry.get("path")
        if not isinstance(relative, str):
            raise ValueError("manifest path must be a string")
        path = confined(root, relative)
        canonical = relative.casefold()
        if canonical in seen:
            raise ValueError("duplicate manifest path")
        seen.add(canonical)
        sha = entry.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
            raise ValueError("invalid SHA256")
        if not path.is_file():
            raise ValueError(f"missing dataset file: {entry['path']}")
        if verify_hashes and file_digest(path) != sha:
            raise ValueError(f"SHA256 mismatch: {entry['path']}")
    for entry in [*tables, cross]:
        rows = entry.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError("parquet rows must be a nonnegative integer")
    return manifest


def _read(root: Path, entry: dict[str, Any], dataset_id: str, columns: list[str]) -> pd.DataFrame:
    path = confined(root, entry["path"])
    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows != entry["rows"]:
        raise ValueError(f"row count mismatch: {entry['path']}")
    metadata = parquet.schema_arrow.metadata or {}
    if b"dataset_id" in metadata and metadata[b"dataset_id"].decode("utf-8") != dataset_id:
        raise ValueError(f"dataset_id metadata mismatch: {entry['path']}")
    names = parquet.schema_arrow.names
    if any(key not in names for key in KEYS):
        raise ValueError(f"missing join keys: {entry['path']}")
    selected = list(dict.fromkeys([*KEYS, *[name for name in columns if name in names], *(["dataset_id"] if "dataset_id" in names else [])]))
    frame = parquet.read(columns=selected).to_pandas()
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError(f"missing or duplicate join keys: {entry['path']}")
    if not pd.api.types.is_datetime64_any_dtype(frame["asof_date"]):
        raise ValueError(f"asof_date must be a timestamp: {entry['path']}")
    if "security_id" in entry and not frame["security_id"].eq(entry["security_id"]).all():
        raise ValueError(f"security_id mismatch: {entry['path']}")
    if "dataset_id" in frame and not frame["dataset_id"].eq(dataset_id).all():
        raise ValueError(f"dataset_id column mismatch: {entry['path']}")
    return frame.drop(columns=["dataset_id"], errors="ignore") if "dataset_id" not in columns else frame


def _load(root: Path, columns: list[str], verify_hashes: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = _manifest(root, verify_hashes)
    tables = [_read(root, entry, manifest["dataset_id"], columns) for entry in manifest["tables"]]
    for table in tables:
        required = [name for name in columns if name not in {"F36", "F37", "F38", "rs20_percentile", "rs60_percentile", "relative_ret60_0050"}]
        if any(name not in table for name in required):
            raise ValueError("missing requested table columns")
    base = pd.concat(tables, ignore_index=True)
    if base.duplicated(KEYS).any():
        raise ValueError("duplicate table join keys")
    cross = _read(root, manifest["cross_section"], manifest["dataset_id"], columns)
    # Outer key validation detects both absent cross rows and extra cross rows.
    keys = cast(pd.DataFrame, base[KEYS]).merge(cast(pd.DataFrame, cross[KEYS]), on=KEYS, how="outer", validate="one_to_one", indicator=True)
    if not cast(pd.Series, keys["_merge"]).eq("both").all():
        raise ValueError("table and cross_section join keys do not match")
    overlap = (set(base.columns) & set(cross.columns)) - set(KEYS)
    if overlap:
        raise ValueError(f"overlapping table and cross_section columns: {sorted(overlap)}")
    joined = base.merge(cross, on=KEYS, how="inner", validate="one_to_one", sort=False)
    if any(name not in joined for name in columns):
        raise ValueError("missing requested dataset columns")
    LOGGER.debug("Loaded atlas dataset=%s tables=%d rows=%d", manifest["dataset_id"], len(tables), len(joined))
    return cast(pd.DataFrame, joined[columns]), manifest


def load_analysis(root: Path, columns: list[str] | None = None, verify_hashes: bool = True) -> pd.DataFrame:
    """Load comparison columns by default; custom projections retain join keys.

    Hash verification covers every listed file, including JSON artifacts.
    Disabling hashes never disables identity, path, row-count, metadata, or key checks.
    """
    selected = list(dict.fromkeys([*KEYS, *(DEFAULT_COLUMNS if columns is None else columns)]))
    return _load(root, selected, verify_hashes)[0]


def verify_dataset(root: Path) -> dict[str, Any]:
    """Validate all declared hashes, parquet row counts, identities and joins."""
    frame, manifest = _load(root, KEYS, True)
    return {
        "dataset_id": manifest["dataset_id"],
        "run_id": manifest["run_id"],
        "tables": len(manifest["tables"]),
        "table_rows": len(frame),
        "cross_section_rows": manifest["cross_section"]["rows"],
        "joined_rows": len(frame),
        "artifacts": len(manifest["artifacts"]),
        "verified_files": len(manifest["tables"]) + 1 + len(manifest["artifacts"]),
    }
