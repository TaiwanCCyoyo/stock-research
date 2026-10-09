"""Synthetic manifest, parquet, projection and integrity regression tests."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_core.feature_atlas_dataset import DEFAULT_COLUMNS, load_analysis, verify_dataset
from research_core.feature_atlas_io import digest_json

Dataset = tuple[Path, dict[str, Any]]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def dataset(tmp_path: Path) -> Dataset:
    (tmp_path / "tables").mkdir()
    identity = {"schema_version": "feature-discrimination-atlas.v1", "source_sha256": {"synthetic": "a" * 64}}
    dataset_id = "fda-" + digest_json(identity)
    tables = []
    cross_parts = []
    for security in ("TW:1101", "TW:1102"):
        frame = pd.DataFrame({
            "security_id": [security] * 2,
            "asof_date": pd.date_range("2020-01-01", periods=2),
            **{f"F{i:02}": [0.0, 1.0] for i in range(1, 36)},
            "label_63": [1.0, None],
            "label_126": [0.0, None],
            "base_eligible": [True, False],
            "year": [2020, 2020],
            "regime": ["up", "up"],
            "industry_ref": ["cement", "cement"],
            "calendar_index": [0, 1],
            "wide_unused_metric": [3.0, 4.0],
            "dataset_id": [dataset_id] * 2,
        })
        relative = f"tables/{security.split(':')[1]}.parquet"
        frame.to_parquet(tmp_path / relative, index=False)
        tables.append({"path": relative, "sha256": digest(tmp_path / relative), "rows": 2, "security_id": security})
        cross_parts.append(
            frame[["security_id", "asof_date"]].assign(
                F36=[1.0, 0.0],
                F37=[0.0, 1.0],
                F38=[None, 1.0],
                rs20_percentile=[0.7, 0.8],
                rs60_percentile=[0.6, 0.9],
                relative_ret60_0050=[0.1, 0.2],
            )
        )
    pd.concat(cross_parts, ignore_index=True).iloc[::-1].to_parquet(tmp_path / "cross_section.parquet", index=False)
    (tmp_path / "summary.json").write_text('{"synthetic": true}', encoding="utf-8")
    manifest = {
        "schema_version": "feature-discrimination-atlas.v1",
        "dataset_id": dataset_id,
        "identity": identity,
        "run_id": "test-run",
        "tables": tables,
        "cross_section": {"path": "cross_section.parquet", "sha256": digest(tmp_path / "cross_section.parquet"), "rows": 4},
        "artifacts": [{"path": "summary.json", "sha256": digest(tmp_path / "summary.json")}],
    }
    write_manifest(tmp_path, manifest)
    return tmp_path, manifest


def update_parquet(root: Path, manifest: dict[str, Any], entry: dict[str, Any], frame: pd.DataFrame) -> None:
    frame.to_parquet(root / entry["path"], index=False)
    entry["sha256"] = digest(root / entry["path"])
    write_manifest(root, manifest)


def test_default_projection_exact_join_and_verified_counts(dataset: Dataset):
    root, manifest = dataset
    result = load_analysis(root)
    assert list(result.columns) == DEFAULT_COLUMNS
    assert len(result) == 4
    assert result.security_id.tolist() == ["TW:1101"] * 2 + ["TW:1102"] * 2
    assert result.F36.tolist() == [1.0, 0.0, 1.0, 0.0]
    assert result.F38.isna().sum() == 2
    assert "wide_unused_metric" not in result
    assert verify_dataset(root) == {
        "dataset_id": manifest["dataset_id"],
        "run_id": "test-run",
        "tables": 2,
        "table_rows": 4,
        "cross_section_rows": 4,
        "joined_rows": 4,
        "artifacts": 1,
        "verified_files": 4,
    }


def test_explicit_projection_can_mix_table_and_cross_columns(dataset: Dataset):
    root, _ = dataset
    result = load_analysis(root, ["wide_unused_metric", "rs20_percentile"])
    assert list(result.columns) == ["security_id", "asof_date", "wide_unused_metric", "rs20_percentile"]
    assert result.rs20_percentile.tolist() == [0.7, 0.8, 0.7, 0.8]
    with pytest.raises(ValueError, match="missing requested"):
        load_analysis(root, ["absent"])


@pytest.mark.parametrize("entry_name", ["table", "cross_section", "artifact"])
def test_all_listed_file_hashes_are_checked(dataset: Dataset, entry_name: str):
    root, manifest = dataset
    entry = {"table": manifest["tables"][0], "cross_section": manifest["cross_section"], "artifact": manifest["artifacts"][0]}[entry_name]
    with (root / entry["path"]).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        verify_dataset(root)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        load_analysis(root, [])


def test_hash_opt_out_does_not_skip_integrity_checks(dataset: Dataset):
    root, manifest = dataset
    (root / "summary.json").write_text("{}", encoding="utf-8")
    assert len(load_analysis(root, [], verify_hashes=False)) == 4
    manifest["tables"][0]["rows"] = 9
    write_manifest(root, manifest)
    with pytest.raises(ValueError, match="row count mismatch"):
        load_analysis(root, [], verify_hashes=False)


def test_changed_identity_rejected_without_changing_any_artifact_bytes(dataset: Dataset):
    root, manifest = dataset
    original_artifacts = {
        entry["path"]: (root / entry["path"]).read_bytes() for entry in [*manifest["tables"], manifest["cross_section"], *manifest["artifacts"]]
    }
    manifest["identity"]["source_sha256"]["synthetic"] = "b" * 64
    write_manifest(root, manifest)
    assert all((root / name).read_bytes() == data for name, data in original_artifacts.items())
    with pytest.raises(ValueError, match="dataset_id identity mismatch"):
        verify_dataset(root)
    for verify_hashes in (True, False):
        with pytest.raises(ValueError, match="dataset_id identity mismatch"):
            load_analysis(root, [], verify_hashes=verify_hashes)


@pytest.mark.parametrize("identity", [None, {}, [], "invalid", 1])
def test_missing_or_malformed_identity_rejected(dataset: Dataset, identity: Any):
    root, manifest = dataset
    if identity is None:
        manifest.pop("identity")
    else:
        manifest["identity"] = identity
    write_manifest(root, manifest)
    with pytest.raises(ValueError, match="nonempty identity object"):
        verify_dataset(root)
    for verify_hashes in (True, False):
        with pytest.raises(ValueError, match="nonempty identity object"):
            load_analysis(root, [], verify_hashes=verify_hashes)


@pytest.mark.parametrize("target", ["table", "cross"])
def test_declared_row_counts_must_match_parquet(dataset: Dataset, target: str):
    root, manifest = dataset
    entry = manifest["tables"][0] if target == "table" else manifest["cross_section"]
    entry["rows"] += 1
    write_manifest(root, manifest)
    with pytest.raises(ValueError, match="row count mismatch"):
        verify_dataset(root)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "null"])
def test_cross_section_requires_exact_nonmissing_unique_keys(dataset: Dataset, mutation: str):
    root, manifest = dataset
    entry = manifest["cross_section"]
    frame = pd.read_parquet(root / entry["path"])
    if mutation == "missing":
        frame = frame.iloc[:-1]
    elif mutation == "extra":
        extra = frame.iloc[:1].assign(security_id="TW:9999")
        frame = pd.concat([frame, extra], ignore_index=True)
    elif mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    else:
        frame.loc[0, "asof_date"] = pd.NaT
    entry["rows"] = len(frame)
    update_parquet(root, manifest, entry, frame)
    with pytest.raises(ValueError, match="join keys"):
        verify_dataset(root)


def test_duplicate_table_keys_and_declared_security_are_rejected(dataset: Dataset):
    root, manifest = dataset
    entry = manifest["tables"][0]
    original = pd.read_parquet(root / entry["path"])
    frame = original.copy()
    frame.loc[1, "asof_date"] = frame.loc[0, "asof_date"]
    update_parquet(root, manifest, entry, frame)
    with pytest.raises(ValueError, match="duplicate join keys"):
        verify_dataset(root)
    frame = original.assign(security_id="TW:9999")
    update_parquet(root, manifest, entry, frame)
    with pytest.raises(ValueError, match="security_id mismatch"):
        verify_dataset(root)


@pytest.mark.parametrize("metadata_kind", ["column", "parquet"])
def test_dataset_id_metadata_must_match(dataset: Dataset, metadata_kind: str):
    root, manifest = dataset
    entry = manifest["tables"][0]
    frame = pd.read_parquet(root / entry["path"])
    if metadata_kind == "column":
        update_parquet(root, manifest, entry, frame.assign(dataset_id="other"))
    else:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"dataset_id": b"other"})
        pq.write_table(table, root / entry["path"])
        entry["sha256"] = digest(root / entry["path"])
        write_manifest(root, manifest)
    with pytest.raises(ValueError, match="dataset_id .* mismatch"):
        verify_dataset(root)


@pytest.mark.parametrize("path", ["../escape.json", "/absolute.json", "C:/escape.json", "C:escape.json", "tables\\1101.parquet", "tables/../1101.parquet"])
def test_manifest_paths_cannot_escape_or_use_windows_aliases(dataset: Dataset, path: str):
    root, manifest = dataset
    manifest["artifacts"][0]["path"] = path
    write_manifest(root, manifest)
    with pytest.raises(ValueError, match="path"):
        verify_dataset(root)


def test_missing_listed_file_is_rejected(dataset: Dataset):
    root, manifest = dataset
    manifest["artifacts"][0]["path"] = "absent.json"
    write_manifest(root, manifest)
    with pytest.raises(ValueError, match="missing dataset file"):
        verify_dataset(root)


def test_linked_file_is_rejected_without_reading_target(dataset: Dataset):
    root, manifest = dataset
    link = root / "linked.json"
    try:
        link.symlink_to(root / "summary.json")
    except OSError:
        pytest.skip("symlink creation requires platform permission")
    manifest["artifacts"][0]["path"] = "linked.json"
    write_manifest(root, manifest)
    with pytest.raises(ValueError, match="linked/reparse"):
        verify_dataset(root)
