"""Synthetic additive backup/restore regression tests; no producer data reads."""

from os import stat_result
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_core import artifact_backup
from research_core.artifact_backup import backup_sources, default_sources, restore_backup, verify_backup
from research_core.artifact_store import file_digest, read_json


def test_sealed_closed_database_requires_matching_hash_and_no_sidecars(tmp_path: Path) -> None:
    source = source_tree(tmp_path)
    database = source / "historical.sqlite"
    database.write_bytes(b"sealed historical database fixture")
    digest = file_digest(database)
    receipt = backup_sources({"dataset": source}, tmp_path / "backup", frozen_sqlite={database: digest})
    assert receipt["files"] == 3
    with pytest.raises(ValueError, match="closed-state mismatch"):
        backup_sources({"dataset": source}, tmp_path / "wrong", frozen_sqlite={database: "0" * 64})
    sidecar = source / "historical.sqlite-wal"
    sidecar.write_bytes(b"writer exists")
    with pytest.raises(ValueError, match="closed-state mismatch"):
        backup_sources({"dataset": source}, tmp_path / "live", frozen_sqlite={database: digest})
    assert not (tmp_path / "live").exists()


def source_tree(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "prices.bin").write_bytes(b"synthetic prices\x00\xff")
    (source / "nested").mkdir()
    (source / "nested" / "labels.json").write_bytes(b'{"label":null}')
    return source


def snapshot(tmp_path: Path) -> tuple[Path, Path, dict[str, Any], Path]:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    receipt = backup_sources({"dataset": source}, root)
    return source, root, receipt, Path(receipt["manifest_path"])


def test_backup_verify_restore_preserves_exact_bytes(tmp_path: Path) -> None:
    source, _, receipt, manifest_path = snapshot(tmp_path)
    manifest = verify_backup(manifest_path)
    assert manifest["complete"] is True
    assert manifest["snapshot_id"] == receipt["snapshot_id"]
    assert receipt["files"] == receipt["copied"] == 2
    assert receipt["reused"] == 0
    destination = tmp_path / "restored"
    restored = restore_backup(manifest_path, destination)
    assert restored["complete"] is True
    assert restored["snapshot_id"] == receipt["snapshot_id"]
    for relative in ("prices.bin", "nested/labels.json"):
        assert (destination / "dataset" / relative).read_bytes() == (source / relative).read_bytes()
    assert read_json(destination / "restore-receipt.json") == restored


def test_first_and_reused_backup_each_publish_linked_append_only_completion(tmp_path: Path) -> None:
    source, root, first, manifest_path = snapshot(tmp_path)
    first_attempt_bytes = Path(first["attempt_path"]).read_bytes()
    first_completion_bytes = Path(first["completion_path"]).read_bytes()
    second = backup_sources({"dataset": source}, root)
    assert first["attempt_path"] != second["attempt_path"]
    assert first["completion_path"] != second["completion_path"]
    assert first["snapshot_id"] == second["snapshot_id"]
    assert len(list((root / "snapshots").glob("*.json"))) == 1
    assert len(list((root / "completions").glob("*.json"))) == 2
    for receipt in (first, second):
        attempt = Path(receipt["attempt_path"])
        completion = read_json(Path(receipt["completion_path"]))
        assert read_json(attempt)["state"] == "started"
        assert read_json(attempt)["complete"] is False
        assert completion["state"] == "completed" and completion["complete"] is True
        assert completion["attempt"] == {"path": attempt.relative_to(root).as_posix(), "sha256": file_digest(attempt)}
        assert completion["snapshot"] == {
            "path": manifest_path.relative_to(root).as_posix(),
            "id": receipt["snapshot_id"],
            "sha256": file_digest(manifest_path),
        }
        assert {key: completion[key] for key in ("copied", "reused", "files", "bytes")} == {key: receipt[key] for key in ("copied", "reused", "files", "bytes")}
    assert second["copied"] == 0 and second["reused"] == 2
    assert Path(first["attempt_path"]).read_bytes() == first_attempt_bytes
    assert Path(first["completion_path"]).read_bytes() == first_completion_bytes


@pytest.mark.parametrize("failure", ["object", "source", "snapshot", "verify"])
def test_backup_failure_never_publishes_completion_and_next_attempt_can_succeed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_inventory = artifact_backup._inventory
    inventories = 0

    def failed_step(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"simulated {failure} failure")

    def failed_reinventory(sources: dict[str, Path], frozen_sqlite: dict[Path, str] | None = None) -> list[dict[str, Any]]:
        nonlocal inventories
        inventories += 1
        if inventories == 2:
            raise RuntimeError("simulated source failure")
        return original_inventory(sources, frozen_sqlite)

    with monkeypatch.context() as context:
        if failure == "source":
            context.setattr(artifact_backup, "_inventory", failed_reinventory)
        else:
            function = {"object": "_seed_object", "snapshot": "_publish_manifest", "verify": "verify_backup"}[failure]
            context.setattr(artifact_backup, function, failed_step)
        with pytest.raises(RuntimeError, match=f"simulated {failure} failure"):
            backup_sources({"dataset": source}, root)
    assert not list((root / "completions").glob("*.json"))
    failed_attempt = next((root / "attempts").glob("*.json"))
    failed_bytes = failed_attempt.read_bytes()
    assert read_json(failed_attempt)["complete"] is False
    retried = backup_sources({"dataset": source}, root)
    assert read_json(Path(retried["completion_path"]))["complete"] is True
    assert failed_attempt.read_bytes() == failed_bytes
    assert len(list((root / "completions").glob("*.json"))) == 1


def test_interrupted_completion_write_retains_only_partial_and_retry_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_write = artifact_backup.write_json

    def interrupted_completion(path: Path, value: Any) -> None:
        if path.parent == root / "completions":
            assert path.name.endswith(".partial")
            path.write_bytes(b'{"complete":')
            raise RuntimeError("simulated interrupted completion")
        original_write(path, value)

    with monkeypatch.context() as context:
        context.setattr(artifact_backup, "write_json", interrupted_completion)
        with pytest.raises(RuntimeError, match="interrupted completion"):
            backup_sources({"dataset": source}, root)
    partials = list((root / "completions").glob(".*.partial"))
    assert len(partials) == 1
    assert list((root / "completions").iterdir()) == partials
    assert len(list((root / "snapshots").glob("*.json"))) == 1
    failed_attempt = next((root / "attempts").glob("*.json"))
    failed_bytes = failed_attempt.read_bytes()
    retried = backup_sources({"dataset": source}, root)
    assert retried["copied"] == 0 and retried["reused"] == 2
    completion = read_json(Path(retried["completion_path"]))
    assert completion["complete"] is True
    assert completion["attempt"]["path"] != failed_attempt.relative_to(root).as_posix()
    assert failed_attempt.read_bytes() == failed_bytes
    assert partials[0].read_bytes() == b'{"complete":'
    assert len(list((root / "completions").glob("*.json"))) == 1
    verify_backup(Path(retried["manifest_path"]))
    assert restore_backup(Path(retried["manifest_path"]), tmp_path / "restored")["complete"] is True


def test_repeated_backup_reuses_then_changed_source_adds_preserved_snapshot(tmp_path: Path) -> None:
    source, root, first, first_path = snapshot(tmp_path)
    original_manifest = first_path.read_bytes()
    repeated = backup_sources({"dataset": source}, root)
    assert repeated["snapshot_id"] == first["snapshot_id"]
    assert repeated["copied"] == 0
    assert repeated["reused"] == 2
    (source / "prices.bin").write_bytes(b"changed synthetic evidence")
    second = backup_sources({"dataset": source}, root)
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["copied"] == second["reused"] == 1
    assert first_path.read_bytes() == original_manifest
    assert len(list((root / "snapshots").glob("*.json"))) == 2
    restore_backup(first_path, tmp_path / "old-restored")
    assert (tmp_path / "old-restored/dataset/prices.bin").read_bytes() == b"synthetic prices\x00\xff"
    verify_backup(Path(second["manifest_path"]))


def test_removed_source_remains_restorable_from_old_snapshot(tmp_path: Path) -> None:
    source, root, first, manifest_path = snapshot(tmp_path)
    (source / "prices.bin").unlink()
    second = backup_sources({"dataset": source}, root)
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["files"] == 1
    restore_backup(manifest_path, tmp_path / "restored")
    assert (tmp_path / "restored/dataset/prices.bin").read_bytes() == b"synthetic prices\x00\xff"
    assert not (source / "prices.bin").exists()


def test_corrupt_object_rejected_without_overwriting_or_restoring(tmp_path: Path) -> None:
    source, root, _, manifest_path = snapshot(tmp_path)
    digest = verify_backup(manifest_path)["files"][0]["sha256"]
    damaged = root / "objects" / digest
    damaged.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="backup object corrupt"):
        verify_backup(manifest_path)
    with pytest.raises(ValueError, match="refusing overwrite"):
        backup_sources({"dataset": source}, root)
    assert damaged.read_bytes() == b"corrupted"
    with pytest.raises(ValueError, match="backup object corrupt"):
        restore_backup(manifest_path, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_interrupted_object_copy_retains_partial_and_retry_publishes_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_copy = artifact_backup.copy_verified

    def interrupted_copy(incoming: Path, destination: Path, expected: str) -> None:
        assert destination.name.startswith(f".{expected}.backup-")
        assert destination.name.endswith(".partial")
        destination.write_bytes(incoming.read_bytes()[:3])
        raise RuntimeError("simulated interrupted copy")

    monkeypatch.setattr(artifact_backup, "copy_verified", interrupted_copy)
    with pytest.raises(RuntimeError, match="simulated interrupted copy"):
        backup_sources({"dataset": source}, root)
    objects = root / "objects"
    partials = list(objects.glob(".*.partial"))
    assert len(partials) == 1
    retained = partials[0].read_bytes()
    assert list(objects.iterdir()) == partials
    assert not list((root / "snapshots").glob("*.json"))
    first_attempt = next((root / "attempts").glob("*.json"))
    assert read_json(first_attempt)["complete"] is False

    monkeypatch.setattr(artifact_backup, "copy_verified", original_copy)
    receipt = backup_sources({"dataset": source}, root)
    manifest_path = Path(receipt["manifest_path"])
    verify_backup(manifest_path)
    assert receipt["copied"] == 2
    assert partials[0].read_bytes() == retained
    assert not list(objects.glob(".*.lock"))
    assert len(list((root / "attempts").glob("*.json"))) == 2
    restore_backup(manifest_path, tmp_path / "restored")
    assert (tmp_path / "restored/dataset/prices.bin").read_bytes() == (source / "prices.bin").read_bytes()


def test_interrupted_manifest_write_retains_partial_and_retry_reuses_objects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_write = artifact_backup.write_json

    def interrupted_write(path: Path, value: Any) -> None:
        if path.parent == root / "snapshots":
            assert path.name.startswith(f".{value['snapshot_id']}.snapshot-")
            assert path.name.endswith(".partial")
            path.write_bytes(b'{"complete":')
            raise RuntimeError("simulated interrupted manifest write")
        original_write(path, value)

    monkeypatch.setattr(artifact_backup, "write_json", interrupted_write)
    with pytest.raises(RuntimeError, match="interrupted manifest write"):
        backup_sources({"dataset": source}, root)
    snapshots = root / "snapshots"
    partials = list(snapshots.glob(".*.partial"))
    assert len(partials) == 1
    assert list(snapshots.iterdir()) == partials
    assert len(list((root / "objects").iterdir())) == 2
    assert read_json(next((root / "attempts").glob("*.json")))["complete"] is False

    monkeypatch.setattr(artifact_backup, "write_json", original_write)
    receipt = backup_sources({"dataset": source}, root)
    assert receipt["copied"] == 0 and receipt["reused"] == 2
    assert partials[0].read_bytes() == b'{"complete":'
    assert not list(snapshots.glob(".*.lock"))
    manifest_path = Path(receipt["manifest_path"])
    assert verify_backup(manifest_path)["complete"] is True
    destination = tmp_path / "restored"
    assert restore_backup(manifest_path, destination)["complete"] is True
    for relative in ("prices.bin", "nested/labels.json"):
        assert (destination / "dataset" / relative).read_bytes() == (source / relative).read_bytes()


def test_manifest_appearing_during_write_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_write = artifact_backup.write_json
    targets: list[Path] = []

    def racing_write(path: Path, value: Any) -> None:
        original_write(path, value)
        if path.parent == root / "snapshots":
            target = path.parent / f"{value['snapshot_id']}.json"
            target.write_bytes(b"competing snapshot")
            targets.append(target)

    monkeypatch.setattr(artifact_backup, "write_json", racing_write)
    with pytest.raises(FileExistsError, match="snapshot appeared during write"):
        backup_sources({"dataset": source}, root)
    assert len(targets) == 1
    assert targets[0].read_bytes() == b"competing snapshot"
    assert len(list((root / "snapshots").glob(".*.partial"))) == 1
    assert not list((root / "snapshots").glob(".*.lock"))


def test_manifest_partial_hash_must_match_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_write = artifact_backup.write_json

    def damaged_write(path: Path, value: Any) -> None:
        if path.parent == root / "snapshots":
            path.write_bytes(b"{}")
        else:
            original_write(path, value)

    monkeypatch.setattr(artifact_backup, "write_json", damaged_write)
    with pytest.raises(ValueError, match="snapshot partial hash mismatch"):
        backup_sources({"dataset": source}, root)
    assert not list((root / "snapshots").glob("*.json"))
    assert len(list((root / "snapshots").glob(".*.partial"))) == 1
    assert not list((root / "snapshots").glob(".*.lock"))


def test_object_appearing_during_copy_is_preserved_and_publication_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_copy = artifact_backup.copy_verified
    competing_bytes = b"a competing writer owns this target"
    targets: list[Path] = []

    def racing_copy(incoming: Path, destination: Path, expected: str) -> None:
        original_copy(incoming, destination, expected)
        target = destination.parent / expected
        target.write_bytes(competing_bytes)
        targets.append(target)

    monkeypatch.setattr(artifact_backup, "copy_verified", racing_copy)
    with pytest.raises(FileExistsError, match="appeared during copy"):
        backup_sources({"dataset": source}, root)
    assert len(targets) == 1
    assert targets[0].read_bytes() == competing_bytes
    partials = list((root / "objects").glob(".*.partial"))
    assert len(partials) == 1
    assert file_digest(partials[0]) == targets[0].name
    assert not list((root / "objects").glob(".*.lock"))
    assert not list((root / "snapshots").glob("*.json"))


def test_existing_object_lock_is_preserved_without_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    objects = root / "objects"
    objects.mkdir(parents=True)
    digest = file_digest(source / "nested/labels.json")
    lock = objects / f".{digest}.lock"
    lock.write_bytes(b"other writer's lock")

    def forbidden_copy(incoming: Path, destination: Path, expected: str) -> None:
        pytest.fail("competing lock must prevent copying")

    monkeypatch.setattr(artifact_backup, "copy_verified", forbidden_copy)
    with pytest.raises(FileExistsError):
        backup_sources({"dataset": source}, root)
    assert lock.read_bytes() == b"other writer's lock"
    assert not (objects / digest).exists()
    assert not list(objects.glob(".*.partial"))


@pytest.mark.parametrize("damage", ["size", "hash"])
def test_partial_requires_size_and_hash_verification_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"

    def unverified_copy(incoming: Path, destination: Path, expected: str) -> None:
        original = incoming.read_bytes()
        destination.write_bytes(original[:1] if damage == "size" else b"x" * len(original))

    monkeypatch.setattr(artifact_backup, "copy_verified", unverified_copy)
    with pytest.raises(ValueError, match="partial hash/size mismatch"):
        backup_sources({"dataset": source}, root)
    partials = list((root / "objects").glob(".*.partial"))
    assert len(partials) == 1
    assert list((root / "objects").iterdir()) == partials
    assert not list((root / "snapshots").glob("*.json"))


@pytest.mark.parametrize("mutation", ["content", "addition", "removal"])
def test_source_mutation_during_copy_never_publishes_complete_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    original_copy = artifact_backup.copy_verified
    changed = False

    def changing_copy(incoming: Path, destination: Path, expected: str) -> None:
        nonlocal changed
        original_copy(incoming, destination, expected)
        if not changed:
            changed = True
            if mutation == "content":
                incoming.write_bytes(b"changed after successful copy")
            elif mutation == "addition":
                (source / "added.json").write_bytes(b"{}")
            else:
                incoming.unlink()

    monkeypatch.setattr(artifact_backup, "copy_verified", changing_copy)
    with pytest.raises(ValueError, match="source changed during backup"):
        backup_sources({"dataset": source}, root)
    assert not list((root / "snapshots").glob("*.json"))
    attempts = list((root / "attempts").glob("*.json"))
    assert len(attempts) == 1
    assert read_json(attempts[0])["complete"] is False


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/windows", "data\\windows", "data//empty", "./data"])
def test_unsafe_namespace_rejected_before_backup_creation(tmp_path: Path, name: str) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    with pytest.raises(ValueError, match="unsafe artifact name"):
        backup_sources({name: source}, root)
    assert not root.exists()


def test_traversal_root_rejected(tmp_path: Path) -> None:
    source = source_tree(tmp_path)
    with pytest.raises(ValueError, match="path traversal"):
        backup_sources({"dataset": source}, tmp_path / "escape" / ".." / "backup")


def test_windows_junction_ancestor_rejected_without_creating_real_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_tree(tmp_path)
    original_lstat = Path.lstat

    def reparse_lstat(path: Path) -> stat_result | SimpleNamespace:
        result = original_lstat(path)
        if path == source.absolute():
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=1024)
        return result

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    with pytest.raises(ValueError, match="linked/reparse path forbidden"):
        backup_sources({"dataset": source}, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("name", [".env", ".env.private", "live.sqlite", "live.sqlite3", "live.db", "live.sqlite-wal", "live.sqlite-shm"])
def test_private_or_live_database_files_explicitly_rejected(tmp_path: Path, name: str) -> None:
    source = source_tree(tmp_path)
    (source / name).write_bytes(b"synthetic private/database fixture")
    with pytest.raises(ValueError, match="private or potentially live database"):
        backup_sources({"dataset": source}, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_default_sources_include_only_cache_task_datasets_and_owner_labels(tmp_path: Path) -> None:
    names = [
        "research_cache/version",
        "tasks/example/datasets",
        "tasks/example/unrelated",
        "tasks/20261010-owner-hhhl-labels/datasets",
        "tasks/20261010-owner-hhhl-labels/annotations",
        "shioaji_stock_prices/data",
        "broker",
        "unrelated",
    ]
    for name in names:
        (tmp_path / name).mkdir(parents=True)
    sources = default_sources(tmp_path)
    assert sources == {
        "research_cache": tmp_path / "research_cache",
        "tasks/example/datasets": tmp_path / "tasks/example/datasets",
        "tasks/20261010-owner-hhhl-labels": tmp_path / "tasks/20261010-owner-hhhl-labels",
    }


def test_overlapping_namespace_duplicates_rejected(tmp_path: Path) -> None:
    source = source_tree(tmp_path)
    with pytest.raises(ValueError, match="nonoverlapping file inventory"):
        backup_sources({"dataset": source, "dataset/nested": source / "nested"}, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("layout", ["source_contains_backup", "backup_contains_source", "same"])
def test_source_backup_tree_overlap_rejected(tmp_path: Path, layout: str) -> None:
    source = source_tree(tmp_path)
    root = source / "backup" if layout == "source_contains_backup" else tmp_path if layout == "backup_contains_source" else source
    with pytest.raises(ValueError, match="trees must not overlap"):
        backup_sources({"dataset": source}, root)


@pytest.mark.parametrize("existing", ["empty_directory", "populated_directory", "file"])
def test_restore_existing_destination_refused_unchanged(tmp_path: Path, existing: str) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "existing"
    if existing == "file":
        destination.write_bytes(b"preserve file")
    else:
        destination.mkdir()
        if existing == "populated_directory":
            (destination / "keep.bin").write_bytes(b"preserve child")
    with pytest.raises(ValueError, match="destination must not exist"):
        restore_backup(manifest_path, destination)
    if existing == "file":
        assert destination.read_bytes() == b"preserve file"
    elif existing == "populated_directory":
        assert list(destination.iterdir()) == [destination / "keep.bin"]
        assert (destination / "keep.bin").read_bytes() == b"preserve child"
    else:
        assert list(destination.iterdir()) == []


def test_interrupted_restore_copy_retains_stage_and_same_destination_retry_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    original_copy = artifact_backup.copy_verified

    def interrupted_copy(incoming: Path, target: Path, expected: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(incoming.read_bytes()[:3])
        raise RuntimeError("simulated interrupted restore copy")

    monkeypatch.setattr(artifact_backup, "copy_verified", interrupted_copy)
    with pytest.raises(RuntimeError, match="interrupted restore copy"):
        restore_backup(manifest_path, destination)
    assert not destination.exists()
    stages = list(tmp_path.glob(".staging-restore-*"))
    assert len(stages) == 1
    retained = {path.relative_to(stages[0]): path.read_bytes() for path in stages[0].rglob("*") if path.is_file()}
    assert retained
    assert not (tmp_path / ".restored.restore.lock").exists()

    monkeypatch.setattr(artifact_backup, "copy_verified", original_copy)
    receipt = restore_backup(manifest_path, destination)
    assert receipt["complete"] is True
    assert list(tmp_path.glob(".staging-restore-*")) == stages
    assert {path.relative_to(stages[0]): path.read_bytes() for path in stages[0].rglob("*") if path.is_file()} == retained
    for relative in ("prices.bin", "nested/labels.json"):
        assert (destination / "dataset" / relative).read_bytes() == (source / relative).read_bytes()
    assert read_json(destination / "restore-receipt.json") == receipt


def test_interrupted_restore_receipt_retains_stage_and_retry_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    original_write = artifact_backup.write_json

    def interrupted_receipt(path: Path, value: Any) -> None:
        if path.name == "restore-receipt.json":
            path.write_bytes(b'{"complete":')
            raise RuntimeError("simulated interrupted restore receipt")
        original_write(path, value)

    monkeypatch.setattr(artifact_backup, "write_json", interrupted_receipt)
    with pytest.raises(RuntimeError, match="interrupted restore receipt"):
        restore_backup(manifest_path, destination)
    assert not destination.exists()
    stages = list(tmp_path.glob(".staging-restore-*"))
    assert len(stages) == 1
    assert (stages[0] / "restore-receipt.json").read_bytes() == b'{"complete":'
    assert not (tmp_path / ".restored.restore.lock").exists()
    monkeypatch.setattr(artifact_backup, "write_json", original_write)
    receipt = restore_backup(manifest_path, destination)
    assert read_json(destination / "restore-receipt.json") == receipt
    assert (stages[0] / "restore-receipt.json").read_bytes() == b'{"complete":'
    manifest = verify_backup(manifest_path)
    for row in manifest["files"]:
        restored = destination / row["path"]
        assert restored.stat().st_size == row["bytes"]
        assert file_digest(restored) == row["sha256"]


def test_restore_other_writer_destination_appearing_during_copy_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    original_copy = artifact_backup.copy_verified

    def competing_copy(incoming: Path, target: Path, expected: str) -> None:
        original_copy(incoming, target, expected)
        if not destination.exists():
            destination.mkdir()
            (destination / "foreign.bin").write_bytes(b"foreign restore")

    monkeypatch.setattr(artifact_backup, "copy_verified", competing_copy)
    with pytest.raises(FileExistsError, match="destination appeared during copy"):
        restore_backup(manifest_path, destination)
    assert list(destination.iterdir()) == [destination / "foreign.bin"]
    assert (destination / "foreign.bin").read_bytes() == b"foreign restore"
    assert len(list(tmp_path.glob(".staging-restore-*"))) == 1
    assert not (tmp_path / ".restored.restore.lock").exists()


def test_foreign_restore_lock_preserved_and_prevents_staging(tmp_path: Path) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    lock = tmp_path / ".restored.restore.lock"
    lock.write_bytes(b"another restore writer")
    with pytest.raises(FileExistsError):
        restore_backup(manifest_path, destination)
    assert lock.read_bytes() == b"another restore writer"
    assert not destination.exists()
    assert not list(tmp_path.glob(".staging-restore-*"))


def test_restore_revalidates_staged_files_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    original_write = artifact_backup.write_json

    def corrupt_after_copy(path: Path, value: Any) -> None:
        original_write(path, value)
        if path.name == "restore-receipt.json":
            (path.parent / "dataset/prices.bin").write_bytes(b"changed after verified copy")

    monkeypatch.setattr(artifact_backup, "write_json", corrupt_after_copy)
    with pytest.raises(ValueError, match="artifact hash/size mismatch"):
        restore_backup(manifest_path, destination)
    assert not destination.exists()
    assert len(list(tmp_path.glob(".staging-restore-*"))) == 1


def test_restore_rejects_manifest_swap_during_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    original_copy = artifact_backup.copy_verified
    original_manifest = manifest_path.read_bytes()

    def swap_manifest(incoming: Path, target: Path, expected: str) -> None:
        original_copy(incoming, target, expected)
        # Semantically identical valid JSON still changes the pinned source bytes.
        manifest_path.write_bytes(b" " + original_manifest)

    monkeypatch.setattr(artifact_backup, "copy_verified", swap_manifest)
    with pytest.raises(ValueError, match="backup manifest changed during restore"):
        restore_backup(manifest_path, destination)
    assert not destination.exists()
    assert len(list(tmp_path.glob(".staging-restore-*"))) == 1


def test_restore_rejects_unlisted_staged_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    original_write = artifact_backup.write_json

    def extra_file(path: Path, value: Any) -> None:
        original_write(path, value)
        if path.name == "restore-receipt.json":
            (path.parent / "unlisted.bin").write_bytes(b"not in manifest")

    monkeypatch.setattr(artifact_backup, "write_json", extra_file)
    with pytest.raises(ValueError, match="restore staged inventory mismatch"):
        restore_backup(manifest_path, destination)
    assert not destination.exists()
    assert len(list(tmp_path.glob(".staging-restore-*"))) == 1


@pytest.mark.parametrize("publication", ["objects", "snapshots", "completions"])
def test_backup_late_publication_race_never_replaces_foreign_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publication: str) -> None:
    source = source_tree(tmp_path)
    root = tmp_path / "backup"
    real_publish = artifact_backup.publish_noreplace
    raced: list[tuple[Path, Path, bytes]] = []
    foreign_bytes = b"foreign artifact created after final existence check"

    def late_competing_publish(partial: Path, destination: Path) -> None:
        if destination.parent == root / publication:
            assert not destination.exists()
            retained_bytes = partial.read_bytes()
            destination.write_bytes(foreign_bytes)
            raced.append((partial, destination, retained_bytes))
        real_publish(partial, destination)

    monkeypatch.setattr(artifact_backup, "publish_noreplace", late_competing_publish)
    with pytest.raises(FileExistsError):
        backup_sources({"dataset": source}, root)
    assert len(raced) == 1
    partial, destination, retained_bytes = raced[0]
    assert destination.read_bytes() == foreign_bytes
    assert partial.read_bytes() == retained_bytes
    assert partial.suffix == ".partial"
    assert not list(destination.parent.glob(".*.lock"))
    attempt = next((root / "attempts").glob("*.json"))
    assert read_json(attempt)["complete"] is False
    if publication != "completions":
        assert not list((root / "completions").glob("*.json"))
    else:
        assert list((root / "completions").glob("*.json")) == [destination]
        assert len(list((root / "snapshots").glob("*.json"))) == 1


@pytest.mark.parametrize("competing", ["empty_directory", "populated_directory", "file"])
def test_restore_late_publication_race_preserves_foreign_destination_and_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, competing: str) -> None:
    _, _, _, manifest_path = snapshot(tmp_path)
    destination = tmp_path / "restored"
    real_publish = artifact_backup.publish_noreplace
    stages: list[tuple[Path, dict[str, bytes]]] = []

    def late_competing_publish(staging: Path, target: Path) -> None:
        assert target == destination and not target.exists()
        assert staging.is_dir()
        stages.append((staging, {path.relative_to(staging).as_posix(): path.read_bytes() for path in staging.rglob("*") if path.is_file()}))
        if competing == "file":
            target.write_bytes(b"foreign file")
        else:
            target.mkdir()
            if competing == "populated_directory":
                (target / "foreign.bin").write_bytes(b"foreign child")
        real_publish(staging, target)

    monkeypatch.setattr(artifact_backup, "publish_noreplace", late_competing_publish)
    with pytest.raises(FileExistsError):
        restore_backup(manifest_path, destination)
    assert len(stages) == 1
    staging, retained = stages[0]
    assert {path.relative_to(staging).as_posix(): path.read_bytes() for path in staging.rglob("*") if path.is_file()} == retained
    assert "restore-receipt.json" in retained
    if competing == "file":
        assert destination.read_bytes() == b"foreign file"
    elif competing == "populated_directory":
        assert list(destination.iterdir()) == [destination / "foreign.bin"]
        assert (destination / "foreign.bin").read_bytes() == b"foreign child"
    else:
        assert list(destination.iterdir()) == []
    assert not (tmp_path / ".restored.restore.lock").exists()
