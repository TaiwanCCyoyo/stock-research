"""Synthetic portable export integrity and saved-comparison CLI regressions."""

import hashlib
import json
import lzma
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_core.feature_atlas_io import digest_json
from research_core.feature_atlas_publication import load_publication, publish_feature_atlas, query_comparisons, verify_publication
from research_core.jobs import digest


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    identity = {"code_sha256": "b" * 64}
    dataset_id = "fda-" + digest_json(identity)
    rows = [
        {"feature": "F33", "panel": "daily", "context_column": "regime", "context_value": "unknown", "tp": 0, "precision": None, "selected_unknown": 3},
        {"feature": "F33", "panel": "daily", "context_column": None, "tp": 0, "precision": 0},
        {"feature": "F01", "panel": "grid126", "context_column": None, "tp": 1, "precision": 1},
    ]
    artifacts = {
        "comparisons.json": {"dataset_id": dataset_id, "comparisons": rows},
        "definitions.json": {
            "features": {"F01": {"source_method_ids": ["M01"]}, "F33": {"source_method_ids": ["LEGACY"]}},
            "continuous": ["x", "y"],
            "thresholds_status": "provisional",
        },
        "summary.json": {
            "run": {"dataset_id": dataset_id, "phase": "exploration"},
            "metrics": {"comparison_rows": 3, "feature_count": 2},
            "portfolio": {"evaluated": False},
            "warnings": ["not account returns"],
        },
    }
    entries = []
    for name, value in artifacts.items():
        write_json(root / name, value)
        entries.append({"path": name, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()})
    # Bulk is intentionally absent; export must neither dereference nor claim it.
    entries.append({"path": "benchmark.parquet", "sha256": "a" * 64})
    write_json(
        root / "manifest.json",
        {
            "schema_version": "feature-discrimination-atlas.v1",
            "dataset_id": dataset_id,
            "run_id": "fixed-run",
            "identity": identity,
            "artifacts": entries,
            "tables": [{"path": "tables/1101.parquet"}],
            "catalog_episode_crosswalk": None,
        },
    )
    return root


def test_exact_bytes_counts_unknowns_and_filter(dataset: Path, tmp_path: Path):
    output = tmp_path / "publication"
    manifest = publish_feature_atlas(dataset, output, ["D:/not-present/bulk"])
    assert manifest["schema_version"] == "feature-atlas-publication.v2"
    assert manifest["publication_id"].startswith("feature-atlas-publication.v2-")
    assert lzma.decompress((output / "comparisons.json.xz").read_bytes(), format=lzma.FORMAT_XZ) == (dataset / "comparisons.json").read_bytes()
    for target, source in (("source-manifest.json", "manifest.json"), ("definitions.json", "definitions.json"), ("summary.json", "summary.json")):
        assert (output / target).read_bytes() == (dataset / source).read_bytes()
    assert manifest["counts"] == {"comparisons": 3, "features": 2, "continuous_components": 2, "panels": {"daily": 2, "grid126": 1}}
    assert query_comparisons(output, "F33", "daily", "regime") == json.loads((dataset / "comparisons.json").read_text())["comparisons"][:1]
    assert query_comparisons(output, "F33")[0]["precision"] == 0
    assert load_publication(output)["summary"]["portfolio"]["evaluated"] is False
    result = verify_publication(output)
    assert result["verified_files"] == 4
    assert result["capabilities"]["bulk_validated"] is False
    assert result["capabilities"]["full_catalog_supplied"] is False
    assert set(path.name for path in output.iterdir()) == {"manifest.json", "source-manifest.json", "definitions.json", "summary.json", "comparisons.json.xz"}
    other = tmp_path / "other"
    assert publish_feature_atlas(dataset, other)["publication_id"] == manifest["publication_id"]


def test_cli_export_and_query(dataset: Path, tmp_path: Path):
    output = tmp_path / "cli"
    command = [sys.executable, "-m", "scripts.publish_feature_atlas", "--dataset", str(dataset), "--output", str(output), "--bulk-location", "D:/absent/bulk"]
    exported = subprocess.run(command, check=True, capture_output=True, text=True)
    manifest = json.loads(exported.stdout)
    query = [sys.executable, "-m", "scripts.query_feature_atlas_publication", "--publication", str(output)]
    verified = subprocess.run([*query, "--verify"], check=True, capture_output=True, text=True)
    assert json.loads(verified.stdout)["publication_id"] == manifest["publication_id"]
    filtered = subprocess.run([*query, "--feature", "F33", "--context", "regime"], check=True, capture_output=True, text=True)
    assert json.loads(filtered.stdout)[0]["precision"] is None


def test_invalid_xz_container_rejected_even_with_matching_archive_hash(dataset: Path, tmp_path: Path):
    output = tmp_path / "publication"
    manifest = publish_feature_atlas(dataset, output)
    invalid = b"not an XZ container"
    (output / "comparisons.json.xz").write_bytes(invalid)
    manifest["files"][0]["sha256"] = hashlib.sha256(invalid).hexdigest()
    manifest["files"][0]["bytes"] = len(invalid)
    write_json(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="invalid comparison XZ"):
        load_publication(output)


def test_unpublished_v1_schema_is_not_read_as_v2(dataset: Path, tmp_path: Path):
    output = tmp_path / "publication"
    manifest = publish_feature_atlas(dataset, output)
    manifest["schema_version"] = "feature-atlas-publication.v1"
    write_json(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="publication must use feature-atlas-publication.v2"):
        load_publication(output)


@pytest.mark.parametrize("name", ["comparisons.json.xz", "definitions.json", "summary.json", "source-manifest.json"])
@pytest.mark.parametrize("mutation", ["corrupt", "missing", "empty"])
def test_supplied_file_corruption(dataset: Path, tmp_path: Path, name: str, mutation: str):
    output = tmp_path / "publication"
    publish_feature_atlas(dataset, output)
    path = output / name
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed" if mutation == "corrupt" else b"")
    with pytest.raises(ValueError, match="mismatch|missing or empty"):
        load_publication(output)


@pytest.mark.parametrize("mutation", ["count", "files", "identity", "comparison_sha", "capability", "backup"])
def test_manifest_rejects_false_claims(dataset: Path, tmp_path: Path, mutation: str):
    output = tmp_path / "publication"
    manifest = publish_feature_atlas(dataset, output, ["D:/absent"])
    if mutation == "count":
        manifest["counts"]["comparisons"] += 1
    elif mutation == "files":
        manifest["files"].pop()
    elif mutation == "identity":
        manifest["publication_id"] = "invented"
    elif mutation == "comparison_sha":
        manifest["comparison_original_sha256"] = "0" * 64
    elif mutation == "capability":
        manifest["capabilities"] = {**manifest["capabilities"], "bulk_validated": True}
    else:
        manifest["bulk_locations"][0]["off_machine_backup"] = True
    write_json(output / "manifest.json", manifest)
    with pytest.raises(ValueError):
        verify_publication(output)


@pytest.mark.parametrize("path", ["../escape", "C:/escape", "C:escape", "folder\\escape", "/absolute", "folder/../escape"])
def test_path_rejection(dataset: Path, tmp_path: Path, path: str):
    output = tmp_path / "publication"
    manifest = publish_feature_atlas(dataset, output)
    manifest["files"][0]["path"] = path
    write_json(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="path"):
        load_publication(output)


def test_source_validation_and_overwrite_rejection(dataset: Path, tmp_path: Path):
    output = tmp_path / "publication"
    publish_feature_atlas(dataset, output)
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        publish_feature_atlas(dataset, output)
    assert (output / "manifest.json").read_bytes() == before
    (dataset / "comparisons.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="source SHA256 mismatch"):
        publish_feature_atlas(dataset, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_changed_source_identity_rejected_despite_rebuilt_publication_identity(dataset: Path, tmp_path: Path):
    output = tmp_path / "publication"
    manifest = publish_feature_atlas(dataset, output)
    original_artifacts = {name: (output / name).read_bytes() for name in ("comparisons.json.xz", "definitions.json", "summary.json")}
    source = json.loads((output / "source-manifest.json").read_text())
    source["identity"]["code_sha256"] = "c" * 64
    write_json(output / "source-manifest.json", source)
    source_bytes = (output / "source-manifest.json").read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    for entry in manifest["files"]:
        if entry["path"] == "source-manifest.json":
            entry.update(sha256=source_sha, bytes=len(source_bytes))
    manifest["source_manifest_sha256"] = source_sha
    manifest["publication_id"] = (
        manifest["schema_version"]
        + "-"
        + digest({
            "schema_version": manifest["schema_version"],
            "dataset_id": source["dataset_id"],
            "run_id": source["run_id"],
            "producer_identity": source["identity"],
            "source_manifest_sha256": source_sha,
            "artifact_sha256": {entry["path"]: entry["sha256"] for entry in manifest["files"]},
        })
    )
    write_json(output / "manifest.json", manifest)
    assert all((output / name).read_bytes() == data for name, data in original_artifacts.items())
    with pytest.raises(ValueError, match="source dataset_id identity mismatch"):
        load_publication(output)
    with pytest.raises(ValueError, match="source dataset_id identity mismatch"):
        verify_publication(output)
    write_json(dataset / "manifest.json", source)
    with pytest.raises(ValueError, match="source dataset_id identity mismatch"):
        publish_feature_atlas(dataset, tmp_path / "new")
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("identity", [None, {}, [], "invalid", 1])
def test_missing_or_malformed_source_identity_rejected(dataset: Path, tmp_path: Path, identity: Any):
    source = json.loads((dataset / "manifest.json").read_text())
    if identity is None:
        source.pop("identity")
    else:
        source["identity"] = identity
    write_json(dataset / "manifest.json", source)
    with pytest.raises(ValueError, match="source producer identity required"):
        publish_feature_atlas(dataset, tmp_path / "new")
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("kind", ["empty", "count", "dataset", "path", "missing_descriptor"])
def test_source_structure_rejection(dataset: Path, tmp_path: Path, kind: str):
    manifest = json.loads((dataset / "manifest.json").read_text())
    if kind in {"empty", "count", "dataset"}:
        comparisons = json.loads((dataset / "comparisons.json").read_text())
        if kind == "empty":
            comparisons["comparisons"] = []
        elif kind == "count":
            comparisons["comparisons"].pop()
        else:
            comparisons["dataset_id"] = "other"
        write_json(dataset / "comparisons.json", comparisons)
        manifest["artifacts"][0]["sha256"] = hashlib.sha256((dataset / "comparisons.json").read_bytes()).hexdigest()
    elif kind == "path":
        manifest["artifacts"][0]["path"] = "../escape.json"
    else:
        manifest["artifacts"].pop(0)
    write_json(dataset / "manifest.json", manifest)
    with pytest.raises(ValueError):
        publish_feature_atlas(dataset, tmp_path / "new")
    assert not (tmp_path / "new").exists()
