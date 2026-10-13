"""Invented catalog-backed table paths; no market observations are loaded."""

import copy
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_shared_v1 as module
from research_core.artifact_store import object_digest
from research_core.pattern_scan_barrier_v1 import FIELDS, metadata
from research_core.pattern_scan_shared_v1 import SIDE_CARS, load_shared
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_file_bundle_v1 import publish_file_bundle
from research_core.research_data_paths import DataRoots


@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[DataRoots, dict[str, dict[str, Any]], dict[str, Any]]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    catalog = DataCatalog(roots)
    source = {"source_id": "synthetic-source", "runtime": {"fixture": "no research"}}
    monkeypatch.setattr(module, "verify_source", lambda value: None)
    payload = tmp_path / "invented.bin"
    payload.write_bytes(b"synthetic table placeholder; readers validate parquet schema")
    entries: dict[str, dict[str, Any]] = {}
    for kind in (*FIELDS, "market"):
        files = {f"stocks/{object_digest(code)}/{field}.parquet": payload for code in ("0050", "2330") for field in FIELDS.get(kind, ())}
        if kind == "features":
            files.update({f"stocks/{object_digest(code)}/global_values.parquet": payload for code in ("0050", "2330")})
        files.update({f"{field}.parquet": payload for field, owner in SIDE_CARS.items() if owner == kind})
        entries[kind] = publish_file_bundle(catalog, metadata(kind, source, "invented-input", pd.date_range("2010-01-04", periods=2)), files)
    return roots, entries, source


def test_two_callers_resolve_one_physical_pinned_copy(published: tuple[DataRoots, dict[str, dict[str, Any]], dict[str, Any]]) -> None:
    roots, entries, source = published
    first = load_shared(roots, entries, ("0050", "2330"), source, "invented-input")
    second = load_shared(roots, entries, ("2330", "0050"), source, "invented-input")
    for code in first.codes:
        for fields in FIELDS.values():
            for field in fields:
                assert first.stock(code, field) == second.stock(code, field)
                assert os.path.samefile(first.stock(code, field), second.stock(code, field))
                assert first.stock(code, field).stat().st_nlink == 1
                assert first.stock(code, field).is_relative_to(roots.primary / "research_cache")
        assert first.global_values(code) == second.global_values(code)
    for name in SIDE_CARS:
        assert first.sidecar(name) == second.sidecar(name)
    first.verify()
    assert first.pins == second.pins and len(first.pins) == 7
    detached = first.entries
    detached["labels"]["version_id"] = "changed"
    assert first.entries == entries
    with pytest.raises(FrozenInstanceError):
        setattr(first, "codes", ())


def test_corruption_stops_existing_and_new_reader(published: tuple[DataRoots, dict[str, dict[str, Any]], dict[str, Any]]) -> None:
    roots, entries, source = published
    shared = load_shared(roots, entries, ("0050", "2330"), source, "invented-input")
    path = shared.stock("0050", "prices")
    path.chmod(path.stat().st_mode | stat.S_IWRITE)
    path.write_bytes(b"corrupt invented payload")
    with pytest.raises(ValueError):
        shared.verify()
    with pytest.raises(ValueError):
        load_shared(roots, entries, ("0050", "2330"), source, "invented-input")


def test_absent_explicit_version_has_no_fallback(published: tuple[DataRoots, dict[str, dict[str, Any]], dict[str, Any]]) -> None:
    roots, entries, source = published
    requested = copy.deepcopy(entries)
    requested["prices"]["version_id"] = "not-published"
    with pytest.raises(KeyError, match="missing"):
        load_shared(roots, requested, ("0050", "2330"), source, "invented-input")


def test_manifest_pin_inputs_and_complete_inventory_are_required(published: tuple[DataRoots, dict[str, dict[str, Any]], dict[str, Any]]) -> None:
    roots, entries, source = published
    requested = copy.deepcopy(entries)
    requested["market"]["manifest"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="identity"):
        load_shared(roots, requested, ("0050", "2330"), source, "invented-input")
    with pytest.raises(ValueError, match="identity"):
        load_shared(roots, entries, ("0050", "2330"), source, "another-input")
    with pytest.raises(ValueError, match="inventory"):
        load_shared(roots, entries, ("0050",), source, "invented-input")
    with pytest.raises(ValueError, match="seven"):
        load_shared(roots, {kind: row for kind, row in entries.items() if kind != "market"}, ("0050", "2330"), source, "invented-input")


def test_strict_table_lookup_and_scope(published: tuple[DataRoots, dict[str, dict[str, Any]], dict[str, Any]]) -> None:
    roots, entries, source = published
    shared = load_shared(roots, entries, ("0050", "2330"), source, "invented-input")
    shared.validate_scope(("2330", "0050"), source, "invented-input")
    for action in (
        lambda: shared.stock("50", "prices"),
        lambda: shared.stock("0050", "invented"),
        lambda: shared.global_values("50"),
        lambda: shared.sidecar("invented"),
    ):
        with pytest.raises(ValueError, match="unknown"):
            action()
    with pytest.raises(ValueError, match="scope"):
        shared.validate_scope(("0050",), source, "invented-input")
    changed_source = {**source, "source_id": "another-source"}
    with pytest.raises(ValueError, match="scope"):
        shared.validate_scope(shared.codes, changed_source, "invented-input")
