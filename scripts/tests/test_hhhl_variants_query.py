"""Synthetic publication integrity and exact-query behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.artifact_store import describe_file, file_digest
from research_core.hhhl_variants_query import CHUNK_BYTES, REQUIRED_COLUMNS, filter_summary, load_event, load_summary, summary_records, summary_transport
from scripts.query_hhhl_variants import main


@pytest.fixture
def publication(tmp_path: Path) -> Path:
    root = tmp_path / "publication with spaces"
    root.mkdir()
    records = []
    for index in range(3):
        row: dict[str, Any] = dict.fromkeys(sorted(REQUIRED_COLUMNS))
        row.update(
            row_kind="candidate",
            candidate_id=f"candidate-{index}",
            cohort_id="P-all",
            split_id="development",
            horizon=126,
            landmark=5,
            riskset_id="new",
            feature_price_basis="frozen-v4",
            calendar_full_n=0,
            hit_n=0,
            loss_n=0,
            flat_win_n=0,
            unknown_n=0,
            censored_n=0,
            known_security_n=0,
            flag_unknown_n=0,
            hit_rate=None,
            feature_id="G",
            bin_id="lt_1.5",
            flag_id="X1",
            year=2020,
        )
        records.append(row)
    records[1].update(split_id="cross-check", horizon=252, hit_rate=0.25)
    pd.DataFrame(records).to_parquet(root / "summary.parquet", index=False)
    descriptor = describe_file(root, root / "summary.parquet")
    descriptor["rows"] = len(records)
    receipt = {
        "schema_version": "hhhl-variants-publication.v1",
        "dataset_id": "synthetic",
        "summary": descriptor,
        # A Windows path need not exist to query the portable summary.
        "local_dataset": {"path": "D:/absent stock inputs/datasets/version-01", "manifest_sha256": "a" * 64},
        "execution": {},
    }
    (root / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return root


def mutate_receipt(root: Path, key: str, value: object) -> None:
    path = root / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["summary"][key] = value
    path.write_text(json.dumps(receipt), encoding="utf-8")


def test_load_without_windows_local_dataset(publication: Path) -> None:
    frame, receipt = load_summary(publication)
    assert len(frame) == 3
    assert receipt["dataset_id"] == "synthetic"
    assert pd.isna(frame.iloc[0]["hit_rate"])


def test_tampered_bytes_fail(publication: Path) -> None:
    with (publication / "summary.parquet").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        load_summary(publication)


def test_same_size_tampering_fails(publication: Path) -> None:
    path = publication / "summary.parquet"
    data = bytearray(path.read_bytes())
    data[10] ^= 1
    path.write_bytes(data)
    with pytest.raises(ValueError, match="hash/size mismatch"):
        load_summary(publication)


@pytest.mark.parametrize("name", ["../summary.parquet", "D:/inputs/summary.parquet", "..\\summary.parquet", "C:\\inputs\\summary.parquet"])
def test_unsafe_descriptor_path_fails(publication: Path, name: str) -> None:
    mutate_receipt(publication, "path", name)
    with pytest.raises(ValueError, match="unsafe artifact name"):
        load_summary(publication)


def test_missing_receipt_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_summary(tmp_path)


@pytest.mark.parametrize("key,value", [("schema_version", "other.v1"), ("dataset_id", ""), ("summary", None)])
def test_invalid_publication_receipt_fails(publication: Path, key: str, value: object) -> None:
    path = publication / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt[key] = value
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError):
        load_summary(publication)


@pytest.mark.parametrize("rows", [0, -1, True, "3"])
def test_invalid_rowcount_fails(publication: Path, rows: object) -> None:
    mutate_receipt(publication, "rows", rows)
    with pytest.raises(ValueError, match="row"):
        load_summary(publication)


def test_missing_schema_column_fails(publication: Path) -> None:
    path = publication / "summary.parquet"
    pd.read_parquet(path).drop(columns="cohort_id").to_parquet(path, index=False)
    receipt_path = publication / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["summary"] = {**describe_file(publication, path), "rows": 3}
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="cohort_id"):
        load_summary(publication)


def test_exact_filters_keep_zero_denominator_null(publication: Path) -> None:
    frame, _ = load_summary(publication)
    result = filter_summary(
        frame,
        row_kind="candidate",
        cohort="P-all",
        split="development",
        horizon=126,
        candidate="candidate-0",
        feature="G",
        bin_id="lt_1.5",
        flag="X1",
        landmark=5,
        riskset="new",
        year=2020,
    )
    assert len(result) == 1
    assert summary_records(result)[0]["hit_rate"] is None
    assert summary_records(result)[0]["calendar_full_n"] == 0
    assert len(frame) == 3
    assert filter_summary(frame, candidate="candidate").empty
    assert filter_summary(frame, limit=0).empty
    assert filter_summary(frame, limit=1)["candidate_id"].tolist() == ["candidate-0"]


def test_nonfinite_records_become_null() -> None:
    frame = pd.DataFrame({"hit_rate": [float("nan"), float("inf"), float("-inf")]})
    assert summary_records(frame) == [{"hit_rate": None}] * 3


def test_filter_missing_column_and_negative_limit(publication: Path) -> None:
    frame, _ = load_summary(publication)
    with pytest.raises(ValueError, match="filter column"):
        filter_summary(frame.drop(columns="flag_id"), flag="X1")
    with pytest.raises(ValueError, match="limit"):
        filter_summary(frame, limit=-1)


def test_cli_verification_and_exact_query(publication: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--publication", str(publication), "--verify"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": "hhhl-variants-publication.v1",
        "dataset_id": "synthetic",
        "rows": 3,
    }
    assert main(["--publication", str(publication), "--candidate", "candidate-0", "--horizon", "126"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output) == 1 and output[0]["hit_rate"] is None


def test_cli_missing_publication_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--publication", str(tmp_path)])
    assert error.value.code == 2
    assert "query failed" in capsys.readouterr().err


EVENT_ID = "hhhl_rule_v4:TW:1101:2020-01-02"


@pytest.fixture
def local_publication(publication: Path) -> Path:
    local = publication.parent / "local dataset"
    local.mkdir()
    artifacts = []
    for part in ("observations", "flags"):
        (local / part).mkdir()
        for ordinal, code in enumerate(("1101", "0050"), 1):
            event = f"hhhl_rule_v4:TW:{code}:2020-01-02"
            frame = pd.DataFrame({"event_id": [event, event], "code": [code, code], "horizon": [126, 252]})
            path = local / part / f"{ordinal:04d}.parquet"
            frame.to_parquet(path, index=False)
            artifacts.append({**describe_file(local, path), "rows": 2, "code": code})
    manifest = {"schema_version": "hhhl-variants-dataset.v1", "dataset_id": "synthetic", "artifacts": artifacts}
    (local / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    path = publication / "receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["local_dataset"] = {"path": str(local.absolute()), "manifest_sha256": file_digest(local / "manifest.json")}
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return publication


@pytest.mark.parametrize("part", ["observations", "flags"])
def test_event_query_two_horizons_and_other_shard_not_read(local_publication: Path, part: str) -> None:
    local = local_publication.parent / "local dataset"
    # Unrelated code is neither required nor verified for this exact event query.
    (local / part / "0002.parquet").unlink()
    frame = load_event(local_publication, EVENT_ID, part)
    assert frame["horizon"].tolist() == [126, 252]
    assert frame["code"].tolist() == ["1101", "1101"]


def test_event_manifest_tamper_fails(local_publication: Path) -> None:
    path = local_publication.parent / "local dataset/manifest.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        load_event(local_publication, EVENT_ID)


def test_event_target_shard_tamper_fails(local_publication: Path) -> None:
    path = local_publication.parent / "local dataset/observations/0001.parquet"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        load_event(local_publication, EVENT_ID)


def test_event_missing_local_version_fails(local_publication: Path) -> None:
    (local_publication.parent / "local dataset/manifest.json").unlink()
    with pytest.raises(FileNotFoundError):
        load_event(local_publication, EVENT_ID)


def test_unknown_event_and_unsupported_part_fail(local_publication: Path) -> None:
    with pytest.raises(ValueError, match="event not found"):
        load_event(local_publication, "hhhl_rule_v4:TW:1101:2020-01-03")
    with pytest.raises(ValueError, match="observations or flags"):
        load_event(local_publication, EVENT_ID, "features")


def test_event_without_code_metadata_scans_shards(local_publication: Path) -> None:
    path = local_publication.parent / "local dataset/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest["artifacts"]:
        entry.pop("code")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt_path = local_publication / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["local_dataset"]["manifest_sha256"] = file_digest(path)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert len(load_event(local_publication, EVENT_ID)) == 2


@pytest.mark.parametrize("fault", ["rowcount", "identity", "traversal", "numeric_code"])
def test_pinned_but_invalid_local_manifest_fails(local_publication: Path, fault: str) -> None:
    path = local_publication.parent / "local dataset/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if fault == "rowcount":
        manifest["artifacts"][0]["rows"] = 3
    elif fault == "identity":
        manifest["dataset_id"] = "other"
    elif fault == "traversal":
        manifest["artifacts"][0]["path"] = "../observations/0001.parquet"
    else:
        manifest["artifacts"][0]["code"] = 1101
    path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt_path = local_publication / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["local_dataset"]["manifest_sha256"] = file_digest(path)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError):
        load_event(local_publication, EVENT_ID)


def test_cli_event_query_limit(local_publication: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--publication", str(local_publication), "--event", EVENT_ID, "--part", "flags", "--limit", "1"]) == 0
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1 and records[0]["event_id"] == EVENT_ID


def install_transport(publication: Path, data: bytes, rows: int) -> dict[str, Any]:
    files, descriptor = summary_transport(data, rows)
    for name, content in files.items():
        (publication / name).write_bytes(content)
    receipt_path = publication / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["summary"] = descriptor
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    (publication / "summary.parquet").unlink()
    return descriptor


def test_binary_chunks_preserve_one_exact_logical_parquet(publication: Path) -> None:
    original = pd.read_parquet(publication / "summary.parquet")
    expected = pd.concat([original] * 200, ignore_index=True)
    expected["large_descriptive_column"] = [f"{index:04d}" + "x" * 1000 for index in range(len(expected))]
    data = expected.to_parquet(index=False, compression=None, use_dictionary=False)
    assert isinstance(data, bytes) and len(data) > CHUNK_BYTES
    descriptor = install_transport(publication, data, len(expected))
    assert len(descriptor["chunks"]) >= 2
    assert all(0 < entry["bytes"] < 500 * 1024 for entry in descriptor["chunks"])
    actual, _ = load_summary(publication)
    pd.testing.assert_frame_equal(actual, expected)
    rebuilt = b"".join((publication / entry["path"]).read_bytes() for entry in descriptor["chunks"])
    assert rebuilt == data


@pytest.mark.parametrize("fault", ["tamper", "missing", "traversal", "oversize", "logical_digest", "logical_size"])
def test_chunk_transport_integrity_fails(publication: Path, fault: str) -> None:
    data = (publication / "summary.parquet").read_bytes()
    descriptor = install_transport(publication, data, 3)
    name = descriptor["chunks"][0]["path"]
    if fault == "tamper":
        (publication / name).write_bytes(b"x" * len(data))
    elif fault == "missing":
        (publication / name).unlink()
    else:
        if fault == "traversal":
            descriptor["chunks"][0]["path"] = "../other.bin"
        elif fault == "oversize":
            descriptor["chunks"][0]["bytes"] = CHUNK_BYTES + 1
        elif fault == "logical_digest":
            descriptor["sha256"] = "0" * 64
        else:
            descriptor["bytes"] += 1
        receipt_path = publication / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["summary"] = descriptor
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        load_summary(publication)
