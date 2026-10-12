"""Real CLI metadata workflows over invented blocks, without worker execution."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from research_core.artifact_store import write_json
from research_core.feature_benchmark_v1 import run_synthetic_benchmark
from research_core.feature_block_store_v1 import FeatureBlockStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def identity() -> dict[str, Any]:
    return {
        "schema": "research-feature-block.v1",
        "feature_id": "invented",
        "definition": {"id": "invented", "version": "v1"},
        "stock_code": "0001",
        "scope": "stock",
        "inputs": {"invented": "a" * 64},
        "implementation": {"research_core/invented.py": "b" * 64},
        "calendar": {"sha256": "c" * 64, "rows": 2, "start": "2020-01-01", "end": "2020-01-02"},
        "semantics": {
            "price_basis": "invented",
            "gap": "reset",
            "warmup": "seed",
            "pivot_availability": "confirmation",
            "calendar_policy": "explicit",
            "quality_policy": "valid",
        },
        "parameters": {},
        "runtime": {"python": "invented"},
        "context": None,
    }


def cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-m", "scripts.feature_blocks", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30
    )


def test_cli_plan_and_query_exact_metadata(tmp_path: Path, identity: dict[str, Any]) -> None:
    store = FeatureBlockStore(tmp_path / "store")
    reference = store.publish(identity, {"invented.bin": b"invented payload"})
    changed = deepcopy(identity)
    changed["semantics"]["gap"] = "different"
    packet, single = tmp_path / "plan.json", tmp_path / "identity.json"
    write_json(packet, {"identities": [identity, changed]})
    write_json(single, identity)
    before = {path.relative_to(store.root).as_posix(): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    planned = cli("plan", "--store", str(store.root), "--identities", str(packet))
    assert planned.returncode == 0, planned.stderr
    blocks = json.loads(planned.stdout)["blocks"]
    assert [row["status"] for row in blocks] == ["reusable", "missing"]
    assert blocks[0]["reference"]["path"] == reference["path"]
    queried = cli("query", "--store", str(store.root), "--identity", str(single))
    assert queried.returncode == 0, queried.stderr
    result = json.loads(queried.stdout)
    assert result["schema"] == "research-feature-query.v1"
    assert result["block"]["status"] == "reusable"
    assert result["block"]["reference"]["artifacts"] == reference["artifacts"]
    assert before == {path.relative_to(store.root).as_posix(): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    assert "invented payload" not in queried.stdout


def test_cli_query_reports_invalid_retaining_corrupt_bytes(tmp_path: Path, identity: dict[str, Any]) -> None:
    store = FeatureBlockStore(tmp_path / "store")
    reference = store.publish(identity, {"invented.bin": b"original"})
    artifact = Path(reference["path"]) / "invented.bin"
    artifact.write_bytes(b"corrupted")
    single = tmp_path / "identity.json"
    write_json(single, identity)
    result = cli("query", "--store", str(store.root), "--identity", str(single))
    assert result.returncode == 0, result.stderr
    block = json.loads(result.stdout)["block"]
    assert block["status"] == "invalid" and block["reference"] is None
    assert block["invalid"]
    assert artifact.read_bytes() == b"corrupted"


def test_cli_rejects_relative_store_and_market_execution(tmp_path: Path, identity: dict[str, Any]) -> None:
    single = tmp_path / "identity.json"
    write_json(single, identity)
    relative = cli("query", "--store", "relative", "--identity", str(single))
    assert relative.returncode != 0 and "absolute feature store" in relative.stderr
    assert cli("execute-market").returncode != 0


def test_benchmark_requires_absolute_fresh_scratch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Absolute fresh"):
        run_synthetic_benchmark(Path("relative"))
    with pytest.raises(FileExistsError, match="fresh scratch"):
        run_synthetic_benchmark(tmp_path)
    assert not list(tmp_path.iterdir())
