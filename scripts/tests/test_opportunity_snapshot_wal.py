"""SQLite sidecar transitions must not weaken the pinned main-file contract."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any, Callable

import pytest

from research_core.opportunity_history_inputs import file_hash, snapshot_inputs


def closed_source(tmp_path: Path, *, wal_mode: bool = True) -> Path:
    source = tmp_path / "closed source.sqlite"
    # sqlite3.Connection.__exit__ commits, but does not close the connection.
    with closing(sqlite3.connect(source)) as writer:
        if wal_mode:
            assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("CREATE TABLE example (n INTEGER)")
        writer.execute("INSERT INTO example VALUES (7)")
        writer.commit()
    if wal_mode:
        with closing(sqlite3.connect(source)) as reader:
            assert reader.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert not Path(str(source) + "-wal").exists()
    return source


def identity(path: Path) -> tuple[int, int, int, int]:
    observed = path.stat()
    return observed.st_size, observed.st_mtime_ns, observed.st_dev, observed.st_ino


def intercept_connections(
    monkeypatch: pytest.MonkeyPatch,
    *,
    during_backup: Callable[[], None] | None = None,
    during_reader_init: Callable[[], None] | None = None,
    before_source_close: Callable[[], None] | None = None,
    after_source_close: Callable[[], None] | None = None,
) -> None:
    real_connect = sqlite3.connect
    initialized = False

    class ObservedConnection(sqlite3.Connection):
        source_reader = False

        def execute(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
            nonlocal initialized
            result = super().execute(sql, *args, **kwargs)
            # Hook the schema read that establishes SQLite's read snapshot,
            # independent of whitespace, projections, and the chosen query.
            if self.source_reader and during_reader_init and not initialized and "sqlite_schema" in sql.lower():
                initialized = True
                during_reader_init()
            return result

        def backup(self, target: sqlite3.Connection, **kwargs: Any) -> None:
            super().backup(target, **kwargs)
            if self.source_reader and during_backup:
                during_backup()

        def close(self) -> None:
            try:
                if self.source_reader and before_source_close:
                    before_source_close()
            finally:
                super().close()
            if self.source_reader and after_source_close:
                after_source_close()

    def connect(database: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(database, factory=ObservedConnection, **kwargs)
        connection.source_reader = kwargs.get("uri", False) and "?mode=ro" in str(database)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)


def assert_partial_without_receipt(target: Path, source: Path) -> None:
    assert (target / source.name).exists()
    assert not (target / "input-receipt.json").exists()
    with pytest.raises(FileExistsError, match="Refusing nonempty target"):
        snapshot_inputs({source.name: source}, target)


def test_closed_wal_source_without_sidecar_can_be_pinned(tmp_path: Path) -> None:
    source = closed_source(tmp_path)
    original = file_hash(source)
    original_identity = identity(source)
    # The fixture proves persisted WAL mode and closes every real connection;
    # keeping a writer open would leave an empty WAL and hide the regression.
    assert not Path(str(source) + "-wal").exists()
    target = tmp_path / "snapshot"
    receipt = snapshot_inputs({source.name: source}, target, {source.name: original})
    assert identity(source) == original_identity
    assert file_hash(source) == original
    assert json.loads((target / "input-receipt.json").read_text(encoding="utf-8")) == receipt
    saved = receipt["files"][0]
    assert receipt["schema_version"] == "opportunity-input-receipt.v1"
    assert saved["name"] == source.name
    assert saved["source_sha256"] == original
    assert saved["snapshot_sha256"] == file_hash(target / source.name)
    assert saved["copy_method"] == "sqlite_backup"
    assert saved["quick_check"] == "ok"
    with closing(sqlite3.connect(target / source.name)) as pinned:
        assert pinned.execute("SELECT n FROM example").fetchall() == [(7,)]


def test_real_writer_commit_during_backup_is_rejected_with_unchanged_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = closed_source(tmp_path)
    original = file_hash(source)
    original_identity = identity(source)
    real_connect = sqlite3.connect
    wal = Path(str(source) + "-wal")
    target = tmp_path / "partial"
    evidence: list[bytes] = []
    with ExitStack() as connections:

        def commit() -> None:
            writer = connections.enter_context(closing(real_connect(source)))
            writer.execute("INSERT INTO example VALUES (8)")
            writer.commit()
            evidence.append(wal.read_bytes())
            assert evidence[-1]
            assert file_hash(source) == original

        intercept_connections(monkeypatch, during_backup=commit)
        with pytest.raises(ValueError, match="WAL"):
            snapshot_inputs({source.name: source}, target, {source.name: original})
        assert evidence
        assert file_hash(source) == original
        assert identity(source) == original_identity
        assert wal.read_bytes() == evidence[-1]
        assert_partial_without_receipt(target, source)
        with closing(real_connect(source)) as reader:
            assert reader.execute("SELECT n FROM example ORDER BY n").fetchall() == [(7,), (8,)]


def test_real_writer_commit_during_source_close_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = closed_source(tmp_path)
    original = file_hash(source)
    original_identity = identity(source)
    real_connect = sqlite3.connect
    wal = Path(str(source) + "-wal")
    target = tmp_path / "partial"
    evidence: list[bytes] = []
    with ExitStack() as connections:

        def commit_before_reader_close() -> None:
            writer = connections.enter_context(closing(real_connect(source)))
            writer.execute("INSERT INTO example VALUES (8)")
            writer.commit()
            evidence.append(wal.read_bytes())
            assert evidence[-1]
            assert file_hash(source) == original
            assert identity(source) == original_identity

        intercept_connections(monkeypatch, before_source_close=commit_before_reader_close)
        with pytest.raises(ValueError, match="WAL"):
            snapshot_inputs({source.name: source}, target, {source.name: original})
        assert len(evidence) == 1
        assert file_hash(source) == original
        assert identity(source) == original_identity
        assert wal.read_bytes() == evidence[-1]
        assert_partial_without_receipt(target, source)
        with closing(real_connect(target / source.name)) as pinned:
            assert pinned.execute("SELECT n FROM example ORDER BY n").fetchall() == [(7,)]
        with closing(real_connect(source)) as reader:
            assert reader.execute("SELECT n FROM example ORDER BY n").fetchall() == [(7,), (8,)]


def test_modeled_reader_owned_empty_wal_teardown_to_missing_is_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model platform cleanup only for this test's reader-created zero-byte WAL."""
    source = closed_source(tmp_path)
    original = file_hash(source)
    original_identity = identity(source)
    wal = Path(str(source) + "-wal")
    assert not wal.exists()
    initialized: list[tuple[int, int, int, int]] = []
    closed: list[bool] = []

    def observe_reader_sidecar() -> None:
        assert wal.exists() and wal.stat().st_size == 0
        initialized.append(identity(wal))

    def modeled_platform_teardown() -> None:
        # Some SQLite/platform combinations remove this naturally. On others,
        # simulate that teardown after the real close, solely in tmp_path.
        if wal.exists():
            assert wal.stat().st_size == 0
            assert identity(wal) == initialized[-1]
            wal.unlink()
        closed.append(True)

    intercept_connections(
        monkeypatch,
        before_source_close=observe_reader_sidecar,
        after_source_close=modeled_platform_teardown,
    )
    target = tmp_path / "snapshot"
    receipt = snapshot_inputs({source.name: source}, target, {source.name: original})
    assert len(initialized) == 1 and closed == [True]
    assert not wal.exists()
    assert file_hash(source) == original
    assert identity(source) == original_identity
    assert receipt["files"][0]["source_sha256"] == original
    assert json.loads((target / "input-receipt.json").read_text(encoding="utf-8")) == receipt
    with closing(sqlite3.connect(target / source.name)) as pinned:
        assert pinned.execute("SELECT n FROM example").fetchall() == [(7,)]


@pytest.mark.parametrize("transition", ["deleted", "replaced"])
def test_preexisting_empty_wal_change_during_source_close_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    # DELETE mode leaves this external sidecar untouched by SQLite, making its
    # close-time removal/replacement deterministic on Windows as well.
    source = closed_source(tmp_path, wal_mode=False)
    original = file_hash(source)
    original_identity = identity(source)
    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"")
    original_wal_identity = identity(wal)
    evidence: list[tuple[int, int, int, int] | None] = []

    def change_preexisting_sidecar() -> None:
        assert identity(wal) == original_wal_identity
        if transition == "deleted":
            wal.unlink()
            evidence.append(None)
        else:
            replacement = tmp_path / "replacement empty sidecar"
            replacement.write_bytes(b"")
            observed = replacement.stat()
            os.utime(replacement, ns=(observed.st_atime_ns, original_wal_identity[1] + 10_000_000))
            os.replace(replacement, wal)
            evidence.append(identity(wal))
            assert evidence[-1] != original_wal_identity

    intercept_connections(monkeypatch, after_source_close=change_preexisting_sidecar)
    target = tmp_path / "partial"
    with pytest.raises(ValueError, match="WAL"):
        snapshot_inputs({source.name: source}, target, {source.name: original})
    assert len(evidence) == 1
    assert file_hash(source) == original
    assert identity(source) == original_identity
    if transition == "deleted":
        assert not wal.exists()
    else:
        assert identity(wal) == evidence[-1]
        assert wal.read_bytes() == b""
    assert_partial_without_receipt(target, source)


def test_main_file_modification_during_backup_preserves_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = closed_source(tmp_path, wal_mode=False)
    original = file_hash(source)
    changed: list[bytes] = []

    def modify_main() -> None:
        with source.open("ab") as stream:
            stream.write(b"external fixture modification")
        changed.append(source.read_bytes())

    intercept_connections(monkeypatch, during_backup=modify_main)
    target = tmp_path / "partial"
    with pytest.raises(ValueError, match="changed"):
        snapshot_inputs({source.name: source}, target, {source.name: original})
    assert changed
    assert file_hash(source) != original
    assert source.read_bytes() == changed[-1]
    assert_partial_without_receipt(target, source)


@pytest.mark.parametrize("transition", ["appears", "changes"])
def test_empty_wal_transition_during_backup_is_not_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    source = closed_source(tmp_path, wal_mode=transition == "changes")
    original = file_hash(source)
    original_identity = identity(source)
    wal = Path(str(source) + "-wal")
    changed: list[tuple[int, int, int, int]] = []

    def change_wal() -> None:
        if transition == "appears":
            assert not wal.exists()
            wal.write_bytes(b"")
        else:
            # A WAL reader has already created its empty sidecar. A later
            # identity change must remain fatal even though its bytes are empty.
            assert wal.exists() and wal.stat().st_size == 0
            before = wal.stat()
            os.utime(wal, ns=(before.st_atime_ns, before.st_mtime_ns + 10_000_000))
        changed.append(identity(wal))

    intercept_connections(monkeypatch, during_backup=change_wal)
    target = tmp_path / "partial"
    with pytest.raises(ValueError, match="WAL"):
        snapshot_inputs({source.name: source}, target, {source.name: original})
    assert changed
    assert file_hash(source) == original
    assert identity(source) == original_identity
    # SQLite may unlink its own empty WAL on close; externally created evidence
    # in DELETE mode must remain available to inspect.
    if transition == "appears":
        assert identity(wal) == changed[-1]
        assert wal.read_bytes() == b""
    assert_partial_without_receipt(target, source)


def test_nonempty_wal_appearing_during_reader_init_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = closed_source(tmp_path)
    original = file_hash(source)
    original_identity = identity(source)
    real_connect = sqlite3.connect
    wal = Path(str(source) + "-wal")
    evidence: list[bytes] = []
    target = tmp_path / "partial"
    with ExitStack() as connections:

        def commit() -> None:
            writer = connections.enter_context(closing(real_connect(source)))
            writer.execute("INSERT INTO example VALUES (8)")
            writer.commit()
            evidence.append(wal.read_bytes())
            assert evidence[-1]
            assert file_hash(source) == original

        def unexpected_backup() -> None:
            pytest.fail("A nonempty WAL must be rejected before backup")

        intercept_connections(monkeypatch, during_reader_init=commit, during_backup=unexpected_backup)
        with pytest.raises(ValueError, match="Nonempty source WAL"):
            snapshot_inputs({source.name: source}, target, {source.name: original})
        assert evidence
        assert file_hash(source) == original
        assert identity(source) == original_identity
        assert wal.read_bytes() == evidence[-1]
        assert_partial_without_receipt(target, source)
