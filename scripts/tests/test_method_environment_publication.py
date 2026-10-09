"""Synthetic publication bytes, receipt binding and path boundary regressions."""

import gzip
import hashlib
import json
import lzma
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest

from research_core.jobs import digest
from scripts import publish_method_environment_interactions as publication

Source = tuple[Path, Path, dict[str, Any], Path, list[dict[str, Any]]]


def write(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=1) + "\n").encode()
    path.write_bytes(raw)
    return raw


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Source:
    root = tmp_path / "source"
    root.mkdir()
    task = getattr(request, "param", publication.TASK)
    inputs = {}
    for group, name in (("code", "scripts/example.py"), ("contracts", f"tasks/{task}/mission.md"), ("data", "datasets/synthetic/manifest.json")):
        inputs[group] = {name: sha(write(root / name, {"synthetic": group}))}
    packet: dict[str, Any] = {
        "schema_version": "research-job.v1",
        "task_id": task,
        "job_id": "test-job",
        "phase": "exploration",
        "window": {"start": "2019-01-02", "end": "2026-08-14"},
        "candidate_id": "test",
        "owner_contract_id": "test",
        "metric_contract_id": "test",
        "execution_contract_id": "test",
        "scenario_id": "test",
        "params": {},
        "runtime": {"synthetic": True},
        "timeout_seconds": 10,
        "inputs": inputs,
        "script": "scripts/example.py",
        "args": ["{output_dir}"],
        "outputs": sorted(publication.OUTPUTS),
        "summary": "summary.json",
    }
    packet_path = root / f"tasks/{task}/params/test-job.json"
    write(packet_path, packet)
    job = publication.job_directory(root, packet)
    summary = {
        "schema_version": "1.0",
        "generated_at": "synthetic",
        "run": {},
        "strategy": {},
        "data": {},
        "metrics": {},
        "portfolio": {},
        "trades": [],
        "warnings": [],
    }
    values = {
        "summary.json": summary,
        "results.json": {"comparisons": [{"precision": None}], "triage": {"qualified": False}},
        "input-audit.json": {"source_datasets": {"atlas": {"dataset_id": "synthetic", "path": "datasets/synthetic"}}},
    }
    hashes = {name: sha(write(job / name, value)) for name, value in values.items()}
    receipt: dict[str, Any] = {"schema_version": "research-receipt.v1", "status": "completed", "packet_sha256": digest(packet), "outputs": hashes}
    write(job / "receipt.json", receipt)
    calls: list[dict[str, Any]] = []

    def verify(root: Path, actual: dict[str, Any]) -> dict[str, Any]:
        calls.append(actual)
        for group in actual["inputs"].values():
            for name, expected in group.items():
                if sha((root / name).read_bytes()) != expected:
                    raise ValueError("input identity mismatch")
        saved = json.loads((job / "receipt.json").read_bytes())
        if saved != receipt or any(sha((job / name).read_bytes()) != expected for name, expected in receipt["outputs"].items()):
            raise ValueError("receipt mismatch")
        return saved

    monkeypatch.setattr(publication, "verify_reuse", verify)
    return root, packet_path, packet, job, calls


def publish(source: Source, name: str = "publication-v1") -> tuple[Path, dict[str, Any]]:
    root, packet_path, packet, _, _ = source
    destination = root / f"tasks/{packet['task_id']}/{name}"
    manifest = publication.publish(root, packet_path, digest(packet), destination)
    return destination, manifest


def resign(path: Path, manifest: dict[str, Any], name: str) -> None:
    manifest["files"][name] = sha((path / name).read_bytes())
    manifest["artifact_id"] = publication._identity(manifest)
    write(path / "manifest.json", manifest)


def test_exact_bytes_determinism_and_independent_reader(source: Source, tmp_path: Path) -> None:
    path, manifest = publish(source)
    root, packet_path, packet, job, calls = source
    assert len(calls) == 2
    for name in publication.OUTPUTS | {"receipt.json"}:
        assert gzip.decompress((path / (name + ".gz")).read_bytes()) == (job / name).read_bytes()
        assert (path / (name + ".gz")).read_bytes() == gzip.compress((job / name).read_bytes(), mtime=0)
    assert gzip.decompress((path / "packet.json.gz").read_bytes()) == packet_path.read_bytes()
    assert (path / "packet.json.gz").read_bytes() == gzip.compress(packet_path.read_bytes(), mtime=0)
    assert manifest["schema_version"] == publication.SCHEMA
    assert manifest["artifact_id"] == publication.SCHEMA + "-" + digest({key: value for key, value in manifest.items() if key != "artifact_id"})
    with zipfile.ZipFile(path / "source-inputs.zip") as bundle:
        for name in {**packet["inputs"]["code"], **packet["inputs"]["contracts"]}:
            assert bundle.read(name) == (root / name).read_bytes()
    assert publish(source, "second")[1]["artifact_id"] == manifest["artifact_id"]
    copied = tmp_path / "portable"
    shutil.copytree(path, copied)
    shutil.rmtree(root)
    data = publication.read_publication(copied)
    assert data["results"]["comparisons"] == [{"precision": None}]
    assert data["manifest"]["bulk_limitation"] == publication.LIMITATION


@pytest.mark.parametrize("source", [publication.INDUSTRY_TASK], indirect=True)
def test_industry_exact_bytes_and_independent_reader(source: Source, tmp_path: Path) -> None:
    path, manifest = publish(source)
    root, packet_path, packet, job, calls = source
    assert len(calls) == 2
    assert manifest["schema_version"] == publication.INDUSTRY_SCHEMA
    assert manifest["artifact_id"].startswith(publication.INDUSTRY_SCHEMA + "-")
    assert {item.name for item in path.iterdir()} == publication.INDUSTRY_FILES | {"manifest.json"}
    for name in publication.OUTPUTS | {"receipt.json"}:
        assert lzma.decompress((path / (name + ".xz")).read_bytes(), format=lzma.FORMAT_XZ) == (job / name).read_bytes()
    assert lzma.decompress((path / "packet.json.xz").read_bytes(), format=lzma.FORMAT_XZ) == packet_path.read_bytes()
    with zipfile.ZipFile(path / "source-inputs.zip") as bundle:
        for name in {**packet["inputs"]["code"], **packet["inputs"]["contracts"]}:
            assert bundle.read(name) == (root / name).read_bytes()
    assert publish(source, "second")[1]["artifact_id"] == manifest["artifact_id"]
    copied = tmp_path / "portable"
    shutil.copytree(path, copied)
    shutil.rmtree(root)
    data = publication.read_publication(copied)
    assert data["packet"]["task_id"] == publication.INDUSTRY_TASK
    assert data["results"]["comparisons"] == [{"precision": None}]


@pytest.mark.parametrize("source", [publication.TASK, publication.INDUSTRY_TASK], indirect=True)
def test_other_approved_task_cannot_use_schema(source: Source) -> None:
    path, manifest = publish(source)
    packet = source[2].copy()
    packet["task_id"] = publication.INDUSTRY_TASK if packet["task_id"] == publication.TASK else publication.TASK
    suffix = ".gz" if manifest["schema_version"] == publication.SCHEMA else ".xz"
    raw = json.dumps(packet).encode()
    (path / ("packet.json" + suffix)).write_bytes(gzip.compress(raw, mtime=0) if suffix == ".gz" else lzma.compress(raw))
    manifest["packet_sha256"] = digest(packet)
    resign(path, manifest, "packet.json" + suffix)
    with pytest.raises(ValueError, match="task and schema mismatch"):
        publication.read_publication(path)


@pytest.mark.parametrize("source", [publication.TASK, publication.INDUSTRY_TASK], indirect=True)
def test_wrong_profile_file_set_rejected(source: Source) -> None:
    path, manifest = publish(source)
    manifest["schema_version"] = publication.INDUSTRY_SCHEMA if manifest["schema_version"] == publication.SCHEMA else publication.SCHEMA
    manifest["artifact_id"] = publication._identity(manifest)
    write(path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="exact file set"):
        publication.read_publication(path)
    with pytest.raises(ValueError, match="required file set mismatch"):
        publication._read_payload(path, manifest)


@pytest.mark.parametrize("source", [publication.TASK, publication.INDUSTRY_TASK], indirect=True)
def test_wrong_extension_rejected(source: Source) -> None:
    path, manifest = publish(source)
    suffix = ".gz" if manifest["schema_version"] == publication.SCHEMA else ".xz"
    (path / ("results.json" + suffix)).rename(path / "results.json.zip")
    with pytest.raises(ValueError, match="exact file set"):
        publication.read_publication(path)


def test_unknown_task_rejected_before_writes(source: Source) -> None:
    root, packet_path, packet, _, calls = source
    packet["task_id"] = "arbitrary-task"
    write(packet_path, packet)
    with pytest.raises(ValueError, match="approved task"):
        publication.publish(root, packet_path, digest(packet), root / "fresh")
    assert calls == [] and not (root / "fresh").exists()


@pytest.mark.parametrize("source", [publication.INDUSTRY_TASK], indirect=True)
@pytest.mark.parametrize("name", sorted(publication.INDUSTRY_FILES))
def test_industry_corruption(source: Source, name: str) -> None:
    path, _ = publish(source)
    (path / name).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="stored file hash"):
        publication.read_publication(path)


@pytest.mark.parametrize("source", [publication.INDUSTRY_TASK], indirect=True)
def test_industry_resigned_output_cannot_override_receipt(source: Source) -> None:
    path, manifest = publish(source)
    (path / "results.json.xz").write_bytes(lzma.compress(b'{"comparisons":[],"triage":{}}'))
    resign(path, manifest, "results.json.xz")
    with pytest.raises(ValueError, match="receipt output binding"):
        publication.read_publication(path)


@pytest.mark.parametrize("source", [publication.TASK, publication.INDUSTRY_TASK], indirect=True)
def test_resigned_archive_cannot_override_input_hash(source: Source) -> None:
    path, manifest = publish(source)
    expected = {**source[2]["inputs"]["code"], **source[2]["inputs"]["contracts"]}
    with zipfile.ZipFile(path / "source-inputs.zip", "w") as bundle:
        for name in expected:
            bundle.writestr(name, b"changed")
    resign(path, manifest, "source-inputs.zip")
    with pytest.raises(ValueError, match="archived input hash"):
        publication.read_publication(path)


def test_unknown_schema_rejected(source: Source) -> None:
    path, manifest = publish(source)
    manifest["schema_version"] = "arbitrary-publication.v1"
    write(path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="schema or required file set"):
        publication.read_publication(path)


@pytest.mark.parametrize("source", [publication.INDUSTRY_TASK], indirect=True)
def test_transport_preserves_bytes_and_offline_outputs(source: Source, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, original_manifest = publish(source)
    original = publication.read_publication(path)
    saved = {item.name: item.read_bytes() for item in path.iterdir()}
    monkeypatch.setattr(publication, "PART_BYTES", 40)
    monkeypatch.setattr(publication, "verify_reuse", lambda *_: pytest.fail("transport must not verify live research inputs"))
    destination = path.parent / "transport"
    manifest = publication.repack_industry(path, destination)
    assert manifest["schema_version"] == publication.TRANSPORT_SCHEMA
    assert manifest["source_artifact_id"] == original_manifest["artifact_id"]
    assert len(manifest["result_parts"]) > 1
    assert b"".join((destination / name).read_bytes() for name in manifest["result_parts"]) == saved["results.json.xz"]
    for name in publication.TRANSPORT_COPIES:
        assert (destination / name).read_bytes() == saved[name]
    assert (destination / "source-manifest.json").read_bytes() == saved["manifest.json"]
    assert {item.name: item.read_bytes() for item in path.iterdir()} == saved
    portable = tmp_path / "portable-transport"
    shutil.copytree(destination, portable)
    shutil.rmtree(source[0])
    monkeypatch.setattr(publication, "PART_BYTES", publication.MAX_PART_BYTES)
    data = publication.read_publication(portable)
    assert data["manifest"] == manifest
    assert data["source_manifest"] == original_manifest
    for name in ("packet", "receipt", "summary", "results", "input-audit"):
        assert data[name] == original[name]


@pytest.mark.parametrize("source", [publication.INDUSTRY_TASK], indirect=True)
@pytest.mark.parametrize("damage", ["hash", "missing", "source_id", "parts", "schema", "source_schema", "reconstructed", "size", "extra"])
def test_transport_tamper_rejected(source: Source, monkeypatch: pytest.MonkeyPatch, damage: str) -> None:
    path, _ = publish(source)
    monkeypatch.setattr(publication, "PART_BYTES", 40)
    destination = path.parent / "transport"
    manifest = publication.repack_industry(path, destination)
    part = manifest["result_parts"][0]
    expected = "stored file hash"
    if damage == "hash":
        (destination / part).write_bytes(b"changed")
    elif damage == "missing":
        (destination / part).unlink()
        expected = "exact file set"
    elif damage == "source_id":
        manifest["source_artifact_id"] = "wrong"
        resign(destination, manifest, part)
        expected = "source identity or schema"
    elif damage == "parts":
        manifest["result_parts"].reverse()
        resign(destination, manifest, part)
        expected = "result parts"
    elif damage == "schema":
        manifest["schema_version"] = "industry-role-transport.v3"
        write(destination / "manifest.json", manifest)
        expected = "schema or required file set"
    elif damage == "source_schema":
        original = json.loads((destination / "source-manifest.json").read_bytes())
        original["schema_version"] = publication.SCHEMA
        write(destination / "source-manifest.json", original)
        resign(destination, manifest, "source-manifest.json")
        expected = "source identity or schema"
    elif damage == "reconstructed":
        (destination / part).write_bytes(b"x" * 40)
        resign(destination, manifest, part)
    elif damage == "size":
        (destination / part).write_bytes(b"x" * (publication.MAX_PART_BYTES + 1))
        resign(destination, manifest, part)
        expected = "part size"
    else:
        (destination / "extra.json").write_bytes(b"{}")
        expected = "exact file set"
    with pytest.raises(ValueError, match=expected):
        publication.read_publication(destination)


@pytest.mark.parametrize("source", [publication.INDUSTRY_TASK], indirect=True)
def test_transport_no_overwrite_or_overlap(source: Source) -> None:
    path, _ = publish(source)
    destination = path.parent / "transport"
    publication.repack_industry(path, destination)
    saved = {item.name: item.read_bytes() for item in destination.iterdir()}
    with pytest.raises(ValueError, match="no overwrite"):
        publication.repack_industry(path, destination)
    assert {item.name: item.read_bytes() for item in destination.iterdir()} == saved
    for overlapping in (path, path / "nested", path.parent):
        with pytest.raises(ValueError, match="overlap"):
            publication.repack_industry(path, overlapping)


def test_transport_rejects_method_publication(source: Source) -> None:
    path, _ = publish(source)
    destination = path.parent / "transport"
    with pytest.raises(ValueError, match="requires industry publication v1"):
        publication.repack_industry(path, destination)
    assert not destination.exists()


@pytest.mark.parametrize("source", [publication.INDUSTRY_TASK], indirect=True)
def test_transport_rechecks_source_bytes(source: Source, monkeypatch: pytest.MonkeyPatch) -> None:
    path, _ = publish(source)
    original = publication.read_publication
    reads = 0

    def mutate(candidate: Path) -> dict[str, Any]:
        nonlocal reads
        data = original(candidate)
        reads += 1
        if reads == 2:
            manifest_path = path / "manifest.json"
            manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
        return data

    monkeypatch.setattr(publication, "read_publication", mutate)
    destination = path.parent / "partial-transport"
    with pytest.raises(ValueError, match="source changed during transport"):
        publication.repack_industry(path, destination)
    assert destination.is_dir() and not (destination / "manifest.json").exists()


@pytest.mark.parametrize("name", sorted(publication.FILES))
def test_corruption(source: Source, name: str) -> None:
    path, _ = publish(source)
    (path / name).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="stored file hash"):
        publication.read_publication(path)


def test_resigned_output_cannot_override_receipt(source: Source) -> None:
    path, manifest = publish(source)
    (path / "results.json.gz").write_bytes(gzip.compress(b'{"comparisons":[],"triage":{}}', mtime=0))
    resign(path, manifest, "results.json.gz")
    with pytest.raises(ValueError, match="receipt output binding"):
        publication.read_publication(path)


def test_resigned_packet_still_bound_to_receipt(source: Source) -> None:
    path, manifest = publish(source)
    packet = source[2].copy()
    packet["params"] = {"changed": True}
    (path / "packet.json.gz").write_bytes(gzip.compress(json.dumps(packet).encode(), mtime=0))
    manifest["packet_sha256"] = digest(packet)
    resign(path, manifest, "packet.json.gz")
    with pytest.raises(ValueError, match="packet digest"):
        publication.read_publication(path)


def test_approval_and_verification_before_writes(source: Source, monkeypatch: pytest.MonkeyPatch) -> None:
    root, packet_path, packet, _, calls = source
    destination = root / "fresh"
    with pytest.raises(ValueError, match="approved digest"):
        publication.publish(root, packet_path, "0" * 64, destination)
    assert not destination.exists() and calls == []
    monkeypatch.setattr(publication, "verify_reuse", lambda *_: (_ for _ in ()).throw(ValueError("reuse failed")))
    with pytest.raises(ValueError, match="reuse failed"):
        publication.publish(root, packet_path, digest(packet), destination)
    assert not destination.exists()


@pytest.mark.parametrize(
    "relative", ["datasets/synthetic/new", "tasks/20261005-method-environment-interactions/runs/registered/test-job/new", "../escape", "folder/../new"]
)
def test_nested_and_unsafe_destination_rejected(source: Source, relative: str) -> None:
    root, packet_path, packet, _, calls = source
    with pytest.raises(ValueError):
        publication.publish(root, packet_path, digest(packet), Path(relative))
    assert calls == []


def test_native_nested_destination_succeeds(source: Source) -> None:
    root, packet_path, packet, _, calls = source
    destination = Path("folder") / "new"
    manifest = publication.publish(root, packet_path, digest(packet), destination)
    assert len(calls) == 2
    assert publication.read_publication(root / destination)["manifest"]["artifact_id"] == manifest["artifact_id"]


def test_no_overwrite_and_extra_file_rejection(source: Source) -> None:
    path, _ = publish(source)
    before = (path / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="no overwrite"):
        publish(source)
    assert (path / "manifest.json").read_bytes() == before
    (path / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="exact file set"):
        publication.read_publication(path)


def test_source_changed_during_copy_keeps_partial(source: Source, monkeypatch: pytest.MonkeyPatch) -> None:
    root, packet_path, packet, job, _ = source
    original = publication.verify_reuse
    count = 0

    def mutate(root: Path, packet: dict[str, Any]) -> dict[str, Any]:
        nonlocal count
        count += 1
        if count == 2:
            (job / "results.json").write_bytes(b"changed")
        return original(root, packet)

    monkeypatch.setattr(publication, "verify_reuse", mutate)
    destination = root / "partial"
    with pytest.raises(ValueError, match="receipt mismatch"):
        publication.publish(root, packet_path, digest(packet), destination)
    assert destination.is_dir() and not (destination / "manifest.json").exists()
