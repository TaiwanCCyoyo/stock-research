"""Invented byte blocks exercise exact reuse and immutable recovery generations."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from research_core import feature_block_store_v1 as blocks
from research_core.artifact_store import canonical, object_digest, read_json
from research_core.feature_identity_v1 import identity_digest


@pytest.fixture
def identity() -> dict[str, Any]:
    return {
        "schema": "research-feature-block.v1",
        "feature_id": "invented-feature",
        "definition": {"id": "invented", "version": "v1"},
        "stock_code": "0050",
        "scope": "stock",
        "inputs": {"prices": "a" * 64},
        "implementation": {"research_core/example.py": "b" * 64},
        "calendar": {"sha256": "c" * 64, "rows": 2, "start": "2020-01-01", "end": "2020-01-02"},
        "semantics": {
            "price_basis": "invented-raw",
            "gap": "invented-reset",
            "warmup": "invented-full",
            "pivot_availability": "invented-confirmation",
            "calendar_policy": "invented-calendar",
            "quality_policy": "invented-quality",
        },
        "parameters": {"window": 3},
        "runtime": {"python": "invented-version"},
        "context": None,
    }


@pytest.fixture
def store(tmp_path: Path) -> blocks.FeatureBlockStore:
    return blocks.FeatureBlockStore(tmp_path / "store")


def reseal(version: Path, manifest: dict[str, Any]) -> Path:
    """Give an intentionally mutated manifest a matching external version hash."""
    body = {key: value for key, value in manifest.items() if key != "version_id"}
    manifest["version_id"] = object_digest(body)
    target = version.with_name(manifest["version_id"])
    version.rename(target)
    (target / "manifest.json").write_bytes(canonical(manifest))
    return target


def test_publish_exact_reuse_and_pinned_query(store: blocks.FeatureBlockStore, identity: dict[str, Any]) -> None:
    payloads = {"nested/data.bin": b"invented\x00bytes", "counts.json": b'{"n":2}'}
    first = store.publish(identity, payloads)
    version = Path(first["path"])
    before = {path.relative_to(version).as_posix(): path.read_bytes() for path in version.rglob("*") if path.is_file()}
    second = store.publish(deepcopy(identity), dict(reversed(list(payloads.items()))))
    assert first["reused"] is False and second["reused"] is True
    assert {key: value for key, value in first.items() if key != "reused"} == {key: value for key, value in second.items() if key != "reused"}
    assert version.parent.name == identity_digest(identity)
    assert blocks.verify_block(version, identity)["version_id"] == first["version_id"]
    assert store.inspect(identity)["status"] == "reusable"
    for name, data in payloads.items():
        assert store.read(identity, name) == store.read(identity, name, reference=first) == data
    assert before == {path.relative_to(version).as_posix(): path.read_bytes() for path in version.rglob("*") if path.is_file()}
    assert not list(store.root.glob(".*.lock"))


@pytest.mark.parametrize("section,key,value", [("inputs", "prices", "d" * 64), ("semantics", "gap", "another-gap")])
def test_plan_preserves_partial_missing_and_exact_dependency_changes(
    store: blocks.FeatureBlockStore, identity: dict[str, Any], section: str, key: str, value: str
) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    changed = deepcopy(identity)
    changed[section][key] = value
    plan = store.plan([identity, changed])
    assert [entry["status"] for entry in plan] == ["reusable", "missing"]
    assert plan[0]["reference"]["path"] == reference["path"]
    assert plan[0]["identity_id"] != plan[1]["identity_id"]
    with pytest.raises(ValueError, match="external reference identity/version mismatch"):
        store.read(changed, "data.bin", reference=reference)
    with pytest.raises(ValueError, match="missing"):
        store.read(changed, "data.bin")
    with pytest.raises(ValueError, match="duplicate"):
        store.plan([identity, deepcopy(identity)])


def test_corrupt_generation_is_retained_and_recovery_is_additive(store: blocks.FeatureBlockStore, identity: dict[str, Any]) -> None:
    old = store.publish(identity, {"data.bin": b"original"})
    old_version = Path(old["path"])
    manifest_bytes = (old_version / "manifest.json").read_bytes()
    (old_version / "data.bin").write_bytes(b"corrupt!")
    assert store.inspect(identity)["status"] == "invalid"
    with pytest.raises(ValueError, match="hash/size"):
        store.read(identity, "data.bin", reference=old)
    recovered = store.publish(identity, {"data.bin": b"original"})
    assert recovered["reused"] is False and recovered["version_id"] != old["version_id"]
    assert (old_version / "data.bin").read_bytes() == b"corrupt!"
    assert (old_version / "manifest.json").read_bytes() == manifest_bytes
    state = store.inspect(identity)
    assert state["status"] == "reusable"
    assert [entry["path"] for entry in state["invalid"]] == [old_version.name]
    assert store.read(identity, "data.bin", reference=recovered) == b"original"


def test_external_manifest_pin_rejects_changed_bytes(store: blocks.FeatureBlockStore, identity: dict[str, Any]) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    manifest_path = Path(reference["path"]) / "manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    blocks.verify_block(manifest_path.parent, identity)
    with pytest.raises(ValueError, match="external manifest pin"):
        store.read(identity, "data.bin", reference=reference)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("schema", "foreign-schema", "incomplete"),
        ("complete", False, "incomplete"),
        ("version_id", "0" * 64, "version mismatch"),
    ],
)
def test_manifest_schema_completion_and_version_are_checked(
    store: blocks.FeatureBlockStore, identity: dict[str, Any], field: str, value: Any, reason: str
) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    version = Path(reference["path"])
    manifest = read_json(version / "manifest.json")
    manifest[field] = value
    (version / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match=reason):
        blocks.verify_block(version, identity)
    assert store.inspect(identity)["status"] == "invalid"


@pytest.mark.parametrize("mutation,reason", [("identity", "identity directory"), ("descriptor", "hash/size"), ("duplicate", "duplicate artifact")])
def test_self_consistent_manifest_cannot_lie_about_identity_or_bytes(
    store: blocks.FeatureBlockStore, identity: dict[str, Any], mutation: str, reason: str
) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    version = Path(reference["path"])
    manifest = read_json(version / "manifest.json")
    if mutation == "identity":
        manifest["identity"]["inputs"]["prices"] = "d" * 64
    elif mutation == "descriptor":
        manifest["artifacts"][0]["sha256"] = "d" * 64
    else:
        manifest["artifacts"].append(deepcopy(manifest["artifacts"][0]))
    version = reseal(version, manifest)
    with pytest.raises(ValueError, match=reason):
        blocks.verify_block(version, identity)


def test_extra_files_and_undeclared_queries_are_rejected(store: blocks.FeatureBlockStore, identity: dict[str, Any]) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    with pytest.raises(ValueError, match="not declared"):
        store.read(identity, "missing.bin", reference=reference)
    version = Path(reference["path"])
    (version / "extra.bin").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="inventory"):
        blocks.verify_block(version, identity)
    assert store.inspect(identity)["status"] == "invalid"


def test_read_checks_the_actual_returned_bytes_after_verification(
    store: blocks.FeatureBlockStore, identity: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    verify = blocks.verify_block

    def mutate_after_verify(version: Path, requested: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = verify(version, requested)
        (version / "data.bin").write_bytes(b"changed!")
        return manifest

    monkeypatch.setattr(blocks, "verify_block", mutate_after_verify)
    with pytest.raises(ValueError, match="returned artifact bytes"):
        store.read(identity, "data.bin", reference=reference)


def test_read_rechecks_manifest_pin_at_end(store: blocks.FeatureBlockStore, identity: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    verify = blocks.verify_files
    calls = 0

    def mutate_after_final_check(version: Path, entries: list[dict[str, Any]]) -> None:
        nonlocal calls
        verify(version, entries)
        calls += 1
        if calls == 2:
            manifest = version / "manifest.json"
            manifest.write_bytes(manifest.read_bytes() + b"\n")

    monkeypatch.setattr(blocks, "verify_files", mutate_after_final_check)
    with pytest.raises(ValueError, match="manifest changed during read"):
        store.read(identity, "data.bin", reference=reference)


def test_unequal_publish_payload_rejected_without_overwrite_and_lock_retained(store: blocks.FeatureBlockStore, identity: dict[str, Any]) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    with pytest.raises(ValueError, match="different bytes"):
        store.publish(identity, {"data.bin": b"different"})
    assert store.read(identity, "data.bin", reference=reference) == b"original"
    lock = store.root / f".{identity_digest(identity)}.lock"
    retained = lock.read_bytes()
    with pytest.raises(FileExistsError):
        store.publish(identity, {"data.bin": b"original"})
    assert lock.read_bytes() == retained


def test_different_valid_generations_are_a_conflict(store: blocks.FeatureBlockStore, identity: dict[str, Any], tmp_path: Path) -> None:
    original = store.publish(identity, {"data.bin": b"original"})
    other = blocks.FeatureBlockStore(tmp_path / "other")
    conflicting = other.publish(identity, {"data.bin": b"different"})
    source = Path(conflicting["path"])
    source.rename(Path(original["path"]).parent / source.name)
    assert store.inspect(identity)["status"] == "conflict"
    with pytest.raises(ValueError, match="conflict"):
        store.read(identity, "data.bin")
    with pytest.raises(ValueError, match="different valid output"):
        store.publish(identity, {"data.bin": b"original"})
    assert store.read(identity, "data.bin", reference=original) == b"original"


def test_existing_exclusive_lock_is_never_overwritten(store: blocks.FeatureBlockStore, identity: dict[str, Any]) -> None:
    store.root.mkdir()
    lock = store.root / f".{identity_digest(identity)}.lock"
    lock.write_bytes(b"foreign or interrupted writer evidence")
    with pytest.raises(FileExistsError):
        store.publish(identity, {"data.bin": b"original"})
    assert lock.read_bytes() == b"foreign or interrupted writer evidence"
    assert store.inspect(identity)["status"] == "missing"


def test_publication_collision_never_overwrites_foreign_target(
    store: blocks.FeatureBlockStore, identity: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    publish = blocks.publish_new_directory
    destinations: list[Path] = []

    def competing_writer(destination: Path, files: dict[str, bytes]) -> None:
        destinations.append(destination)
        destination.mkdir()
        (destination / "foreign.bin").write_bytes(b"foreign")
        publish(destination, files)

    monkeypatch.setattr(blocks, "publish_new_directory", competing_writer)
    with pytest.raises(FileExistsError):
        store.publish(identity, {"data.bin": b"original"})
    assert (destinations[0] / "foreign.bin").read_bytes() == b"foreign"
    assert not (destinations[0] / "data.bin").exists()
    assert (store.root / f".{identity_digest(identity)}.lock").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "nested/../escape",
        "/absolute",
        "D:/absolute",
        "nested\\data.bin",
        "a:stream",
        "",
        "a//b",
        "./data",
        "manifest.json",
        "manifest.json/nested",
    ],
)
def test_forbidden_and_reserved_payload_paths_do_not_publish(store: blocks.FeatureBlockStore, identity: dict[str, Any], name: str) -> None:
    with pytest.raises(ValueError):
        store.publish(identity, {name: b"invented"})
    assert not store.root.exists()


@pytest.mark.parametrize("payload", [{}, {"data.bin": "text"}, {"data.bin": bytearray(b"bytes")}])
def test_payloads_must_be_nonempty_bytes_mapping(store: blocks.FeatureBlockStore, identity: dict[str, Any], payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="byte payload"):
        store.publish(identity, payload)
    assert not store.root.exists()


def test_relative_and_traversing_roots_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        blocks.FeatureBlockStore(Path("relative-store"))
    with pytest.raises(ValueError, match="traversal"):
        blocks.FeatureBlockStore(tmp_path / "nested" / ".." / "store")


def test_reference_from_another_root_is_rejected(store: blocks.FeatureBlockStore, identity: dict[str, Any], tmp_path: Path) -> None:
    foreign = blocks.FeatureBlockStore(tmp_path / "foreign").publish(identity, {"data.bin": b"original"})
    with pytest.raises(ValueError, match="outside"):
        store.read(identity, "data.bin", reference=foreign)


@pytest.mark.parametrize("field,value", [("identity_id", "0" * 64), ("version_id", "0" * 64)])
def test_external_reference_identity_and_version_pins_are_checked(store: blocks.FeatureBlockStore, identity: dict[str, Any], field: str, value: str) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    forged = {**reference, field: value}
    with pytest.raises(ValueError, match="external reference identity/version mismatch"):
        store.read(identity, "data.bin", reference=forged)
    assert store.read(identity, "data.bin", reference=reference) == b"original"


def test_external_reference_relative_path_is_rejected_before_resolution(
    store: blocks.FeatureBlockStore, identity: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    monkeypatch.chdir(store.root.parent)
    relative = Path(reference["path"]).relative_to(store.root.parent)
    with pytest.raises(ValueError, match="absolute feature reference path"):
        store.read(identity, "data.bin", reference={**reference, "path": str(relative)})


def test_verify_requires_digest_directory_and_requested_identity(store: blocks.FeatureBlockStore, identity: dict[str, Any]) -> None:
    reference = store.publish(identity, {"data.bin": b"original"})
    version = Path(reference["path"])
    changed = deepcopy(identity)
    changed["stock_code"] = "50"
    with pytest.raises(ValueError, match="requested feature identity"):
        blocks.verify_block(version, changed)
    version.rename(version.with_name("mutable-latest"))
    with pytest.raises(ValueError, match="explicit identity/version"):
        blocks.verify_block(version.with_name("mutable-latest"))
