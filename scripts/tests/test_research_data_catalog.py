"""Synthetic publication, discovery and identity failures; no live inputs."""

import os
import subprocess
from pathlib import Path

import pytest

from research_core.artifact_store import file_digest, read_json, write_json
from research_core.research_data_builder import publish_bundle
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots


def metadata() -> dict:
    unavailable = {"start": None, "end": None, "reason": "not applicable to synthetic data"}
    return {
        "data_id": "synthetic-features",
        "kind": "features",
        "definition_version": "fixture.v1",
        "parameters": {"fixture": True},
        "inputs": {"prices": "invented-v1"},
        "coverage": {
            "scope": "two invented stocks",
            "raw_input_period": {"start": "2010-01-04", "end": "2010-01-05", "reason": None},
            "valid_indicator_period": unavailable,
            "complete_label_period": unavailable,
        },
        "status": "partial",
        "limitations": ["synthetic fixture"],
        "backup": {"status": "not_backed_up", "off_machine": False},
    }


@pytest.fixture
def catalog(tmp_path: Path) -> DataCatalog:
    (tmp_path / "primary/.git").mkdir(parents=True)
    return DataCatalog(DataRoots.from_env({DATA_ROOT_ENV: str(tmp_path / "primary/research_data")}))


def inventory(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.stat().st_size, file_digest(p)) for p in root.rglob("*") if p.is_file()}


def make_worktree(catalog: DataCatalog, name: str) -> Path:
    primary = catalog.roots.primary
    git = ["git", "-c", "init.templateDir=", "-c", f"core.hooksPath={primary / 'no-hooks'}", "-c", "commit.gpgSign=false", "-C", str(primary)]
    subprocess.run([*git, "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(
        [*git, "-c", "user.name=Synthetic fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    target = primary / ".worktrees" / name
    subprocess.run([*git, "worktree", "add", "--detach", str(target), "HEAD"], check=True, capture_output=True)
    return target


def test_publish_reuse_and_two_worktrees_share_one_physical_version(catalog: DataCatalog):
    entry = publish_bundle(catalog, metadata(), {"features.json": b'{"MA20": [1,2]}'})
    snapshot = catalog.read()["version_id"]
    before = inventory(catalog.roots.data)
    for name in ("first", "second"):
        worktree = make_worktree(catalog, name)
        roots = DataRoots.from_env({DATA_ROOT_ENV: str(catalog.roots.data)}, worktree=worktree)
        other = DataCatalog(roots)
        result = other.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"])
        assert os.path.samefile(roots.artifact_path("data", result["manifest"]["path"]), catalog.roots.artifact_path("data", entry["manifest"]["path"]))
        assert not (worktree / "research_data").exists()
    assert publish_bundle(catalog, metadata(), {"features.json": b'{"MA20": [1,2]}'}) == entry
    assert catalog.read()["version_id"] == snapshot
    assert inventory(catalog.roots.data) == before


def test_definition_and_input_changes_produce_new_versions_and_reject_reuse(catalog: DataCatalog):
    entry = publish_bundle(catalog, metadata(), {"features.json": b"old"})
    changed = {**metadata(), "definition_version": "fixture.v2", "inputs": {"prices": "invented-v2"}}
    new = publish_bundle(catalog, changed, {"features.json": b"new"}, lineage={"extends": entry["version_id"], "mode": "rebuild_definition"})
    assert new["version_id"] != entry["version_id"]
    with pytest.raises(ValueError, match="identity mismatch"):
        catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"], expected_inputs=changed["inputs"])
    with pytest.raises(ValueError, match="identity mismatch"):
        catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"], definition_version="fixture.v2")
    with pytest.raises(KeyError):
        catalog.get(entry["data_id"], "latest", manifest_sha256=entry["manifest"]["sha256"])


def test_corruption_raises_without_recalculation(catalog: DataCatalog):
    entry = publish_bundle(catalog, metadata(), {"features.json": b"old"})
    file = catalog.roots.artifact_path("data", entry["manifest"]["path"]).parent / "features.json"
    file.chmod(0o600)
    file.write_bytes(b"bad")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"])
    assert file.read_bytes() == b"bad"


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "C:/escape",
        "name:stream",
        "manifest.json",
        "bad.",
        "bad ",
        "CON.txt",
        "COM¹.txt",
        "COM²",
        "COM³",
        "LPT¹.txt",
        "LPT²",
        "LPT³",
        "left<right",
        "null\0name",
    ],
)
def test_unsafe_publication_names_fail(catalog: DataCatalog, name: str):
    with pytest.raises(ValueError):
        publish_bundle(catalog, metadata(), {name: b"bad"})
    assert not (catalog.roots.data / "catalog.json").exists()
    assert not catalog.roots.data.exists()


def test_metadata_replacement_and_writer_conflict_fail_closed(catalog: DataCatalog):
    entry = publish_bundle(catalog, metadata(), {"features.json": b"original"})
    with pytest.raises(ValueError, match="identity metadata mismatch"):
        catalog.register([{**entry, "limitations": ["rewrite"]}])
    assert not (catalog.roots.data / ".catalog.lock").exists()
    write_json(catalog.roots.data / ".catalog.lock", {"owner": "other writer"})
    assert read_json(catalog.roots.data / ".catalog.lock")
    with pytest.raises(FileExistsError):
        catalog.register([entry])


def test_old_catalog_snapshot_survives_later_registration(catalog: DataCatalog):
    publish_bundle(catalog, metadata(), {"features.json": b"old"})
    old = catalog.read()
    publish_bundle(catalog, metadata(), {"features.json": b"new"})
    assert len(catalog.read()["entries"]) == 2
    assert catalog.read(old["version_id"]) == old


def test_retire_stops_advertising_one_version_and_keeps_history(catalog: DataCatalog):
    kept = publish_bundle(catalog, metadata(), {"features.json": b"kept"})
    gone = publish_bundle(catalog, metadata(), {"features.json": b"gone"})
    before = catalog.read()
    payload = catalog.roots.artifact_path("data", gone["manifest"]["path"])

    after = catalog.retire(gone["data_id"], gone["version_id"], manifest_sha256=gone["manifest"]["sha256"], reason="superseded", retired_on="2026-10-15")

    assert catalog.read() == after
    assert [row["version_id"] for row in after["entries"]] == [kept["version_id"]]
    assert after["retired"] == [{"entry": gone, "reason": "superseded", "retired_on": "2026-10-15"}]
    assert "## Retired" in (catalog.roots.data / "README.md").read_text(encoding="utf-8")
    assert catalog.read(before["version_id"]) == before
    assert payload.exists()  # retiring never deletes payload
    with pytest.raises(KeyError):
        catalog.get(gone["data_id"], gone["version_id"], manifest_sha256=gone["manifest"]["sha256"])
    # A later registration carries the retirement record forward.
    publish_bundle(catalog, metadata(), {"features.json": b"later"})
    assert catalog.read()["retired"] == after["retired"]
    # Ordinary registration never re-advertises a retired version, and leaves no lock.
    current = catalog.read()["version_id"]
    with pytest.raises(ValueError, match="retired"):
        catalog.register([gone])
    with pytest.raises(ValueError, match="retired"):
        publish_bundle(catalog, metadata(), {"features.json": b"gone"})
    assert catalog.read()["version_id"] == current
    assert not (catalog.roots.data / ".catalog.lock").exists()


def test_retire_refuses_unknown_or_mismatched_versions_without_publishing(catalog: DataCatalog):
    entry = publish_bundle(catalog, metadata(), {"features.json": b"only"})
    snapshot = catalog.read()["version_id"]
    with pytest.raises(KeyError):
        catalog.retire(entry["data_id"], "0" * 64, manifest_sha256=entry["manifest"]["sha256"], reason="x", retired_on="2026-10-15")
    with pytest.raises(ValueError, match="identity mismatch"):
        catalog.retire(entry["data_id"], entry["version_id"], manifest_sha256="0" * 64, reason="x", retired_on="2026-10-15")
    with pytest.raises(ValueError, match="reason"):
        catalog.retire(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"], reason=" ", retired_on="2026-10-15")
    assert catalog.read()["version_id"] == snapshot
    assert not (catalog.roots.data / ".catalog.lock").exists()  # a bad request never strands the writer lock
    write_json(catalog.roots.data / ".catalog.lock", {"owner": "other writer"})
    with pytest.raises(FileExistsError):
        catalog.retire(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"], reason="x", retired_on="2026-10-15")


def test_cli_catalog_and_worktree_check(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    import sys

    from scripts.research_data import main

    publish_bundle(catalog, metadata(), {"features.json": b"fixture"})
    monkeypatch.setenv(DATA_ROOT_ENV, str(catalog.roots.data))
    monkeypatch.setattr(sys, "argv", ["research_data", "catalog"])
    assert main() == 0
    assert "synthetic-features" in capsys.readouterr().out
    worktree = make_worktree(catalog, "test")
    monkeypatch.setattr(sys, "argv", ["research_data", "check-worktree", str(worktree)])
    assert main() == 0
    assert "verified" in capsys.readouterr().out
    entry = catalog.read()["entries"][0]
    retire = ["research_data", "retire", entry["data_id"], entry["version_id"], "--manifest-sha256", entry["manifest"]["sha256"]]
    monkeypatch.setattr(sys, "argv", [*retire, "--reason", "fixture retired", "--retired-on", "2026-10-15"])
    assert main() == 0
    assert '"retired"' in capsys.readouterr().out
    assert catalog.read()["entries"] == []


@pytest.mark.parametrize("key", ["series_id", "calendar_id", "source_manifest_sha256"])
def test_market_context_inputs_must_match_sealed_source(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch, key: str):
    from research_core import market_context_artifact
    from research_core.artifact_store import canonical
    from research_core.research_data_catalog import verify_entry

    path = catalog.roots.primary / "tasks/fixture-context/manifest.json"
    path.parent.mkdir(parents=True)
    source = {
        "dataset_id": "sha256:fixture-context",
        "definition_version": "fixture-context.v1",
        "series_id": "series-v1",
        "calendar_id": "calendar-v1",
        "source_manifest_sha256": "source-v1",
    }
    path.write_bytes(canonical(source))
    entry = {
        **metadata(),
        "data_id": "market-context",
        "kind": "market",
        "version_id": "fixture-context",
        "definition_version": "fixture-context.v1",
        "reader": "market_context",
        "manifest": {"scope": "primary", "path": path.relative_to(catalog.roots.primary).as_posix(), "sha256": file_digest(path)},
        "inputs": {key: source[key] for key in ("series_id", "calendar_id", "source_manifest_sha256")},
    }
    monkeypatch.setattr(market_context_artifact, "read_dataset", lambda _: {"verified_fixture": True})
    verify_entry(entry, catalog.roots)
    entry["inputs"][key] = "wrong-source"
    with pytest.raises(ValueError, match="market-context identity mismatch"):
        verify_entry(entry, catalog.roots)
