from __future__ import annotations

import errno
import hashlib
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from scripts import opportunity_artifact_publication as publication
from scripts.build_opportunity_history import canonical, read_json, sha, write_json

WINDOWS_PUBLICATION = pytest.mark.skipif(sys.platform != "win32", reason="Publication requires Windows mandatory read-sharing guards")


def _artifacts(tmp_path: Path) -> tuple[Path, dict[Path, str], Path]:
    sources = [tmp_path / "native evidence.bin", tmp_path / "params.bin"]
    for source in sources:
        source.write_bytes(b"original " + source.name.encode())
    output = tmp_path / "catalog"
    output.mkdir()
    partial = output / "completed chunk.bin"
    partial.write_bytes(b"retained export evidence")
    return output / "manifest.json", {source: sha(source) for source in sources}, partial


@WINDOWS_PUBLICATION
def test_valid_sources_publish_complete_json_and_retain_staging_alias(tmp_path: Path) -> None:
    final, identities, partial = _artifacts(tmp_path)
    value = {"rows": [{"code": "A", "value": 1}], "complete": True}
    before = {path: path.read_bytes() for path in identities}
    publication.publish_json_manifest(final, value, identities)
    assert final.read_bytes() == canonical(value)
    assert read_json(final) == value
    prepared = final.parent / ".publication" / final.name
    assert prepared.samefile(final)
    assert prepared.read_bytes() == canonical(value)
    assert partial.read_bytes() == b"retained export evidence"
    for path, raw in before.items():
        assert path.read_bytes() == raw


@WINDOWS_PUBLICATION
def test_writer_prepares_json_before_final_path_becomes_visible(tmp_path: Path) -> None:
    final, identities, _ = _artifacts(tmp_path)
    staged: list[Path] = []

    def writer(path: Path, value: Any) -> None:
        assert not final.exists()
        assert path != final
        write_json(path, value)
        assert not final.exists()
        assert read_json(path) == value
        staged.append(path)

    publication.publish_json_manifest(final, {"complete": True}, identities, writer=writer)
    assert len(staged) == 1
    assert staged[0].samefile(final)
    assert read_json(staged[0]) == {"complete": True}
    assert read_json(final) == {"complete": True}


@WINDOWS_PUBLICATION
def test_existing_final_manifest_is_never_overwritten(tmp_path: Path) -> None:
    final, identities, partial = _artifacts(tmp_path)
    original = b"existing publication bytes"
    final.write_bytes(original)

    def forbidden_writer(path: Path, value: Any) -> None:
        pytest.fail("An existing publication must be rejected before preparation")

    with pytest.raises(FileExistsError):
        publication.publish_json_manifest(final, {"replacement": True}, identities, writer=forbidden_writer)
    assert final.read_bytes() == original
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_writer_failure_releases_all_source_guards_and_retains_prepared_evidence(tmp_path: Path) -> None:
    final, identities, partial = _artifacts(tmp_path)
    prepared: list[Path] = []

    def failing_writer(path: Path, value: Any) -> None:
        write_json(path, value)
        prepared.append(path)
        raise RuntimeError("injected preparation failure")

    with pytest.raises(RuntimeError, match="injected preparation failure"):
        publication.publish_json_manifest(final, {"prepared": True}, identities, writer=failing_writer)
    assert not final.exists()
    assert len(prepared) == 1
    assert read_json(prepared[0]) == {"prepared": True}
    assert partial.read_bytes() == b"retained export evidence"
    # On Windows these writes fail if even one source handle was leaked.
    for source in identities:
        source.write_bytes(b"write after failed publication")
        assert source.read_bytes() == b"write after failed publication"


@WINDOWS_PUBLICATION
def test_windows_guard_denies_source_writer_but_allows_readers(tmp_path: Path) -> None:
    final, identities, _ = _artifacts(tmp_path)
    before = {path: path.read_bytes() for path in identities}
    attempted: list[Path] = []

    def guarded_writer(path: Path, value: Any) -> None:
        for source, original in before.items():
            assert source.read_bytes() == original
            attempted.append(source)
            with pytest.raises(PermissionError):
                source.write_bytes(b"forbidden write during publication")
        write_json(path, value)

    publication.publish_json_manifest(final, {"complete": True}, identities, writer=guarded_writer)
    assert set(attempted) == set(identities)
    assert read_json(final) == {"complete": True}
    for source, original in before.items():
        assert source.read_bytes() == original


@WINDOWS_PUBLICATION
def test_source_mutation_at_atomic_link_boundary_refuses_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, identities, partial = _artifacts(tmp_path)
    target = next(iter(identities))
    before = {path: path.read_bytes() for path in identities}
    real_link = publication.os.link
    attempted = False
    changed = False

    def link_with_mutating_actor(source: Any, destination: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal attempted, changed
        assert not attempted, "Publication must perform a single exclusive commit"
        attempted = True
        # The Windows mandatory guard blocks this writer at commit.
        target.write_bytes(b"source changed at publication commit")
        changed = True
        real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(publication.os, "link", link_with_mutating_actor)
    with pytest.raises((PermissionError, ValueError)):
        publication.publish_json_manifest(final, {"complete": True}, identities)
    assert attempted
    assert not final.exists()
    assert partial.read_bytes() == b"retained export evidence"
    assert read_json(final.parent / ".publication" / final.name) == {"complete": True}
    for source, original in before.items():
        expected = b"source changed at publication commit" if source == target and changed else original
        assert source.read_bytes() == expected


@WINDOWS_PUBLICATION
def test_writer_cannot_resign_changed_prepared_manifest(tmp_path: Path) -> None:
    final, identities, partial = _artifacts(tmp_path)
    before = {path: path.read_bytes() for path in identities}
    prepared: list[Path] = []

    def changing_writer(path: Path, value: Any) -> None:
        write_json(path, {"changed": True})
        prepared.append(path)

    with pytest.raises(ValueError):
        publication.publish_json_manifest(final, {"expected": True}, identities, writer=changing_writer)
    assert not final.exists()
    assert len(prepared) == 1
    assert read_json(prepared[0]) == {"changed": True}
    assert partial.read_bytes() == b"retained export evidence"
    for source, original in before.items():
        assert source.read_bytes() == original


@WINDOWS_PUBLICATION
def test_competing_final_created_at_commit_is_not_overwritten_or_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, identities, partial = _artifacts(tmp_path)
    real_link = publication.os.link
    competing_bytes = b"another publisher owns this manifest"
    attempted = False

    def link_with_competing_publication(source: Any, destination: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal attempted
        assert not attempted
        attempted = True
        Path(destination).write_bytes(competing_bytes)
        real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(publication.os, "link", link_with_competing_publication)
    with pytest.raises(FileExistsError):
        publication.publish_json_manifest(final, {"our prepared manifest": True}, identities)
    assert attempted
    assert final.read_bytes() == competing_bytes
    assert read_json(final.parent / ".publication" / final.name) == {"our prepared manifest": True}
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_full_scale_sources_use_bounded_live_python_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    raw = b"tiny pinned artifact"
    expected = hashlib.sha256(raw).hexdigest()
    identities: dict[Path, str] = {}
    for index in range(17_000):
        path = source_root / f"{index:05}.bin"
        path.write_bytes(raw)
        identities[path] = expected
    output = tmp_path / "catalog"
    output.mkdir()
    final = output / "manifest.json"
    original_open = Path.open
    original_fdopen = publication.os.fdopen
    live = 0
    peak = 0

    class CountedStream:
        def __init__(self, stream: Any) -> None:
            nonlocal live, peak
            self.stream = stream
            self.released = False
            live += 1
            peak = max(peak, live)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.stream, name)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            self.close()

        def close(self) -> None:
            nonlocal live
            if not self.released:
                self.released = True
                try:
                    self.stream.close()
                finally:
                    live -= 1

    def check_capacity() -> None:
        if live >= 32:
            raise OSError(errno.EMFILE, "Injected limit: 32 simultaneous Python/CRT streams")

    def counted_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        check_capacity()
        return CountedStream(original_open(path, *args, **kwargs))

    def counted_fdopen(*args: Any, **kwargs: Any) -> Any:
        # The old guard converts native handles to CRT streams directly,
        # bypassing Path.open; count that route under the same resource limit.
        check_capacity()
        return CountedStream(original_fdopen(*args, **kwargs))

    monkeypatch.setattr(Path, "open", counted_open)
    monkeypatch.setattr(publication.os, "fdopen", counted_fdopen)
    publication.publish_json_manifest(final, {"artifact_count": len(identities)}, identities)
    assert read_json(final) == {"artifact_count": 17_000}
    assert 0 < peak <= 32
    assert live == 0
    assert (output / ".publication" / final.name).samefile(final)


@WINDOWS_PUBLICATION
def test_already_scanned_source_cannot_change_during_final_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, _, partial = _artifacts(tmp_path)
    source_a = tmp_path / "A.bin"
    source_b = tmp_path / "B.bin"
    source_a.write_bytes(b"original A")
    source_b.write_bytes(b"original B")
    identities = {source_a: sha(source_a), source_b: sha(source_b)}
    original_lstat = Path.lstat
    attempted = False

    def lstat_with_late_writer(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal attempted
        info = original_lstat(path, *args, **kwargs)
        if path == source_b and final.exists() and not attempted:
            # Sorted validation has scanned A before checking B after link.
            attempted = True
            source_a.write_bytes(b"late change to already scanned A")
        return info

    monkeypatch.setattr(Path, "lstat", lstat_with_late_writer)
    with pytest.raises((PermissionError, ValueError)):
        publication.publish_json_manifest(final, {"complete": True}, identities)
    assert attempted
    assert not final.exists()
    assert source_a.read_bytes() == b"original A"
    assert source_b.read_bytes() == b"original B"
    assert partial.read_bytes() == b"retained export evidence"
    assert read_json(final.parent / ".publication" / final.name) == {"complete": True}


@pytest.mark.parametrize("existing_final", [False, True])
def test_posix_publication_is_refused_before_writer_or_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_final: bool,
) -> None:
    final, identities, partial = _artifacts(tmp_path)
    if existing_final:
        final.write_bytes(b"existing publication")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    attempted = False

    def forbidden_writer(path: Path, value: Any) -> None:
        nonlocal attempted
        attempted = True
        pytest.fail("Unsupported publication must refuse before invoking its writer")

    monkeypatch.setattr(publication.sys, "platform", "linux")
    with pytest.raises((NotImplementedError, ValueError), match="(?i)windows.*mandatory|mandatory.*windows"):
        publication.publish_json_manifest(final, {"complete": True}, identities, writer=forbidden_writer)
    assert not attempted
    assert not (final.parent / ".publication").exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_writer_cannot_rename_source_ancestor_directory(tmp_path: Path) -> None:
    final, _, partial = _artifacts(tmp_path)
    ancestor = tmp_path / "frozen sources"
    nested = ancestor / "nested"
    nested.mkdir(parents=True)
    sources = [nested / "A.bin", nested / "B.bin"]
    for source in sources:
        source.write_bytes(b"original source " + source.name.encode())
    identities = {source: sha(source) for source in sources}
    before = {source: source.read_bytes() for source in sources}
    moved = tmp_path / "renamed sources"
    attempted = False

    def writer_with_directory_rename(path: Path, value: Any) -> None:
        nonlocal attempted
        attempted = True
        ancestor.rename(moved)
        write_json(path, value)

    with pytest.raises((PermissionError, ValueError)):
        publication.publish_json_manifest(final, {"complete": True}, identities, writer=writer_with_directory_rename)
    assert attempted
    assert not final.exists()
    assert ancestor.is_dir()
    assert not moved.exists()
    for source, original in before.items():
        assert source.read_bytes() == original
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_guard_acquisition_failure_releases_earlier_source_handles(tmp_path: Path) -> None:
    final, identities, partial = _artifacts(tmp_path)
    before = {source: source.read_bytes() for source in identities}
    missing = tmp_path / "zzzz missing last artifact.bin"
    assert sorted([*identities, missing])[-1] == missing
    identities[missing] = hashlib.sha256(b"missing artifact expected bytes").hexdigest()
    attempted = False

    def forbidden_writer(path: Path, value: Any) -> None:
        nonlocal attempted
        attempted = True
        pytest.fail("Every source guard must be acquired before manifest preparation")

    with pytest.raises((OSError, ValueError)):
        publication.publish_json_manifest(final, {"complete": True}, identities, writer=forbidden_writer)
    assert not attempted
    assert not final.exists()
    assert not missing.exists()
    assert partial.read_bytes() == b"retained export evidence"
    for source, original in before.items():
        assert source.read_bytes() == original
        source.write_bytes(b"write after incomplete guard acquisition")
        assert source.read_bytes() == b"write after incomplete guard acquisition"


def test_posix_rebuild_refuses_before_reading_source_or_creating_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.rebuild_saved_opportunity_catalog import rebuild_saved_catalog

    source = tmp_path / "nonexistent source" / "manifest.json"
    output = tmp_path / "new output"
    attempted_read = False

    def forbidden_read(path: Path) -> bytes:
        nonlocal attempted_read
        attempted_read = True
        pytest.fail("Unsupported rebuild must refuse before reading any artifact")

    monkeypatch.setattr(publication.sys, "platform", "linux")
    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    with pytest.raises(ValueError, match="(?i)windows.*mandatory|mandatory.*windows"):
        rebuild_saved_catalog(source, output)
    assert not attempted_read
    assert not source.exists()
    assert not output.exists()


def _make_file_symlink_or_skip(alias: Path, physical: Path) -> None:
    try:
        os.symlink(physical, alias, target_is_directory=False)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314 or error.errno in (errno.ENOSYS, errno.EOPNOTSUPP):
            pytest.skip(f"OS does not permit this symlink fixture: {error}")
        raise


@WINDOWS_PUBLICATION
def test_source_symlink_alias_is_rejected_before_manifest_writer(tmp_path: Path) -> None:
    final, identities, partial = _artifacts(tmp_path)
    physical = next(iter(identities))
    original = physical.read_bytes()
    alias = tmp_path / "source alias.bin"
    _make_file_symlink_or_skip(alias, physical)
    identities[alias] = identities.pop(physical)
    before = {source: source.read_bytes() for source in identities}
    attempted = False

    def forbidden_writer(path: Path, value: Any) -> None:
        nonlocal attempted
        attempted = True
        pytest.fail("A reparse source alias must be refused before manifest preparation")

    with pytest.raises(ValueError, match="(?i)reparse|physical|symlink"):
        publication.publish_json_manifest(final, {"complete": True}, identities, writer=forbidden_writer)
    assert not attempted
    assert not final.exists()
    assert physical.read_bytes() == original
    assert alias.is_symlink()
    assert alias.samefile(physical)
    for source, raw in before.items():
        assert source.read_bytes() == raw
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_rebuild_does_not_erase_saved_native_symlink_alias(tmp_path: Path) -> None:
    from scripts.rebuild_saved_opportunity_catalog import rebuild_saved_catalog
    from scripts.tests.test_rebuild_saved_opportunity_catalog import saved_catalog

    source = saved_catalog(tmp_path / "task")
    task_root = source.parent.parent
    native = task_root / "runs/native/A.json.gz"
    original = native.read_bytes()
    physical = native.with_name("A-physical.json.gz")
    native.rename(physical)
    _make_file_symlink_or_skip(native, physical)
    before = {path: path.read_bytes() for path in task_root.rglob("*") if path.is_file()}
    output = task_root / "catalog-v2"
    with pytest.raises(ValueError, match="(?i)reparse|physical|symlink"):
        rebuild_saved_catalog(source, output)
    assert not (output / "manifest.json").exists()
    assert native.is_symlink()
    assert native.samefile(physical)
    assert physical.read_bytes() == original
    for path, raw in before.items():
        assert path.read_bytes() == raw


@pytest.fixture
def directory_junction(tmp_path: Path) -> Iterator[Callable[[Path, Path], None]]:
    aliases: list[Path] = []

    def create(alias: Path, physical: Path) -> None:
        assert sys.platform == "win32"
        assert alias.absolute().is_relative_to(tmp_path.absolute())
        assert physical.absolute().is_relative_to(tmp_path.absolute())
        assert physical.is_dir()
        assert not alias.exists()
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(physical)],
            shell=False,
            check=True,
            capture_output=True,
        )
        aliases.append(alias)

    try:
        yield create
    finally:
        # Remove only each junction directory entry before pytest's recursive
        # tmp cleanup; os.rmdir does not recurse into its physical target.
        for alias in reversed(aliases):
            os.rmdir(alias)


@WINDOWS_PUBLICATION
def test_sources_beneath_directory_junction_are_rejected_before_writer(
    tmp_path: Path,
    directory_junction: Callable[[Path, Path], None],
) -> None:
    final, _, partial = _artifacts(tmp_path)
    physical = tmp_path / "physical sources"
    physical.mkdir()
    originals = {"A.bin": b"original A", "B.bin": b"original B"}
    for name, raw in originals.items():
        (physical / name).write_bytes(raw)
    alias = tmp_path / "source junction"
    directory_junction(alias, physical)
    identities = {alias / name: sha(physical / name) for name in originals}
    attempted = False

    def forbidden_writer(path: Path, value: Any) -> None:
        nonlocal attempted
        attempted = True
        pytest.fail("A junction ancestor must be refused before manifest preparation")

    with pytest.raises(ValueError, match="(?i)reparse|physical|junction"):
        publication.publish_json_manifest(final, {"complete": True}, identities, writer=forbidden_writer)
    assert not attempted
    assert not final.exists()
    assert alias.is_dir()
    for name, raw in originals.items():
        assert (physical / name).read_bytes() == raw
        assert (alias / name).read_bytes() == raw
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_rebuild_does_not_erase_saved_native_directory_junction(
    tmp_path: Path,
    directory_junction: Callable[[Path, Path], None],
) -> None:
    from scripts.rebuild_saved_opportunity_catalog import rebuild_saved_catalog
    from scripts.tests.test_rebuild_saved_opportunity_catalog import saved_catalog

    source = saved_catalog(tmp_path / "task")
    task_root = source.parent.parent
    native_dir = task_root / "runs/native"
    physical = native_dir.with_name("native-physical")
    native_dir.rename(physical)
    before = {path: path.read_bytes() for path in task_root.rglob("*") if path.is_file()}
    directory_junction(native_dir, physical)
    output = task_root / "catalog-v2"
    with pytest.raises(ValueError, match="(?i)reparse|physical|junction"):
        rebuild_saved_catalog(source, output)
    assert not (output / "manifest.json").exists()
    assert native_dir.is_dir()
    for path, raw in before.items():
        assert path.read_bytes() == raw
    for path in physical.iterdir():
        assert (native_dir / path.name).read_bytes() == path.read_bytes()


@WINDOWS_PUBLICATION
def test_output_parent_directory_junction_is_rejected_before_staging(
    tmp_path: Path,
    directory_junction: Callable[[Path, Path], None],
) -> None:
    physical_final, identities, partial = _artifacts(tmp_path)
    physical_output = physical_final.parent
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    alias = tmp_path / "output junction"
    directory_junction(alias, physical_output)
    alias_final = alias / physical_final.name
    attempted = False

    def forbidden_writer(path: Path, value: Any) -> None:
        nonlocal attempted
        attempted = True
        pytest.fail("A junction output namespace must be refused before preparation")

    with pytest.raises(ValueError, match="(?i)reparse|physical|junction"):
        publication.publish_json_manifest(alias_final, {"complete": True}, identities, writer=forbidden_writer)
    assert not attempted
    assert not alias_final.exists()
    assert not physical_final.exists()
    assert not (physical_output / ".publication").exists()
    assert alias.is_dir()
    assert {path: path.read_bytes() for path in physical_output.rglob("*") if path.is_file()} == {
        path: raw for path, raw in before.items() if path.is_relative_to(physical_output)
    }
    for path, raw in before.items():
        assert path.read_bytes() == raw
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_staging_replacement_after_guard_release_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, identities, partial = _artifacts(tmp_path)
    before = {source: source.read_bytes() for source in identities}
    value = {"complete": True, "rows": [{"code": "A"}]}
    prepared = final.parent / ".publication" / final.name
    competing_bytes = b"another writer owns this staging replacement"
    original_guard = publication._guard_artifacts
    attempted = False

    @contextmanager
    def guard_with_post_release_actor(mapping: Any, **kwargs: Any) -> Iterator[Any]:
        nonlocal attempted
        with original_guard(mapping, **kwargs) as validate:
            yield validate
        if prepared in mapping and not attempted:
            # The original prepared inode is still linked at final. Replace
            # only the staging directory entry once its mandatory guard closes.
            attempted = True
            prepared.unlink()
            prepared.write_bytes(competing_bytes)

    monkeypatch.setattr(publication, "_guard_artifacts", guard_with_post_release_actor)
    publication.publish_json_manifest(final, value, identities)
    assert attempted
    assert final.read_bytes() == canonical(value)
    assert prepared.read_bytes() == competing_bytes
    assert not prepared.samefile(final)
    for source, original in before.items():
        assert source.read_bytes() == original
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_rollback_preserves_final_replacement_at_identity_check_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, identities, partial = _artifacts(tmp_path)
    before = {source: source.read_bytes() for source in identities}
    value = {"complete": True, "rows": [{"code": "A"}]}
    prepared = final.parent / ".publication" / final.name
    competing_bytes = b"another writer owns this final replacement"
    original_validate = publication._validate_artifact
    original_lstat = Path.lstat
    original_api = publication._windows_file_api
    final_name = os.path.normcase(os.path.abspath(final))
    rollback_started = False
    attempted = False

    def replace_once() -> None:
        nonlocal attempted
        if not attempted:
            attempted = True
            final.unlink()
            final.write_bytes(competing_bytes)

    def fail_postpublication_prepared_validation(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal rollback_started
        if path == prepared and final.exists():
            rollback_started = True
            raise ValueError("injected postpublication validation failure")
        original_validate(path, *args, **kwargs)

    def lstat_with_replacement(path: Path, *args: Any, **kwargs: Any) -> Any:
        info = original_lstat(path, *args, **kwargs)
        if path == final and rollback_started:
            # Return the original entry's stat after replacing it, exposing
            # the old stat-then-unlink rollback's deletion of a foreign file.
            replace_once()
        return info

    def api_with_delete_open_actor() -> Any:
        api = original_api()
        real_create = api[0]

        def create_with_replacement(name: Any, desired_access: Any, *args: Any) -> Any:
            filename = str(getattr(name, "value", name))
            if filename.startswith("\\\\?\\UNC\\"):
                filename = "\\\\" + filename[8:]
            elif filename.startswith("\\\\?\\"):
                filename = filename[4:]
            access = int(getattr(desired_access, "value", desired_access))
            if rollback_started and access & 0x00010000 and os.path.normcase(os.path.abspath(filename)) == final_name:
                # A handle-based rollback must inspect the identity of the
                # file actually opened after this replacement, then retain it.
                replace_once()
            return real_create(name, desired_access, *args)

        return (create_with_replacement, *api[1:])

    monkeypatch.setattr(publication, "_validate_artifact", fail_postpublication_prepared_validation)
    monkeypatch.setattr(Path, "lstat", lstat_with_replacement)
    monkeypatch.setattr(publication, "_windows_file_api", api_with_delete_open_actor)
    with pytest.raises(ValueError, match="injected postpublication validation failure"):
        publication.publish_json_manifest(final, value, identities)
    assert rollback_started
    assert attempted, "The replacement actor must reach a rollback identity boundary"
    assert final.read_bytes() == competing_bytes
    assert prepared.read_bytes() == canonical(value)
    assert not prepared.samefile(final)
    for source, original in before.items():
        assert source.read_bytes() == original
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_postpublication_failure_retracts_owned_final_and_retains_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, identities, partial = _artifacts(tmp_path)
    before = {source: source.read_bytes() for source in identities}
    value = {"complete": True}
    prepared = final.parent / ".publication" / final.name
    original_validate = publication._validate_artifact
    injected = False

    def fail_after_publication(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal injected
        if path == prepared and final.exists():
            injected = True
            raise ValueError("injected postpublication failure without competitor")
        original_validate(path, *args, **kwargs)

    monkeypatch.setattr(publication, "_validate_artifact", fail_after_publication)
    with pytest.raises(ValueError, match="injected postpublication failure without competitor"):
        publication.publish_json_manifest(final, value, identities)
    assert injected
    assert not final.exists()
    assert prepared.read_bytes() == canonical(value)
    for source, raw in before.items():
        assert source.read_bytes() == raw
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_rollback_delete_handle_prevents_replacement_during_identity_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, identities, partial = _artifacts(tmp_path)
    before = {source: source.read_bytes() for source in identities}
    value = {"complete": True}
    prepared = final.parent / ".publication" / final.name
    original_validate = publication._validate_artifact
    original_identity = publication._windows_file_identity
    rollback_started = False
    attempted = False

    def fail_after_publication(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal rollback_started
        if path == prepared and final.exists():
            rollback_started = True
            raise ValueError("injected failure before guarded rollback identity")
        original_validate(path, *args, **kwargs)

    def identity_with_replacement_actor(handle: Any) -> bytes:
        nonlocal attempted
        if rollback_started and not attempted:
            attempted = True
            assert final.exists()
            # Source guards have closed; the newly opened DELETE handle must
            # itself prevent replacing the directory entry while ID is read.
            with pytest.raises(PermissionError):
                final.unlink()
        return original_identity(handle)

    monkeypatch.setattr(publication, "_validate_artifact", fail_after_publication)
    monkeypatch.setattr(publication, "_windows_file_identity", identity_with_replacement_actor)
    with pytest.raises(ValueError, match="injected failure before guarded rollback identity"):
        publication.publish_json_manifest(final, value, identities)
    assert rollback_started
    assert attempted
    assert not final.exists()
    assert prepared.read_bytes() == canonical(value)
    for source, raw in before.items():
        assert source.read_bytes() == raw
    assert partial.read_bytes() == b"retained export evidence"


@WINDOWS_PUBLICATION
def test_reader_blocks_rollback_without_replacing_original_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final, identities, partial = _artifacts(tmp_path)
    before = {source: source.read_bytes() for source in identities}
    value = {"complete": True}
    prepared = final.parent / ".publication" / final.name
    original_validate = publication._validate_artifact
    readers: list[Any] = []

    def fail_with_live_reader(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == prepared and final.exists():
            # A normal Python reader omits FILE_SHARE_DELETE and therefore
            # blocks acquiring rollback's DELETE handle after guards close.
            readers.append(final.open("rb"))
            raise ValueError("injected postpublication failure with live reader")
        original_validate(path, *args, **kwargs)

    monkeypatch.setattr(publication, "_validate_artifact", fail_with_live_reader)
    try:
        with pytest.raises(ValueError, match="injected postpublication failure with live reader") as caught:
            publication.publish_json_manifest(final, value, identities)
        assert readers
        assert any("rollback could not complete" in note.lower() for note in getattr(caught.value, "__notes__", ()))
        assert final.read_bytes() == canonical(value)
        assert prepared.samefile(final)
        assert prepared.read_bytes() == canonical(value)
        for source, raw in before.items():
            assert source.read_bytes() == raw
        assert partial.read_bytes() == b"retained export evidence"
    finally:
        for reader in readers:
            reader.close()

    # With the test-owned reader released, these writes/rename demonstrate
    # that publication did not leak source guards or its namespace anchor.
    for source, raw in before.items():
        source.write_bytes(raw)
    retained = final.with_name("retained after rollback.json")
    final.rename(retained)
    assert retained.read_bytes() == canonical(value)
    assert prepared.samefile(retained)
