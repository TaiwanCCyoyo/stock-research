"""Copy-boundary tests; the complete snapshot gate has its own reader tests."""

import os
from pathlib import Path

import pytest

from scripts import restore_opportunity_history as restore


def producer(tmp_path: Path) -> Path:
    source = tmp_path / "producer"
    (source / "catalog-v2").mkdir(parents=True)
    (source / "runs/native").mkdir(parents=True)
    (source / "catalog-v2/manifest.json").write_bytes(b"frozen manifest")
    (source / "runs/native/result.json").write_bytes(b"saved native results")
    return source


def test_restore_validates_before_copy_and_preserves_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = producer(tmp_path)
    destination = tmp_path / "consumer"
    before = restore._identities(source)
    calls: list[tuple[Path, str]] = []

    def validate(path: Path, expected_sha: str) -> None:
        assert not destination.exists()
        calls.append((path, expected_sha))

    monkeypatch.setattr(restore, "HistoryStore", validate)
    assert restore.restore_bundle(source, destination) == destination
    assert calls == [(source, restore.DEFAULT_SHA)]
    assert restore._identities(source) == restore._identities(destination) == before


def test_restore_never_overwrites_existing_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = producer(tmp_path)
    destination = tmp_path / "consumer"
    destination.mkdir()
    sentinel = destination / "keep.json"
    sentinel.write_bytes(b"existing evidence")
    monkeypatch.setattr(restore, "HistoryStore", lambda *_: pytest.fail("must reject before reading source"))
    with pytest.raises(FileExistsError, match="not be overwritten"):
        restore.restore_bundle(source, destination)
    assert sentinel.read_bytes() == b"existing evidence"


def test_invalid_snapshot_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = producer(tmp_path)
    destination = tmp_path / "consumer"

    def reject(*_: object) -> None:
        raise ValueError("Configured catalog manifest hash mismatch")

    monkeypatch.setattr(restore, "HistoryStore", reject)
    with pytest.raises(ValueError, match="hash mismatch"):
        restore.restore_bundle(source, destination)
    assert not destination.exists()


def test_changed_bytes_during_validation_reject_restored_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = producer(tmp_path)
    destination = tmp_path / "consumer"

    def change(*_: object) -> None:
        (source / "runs/native/result.json").write_bytes(b"changed concurrently")

    monkeypatch.setattr(restore, "HistoryStore", change)
    with pytest.raises(ValueError, match="changed during"):
        restore.restore_bundle(source, destination)


def test_source_destination_overlap_writes_nothing(tmp_path: Path) -> None:
    source = producer(tmp_path)
    with pytest.raises(ValueError, match="separate"):
        restore.restore_bundle(source, source / "consumer")
    assert not (source / "consumer").exists()


@pytest.mark.parametrize("alias", ["source", "destination"])
@pytest.mark.parametrize("relative", [False, True])
def test_parent_components_cannot_hide_subtree_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: str, relative: bool) -> None:
    source = producer(tmp_path)
    (source / "pad").mkdir()
    (tmp_path / "pad").mkdir()
    destination = source / "catalog-v2/copied"
    source_input = source / "pad/.." if alias == "source" else source
    destination_input = tmp_path / "pad/../producer/catalog-v2/copied" if alias == "destination" else destination
    before = restore._identities(source)
    if relative:
        monkeypatch.chdir(tmp_path)
        source_input = source_input.relative_to(tmp_path)
        destination_input = destination_input.relative_to(tmp_path)
    monkeypatch.setattr(restore, "HistoryStore", lambda *_: pytest.fail("overlap must fail before validation or writes"))
    monkeypatch.setattr(restore.shutil, "copytree", lambda *_: pytest.fail("overlap reached copying"))

    with pytest.raises(ValueError, match="separate directories"):
        restore.restore_bundle(source_input, destination_input)

    assert not destination.exists()
    assert restore._identities(source) == before


def test_separate_parent_component_paths_restore_normally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = producer(tmp_path)
    (source / "pad").mkdir()
    (tmp_path / "pad").mkdir()
    destination = tmp_path / "consumer"
    before = restore._identities(source)
    validated: list[Path] = []
    monkeypatch.setattr(restore, "HistoryStore", lambda path, _: validated.append(path))

    result = restore.restore_bundle(source / "pad/..", tmp_path / "pad/../consumer")

    assert result == destination.resolve()
    assert validated == [source.resolve()]
    assert restore._identities(source) == restore._identities(destination) == before


@pytest.mark.parametrize("link_check", ["is_symlink", "is_junction"])
@pytest.mark.parametrize("role", ["source", "destination"])
def test_parent_normalization_cannot_hide_link_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link_check: str, role: str) -> None:
    source = producer(tmp_path)
    link = tmp_path / "link"
    link.mkdir()
    destination = tmp_path / "consumer"
    original = getattr(Path, link_check, lambda _: False)
    # Simulate a detected link on every platform without requiring link privileges.
    monkeypatch.setattr(Path, link_check, lambda path: path == link or original(path), raising=False)
    monkeypatch.setattr(restore, "HistoryStore", lambda *_: pytest.fail("link must fail before source validation"))

    with pytest.raises(ValueError, match="without links or junctions"):
        source_input = link / ".." / source.name if role == "source" else source
        destination_input = link / ".." / destination.name if role == "destination" else destination
        restore.restore_bundle(source_input, destination_input)

    assert not destination.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows filesystem namespace aliases")
@pytest.mark.parametrize("role", ["source", "destination"])
def test_windows_namespace_alias_cannot_hide_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    source = producer(tmp_path)
    destination = source / "catalog-v2/copied"
    before = restore._identities(source)
    path = source if role == "source" else destination
    value = str(path.resolve())
    alias = Path("\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value)
    monkeypatch.setattr(restore, "HistoryStore", lambda *_: pytest.fail("overlap must fail before validation"))
    monkeypatch.setattr(restore.shutil, "copytree", lambda *_: pytest.fail("overlap reached copying"))

    with pytest.raises(ValueError, match="separate directories"):
        restore.restore_bundle(alias if role == "source" else source, alias if role == "destination" else destination)

    assert not destination.exists()
    assert restore._identities(source) == before


def test_directory_identity_failure_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = producer(tmp_path)
    destination = tmp_path / "consumer"
    before = restore._identities(source)

    def fail_identity(*_: object) -> bool:
        raise OSError("Cannot inspect directory identity")

    monkeypatch.setattr(Path, "samefile", fail_identity)
    monkeypatch.setattr(restore, "HistoryStore", lambda *_: pytest.fail("identity failure must stop before validation"))
    with pytest.raises(OSError, match="directory identity"):
        restore.restore_bundle(source, destination)

    assert not destination.exists()
    assert restore._identities(source) == before
