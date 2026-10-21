"""Materialize and validate the actual compiled source snapshot, without links."""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
import zipfile
from pathlib import Path
from typing import Any

from research_core.artifact_store import file_digest, publish_noreplace, relative_name
from research_core.research_data_paths import _check_tree, _checked_path

LOGGER = logging.getLogger(__name__)


def materialize_archive(archive_path: Path, destination: Path, identity: dict[str, Any], archive_sha256: str) -> Path:
    """Hash the consumed ZIP buffer and the stored source bytes before dispatch.

    The snapshot is primary-owned scratch, outside formatter-managed worktrees.
    SourceFinder compiles these files; later working-tree formatting cannot alter
    the source of an already running study. Existing snapshots are never replaced.
    """
    archive_path, destination = _checked_path(archive_path), _checked_path(destination)
    raw = archive_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != archive_sha256:
        raise ValueError("retained source archive changed")
    expected = identity["sources"]
    if not isinstance(expected, dict) or not expected:
        raise ValueError("nonempty source inventory required")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("source archive inventory differs")
        for name in names:
            relative_name(name)
        if not destination.exists():
            staging = _checked_path(destination.parent / f".implementation-{uuid.uuid4().hex}")
            staging.mkdir()
            for name in sorted(names):
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != expected[name]:
                    raise ValueError("source archive member identity differs")
                target = _checked_path(staging / name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(data)
            publish_noreplace(staging, destination)
    _check_tree(destination)
    actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
    if actual != set(expected):
        raise ValueError("compiled source snapshot inventory differs")
    for name, digest in expected.items():
        if file_digest(_checked_path(destination / name)) != digest:
            raise ValueError("compiled source snapshot member changed")
    LOGGER.info("Validated actual compiled source snapshot files=%d path=%s", len(expected), destination)
    return destination
