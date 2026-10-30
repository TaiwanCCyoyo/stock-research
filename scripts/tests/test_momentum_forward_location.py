"""Forward-log location and one-way migration (synthetic data in tmp_path only)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

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
    assert _snapshot(root) == expected


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


def test_v2_attempt_owner_lock_is_copied_for_recovery(locations: tuple[Path, Path]) -> None:
    # recover() needs each attempt's owner.lock to prove a released owner; only root coordination locks stay behind.
    legacy, root = locations
    attempt = legacy / "attempt-journal-v2" / "a1"
    attempt.mkdir(parents=True)
    (attempt / "started.json").write_bytes(b'{"s":1}')
    (attempt / "owner.lock").write_bytes(b"")

    paths.migrate_legacy_forward_log(legacy, root)

    assert (root / "attempt-journal-v2" / "a1" / "owner.lock").is_file()
    assert (root / "attempt-journal-v2" / "a1" / "started.json").read_bytes() == b'{"s":1}'
    assert not (root / ".attempts-v2-append.lock").exists()


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
