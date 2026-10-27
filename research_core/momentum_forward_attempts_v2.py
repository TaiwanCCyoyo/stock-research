"""Process-crash journal; terminal files are authoritative, JSONL is a projection.

Only a cooperating local owner's released OS lock proves that recovery may act.
No PID/age heuristics, history truncation, or market reads belong in this module.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from research_core.artifact_store import publish_noreplace, release_os_lock, safe_path, try_os_lock

LOGGER = logging.getLogger(__name__)
JOURNAL = "attempt-journal-v2"
LEDGER = "attempts-v2.jsonl"
PROTOCOL = "local-os-lock.v2"
START_SCHEMA = "momentum-forward-start.v2"
TERMINAL_SCHEMA = "momentum-forward-terminal.v2"
OUTCOMES = {"on_time", "late", "cohort_recovered", "already_frozen", "refused", "failed", "not_recorded", "interrupted"}
Checkpoint = Callable[[str], None]


class JournalError(RuntimeError):
    """Preserve the evidence and require operator inspection."""


class JournalBusyError(JournalError):
    """An OS lock is busy or its ownership cannot be established."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode(raw: bytes, source: Path) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (UnicodeError, ValueError) as error:
        raise JournalError(f"corrupt journal/ledger at {source}; bytes preserved: {error}") from error


def _validate(value: dict[str, Any], attempt_id: str, schema: str) -> None:
    if value.get("schema") != schema or value.get("attempt_id") != attempt_id:
        raise JournalError(f"invalid schema/attempt identity: {attempt_id}; bytes preserved")
    try:
        if not isinstance(attempt_id, str):
            raise ValueError("invalid id type")
        if uuid.UUID(attempt_id).hex != attempt_id:
            raise ValueError("noncanonical id")
        stamp = datetime.fromisoformat(value["attempted_at_utc"])
        if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError("start must be UTC")
        if value["mode"] not in {"manual", "scheduled"} or not isinstance(value["code_commit"], str) or not value["code_commit"]:
            raise ValueError("invalid mode/code identity")
        requested = value["requested_day"]
        if requested is not None and (not isinstance(requested, str) or datetime.strptime(requested, "%Y-%m-%d").strftime("%Y-%m-%d") != requested):
            raise ValueError("invalid requested day")
        if schema == TERMINAL_SCHEMA:
            if value["outcome"] not in OUTCOMES:
                raise ValueError("invalid outcome")
            if value["outcome"] == "interrupted":
                if value["finished_at_utc"] is not None or value["completion"] != "unknown":
                    raise ValueError("recovery cannot invent completion")
                datetime.fromisoformat(value["recovered_at_utc"])
            else:
                datetime.fromisoformat(value["finished_at_utc"])
    except (KeyError, TypeError, ValueError) as error:
        raise JournalError(f"invalid journal contract: {attempt_id}; bytes preserved: {error}") from error


def _publish(path: Path, value: dict[str, Any]) -> None:
    staging = path.with_name(f".staging-{path.name}-{uuid.uuid4().hex}")
    with staging.open("xb") as stream:
        stream.write(_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    publish_noreplace(staging, path)


@contextmanager
def root_lock(root: Path, name: str) -> Iterator[bool]:
    """Stable lock files are never deleted/replaced, including after a crash."""
    root = safe_path(root)
    root.mkdir(parents=True, exist_ok=True)
    with safe_path(root / name).open("a+b") as handle:
        locked = try_os_lock(handle)
        try:
            yield locked
        finally:
            if locked:
                release_os_lock(handle)


def _ledger(root: Path) -> list[dict[str, Any]]:
    path = safe_path(root / LEDGER)
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise JournalError(f"partial JSONL at {path}; bytes preserved; automatic repair stopped")
    entries = []
    seen: set[str] = set()
    for line in raw.splitlines():
        entry = _decode(line, path)
        attempt_id = entry.get("attempt_id", "")
        _validate(entry, attempt_id, TERMINAL_SCHEMA)
        if attempt_id in seen:
            raise JournalError(f"duplicate attempt_id in {path}; bytes preserved")
        seen.add(attempt_id)
        entries.append(entry)
    return entries


def append_terminal(root: Path, terminal: dict[str, Any], *, checkpoint: Checkpoint | None = None) -> None:
    """Check and append under one OS lock; never repair an incomplete physical row."""
    _validate(terminal, terminal["attempt_id"], TERMINAL_SCHEMA)
    source = safe_path(root / JOURNAL / terminal["attempt_id"] / "terminal.json")
    if _decode(source.read_bytes(), source) != terminal:
        raise JournalError("projection differs from durable terminal; bytes preserved")
    with root_lock(root, ".attempts-v2-append.lock") as locked:
        if not locked:
            raise JournalBusyError("v2 append lock busy/unknown; durable terminal retained")
        entries = _ledger(root)
        existing = next((entry for entry in entries if entry["attempt_id"] == terminal["attempt_id"]), None)
        if existing is not None:
            if existing != terminal:
                raise JournalError("ledger conflicts with durable terminal; bytes preserved")
            return
        with safe_path(root / LEDGER).open("ab") as stream:
            stream.write(_bytes(terminal))
            stream.flush()
            os.fsync(stream.fileno())
        if checkpoint is not None:
            checkpoint("appended")


class Attempt:
    """Own the per-attempt OS lock from before start publication through append."""

    def __init__(self, root: Path, *, requested_day: str | None, mode: str, code_commit: str = "unknown", checkpoint: Checkpoint | None = None) -> None:
        self.root = safe_path(root)
        self.attempt_id = uuid.uuid4().hex
        self.path = safe_path(self.root / JOURNAL / self.attempt_id)
        self.path.mkdir(parents=True, exist_ok=False)
        self.checkpoint = checkpoint
        self.owner: IO[bytes] = (self.path / "owner.lock").open("x+b")
        self.closed = False
        if not try_os_lock(self.owner):
            self.owner.close()
            raise JournalBusyError("cannot establish new attempt ownership")
        self.started: dict[str, Any] = {
            "schema": START_SCHEMA,
            "attempt_id": self.attempt_id,
            "attempted_at_utc": utc_now(),
            "requested_day": requested_day,
            "mode": mode,
            "code_commit": code_commit,
            "owner_host": socket.gethostname(),
            "owner_protocol": PROTOCOL,
        }
        try:
            _validate(self.started, self.attempt_id, START_SCHEMA)
            _publish(self.path / "started.json", self.started)
            LOGGER.info("Durable forward start %s mode=%s", self.attempt_id, mode)
            if checkpoint is not None:
                checkpoint("started")
        except BaseException:
            self.close()
            raise

    def finish(self, fields: dict[str, Any]) -> dict[str, Any]:
        terminal = {**self.started, **fields, "schema": TERMINAL_SCHEMA, "attempt_id": self.attempt_id}
        _validate(terminal, self.attempt_id, TERMINAL_SCHEMA)
        destination = self.path / "terminal.json"
        if destination.exists():
            if _decode(destination.read_bytes(), destination) != terminal:
                raise JournalError("attempt already has a different terminal; bytes preserved")
        else:
            _publish(destination, terminal)
        if self.checkpoint is not None:
            self.checkpoint("terminal")
        append_terminal(self.root, terminal, checkpoint=self.checkpoint)
        LOGGER.info("Forward terminal %s outcome=%s", self.attempt_id, terminal["outcome"])
        return terminal

    def close(self) -> None:
        if not self.closed:
            release_os_lock(self.owner)
            self.owner.close()
            self.closed = True


def recover(root: Path) -> list[str]:
    """Reconcile abandoned local attempts, leaving active/unknown owners pending.

    Acquiring the original lock proves the cooperating owner no longer owns it;
    a foreign/unknown protocol, missing lock, or failed lock attempt proves nothing.
    """
    journal = safe_path(root / JOURNAL)
    pending: list[str] = []
    if not journal.exists():
        return pending
    for path in sorted(journal.iterdir()):
        safe_path(path)
        start_path = safe_path(path / "started.json")
        if not path.is_dir() or not start_path.exists():
            continue  # no durable acceptance; retain any staging evidence
        started = _decode(start_path.read_bytes(), start_path)
        _validate(started, path.name, START_SCHEMA)
        if started.get("owner_protocol") != PROTOCOL or started.get("owner_host") != socket.gethostname():
            pending.append(path.name)
            continue
        try:
            handle = safe_path(path / "owner.lock").open("r+b")
        except OSError:
            pending.append(path.name)
            continue
        with handle:
            if not try_os_lock(handle):
                pending.append(path.name)
                continue
            try:
                terminal_path = safe_path(path / "terminal.json")
                if terminal_path.exists():
                    terminal = _decode(terminal_path.read_bytes(), terminal_path)
                    _validate(terminal, path.name, TERMINAL_SCHEMA)
                    if any(
                        terminal.get(key) != started.get(key)
                        for key in ("attempt_id", "attempted_at_utc", "requested_day", "mode", "owner_host", "owner_protocol")
                    ):
                        raise JournalError("terminal conflicts with start identity; bytes preserved")
                else:
                    terminal = {
                        **started,
                        "schema": TERMINAL_SCHEMA,
                        "outcome": "interrupted",
                        "completion": "unknown",
                        "finished_at_utc": None,
                        "recovered_at_utc": utc_now(),
                        "reason": "local OS ownership released without a durable terminal; day/cohort state is not completion evidence",
                    }
                    _publish(terminal_path, terminal)
                append_terminal(root, terminal)
            finally:
                release_os_lock(handle)
    if pending:
        LOGGER.info("Forward attempts pending (active/unknown ownership): %s", pending)
    return pending


def read_attempts(root: Path, *, include_legacy: bool = True) -> list[dict[str, Any]]:
    """Physical source tags, no timestamp deduplication of legacy history."""
    entries: list[dict[str, Any]] = []
    legacy = safe_path(root / "attempts.jsonl")
    if include_legacy and legacy.exists():
        entries.extend({**_decode(line, legacy), "physical_ledger": "attempts.jsonl"} for line in legacy.read_bytes().splitlines() if line.strip())
    with root_lock(root, ".attempts-v2-append.lock") as locked:
        if not locked:
            raise JournalBusyError("v2 append lock busy/unknown")
        entries.extend({**entry, "physical_ledger": LEDGER} for entry in _ledger(root))
    return entries
