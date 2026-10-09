"""Verify exact source bytes and explicitly load only the frozen pure detector."""

from __future__ import annotations

import ast
import hashlib
import types
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.artifact_store import read_json, safe_path

ROOT = Path(__file__).parent


def verify_sources(version: str) -> dict[str, str]:
    """No scratch paths, source rewriting or implicit data reads."""
    registry = read_json(ROOT / "sources.json")
    if version not in registry["versions"]:
        raise ValueError("unregistered HHHL version")
    record = registry["versions"][version]
    path = safe_path(ROOT / record["archive"])
    with path.open("rb") as stream:
        captured = stream.read(1_000_001)
    if len(captured) > 1_000_000:
        raise ValueError("HHHL archive exceeds size limit")
    if hashlib.sha256(captured).hexdigest() != record["sha256"]:
        raise ValueError("HHHL archive hash mismatch")
    texts: dict[str, str] = {}
    with zipfile.ZipFile(BytesIO(captured)) as archive:
        if sorted(archive.namelist()) != sorted(record["members"]):
            raise ValueError("HHHL archive members mismatch")
        for name, expected in record["members"].items():
            info = archive.getinfo(name)
            if info.file_size > 100_000:
                raise ValueError("HHHL source exceeds size limit")
            raw = archive.read(name)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("HHHL source hash mismatch")
            texts[name] = raw.decode("utf-8")
    return texts


def _pure_module(text: str, namespace: dict[str, Any], filename: str) -> dict[str, Any]:
    nodes: list[ast.stmt] = []
    for node in ast.parse(text).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not isinstance(node, (ast.FunctionDef, ast.Assign, ast.Expr)) or (isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant)):
            raise ValueError("unexpected frozen module statement")
        nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
    return namespace


def load_detector(version: str) -> Any:
    """Explicit trusted-source execution, not a sandbox or data loader.

    Original detect.py example generator and adjprice.py's live-data loader are
    NEVER executed. The caller must supply the price basis and ATR input.
    """
    return _detector_from_sources(version, verify_sources(version))


def _detector_from_sources(version: str, texts: dict[str, str]) -> Any:
    """Compile a caller's captured trusted source mapping without rereading it."""
    functions: list[ast.stmt] = [node for node in ast.parse(texts["detect.py"]).body if isinstance(node, ast.FunctionDef) and node.name == "pivots_atr"]
    if len(functions) != 1:
        raise ValueError("one frozen pivots_atr required")
    pivot_namespace: dict[str, Any] = {"np": np}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "detect.py", "exec"), pivot_namespace)
    namespace: dict[str, Any] = {"np": np, "pd": pd, "pivots_atr": pivot_namespace["pivots_atr"]}
    range_name = "bigrange_v4" if version == "v4" else "bigrange"
    if f"{range_name}.py" in texts:
        range_namespace = _pure_module(texts[f"{range_name}.py"], dict(namespace), f"{range_name}.py")
        namespace[range_name] = types.SimpleNamespace(**{key: value for key, value in range_namespace.items() if key != "__builtins__"})
    namespace = _pure_module(texts[f"hhhl_rule_{version}.py"], namespace, f"hhhl_rule_{version}.py")
    return namespace["detect"]
