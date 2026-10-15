"""Physical synthetic result handoff and immediate owned-scratch retirement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_result_lifecycle_v3 as lifecycle
from research_core.artifact_store import file_digest, read_json, write_json
from research_core.research_data_catalog import DataCatalog, verify_entry
from research_core.research_data_paths import DataRoots

MANAGED_PARENT = "bundles/synthetic-retained-results"


@pytest.fixture
def synthetic_source() -> dict[str, Any]:
    return {
        "schema": "pattern-scan-source.git.v2",
        "source_id": "synthetic-source",
        "code": {"commit": "a" * 40, "dirty": False},
    }


def _metadata(source: dict[str, Any]) -> dict[str, Any]:
    unavailable = {"start": None, "end": None, "reason": "synthetic only"}
    return {
        "data_id": "synthetic-retained-results",
        "kind": "patterns",
        "definition_version": "fixture.v1",
        "parameters": {"fixture": True},
        "inputs": {"source_id": source["source_id"], "input_id": "synthetic-input"},
        "coverage": {
            "scope": "invented",
            "raw_input_period": unavailable,
            "valid_indicator_period": unavailable,
            "complete_label_period": unavailable,
        },
        "status": "complete",
        "limitations": ["synthetic fixture"],
        "backup": {"status": "not_backed_up", "off_machine": False},
    }


@pytest.fixture
def case(tmp_path: Path, synthetic_source: dict[str, Any]) -> dict[str, Any]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    run = primary / ".tmp/pattern-scan-execution/synthetic-results"
    for name in ("analysis", "audits", "prepared", "parts/stock", "global"):
        (run / name).mkdir(parents=True)
    aggregate = run / "analysis/aggregate.parquet"
    pq.write_table(pa.table({"cell_id": ["one", "two"], "known_n": [3, 4]}), aggregate, compression="zstd")
    audit = run / "audits/independent.json"
    write_json(audit, {"complete": True, "mismatch_n": 0})
    execution = run / "request-all.json"
    write_json(execution, {"source": synthetic_source, "mode": "all"})
    report = run / "analysis/report.md"
    report.write_text("# Synthetic report\n\nVerified invented aggregates.\n", encoding="utf-8")
    verification = run / "audits/delivery-verification.json"
    write_json(
        verification,
        {
            "schema": "pattern-scan-delivery-verification.v3",
            "complete": True,
            "source_id": synthetic_source["source_id"],
            "input_id": "synthetic-input",
            "event_audit_n": 10,
            "candidate_audit_n": 5,
            "candidate_comparison_rows": 54_720,
            "mismatch_n": 0,
        },
    )
    transient = run / "prepared/prices.parquet"
    pq.write_table(pa.table({"close": [1.0, 2.0]}), transient)
    (run / "parts/stock/events.bin").write_bytes(b"owned expanded event details")
    write_json(run / "global/receipt.json", {"consumed": True})
    older = run.parent / "older-profile"
    older.mkdir()
    old_json = older / "resource-profile.json"
    write_json(old_json, {"historical": True})
    files = {
        "aggregates/aggregate.parquet": aggregate,
        "audits/independent.json": audit,
        "execution/request.json": execution,
        "execution/resource-profile.json": old_json,
    }
    descriptor = lifecycle.record_computed_results(
        run,
        files,
        source=synthetic_source,
        input_id="synthetic-input",
        provenance={"original_scope": "invented"},
        transient_files=[path for path in run.rglob("*") if path.is_file()],
    )
    return {
        "roots": roots,
        "catalog": DataCatalog(roots),
        "run": run,
        "source": synthetic_source,
        "files": files,
        "descriptor": descriptor,
        "metadata": _metadata(synthetic_source),
        "report": report,
        "verification": verification,
        "transient": transient,
        "older": older,
    }


def _handoff(case: dict[str, Any]) -> dict[str, Any]:
    return lifecycle.handoff_results(
        case["descriptor"],
        case["catalog"],
        case["metadata"],
        managed_parent=MANAGED_PARENT,
        verification=case["verification"],
        report=case["report"],
    )


def _final(case: dict[str, Any], proof: dict[str, Any]) -> Path:
    entry = proof["entry"]
    return case["roots"].artifact_path(entry["manifest"]["scope"], entry["manifest"]["path"]).parent


def _hashes(directory: Path) -> dict[str, str]:
    return {path.relative_to(directory).as_posix(): file_digest(path) for path in directory.rglob("*") if path.is_file()}


def test_computed_inventory_records_bytes_footer_and_unpublished_state(case: dict[str, Any]) -> None:
    body = lifecycle.verify_computed_results(case["descriptor"])
    aggregate = next(row for row in body["artifacts"] if row["path"] == "aggregates/aggregate.parquet")
    assert aggregate["rows"] == 2 and aggregate["compression"] == ["ZSTD"]
    assert aggregate["bytes"] == case["files"][aggregate["path"]].stat().st_size
    assert body["payload_bytes"] == sum(row["bytes"] for row in body["artifacts"])
    assert body["state"] == "computed_unpublished" and body["permanent_location"] is None
    assert body["source"] == case["source"] and body["input_id"] == "synthetic-input"
    assert not case["roots"].data.exists()
    assert case["transient"].is_file()


@pytest.mark.parametrize("changed", ("aggregate", "index"))
def test_corrupt_computed_result_or_index_rejected(case: dict[str, Any], changed: str) -> None:
    path = case["files"]["aggregates/aggregate.parquet"] if changed == "aggregate" else Path(case["descriptor"]["path"])
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="changed"):
        lifecycle.verify_computed_results(case["descriptor"])


@pytest.mark.parametrize("operation", ("handoff", "cleanup"))
def test_active_scan_blocks_handoff_and_cleanup_before_mutation(case: dict[str, Any], operation: str) -> None:
    write_json(case["run"] / lifecycle.ACTIVE, {"pid": 123})
    before = _hashes(case["run"])
    with pytest.raises(ValueError, match="actively executing"):
        if operation == "handoff":
            _handoff(case)
        else:
            lifecycle.cleanup_run(case["run"], case["catalog"])
    assert _hashes(case["run"]) == before
    assert not case["roots"].data.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema", "wrong"),
        ("complete", False),
        ("source_id", "different"),
        ("input_id", "different"),
        ("event_audit_n", 9),
        ("event_audit_n", 11),
        ("candidate_audit_n", 4),
        ("candidate_audit_n", 6),
        ("candidate_comparison_rows", 54_719),
        ("candidate_comparison_rows", 54_721),
        ("mismatch_n", 1),
    ),
)
def test_exact_delivery_audit_packet_required(case: dict[str, Any], field: str, value: Any) -> None:
    packet = read_json(case["verification"])
    packet[field] = value
    case["verification"].unlink()
    write_json(case["verification"], packet)
    before = _hashes(case["run"])
    with pytest.raises(ValueError, match="ten-event/five-candidate"):
        _handoff(case)
    assert _hashes(case["run"]) == before
    assert not (case["run"] / "handoff-plan.json").exists()


@pytest.mark.parametrize("missing", ("verification", "report"))
def test_missing_delivery_file_blocks_handoff_without_moving_results(case: dict[str, Any], missing: str) -> None:
    case[missing].unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        _handoff(case)
    assert all(path.is_file() for path in case["files"].values())
    assert not (case["run"] / "handoff-plan.json").exists()


def test_single_copy_handoff_and_immediate_physical_cleanup(case: dict[str, Any]) -> None:
    owned = {name: path.stat() for name, path in case["files"].items() if path.is_relative_to(case["run"])}
    owned["report.md"] = case["report"].stat()
    older_before = _hashes(case["older"])
    proof = _handoff(case)
    final = _final(case, proof)
    body = verify_entry(proof["entry"], case["roots"])
    names = {row["path"] for row in body["artifacts"]}
    assert names == {*case["files"], "report.md", "audits/delivery-verification.json", "run-receipt.json"}
    for name, before in owned.items():
        after = (final / name).stat()
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
        assert after.st_nlink == 1
    assert not case["report"].exists()
    assert all(not path.exists() for path in case["files"].values() if path.is_relative_to(case["run"]))
    assert not (case["roots"].primary / "research_cache").exists()
    retained_before = _hashes(final)
    cleanup = lifecycle.cleanup_run(case["run"], case["catalog"])
    assert cleanup["complete"] is True and cleanup["recovery_period_days"] == 0
    assert cleanup["removed_files"] > 0 and cleanup["removed_bytes"] > 0
    assert {path.name for path in case["run"].iterdir()} == {"publication-handoff.json", "cleanup-receipt.json"}
    assert not case["transient"].exists()
    assert _hashes(final) == retained_before and _hashes(case["older"]) == older_before
    verify_entry(proof["entry"], case["roots"])
    assert pq.read_table(final / "aggregates/aggregate.parquet").column("known_n").to_pylist() == [3, 4]
    receipt = read_json(final / "run-receipt.json")
    assert receipt["code"] == case["source"]["code"] and receipt["input_id"] == "synthetic-input"


def test_registration_interruption_resumes_final_with_immutable_journals(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    original = case["catalog"].register

    def interrupted(entries: Any) -> None:
        raise RuntimeError("invented registration interruption")

    monkeypatch.setattr(case["catalog"], "register", interrupted)
    with pytest.raises(RuntimeError, match="registration interruption"):
        _handoff(case)
    journals = {name: file_digest(case["run"] / name) for name in ("handoff-plan.json", "publication-ready.json")}
    ready = read_json(case["run"] / "publication-ready.json")
    assert not Path(ready["stage"]).exists()
    final = _final(case, ready)
    verify_entry(ready["entry"], case["roots"])
    assert not (case["run"] / "publication-handoff.json").exists()
    with pytest.raises((ValueError, FileNotFoundError)):
        lifecycle.cleanup_run(case["run"], case["catalog"])
    monkeypatch.setattr(case["catalog"], "register", original)
    proof = _handoff(case)
    assert proof["entry"] == ready["entry"] and _final(case, proof) == final
    assert journals == {name: file_digest(case["run"] / name) for name in journals}
    assert len(case["catalog"].read()["entries"]) == 1


def test_interrupted_individual_relocation_resumes_without_duplicate_payload(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    original = lifecycle.relocate_noreplace
    moved: list[tuple[Path, Path]] = []

    def interrupted(source: Path, target: Path) -> None:
        original(source, target)
        moved.append((source, target))
        raise RuntimeError("invented crash after completed file relocation")

    monkeypatch.setattr(lifecycle, "relocate_noreplace", interrupted)
    with pytest.raises(RuntimeError, match="completed file relocation"):
        _handoff(case)
    assert len(moved) == 1 and not moved[0][0].exists() and moved[0][1].is_file()
    journal_hash = file_digest(case["run"] / "handoff-plan.json")
    inode = moved[0][1].stat().st_ino
    monkeypatch.setattr(lifecycle, "relocate_noreplace", original)
    proof = _handoff(case)
    assert file_digest(case["run"] / "handoff-plan.json") == journal_hash
    plan = read_json(case["run"] / "handoff-plan.json")
    first_name = next(row["path"] for row in plan["artifacts"] if row["source_path"] == str(moved[0][0]))
    assert (_final(case, proof) / first_name).stat().st_ino == inode
    verify_entry(proof["entry"], case["roots"])


@pytest.mark.parametrize("damage", ("unknown", "hardlink", "symlink"))
def test_unsafe_scratch_blocks_cleanup_before_any_deletion(case: dict[str, Any], tmp_path: Path, damage: str) -> None:
    _handoff(case)
    if damage == "unknown":
        (case["run"] / "unowned.txt").write_bytes(b"must survive")
    elif damage == "hardlink":
        os.link(case["transient"], tmp_path / "outside-hardlink.parquet")
    else:
        try:
            (case["run"] / "analysis/linked-directory").symlink_to(case["older"], target_is_directory=True)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip("Windows session lacks symbolic-link privilege")
            raise
    before = _hashes(case["run"])
    with pytest.raises(ValueError, match="unknown|hardlink|linked|reparse"):
        lifecycle.cleanup_run(case["run"], case["catalog"])
    assert _hashes(case["run"]) == before


def test_unknown_nested_file_blocks_cleanup_before_any_deletion(case: dict[str, Any]) -> None:
    _handoff(case)
    (case["run"] / "analysis/unowned.txt").write_bytes(b"not a declared owned artifact")
    before = _hashes(case["run"])
    with pytest.raises(ValueError, match="unknown|ownership"):
        lifecycle.cleanup_run(case["run"], case["catalog"])
    assert _hashes(case["run"]) == before


def test_formal_corruption_blocks_cleanup_before_any_deletion(case: dict[str, Any]) -> None:
    proof = _handoff(case)
    (_final(case, proof) / "aggregates/aggregate.parquet").write_bytes(b"corrupt formal result")
    before = _hashes(case["run"])
    with pytest.raises(ValueError, match="mismatch"):
        lifecycle.cleanup_run(case["run"], case["catalog"])
    assert _hashes(case["run"]) == before and case["transient"].is_file()


def test_no_cleanup_without_publication_and_reference_handoff(case: dict[str, Any]) -> None:
    before = _hashes(case["run"])
    with pytest.raises((ValueError, FileNotFoundError)):
        lifecycle.cleanup_run(case["run"], case["catalog"])
    assert _hashes(case["run"]) == before


def test_catalog_publication_alone_cannot_authorize_cleanup(case: dict[str, Any]) -> None:
    proof = _handoff(case)
    verify_entry(proof["entry"], case["roots"])
    (case["run"] / "publication-handoff.json").unlink()
    before = _hashes(case["run"])
    with pytest.raises((ValueError, FileNotFoundError)):
        lifecycle.cleanup_run(case["run"], case["catalog"])
    assert _hashes(case["run"]) == before and case["transient"].is_file()
