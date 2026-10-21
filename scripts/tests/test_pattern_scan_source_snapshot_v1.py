"""Compiled source snapshots preserve actual bytes and reject stale resumes."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from research_core.artifact_store import file_digest
from research_core.pattern_scan_source_snapshot_v1 import materialize_archive


def fixture_archive(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    path = tmp_path / "sources.zip"
    files = {"research_core/example.py": b"VALUE = 1\r\n", "params/fixed.json": b'{"fixed":true}\n'}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path, {"sources": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}


def test_actual_snapshot_raw_bytes_and_exact_reuse(tmp_path: Path) -> None:
    archive, identity = fixture_archive(tmp_path)
    root = materialize_archive(archive, tmp_path / "implementation", identity, file_digest(archive))
    code = root / "research_core/example.py"
    assert code.read_bytes() == b"VALUE = 1\r\n" and code.stat().st_nlink == 1
    before = code.stat().st_mtime_ns
    assert materialize_archive(archive, root, identity, file_digest(archive)) == root
    assert code.stat().st_mtime_ns == before
    namespace: dict[str, object] = {}
    exec(compile(code.read_bytes(), str(code), "exec"), namespace)
    assert namespace["VALUE"] == 1


@pytest.mark.parametrize("damage", ["archive", "member", "extra", "hardlink"])
def test_snapshot_identity_changes_never_replaced(tmp_path: Path, damage: str) -> None:
    archive, identity = fixture_archive(tmp_path)
    pin = file_digest(archive)
    root = materialize_archive(archive, tmp_path / "implementation", identity, pin)
    code = root / "research_core/example.py"
    if damage == "archive":
        archive.write_bytes(b"changed retained source archive")
    elif damage == "member":
        code.write_bytes(b"VALUE = 2\n")
    elif damage == "extra":
        (root / "extra.py").write_bytes(b"VALUE = 3\n")
    else:
        alias = tmp_path / "alias.py"
        alias.hardlink_to(code)
    with pytest.raises(ValueError):
        materialize_archive(archive, root, identity, pin)
    assert code.exists()


def test_archive_traversal_rejected_before_output(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../escape.py", b"bad")
    identity = {"sources": {"../escape.py": hashlib.sha256(b"bad").hexdigest()}}
    with pytest.raises(ValueError):
        materialize_archive(archive, tmp_path / "implementation", identity, file_digest(archive))
    assert not (tmp_path / "implementation").exists() and not (tmp_path / "escape.py").exists()
