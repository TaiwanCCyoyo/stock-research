"""Invented file publication checks; no market artifacts are read."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from research_core import artifact_store
from research_core import research_data_file_bundle_v1 as publisher
from research_core.artifact_store import file_digest, write_json
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


MANAGED_PARENT = "bundles/synthetic-file-bundle"


def _staged(catalog: DataCatalog, name: str = ".staging-fixture") -> Path:
    directory = catalog.roots.artifact_path("data", f"{MANAGED_PARENT}/{name}")
    (directory / "nested").mkdir(parents=True)
    (directory / "nested/payload.bin").write_bytes(b"single physical payload")
    return directory


def test_prepare_staged_bundle_keeps_payload_and_catalog_until_publication(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = _staged(catalog)
    payload = staging / "nested/payload.bin"
    before = payload.stat()
    original_rename, original_register = publisher.publish_noreplace, catalog.register

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("preparation must not publish or register")

    monkeypatch.setattr(publisher, "publish_noreplace", forbidden)
    monkeypatch.setattr(catalog, "register", forbidden)
    entry, body = publisher.prepare_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    after = payload.stat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    assert payload.read_bytes() == b"single physical payload"
    assert file_digest(staging / "manifest.json") == entry["version_id"]
    assert body["artifacts"] == [{"path": "nested/payload.bin", "bytes": payload.stat().st_size, "sha256": file_digest(payload)}]
    assert not _manifest(catalog, entry).exists()
    assert not (catalog.roots.data / "catalog.json").exists()
    assert publisher.prepare_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT) == (entry, body)
    monkeypatch.setattr(publisher, "publish_noreplace", original_rename)
    monkeypatch.setattr(catalog, "register", original_register)
    assert publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT) == entry
    assert not staging.exists()
    final = _manifest(catalog, entry).parent / "nested/payload.bin"
    assert (final.stat().st_dev, final.stat().st_ino) == (before.st_dev, before.st_ino)


def test_staged_publication_renames_once_without_payload_copy(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = _staged(catalog)
    before = (staging / "nested/payload.bin").stat()
    original = publisher.publish_noreplace
    renames = []

    def rename(source: Path, destination: Path) -> None:
        renames.append((source, destination))
        original(source, destination)

    def no_copy(*args: Any, **kwargs: Any) -> None:
        pytest.fail("staged publication must not copy payloads")

    monkeypatch.setattr(publisher, "copy_verified", no_copy)
    monkeypatch.setattr(publisher, "publish_noreplace", rename)
    entry = publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    manifest = _manifest(catalog, entry)
    payload = manifest.parent / "nested/payload.bin"
    after = payload.stat()
    assert not staging.exists()
    assert renames == [(staging, manifest.parent)]
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    assert payload.read_bytes() == b"single physical payload" and after.st_nlink == 1
    assert entry["manifest"]["scope"] == "data"
    assert not (catalog.roots.primary / "research_cache").exists()
    assert catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"]) == entry


def test_staged_registration_failure_keeps_verified_final_for_retry(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = _staged(catalog)
    original = catalog.register

    def fail_registration(entries: Any) -> None:
        raise RuntimeError("invented catalog registration interruption")

    monkeypatch.setattr(catalog, "register", fail_registration)
    with pytest.raises(RuntimeError, match="registration interruption"):
        publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    assert not staging.exists()
    finals = list(catalog.roots.artifact_path("data", MANAGED_PARENT).iterdir())
    assert len(finals) == 1 and (finals[0] / "manifest.json").is_file()
    before = {path.relative_to(finals[0]): file_digest(path) for path in finals[0].rglob("*") if path.is_file()}
    assert not (catalog.roots.data / "catalog.json").exists()
    monkeypatch.setattr(catalog, "register", original)
    entry = publisher.publish_staged_bundle(catalog, _metadata(), finals[0], managed_parent=MANAGED_PARENT)
    assert _manifest(catalog, entry).parent == finals[0]
    assert before == {path.relative_to(finals[0]): file_digest(path) for path in finals[0].rglob("*") if path.is_file()}


@pytest.mark.parametrize("damage", (None, "payload", "extra", "manifest"))
def test_staged_existing_final_is_verified_and_never_replaced(catalog: DataCatalog, damage: str | None) -> None:
    first = _staged(catalog)
    entry = publisher.publish_staged_bundle(catalog, _metadata(), first, managed_parent=MANAGED_PARENT)
    destination = _manifest(catalog, entry).parent
    if damage == "payload":
        (destination / "nested/payload.bin").write_bytes(b"corrupt")
    elif damage == "extra":
        (destination / "unexpected.bin").write_bytes(b"unexpected")
    elif damage == "manifest":
        (destination / "manifest.json").write_bytes(b"{}")
    second = _staged(catalog, ".staging-second")
    before = {path.relative_to(destination): file_digest(path) for path in destination.rglob("*") if path.is_file()}
    if damage is None:
        assert publisher.publish_staged_bundle(catalog, _metadata(), second, managed_parent=MANAGED_PARENT) == entry
    else:
        with pytest.raises(ValueError, match="mismatch|inventory|identity|digest"):
            publisher.publish_staged_bundle(catalog, _metadata(), second, managed_parent=MANAGED_PARENT)
    assert second.is_dir() and (second / "nested/payload.bin").is_file()
    assert before == {path.relative_to(destination): file_digest(path) for path in destination.rglob("*") if path.is_file()}


@pytest.mark.parametrize("bad_parent", ("../escape", "C:/escape", "bundles/name:stream"))
def test_staged_unsafe_managed_parent_rejected(catalog: DataCatalog, bad_parent: str) -> None:
    staging = _staged(catalog)
    with pytest.raises(ValueError):
        publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=bad_parent)
    assert not (staging / "manifest.json").exists()


@pytest.mark.parametrize("damage", ("outside", "relative", "unmanaged-name", "manifest", "manifest-directory", "hardlink", "empty"))
def test_staged_invalid_inventory_or_location_rejected(catalog: DataCatalog, tmp_path: Path, damage: str) -> None:
    staging = _staged(catalog)
    argument = staging
    if damage == "outside":
        argument = tmp_path
    elif damage == "relative":
        argument = Path(".staging-relative")
    elif damage == "unmanaged-name":
        argument = staging.with_name("ordinary-directory")
        staging.rename(argument)
    elif damage == "manifest":
        write_json(staging / "manifest.json", {"unrelated": True})
    elif damage == "manifest-directory":
        (staging / "manifest.json").mkdir()
    elif damage == "hardlink":
        os.link(staging / "nested/payload.bin", tmp_path / "alias.bin")
    elif damage == "empty":
        (staging / "nested/payload.bin").unlink()
    with pytest.raises(ValueError):
        publisher.publish_staged_bundle(catalog, _metadata(), argument, managed_parent=MANAGED_PARENT)
    assert not (catalog.roots.data / "catalog.json").exists()


def test_staged_symlink_rejected_before_traversal(catalog: DataCatalog, tmp_path: Path) -> None:
    staging = _staged(catalog)
    alias = staging / "linked-directory"
    try:
        alias.symlink_to(tmp_path, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows session lacks symbolic-link privilege")
        raise
    with pytest.raises(ValueError, match="linked|reparse"):
        publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    assert not (staging / "manifest.json").exists()


def test_staged_cross_filesystem_refused_before_manifest(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = _staged(catalog)
    original = Path.stat

    class OtherDeviceStat:
        def __init__(self, info: os.stat_result) -> None:
            self.original = info
            self.st_dev = info.st_dev + 1

        def __getattr__(self, name: str) -> Any:
            return getattr(self.original, name)

    def different_device(path: Path, *args: Any, **kwargs: Any) -> Any:
        info = original(path, *args, **kwargs)
        if path == staging:
            return OtherDeviceStat(info)
        return info

    monkeypatch.setattr(Path, "stat", different_device)
    with pytest.raises(ValueError, match="same filesystem"):
        publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    assert not (staging / "manifest.json").exists()


def test_staged_changed_payload_before_rename_is_not_published(catalog: DataCatalog) -> None:
    staging = _staged(catalog)
    publisher.prepare_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    (staging / "nested/payload.bin").write_bytes(b"changed before publication")
    with pytest.raises(ValueError, match="identity"):
        publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    assert staging.is_dir()
    assert list(staging.parent.iterdir()) == [staging]
    assert not (catalog.roots.data / "catalog.json").exists()


@pytest.mark.parametrize("operation", ("prepare", "publish", "retry-final", "reuse-final"))
def test_staged_publisher_hashes_each_physical_payload_once_per_call(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    staging = _staged(catalog)
    if operation in {"retry-final", "reuse-final"}:
        entry = publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
        final = _manifest(catalog, entry).parent
        staging = final if operation == "retry-final" else _staged(catalog, ".staging-reuse")
    else:
        final = None
    # Count only the staged publisher. Real registration independently verifies
    # the final bundle, exercised by the physical catalog tests above.
    registered = []
    monkeypatch.setattr(catalog, "register", lambda entries: registered.extend(entries))
    original = artifact_store.file_digest
    hashed: list[Path] = []

    def observed(path: Path) -> str:
        if path.name == "payload.bin":
            hashed.append(path)
        return original(path)

    monkeypatch.setattr(artifact_store, "file_digest", observed)
    monkeypatch.setattr(publisher, "file_digest", observed)
    if operation == "prepare":
        publisher.prepare_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    else:
        publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT)
    expected = [staging / "nested/payload.bin"]
    if operation == "reuse-final":
        assert final is not None
        expected.append(final / "nested/payload.bin")
    assert hashed == expected
    assert len(registered) == (0 if operation == "prepare" else 1)


def test_staged_callback_journals_exact_entry_before_publication(catalog: DataCatalog) -> None:
    staging = _staged(catalog)
    observed = []

    def before_publish(entry: dict[str, Any]) -> None:
        assert staging.is_dir() and (staging / "manifest.json").is_file()
        assert not _manifest(catalog, entry).exists()
        assert not (catalog.roots.data / "catalog.json").exists()
        observed.append(entry)

    entry = publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT, before_publish=before_publish)
    assert observed == [entry]
    assert _manifest(catalog, entry).is_file()


def test_staged_callback_failure_preserves_stage_and_retry_identity(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = _staged(catalog)
    planned = []
    original_register = catalog.register

    def forbidden_registration(entries: Any) -> None:
        pytest.fail("callback failure must precede registration")

    def interrupted(entry: dict[str, Any]) -> None:
        planned.append(entry)
        raise RuntimeError("invented journal interruption")

    monkeypatch.setattr(catalog, "register", forbidden_registration)
    with pytest.raises(RuntimeError, match="journal interruption"):
        publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT, before_publish=interrupted)
    assert staging.is_dir() and not _manifest(catalog, planned[0]).exists()
    assert not (catalog.roots.data / "catalog.json").exists()
    before = {path.relative_to(staging): file_digest(path) for path in staging.rglob("*") if path.is_file()}
    monkeypatch.setattr(catalog, "register", original_register)
    retried: list[dict[str, Any]] = []
    entry = publisher.publish_staged_bundle(catalog, _metadata(), staging, managed_parent=MANAGED_PARENT, before_publish=retried.append)
    assert retried == planned == [entry]
    final = _manifest(catalog, entry).parent
    assert before == {path.relative_to(final): file_digest(path) for path in final.rglob("*") if path.is_file()}
