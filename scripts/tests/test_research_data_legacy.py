"""Existing registration preserves bytes and avoids invented validity claims."""

from pathlib import Path

from research_core.artifact_store import canonical, file_digest
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_legacy import existing_entries
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots


def test_old_study_is_registered_in_place_with_unknown_warmup_and_backup(tmp_path: Path):
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    path = primary / "tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-descriptive-01/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        canonical({
            "schema_version": "hhhl-probability.v4",
            "complete": True,
            "rule": "hhhl_rule_v4",
            "window": ["2019-01-02", "2026-08-14"],
            "identity": {"source": "invented"},
        })
    )
    digest = file_digest(path)
    catalog = DataCatalog(DataRoots.from_env({DATA_ROOT_ENV: str(primary / "research_data")}))
    entries = existing_entries(catalog)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["manifest"]["path"] == path.relative_to(primary).as_posix()
    assert entry["manifest"]["sha256"] == digest
    assert entry["coverage"]["raw_input_period"]["start"] == "2019-01-02"
    assert entry["status"] == "legacy"
    assert entry["reader"] == "metadata_only"
    assert entry["backup"]["status"] == "unknown_for_exact_version"
    catalog.register(entries)
    assert file_digest(path) == digest
    assert not list(catalog.roots.data.glob("patterns/**/*"))
