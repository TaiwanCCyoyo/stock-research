"""Pinned discovery of shared research versions; payload readers retain authority."""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import canonical, file_digest, object_digest, publish_new_directory, read_json, relative_name, verify_files, write_json
from research_core.research_data_paths import DataRoots

LOGGER = logging.getLogger(__name__)
SCHEMA = "research-data-catalog.v1"
DIGEST = re.compile(r"[0-9a-f]{64}")
READERS = {"market_context", "derived_cache", "feature_block", "bundle", "metadata_only"}
KINDS = {"universe", "prices", "pivots", "features", "patterns", "labels", "market", "episodes"}
CATALOG_FIELDS = {"data_id", "kind", "definition_version", "parameters", "inputs", "coverage", "status", "limitations", "backup"}


def validate_entry(entry: dict[str, Any], roots: DataRoots) -> dict[str, Any]:
    """Validate discovery metadata without interpreting research observations."""
    entry = read_detached(entry)
    if set(entry) != CATALOG_FIELDS | {"version_id", "reader", "manifest"}:
        raise ValueError("catalog entry must contain only discovery metadata and a manifest pin")
    for field in ("data_id", "version_id", "definition_version"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            raise ValueError(f"nonempty {field} required")
        relative_name(entry[field])
    if entry.get("kind") not in KINDS or entry.get("reader") not in READERS or entry.get("status") not in {"complete", "partial", "legacy"}:
        raise ValueError("unsupported catalog kind, reader or status")
    for field in ("parameters", "inputs", "coverage", "backup"):
        if not isinstance(entry.get(field), dict) or not entry[field]:
            raise ValueError(f"nonempty {field} metadata required")
    coverage = entry["coverage"]
    if not isinstance(coverage.get("scope"), str) or not coverage["scope"]:
        raise ValueError("declared coverage scope required")
    for field in ("raw_input_period", "valid_indicator_period", "complete_label_period"):
        value = coverage.get(field)
        if not isinstance(value, dict) or set(value) != {"start", "end", "reason"}:
            raise ValueError(f"explicit coverage.{field} required")
        if value["start"] is None or value["end"] is None:
            if not isinstance(value["reason"], str) or not value["reason"]:
                raise ValueError("unknown/not-applicable period requires a reason")
        else:
            from datetime import date

            if date.fromisoformat(value["start"]) > date.fromisoformat(value["end"]):
                raise ValueError("reversed coverage period")
    if not isinstance(entry.get("limitations"), list) or any(not isinstance(x, str) for x in entry["limitations"]):
        raise ValueError("limitations list required")
    location = entry.get("manifest")
    if not isinstance(location, dict) or set(location) != {"scope", "path", "sha256"} or not DIGEST.fullmatch(str(location["sha256"])):
        raise ValueError("explicit external manifest pin required")
    roots.artifact_path(location["scope"], location["path"])
    return entry


def read_detached(value: dict[str, Any]) -> dict[str, Any]:
    import json

    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return json.loads(canonical(value))


def render_readme(catalog: dict[str, Any]) -> str:
    lines = [
        "# Shared research data",
        "",
        f"Catalog snapshot: `{catalog['version_id']}`",
        "",
        "Generated from catalog.json. Pin an explicit data/version and manifest SHA256; discovery is not validity certification.",
        "",
        "| Data | Version | Status | Scope | Input period | Manifest |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in catalog["entries"]:
        period = row["coverage"]["raw_input_period"]
        cells = [
            row["data_id"],
            row["version_id"],
            row["status"],
            row["coverage"]["scope"],
            f"{period['start']}..{period['end']}",
            f"{row['manifest']['scope']}:{row['manifest']['path']}",
        ]
        lines.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in cells) + " |")
    return "\n".join(lines) + "\n"


class DataCatalog:
    """Single-writer additive catalog with immutable discovery snapshots."""

    def __init__(self, roots: DataRoots):
        self.roots = roots

    def read(self, snapshot: str | None = None) -> dict[str, Any]:
        if snapshot is None:
            pointer = read_json(self.roots.artifact_path("data", "catalog.json"))
            if pointer.get("schema") != "research-data-index.v1":
                raise ValueError("unsupported catalog index")
            snapshot = pointer["snapshot"]
        if not isinstance(snapshot, str) or not DIGEST.fullmatch(snapshot):
            raise ValueError("explicit catalog snapshot digest required")
        path = self.roots.artifact_path("data", f"catalog-snapshots/{snapshot}/catalog.json")
        catalog = read_json(path, max_bytes=64_000_000)
        body = {key: value for key, value in catalog.items() if key != "version_id"}
        if catalog.get("schema") != SCHEMA or catalog.get("version_id") != snapshot or object_digest(body) != snapshot:
            raise ValueError("catalog snapshot identity mismatch")
        entries = [validate_entry(row, self.roots) for row in catalog["entries"]]
        keys = [(row["data_id"], row["version_id"]) for row in entries]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate catalog version")
        return catalog

    def register(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Register verified existing locations, never move or re-pin old records."""
        additions = [validate_entry(row, self.roots) for row in entries]
        for row in additions:
            verify_entry(row, self.roots)
        self.roots.data.mkdir(parents=True, exist_ok=True)
        lock = self.roots.artifact_path("data", ".catalog.lock")
        token = {"pid": os.getpid(), "token": uuid.uuid4().hex}
        write_json(lock, token)
        succeeded = False
        try:
            rows = self.read()["entries"] if self.roots.artifact_path("data", "catalog.json").exists() else []
            by_key = {(row["data_id"], row["version_id"]): row for row in rows}
            for row in additions:
                key = (row["data_id"], row["version_id"])
                if key in by_key and by_key[key] != row:
                    raise ValueError("catalog version already registered with different metadata")
                by_key[key] = row
            body: dict[str, Any] = {"schema": SCHEMA, "entries": [by_key[key] for key in sorted(by_key)]}
            catalog: dict[str, Any] = {**body, "version_id": object_digest(body)}
            target = self.roots.artifact_path("data", f"catalog-snapshots/{catalog['version_id']}")
            if not target.exists():
                publish_new_directory(target, {"catalog.json": canonical(catalog), "README.md": render_readme(catalog).encode()})
            self.read(catalog["version_id"])
            # Only mutable discovery views are replaced. Dataset versions are immutable.
            for name, payload in (
                ("README.md", render_readme(catalog).encode()),
                ("catalog.json", canonical({"schema": "research-data-index.v1", "snapshot": catalog["version_id"]})),
            ):
                staging = self.roots.artifact_path("data", f".catalog-{uuid.uuid4().hex}.partial")
                with staging.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(staging, self.roots.artifact_path("data", name))
            succeeded = True
            LOGGER.info("Registered shared catalog snapshot=%s entries=%d", catalog["version_id"], len(catalog["entries"]))
            return catalog
        finally:
            if succeeded and read_json(lock) == token:
                lock.unlink()

    def get(
        self, data_id: str, version_id: str, *, manifest_sha256: str, expected_inputs: dict[str, Any] | None = None, definition_version: str | None = None
    ) -> dict[str, Any]:
        """No latest, missing-version fallback, or calculation on a read path."""
        return self.get_verified(data_id, version_id, manifest_sha256=manifest_sha256, expected_inputs=expected_inputs, definition_version=definition_version)[
            0
        ]

    def get_verified(
        self, data_id: str, version_id: str, *, manifest_sha256: str, expected_inputs: dict[str, Any] | None = None, definition_version: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """`get`, plus the reader result of the one verification it ran.

        A caller that needs the verified manifest uses this instead of `get` followed by
        another `verify_entry`, which would read and hash every member a second time.
        """
        rows = [row for row in self.read()["entries"] if (row["data_id"], row["version_id"]) == (data_id, version_id)]
        if len(rows) != 1:
            raise KeyError(f"shared version missing: {data_id}/{version_id}")
        row = rows[0]
        if (
            row["manifest"]["sha256"] != manifest_sha256
            or (expected_inputs is not None and row["inputs"] != expected_inputs)
            or (definition_version is not None and row["definition_version"] != definition_version)
        ):
            raise ValueError("requested shared version identity mismatch")
        return row, verify_entry(row, self.roots)


def verify_entry(entry: dict[str, Any], roots: DataRoots) -> dict[str, Any]:
    entry = validate_entry(entry, roots)
    ref = entry["manifest"]
    path = roots.artifact_path(ref["scope"], ref["path"])
    if file_digest(path) != ref["sha256"]:
        raise ValueError("catalog external manifest pin mismatch")

    # Specialized readers predate the no-hardlink contract. Check every member
    # before delegating; safe_path alone only detects reparse/symlink aliases.
    def walk_error(error: OSError) -> None:
        raise error

    for directory, directories, files in os.walk(path.parent, followlinks=False, onerror=walk_error):
        for name in (*directories, *files):
            member = Path(directory) / name
            roots.artifact_path(ref["scope"], member.relative_to(roots.data if ref["scope"] == "data" else roots.primary).as_posix())
    reader = entry["reader"]
    if reader == "market_context":
        from research_core.market_context_artifact import read_dataset

        result = read_dataset(path.parent)
    elif reader == "derived_cache":
        from research_core.derived_cache import verify_cache

        result = verify_cache(path.parent)
    elif reader == "feature_block":
        from research_core.feature_block_store_v1 import verify_block

        result = verify_block(path.parent)
    else:
        result = read_json(path, max_bytes=64_000_000)
        if reader == "bundle":
            if result.get("schema") != "research-data-bundle.v1" or result.get("complete") is not True:
                raise ValueError("incomplete shared bundle")
            stored_metadata = {key: value for key, value in entry.items() if key in CATALOG_FIELDS}
            declared_metadata = result.get("metadata")
            if (
                not isinstance(declared_metadata, dict)
                or {key: declared_metadata.get(key) for key in CATALOG_FIELDS} != stored_metadata
                or object_digest(result) != entry["version_id"]
            ):
                raise ValueError("catalog/bundle identity metadata mismatch")
            verify_files(path.parent, result["artifacts"])
    if reader in {"market_context", "derived_cache", "feature_block"}:
        sealed = read_json(path)
        if reader == "market_context":
            source_inputs = {key: sealed[key] for key in ("series_id", "calendar_id", "source_manifest_sha256")}
            if (
                entry["version_id"] != sealed["dataset_id"].removeprefix("sha256:")
                or entry["definition_version"] != sealed["definition_version"]
                or entry["inputs"] != source_inputs
            ):
                raise ValueError("catalog/market-context identity mismatch")
        elif reader == "derived_cache":
            if (
                entry["version_id"] != sealed["version_id"]
                or entry["definition_version"] != sealed["identity"]["definitions"]["prices"]
                or entry["inputs"] != sealed["identity"]["inputs"]
            ):
                raise ValueError("catalog/cache identity mismatch")
        elif (
            entry["version_id"] != sealed["version_id"]
            or entry["definition_version"] != sealed["identity"]["definition"]["version"]
            or entry["inputs"] != sealed["identity"]["inputs"]
        ):
            raise ValueError("catalog/feature identity mismatch")
    if file_digest(path) != ref["sha256"]:
        raise ValueError("shared manifest changed during verification")
    return result


def read_market_context(catalog: DataCatalog, version_id: str, manifest_sha256: str, *, layer: str) -> list[dict[str, Any]]:
    from research_core.market_context_artifact import load_context_rows

    row = catalog.get("market-context", version_id, manifest_sha256=manifest_sha256)
    if row["reader"] != "market_context":
        raise ValueError("market context reader required")
    path = catalog.roots.artifact_path(row["manifest"]["scope"], row["manifest"]["path"])
    result = load_context_rows(path.parent, layer=layer)
    verify_entry(row, catalog.roots)
    return result
