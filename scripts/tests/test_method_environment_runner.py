"""Synthetic packet preparation tests; no market outcomes are accessed."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from research_core.evidence import EvidenceError
from scripts import run_method_environment_interactions as runner


def test_manifest_enumeration_rejects_traversal_and_duplicate(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps({"artifacts": [{"path": "../escape.json"}]}))
    with pytest.raises(EvidenceError):
        runner.declared_artifacts(tmp_path, "source", atlas=False)
    manifest.write_text(json.dumps({"artifacts": [{"path": "a.json"}, {"path": "A.json"}]}))
    with pytest.raises(ValueError, match="duplicate"):
        runner.declared_artifacts(tmp_path, "source", atlas=False)


def test_prepare_hashes_all_artifacts_without_evaluating_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Only packet shape is exercised: fake hashing never reads real source data.
    monkeypatch.setattr(runner, "declared_artifacts", lambda root, relative, **kwargs: [f"{relative}/manifest.json", f"{relative}/all-inputs.bin"])
    monkeypatch.setattr(runner, "file_digest", lambda path: "a" * 64)
    monkeypatch.setattr(runner, "runtime_identity", lambda: {"python": "synthetic"})
    monkeypatch.setattr(runner, "load_analysis", lambda *args, **kwargs: pytest.fail("preparation must not load observations"))
    monkeypatch.setattr(runner, "load_context_rows", lambda *args, **kwargs: pytest.fail("preparation must not load contexts"))
    info = runner.prepare_packet(tmp_path, "fixture-v1")
    plain = Path(info["packet"])
    compressed = Path(info["portable_packet"])
    assert gzip.decompress(compressed.read_bytes()) == plain.read_bytes()
    packet = json.loads(plain.read_text())
    assert len(packet["inputs"]["data"]) == 4
    assert packet["params"]["max_comparisons"] == 672
    assert packet["phase"] == "exploration"
    assert packet["timeout_seconds"] == 1800
    with pytest.raises(ValueError, match="destination exists"):
        runner.prepare_packet(tmp_path, "fixture-v1")
