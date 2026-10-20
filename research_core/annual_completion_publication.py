"""Bounded, lossless transport for the four annual-completion result files.

The ZIP contains original result and receipt bytes. A load verifies the three
small result members once against the receipt and consumes those same bytes;
input fingerprints are provenance only and never opened or hashed here.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import logging
import os
import stat
import uuid
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from research_core.artifact_store import publish_noreplace, relative_name, safe_path
from research_core.json_integrity import strict_json_object
from research_core.producer_data import REPO_ROOT

LOGGER = logging.getLogger(__name__)
ARCHIVE = "publication.zip"
MAX_ARCHIVE_BYTES = 500 * 1024
MAX_MEMBER_BYTES = 500 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
RESULT_NAMES = {"results": "results.json", "admission": "admission-audit.json", "performance": "performance.json"}
MEMBERS = (*RESULT_NAMES.values(), "run-receipt.json")
MEMBER_SCHEMAS = {
    "results.json": "annual-completion-result.v2",
    "admission-audit.json": "annual-completion-admission.v2",
    "performance.json": "annual-completion-performance.v2",
    "run-receipt.json": "run-receipt.v1",
}


def _bounded_file(path: Path, limit: int) -> bytes:
    with safe_path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"publication file exceeds byte limit: {path.name}")
    return raw


def _plain_members(root: Path) -> dict[str, bytes]:
    members = {name: _bounded_file(root / name, MAX_MEMBER_BYTES) for name in MEMBERS}
    if sum(map(len, members.values())) > MAX_TOTAL_BYTES:
        raise ValueError("publication exceeds total byte limit")
    return members


def _archive_members(path: Path) -> dict[str, bytes]:
    raw_archive = _bounded_file(path, MAX_ARCHIVE_BYTES)
    try:
        with zipfile.ZipFile(io.BytesIO(raw_archive)) as archive:
            entries = archive.infolist()
            names = [relative_name(entry.filename) for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("duplicate publication ZIP members")
            if len(names) != len(MEMBERS) or set(names) != set(MEMBERS):
                raise ValueError("publication ZIP must have exactly the four result members")
            total = 0
            members = {}
            for entry in entries:
                mode = entry.external_attr >> 16
                attributes = entry.external_attr & 0xFFFF
                if (
                    entry.orig_filename != entry.filename
                    or entry.is_dir()
                    or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                    or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
                ):
                    raise ValueError(f"linked or nonregular ZIP member forbidden: {entry.filename}")
                if entry.flag_bits & 1:
                    raise ValueError(f"encrypted ZIP member forbidden: {entry.filename}")
                if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError(f"unsupported ZIP compression: {entry.filename}")
                if not 0 <= entry.file_size <= MAX_MEMBER_BYTES:
                    raise ValueError(f"publication member exceeds byte limit: {entry.filename}")
                total += entry.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("publication exceeds total byte limit")
                with archive.open(entry, "r") as stream:
                    raw = stream.read(MAX_MEMBER_BYTES + 1)
                if len(raw) != entry.file_size or len(raw) > MAX_MEMBER_BYTES:
                    raise ValueError(f"publication member size mismatch: {entry.filename}")
                members[entry.filename] = raw
            return members
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError("invalid publication ZIP") from error


def _verified(members: dict[str, bytes], root: Path, repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        publication_path = relative_name(root.relative_to(safe_path(REPO_ROOT if repo_root is None else repo_root)).as_posix())
    except ValueError as error:
        raise ValueError("publication root must be a repository-relative directory") from error
    if set(members) != set(MEMBERS):
        raise ValueError("exact publication member names required")
    parsed: dict[str, dict[str, Any]] = {}
    for name, raw in members.items():
        value = strict_json_object(raw)
        if value.get("schema") != MEMBER_SCHEMAS[name]:
            raise ValueError(f"publication schema mismatch: {name}")
        parsed[name] = value
    receipt = parsed["run-receipt.json"]
    if not isinstance(parsed["admission-audit.json"].get("unresolved"), list):
        raise ValueError("publication admission unresolved list required")
    run_id = receipt.get("run_id")
    if not isinstance(run_id, str) or not run_id or any(value.get("run_id") != run_id for value in parsed.values()):
        raise ValueError("publication run_id mismatch")
    results = receipt.get("results")
    if not isinstance(results, dict) or set(results) != set(RESULT_NAMES):
        raise ValueError("receipt must identify exactly the three result names")
    for key, name in RESULT_NAMES.items():
        identity = results[key]
        if not isinstance(identity, dict):
            raise ValueError(f"receipt result identity required: {key}")
        source_path = identity.get("path")
        if not isinstance(source_path, str) or relative_name(source_path) != f"{publication_path}/{name}":
            raise ValueError(f"receipt result publication path mismatch: {key}")
        size = identity.get("bytes")
        digest = identity.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size != len(members[name]):
            raise ValueError(f"receipt result byte size mismatch: {name}")
        if not isinstance(digest, str) or hashlib.sha256(members[name]).hexdigest() != digest:
            raise ValueError(f"receipt result SHA-256 mismatch: {name}")
    return parsed


def load_publication(root: Path, *, repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load verified JSON keyed by the four exact filenames, without extraction.

    An existing ZIP always takes precedence, including a corrupt ZIP. Expanded
    local files are accepted only when no ZIP exists. Present public reading
    projections must match the already consumed ZIP bytes; callers retain this
    return value instead of repeatedly loading and verifying within one operation.
    """
    root = safe_path(root)
    archive = safe_path(root / ARCHIVE)
    has_archive = archive.exists()
    members = _archive_members(archive) if has_archive else _plain_members(root)
    if has_archive:
        for name in ("results.json", "performance.json"):
            projection = safe_path(root / name)
            if projection.exists() and _bounded_file(projection, MAX_MEMBER_BYTES) != members[name]:
                raise ValueError(f"publication projection byte mismatch: {name}")
    return _verified(members, root, repo_root)


def pack_publication(root: Path) -> Path:
    """Verify and pack original bounded bytes into a new no-replace ZIP."""
    root = safe_path(root)
    destination = safe_path(root / ARCHIVE)
    if destination.exists():
        raise FileExistsError(f"publication archive already exists: {destination}")
    members = _plain_members(root)
    _verified(members, root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in MEMBERS:
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, members[name], compresslevel=9)
    raw = buffer.getvalue()
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError("publication ZIP exceeds compressed byte limit")
    staging = safe_path(root / f".publication-{uuid.uuid4().hex}.staging")
    with staging.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    publish_noreplace(staging, destination)
    LOGGER.info("Packed annual completion publication files=%d raw_bytes=%d zip_bytes=%d", len(members), sum(map(len, members.values())), len(raw))
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, default=REPO_ROOT / "tasks/20261013-annual-winner-rotation/publications/completion-v2")
    args = parser.parse_args(argv)
    print(pack_publication(args.publication))  # noqa: T201 - CLI output path
    return 0
