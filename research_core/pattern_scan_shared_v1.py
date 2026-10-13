"""Pinned catalog-backed inputs for analysis, without copies or fallback."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from research_core.artifact_store import canonical, object_digest, read_json
from research_core.pattern_scan_barrier_v1 import FIELDS
from research_core.pattern_scan_execution_v1 import verify_source
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DataRoots

LOGGER = logging.getLogger(__name__)
SIDE_CARS = {"close_matrix": "prices", "jump_matrix": "prices", "context": "market", "benchmark": "market"}


@dataclass(frozen=True)
class SharedInputs:
    roots: DataRoots
    codes: tuple[str, ...]
    _entries: tuple[tuple[str, bytes], ...]
    _expected_inputs: bytes
    _stocks: Mapping[tuple[str, str], Path]
    _globals: Mapping[str, Path]
    _sidecars: Mapping[str, Path]

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        """Detached catalog records; callers cannot mutate the pinned originals."""
        return {kind: json.loads(payload) for kind, payload in self._entries}

    @property
    def pins(self) -> dict[str, dict[str, str]]:
        return {
            kind: {"data_id": entry["data_id"], "version_id": entry["version_id"], "manifest_sha256": entry["manifest"]["sha256"]}
            for kind, entry in self.entries.items()
        }

    def stock(self, code: str, name: str) -> Path:
        try:
            return self._stocks[code, name]
        except KeyError as error:
            raise ValueError("unknown fixed stock/table") from error

    def global_values(self, code: str) -> Path:
        try:
            return self._globals[code]
        except KeyError as error:
            raise ValueError("unknown fixed global stock") from error

    def sidecar(self, name: str) -> Path:
        try:
            return self._sidecars[name]
        except KeyError as error:
            raise ValueError("unknown fixed shared sidecar") from error

    def validate_scope(self, codes: Sequence[str], source: dict[str, Any], input_id: str) -> None:
        expected = {"fixed_input_id": input_id, "source_id": source["source_id"], "runtime": source["runtime"]}
        if tuple(sorted(codes)) != self.codes or canonical(expected) != self._expected_inputs:
            raise ValueError("shared stock/source/input scope differs")

    def verify(self) -> None:
        catalog = DataCatalog(self.roots)
        for kind, entry in self.entries.items():
            current = catalog.get(
                entry["data_id"],
                entry["version_id"],
                manifest_sha256=entry["manifest"]["sha256"],
                expected_inputs=json.loads(self._expected_inputs),
                definition_version="pattern-scan.v1",
            )
            if current != entry:
                raise ValueError(f"fixed shared entry changed: {kind}")
        LOGGER.debug("Verified seven fixed shared versions for %d stocks", len(self.codes))


def load_shared(roots: DataRoots, entries: dict[str, dict[str, Any]], codes: Sequence[str], source: dict[str, Any], input_id: str) -> SharedInputs:
    """Resolve exact published versions; missing or corrupt inputs stop the read."""
    verify_source(source)
    kinds = {*FIELDS, "market"}
    supplied_codes = tuple(codes)
    if (
        set(entries) != kinds
        or not supplied_codes
        or any(not isinstance(code, str) or not code.strip() for code in supplied_codes)
        or len(set(supplied_codes)) != len(supplied_codes)
    ):
        raise ValueError("seven fixed entries and unique nonblank stock codes required")
    fixed_codes = tuple(sorted(supplied_codes))
    expected_inputs = {"fixed_input_id": input_id, "source_id": source["source_id"], "runtime": source["runtime"]}
    catalog = DataCatalog(roots)
    stock_paths: dict[tuple[str, str], Path] = {}
    globals_paths: dict[str, Path] = {}
    side_paths: dict[str, Path] = {}
    fixed_entries: list[tuple[str, bytes]] = []
    for kind in sorted(kinds):
        requested = entries[kind]
        entry = catalog.get(
            requested["data_id"],
            requested["version_id"],
            manifest_sha256=requested["manifest"]["sha256"],
            expected_inputs=expected_inputs,
            definition_version="pattern-scan.v1",
        )
        if (
            entry != requested
            or entry["kind"] != kind
            or entry["reader"] != "bundle"
            or entry["status"] != "complete"
            or entry["data_id"] != f"pattern-scan-full-2010-v1-{kind}"
        ):
            raise ValueError("shared entry does not match approved published scope")
        manifest = entry["manifest"]
        parent = Path(manifest["path"]).parent.as_posix()
        body = read_json(roots.artifact_path(manifest["scope"], manifest["path"]), max_bytes=64_000_000)
        names = [record["path"] for record in body["artifacts"]]
        expected_names: set[str] = set()
        for code in fixed_codes:
            for field in FIELDS.get(kind, ()):
                name = f"stocks/{object_digest(code)}/{field}.parquet"
                expected_names.add(name)
                stock_paths[code, field] = roots.artifact_path(manifest["scope"], f"{parent}/{name}")
            if kind == "features":
                name = f"stocks/{object_digest(code)}/global_values.parquet"
                expected_names.add(name)
                globals_paths[code] = roots.artifact_path(manifest["scope"], f"{parent}/{name}")
        for field, owner in SIDE_CARS.items():
            if owner == kind:
                name = f"{field}.parquet"
                expected_names.add(name)
                side_paths[field] = roots.artifact_path(manifest["scope"], f"{parent}/{name}")
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise ValueError(f"incomplete or mismatched shared table inventory: {kind}")
        fixed_entries.append((kind, canonical(entry)))
    verify_source(source)
    return SharedInputs(
        roots,
        fixed_codes,
        tuple(fixed_entries),
        canonical(expected_inputs),
        MappingProxyType(stock_paths),
        MappingProxyType(globals_paths),
        MappingProxyType(side_paths),
    )
