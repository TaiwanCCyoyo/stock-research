"""Publish a verified manifest exclusively while retaining artifact read guards."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from functools import cache
from pathlib import Path
from typing import Any

from scripts.build_opportunity_history import canonical, write_json


@cache
def _windows_file_api() -> tuple[Any, Any, Any, Any]:
    if sys.platform != "win32":
        raise RuntimeError("Windows file-sharing guards require Windows")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    information = kernel.GetFileInformationByHandleEx
    information.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    information.restype = wintypes.BOOL
    disposition = kernel.SetFileInformationByHandle
    disposition.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    disposition.restype = wintypes.BOOL
    return create, close, information, disposition


def require_publication_support() -> None:
    """Reject platforms without mandatory protection against existing writers."""
    if sys.platform != "win32":
        raise ValueError("Saved catalog publication requires Windows mandatory file-sharing guards; POSIX advisory locks cannot protect uncooperative writers")


def _windows_file_identity(handle: int) -> bytes:
    import ctypes

    _, _, information, _ = _windows_file_api()
    # FILE_ID_INFO is an 8-byte volume identifier plus a 128-bit file ID.
    # Comparing native IDs also works where Python stat exposes fewer ID bits.
    # https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info
    identity = ctypes.create_string_buffer(24)
    if not information(handle, 18, identity, len(identity)):
        raise ctypes.WinError(ctypes.get_last_error())
    return identity.raw


@contextmanager
def _open_windows_handle(path: Path, *, access: int, sharing: int, directory: bool = False) -> Iterator[int]:
    require_publication_support()
    import ctypes

    create, close, information, _ = _windows_file_api()
    name = os.path.abspath(path)
    if not name.startswith("\\\\?\\"):
        name = "\\\\?\\UNC\\" + name[2:] if name.startswith("\\\\") else "\\\\?\\" + name
    flags = 0x00200000 | (0x02000000 if directory else 0x08000000)
    handle = create(name, access, sharing, None, 3, flags, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attributes = ctypes.create_string_buffer(8)
        if not information(handle, 9, attributes, len(attributes)):
            raise ctypes.WinError(ctypes.get_last_error())
        if int.from_bytes(attributes.raw[:4], "little") & 0x00000400:
            raise ValueError(f"Publication guards require physical paths without reparse points: {path}")
        yield handle
    finally:
        close(handle)


@contextmanager
def _open_guarded(path: Path, *, directory: bool = False) -> Iterator[bytes]:
    # Keep kernel HANDLEs, never a CRT descriptor/BinaryIO for each artifact.
    # File guards deny write/delete handles and writable mappings. Directory
    # guards allow reads/writes but deny renaming/deleting the namespace.
    # https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
    access = 0 if directory else 0x80000000
    sharing = 0x00000003 if directory else 0x00000001
    with _open_windows_handle(path, access=access, sharing=sharing, directory=directory) as handle:
        yield _windows_file_identity(handle)


def _retract_manifest(path: Path, expected_identity: bytes) -> None:
    import ctypes

    try:
        # Open the final link, not the prepared alias. Deny other read/write/
        # delete handles while identity-checking and marking this link deleted.
        with _open_windows_handle(path, access=0x00010000, sharing=0) as handle:
            if _windows_file_identity(handle) != expected_identity:
                return
            _, _, _, disposition = _windows_file_api()
            delete = ctypes.c_ubyte(1)  # FILE_DISPOSITION_INFO.DeleteFile (BOOLEAN)
            # FileDispositionInfo=4 marks the link selected by this handle.
            # No pathname deletion follows the identity check.
            # https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle
            if not disposition(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
                raise ctypes.WinError(ctypes.get_last_error())
    except FileNotFoundError:
        return


def _validate_artifact(path: Path, expected: str, guarded_identity: bytes) -> None:
    if sys.platform != "win32":
        require_publication_support()
        return
    import msvcrt

    # At most one Python/CRT stream is live, regardless of artifact count.
    # Native guard handles remain held across every scan and the final commit.
    with path.open("rb") as stream:
        if _windows_file_identity(msvcrt.get_osfhandle(stream.fileno())) != guarded_identity:
            raise ValueError(f"Publication artifact path replaced: {path}")
        if _file_identity(path.lstat()) != _file_identity(os.fstat(stream.fileno())):
            raise ValueError(f"Publication artifact path replaced: {path}")
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"Publication artifact hash mismatch: {path}")


def _file_identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


@contextmanager
def _guard_artifacts(identities: Mapping[Path, str], *, namespace: Path | None = None) -> Iterator[Callable[[], None]]:
    with ExitStack() as stack:
        directories = {parent for path in identities for parent in Path(os.path.abspath(path)).parents}
        if namespace is not None:
            directory = Path(os.path.abspath(namespace))
            directories.update((directory, *directory.parents))
        for directory in sorted(directories, key=lambda item: (len(item.parts), str(item))):
            stack.enter_context(_open_guarded(directory, directory=True))
        guards = [(path, expected, stack.enter_context(_open_guarded(path))) for path, expected in sorted(identities.items())]

        def validate() -> None:
            for path, expected, guarded_identity in guards:
                _validate_artifact(path, expected, guarded_identity)

        validate()
        yield validate


def publish_json_manifest(
    path: Path,
    value: Any,
    identities: Mapping[Path, str],
    *,
    writer: Callable[[Path, Any], None] = write_json,
) -> None:
    """Expose complete prepared bytes once; never overwrite an existing manifest.

    Windows native read-sharing handles cover the validation/commit interval;
    hashing uses one temporary CRT reader. POSIX publication is refused before
    preparation because advisory locks cannot protect uncooperative writers.
    Future external edits remain reader-detectable. Staging evidence is retained
    after success because its directory entry may change once guards close.
    """
    require_publication_support()
    # Preserve the final directory entry for the exclusive-create check; do
    # not follow an unexpected manifest symlink into another destination.
    path = Path(os.path.abspath(path))
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Manifest publication already exists: {path}")
    expected = hashlib.sha256(canonical(value)).hexdigest()
    staging = path.parent / ".publication"
    prepared = staging / path.name
    published = False
    published_identity: bytes | None = None
    with ExitStack() as anchors:
        try:
            with _guard_artifacts(identities, namespace=path.parent) as validate_sources:
                staging.mkdir(exist_ok=False)
                writer(prepared, value)
                with prepared.open("rb+") as stream:
                    os.fsync(stream.fileno())
                with _guard_artifacts({prepared: expected}) as validate_prepared:
                    validate_sources()
                    prepared_identity = _file_identity(prepared.lstat())
                    # Keep the original object/ID alive after strong guards
                    # close. Metadata access permits a later DELETE handle;
                    # READ|DELETE sharing still denies writes to this object.
                    anchor = anchors.enter_context(_open_windows_handle(prepared, access=0, sharing=0x00000005))
                    published_identity = _windows_file_identity(anchor)
                    # A same-filesystem hard-link create is an atomic,
                    # exclusive commit. Retain the staging alias as evidence.
                    os.link(prepared, path)
                    published = True
                    validate_sources()
                    validate_prepared()
                    if _file_identity(path.lstat()) != prepared_identity:
                        raise ValueError(f"Published manifest path replaced: {path}")
        except BaseException as error:
            # Strong read guards must close before requesting DELETE access.
            # The anchor prevents identity reuse; deletion stays handle-bound.
            if published and published_identity is not None:
                try:
                    _retract_manifest(path, published_identity)
                except (OSError, ValueError) as rollback_error:
                    error.add_note(f"Manifest rollback could not complete; retaining evidence at {path}: {rollback_error}")
            raise
