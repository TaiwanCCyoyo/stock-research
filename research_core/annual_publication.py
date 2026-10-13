"""Read-only annual-result verification and source-bound reuse of frozen ranks."""

from __future__ import annotations

import ast
import gzip
import json
import math
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from research_core.artifact_store import file_digest, read_json
from research_core.research_data_catalog import DataCatalog, verify_entry


def _equivalent(actual: Any, expected: Any) -> bool:
    # Formatting can turn JSON 0.0 into 0. Keep numeric meaning, but never equate
    # a boolean to a number; dictionary/list structure and every value must match.
    if isinstance(expected, bool):
        return type(actual) is bool and actual == expected
    if isinstance(expected, (int, float)):
        return type(actual) in (int, float) and math.isfinite(actual) and Decimal(str(actual)) == Decimal(str(expected))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all(_equivalent(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_equivalent(a, b) for a, b in zip(actual, expected, strict=True))
    return type(actual) is type(expected) and actual == expected


def verified_result(path: Path, catalog: DataCatalog) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Bind a public report to the exact published payload and input lineage."""
    result = read_json(path)
    for key, expected_id in (("input_entry", "annual-rotation-inputs"), ("process_entry", "annual-rotation-process")):
        entry = result[key]
        if entry["data_id"] != expected_id:
            raise ValueError("unexpected annual dataset family")
        stored = catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"])
        if not _equivalent(entry, stored):
            raise ValueError("public entry differs from registered identity")
    input_entry, process_entry = result["input_entry"], result["process_entry"]
    manifest = verify_entry(process_entry, catalog.roots)
    inputs = manifest["metadata"]["inputs"]
    if inputs["input_version"] != input_entry["version_id"] or inputs["input_manifest_sha256"] != input_entry["manifest"]["sha256"]:
        raise ValueError("input/process identity mismatch")
    if not _equivalent(manifest["lineage"]["input_entry"], input_entry) or not _equivalent(inputs["source"], result["source"]):
        raise ValueError("source/input lineage mismatch")
    members = {row["path"]: row["sha256"] for row in manifest["artifacts"]}
    for name, digest in result["source"]["files"].items():
        if members.get(f"implementation/{name}") != digest:
            raise ValueError("source snapshot differs from manifest member digest")
    root = catalog.roots.artifact_path(process_entry["manifest"]["scope"], process_entry["manifest"]["path"]).parent
    expected = read_json(root / "results.json")
    public = {key: value for key, value in result.items() if key != "process_entry"}
    if not _equivalent(public, expected):
        raise ValueError("public results differ from published results.json")
    reused = manifest["lineage"].get("ranking_reuse_entry")
    if reused is not None:
        old_manifest = verify_entry(reused, catalog.roots)
        if not _equivalent(old_manifest["lineage"]["input_entry"], input_entry) or not _equivalent(inputs.get("ranking_reuse_entry"), reused):
            raise ValueError("reused ranking input lineage mismatch")
    return result, root, manifest


def reuse_rank_rows(previous_path: Path, catalog: DataCatalog, *, repo: Path, input_entry: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    """Reuse unchanged numerical ranking without rerunning any market stock.

    This compatibility bridge is intentionally narrow: only the tail holding
    helpers may change. The old ranking/economic prefix, pool, price basis,
    action types, parameters and input version must match exactly.
    """
    previous, root, manifest = verified_result(previous_path, catalog)
    if not _equivalent(previous["input_entry"], input_entry) or not _equivalent(manifest["metadata"]["parameters"], parameters):
        raise ValueError("rank reuse inputs/parameters mismatch")
    module_name = "research_core/annual_rotation.py"
    old_module = (root / "implementation" / module_name).read_bytes()
    new_module = (repo / module_name).read_bytes()
    boundary = b"\ndef paired_benchmark_path"
    if boundary not in old_module or old_module.split(boundary)[0] != new_module.split(boundary)[0]:
        raise ValueError("ranking/economic implementation prefix changed")
    for name in ("research_core/annual_ranking_pool.py", "research_core/price_basis.py", "StockProject/engine/data_loader.py"):
        if file_digest(repo / name) != previous["source"]["files"][name]:
            raise ValueError(f"ranking dependency changed: {name}")
    runner = "tasks/20261013-annual-winner-rotation/run_study.py"

    def scope_tree(path: Path) -> str:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return ast.dump(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "scope"))

    if scope_tree(root / "implementation" / runner) != scope_tree(repo / runner):
        raise ValueError("historical scope implementation changed")
    with gzip.GzipFile(fileobj=BytesIO((root / "candidates.json.gz").read_bytes())) as stream:
        raw = stream.read(64_000_001)
    if len(raw) > 64_000_000:
        raise ValueError("candidate payload exceeds bound")
    rows = json.loads(raw)
    execution = read_json(root / "execution.json")
    if not isinstance(rows, list) or len(rows) != execution["row_count"]:
        raise ValueError("candidate count differs from retained execution")
    return {"rows": rows, "performance": {**execution, "rank_reuse": {"entry": previous["process_entry"], "new_stocks_calculated": 0}}}
