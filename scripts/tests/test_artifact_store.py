"""Native no-replace publication and fail-closed backend regression tests."""

import ctypes
import errno
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_core import artifact_store as store


@pytest.mark.parametrize("directory", [False, True])
def test_native_publication_moves_complete_sibling(tmp_path: Path, directory: bool) -> None:
    source, target = tmp_path / ".staged", tmp_path / "final"
    if directory:
        source.mkdir()
        (source / "data.bin").write_bytes(b"complete")
    else:
        source.write_bytes(b"complete")
    store.publish_noreplace(source, target)
    assert not source.exists()
    assert (target / "data.bin" if directory else target).read_bytes() == b"complete"


@pytest.mark.parametrize("source_dir,target_kind", [(False, "file"), (False, "empty"), (True, "file"), (True, "empty"), (True, "populated")])
def test_native_publication_never_replaces_existing_target(tmp_path: Path, source_dir: bool, target_kind: str) -> None:
    source, target = tmp_path / ".staged", tmp_path / "final"
    if source_dir:
        source.mkdir()
        (source / "data.bin").write_bytes(b"staged")
    else:
        source.write_bytes(b"staged")
    if target_kind == "file":
        target.write_bytes(b"foreign")
    else:
        target.mkdir()
        if target_kind == "populated":
            (target / "foreign.bin").write_bytes(b"foreign")
    with pytest.raises(FileExistsError):
        store.publish_noreplace(source, target)
    assert (source / "data.bin" if source_dir else source).read_bytes() == b"staged"
    if target_kind == "file":
        assert target.read_bytes() == b"foreign"
    elif target_kind == "empty":
        assert list(target.iterdir()) == []
    else:
        assert (target / "foreign.bin").read_bytes() == b"foreign"


@pytest.mark.parametrize("bad_path", ["source", "destination"])
def test_null_path_cannot_be_truncated_by_native_backend(tmp_path: Path, bad_path: str) -> None:
    source, target = tmp_path / ".staged", tmp_path / "final"
    source.write_bytes(b"staged")
    with pytest.raises(ValueError, match="embedded null"):
        store.publish_noreplace(
            Path(str(source) + "\0other") if bad_path == "source" else source, Path(str(target) + "\0other") if bad_path == "destination" else target
        )
    assert source.read_bytes() == b"staged" and not target.exists()


def test_cross_directory_publication_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / ".staged"
    source.write_bytes(b"staged")
    destination = tmp_path / "another" / "final"
    with pytest.raises(ValueError, match="sibling"):
        store.publish_noreplace(source, destination)
    assert source.exists() and not destination.exists()


def test_unsupported_platform_has_no_overwriting_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, destination = tmp_path / ".staged", tmp_path / "final"
    source.write_bytes(b"staged")
    destination.write_bytes(b"foreign")
    monkeypatch.setattr(store.sys, "platform", "unsupported")
    with pytest.raises(OSError) as failure:
        store.publish_noreplace(source, destination)
    assert failure.value.errno == errno.ENOTSUP
    assert source.read_bytes() == b"staged" and destination.read_bytes() == b"foreign"


@pytest.mark.parametrize("code", [0, errno.EEXIST, errno.ENOSYS, errno.EINVAL, errno.EXDEV])
def test_linux_backend_uses_noreplace_flag_and_propagates_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    source, destination = tmp_path / ".staged", tmp_path / "final"
    source.write_bytes(b"staged")
    observed: list[tuple[Any, ...]] = []

    class FakeRename:
        argtypes: list[Any]
        restype: Any

        def __call__(self, *args: Any) -> int:
            observed.append(args)
            ctypes.set_errno(code)
            return 0 if code == 0 else -1

    function = FakeRename()
    monkeypatch.setattr(store.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(renameat2=function))
    if code == 0:
        store._linux_publish_noreplace(source, destination)
    else:
        with pytest.raises(OSError) as failure:
            store._linux_publish_noreplace(source, destination)
        assert failure.value.errno == code
    assert observed == [(-100, os.fsencode(source), -100, os.fsencode(destination), 1)]
    assert function.argtypes == [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    assert function.restype == ctypes.c_int
    assert source.read_bytes() == b"staged" and not destination.exists()


def test_missing_linux_api_refuses_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, destination = tmp_path / ".staged", tmp_path / "final"
    source.write_bytes(b"staged")
    monkeypatch.setattr(store.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace())
    with pytest.raises(OSError) as failure:
        store._linux_publish_noreplace(source, destination)
    assert failure.value.errno == errno.ENOTSUP
    assert source.read_bytes() == b"staged" and not destination.exists()


def test_new_directory_is_published_whole_and_never_merged_into_an_existing_one(tmp_path: Path) -> None:
    target = tmp_path / "v2"
    store.publish_new_directory(target, {"a.json": b"{}", "nested/b.bin": b"bytes"})
    assert (target / "a.json").read_bytes() == b"{}"
    assert (target / "nested" / "b.bin").read_bytes() == b"bytes"
    assert [p.name for p in tmp_path.iterdir()] == ["v2"]

    with pytest.raises(FileExistsError):
        store.publish_new_directory(target, {"a.json": b"replaced"})
    assert (target / "a.json").read_bytes() == b"{}"
    with pytest.raises(ValueError, match="unsafe artifact name"):
        store.publish_new_directory(tmp_path / "v3", {"../escape": b"x"})
    assert not (tmp_path / "v3").exists()


def test_generated_metadata_is_verified_before_visibility_and_never_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "payload/metadata.json"
    target.parent.mkdir()
    scratch = tmp_path / "owned-scratch"
    original = store.relocate_noreplace
    payload = b'{"complete":true}'
    observed: list[Path] = []

    def publish(source: Path, destination: Path) -> None:
        assert source.parent == scratch and destination == target
        assert source.read_bytes() == payload and not target.exists()
        observed.append(source)
        original(source, destination)

    monkeypatch.setattr(store, "relocate_noreplace", publish)
    store.publish_generated_bytes(target, payload, scratch=scratch)
    assert len(observed) == 1 and not observed[0].exists()
    assert target.read_bytes() == payload and list(scratch.iterdir()) == []
    before = target.stat()
    with pytest.raises(FileExistsError):
        store.publish_generated_bytes(target, b"different", scratch=scratch)
    after = target.stat()
    assert (before.st_dev, before.st_ino, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_mtime_ns)
    assert target.read_bytes() == payload and list(scratch.iterdir()) == []
