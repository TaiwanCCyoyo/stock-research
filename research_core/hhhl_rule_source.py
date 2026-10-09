"""Load a byte-preserved owner rule without running the old example generator."""

from __future__ import annotations

import ast
import hashlib
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
SOURCE_HASHES = {
    "hhhl_rule_v1": {
        "hhhl_rule_v1.py": "0039ca034d396dbba21f5e3e6de2bb552f809404e2424e5c1beb0f84eed017ba",  # pragma: allowlist secret - verified source SHA-256
        "detect.py": "fba922502f8d34c2c928c7accca9baa17b1e9c83dae8be398b8b4fa773ee8eeb",  # pragma: allowlist secret - verified source SHA-256
    },
    "hhhl_rule_v4": {
        "hhhl_rule_v4.py": "6390e5a61519c041a6989257af59599e71ae1c24ba5d6d70c96c5c7ea8f8d5c8",  # pragma: allowlist secret - verified source SHA-256
        "bigrange_v4.py": "59634879c7e0358b57baa98a2187eb7de928de7df229c3053ba905f91a6dd574",  # pragma: allowlist secret - verified source SHA-256
        "adjprice.py": "cb8d7a53b8362c51292795eefd90e9cdb8353b38fa81695779bf6e7b7fe777ef",  # pragma: allowlist secret - verified source SHA-256
        "detect.py": "fba922502f8d34c2c928c7accca9baa17b1e9c83dae8be398b8b4fa773ee8eeb",  # pragma: allowlist secret - verified source SHA-256
    },
}
Pivot = tuple[int, int, float]
PivotFunction = Callable[..., tuple[list[Pivot], list[Pivot]]]


@dataclass(frozen=True)
class FrozenRule:
    rule_id: str
    detect: Callable[[pd.DataFrame], list[dict[str, Any]]]
    pivots: PivotFunction
    k: float
    source_hashes: dict[str, str]


def load_source_texts(sources: Path, rule_id: str) -> dict[str, str]:
    """Read only a registered archive whose complete member set and bytes match."""
    if rule_id not in SOURCE_HASHES:
        raise ValueError(f"unregistered rule version: {rule_id}")
    texts = {}
    with zipfile.ZipFile(sources / f"{rule_id}.zip") as archive:
        if sorted(archive.namelist()) != sorted(SOURCE_HASHES[rule_id]):
            raise ValueError("frozen archive members mismatch")
        for name, expected in SOURCE_HASHES[rule_id].items():
            raw = archive.read(name)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"frozen source hash mismatch: {name}")
            texts[name] = raw.decode("utf-8")
    return texts


def load_rule(sources: Path, rule_id: str) -> FrozenRule:
    """Only registered, exact local source bytes are executable; no tmp imports."""
    texts = load_source_texts(sources, rule_id)
    if rule_id == "hhhl_rule_v4":
        from research_core.hhhl_v4_source import load_v4_components

        detect, pivots, k, _ = load_v4_components(texts)
        LOGGER.info("Loaded frozen rule=%s source_count=%d", rule_id, len(texts))
        return FrozenRule(rule_id, detect, pivots, k, dict(SOURCE_HASHES[rule_id]))
    pivot_tree = ast.parse(texts["detect.py"])
    pivot_nodes: list[ast.stmt] = [n for n in pivot_tree.body if isinstance(n, ast.FunctionDef) and n.name == "pivots_atr"]
    if len(pivot_nodes) != 1:
        raise ValueError("source must declare one pivots_atr function")
    pivot_namespace: dict[str, Any] = {"np": np}
    exec(compile(ast.Module(body=pivot_nodes, type_ignores=[]), "detect.py", "exec"), pivot_namespace)
    pivots = cast(PivotFunction, pivot_namespace["pivots_atr"])
    rule_tree = ast.parse(texts[f"{rule_id}.py"])
    imports = [n for n in rule_tree.body if isinstance(n, ast.ImportFrom) and n.module == "detect"]
    if len(imports) != 1 or [(a.name, a.asname) for a in imports[0].names] != [("pivots_atr", None)]:
        raise ValueError("unexpected frozen rule import seam")
    rule_tree.body.remove(imports[0])
    namespace: dict[str, Any] = {"pivots_atr": pivots}
    exec(compile(rule_tree, f"{rule_id}.py", "exec"), namespace)
    LOGGER.info("Loaded frozen rule=%s source_count=%d", rule_id, len(texts))
    return FrozenRule(rule_id, namespace["detect"], pivots, float(namespace["K"]), dict(SOURCE_HASHES[rule_id]))
