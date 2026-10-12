"""Serialization-only fixed publication tests on invented artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.artifact_store import file_digest, object_digest, read_json, verify_files, write_json
from research_core.hhhl_variants_publication_v1 import publish_result
from research_core.hhhl_variants_query import REQUIRED_COLUMNS, load_summary


@dataclass
class FakeInputs:
    tables: list[dict[str, Any]]
    pins: dict[str, Any]


@pytest.fixture
def packet(tmp_path: Path) -> dict[str, Any]:
    staging = tmp_path / ".staging-dataset"
    staging.mkdir()
    (staging / "daily").mkdir()
    (staging / "pivots").mkdir()
    pd.DataFrame({"calendar_index": [0, 1], "atr_pct": [None, 0.02]}).to_parquet(staging / "daily/0001.parquet", index=False)
    write_json(staging / "pivots/0001.json", {"code": "0050", "low_pivots": []})
    write_json(staging / "selection.json", {"candidates": [{"candidate_id": "invented"}]})
    row: dict[str, Any] = dict.fromkeys(REQUIRED_COLUMNS)
    row.update(
        row_kind="baseline",
        base_row_kind="baseline",
        cohort_id="P-clean",
        split_id="development",
        horizon=126,
        feature_price_basis="frozen-v4",
        calendar_full_n=0,
        hit_n=0,
        loss_n=0,
        flat_win_n=0,
        unknown_n=0,
        censored_n=0,
        known_security_n=0,
        flag_unknown_n=0,
    )
    pins = tmp_path / "input-pins.json"
    write_json(pins, {"synthetic": True})
    mission = tmp_path / "mission.md"
    mission.write_text("Invented fixed mission\n", encoding="utf-8")
    return {
        "inputs": FakeInputs([{"security_id": "TW:0050"}], {"v4_bulk": {"manifest_sha256": "a" * 64}}),
        "pins_path": pins,
        "staging": staging,
        "final": tmp_path / "dataset",
        "publication": tmp_path / "tracked/publication-v1",
        "summary": pd.DataFrame([row]),
        "selection": {"candidates": [{"candidate_id": "invented"}]},
        "execution": {"code_commit": "synthetic", "cache_lineage": {"source": "invented-prior-attempt"}},
        "mission_path": mission,
    }


def test_fixed_publication_manifest_identity_and_portable_reader(packet: dict[str, Any]) -> None:
    receipt = publish_result(**packet)
    final, publication = packet["final"], packet["publication"]
    assert not packet["staging"].exists()
    manifest = read_json(final / "manifest.json")
    assert manifest["schema_version"] == "hhhl-variants-dataset.v1"
    assert manifest["summary_rows"] == 1 and manifest["candidate_n"] == 1
    assert manifest["dataset_id"] == "hhhl-variants-" + object_digest(manifest["identity"])
    assert manifest["identity"] == {
        "input_pins_sha256": file_digest(packet["pins_path"]),
        "execution": packet["execution"],
        "mission_sha256": file_digest(packet["mission_path"]),
        "definition_id": "hhhl-variants-features.v1",
    }
    descriptors = {entry["path"]: entry for entry in manifest["artifacts"]}
    assert descriptors["daily/0001.parquet"]["rows"] == 2
    assert descriptors["daily/0001.parquet"]["code"] == "0050"
    assert descriptors["pivots/0001.json"]["code"] == "0050"
    assert descriptors["summary.parquet"]["rows"] == 1
    verify_files(final, manifest["artifacts"])
    summary, loaded = load_summary(publication)
    assert loaded == receipt
    assert summary["input_dataset_id"].tolist() == ["hhhl-v4-descriptive-01"]
    assert summary["input_manifest_sha256"].tolist() == ["a" * 64]
    assert "input_dataset_id" not in packet["summary"]  # caller frame retained
    assert receipt["summary_row_kind_counts"] == {"baseline": 1}
    assert receipt["summary_base_row_kind_counts"] == {"baseline": 1}
    assert receipt["execution"]["cache_lineage"] == {"source": "invented-prior-attempt"}
    assert receipt["local_dataset"]["manifest_sha256"] == file_digest(final / "manifest.json")
    assert all(0 < entry["bytes"] < 500 * 1024 for entry in receipt["summary"]["chunks"])


@pytest.mark.parametrize("target", ["final", "publication"])
def test_existing_target_unchanged_and_staging_retained(packet: dict[str, Any], target: str) -> None:
    destination = packet[target]
    destination.mkdir(parents=True)
    marker = destination / "existing.bin"
    marker.write_bytes(b"preserve existing target")
    initial = file_digest(packet["staging"] / "daily/0001.parquet")
    with pytest.raises(FileExistsError):
        publish_result(**packet)
    assert marker.read_bytes() == b"preserve existing target"
    assert file_digest(packet["staging"] / "daily/0001.parquet") == initial
    assert not (packet["staging"] / "summary.parquet").exists()


def test_non_sibling_dataset_paths_rejected_before_writing(packet: dict[str, Any]) -> None:
    packet["final"] = packet["final"].parent / "nested/dataset"
    with pytest.raises(ValueError, match="sibling"):
        publish_result(**packet)
    assert not (packet["staging"] / "summary.parquet").exists()


def test_failed_identity_read_keeps_staging_evidence(packet: dict[str, Any]) -> None:
    packet["mission_path"].unlink()
    with pytest.raises(FileNotFoundError):
        publish_result(**packet)
    assert (packet["staging"] / "summary.parquet").is_file()
    assert not packet["final"].exists()
    assert not packet["publication"].exists()


def test_staged_summary_not_replaced(packet: dict[str, Any]) -> None:
    path = packet["staging"] / "summary.parquet"
    path.write_bytes(b"prior attempt evidence")
    with pytest.raises(FileExistsError):
        publish_result(**packet)
    assert path.read_bytes() == b"prior attempt evidence"
