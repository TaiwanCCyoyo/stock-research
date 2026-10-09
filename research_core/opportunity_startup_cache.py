"""Authenticated local memo of an already verified web projection.

This is disposable performance state, never research evidence or a trust anchor.
The caller must hash every currently referenced source before accepting a memo.
An installation-local key prevents edited cache JSON from minting validation.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from scripts.opportunity_native_receipt_cache import _check_path_chain, _regular_file_descriptor

logger = logging.getLogger(__name__)
SCHEMA = "opportunity-web-startup-memo.v1"
MAX_FILE_BYTES = 96 * 1024 * 1024
# Full-market raw/adjusted arrays are considerably larger before compression.
MAX_DECODED_BYTES = 512 * 1024 * 1024


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class StartupCache:
    """Only successful full-reader results are saved by the owning web reader."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.absolute()

    def _key(self, *, create: bool) -> bytes | None:
        if not _check_path_chain(self.directory):
            return None
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "authentication.bin"
        if not _check_path_chain(path):
            return None
        if create:
            try:
                with path.open("xb") as stream:
                    stream.write(secrets.token_bytes(32))
            except FileExistsError:
                pass
        descriptor = _regular_file_descriptor(path)
        if descriptor is None:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            key = stream.read(33)
        return key if len(key) == 32 else None

    def _path(self, context: dict[str, Any]) -> Path:
        return self.directory / (hashlib.sha256(canonical(context)).hexdigest() + ".json.gz")

    def load(self, context: dict[str, Any]) -> dict[str, Any] | None:
        try:
            key = self._key(create=False)
            if key is None:
                return None
            path = self._path(context)
            if not _check_path_chain(path):
                return None
            descriptor = _regular_file_descriptor(path)
            if descriptor is None:
                return None
            with os.fdopen(descriptor, "rb") as stream:
                payload = stream.read(MAX_FILE_BYTES + 1)
            if len(payload) > MAX_FILE_BYTES or len(payload) < 65:
                return None
            signature, compressed = payload[:64], payload[65:]
            expected = hmac.new(key, canonical(context) + b"\0" + compressed, hashlib.sha256).hexdigest().encode()
            if payload[64:65] != b"\n" or not hmac.compare_digest(signature, expected):
                return None
            # Bound expansion independently of the compressed-file limit.
            import io

            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                decoded = stream.read(MAX_DECODED_BYTES + 1)
            if len(decoded) > MAX_DECODED_BYTES:
                return None
            result = json.loads(decoded)
            if (
                not isinstance(result, dict)
                or result.get("schema") != SCHEMA
                or result.get("context") != context
                or not isinstance(result.get("projection"), dict)
            ):
                return None
            logger.info("Reusing authenticated historical web projection")
            return result["projection"]
        except (OSError, ValueError, TypeError, RecursionError, OverflowError):
            logger.debug("Historical startup memo unavailable", exc_info=True)
            return None

    def save(self, context: dict[str, Any], projection: dict[str, Any]) -> None:
        temporary: Path | None = None
        try:
            key = self._key(create=True)
            if key is None:
                return
            encoded = canonical({"schema": SCHEMA, "context": context, "projection": projection})
            if len(encoded) > MAX_DECODED_BYTES:
                logger.warning("Historical startup projection exceeds decoded memo limit (%d bytes)", len(encoded))
                return
            compressed = gzip.compress(encoded, compresslevel=3, mtime=0)
            if len(compressed) + 65 > MAX_FILE_BYTES:
                logger.warning("Historical startup projection exceeds compressed memo limit (%d bytes)", len(compressed))
                return
            signature = hmac.new(key, canonical(context) + b"\0" + compressed, hashlib.sha256).hexdigest().encode()
            target = self._path(context)
            if not _check_path_chain(target):
                return
            descriptor, name = tempfile.mkstemp(prefix=".startup-", suffix=".tmp", dir=self.directory)
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(signature + b"\n" + compressed)
                stream.flush()
                os.fsync(stream.fileno())
            if not _check_path_chain(target):
                return
            os.replace(temporary, target)
            logger.info("Saved historical startup memo (%d decoded, %d compressed bytes)", len(encoded), len(compressed))
            temporary = None
        except (OSError, ValueError, TypeError, RecursionError, OverflowError):
            logger.warning("Historical startup memo could not be saved", exc_info=True)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # A disposable memo must never prevent verified history from loading.
                    logger.warning("Historical startup temporary memo could not be removed", exc_info=True)
