"""Forward-log location and one-way migration (synthetic data in tmp_path only)."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from research_core import momentum_forward_attempts_v2 as journal
from research_core import momentum_forward_paths as paths
from scripts import record_momentum_forward_day as v1_script
from scripts import record_momentum_forward_day_v2 as v2_script

LEDGER = b'{"a":1}\n{"a":2}\n'


def _legacy(tmp_path: Path) -> Path:
    legacy = tmp_path / "primary" / "tasks" / paths.TASK_ID / "forward-log"
    (legacy / "days").mkdir(parents=True)
    (legacy / "cohort.json").write_bytes(b'{"c":1}')
    (legacy / "attempts.jsonl").write_bytes(LEDGER)
    (legacy / "days" / "2026-10-22.parquet").write_bytes(b"day-one")
    (legacy / ".attempts-v2-append.lock").write_bytes(b"x")
    return legacy


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    shared = tmp_path / "shared"
    legacy = _legacy(tmp_path)
    monkeypatch.setattr(paths, "shared_data_root", lambda: shared)
    monkeypatch.setattr(paths, "legacy_forward_log_root", lambda repo_root=paths.REPO_ROOT: legacy)
    return legacy, shared / "tasks" / paths.TASK_ID / "forward-log"


def test_default_root_uses_patched_shared_root(locations: tuple[Path, Path]) -> None:
    assert paths.default_forward_log_root() == locations[1]


def test_migration_copies_byte_identically_and_leaves_legacy(locations: tuple[Path, Path]) -> None:
    legacy, root = locations
    before = _snapshot(legacy)
    assert paths.resolve_forward_log_root(None) == root
    assert _snapshot(legacy) == before
    expected = {k: v for k, v in before.items() if not k.endswith(".lock")}
    copied = _snapshot(root)
    assert copied.pop(paths.MIGRATION_LOCK) == b""  # destination coordination file, never copied from legacy
    assert copied == expected


def test_rerun_is_noop_and_grown_ledger_accepted(locations: tuple[Path, Path]) -> None:
    legacy, root = locations
    assert paths.migrate_legacy_forward_log(legacy, root) == (3, 0)
    assert paths.migrate_legacy_forward_log(legacy, root) == (0, 3)
    (root / "attempts.jsonl").write_bytes(LEDGER + b'{"a":3}\n')
    assert paths.migrate_legacy_forward_log(legacy, root) == (0, 3)
    assert (root / "attempts.jsonl").read_bytes() == LEDGER + b'{"a":3}\n'


def test_differing_day_file_raises(locations: tuple[Path, Path]) -> None:
    legacy, root = locations
    (root / "days").mkdir(parents=True)
    (root / "days" / "2026-10-22.parquet").write_bytes(b"other")
    with pytest.raises(paths.ForwardLogMigrationError, match="2026-10-22.parquet"):
        paths.resolve_forward_log_root(None)
    assert not (root / "attempts.jsonl").exists() or (root / "attempts.jsonl").read_bytes() == LEDGER


def test_differing_ledger_prefix_raises(locations: tuple[Path, Path]) -> None:
    legacy, root = locations
    root.mkdir(parents=True)
    (root / "attempts.jsonl").write_bytes(b'{"a":9}\n{"a":2}\n{"a":3}\n')
    with pytest.raises(paths.ForwardLogMigrationError, match="attempts.jsonl"):
        paths.migrate_legacy_forward_log(legacy, root)
    (root / "attempts.jsonl").write_bytes(b'{"a":1}\n')  # shorter than legacy
    with pytest.raises(paths.ForwardLogMigrationError, match="attempts.jsonl"):
        paths.migrate_legacy_forward_log(legacy, root)


def test_explicit_root_skips_migration(locations: tuple[Path, Path], tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    assert paths.resolve_forward_log_root(explicit) == explicit
    assert not locations[1].exists()
    assert not explicit.exists()


def test_missing_legacy_is_noop(tmp_path: Path) -> None:
    assert paths.migrate_legacy_forward_log(tmp_path / "none", tmp_path / "root") == (0, 0)
    assert paths.migrate_legacy_forward_log(None, tmp_path / "root") == (0, 0)


def test_interrupted_copy_recovers(locations: tuple[Path, Path]) -> None:
    legacy, root = locations
    (root / "days").mkdir(parents=True)
    (root / "days" / f"{paths._STAGING_PREFIX}deadbeef-2026-10-22.parquet").write_bytes(b"day")  # truncated leftover
    copied, present = paths.migrate_legacy_forward_log(legacy, root)
    assert (copied, present) == (3, 0)
    assert (root / "days" / "2026-10-22.parquet").read_bytes() == b"day-one"


def test_symlink_in_legacy_is_rejected(locations: tuple[Path, Path], tmp_path: Path) -> None:
    legacy, root = locations
    target = tmp_path / "target.txt"
    target.write_bytes(b"t")
    try:
        (legacy / "link.txt").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(paths.ForwardLogMigrationError, match="link"):
        paths.migrate_legacy_forward_log(legacy, root)


@pytest.mark.parametrize("module", [v1_script, v2_script])
def test_entry_points_stop_without_recording_on_mismatch(module: ModuleType, locations: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    legacy, root = locations
    (root / "days").mkdir(parents=True)
    (root / "days" / "2026-10-22.parquet").write_bytes(b"other")
    called: list[object] = []
    for name in ("scheduled_record", "record_with_ledger", "run"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, lambda *a, **k: called.append(a))
    monkeypatch.setattr(sys, "argv", ["prog"])
    with pytest.raises(SystemExit) as raised:
        module.main()
    assert "nothing recorded" in str(raised.value)
    assert called == []
    assert not (root / "attempts.jsonl").exists()


def test_a_held_legacy_lock_stops_migration_before_any_copy(locations: tuple[Path, Path]) -> None:
    from research_core.artifact_store import release_os_lock, try_os_lock

    legacy, root = locations
    attempt = legacy / "attempt-journal-v2" / "a1"
    attempt.mkdir(parents=True)
    (attempt / "owner.lock").write_bytes(b"")
    with (attempt / "owner.lock").open("r+b") as held:
        assert try_os_lock(held)
        try:
            # A second handle conflicts even inside one process on Windows; elsewhere use a child process.
            if sys.platform == "win32":
                with pytest.raises(paths.ForwardLogMigrationError, match="still in use"):
                    paths.migrate_legacy_forward_log(legacy, root)
                assert not root.exists()
        finally:
            release_os_lock(held)


def _failing_scandir(monkeypatch: pytest.MonkeyPatch, bad: Path) -> None:
    real = os.scandir

    def scandir(path: str = "."):  # type: ignore[no-untyped-def]
        if Path(str(path)) == bad:
            raise PermissionError(13, "injected listing failure", str(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)


@pytest.mark.parametrize("where", ["root", "days"])
def test_listing_error_fails_closed(locations: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, where: str) -> None:
    legacy, root = locations
    _failing_scandir(monkeypatch, legacy if where == "root" else legacy / "days")
    with pytest.raises(paths.ForwardLogMigrationError, match="cannot list"):
        paths.migrate_legacy_forward_log(legacy, root)
    assert not root.exists()


@pytest.mark.parametrize("module", [v1_script, v2_script])
@pytest.mark.parametrize("where", ["root", "days"])
def test_entry_points_stop_on_listing_error(module: ModuleType, where: str, locations: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    legacy, root = locations
    called: list[object] = []
    for name in ("scheduled_record", "record_with_ledger", "run"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, lambda *a, **k: called.append(a))
    _failing_scandir(monkeypatch, legacy if where == "root" else legacy / "days")
    monkeypatch.setattr(sys, "argv", ["prog"])
    with pytest.raises(SystemExit) as raised:
        module.main()
    assert "nothing recorded" in str(raised.value)
    assert called == []
    assert not root.exists()  # nothing written in the new location
    assert (legacy / "attempts.jsonl").read_bytes() == LEDGER  # nor in the legacy one
    assert not (legacy / "attempts-v2.jsonl").exists() and not (legacy / "attempt-journal-v2").exists()


def test_destination_migration_lock_busy_refuses(locations: tuple[Path, Path]) -> None:
    from research_core.artifact_store import release_os_lock, try_os_lock

    legacy, root = locations
    root.mkdir(parents=True)
    with (root / paths.MIGRATION_LOCK).open("a+b") as other:
        assert try_os_lock(other)
        try:
            with pytest.raises(paths.ForwardLogMigrationError, match="another forward-log migration"):
                paths.migrate_legacy_forward_log(legacy, root)
        finally:
            release_os_lock(other)
    assert not (root / "attempts.jsonl").exists()
    assert paths.migrate_legacy_forward_log(legacy, root) == (3, 0)  # released, so the next run proceeds


def test_locks_stay_held_during_copy_and_released_after(locations: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core.artifact_store import release_os_lock, try_os_lock

    legacy, root = locations
    attempt = legacy / "attempt-journal-v2" / "a1"
    attempt.mkdir(parents=True)
    (attempt / "owner.lock").write_bytes(b"")
    locks = (legacy / ".attempts-v2-append.lock", attempt / "owner.lock", root / paths.MIGRATION_LOCK)
    probed: list[bool] = []
    real = paths._copy_noreplace

    def probe(source: Path, destination: Path, held: object = None) -> None:
        for lock in locks:
            with lock.open("r+b") as other:
                got = try_os_lock(other)
                if got:
                    release_os_lock(other)
                probed.append(got)
        real(source, destination, held)  # type: ignore[arg-type]

    monkeypatch.setattr(paths, "_copy_noreplace", probe)
    paths.migrate_legacy_forward_log(legacy, root)
    assert len(probed) >= 3 and not any(probed)
    for lock in locks:
        with lock.open("r+b") as other:
            assert try_os_lock(other)
            release_os_lock(other)


def _late_writer(monkeypatch: pytest.MonkeyPatch, after_name: str, action: Callable[[], object]) -> Callable[..., None]:
    real = paths._copy_noreplace

    def copy(source: Path, destination: Path, held: object = None) -> None:
        real(source, destination, held)  # type: ignore[arg-type]
        if destination.name == after_name:
            action()

    monkeypatch.setattr(paths, "_copy_noreplace", copy)
    return real


def test_late_ledger_append_is_detected_and_next_run_refuses(locations: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    legacy, root = locations

    def append() -> None:
        with (legacy / "attempts.jsonl").open("ab") as stream:
            stream.write(b'{"a":3}\n')

    real = _late_writer(monkeypatch, "attempts.jsonl", append)
    with pytest.raises(paths.ForwardLogMigrationError, match="late writer.*attempts.jsonl"):
        paths.migrate_legacy_forward_log(legacy, root)
    monkeypatch.setattr(paths, "_copy_noreplace", real)
    # the legacy ledger is now longer than the copy, so every later run stays closed
    with pytest.raises(paths.ForwardLogMigrationError, match="attempts.jsonl"):
        paths.migrate_legacy_forward_log(legacy, root)


def test_late_new_day_file_is_detected(locations: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    legacy, root = locations
    _late_writer(monkeypatch, "cohort.json", lambda: (legacy / "days" / "2026-10-23.parquet").write_bytes(b"late"))
    with pytest.raises(paths.ForwardLogMigrationError, match="late writer.*2026-10-23.parquet"):
        paths.migrate_legacy_forward_log(legacy, root)


def test_late_removed_file_is_detected(locations: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    legacy, root = locations
    _late_writer(monkeypatch, "cohort.json", lambda: (legacy / "attempts.jsonl").unlink())
    with pytest.raises(paths.ForwardLogMigrationError, match="late writer"):
        paths.migrate_legacy_forward_log(legacy, root)


class _Crash(Exception):
    pass


def _attempt_states(legacy: Path) -> tuple[str, str]:
    """Genuine v2 journal states written by the real v2 code: (started-only, terminal-not-projected)."""

    def die(point: str) -> None:
        if point == "terminal":
            raise _Crash

    started_only = journal.Attempt(legacy, requested_day="2026-10-22", mode="scheduled", code_commit="fixture")
    started_only.close()  # owner released, no terminal
    unprojected = journal.Attempt(legacy, requested_day="2026-10-22", mode="manual", code_commit="fixture", checkpoint=die)
    with pytest.raises(_Crash):
        unprojected.finish({"outcome": "on_time", "finished_at_utc": journal.utc_now(), "completion": "complete"})
    unprojected.close()  # terminal durable, ledger row never appended
    assert not (legacy / journal.LEDGER).exists()
    return started_only.attempt_id, unprojected.attempt_id


def _assert_recovered(root: Path, started_only: str, unprojected: str) -> None:
    assert journal.recover(root) == []
    rows = journal.read_attempts(root, include_legacy=False)
    by_id = {row["attempt_id"]: row for row in rows}
    assert len(rows) == len(by_id) == 2
    assert by_id[started_only]["outcome"] == "interrupted" and by_id[started_only]["finished_at_utc"] is None
    assert by_id[unprojected]["outcome"] == "on_time"
    assert (root / journal.JOURNAL / unprojected / "terminal.json").is_file()


def test_real_v2_states_recover_exactly_once_after_migration(tmp_path: Path, locations: tuple[Path, Path]) -> None:
    legacy, root = locations
    started_only, unprojected = _attempt_states(legacy)
    control = tmp_path / "control"
    shutil.copytree(legacy, control)
    _assert_recovered(control, started_only, unprojected)  # control: same states recover in a plain copy

    paths.migrate_legacy_forward_log(legacy, root)
    assert not (root / journal.LEDGER).exists()  # migration copies state; it never projects
    _assert_recovered(root, started_only, unprojected)
    ledger = (root / journal.LEDGER).read_bytes()
    assert len(ledger.splitlines()) == 2

    # exactly once: recover again, migrate again (legacy still holds the same state), recover again
    assert journal.recover(root) == []
    assert paths.migrate_legacy_forward_log(legacy, root)[0] == 0
    assert journal.recover(root) == []
    assert (root / journal.LEDGER).read_bytes() == ledger
    assert not (legacy / journal.LEDGER).exists()  # recovery in the new root never touched legacy
