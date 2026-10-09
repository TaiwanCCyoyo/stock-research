from __future__ import annotations

import gzip
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import build_opportunity_history as builder
from scripts import rebuild_saved_opportunity_catalog as rebuild
from scripts.build_opportunity_history import canonical, read_json
from scripts.tests.test_rebuild_saved_opportunity_catalog import saved_catalog

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Saved rebuild publication requires Windows mandatory file-sharing guards")


def _replace_json(path: Path, value: Any) -> None:
    data = canonical(value)
    path.write_bytes(gzip.compress(data, mtime=0) if path.suffix == ".gz" else data)


def _source_bytes(source_path: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in source_path.parent.parent.rglob("*") if path.is_file()}


def _assert_preserved(before: dict[Path, bytes], changed: dict[Path, bytes]) -> None:
    for path, raw in before.items():
        assert path.read_bytes() == changed.get(path, raw)


@pytest.fixture(autouse=True)
def prohibit_method_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Saved-only rebuild must not execute Node, fitting, or another process")

    monkeypatch.setattr(builder, "run_node", forbidden)
    monkeypatch.setattr(builder.subprocess, "run", forbidden)


SOURCE_ARTIFACTS = (
    "native",
    "receipt",
    "manifest",
    "params",
    "input",
    "series",
    "excluded_series",
    "table",
    "calendar",
    "series_manifest",
    "extra",
    "method_source",
)


def _artifact(source_path: Path, name: str) -> Path:
    root = source_path.parent
    task = root.parent
    return {
        "native": task / "runs/native/A.json.gz",
        "receipt": task / "runs/native/A.receipt.json",
        "manifest": source_path,
        "params": task / "params.json",
        "input": task / "inputs/fixture.bin",
        "series": root / "series/A.json.gz",
        "excluded_series": root / "series/U.json.gz",
        "table": root / "chunks/securities-00000.json.gz",
        "calendar": root / "series/calendar.json",
        "series_manifest": root / "series-manifest.json",
        "extra": root / "classifications.json",
        "method_source": task / "method-snapshot/analysis.ts",
    }[name]


def _mutate(path: Path, changed: dict[Path, bytes]) -> None:
    if path.suffix in (".json", ".gz"):
        value = read_json(path)
        if "timing" in value:
            value["timing"]["elapsed_ms"] += 1
        else:
            value["mutation_after_verification"] = True
        _replace_json(path, value)
    else:
        path.write_bytes(path.read_bytes() + b"\nmutation after verification\n")
    changed[path] = path.read_bytes()


def test_native_timing_mutation_after_verification_refuses_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = saved_catalog(tmp_path / "task")
    before = _source_bytes(source_path)
    native_path = source_path.parent.parent / "runs/native/A.json.gz"
    output = source_path.parent.parent / "catalog-v2"
    changed: dict[Path, bytes] = {}
    original_verify = rebuild._verify_source

    def verify_then_mutate(*args: Any, **kwargs: Any) -> Any:
        verified = original_verify(*args, **kwargs)
        native = read_json(native_path)
        native["timing"]["elapsed_ms"] += 1
        _replace_json(native_path, native)
        changed[native_path] = native_path.read_bytes()
        return verified

    monkeypatch.setattr(rebuild, "_verify_source", verify_then_mutate)
    with pytest.raises(ValueError):
        rebuild.rebuild_saved_catalog(source_path, output)
    assert changed
    assert not (output / "manifest.json").exists()
    _assert_preserved(before, changed)


@pytest.mark.parametrize("artifact", SOURCE_ARTIFACTS)
@pytest.mark.parametrize("stage", ["verified", "last_adaptation", "chunk_written"])
def test_source_mutation_at_rebuild_boundaries_refuses_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
    stage: str,
) -> None:
    source_path = saved_catalog(tmp_path / "task")
    before = _source_bytes(source_path)
    output = source_path.parent.parent / "catalog-v2"
    changed: dict[Path, bytes] = {}
    target = _artifact(source_path, artifact)

    def mutate_once() -> None:
        if not changed:
            _mutate(target, changed)

    if stage == "verified":
        original_verify = rebuild._verify_source

        def verify_then_mutate(*args: Any, **kwargs: Any) -> Any:
            result = original_verify(*args, **kwargs)
            mutate_once()
            return result

        monkeypatch.setattr(rebuild, "_verify_source", verify_then_mutate)
    elif stage == "last_adaptation":
        original_adapt = rebuild.adapt_security

        def adapt_then_mutate(series: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            result = original_adapt(series, *args, **kwargs)
            # U is the final, excluded security. Both U and A have already
            # been read, so a read-time check alone cannot catch this change.
            if series["code"] == "U":
                mutate_once()
            return result

        monkeypatch.setattr(rebuild, "adapt_security", adapt_then_mutate)
    else:
        original_write = rebuild.write_json

        def write_then_mutate(path: Path, value: Any) -> None:
            original_write(path, value)
            if path.parent == output / "chunks":
                mutate_once()

        monkeypatch.setattr(rebuild, "write_json", write_then_mutate)

    with pytest.raises(ValueError):
        rebuild.rebuild_saved_catalog(source_path, output)
    assert changed, "The scheduled mutation must execute before rejection"
    assert not (output / "manifest.json").exists()
    _assert_preserved(before, changed)
    if stage != "verified":
        assert output.is_dir()
        assert any(path.is_file() for path in output.rglob("*")), "Keep partial evidence for inspection"


@pytest.mark.parametrize("artifact", ["early_chunk", "copied_series"])
def test_output_mutation_after_chunk_write_refuses_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    source_path = saved_catalog(tmp_path / "task")
    before = _source_bytes(source_path)
    output = source_path.parent.parent / "catalog-v2"
    original_write = rebuild.write_json
    written_chunks: list[Path] = []
    changed: dict[Path, bytes] = {}

    def write_then_mutate(path: Path, value: Any) -> None:
        original_write(path, value)
        if path.parent == output / "chunks":
            written_chunks.append(path)
            # The first chunk already has its descriptor when the second is
            # written; hashing only each newly written chunk misses this.
            if len(written_chunks) == 2:
                target = written_chunks[0] if artifact == "early_chunk" else output / "series/A.json.gz"
                _mutate(target, changed)

    monkeypatch.setattr(rebuild, "write_json", write_then_mutate)
    with pytest.raises(ValueError):
        rebuild.rebuild_saved_catalog(source_path, output)
    assert changed
    assert not (output / "manifest.json").exists()
    _assert_preserved(before, {})
    _assert_preserved(changed, {})
    assert output.is_dir()


def test_unchanged_saved_sources_publish_without_execution_or_overwrite(tmp_path: Path) -> None:
    source_path = saved_catalog(tmp_path / "task")
    before = _source_bytes(source_path)
    output = source_path.parent.parent / "catalog-v2"
    manifest = rebuild.rebuild_saved_catalog(source_path, output)
    assert (output / "manifest.json").is_file()
    assert manifest["analysis_recomputed"] is False
    assert manifest["analyzed_security_count"] == 1
    assert sum(ref["count"] for ref in manifest["tables"]["securities"]) == 2
    _assert_preserved(before, {})


def test_current_chunk_mutation_before_descriptor_refuses_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = saved_catalog(tmp_path / "task")
    before = _source_bytes(source_path)
    output = source_path.parent.parent / "catalog-v2"
    original_write = rebuild.write_json
    changed: dict[Path, bytes] = {}

    def write_then_mutate_current_chunk(path: Path, value: Any) -> None:
        original_write(path, value)
        # The caller has not yet received write_json's return, so it cannot
        # have constructed this chunk's descriptor from the saved path.
        if path.parent == output / "chunks" and not changed:
            _mutate(path, changed)

    monkeypatch.setattr(rebuild, "write_json", write_then_mutate_current_chunk)
    with pytest.raises(ValueError):
        rebuild.rebuild_saved_catalog(source_path, output)
    assert changed
    assert not (output / "manifest.json").exists()
    _assert_preserved(before, {})
    _assert_preserved(changed, {})
    assert output.is_dir()


def test_native_single_read_mutation_with_unchanged_disk_refuses_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = saved_catalog(tmp_path / "task")
    before = _source_bytes(source_path)
    output = source_path.parent.parent / "catalog-v2"
    native_path = _artifact(source_path, "native").resolve()
    native = read_json(native_path)
    native["timing"]["elapsed_ms"] += 1
    mutated_read = gzip.compress(canonical(native), mtime=0)
    original_read_bytes = Path.read_bytes
    intercepted = False

    def read_bytes_with_one_mutated_native(path: Path) -> bytes:
        nonlocal intercepted
        if path.resolve() == native_path and output.exists() and not intercepted:
            intercepted = True
            return mutated_read
        return original_read_bytes(path)

    # Initial verification sees original bytes. The later read gets valid
    # but different bytes once; a separate hash read or final disk recheck
    # sees the unchanged original and cannot detect the consumed mutation.
    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_one_mutated_native)
    with pytest.raises(ValueError):
        rebuild.rebuild_saved_catalog(source_path, output)
    assert intercepted
    assert not (output / "manifest.json").exists()
    _assert_preserved(before, {})
    assert output.is_dir()
    assert any(path.is_file() for path in output.rglob("*"))


@pytest.mark.parametrize("artifact", ["native", "source_manifest", "early_chunk", "copied_series"])
def test_mutation_at_manifest_write_boundary_refuses_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    source_path = saved_catalog(tmp_path / "task")
    before = _source_bytes(source_path)
    output = source_path.parent.parent / "catalog-v2"
    original_write = rebuild.write_json
    changed: dict[Path, bytes] = {}
    attempted = False
    partial_before: dict[Path, bytes] = {}

    def write_with_publication_boundary_actor(path: Path, value: Any) -> None:
        nonlocal attempted, partial_before
        # Match the publication artifact even if the implementation prepares
        # it in a private staging directory before atomic publication.
        if path.name == "manifest.json" and path.resolve() != source_path.resolve() and not attempted:
            partial_before = {item: item.read_bytes() for item in output.rglob("*") if item.is_file()}
            targets = {
                "native": _artifact(source_path, "native"),
                "source_manifest": source_path,
                "early_chunk": sorted((output / "chunks").glob("*.json.gz"))[0],
                "copied_series": output / "series/A.json.gz",
            }
            # A writer guard may reject the actor's write. Record the attempt
            # first and let that refusal reach the rebuild's failure handling.
            attempted = True
            _mutate(targets[artifact], changed)
        original_write(path, value)

    monkeypatch.setattr(rebuild, "write_json", write_with_publication_boundary_actor)
    with pytest.raises(ValueError):
        rebuild.rebuild_saved_catalog(source_path, output)
    assert attempted, "The actor must reach the manifest publication boundary"
    assert not (output / "manifest.json").exists()
    _assert_preserved(before, changed)
    assert partial_before, "Completed export evidence must exist before publication"
    _assert_preserved(partial_before, changed)
