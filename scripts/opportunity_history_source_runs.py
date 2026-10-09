"""Recompute deterministic source run indices with the exact pinned JavaScript wrapper."""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("verify_opportunity_source_runs.mjs")


def _read(path: Path) -> Any:
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def expected_source_runs(manifest_path: Path, codes: set[str] | None = None) -> dict[str, list[int | None]]:
    """Batch selected or all native stock codes once, with no Python math fallback."""
    manifest = _read(manifest_path)
    native = manifest.get("native")
    if not isinstance(native, dict) or any(not isinstance(code, str) for code in native):
        raise ValueError("Invalid native code map for exact JavaScript source run validation")
    selected = set(native) if codes is None else codes
    if not isinstance(selected, set) or any(not isinstance(code, str) or not code for code in selected) or not selected.issubset(native):
        raise ValueError("Invalid selected code set for exact JavaScript source run validation")
    calendar = _read(manifest_path.parent / manifest["calendar"]["path"])
    count = len(calendar["dates"])
    if codes is not None and not selected:
        return {}
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is unavailable on PATH for exact JavaScript source run validation")
    command = [node, "--experimental-strip-types", str(SCRIPT), "--manifest", str(manifest_path.resolve())]
    if codes is not None:
        for code in sorted(selected):
            command.extend(["--code", code])
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"Node is unavailable for exact JavaScript source run validation: {node}") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Exact JavaScript source run validation failed: {error.stderr or error}") from error
    except OSError as error:
        raise RuntimeError(f"Cannot execute Node for exact JavaScript source run validation: {error}") from error
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("Invalid JSON from exact JavaScript source run validation") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "opportunity-expected-source-runs.v1"
        or type(payload.get("calendar_count")) is not int
        or payload["calendar_count"] != count
    ):
        raise ValueError("Invalid exact JavaScript source run response schema/calendar count")
    results = payload.get("results")
    if not isinstance(results, dict) or set(results) != selected:
        raise ValueError("Exact JavaScript source run response code mismatch")
    for code, runs in results.items():
        if not isinstance(runs, list) or len(runs) != count or any(value is not None and (type(value) is not int or value < 0) for value in runs):
            raise ValueError(f"Invalid exact JavaScript source run array: {code}")
    return results
