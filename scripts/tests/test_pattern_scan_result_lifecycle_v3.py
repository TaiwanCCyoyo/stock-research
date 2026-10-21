"""Synthetic result handoff, non-price cleanup and later prepared retirement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_result_lifecycle_v3 as lifecycle
from research_core.artifact_store import canonical, file_digest, object_digest, read_json, write_json
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
    equivalence = run / "audits/price-reader-equivalence.json"
    write_json(
        equivalence,
        {
            "schema": "pattern-scan-price-reader-equivalence.v3",
            "complete": True,
            "reference_source_id": synthetic_source["source_id"],
            "reference_input_id": "synthetic-input",
            "calendar_n": 4110,
            "security_n": 1943,
            "cutoff": "2026-10-12",
            "all_columns_equal": True,
            "calendar_equal": True,
            "quality_equal": True,
            "mismatch_n": 0,
            "generation": "synthetic-shared-generation",
        },
    )
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
        "equivalence": equivalence,
        "verification": verification,
        "transient": transient,
        "older": older,
    }


def _handoff(case: dict[str, Any], *, retain_equivalence: bool = True) -> dict[str, Any]:
    return lifecycle.handoff_results(
        case["descriptor"],
        case["catalog"],
        case["metadata"],
        managed_parent=MANAGED_PARENT,
        verification=case["verification"],
        report=case["report"],
        audit_files={"audits/price-reader-equivalence.json": case["equivalence"]} if retain_equivalence else None,
    )


def _final(case: dict[str, Any], proof: dict[str, Any]) -> Path:
    entry = proof["entry"]
    return case["roots"].artifact_path(entry["manifest"]["scope"], entry["manifest"]["path"]).parent


def _hashes(directory: Path) -> dict[str, str]:
    return {path.relative_to(directory).as_posix(): file_digest(path) for path in directory.rglob("*") if path.is_file()}


def _external_equivalence(case: dict[str, Any], *, packet: dict[str, Any] | None = None) -> Path:
    """Invent a new audit outside the run after phase-one cleanup."""
    path = case["run"].parent / "independent-price-reader-equivalence.json"
    write_json(
        path,
        packet
        if packet is not None
        else {
            "schema": "pattern-scan-price-reader-equivalence.v3",
            "complete": True,
            "reference_source_id": case["source"]["source_id"],
            "reference_input_id": "synthetic-input",
            "calendar_n": 4110,
            "security_n": 1943,
            "cutoff": "2026-10-12",
            "all_columns_equal": True,
            "calendar_equal": True,
            "quality_equal": True,
            "mismatch_n": 0,
            "generation": "synthetic-shared-generation",
        },
    )
    return path


def _phase_one(case: dict[str, Any]) -> dict[str, Any]:
    before = _hashes(case["run"] / "prepared")
    receipt = lifecycle.cleanup_run(case["run"], case["catalog"])
    assert receipt["phase"] == "non_price_scratch" and receipt["prices_retained"] is True
    assert receipt["prepared_inventory"]
    assert receipt["prepared_inventory_sha256"] == object_digest(receipt["prepared_inventory"])
    assert receipt["publication_handoff_sha256"] == file_digest(case["run"] / "publication-handoff.json")
    assert receipt["reference_source_id"] == case["source"]["source_id"] and receipt["reference_input_id"] == "synthetic-input"
    for name, descriptor in receipt["prepared_inventory"].items():
        path = case["run"] / name
        assert path.is_relative_to(case["run"] / "prepared")
        info = path.stat()
        assert descriptor == {"bytes": info.st_size, "sha256": file_digest(path), "device": info.st_dev, "inode": info.st_ino, "mtime_ns": info.st_mtime_ns}
    assert _hashes(case["run"] / "prepared") == before
    assert not (case["run"] / "parts").exists()
    assert not (case["run"] / "global").exists()
    assert not (case["run"] / "analysis").exists()
    assert not (case["run"] / "audits").exists()
    return receipt


@pytest.mark.parametrize("kind", ("snapshot", "run_receipt", "manifest"))
def test_same_handoff_retries_after_actual_partial_metadata_write(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    needles = {
        "snapshot": b'"historical":true',
        "run_receipt": b'"schema":"pattern-scan-result-receipt.v3"',
        "manifest": b'"schema":"research-data-bundle.v1"',
    }
    original_open = Path.open
    interrupted: list[Path] = []
    prior = _hashes(case["older"])
    payload = case["files"]["aggregates/aggregate.parquet"]
    identity = payload.stat()

    class PartialWriter:
        def __init__(self, path: Path, stream: Any) -> None:
            self.path, self.stream = path, stream

        def __enter__(self) -> Any:
            self.stream.__enter__()
            return self

        def __exit__(self, *args: Any) -> Any:
            return self.stream.__exit__(*args)

        def write(self, data: bytes) -> int:
            if not interrupted and needles[kind] in data:
                self.stream.write(data[: len(data) // 2])
                self.stream.flush()
                os.fsync(self.stream.fileno())
                interrupted.append(self.path)
                raise OSError("invented process interruption during metadata write")
            return self.stream.write(data)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.stream, name)

    def opened(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        stream = original_open(path, mode, *args, **kwargs)
        return PartialWriter(path, stream) if mode == "xb" and path.suffix == ".metadata" else stream

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(OSError, match="interruption during metadata write"):
        _handoff(case)
    assert len(interrupted) == 1 and interrupted[0].read_bytes()
    plan = read_json(case["run"] / "handoff-plan.json")
    stage = Path(plan["stage"])
    assert interrupted[0].parent == Path(plan["metadata_scratch"])
    assert not interrupted[0].is_relative_to(stage)
    assert not (stage / {"snapshot": "execution/resource-profile.json", "run_receipt": "run-receipt.json", "manifest": "manifest.json"}[kind]).exists()
    assert _hashes(case["older"]) == prior
    proof = _handoff(case)
    final = _final(case, proof)
    after = (final / "aggregates/aggregate.parquet").stat()
    assert (identity.st_dev, identity.st_ino) == (after.st_dev, after.st_ino)
    published = _hashes(final)
    verify_entry(proof["entry"], case["roots"])
    _handoff(case)
    assert _hashes(final) == published and _hashes(case["older"]) == prior
    assert not any(path.suffix == ".metadata" for path in final.rglob("*"))
    assert interrupted[0].is_file()
    lifecycle.cleanup_run(case["run"], case["catalog"])
    assert not interrupted[0].exists() and _hashes(final) == published
    assert case["transient"].is_file()


@pytest.mark.parametrize("identity", ("source_id", "input_id"))
def test_publication_metadata_cannot_relabel_computed_results(case: dict[str, Any], identity: str) -> None:
    case["metadata"]["inputs"][identity] = "different"
    before = _hashes(case["run"])
    with pytest.raises(ValueError, match="metadata source/input"):
        _handoff(case)
    assert _hashes(case["run"]) == before


@pytest.mark.parametrize(
    "issue",
    (
        "missing",
        "wrong_source",
        "wrong_input",
        "latest_only",
        "different_column",
        "different_calendar",
        "different_quality",
        "different_calendar_n",
        "different_security_n",
        "mismatch",
        "no_generation",
    ),
)
def test_prepared_prices_wait_for_verified_shared_reader_transition(case: dict[str, Any], issue: str) -> None:
    packet = read_json(case["equivalence"])
    if issue == "wrong_source":
        packet["reference_source_id"] = "different-source"
    elif issue == "wrong_input":
        packet["reference_input_id"] = "different-input"
    elif issue == "latest_only":
        packet["cutoff"] = "2026-10-15"
    elif issue == "different_column":
        packet["all_columns_equal"] = False
    elif issue == "different_calendar":
        packet["calendar_equal"] = False
    elif issue == "different_quality":
        packet["quality_equal"] = False
    elif issue == "different_calendar_n":
        packet["calendar_n"] = 4111
    elif issue == "different_security_n":
        packet["security_n"] = 1942
    elif issue == "mismatch":
        packet["mismatch_n"] = 1
    elif issue == "no_generation":
        packet["generation"] = ""
    if issue != "missing":
        case["equivalence"].unlink()
        write_json(case["equivalence"], packet)
    _handoff(case, retain_equivalence=issue != "missing")
    _phase_one(case)
    before = _hashes(case["run"])
    with pytest.raises(ValueError, match="equivalence"):
        lifecycle.retire_prepared_prices(case["run"], case["catalog"])
    assert _hashes(case["run"]) == before
    assert case["transient"].exists()


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


def test_single_copy_handoff_and_two_phase_physical_cleanup(case: dict[str, Any]) -> None:
    owned = {name: path.stat() for name, path in case["files"].items() if path.is_relative_to(case["run"])}
    owned["report.md"] = case["report"].stat()
    older_before = _hashes(case["older"])
    proof = _handoff(case)
    final = _final(case, proof)
    body = verify_entry(proof["entry"], case["roots"])
    names = {row["path"] for row in body["artifacts"]}
    assert names == {*case["files"], "report.md", "audits/delivery-verification.json", "audits/price-reader-equivalence.json", "run-receipt.json"}
    for name, before in owned.items():
        after = (final / name).stat()
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
        assert after.st_nlink == 1
    assert not case["report"].exists()
    assert all(not path.exists() for path in case["files"].values() if path.is_relative_to(case["run"]))
    assert not (case["roots"].primary / "research_cache").exists()
    retained_before = _hashes(final)
    cleanup = _phase_one(case)
    assert cleanup["complete"] is True and cleanup["recovery_period_days"] == 0
    assert cleanup["removed_files"] > 0 and cleanup["removed_bytes"] > 0
    assert {path.name for path in case["run"].iterdir()} == {"publication-handoff.json", "cleanup-receipt.json", "prepared"}
    equality_path = final / "audits/price-reader-equivalence.json"
    before_transition = _hashes(case["run"])
    transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=equality_path)
    assert Path(transition["path"]).is_file() and file_digest(Path(transition["path"])) == transition["sha256"]
    assert all(file_digest(case["run"] / name) == digest for name, digest in before_transition.items())
    retirement = lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    assert retirement["complete"] is True
    assert not case["transient"].exists() and not (case["run"] / "prepared").exists()
    assert Path(transition["path"]).is_file()
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


def test_late_external_equivalence_two_phase_e2e_and_immutable_retries(case: dict[str, Any]) -> None:
    proof = _handoff(case, retain_equivalence=False)
    final = _final(case, proof)
    retained = _hashes(final)
    assert not (final / "audits/price-reader-equivalence.json").exists()
    price_hash = file_digest(case["transient"])
    cleanup = _phase_one(case)
    phase_one_files = _hashes(case["run"])
    assert lifecycle.cleanup_run(case["run"], case["catalog"]) == cleanup
    assert _hashes(case["run"]) == phase_one_files and _hashes(final) == retained
    equivalence = _external_equivalence(case)
    external_bytes = equivalence.read_bytes()
    transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=equivalence)
    transition_path = Path(transition["path"])
    assert transition_path == case["run"] / "price-reader-transition.json"
    assert transition["sha256"] == file_digest(transition_path)
    packet = read_json(transition_path)
    assert packet["schema"] == "pattern-scan-price-reader-transition.v3" and packet["complete"] is True
    assert packet["published_entry"] == proof["entry"] and packet["run_root"] == str(case["run"])
    assert packet["publication_handoff_sha256"] == file_digest(case["run"] / "publication-handoff.json")
    assert packet["cleanup_receipt_sha256"] == file_digest(case["run"] / "cleanup-receipt.json")
    assert packet["prepared_inventory_sha256"] == cleanup["prepared_inventory_sha256"]
    assert packet["reference_source_id"] == case["source"]["source_id"] and packet["reference_input_id"] == "synthetic-input"
    assert packet["equivalence"]["path"] == str(equivalence)
    assert packet["equivalence"]["bytes"] == len(external_bytes)
    assert packet["equivalence"]["sha256"] == file_digest(equivalence)
    assert packet["equivalence"]["contents"].encode("utf-8") == external_bytes
    assert isinstance(packet["owned_metadata"], dict)
    assert file_digest(case["transient"]) == price_hash
    assert equivalence.read_bytes() == external_bytes and _hashes(final) == retained
    assert all(file_digest(case["run"] / name) == digest for name, digest in phase_one_files.items())
    recorded_files = _hashes(case["run"])
    assert lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=equivalence) == transition
    assert _hashes(case["run"]) == recorded_files
    retirement = lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    assert retirement["schema"] == "pattern-scan-price-retirement.v3" and retirement["complete"] is True
    assert retirement["published_entry"] == proof["entry"] and retirement["transition"] == transition
    assert retirement["reference_source_id"] == case["source"]["source_id"] and retirement["reference_input_id"] == "synthetic-input"
    assert retirement["prepared_inventory_sha256"] == cleanup["prepared_inventory_sha256"]
    assert retirement["removed_files"] >= 1 and retirement["removed_bytes"] > 0
    assert not (case["run"] / "prepared").exists()
    assert (case["run"] / "price-retirement-receipt.json").is_file() and transition_path.is_file()
    assert equivalence.read_bytes() == external_bytes
    finished = _hashes(case["run"])
    assert lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition) == retirement
    assert lifecycle.cleanup_run(case["run"], case["catalog"]) == cleanup
    assert _hashes(case["run"]) == finished and _hashes(final) == retained
    verify_entry(proof["entry"], case["roots"])


@pytest.mark.parametrize(
    "field",
    (
        "published_entry",
        "reference_source_id",
        "reference_input_id",
        "prepared_inventory_sha256",
        "publication_handoff_sha256",
        "cleanup_receipt_sha256",
        "equivalence_hash",
        "descriptor_hash",
    ),
)
def test_transition_binding_tamper_rejected_without_any_price_deletion(case: dict[str, Any], field: str) -> None:
    proof = _handoff(case, retain_equivalence=False)
    final = _final(case, proof)
    retained = _hashes(final)
    _phase_one(case)
    transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=_external_equivalence(case))
    path = Path(transition["path"])
    packet = read_json(path)
    if field == "descriptor_hash":
        transition = {**transition, "sha256": "0" * 64}
    else:
        if field == "published_entry":
            packet[field] = {**packet[field], "version_id": "wrong-version"}
        elif field == "equivalence_hash":
            packet["equivalence"]["sha256"] = "0" * 64
        else:
            packet[field] = "different"
        # A valid descriptor hash cannot authorize a forged publication binding.
        path.write_bytes(canonical(packet))
        transition = {**transition, "sha256": file_digest(path)}
    before = _hashes(case["run"])
    with pytest.raises(ValueError):
        lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    assert _hashes(case["run"]) == before and case["transient"].is_file()
    assert _hashes(final) == retained


@pytest.mark.parametrize(
    "damage", ("unknown", "unknown_prepared", "modified_price", "active", "hardlink", "transition_hardlink", "symlink", "formal_corruption")
)
def test_phase_two_safety_checks_precede_all_deletions(case: dict[str, Any], tmp_path: Path, damage: str) -> None:
    proof = _handoff(case, retain_equivalence=False)
    final = _final(case, proof)
    _phase_one(case)
    transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=_external_equivalence(case))
    if damage == "unknown":
        (case["run"] / "unowned.txt").write_bytes(b"must survive phase two")
    elif damage == "unknown_prepared":
        (case["run"] / "prepared/unowned.parquet").write_bytes(b"not registered prices")
    elif damage == "modified_price":
        case["transient"].write_bytes(b"modified registered synthetic price")
    elif damage == "active":
        write_json(case["run"] / lifecycle.ACTIVE, {"pid": 123})
    elif damage == "hardlink":
        os.link(case["transient"], tmp_path / "price-alias.parquet")
    elif damage == "transition_hardlink":
        os.link(Path(transition["path"]), tmp_path / "transition-alias.json")
    elif damage == "symlink":
        try:
            (case["run"] / "linked-directory").symlink_to(case["older"], target_is_directory=True)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                pytest.skip("Windows session lacks symbolic-link privilege")
            raise
    else:
        (final / "aggregates/aggregate.parquet").write_bytes(b"corrupt formal result")
    before, formal_before = _hashes(case["run"]), _hashes(final)
    with pytest.raises(ValueError):
        lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    assert _hashes(case["run"]) == before and case["transient"].is_file()
    assert _hashes(final) == formal_before


@pytest.mark.parametrize("problem", ("wrong_source", "wrong_input", "bad_quality", "active", "inside_run"))
def test_record_transition_rejects_invalid_or_unowned_evidence_without_mutation(case: dict[str, Any], problem: str) -> None:
    _handoff(case, retain_equivalence=False)
    _phase_one(case)
    path = _external_equivalence(case)
    packet = read_json(path)
    if problem == "wrong_source":
        packet["reference_source_id"] = "different"
    elif problem == "wrong_input":
        packet["reference_input_id"] = "different"
    elif problem == "bad_quality":
        packet["quality_equal"] = False
    elif problem == "active":
        write_json(case["run"] / lifecycle.ACTIVE, {"pid": 123})
    else:
        path = case["run"] / "late-unregistered-equivalence.json"
    path.write_bytes(canonical(packet))
    before, evidence_before = _hashes(case["run"]), file_digest(path)
    with pytest.raises(ValueError):
        lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=path)
    assert _hashes(case["run"]) == before and file_digest(path) == evidence_before
    assert case["transient"].is_file()


def test_retirement_retries_after_actual_interrupted_price_unlink(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    proof = _handoff(case, retain_equivalence=False)
    final = _final(case, proof)
    retained = _hashes(final)
    _phase_one(case)
    transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=_external_equivalence(case))
    original_unlink = Path.unlink
    deleted: list[Path] = []

    def interrupted(path: Path, *args: Any, **kwargs: Any) -> None:
        original_unlink(path, *args, **kwargs)
        if path == case["transient"] and not deleted:
            deleted.append(path)
            raise OSError("synthetic interruption after registered price unlink")

    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(OSError, match="after registered price unlink"):
        lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    assert deleted == [case["transient"]] and not case["transient"].exists()
    assert _hashes(final) == retained
    monkeypatch.setattr(Path, "unlink", original_unlink)
    receipt = lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    assert receipt["complete"] is True and not (case["run"] / "prepared").exists()
    finished = _hashes(case["run"])
    assert lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition) == receipt
    assert _hashes(case["run"]) == finished and _hashes(final) == retained


@pytest.mark.parametrize(
    ("target_name", "schema"),
    [
        ("cleanup-plan.json", "pattern-scan-cleanup-plan.v3"),
        ("cleanup-receipt.json", "pattern-scan-cleanup.v3"),
        ("price-reader-transition.json", "pattern-scan-price-reader-transition.v3"),
        ("price-retirement-plan.json", "pattern-scan-price-retirement-plan.v3"),
        ("price-retirement-receipt.json", "pattern-scan-price-retirement.v3"),
    ],
)
def test_retirement_metadata_partial_write_stays_external_and_same_stage_retries(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
    schema: str,
) -> None:
    proof = _handoff(case, retain_equivalence=False)
    final = _final(case, proof)
    formal_before, older_before = _hashes(final), _hashes(case["older"])
    price_before = file_digest(case["transient"])
    transition = None
    equivalence = None
    if target_name.startswith("price-"):
        _phase_one(case)
        equivalence = _external_equivalence(case)
    if target_name.startswith("price-retirement-"):
        assert equivalence is not None
        transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=equivalence)

    def action() -> dict[str, Any]:
        if target_name.startswith("cleanup-"):
            return lifecycle.cleanup_run(case["run"], case["catalog"])
        if target_name == "price-reader-transition.json":
            assert equivalence is not None
            return lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=equivalence)
        return lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)

    needle = canonical({"schema": schema})[1:-1]
    original_open = Path.open
    interrupted: list[Path] = []
    attempts: list[Path] = []

    class PartialWriter:
        def __init__(self, path: Path, stream: Any) -> None:
            self.path, self.stream = path, stream

        def __enter__(self) -> Any:
            self.stream.__enter__()
            return self

        def __exit__(self, *args: Any) -> Any:
            return self.stream.__exit__(*args)

        def write(self, data: bytes) -> int:
            if needle in data:
                attempts.append(self.path)
                if not interrupted:
                    self.stream.write(data[: len(data) // 2])
                    self.stream.flush()
                    os.fsync(self.stream.fileno())
                    interrupted.append(self.path)
                    raise OSError("synthetic interruption after actual partial retirement metadata write")
            return self.stream.write(data)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.stream, name)

    def opened(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        stream = original_open(path, mode, *args, **kwargs)
        return PartialWriter(path, stream) if mode == "xb" and path.suffix == ".metadata" else stream

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(OSError, match="actual partial retirement metadata write"):
        action()
    assert len(interrupted) == 1 and interrupted[0].read_bytes()
    partial = interrupted[0]
    assert partial.parent.parent == case["run"].parent
    assert partial.parent.name.startswith(".retirement-metadata-")
    assert not partial.is_relative_to(case["run"]) and not partial.is_relative_to(final)
    assert not (case["run"] / target_name).exists()
    diagnostic = (file_digest(partial), partial.stat().st_mtime_ns)
    assert _hashes(final) == formal_before and _hashes(case["older"]) == older_before
    if target_name != "price-retirement-receipt.json":
        assert file_digest(case["transient"]) == price_before
    else:
        # Phase two already unlinked the authorized prices before writing its
        # completion receipt; its immutable plan is the authority for retry.
        assert not case["transient"].exists()
        assert (case["run"] / "price-retirement-plan.json").is_file()
    result = action()
    assert (case["run"] / target_name).is_file() or target_name.endswith("-plan.json")
    assert len(attempts) == 2 and attempts[0] == partial
    assert attempts[1] != partial and attempts[1].parent != partial.parent
    assert (file_digest(partial), partial.stat().st_mtime_ns) == diagnostic
    assert _hashes(final) == formal_before and _hashes(case["older"]) == older_before
    if target_name.startswith("cleanup-"):
        assert result["phase"] == "non_price_scratch" and result["prices_retained"] is True
        assert file_digest(case["transient"]) == price_before
    elif target_name == "price-reader-transition.json":
        assert result["sha256"] == file_digest(Path(result["path"]))
        assert file_digest(case["transient"]) == price_before
    else:
        assert result["complete"] is True and not (case["run"] / "prepared").exists()
    after = _hashes(case["run"])
    assert action() == result
    assert _hashes(case["run"]) == after and len(attempts) == 2
    assert _hashes(final) == formal_before and _hashes(case["older"]) == older_before
    assert (file_digest(partial), partial.stat().st_mtime_ns) == diagnostic
    assert not any(path.suffix == ".metadata" for path in case["run"].rglob("*"))


@pytest.mark.parametrize("point", ("scratch_unlinked_before_receipt", "receipt_published_before_plan_unlink"))
def test_phase_one_unlink_interruption_retries_without_losing_prices_or_rewriting_receipt(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    proof = _handoff(case, retain_equivalence=False)
    final = _final(case, proof)
    formal_before = _hashes(final)
    price_before = file_digest(case["transient"])
    target = case["run"] / ("parts/stock/events.bin" if point == "scratch_unlinked_before_receipt" else "cleanup-plan.json")
    original_unlink = Path.unlink
    interrupted: list[Path] = []
    receipt_before: list[tuple[str, int]] = []

    def unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == target and not interrupted:
            interrupted.append(path)
            if point == "scratch_unlinked_before_receipt":
                original_unlink(path, *args, **kwargs)
            else:
                receipt = case["run"] / "cleanup-receipt.json"
                assert receipt.is_file()
                receipt_before.append((file_digest(receipt), receipt.stat().st_mtime_ns))
            raise OSError("synthetic interruption at phase-one unlink boundary")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(OSError, match="phase-one unlink boundary"):
        lifecycle.cleanup_run(case["run"], case["catalog"])
    assert interrupted == [target]
    assert (case["run"] / "cleanup-plan.json").is_file()
    if point == "scratch_unlinked_before_receipt":
        assert not target.exists() and not (case["run"] / "cleanup-receipt.json").exists()
    assert file_digest(case["transient"]) == price_before and _hashes(final) == formal_before
    monkeypatch.setattr(Path, "unlink", original_unlink)
    receipt = _phase_one(case)
    assert not (case["run"] / "cleanup-plan.json").exists()
    if receipt_before:
        path = case["run"] / "cleanup-receipt.json"
        assert (file_digest(path), path.stat().st_mtime_ns) == receipt_before[0]
    after = _hashes(case["run"])
    assert lifecycle.cleanup_run(case["run"], case["catalog"]) == receipt
    assert _hashes(case["run"]) == after and _hashes(final) == formal_before


def _tree_identity(root: Path) -> dict[str, tuple[int, str | None]]:
    """Observe all synthetic files and directories, including their mtimes."""
    return {path.relative_to(root).as_posix(): (path.stat().st_mtime_ns, file_digest(path) if path.is_file() else None) for path in (root, *root.rglob("*"))}


def test_real_read_only_status_and_retirement_use_snapshot_after_external_evidence_disappears(case: dict[str, Any]) -> None:
    proof = _handoff(case, retain_equivalence=False)
    final = _final(case, proof)
    retained_before = _hashes(final)
    _phase_one(case)
    before = _tree_identity(case["roots"].primary)
    assert lifecycle.verify_retained_status(case["run"], case["catalog"]) == {"entry": proof["entry"], "prices_retained": True}
    assert _tree_identity(case["roots"].primary) == before
    external = _external_equivalence(case)
    equality = read_json(external)
    # This name is provenance, not a live catalog-generation lookup. No such
    # generation or producer exists in this all-synthetic fixture.
    equality["generation"] = "synthetic-generation-no-longer-available"
    assert not {"published_entry", "prepared_inventory_sha256", "publication_handoff_sha256"}.intersection(equality)
    external.write_bytes(canonical(equality))
    transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=external)
    snapshot = read_json(Path(transition["path"]))["equivalence"]["contents"]
    assert read_json(external)["generation"] == equality["generation"]
    external.unlink()  # Only the generated pytest fixture evidence is removed.
    assert not external.exists()
    before = _tree_identity(case["roots"].primary)
    assert lifecycle.verify_retained_status(case["run"], case["catalog"]) == {"entry": proof["entry"], "prices_retained": True}
    assert _tree_identity(case["roots"].primary) == before
    retirement = lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    assert retirement["complete"] is True and not (case["run"] / "prepared").exists()
    assert read_json(Path(transition["path"]))["equivalence"]["contents"] == snapshot
    before = _tree_identity(case["roots"].primary)
    assert lifecycle.verify_retained_status(case["run"], case["catalog"]) == {"entry": proof["entry"], "prices_retained": False}
    assert _tree_identity(case["roots"].primary) == before
    assert _hashes(final) == retained_before


def test_real_read_only_status_preserves_historical_all_at_once_cleanup_receipt(case: dict[str, Any]) -> None:
    proof = _handoff(case)
    final = _final(case, proof)
    retained_before = _hashes(final)
    _phase_one(case)
    transition = lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=final / "audits/price-reader-equivalence.json")
    lifecycle.retire_prepared_prices(case["run"], case["catalog"], transition=transition)
    # Construct the old physical state exclusively from this pytest fixture.
    # No existing run or historical artifact outside it is edited or deleted.
    for name in ("price-reader-transition.json", "price-retirement-plan.json", "price-retirement-receipt.json"):
        path = case["run"] / name
        if path.exists():
            path.unlink()
    historical = {"schema": "pattern-scan-cleanup.v3", "complete": True, "run_root": str(case["run"]), "entry": proof["entry"]}
    (case["run"] / "cleanup-receipt.json").write_bytes(canonical(historical))
    before = _tree_identity(case["roots"].primary)
    assert lifecycle.verify_retained_status(case["run"], case["catalog"]) == {"entry": proof["entry"], "prices_retained": False}
    assert _tree_identity(case["roots"].primary) == before and _hashes(final) == retained_before


@pytest.mark.parametrize("field", ("published_entry", "prepared_inventory_sha256", "publication_handoff_sha256"))
def test_explicitly_contradictory_optional_equality_binding_rejected_without_mutation(case: dict[str, Any], field: str) -> None:
    proof = _handoff(case, retain_equivalence=False)
    _phase_one(case)
    external = _external_equivalence(case)
    packet = read_json(external)
    packet[field] = {**proof["entry"], "version_id": "contradictory-published-version"} if field == "published_entry" else "0" * 64
    external.write_bytes(canonical(packet))
    before = _tree_identity(case["roots"].primary)
    with pytest.raises(ValueError, match="equivalence|binding"):
        lifecycle.record_price_reader_transition(case["run"], case["catalog"], equivalence=external)
    assert _tree_identity(case["roots"].primary) == before
    assert case["transient"].is_file() and not (case["run"] / "price-reader-transition.json").exists()
