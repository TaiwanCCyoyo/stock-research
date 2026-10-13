"""Invented file publication checks; no market artifacts are read."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from research_core import artifact_store
from research_core import research_data_file_bundle_v1 as publisher
from research_core.artifact_store import file_digest
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DataRoots


@pytest.fixture
def catalog(tmp_path: Path) -> DataCatalog:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    return DataCatalog(DataRoots(primary, primary / "research_data"))


def _metadata() -> dict[str, Any]:
    unavailable = {"start": None, "end": None, "reason": "synthetic only"}
    return {
        "data_id": "synthetic-file-bundle",
        "kind": "features",
        "definition_version": "fixture.v1",
        "parameters": {"fixture": True},
        "inputs": {"prices": "invented-v1"},
        "coverage": {
            "scope": "invented",
            "raw_input_period": {"start": "2010-01-04", "end": "2010-01-05", "reason": None},
            "valid_indicator_period": unavailable,
            "complete_label_period": unavailable,
        },
        "status": "partial",
        "limitations": ["synthetic fixture"],
        "backup": {"status": "not_backed_up", "off_machine": False},
    }


def _source(tmp_path: Path, name: str = "source.bin", content: bytes = b"invented") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _manifest(catalog: DataCatalog, entry: dict[str, Any]) -> Path:
    return catalog.roots.artifact_path(entry["manifest"]["scope"], entry["manifest"]["path"])


def test_multifile_physical_publication_exact_catalog_lookup_and_reuse(catalog: DataCatalog, tmp_path: Path) -> None:
    files = {"nested/a.bin": _source(tmp_path, "a.bin", b"a" * (2 * 1024 * 1024)), "b.bin": _source(tmp_path, "b.bin", b"b" * (1024 * 1024))}
    entry = publisher.publish_file_bundle(catalog, _metadata(), files)
    assert entry["manifest"]["scope"] == "primary"
    manifest = _manifest(catalog, entry)
    assert manifest.is_relative_to(catalog.roots.primary / "research_cache")
    assert not any(path.name in ("a.bin", "b.bin") for path in catalog.roots.data.rglob("*"))
    assert catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"]) == entry
    before = {path.relative_to(manifest.parent).as_posix(): file_digest(path) for path in manifest.parent.rglob("*") if path.is_file()}
    snapshot = catalog.read()["version_id"]
    assert publisher.publish_file_bundle(catalog, _metadata(), files) == entry
    assert catalog.read()["version_id"] == snapshot
    assert before == {path.relative_to(manifest.parent).as_posix(): file_digest(path) for path in manifest.parent.rglob("*") if path.is_file()}
    for name, source in files.items():
        target = manifest.parent / name
        assert target.read_bytes() == source.read_bytes()
        assert not os.path.samefile(target, source) and target.stat().st_nlink == 1


def test_changed_source_publishes_new_version_preserving_old_bytes(catalog: DataCatalog, tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = publisher.publish_file_bundle(catalog, _metadata(), {"payload.bin": source})
    old = _manifest(catalog, first).parent / "payload.bin"
    old_hash = file_digest(old)
    source.write_bytes(b"new invented content")
    second = publisher.publish_file_bundle(catalog, _metadata(), {"payload.bin": source})
    assert second["version_id"] != first["version_id"]
    assert old.read_bytes() == b"invented" and file_digest(old) == old_hash
    assert len(catalog.read()["entries"]) == 2


def test_task_report_payload_has_one_catalogued_task_home(catalog: DataCatalog, tmp_path: Path) -> None:
    source = _source(tmp_path)
    entry = publisher.publish_file_bundle(catalog, _metadata(), {"summary.bin": source}, task_id="synthetic-study")
    manifest = _manifest(catalog, entry)
    assert manifest.is_relative_to(catalog.roots.primary / "tasks/synthetic-study/datasets")
    assert not (catalog.roots.primary / "research_cache").exists()
    assert catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"]) == entry
    assert publisher.publish_file_bundle(catalog, _metadata(), {"summary.bin": source}, task_id="synthetic-study") == entry
    with pytest.raises(ValueError):
        publisher.publish_file_bundle(catalog, _metadata(), {"summary.bin": source}, task_id="../escape")


@pytest.mark.parametrize("name", ("../escape", "C:/escape", "name:stream", "manifest.json", "manifest.json/child"))
def test_unsafe_or_reserved_payload_paths_rejected(catalog: DataCatalog, tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        publisher.publish_file_bundle(catalog, _metadata(), {name: _source(tmp_path)})
    assert not catalog.roots.data.exists()


def test_hardlinked_source_rejected(catalog: DataCatalog, tmp_path: Path) -> None:
    source = _source(tmp_path)
    linked = tmp_path / "hardlink.bin"
    os.link(source, linked)
    with pytest.raises(ValueError, match="hardlink"):
        publisher.publish_file_bundle(catalog, _metadata(), {"payload.bin": linked})


def test_symlinked_source_rejected(catalog: DataCatalog, tmp_path: Path) -> None:
    source = _source(tmp_path)
    linked = tmp_path / "symlink.bin"
    try:
        linked.symlink_to(source)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows session lacks symbolic-link privilege")
        raise
    with pytest.raises(ValueError, match="linked|reparse"):
        publisher.publish_file_bundle(catalog, _metadata(), {"payload.bin": linked})


def test_corrupt_existing_final_fails_without_replacement(catalog: DataCatalog, tmp_path: Path) -> None:
    source = _source(tmp_path)
    entry = publisher.publish_file_bundle(catalog, _metadata(), {"payload.bin": source})
    payload = _manifest(catalog, entry).parent / "payload.bin"
    payload.chmod(0o600)
    payload.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="mismatch"):
        publisher.publish_file_bundle(catalog, _metadata(), {"payload.bin": source})
    assert payload.read_bytes() == b"corrupt"
    assert len(catalog.read()["entries"]) == 1


def test_source_changes_during_copy_leave_only_staging(catalog: DataCatalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    original = publisher.copy_verified
    original_stream_copy = artifact_store.shutil.copyfileobj
    observed: list[Path] = []

    def changed_copy(input_path: Path, destination: Path, expected: str) -> None:
        observed.append(destination)
        original(input_path, destination, expected)

    def changed_stream_copy(incoming: BinaryIO, outgoing: BinaryIO, length: int = 0) -> None:
        original_stream_copy(incoming, outgoing, length)
        source.write_bytes(b"changed during copy")

    monkeypatch.setattr(publisher, "copy_verified", changed_copy)
    monkeypatch.setattr(artifact_store.shutil, "copyfileobj", changed_stream_copy)
    with pytest.raises(ValueError, match="mismatch"):
        publisher.publish_file_bundle(catalog, _metadata(), {"payload.bin": source})
    assert observed and any(part.startswith(".staging-") for part in observed[0].parts)
    parent = observed[0].parent.parent
    assert all(path.name.startswith(".staging-") for path in parent.iterdir())
    assert not (catalog.roots.data / "catalog.json").exists()
