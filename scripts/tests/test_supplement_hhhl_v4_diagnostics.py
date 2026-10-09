"""Synthetic checks for the portable v4 landmark-reason supplement."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.jobs import file_digest
from scripts.publish_hhhl_v4_probability import convert_publication, publish, verify_publication
from scripts.supplement_hhhl_v4_diagnostics import _read_supplement_archive, create_supplement, main, verify_supplement
from scripts.tests.test_publish_hhhl_v4_probability import _summary_rows as _fixed_summary_rows
from scripts.validate_hhhl_v4_source import write_json


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _summary_rows() -> list[dict[str, Any]]:
    return _fixed_summary_rows()


def _legacy_census(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for landmark in (10, 20, 40):
        for status in ("active", "early_hit", "early_failed", "unknown"):
            for eligible in (True, False):
                group = frame.loc[frame["landmark"].eq(landmark) & frame["status"].eq(status) & frame["base_eligible"].eq(eligible)]
                rows.append({
                    "landmark": landmark,
                    "status": status,
                    "eligible": eligible,
                    "events": len(group),
                    "securities": int(group["security_id"].nunique()),
                })
    return rows


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _rewrite_supplement(path: Path, mutate: Any) -> None:
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(contents["manifest.json"])
    mutate(metadata, contents)
    if "reason-census.json" in contents:
        census_bytes = contents["reason-census.json"]
        metadata["artifacts"]["reason-census.json"] = {"sha256": _sha(census_bytes), "bytes": len(census_bytes)}
    contents["manifest.json"] = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def _synthetic_publication(tmp_path: Path, *, helper_override: bytes | None = None) -> tuple[Path, Path, pd.DataFrame]:
    run = tmp_path / "run"
    run.mkdir()
    checkout = tmp_path / "synthetic-checkout"
    builder = checkout / "scripts" / "build_hhhl_v4_probability.py"
    helper = Path(__file__).resolve().parents[2] / "research_core" / "hhhl_v4_summary.py"
    if helper_override is not None:
        helper = checkout / "research_core" / "hhhl_v4_summary.py"
        _write_bytes(helper, helper_override)
    _write_bytes(builder, b"# synthetic producer code\n")
    _write_bytes(checkout / "mission.md", b"synthetic frozen mission\n")

    landmarks = pd.DataFrame([
        {"security_id": "A", "landmark": 10, "base_eligible": True, "status": "unknown", "reason": "missing_before_landmark"},
        {"security_id": "A", "landmark": 10, "base_eligible": True, "status": "unknown", "reason": "window_end"},
        {"security_id": "B", "landmark": 10, "base_eligible": False, "status": "unknown", "reason": "missing_before_landmark"},
        {"security_id": "C", "landmark": 20, "base_eligible": False, "status": "unknown", "reason": "window_end"},
    ])
    landmarks.to_parquet(run / "landmarks.parquet", index=False)
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_bytes = {
        "summaries.json": json.dumps(_summary_rows(), separators=(",", ":")).encode("utf-8"),
        "diagnostics.json": json.dumps({"landmark_census": _legacy_census(landmarks), "label_discordance": []}).encode("utf-8"),
        "coverage.json": b"[]\n",
        "audit-sample.parquet": b"synthetic audit placeholder",
        "label-discordance-63.parquet": b"synthetic 63-day placeholder",
        "label-discordance-126.parquet": b"synthetic 126-day placeholder",
        "landmarks.parquet": (run / "landmarks.parquet").read_bytes(),
    }
    for name, data in artifact_bytes.items():
        if name != "landmarks.parquet":
            _write_bytes(run / name, data)
        artifacts[name] = {"sha256": _sha(data), "bytes": len(data)}

    helper_bytes = helper.read_bytes()
    identity = {
        str(builder.resolve()): _sha(builder.read_bytes()),
        "mission.md": _sha((checkout / "mission.md").read_bytes()),
        str(helper.resolve()): _sha(helper_bytes),
    }
    write_json(
        run / "manifest.json",
        {
            "schema_version": "hhhl-probability.v4",
            "complete": True,
            "code_commit": "synthetic-commit",
            "identity": identity,
            "counts": {"landmarks": len(landmarks)},
            "artifacts": artifacts,
        },
    )
    v1_root = tmp_path / "publication-v1"
    publication_root = tmp_path / "publication-v2"
    publish(run, v1_root)
    convert_publication(v1_root, publication_root)
    return run, publication_root, landmarks


def test_original_and_supplement_helper_vintages_remain_separately_bound(tmp_path: Path) -> None:
    run, publication, _ = _synthetic_publication(tmp_path, helper_override=b"# synthetic older helper identity\n")
    output = tmp_path / "new-supplement.zip"
    metadata = create_supplement(run, publication, output)
    assert metadata["source_summary_helper_sha256"] != metadata["summary_helper_sha256"]
    assert verify_supplement(output, publication)["metadata"] == metadata

    def wrong_current(identity: dict[str, Any], _contents: dict[str, bytes]) -> None:
        identity["summary_helper_sha256"] = "0" * 64

    _rewrite_supplement(output, wrong_current)
    with pytest.raises(ValueError, match="helper snapshot identity mismatch"):
        verify_supplement(output, publication)


def test_supplement_is_bound_portable_and_preserves_both_unknown_reasons(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run, publication, source = _synthetic_publication(tmp_path)
    run_manifest_before = (run / "manifest.json").read_bytes()
    run_manifest = json.loads(run_manifest_before)
    landmark_sha = file_digest(run / "landmarks.parquet")
    publication_before = {path.name: path.read_bytes() for path in publication.iterdir()}
    supplement = tmp_path / "diagnostics-supplement.zip"

    assert main(["--run", str(run), "--publication", str(publication), "--output", str(supplement)]) == 0
    metadata = json.loads(capsys.readouterr().out)
    publication_metadata = verify_publication(publication)["metadata"]
    assert metadata["original_run_manifest_sha256"] == publication_metadata["run_manifest_sha256"]
    assert metadata["original_bundle_sha256"] == publication_metadata["bundle_sha256"]
    assert metadata["source_landmark_path"] == "landmarks.parquet"
    assert metadata["source_landmark_sha256"] == landmark_sha
    assert metadata["source_landmark_bytes"] == (run / "landmarks.parquet").stat().st_size
    assert metadata["complete"] is True
    assert set(metadata["artifacts"]) == {
        "reason-census.json",
        "landmarks.parquet",
        "code/research_core/hhhl_v4_summary.py",
        "code/scripts/supplement_hhhl_v4_diagnostics.py",
    }
    producer_identity = next(
        digest for path, digest in run_manifest["identity"].items() if path.replace("\\", "/").endswith("scripts/build_hhhl_v4_probability.py")
    )
    helper_identity = next(digest for path, digest in run_manifest["identity"].items() if path.replace("\\", "/").endswith("research_core/hhhl_v4_summary.py"))
    assert metadata["producer_code_sha256"] == producer_identity
    assert metadata["summary_helper_sha256"] == helper_identity
    assert metadata["source_summary_helper_sha256"] == helper_identity
    assert metadata["supplement_script_sha256"]
    assert (run / "manifest.json").read_bytes() == run_manifest_before
    assert file_digest(run / "landmarks.parquet") == landmark_sha
    assert {path.name: path.read_bytes() for path in publication.iterdir()} == publication_before

    with zipfile.ZipFile(supplement) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "reason-census.json",
            "landmarks.parquet",
            "code/research_core/hhhl_v4_summary.py",
            "code/scripts/supplement_hhhl_v4_diagnostics.py",
        }
        census = json.loads(archive.read("reason-census.json"))
        projection = pd.read_parquet(io.BytesIO(archive.read("landmarks.parquet")))
    assert tuple(projection.columns) == ("security_id", "landmark", "base_eligible", "status", "reason")
    assert len(projection) == len(source)
    assert sum(row["rows"] for row in census) == len(source)
    assert {row["reason"] for row in census} == {"missing_before_landmark", "window_end"}
    assert {row["eligibility"] for row in census} == {"eligible", "ineligible"}

    # Verification relies on the sealed publication and supplement, not the bulky source run.
    run.rename(tmp_path / "run-unavailable")
    verified = verify_supplement(supplement, publication)
    assert verified["metadata"] == metadata
    assert verified["census"] == census
    before = supplement.read_bytes()
    with pytest.raises(FileExistsError):
        create_supplement(run, publication, supplement)
    assert supplement.read_bytes() == before


def test_run_manifest_mismatch_is_rejected_before_supplement_write(tmp_path: Path) -> None:
    run, publication, _ = _synthetic_publication(tmp_path)
    manifest_path = run / "manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    output = tmp_path / "mismatch.zip"

    with pytest.raises(ValueError, match="run manifest does not match the saved publication"):
        create_supplement(run, publication, output)
    assert not output.exists()


def test_supplement_archive_tampering_is_rejected(tmp_path: Path) -> None:
    run, publication, _ = _synthetic_publication(tmp_path)
    supplement = tmp_path / "diagnostics-supplement.zip"
    create_supplement(run, publication, supplement)
    data = bytearray(supplement.read_bytes())
    data[len(data) // 2] ^= 1
    supplement.write_bytes(data)

    with pytest.raises(ValueError):
        verify_supplement(supplement, publication)


def test_supplement_normalizes_deflate_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, publication, _ = _synthetic_publication(tmp_path)
    supplement = tmp_path / "bad-deflate.zip"
    create_supplement(run, publication, supplement)

    def broken_read(*_args: Any, **_kwargs: Any) -> bytes:
        raise zlib.error("synthetic invalid distance")

    monkeypatch.setattr(zipfile.ZipExtFile, "read", broken_read)
    with pytest.raises(ValueError, match="invalid diagnostics supplement ZIP") as failure:
        _read_supplement_archive(supplement)
    assert isinstance(failure.value.__cause__, zlib.error)


def test_rehashed_census_cannot_shift_rows_between_legacy_cells(tmp_path: Path) -> None:
    run, publication, _ = _synthetic_publication(tmp_path)
    supplement = tmp_path / "diagnostics-supplement.zip"
    create_supplement(run, publication, supplement)

    def shift_cell(_metadata: dict[str, Any], contents: dict[str, bytes]) -> None:
        census = json.loads(contents["reason-census.json"])
        census[0]["landmark"] = 20  # Keep the grand total but move rows to a different legacy cell.
        contents["reason-census.json"] = json.dumps(census, ensure_ascii=False, indent=2).encode("utf-8")

    _rewrite_supplement(supplement, shift_cell)

    with pytest.raises(ValueError, match="reason census does not exactly match recomputed landmark source rows"):
        verify_supplement(supplement, publication)


@pytest.mark.parametrize("field", ["reason", "securities"])
def test_rehashed_reason_census_must_match_saved_landmark_rows(tmp_path: Path, field: str) -> None:
    _run, publication, _ = _synthetic_publication(tmp_path)
    supplement = tmp_path / "diagnostics-supplement.zip"
    create_supplement(_run, publication, supplement)

    def change_census(_metadata: dict[str, Any], contents: dict[str, bytes]) -> None:
        census = json.loads(contents["reason-census.json"])
        if field == "reason":
            # This preserves every legacy L/status/eligibility event total.
            census[0]["reason"] = "forged-reason-reallocation"
        else:
            census[0]["securities"] += 1
        contents["reason-census.json"] = json.dumps(census, ensure_ascii=False, indent=2).encode("utf-8")

    _rewrite_supplement(supplement, change_census)
    with pytest.raises(ValueError, match="reason census does not exactly match recomputed landmark source rows"):
        verify_supplement(supplement, publication)


def test_rehashed_landmark_projection_must_reconstruct_exact_reason_census(tmp_path: Path) -> None:
    run, publication, _ = _synthetic_publication(tmp_path)
    supplement = tmp_path / "diagnostics-supplement.zip"
    create_supplement(run, publication, supplement)

    def change_projection(metadata: dict[str, Any], contents: dict[str, bytes]) -> None:
        frame = pd.read_parquet(io.BytesIO(contents["landmarks.parquet"]))
        frame.loc[0, "reason"] = "forged-source-reason"
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)
        contents["landmarks.parquet"] = buffer.getvalue()
        metadata["artifacts"]["landmarks.parquet"] = {
            "sha256": _sha(contents["landmarks.parquet"]),
            "bytes": len(contents["landmarks.parquet"]),
        }

    _rewrite_supplement(supplement, change_projection)
    with pytest.raises(ValueError, match="reason census does not exactly match recomputed landmark source rows"):
        verify_supplement(supplement, publication)


def test_supplement_source_projection_identity_must_match_publication(tmp_path: Path) -> None:
    run, publication, _ = _synthetic_publication(tmp_path)
    supplement = tmp_path / "diagnostics-supplement.zip"
    create_supplement(run, publication, supplement)

    def change_identity(metadata: dict[str, Any], _contents: dict[str, bytes]) -> None:
        metadata["source_landmark_sha256"] = "0" * 64

    _rewrite_supplement(supplement, change_identity)
    with pytest.raises(ValueError, match="supplement source landmark hash does not match publication identity"):
        verify_supplement(supplement, publication)


def test_legacy_v1_supplement_is_rejected_for_current_verification(tmp_path: Path) -> None:
    run, publication, _ = _synthetic_publication(tmp_path)
    supplement = tmp_path / "diagnostics-supplement.zip"
    create_supplement(run, publication, supplement)
    with zipfile.ZipFile(supplement) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        census = archive.read("reason-census.json")
    manifest["schema_version"] = "hhhl-v4-diagnostics-supplement.v1"
    manifest["artifacts"].pop("landmarks.parquet")
    with zipfile.ZipFile(supplement, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("reason-census.json", census)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    with pytest.raises(ValueError, match="legacy v1 diagnostics supplement lacks source rows"):
        verify_supplement(supplement, publication)
