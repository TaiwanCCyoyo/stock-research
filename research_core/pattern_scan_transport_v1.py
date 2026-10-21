"""Complete, verified aggregate-only Parquet publication in Git-sized chunks."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from research_core.artifact_store import file_digest, publish_noreplace, read_json, relative_name, safe_path, write_json
from research_core.hhhl_variants_query import CHUNK_BYTES, summary_transport
from research_core.pattern_scan_parquet_v1 import read_frame

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = "pattern-scan-aggregate-transport.v1"
PRIVATE_NAMES = ("observations", "audits", "raw_events", "prices", "indicators", "base_labels", "holding_context", "per_event", "private", "anchors")
RESERVED = re.compile(r"^(?:con(?:in\$|out\$)?|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:[ .]|$)", re.IGNORECASE)


def _name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("logical table name must be a relative POSIX path")
    name = relative_name(value)
    if not name.endswith(".parquet"):
        raise ValueError("logical table requires .parquet suffix")
    for part in name.split("/"):
        if part.endswith((".", " ")) or RESERVED.match(part) or any(ord(char) < 32 or char in '<>"|?*' for char in part):
            raise ValueError("Windows-unsafe logical table name")
    if any(token in name.lower().replace("-", "_").replace(" ", "_") for token in PRIVATE_NAMES):
        raise ValueError("per-event/private table names are forbidden")
    return name


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source/input identity must be a nonblank string")
    return value


def _integer(value: Any, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < int(positive):
        raise ValueError("invalid transport count/size")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("invalid transport SHA256")
    return value


def _descriptors(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported aggregate transport schema")
    _identity(receipt.get("source_id"))
    _identity(receipt.get("input_id"))
    tables = receipt.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise ValueError("complete aggregate table inventory required")
    seen: set[str] = set()
    for name, descriptor in tables.items():
        _name(name)
        folded = name.casefold()
        if folded in seen:
            raise ValueError("case-alias logical table names forbidden")
        seen.add(folded)
        if not isinstance(descriptor, dict) or descriptor.get("path") != name or descriptor.get("transport") != "binary-chunks.v1":
            raise ValueError("invalid logical table descriptor")
        _integer(descriptor.get("bytes"), positive=True)
        _integer(descriptor.get("rows"))
        _digest(descriptor.get("sha256"))
        chunks = descriptor.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("ordered chunks required")
        for index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict) or chunk.get("path") != f"summary.parquet.part-{index:05d}.bin":
                raise ValueError("chunk path/order mismatch")
            size = _integer(chunk.get("bytes"), positive=True)
            if size > CHUNK_BYTES or (index < len(chunks) - 1 and size != CHUNK_BYTES):
                raise ValueError("chunk size differs from binary-chunks.v1")
            _digest(chunk.get("sha256"))
        if sum(chunk["bytes"] for chunk in chunks) != descriptor["bytes"]:
            raise ValueError("chunk sizes differ from logical table")
    if any("/".join(name.split("/")[:index]) in seen for name in seen for index in range(1, len(name.split("/")))):
        raise ValueError("overlapping logical table directories forbidden")
    return tables


def _inventory(root: Path, tables: dict[str, dict[str, Any]]) -> None:
    expected = {"manifest.json"}
    for name, descriptor in tables.items():
        expected.update(f"tables/{name}/{chunk['path']}" for chunk in descriptor["chunks"])
    expected_dirs = {parent.as_posix() for name in expected for parent in Path(name).parents if parent != Path(".")}
    files: set[str] = set()
    directories: set[str] = set()
    for supplied in root.rglob("*"):
        path = safe_path(supplied)
        name = path.relative_to(root).as_posix()
        if path.is_dir():
            directories.add(name)
        elif path.is_file():
            if path.stat().st_nlink != 1:
                raise ValueError("linked transport file forbidden")
            files.add(name)
        else:
            raise ValueError("unsupported transport filesystem entry")
    if files != expected or directories != expected_dirs:
        raise ValueError("transport file/directory inventory differs")


def _consume(root: Path, name: str, descriptor: dict[str, Any]) -> pd.DataFrame:
    buffers = []
    for chunk in descriptor["chunks"]:
        data = safe_path(root / "tables" / name / chunk["path"]).read_bytes()
        if len(data) != chunk["bytes"] or hashlib.sha256(data).hexdigest() != chunk["sha256"]:
            raise ValueError("consumed chunk hash/size mismatch")
        buffers.append(data)
    data = b"".join(buffers)
    if len(data) != descriptor["bytes"] or hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
        raise ValueError("reconstructed table hash/size mismatch")
    frame = read_frame(io.BytesIO(data))
    if len(frame) != descriptor["rows"]:
        raise ValueError("decoded aggregate row count differs")
    return frame


def read_aggregate(output: Path, logical_name: str) -> pd.DataFrame:
    """Verify the same reconstructed bytes decoded by the shared SR codec."""
    root = safe_path(output)
    name = _name(logical_name)
    tables = _descriptors(read_json(root / "manifest.json"))
    if name not in tables:
        raise ValueError("logical table absent from manifest")
    _inventory(root, tables)
    frame = _consume(root, name, tables[name])
    LOGGER.debug("Read aggregate transport table=%s rows=%d", name, len(frame))
    return frame


def export_aggregates(output: Path, tables: Mapping[str, Path], *, source_id: str, input_id: str) -> dict[str, Any]:
    """Publish all caller-allowlisted aggregate rows without filtering or rewriting.

    Failed publication retains its unique staging tree. Existing output is reused
    only after full inventory, bytes, codec, row counts and identity verification.
    A name allowlist is an explicit caller assertion of aggregate-only content;
    this interface never derives that assertion from data values or selects rows.
    """
    root = safe_path(output)
    receipt: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "source_id": _identity(source_id), "input_id": _identity(input_id), "tables": {}}
    # Validate caller names before reading sources; hold only one table's bytes.
    names = [_name(name) for name in tables]
    folded = {name.casefold() for name in names}
    if (
        not names
        or len(folded) != len(names)
        or any("/".join(name.split("/")[:index]) in folded for name in folded for index in range(1, len(name.split("/"))))
    ):
        raise ValueError("nonempty distinct nonoverlapping logical tables required")
    staging = None
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = safe_path(root.parent / f".staging-{root.name}-{uuid.uuid4().hex}")
        staging.mkdir()
    for supplied_name, supplied_path in tables.items():
        name = _name(supplied_name)
        path = safe_path(supplied_path)
        before = file_digest(path)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != before or file_digest(path) != before:
            raise ValueError("aggregate source changed while capturing bytes")
        frame = read_frame(io.BytesIO(data))
        chunks, descriptor = summary_transport(data, len(frame))
        descriptor["path"] = name
        receipt["tables"][name] = descriptor
        if staging is not None:
            directory = safe_path(staging / "tables" / name)
            directory.mkdir(parents=True, exist_ok=True)
            for part, payload in chunks.items():
                with safe_path(directory / part).open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
    descriptors = _descriptors(receipt)
    if staging is None:
        existing = read_json(root / "manifest.json")
        existing_tables = _descriptors(existing)
        _inventory(root, existing_tables)
        for name, descriptor in existing_tables.items():
            _consume(root, name, descriptor)
        if existing != receipt:
            raise ValueError("existing aggregate transport identity/content differs")
        LOGGER.info("Reused verified aggregate transport tables=%d", len(descriptors))
        return existing
    write_json(staging / "manifest.json", receipt)
    _inventory(staging, descriptors)
    for name, descriptor in descriptors.items():
        _consume(staging, name, descriptor)
    publish_noreplace(staging, root)
    LOGGER.info("Published aggregate transport tables=%d", len(descriptors))
    return receipt
