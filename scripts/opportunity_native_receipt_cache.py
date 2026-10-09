"""Opt-in, bounded disk cache for successful native semantic receipts."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

CACHE_SCHEMA = "opportunity-native-verification-cache.v1"
RECEIPT_SCHEMA = "opportunity-native-source-semantics.v1"
MAX_CACHE_BYTES = 16 * 1024
_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_RECEIPT_FIELDS = ("schema", "status", "method_count", "wave_count", "launch_count")
_CACHE_DIRECTORY: contextvars.ContextVar[Path | None] = contextvars.ContextVar("opportunity_native_receipt_cache_directory", default=None)


def _key(value: str) -> str:
    if not isinstance(value, str) or _KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("semantic receipt cache key must be 64 hexadecimal characters")
    return value.lower()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("semantic receipt must be an object")
    if value.get("schema") != RECEIPT_SCHEMA or value.get("status") != "verified":
        raise ValueError("only complete verified source semantic receipts may be cached")
    for field in ("method_count", "wave_count", "launch_count"):
        count = value.get(field)
        if type(count) is not int or count < 0:
            raise ValueError(f"semantic receipt {field} must be a nonnegative integer")
    # Keep only the small stable contract, never diagnostics or failed scopes.
    return {field: value[field] for field in _RECEIPT_FIELDS}


def _is_reparse_or_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _check_path_chain(path: Path) -> bool:
    """Reject links/reparse points in every existing component of the root."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    for component in reversed((absolute, *absolute.parents)):
        if _is_reparse_or_link(component):
            return False
    return True


def _root(directory: Path, *, create: bool) -> Path | None:
    path = Path(os.path.abspath(os.fspath(directory)))
    if not _check_path_chain(path):
        return None
    if create:
        path.mkdir(parents=True, exist_ok=True)
        if not _check_path_chain(path):
            return None
    elif not path.is_dir():
        return None
    return path


def _regular_file_descriptor(path: Path) -> int | None:
    if _is_reparse_or_link(path):
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if not stat.S_ISREG(metadata.st_mode) or attributes & reparse_flag:
            os.close(descriptor)
            return None
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def semantic_receipt_cache(directory: Path | None) -> Iterator[None]:
    """Enable receipt reuse within this context; ``None`` disables it."""
    token = _CACHE_DIRECTORY.set(Path(directory) if directory is not None else None)
    try:
        yield
    finally:
        _CACHE_DIRECTORY.reset(token)


def load_receipt(key: str) -> dict[str, Any] | None:
    """Read one small verified receipt; invalid or unavailable cache data is a miss."""
    normalized_key = _key(key)
    directory = _CACHE_DIRECTORY.get()
    if directory is None:
        return None
    try:
        root = _root(directory, create=False)
        if root is None:
            return None
        path = root / f"{normalized_key}.json"
        descriptor = _regular_file_descriptor(path)
        if descriptor is None:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            if os.fstat(stream.fileno()).st_size > MAX_CACHE_BYTES:
                return None
            payload = stream.read(MAX_CACHE_BYTES + 1)
        if len(payload) > MAX_CACHE_BYTES:
            return None
        envelope = json.loads(payload.decode("utf-8"))
        if not isinstance(envelope, dict) or envelope.get("schema") != CACHE_SCHEMA or envelope.get("key") != normalized_key:
            return None
        receipt = envelope.get("receipt")
        digest = envelope.get("receiptSha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        if hashlib.sha256(_canonical(receipt)).hexdigest() != digest:
            return None
        return _receipt(receipt)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError, OverflowError):
        return None


def save_receipt(key: str, receipt: dict[str, Any]) -> None:
    """Atomically save one compact complete receipt when the context opts in."""
    normalized_key = _key(key)
    compact_receipt = _receipt(receipt)
    directory = _CACHE_DIRECTORY.get()
    if directory is None:
        return
    temporary: Path | None = None
    try:
        root = _root(directory, create=True)
        if root is None:
            return
        target = root / f"{normalized_key}.json"
        if _is_reparse_or_link(target):
            return
        receipt_digest = hashlib.sha256(_canonical(compact_receipt)).hexdigest()
        payload = _canonical({
            "schema": CACHE_SCHEMA,
            "key": normalized_key,
            "receipt": compact_receipt,
            "receiptSha256": receipt_digest,
        })
        if len(payload) > MAX_CACHE_BYTES:
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=".native-verification-", suffix=".tmp", dir=root)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
        if not _check_path_chain(root) or _is_reparse_or_link(target):
            return
        os.replace(temporary, target)
        temporary = None
    except OSError:
        # This cache is an optimization only; the caller must run full verification.
        return
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
