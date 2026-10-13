"""Synthetic completion revalidation and explicit bounded CLI authority."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from research_core import pattern_scan_run_v1 as run
from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, write_json
from research_core.research_data_paths import DataRoots
from scripts import pattern_scan


@pytest.fixture
def roots(tmp_path: Path) -> DataRoots:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    return DataRoots(primary, primary / "research_data")


def synthetic_entry(roots: DataRoots, name: str = "invented") -> tuple[dict[str, Any], Path]:
    unavailable = {"start": None, "end": None, "reason": "invented fixture"}
    metadata = {
        "data_id": name,
        "kind": "features",
        "definition_version": "invented.v1",
        "parameters": {"fixture": True},
        "inputs": {"raw": "invented-input"},
        "coverage": {"scope": "invented bytes", **{name: unavailable for name in ("raw_input_period", "valid_indicator_period", "complete_label_period")}},
        "status": "partial",
        "limitations": ["invented bytes only"],
        "backup": {"status": "not_verified"},
    }
    directory = roots.data / name
    directory.mkdir(parents=True)
    payload = directory / "payload.bin"
    payload.write_bytes(b"invented payload")
    manifest = {"schema": "research-data-bundle.v1", "complete": True, "metadata": metadata, "lineage": None, "artifacts": [describe_file(directory, payload)]}
    manifest_path = directory / "manifest.json"
    manifest_path.write_bytes(canonical(manifest))
    entry = {
        **metadata,
        "version_id": object_digest(manifest),
        "reader": "bundle",
        "manifest": {"scope": "data", "path": f"{name}/manifest.json", "sha256": file_digest(manifest_path)},
    }
    return entry, payload


@pytest.fixture
def completion(roots: DataRoots, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    raw = tmp_path / "invented-input.bin"
    raw.write_bytes(b"invented input")
    raw_digest = file_digest(raw)
    manifest = tmp_path / "invented-input-manifest.json"
    write_json(manifest, {"input_sha256": raw_digest})
    manifest_digest = file_digest(manifest)
    source_file = tmp_path / "invented-source.py"
    source_file.write_bytes(b"invented_definition = 1\n")
    source = {"source_id": "invented-source", "sha256": file_digest(source_file)}

    def verify_source(supplied: dict[str, Any]) -> None:
        if supplied != source or file_digest(source_file) != source["sha256"]:
            raise ValueError("invented source drift")

    def verify_raw() -> None:
        if file_digest(manifest) != manifest_digest or file_digest(raw) != raw_digest:
            raise ValueError("invented input drift")

    snapshot = SimpleNamespace(input_id="invented-input", verify_after=Mock(side_effect=verify_raw))

    def load_snapshot(supplied_roots: DataRoots, *, manifest_sha256: str) -> SimpleNamespace:
        assert supplied_roots == roots and manifest_sha256 == manifest_digest
        verify_raw()
        return snapshot

    part = tmp_path / "invented-stock-part.bin"
    part.write_bytes(b"invented part")
    part_digest = file_digest(part)
    barrier_file = tmp_path / "invented-global-part.bin"
    barrier_file.write_bytes(b"invented global")
    barrier = {"sha256": file_digest(barrier_file)}
    results = [{"code": "INVENTED", "sha256": part_digest}]

    def verify_parts(supplied: list[dict[str, Any]], **identity: Any) -> dict[str, Path]:
        assert supplied == results and identity == {"source": source, "input_id": "invented-input"}
        if file_digest(part) != part_digest:
            raise ValueError("invented stock part drift")
        return {"INVENTED": part.parent}

    def verify_barrier(supplied: dict[str, Any]) -> None:
        assert supplied == barrier
        if file_digest(barrier_file) != barrier["sha256"]:
            raise ValueError("invented barrier drift")

    entry, published = synthetic_entry(roots)
    source_spy, load_spy = Mock(side_effect=verify_source), Mock(side_effect=load_snapshot)
    part_spy, barrier_spy = Mock(side_effect=verify_parts), Mock(side_effect=verify_barrier)
    entry_spy = Mock(wraps=run.verify_entry)

    def validate_profile(profile: dict[str, Any], *, source: dict[str, Any], input_id: str) -> None:
        assert profile["source_id"] == source["source_id"] and profile["input_id"] == input_id
        for pool in profile["profiles"]:
            part_spy(pool["results"], source=source, input_id=input_id)

    profile_spy = Mock(side_effect=validate_profile)
    monkeypatch.setattr(run, "verify_source", source_spy)
    monkeypatch.setattr(run, "load_snapshot", load_spy)
    monkeypatch.setattr(run, "verified_parts", part_spy)
    monkeypatch.setattr(run, "verify_barrier", barrier_spy)
    monkeypatch.setattr(run, "verify_entry", entry_spy)
    monkeypatch.setattr(run, "validate_profile", profile_spy)
    request = {"source": source, "input_manifest_sha256": manifest_digest}
    saved = {
        "complete": True,
        "request_id": object_digest(request),
        "result": {"phase": "full_stock_shared_versions", "pool": {"results": results}, "barrier": barrier, "shared_versions": {"features": entry}},
    }
    return SimpleNamespace(
        roots=roots,
        request=request,
        saved=saved,
        raw=raw,
        snapshot=snapshot,
        source_file=source_file,
        published=published,
        part=part,
        barrier_file=barrier_file,
        source_spy=source_spy,
        load_spy=load_spy,
        part_spy=part_spy,
        barrier_spy=barrier_spy,
        entry_spy=entry_spy,
    )


@pytest.mark.parametrize("full_analysis", [False, True])
def test_completion_rechecks_raw_source_parts_barrier_and_every_published_pin(completion: SimpleNamespace, full_analysis: bool) -> None:
    if full_analysis:
        result = completion.saved["result"]
        result["phase"] = "complete_pattern_scan"
        result["analysis"] = {key: synthetic_entry(completion.roots, key)[0] for key in ("shared_event_outcomes", "shared_episodes", "shared_report_tables")}
    run.verify_completion(completion.saved, completion.request, completion.roots)
    assert completion.source_spy.call_count == 2
    completion.load_spy.assert_called_once_with(completion.roots, manifest_sha256=completion.request["input_manifest_sha256"])
    completion.snapshot.verify_after.assert_called_once_with()
    completion.part_spy.assert_called_once()
    completion.barrier_spy.assert_called_once()
    assert completion.entry_spy.call_count == (4 if full_analysis else 1)
    expected_entries = [*completion.saved["result"]["shared_versions"].values()]
    if full_analysis:
        expected_entries.extend(completion.saved["result"]["analysis"].values())
    assert [call.args for call in completion.entry_spy.call_args_list] == [(entry, completion.roots) for entry in expected_entries]


@pytest.mark.parametrize("when", ["before_load", "after_load"])
def test_completion_rejects_raw_input_drift(completion: SimpleNamespace, when: str) -> None:
    if when == "before_load":
        completion.raw.write_bytes(b"changed input")
    else:
        loader = completion.load_spy.side_effect

        def changed_after_load(*args: Any, **kwargs: Any) -> Any:
            snapshot = loader(*args, **kwargs)
            completion.raw.write_bytes(b"changed input")
            return snapshot

        completion.load_spy.side_effect = changed_after_load
    with pytest.raises(ValueError, match="invented input drift"):
        run.verify_completion(completion.saved, completion.request, completion.roots)
    if when == "after_load":
        completion.snapshot.verify_after.assert_called_once_with()
    completion.part_spy.assert_not_called()
    completion.entry_spy.assert_not_called()


@pytest.mark.parametrize("damaged", ["source_file", "part", "barrier_file", "published"])
def test_completion_rejects_current_source_parts_or_real_published_payload_drift(completion: SimpleNamespace, damaged: str) -> None:
    getattr(completion, damaged).write_bytes(b"changed bytes")
    with pytest.raises(ValueError):
        run.verify_completion(completion.saved, completion.request, completion.roots)
    if damaged == "published":
        completion.snapshot.verify_after.assert_called_once_with()
        completion.entry_spy.assert_called_once()


def test_cached_profile_file_must_match_receipt_and_verify_profile_parts(completion: SimpleNamespace, tmp_path: Path) -> None:
    profile = {
        "source_id": completion.request["source"]["source_id"],
        "input_id": "invented-input",
        "profiles": [{"results": completion.saved["result"]["pool"]["results"]}],
    }
    profile_path = tmp_path / "resource-profile.json"
    write_json(profile_path, profile)
    completion.saved["result"] = {"phase": "resource_profile", "profile_path": str(profile_path), "profile": profile}
    run.verify_completion(completion.saved, completion.request, completion.roots)
    completion.part_spy.assert_called_once()
    changed = {**profile, "input_id": "changed-input"}
    profile_path.write_bytes(canonical(changed))
    with pytest.raises(ValueError, match="completed profile identity differs"):
        run.verify_completion(completion.saved, completion.request, completion.roots)


@pytest.mark.parametrize("damage", ["request_id", "complete"])
def test_completion_rejects_wrong_or_incomplete_receipt(completion: SimpleNamespace, damage: str) -> None:
    completion.saved[damage] = "wrong" if damage == "request_id" else False
    with pytest.raises(ValueError, match="invalid existing coordinator completion"):
        run.verify_completion(completion.saved, completion.request, completion.roots)
    completion.load_spy.assert_not_called()


def cli_arguments(roots: DataRoots, mode: str = "profile") -> list[str]:
    return [
        "pattern_scan",
        mode,
        "--primary-root",
        str(roots.primary),
        "--data-root",
        str(roots.data),
        "--input-manifest-sha256",
        "a" * 64,
        "--run-id",
        "invented-run",
    ]


@pytest.mark.parametrize("mode,phase", [("profile", "resource_profile"), ("stock", "full_stock_shared_versions"), ("all", "complete_pattern_scan")])
def test_real_cli_routes_explicit_roots_authority_and_profile(
    roots: DataRoots, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str, phase: str
) -> None:
    profile = roots.primary / "profile.json"
    launch = Mock(return_value={"complete": True, "source_id": "invented-source", "result": {"phase": phase}})
    monkeypatch.setattr(pattern_scan, "launch", launch)
    monkeypatch.setattr(pattern_scan.sys, "argv", [*cli_arguments(roots, mode), "--profile", str(profile), "--calculation-authorized"])
    pattern_scan.main()
    launch.assert_called_once_with(roots, mode=mode, input_manifest_sha256="a" * 64, run_id="invented-run", profile_path=profile, calculation_authorized=True)
    assert json.loads(capsys.readouterr().out) == {"complete": True, "source_id": "invented-source", "phase": phase}


def test_cli_without_authority_reaches_real_launch_and_stops_before_source_or_job(roots: DataRoots, monkeypatch: pytest.MonkeyPatch) -> None:
    source = Mock(side_effect=AssertionError("source must not be read"))
    job = Mock(side_effect=AssertionError("job must not be created"))
    monkeypatch.setattr(run, "source_identity", source)
    monkeypatch.setattr(run, "_MemoryBoundJob", job)
    monkeypatch.setattr(pattern_scan, "launch", run.launch)
    monkeypatch.setattr(pattern_scan.sys, "argv", cli_arguments(roots))
    with pytest.raises(PermissionError, match="calculation authorization"):
        pattern_scan.main()
    source.assert_not_called()
    job.assert_not_called()
    assert not (roots.primary / ".tmp").exists()


@pytest.mark.parametrize(
    "invalid",
    [
        {"mode": "invalid"},
        {"run_id": "../escape"},
        {"run_id": "a/b"},
        {"run_id": "CON"},
        {"run_id": "nul.json"},
        {"run_id": "trailing "},
        {"run_id": ".. "},
        {"run_id": "C:/absolute"},
        {"memory_bytes": 0},
        {"memory_bytes": True},
        {"memory_bytes": 8 * 1024**3},
        {"job_memory_bytes": 9 * 1024**3},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
        {"timeout_seconds": float("nan")},
    ],
)
def test_launch_invalid_bounds_and_names_stop_before_source_files_or_jobs(roots: DataRoots, monkeypatch: pytest.MonkeyPatch, invalid: dict[str, Any]) -> None:
    source = Mock(side_effect=AssertionError("source must not be read"))
    job = Mock(side_effect=AssertionError("job must not be created"))
    monkeypatch.setattr(run, "source_identity", source)
    monkeypatch.setattr(run, "_MemoryBoundJob", job)
    monkeypatch.setattr(run, "host_resources", lambda: {"physical_available_bytes": 20 * 1024**3})
    args = {"mode": "profile", "input_manifest_sha256": "a" * 64, "run_id": "invented-run", "calculation_authorized": True, **invalid}
    with pytest.raises(ValueError):
        run.launch(roots, **args)
    source.assert_not_called()
    job.assert_not_called()
    assert not (roots.primary / ".tmp").exists()


@pytest.mark.parametrize("available", [None, 12 * 1024**3 - 1])
def test_launch_refuses_unprovable_host_reserve_without_source_or_jobs(roots: DataRoots, monkeypatch: pytest.MonkeyPatch, available: int | None) -> None:
    source, job = Mock(), Mock()
    monkeypatch.setattr(run, "host_resources", lambda: {"physical_available_bytes": available})
    monkeypatch.setattr(run, "source_identity", source)
    monkeypatch.setattr(run, "_MemoryBoundJob", job)
    with pytest.raises(ValueError, match="four GiB host reserve"):
        run.launch(roots, mode="profile", input_manifest_sha256="a" * 64, run_id="invented-run", calculation_authorized=True)
    source.assert_not_called()
    job.assert_not_called()


@pytest.mark.parametrize("relative", ["primary", "data"])
def test_cli_rejects_relative_roots_before_launch(roots: DataRoots, monkeypatch: pytest.MonkeyPatch, relative: str) -> None:
    argv = cli_arguments(roots)
    argv[argv.index("--primary-root" if relative == "primary" else "--data-root") + 1] = relative
    launch = Mock()
    monkeypatch.setattr(pattern_scan, "launch", launch)
    monkeypatch.setattr(pattern_scan.sys, "argv", argv)
    with pytest.raises(ValueError, match="explicit absolute"):
        pattern_scan.main()
    launch.assert_not_called()
