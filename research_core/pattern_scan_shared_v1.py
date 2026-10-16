"""Pinned catalog-backed inputs for analysis, without copies or fallback."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from research_core.artifact_store import canonical, object_digest
from research_core.pattern_scan_barrier_v1 import FIELDS
from research_core.pattern_scan_execution_v1 import verify_source
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DataRoots
from research_core.research_measurement_v1 import phase_receipt, resource_sample

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
    _catalog: DataCatalog = dataclass_field(repr=False, compare=False)
    _manifests: tuple[tuple[str, bytes], ...] = dataclass_field(repr=False)
    _descriptors: Mapping[Path, tuple[str, str, int, str]] = dataclass_field(repr=False)
    _measurements: dict[str, dict[str, Any]] = dataclass_field(default_factory=dict, repr=False, compare=False)

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

    @property
    def consumption_measurements(self) -> list[dict[str, Any]]:
        """Detached bounded per-table/process phase totals, not phase peak RSS."""
        return json.loads(canonical([self._measurements[name] for name in sorted(self._measurements)]))

    def _measure(self, table: str, phase: str, before: dict[str, Any], after: dict[str, Any]) -> None:
        receipt = phase_receipt(phase, before, after)
        aggregate = self._measurements.setdefault(
            table, {"table": table, "scope": "this process, consumed bytes; wall/CPU only", "read_n": 0, "consumed_bytes": 0, "phases": {}}
        )
        totals = aggregate["phases"].setdefault(phase, {"count": 0, "wall_seconds": 0.0, "cpu_seconds": 0.0})
        totals["count"] += 1
        totals["wall_seconds"] += receipt["wall_seconds"]
        totals["cpu_seconds"] += receipt["cpu_seconds"]

    def _read(self, path: Path, table: str, **kwargs: Any) -> pd.DataFrame:
        scope, name, expected_size, expected_digest = self._descriptors[path]
        before = resource_sample()
        guarded = self.roots.artifact_path(scope, name)
        self._measure(table, "path_checks", before, resource_sample())
        if guarded != path:
            raise ValueError("shared consumed path differs from fixed descriptor")
        before = resource_sample()
        with guarded.open("rb") as stream:
            payload = stream.read(expected_size + 1)
        self._measure(table, "disk_read", before, resource_sample())
        self._measurements[table]["read_n"] += 1
        self._measurements[table]["consumed_bytes"] += len(payload)
        if len(payload) != expected_size:
            LOGGER.warning("Shared consumed size differs table=%s expected=%d actual=%d", table, expected_size, len(payload))
            raise ValueError("shared consumed byte size differs from pinned descriptor")
        before = resource_sample()
        actual_digest = hashlib.sha256(payload).hexdigest()
        self._measure(table, "sha", before, resource_sample())
        if actual_digest != expected_digest:
            LOGGER.warning("Shared consumed digest differs table=%s path=%s", table, path)
            raise ValueError("shared consumed bytes digest differs from pinned descriptor")
        before = resource_sample()
        try:
            result = read_frame(BytesIO(payload), **kwargs)
        finally:
            self._measure(table, "decode", before, resource_sample())
        LOGGER.debug("Consumed verified shared table=%s bytes=%d rows=%d", table, len(payload), len(result))
        return result

    def read_stock(self, code: str, name: str, **kwargs: Any) -> pd.DataFrame:
        return self._read(self.stock(code, name), f"stock:{name}", **kwargs)

    def read_global(self, code: str, **kwargs: Any) -> pd.DataFrame:
        return self._read(self.global_values(code), "global_values", **kwargs)

    def read_sidecar(self, name: str, **kwargs: Any) -> pd.DataFrame:
        return self._read(self.sidecar(name), f"sidecar:{name}", **kwargs)

    def validate_scope(self, codes: Sequence[str], source: dict[str, Any], input_id: str) -> None:
        expected = {"fixed_input_id": input_id, "source_id": source["source_id"], "runtime": source["runtime"]}
        if tuple(sorted(codes)) != self.codes or canonical(expected) != self._expected_inputs:
            raise ValueError("shared stock/source/input scope differs")

    def verify(self) -> None:
        for kind, entry in self.entries.items():
            current, _ = self._catalog.get_verified(
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
    fixed_manifests: list[tuple[str, bytes]] = []
    descriptors: dict[Path, tuple[str, str, int, str]] = {}
    for kind in sorted(kinds):
        requested = entries[kind]
        entry, body = catalog.get_verified(
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
        names = [record["path"] for record in body["artifacts"]]
        for record in body["artifacts"]:
            name = f"{parent}/{record['path']}"
            path = roots.artifact_path(manifest["scope"], name)
            descriptors[path] = (manifest["scope"], name, record["bytes"], record["sha256"])
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
        fixed_manifests.append((kind, canonical(body)))
    verify_source(source)
    return SharedInputs(
        roots,
        fixed_codes,
        tuple(fixed_entries),
        canonical(expected_inputs),
        MappingProxyType(stock_paths),
        MappingProxyType(globals_paths),
        MappingProxyType(side_paths),
        catalog,
        tuple(fixed_manifests),
        MappingProxyType(descriptors),
    )
