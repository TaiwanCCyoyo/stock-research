"""Report execution metadata selection for live Git and archived seal protocols."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from research_core import pattern_scan_analysis_v1 as analysis
from research_core.artifact_store import file_digest, read_json, write_json


@pytest.fixture
def live(tmp_path: Path) -> tuple[Path, dict[str, Any], str, dict[str, Path]]:
    run = tmp_path / "run"
    run.mkdir()
    output = run / "analysis"
    source = {"schema": "pattern-scan-source.git.v2", "source_id": "synthetic-git-source", "code": {"commit": "a" * 40, "dirty": False}}
    input_id = "synthetic-input"
    index = run / "derived-preparation.json"
    write_json(index, {"schema": "pattern-scan-derived-preparation.v2", "scope": "full_ordinary_reference", "source": source, "input_id": input_id})
    producer_receipt = run / "producer-read-receipt.json"
    write_json(
        producer_receipt,
        {
            "schema": "run-receipt.v1",
            "run_id": "synthetic:producer-read",
            "results": {
                "derived_preparation": {
                    "path": str(index),
                    "bytes": index.stat().st_size,
                    "sha256": file_digest(index),
                }
            },
        },
    )
    profile, capacity = tmp_path / "chosen-profile.json", tmp_path / "chosen-capacity.json"
    write_json(profile, {"schema": "pattern-scan-resource-profile.v1", "source_id": source["source_id"], "input_id": input_id})
    write_json(capacity, {"schema": "pattern-scan-capacity.v2", "synthetic": True})
    request = run / "request-all.json"
    write_json(
        request,
        {
            "schema": "pattern-scan-coordinator-request.v2",
            "calculation_authorized": True,
            "mode": "all",
            "source": source,
            "run_id": "synthetic",
            "run_root": str(run),
            "prepared_path": str(index),
            "profile_path": str(profile),
            "capacity_path": str(capacity),
        },
    )
    expected = {
        "execution/request.json": request,
        "execution/derived-preparation.json": index,
        "execution/producer-read-receipt.json": producer_receipt,
        "execution/resource-profile.json": profile,
        "execution/capacity-plan.json": capacity,
    }
    return output, source, input_id, expected


def _replace(path: Path, key: str, value: Any) -> None:
    record = read_json(path)
    record[key] = value
    path.unlink()
    write_json(path, record)


def test_live_metadata_uses_explicit_profile_capacity_and_needs_no_source_archive(live: Any) -> None:
    output, source, input_id, expected = live
    assert not (output.parent / "seal").exists()
    assert not (output.parent / "run-all-receipt.json").exists()
    assert analysis._report_execution_files(output, source, input_id) == expected
    assert not list(output.parent.rglob("*.zip"))
    assert not output.exists()


@pytest.mark.parametrize(
    "name",
    [
        "execution/request.json",
        "execution/derived-preparation.json",
        "execution/producer-read-receipt.json",
        "execution/resource-profile.json",
        "execution/capacity-plan.json",
    ],
)
def test_live_missing_required_metadata_fails_before_analysis(live: Any, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    output, source, input_id, expected = live
    expected[name].unlink()
    monkeypatch.setattr(analysis, "verify_source", lambda source: None)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("missing execution provenance must fail before loading or computing analysis")

    monkeypatch.setattr(analysis, "load_shared", forbidden)
    with pytest.raises(ValueError, match="metadata"):
        analysis.run_analysis(cast(Any, None), {}, {}, {}, output, source=source, input_id=input_id)
    assert not output.exists()


@pytest.mark.parametrize(
    "name,key,value",
    [
        ("execution/request.json", "source", {"source_id": "other"}),
        ("execution/request.json", "mode", "stock"),
        ("execution/request.json", "run_root", "unowned-run"),
        ("execution/request.json", "prepared_path", "different-derived-preparation.json"),
        ("execution/request.json", "profile_path", None),
        ("execution/request.json", "capacity_path", None),
        ("execution/derived-preparation.json", "source", {"source_id": "other"}),
        ("execution/derived-preparation.json", "input_id", "other-input"),
        ("execution/derived-preparation.json", "scope", "representative_resource_probe"),
        ("execution/producer-read-receipt.json", "run_id", "other:producer-read"),
        ("execution/producer-read-receipt.json", "results", {}),
        ("execution/resource-profile.json", "source_id", "other-source"),
        ("execution/resource-profile.json", "input_id", "other-input"),
        ("execution/capacity-plan.json", "schema", "other-protocol"),
    ],
)
def test_live_mismatched_metadata_identity_fails_closed(live: Any, name: str, key: str, value: Any) -> None:
    output, source, input_id, expected = live
    _replace(expected[name], key, value)
    with pytest.raises(ValueError, match="identity|metadata|protocol"):
        analysis._report_execution_files(output, source, input_id)


def test_legacy_report_keeps_exact_two_seal_paths(tmp_path: Path) -> None:
    output = tmp_path / "run" / "analysis"
    assert analysis._report_execution_files(output, {"schema": "pattern-scan-source.v1"}, "legacy-input") == {
        "executed-sources.zip": output.parent / "seal" / "executed-sources.zip",
        "source.json": output.parent / "seal" / "source.json",
    }


def test_live_run_analysis_publisher_receives_selected_metadata(live: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_completion_v1 as completion

    output, source, input_id, expected = live
    monkeypatch.setattr(analysis, "verify_source", lambda source: None)
    monkeypatch.setattr(analysis, "load_shared", lambda *args: SimpleNamespace(consumption_measurements=[]))
    monkeypatch.setattr(analysis, "prepare_event_parts", lambda *args, **kwargs: {})
    monkeypatch.setattr(analysis, "select_all", lambda *args: {})
    monkeypatch.setattr(analysis, "_audits", lambda *args, **kwargs: {"files": {}})
    counts = {
        name: 0
        for name in (
            "full_cell_n",
            "annual_row_n",
            "candidate_primary_row_n",
            "primary_single_row_n",
            "secondary_single_row_n",
            "missing_diagnostic_row_n",
            "full_plus_drop_and_annual_rows_per_cell",
        )
    }
    monkeypatch.setattr(analysis, "summarize_all", lambda *args: {"files": {}, **counts})
    monkeypatch.setattr(completion, "complete_followup", lambda *args, **kwargs: {"episodes": {"files": {}}, "files": {}})
    monkeypatch.setattr(analysis, "metadata", lambda *args: {"inputs": {}, "parameters": {}, "coverage": {}, "backup": {}})
    monkeypatch.setattr(analysis, "DataCatalog", lambda roots: None)
    published = []

    def publish(catalog: Any, meta: dict[str, Any], files: dict[str, Path], **kwargs: Any) -> dict[str, Any]:
        published.append((meta["data_id"], dict(files)))
        return {"data_id": meta["data_id"], "version_id": "synthetic-version", "manifest": {"sha256": "synthetic-hash"}}

    monkeypatch.setattr(analysis, "publish_file_bundle", publish)
    entries = {"labels": {"data_id": "labels", "version_id": "synthetic-labels", "manifest": {"sha256": "synthetic-label-hash"}}}
    result = analysis.run_analysis(cast(Any, None), {}, {"calendar": ["2020-01-02"]}, entries, output, source=source, input_id=input_id)
    assert result["shared_report_tables"]["data_id"] == "pattern-scan-report-tables-full-2010-v1"
    report_files = published[-1][1]
    assert report_files == {"selection.json": output / "selection.json", **expected}
    assert not any(name.endswith(".zip") or name == "source.json" for name in report_files)
    assert "run-all-receipt.json" not in report_files
