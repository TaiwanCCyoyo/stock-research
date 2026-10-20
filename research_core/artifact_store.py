"""Small shared primitives for additive, verified local research artifacts."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, Any


def safe_path(path: Path) -> Path:
    """Reject traversal and symlink/NTFS reparse ancestors, including junctions."""
    if ".." in path.parts:
        raise ValueError(f"path traversal forbidden: {path}")
    absolute = path.absolute()
    for ancestor in (absolute, *absolute.parents):
        if ancestor.exists() or ancestor.is_symlink():
            attributes = getattr(ancestor.lstat(), "st_file_attributes", 0)
            if ancestor.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                raise ValueError(f"linked/reparse path forbidden: {ancestor}")
    return absolute


def relative_name(value: str) -> str:
    """Validate portable artifact names before combining them with a root."""
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if not value or "\\" in value or ":" in value or posix.is_absolute() or windows.drive or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError(f"unsafe artifact name: {value}")
    if any(not part for part in value.split("/")):
        raise ValueError(f"unsafe artifact name: {value}")
    return value


def try_os_lock(handle: IO[bytes]) -> bool:
    """Take an exclusive OS lock on the first byte; the OS drops it when the process ends."""
    handle.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def release_os_lock(handle: IO[bytes]) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _linux_publish_noreplace(source: Path, destination: Path) -> None:
    """Linux renameat2(RENAME_NOREPLACE); unsupported kernels/FS fail closed."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as error:
        raise OSError(errno.ENOTSUP, "atomic no-replace publication unavailable", str(destination)) from error
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    # Absolute paths ignore AT_FDCWD (-100). Flag 1 is RENAME_NOREPLACE.
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def publish_noreplace(source: Path, destination: Path) -> None:
    """Atomically move a staged sibling file/tree without replacing any final.

    No check-then-rename fallback: failure retains staging and existing bytes.
    Windows os.rename and Linux renameat2 provide native no-replace semantics.
    """
    if "\0" in str(source) or "\0" in str(destination):
        raise ValueError("embedded null in publication path")
    source, destination = map(safe_path, (source, destination))
    if source.parent != destination.parent:
        raise ValueError("publication requires sibling paths on one filesystem")
    if sys.platform == "win32":
        os.rename(source, destination)
    elif sys.platform == "linux":
        _linux_publish_noreplace(source, destination)
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace publication unavailable", str(destination))


def relocate_noreplace(source: Path, destination: Path) -> None:
    """Transfer owned files within one filesystem without copying or replacing.

    Unlike final publication, a journaled handoff can cross parent directories.
    The native no-replace operation still fails closed and never falls back to
    copy/delete across filesystems.
    """
    source, destination = map(safe_path, (source, destination))
    if source.stat().st_dev != destination.parent.stat().st_dev:
        raise OSError(errno.EXDEV, "single-copy handoff requires the same filesystem", str(destination))
    if sys.platform == "win32":
        os.rename(source, destination)
    elif sys.platform == "linux":
        _linux_publish_noreplace(source, destination)
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace handoff unavailable", str(destination))


def publish_new_directory(destination: Path, files: dict[str, bytes]) -> None:
    """Publish `files` as a brand-new directory in one step; never replace or merge into one.

    Every file is written and fsynced into a fresh sibling `.staging-<name>-<uuid>` tree, which
    then moves to `destination` with `publish_noreplace`. A failure leaves `destination` absent
    and keeps the staging tree for diagnosis.
    """
    destination = safe_path(destination)
    if destination.exists():
        raise FileExistsError(errno.EEXIST, "publication target already exists", str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = safe_path(destination.parent / f".staging-{destination.name}-{uuid.uuid4().hex}")
    staging.mkdir()
    for name, data in files.items():
        path = safe_path(staging / relative_name(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    publish_noreplace(staging, destination)


def file_digest(path: Path) -> str:
    with safe_path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def object_digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    with safe_path(path).open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def publish_generated_bytes(path: Path, payload: bytes, *, scratch: Path) -> None:
    """Atomically publish generated metadata; retain interrupted scratch for its owner.

    Scratch must be outside the payload tree at the caller's chosen location.
    A fresh file on every attempt lets a crash leave partial bytes without making
    the intended destination visible or preventing a retry. Existing destinations
    are never replaced. The caller owns scratch retirement after its handoff.
    """
    path, scratch = map(safe_path, (path, scratch))
    if path.exists():
        raise FileExistsError(errno.EEXIST, "generated destination already exists", str(path))
    scratch.mkdir(parents=True, exist_ok=True)
    if scratch.stat().st_dev != path.parent.stat().st_dev:
        raise OSError(errno.EXDEV, "generated metadata requires the same filesystem", str(path))
    staged = safe_path(scratch / f"{uuid.uuid4().hex}.metadata")
    with staged.open("xb") as stream:
        if stream.write(payload) != len(payload):
            raise OSError("incomplete generated metadata write")
        stream.flush()
        os.fsync(stream.fileno())
    if staged.stat().st_size != len(payload) or file_digest(staged) != hashlib.sha256(payload).hexdigest():
        raise ValueError("generated metadata differs before publication")
    relocate_noreplace(staged, path)


def read_json(path: Path, *, max_bytes: int = 8_000_000) -> dict[str, Any]:
    with safe_path(path).open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("manifest exceeds size limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def copy_verified(source: Path, destination: Path, expected: str) -> None:
    """Copy exclusively and fail if either source observation differs."""
    source, destination = safe_path(source), safe_path(destination)
    if file_digest(source) != expected:
        raise ValueError(f"source changed before copy: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if file_digest(source) != expected or file_digest(destination) != expected:
        raise ValueError(f"source changed or copy mismatch: {source}")


def describe_file(root: Path, path: Path) -> dict[str, Any]:
    path = safe_path(path)
    return {"path": relative_name(path.relative_to(root).as_posix()), "bytes": path.stat().st_size, "sha256": file_digest(path)}


def verify_files(root: Path, entries: list[dict[str, Any]]) -> None:
    """Verify every declared descriptor; a manifest is evidence, not authority."""
    names: set[str] = set()
    for entry in entries:
        name = relative_name(entry["path"])
        if name in names:
            raise ValueError(f"duplicate artifact: {name}")
        names.add(name)
        path = safe_path(root / name)
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"invalid descriptor: {name}")
        if path.stat().st_size != size or file_digest(path) != digest:
            raise ValueError(f"artifact hash/size mismatch: {name}")
