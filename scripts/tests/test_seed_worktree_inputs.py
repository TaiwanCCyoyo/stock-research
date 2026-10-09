"""Functional worktree seeding regression; no canonical data access."""

import json
import os
import sqlite3
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import seed_worktree_inputs
from scripts.seed_worktree_inputs import seed_inputs


def test_seed_only_read_inputs_no_derived_or_large_raw_and_preserves_existing(tmp_path: Path):
    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    source, target = primary / "shioaji_stock_prices/data", worktree / "shioaji_stock_prices/data"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    for name in ("2330_day.csv", "2330_min.csv", "price_daily.parquet", "stock_category.json5", "unknown.bin"):
        (source / name).write_bytes(name.encode())
    (source / "technical_features").mkdir()
    (source / "technical_features/raw.bin").write_bytes(b"do not copy")
    (primary / "research_cache").mkdir()
    (primary / "research_cache/derived.bin").write_bytes(b"do not copy")
    (target / "price_daily.parquet").write_bytes(b"existing sealed input")
    receipt = seed_inputs(primary, worktree)
    assert [row["path"] for row in receipt["files"]] == ["2330_day.csv"]
    assert receipt["existing_preserved"] == ["price_daily.parquet"]
    assert sorted(path.name for path in target.iterdir()) == ["2330_day.csv", "price_daily.parquet"]
    assert (target / "price_daily.parquet").read_bytes() == b"existing sealed input"
    assert (source / "2330_min.csv").exists()


def test_sqlite_snapshot_includes_committed_wal_rows(tmp_path: Path):
    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    source, target = primary / "shioaji_stock_prices/data", worktree / "shioaji_stock_prices/data"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    with sqlite3.connect(source / "institutional.sqlite") as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE evidence(value INTEGER)")
        writer.execute("INSERT INTO evidence VALUES (42)")
        writer.commit()
        receipt = seed_inputs(primary, worktree)
        with sqlite3.connect(target / "institutional.sqlite") as copied:
            assert copied.execute("SELECT value FROM evidence").fetchall() == [(42,)]
    assert receipt["files"][0]["mode"].startswith("consistent_sqlite_backup")


def test_stable_inputs_preserve_exact_mtime_and_csv_freshness(tmp_path: Path) -> None:
    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    source, target = primary / "shioaji_stock_prices/data", worktree / "shioaji_stock_prices/data"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    parquet = source / "price_daily.parquet"
    csv = source / "2330_day.csv"
    parquet.write_bytes(b"older parquet fixture")
    csv.write_bytes(b"newer csv fixture")
    os.utime(parquet, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    os.utime(csv, ns=(1_700_000_001_000_000_000, 1_700_000_001_000_000_000))
    expected = {path.name: path.stat().st_mtime_ns for path in (parquet, csv)}

    seed_inputs(primary, worktree)

    assert {name: (target / name).stat().st_mtime_ns for name in expected} == expected
    assert (target / csv.name).stat().st_mtime_ns > (target / parquet.name).stat().st_mtime_ns


def test_failed_copy_retains_partial_and_retry_publishes_complete_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    source, target = primary / "shioaji_stock_prices/data", worktree / "shioaji_stock_prices/data"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    incoming = source / "2330_day.csv"
    incoming.write_bytes(b"complete csv fixture")
    original_copy = seed_worktree_inputs.copy_verified

    def interrupted_copy(source_path: Path, destination: Path, expected: str) -> None:
        destination.write_bytes(b"interrupted partial")
        raise OSError("injected copy interruption")

    monkeypatch.setattr(seed_worktree_inputs, "copy_verified", interrupted_copy)
    with pytest.raises(OSError, match="injected copy interruption"):
        seed_inputs(primary, worktree)

    assert not (target / incoming.name).exists()
    partials = list(target.glob(f".{incoming.name}.seed-*.partial"))
    assert len(partials) == 1
    assert partials[0].read_bytes() == b"interrupted partial"
    assert not (target / f".{incoming.name}.seed.lock").exists()

    monkeypatch.setattr(seed_worktree_inputs, "copy_verified", original_copy)
    receipt = seed_inputs(primary, worktree)

    assert (target / incoming.name).read_bytes() == incoming.read_bytes()
    assert partials[0].read_bytes() == b"interrupted partial"
    assert receipt["existing_preserved"] == []
    assert [row["path"] for row in receipt["files"]] == [incoming.name]
    assert not (target / f".{incoming.name}.seed.lock").exists()


def test_target_created_during_copy_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    source, target = primary / "shioaji_stock_prices/data", worktree / "shioaji_stock_prices/data"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    incoming = source / "2330_day.csv"
    incoming.write_bytes(b"source csv fixture")
    original_copy = seed_worktree_inputs.copy_verified
    concurrent_target = target / incoming.name

    def concurrent_copy(source_path: Path, destination: Path, expected: str) -> None:
        original_copy(source_path, destination, expected)
        concurrent_target.write_bytes(b"concurrent writer snapshot")

    monkeypatch.setattr(seed_worktree_inputs, "copy_verified", concurrent_copy)
    with pytest.raises(FileExistsError):
        seed_inputs(primary, worktree)

    assert concurrent_target.read_bytes() == b"concurrent writer snapshot"
    assert not (target / f".{incoming.name}.seed.lock").exists()


@pytest.mark.parametrize("relative", ["2330_day.csv", "adjusted_prices/daily/2330_day.csv"])
def test_target_created_at_publication_boundary_is_never_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    incoming, outgoing = source / relative, target / relative
    incoming.write_bytes(b"complete source snapshot")
    original_publish = seed_worktree_inputs.publish_noreplace
    observed: list[Path] = []

    def foreign_writer_at_publication(staging: Path, destination: Path) -> None:
        observed.append(staging)
        assert destination == outgoing and not destination.exists()
        destination.write_bytes(b"foreign writer snapshot")
        original_publish(staging, destination)

    monkeypatch.setattr(seed_worktree_inputs, "publish_noreplace", foreign_writer_at_publication)
    with pytest.raises(FileExistsError):
        seed_inputs(primary, worktree)

    assert outgoing.read_bytes() == b"foreign writer snapshot"
    assert len(observed) == 1 and observed[0].read_bytes() == b"complete source snapshot"
    assert observed[0].name.startswith(f".{incoming.name}.seed-") and observed[0].suffix == ".partial"
    assert not outgoing.with_name(f".{outgoing.name}.seed.lock").exists()
    assert incoming.read_bytes() == b"complete source snapshot"
    assert list((worktree / ".tmp").glob("worktree-seed-*/receipt.json")) == []


def test_data_quality_report_preserves_bytes_mtime_provenance_and_repeat_snapshot(tmp_path: Path) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    incoming = source / "data_quality_report.json"
    content = b'{"source":"synthetic","missing_symbols":[]}\n'
    incoming.write_bytes(content)
    os.utime(incoming, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    mtime = incoming.stat().st_mtime_ns
    digest = seed_worktree_inputs.file_digest(incoming)

    first = seed_inputs(primary, worktree)

    outgoing = target / incoming.name
    assert outgoing.read_bytes() == content and outgoing.stat().st_mtime_ns == mtime
    assert len(first["files"]) == 1
    record = first["files"][0]
    assert record["path"] == incoming.name and record["source"] == str(incoming)
    assert record["sha256"] == digest and record["bytes"] == len(content) and record["mtime_ns"] == mtime
    assert record["mode"] == "stable_file_copy"

    repeated = seed_inputs(primary, worktree)

    assert repeated["files"] == [] and repeated["existing_preserved"] == [incoming.name]
    preserved = repeated["preserved_inventory"][0]
    assert preserved["path"] == incoming.name and preserved["source_ref"] == str(incoming)
    assert preserved["sha256"] == digest and preserved["mtime_ns"] == mtime
    assert preserved["mode"] == "existing_snapshot_preserved" and preserved["current_source_byte_match"] is True
    assert outgoing.read_bytes() == content and outgoing.stat().st_mtime_ns == mtime
    assert incoming.read_bytes() == content and incoming.stat().st_mtime_ns == mtime


def test_cli_prints_counts_and_receipt_path_with_complete_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    source, target = primary / "shioaji_stock_prices/data", worktree / "shioaji_stock_prices/data"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    for name in ("2330_day.csv", "2317_day.csv"):
        (source / name).write_bytes(name.encode())
    monkeypatch.setattr(sys, "argv", ["seed_worktree_inputs", "--primary", str(primary), "--worktree", str(worktree)])

    assert seed_worktree_inputs.main() == 0

    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert set(summary) == {"files", "bytes_copied", "existing_preserved", "receipt_path", "source_alignment_required"}
    assert summary["source_alignment_required"] is False
    assert summary["files"] == 2
    assert summary["existing_preserved"] == 0
    assert summary["bytes_copied"] == sum(path.stat().st_size for path in source.iterdir())
    receipt = json.loads(Path(summary["receipt_path"]).read_text(encoding="utf-8"))
    assert [row["path"] for row in receipt["files"]] == ["2317_day.csv", "2330_day.csv"]
    assert '"sha256"' not in output.out
    assert '"source"' not in output.out
    assert output.err == ""


def legacy_layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    source, target = primary / "shioaji_stock_prices/data", worktree / "shioaji_stock_prices/data"
    (source / "adjusted_prices/daily").mkdir(parents=True)
    target.mkdir(parents=True)
    return primary, worktree, source, target


def test_legacy_daily_explicit_readset_preserves_paths_bytes_mtime_and_source(tmp_path: Path) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    daily = source / "adjusted_prices/daily"
    names = ("2330_day.csv", "price_daily.parquet", "dividends.parquet")
    for i, name in enumerate(names):
        path = daily / name
        path.write_bytes(f"synthetic {name}".encode())
        os.utime(path, ns=(1_700_000_000_000_000_000 + i, 1_700_000_000_000_000_000 + i))
    for name in ("2330_min.csv", "unknown.bin", "institutional.sqlite"):
        (daily / name).write_bytes(b"excluded")
    (daily / "nested").mkdir()
    (daily / "nested/2330_day.csv").write_bytes(b"excluded nested")
    (source / "adjusted_prices/other").mkdir()
    (source / "adjusted_prices/other/2330_day.csv").write_bytes(b"excluded sibling")
    before = {name: ((daily / name).read_bytes(), (daily / name).stat().st_mtime_ns) for name in names}

    receipt = seed_inputs(primary, worktree)

    records = {row["path"]: row for row in receipt["files"]}
    assert set(records) == {f"adjusted_prices/daily/{name}" for name in names}
    for name, (content, mtime) in before.items():
        relative = f"adjusted_prices/daily/{name}"
        copied = target / relative
        assert copied.read_bytes() == content and copied.stat().st_mtime_ns == mtime
        assert records[relative]["source"] == str(daily / name)
        assert records[relative]["mode"] == "stable_file_copy"
        assert records[relative]["mtime_ns"] == mtime
        assert records[relative]["sha256"] == seed_worktree_inputs.file_digest(daily / name)
        assert ((daily / name).read_bytes(), (daily / name).stat().st_mtime_ns) == before[name]
    assert sorted(path.name for path in (target / "adjusted_prices/daily").iterdir()) == sorted(names)
    assert not (target / "adjusted_prices/other").exists()
    assert json.loads(Path(receipt["receipt_path"]).read_text(encoding="utf-8"))["files"] == receipt["files"]


def test_existing_legacy_snapshot_is_preserved(tmp_path: Path) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    relative = "adjusted_prices/daily/2330_day.csv"
    (source / relative).write_bytes(b"producer newer bytes")
    (target / relative).parent.mkdir(parents=True)
    (target / relative).write_bytes(b"existing sealed bytes")
    before = (target / relative).stat().st_mtime_ns
    receipt = seed_inputs(primary, worktree)
    assert receipt["files"] == [] and receipt["existing_preserved"] == [relative]
    assert (target / relative).read_bytes() == b"existing sealed bytes"
    assert (target / relative).stat().st_mtime_ns == before


@pytest.mark.parametrize("location", ["source", "target"])
@pytest.mark.parametrize("name", [".2330_day.csv.seed-interrupted.partial", ".2330_day.csv.seed.lock"])
def test_unfinished_legacy_snapshot_is_rejected(tmp_path: Path, location: str, name: str) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    (source / "adjusted_prices/daily/2330_day.csv").write_bytes(b"synthetic source")
    directory = (source if location == "source" else target) / "adjusted_prices/daily"
    directory.mkdir(parents=True, exist_ok=True)
    evidence = directory / name
    evidence.write_bytes(b"unfinished evidence")
    with pytest.raises(ValueError, match="unfinished legacy daily snapshot"):
        seed_inputs(primary, worktree)
    assert evidence.read_bytes() == b"unfinished evidence"
    assert not (target / "adjusted_prices/daily/2330_day.csv").exists()


@pytest.mark.parametrize("location", ["source_directory", "target_directory", "source_file", "target_file"])
@pytest.mark.parametrize("linked_kind", ["symlink", "reparse"])
def test_legacy_link_or_junction_is_rejected_without_following(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str, linked_kind: str) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    incoming = source / "adjusted_prices/daily/2330_day.csv"
    incoming.write_bytes(b"synthetic source")
    outgoing = target / "adjusted_prices/daily/2330_day.csv"
    outgoing.parent.mkdir(parents=True)
    outgoing.write_bytes(b"existing snapshot")
    unsafe = {"source_directory": incoming.parent, "target_directory": outgoing.parent, "source_file": incoming, "target_file": outgoing}[location]
    original_lstat = Path.lstat

    def reparse_lstat(path: Path):
        observed = original_lstat(path)
        if path == unsafe:
            return SimpleNamespace(
                st_mode=stat.S_IFLNK if linked_kind == "symlink" else observed.st_mode, st_file_attributes=1024 if linked_kind == "reparse" else 0
            )
        return observed

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", reparse_lstat)
        with pytest.raises(ValueError, match="linked/reparse path forbidden"):
            seed_inputs(primary, worktree)
    assert incoming.read_bytes() == b"synthetic source" and outgoing.read_bytes() == b"existing snapshot"


def test_interrupted_legacy_copy_keeps_partial_without_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    incoming = source / "adjusted_prices/daily/2330_day.csv"
    incoming.write_bytes(b"synthetic complete source")
    original_copy = seed_worktree_inputs.copy_verified

    def interrupted_copy(source_path: Path, destination: Path, expected: str) -> None:
        assert destination.parent == target / "adjusted_prices/daily"
        destination.write_bytes(b"partial evidence")
        raise OSError("injected legacy interruption")

    monkeypatch.setattr(seed_worktree_inputs, "copy_verified", interrupted_copy)
    with pytest.raises(OSError, match="injected legacy interruption"):
        seed_inputs(primary, worktree)
    assert incoming.read_bytes() == b"synthetic complete source"
    assert not (target / "adjusted_prices/daily/2330_day.csv").exists()
    partials = list((target / "adjusted_prices/daily").glob(".2330_day.csv.seed-*.partial"))
    assert len(partials) == 1 and partials[0].read_bytes() == b"partial evidence"
    assert not (target / "adjusted_prices/daily/.2330_day.csv.seed.lock").exists()
    monkeypatch.setattr(seed_worktree_inputs, "copy_verified", original_copy)
    receipt = seed_inputs(primary, worktree)
    assert (target / "adjusted_prices/daily/2330_day.csv").read_bytes() == incoming.read_bytes()
    assert partials[0].read_bytes() == b"partial evidence"
    assert [row["path"] for row in receipt["files"]] == ["adjusted_prices/daily/2330_day.csv"]
    assert receipt["existing_preserved"] == []
    assert not (target / "adjusted_prices/daily/.2330_day.csv.seed.lock").exists()


def test_retry_reports_mixed_preserved_and_new_snapshot_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    (source / "2330_day.csv").write_bytes(b"old producer csv")
    (source / "price_daily.parquet").write_bytes(b"old producer parquet")
    publish = seed_worktree_inputs._publish_snapshot

    def fail_later(incoming: Path, outgoing: Path) -> None:
        if incoming.name == "price_daily.parquet":
            raise OSError("injected later failure")
        publish(incoming, outgoing)

    monkeypatch.setattr(seed_worktree_inputs, "_publish_snapshot", fail_later)
    with pytest.raises(OSError, match="injected later failure"):
        seed_inputs(primary, worktree)
    assert (target / "2330_day.csv").read_bytes() == b"old producer csv"
    (source / "2330_day.csv").write_bytes(b"new producer csv")
    (source / "price_daily.parquet").write_bytes(b"new producer parquet")
    monkeypatch.setattr(seed_worktree_inputs, "_publish_snapshot", publish)

    receipt = seed_inputs(primary, worktree)

    assert (target / "2330_day.csv").read_bytes() == b"old producer csv"
    assert (target / "price_daily.parquet").read_bytes() == b"new producer parquet"
    assert receipt["existing_preserved"] == ["2330_day.csv"]
    assert [row["path"] for row in receipt["files"]] == ["price_daily.parquet"]
    preserved = receipt["preserved_inventory"][0]
    assert preserved["path"] == "2330_day.csv" and preserved["bytes"] == len(b"old producer csv")
    assert preserved["sha256"] == seed_worktree_inputs.file_digest(target / "2330_day.csv")
    assert preserved["mtime_ns"] == (target / "2330_day.csv").stat().st_mtime_ns
    assert preserved["source_ref"] == str(source / "2330_day.csv")
    assert preserved["mode"] == "existing_snapshot_preserved" and preserved["original_source_identity"] == "unknown"
    assert preserved["current_source_byte_match"] is False
    assert preserved["current_source_reference"]["sha256"] == seed_worktree_inputs.file_digest(source / "2330_day.csv")
    assert preserved["current_source_reference_role"] == "current_observation_not_original_source_identity"
    assert receipt["source_alignment_required"] is True
    assert receipt["input_set_coherence"] == "not_certified_by_file_seeding"


@pytest.mark.parametrize("existing", [True, False])
def test_preserved_or_new_file_change_before_receipt_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    (source / "2330_day.csv").write_bytes(b"source csv")
    (source / "price_daily.parquet").write_bytes(b"source parquet")
    if existing:
        (target / "2330_day.csv").write_bytes(b"existing csv")
    publish = seed_worktree_inputs._publish_snapshot

    def change_previous(incoming: Path, outgoing: Path) -> None:
        publish(incoming, outgoing)
        if incoming.name == "price_daily.parquet":
            (target / "2330_day.csv").write_bytes(b"concurrent changed snapshot")

    monkeypatch.setattr(seed_worktree_inputs, "_publish_snapshot", change_previous)
    with pytest.raises(ValueError, match="snapshot changed before receipt"):
        seed_inputs(primary, worktree)
    assert list((worktree / ".tmp").glob("worktree-seed-*/receipt.json")) == []
    assert (target / "2330_day.csv").read_bytes() == b"concurrent changed snapshot"


def closed_database(path: Path, value: int) -> None:
    database = sqlite3.connect(path)
    try:
        database.execute("CREATE TABLE evidence(value INTEGER)")
        database.execute("INSERT INTO evidence VALUES (?)", (value,))
        database.commit()
    finally:
        database.close()


def test_preserved_closed_sqlite_inventory_does_not_claim_live_source_match(tmp_path: Path) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    closed_database(source / "institutional.sqlite", 42)
    closed_database(target / "institutional.sqlite", 7)
    before = (target / "institutional.sqlite").read_bytes()
    receipt = seed_inputs(primary, worktree)
    row = receipt["preserved_inventory"][0]
    assert row["path"] == "institutional.sqlite" and row["original_source_identity"] == "unknown"
    assert row["current_source_reference"]["logical_match"] is None
    assert "current_source_byte_match" not in row
    assert receipt["source_alignment_required"] is True
    assert (target / "institutional.sqlite").read_bytes() == before
    assert not list(target.glob("institutional.sqlite-*"))


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_preserved_sqlite_sidecars_prevent_success_receipt(tmp_path: Path, suffix: str) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    closed_database(source / "institutional.sqlite", 42)
    closed_database(target / "institutional.sqlite", 7)
    sidecar = target / f"institutional.sqlite{suffix}"
    sidecar.write_bytes(b"unclosed snapshot evidence")
    with pytest.raises(ValueError, match="SQLite snapshot has sidecar"):
        seed_inputs(primary, worktree)
    assert sidecar.read_bytes() == b"unclosed snapshot evidence"
    assert list((worktree / ".tmp").glob("worktree-seed-*/receipt.json")) == []


@pytest.mark.parametrize("source_legacy_exists", [True, False])
def test_destination_orphans_are_inventoried_without_fabricating_source_identity(tmp_path: Path, source_legacy_exists: bool) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    if not source_legacy_exists:
        (source / "adjusted_prices/daily").rmdir()
        (source / "adjusted_prices").rmdir()
    (target / "adjusted_prices/daily").mkdir(parents=True)
    expected = {
        "2330_day.csv": b"orphan top csv",
        "adjusted_prices/daily/2317_day.csv": b"orphan legacy csv",
        "adjusted_prices/daily/price_daily.parquet": b"orphan legacy parquet",
        "adjusted_prices/daily/dividends.parquet": b"orphan dividends",
    }
    for relative, content in expected.items():
        (target / relative).write_bytes(content)
    closed_database(target / "institutional.sqlite", 7)
    expected["institutional.sqlite"] = (target / "institutional.sqlite").read_bytes()
    for relative in ("unknown.bin", "2330_min.csv", "adjusted_prices/daily/unknown.bin", "adjusted_prices/daily/institutional.sqlite"):
        (target / relative).write_bytes(b"unused excluded")
    (target / "technical_features").mkdir()
    (target / "technical_features/2330_day.csv").write_bytes(b"excluded other derived directory")
    before = {relative: (target / relative).stat().st_mtime_ns for relative in expected}

    receipt = seed_inputs(primary, worktree)

    assert receipt["files"] == [] and set(receipt["existing_preserved"]) == set(expected)
    inventory = {row["path"]: row for row in receipt["preserved_inventory"]}
    assert len(receipt["preserved_inventory"]) == len(expected) and set(inventory) == set(expected)
    assert receipt["source_alignment_required"] is True
    for relative, content in expected.items():
        row = inventory[relative]
        assert (target / relative).read_bytes() == content
        assert (target / relative).stat().st_mtime_ns == before[relative]
        assert row["sha256"] == seed_worktree_inputs.file_digest(target / relative)
        assert row["original_source_identity"] == "unknown" and row["mode"] == "existing_snapshot_preserved"
        assert row["source_ref"] == str(source / relative)
        assert row["current_source_reference"] == {"path": str(source / relative), "status": "missing"}
        assert row["current_source_byte_match"] is None


@pytest.mark.parametrize("name", [".2330_day.csv.seed-interrupted.partial", ".2330_day.csv.seed.lock"])
def test_absent_legacy_source_does_not_bypass_destination_safety(tmp_path: Path, name: str) -> None:
    primary, worktree, source, target = legacy_layout(tmp_path)
    (source / "adjusted_prices/daily").rmdir()
    (source / "adjusted_prices").rmdir()
    daily = target / "adjusted_prices/daily"
    daily.mkdir(parents=True)
    (daily / name).write_bytes(b"unfinished evidence")
    with pytest.raises(ValueError, match="unfinished legacy daily snapshot"):
        seed_inputs(primary, worktree)
    assert (daily / name).read_bytes() == b"unfinished evidence"
