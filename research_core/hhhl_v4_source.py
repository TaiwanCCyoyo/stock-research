"""Load the byte-preserved v4 rule and prepare its price inputs from memory only."""

from __future__ import annotations

import ast
import datetime as dt
import logging
import types
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
RULE_ID = "hhhl_rule_v4"
DATASET_ID = "fda-86245f2e223fc45c9f84afb0dcf77c1fff7ab22d0a1b0b4a4c8800972ce9327e"
# Exact members of the preregistered preparation-v1 bundle (4908ef85...db549).
FIXED_INPUT_SHA256 = {
    "corporate_action_factors.parquet": "sha256:427b81a70d3548a0595a80c547544cf4da8824ddcbda2dbb366032e68ba5df7a".removeprefix("sha256:"),
    "validation-cases.json": "sha256:8e2c2937c38fe276a00246b23b497b8f7f8a93b20ff9dca2be7a463453ec7abb".removeprefix("sha256:"),
    "input-receipt.json": "sha256:d4942a053b2df2328da5ef83d8854e1079ddd5c50507e48961e4488ec888e550".removeprefix("sha256:"),
}
DEFAULT_CUTOFF = "2026-08-14"
RAW_COLUMNS = (
    "asof_date",
    "RawOpen",
    "RawHigh",
    "RawLow",
    "RawClose",
    "VolumeLots",
    "atr14_pct",
)
ACTION_COLUMNS = ("code", "ex_date", "event_type", "price_factor")
OHLC_COLUMNS = ("RawOpen", "RawHigh", "RawLow", "RawClose")

Pivot = tuple[int, int, float]
PivotFunction = Callable[..., tuple[list[Pivot], list[Pivot]]]
PriceLoader = Callable[[pd.DataFrame, pd.DataFrame, str, str], pd.DataFrame]


def _import_signature(tree: ast.Module) -> list[tuple[Any, ...]]:
    signature: list[tuple[Any, ...]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            signature.append(("import", tuple((item.name, item.asname) for item in node.names)))
        elif isinstance(node, ast.ImportFrom):
            signature.append(("from", node.module, node.level, tuple((item.name, item.asname) for item in node.names)))
    return signature


def _require_imports(tree: ast.Module, expected: list[tuple[Any, ...]], label: str) -> None:
    if _import_signature(tree) != expected:
        raise ValueError(f"unexpected frozen {label} imports")


def _one_function(tree: ast.Module, name: str, label: str) -> ast.FunctionDef:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(functions) != 1:
        raise ValueError(f"frozen {label} must declare one {name} function")
    return functions[0]


def _compile(tree: ast.Module, filename: str, namespace: dict[str, Any]) -> dict[str, Any]:
    exec(compile(tree, filename, "exec"), namespace)
    return namespace


def _is_named_assignment(node: ast.stmt, name: str) -> bool:
    return isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name


def _is_single_import(node: ast.stmt, name: str, asname: str | None) -> bool:
    return isinstance(node, ast.Import) and len(node.names) == 1 and node.names[0].name == name and node.names[0].asname == asname


class _AdjpriceSeamRewriter(ast.NodeTransformer):
    def __init__(self) -> None:
        self.read_count = 0
        self.factor_call_count = 0

    def visit_Call(self, node: ast.Call) -> ast.expr:
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "pd" and node.func.attr == "read_parquet":
            self.read_count += 1
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="_read_frozen_parquet", ctx=ast.Load()),
                    args=[ast.Name(id="raw_frame", ctx=ast.Load())],
                    keywords=[ast.keyword(arg="columns", value=ast.Name(id="cols", ctx=ast.Load()))],
                ),
                node,
            )
        if isinstance(node.func, ast.Name) and node.func.id == "_factors" and not node.args and not node.keywords:
            self.factor_call_count += 1
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="_factors", ctx=ast.Load()),
                    args=[ast.Name(id="actions_frame", ctx=ast.Load()), ast.Name(id="cutoff", ctx=ast.Load())],
                    keywords=[],
                ),
                node,
            )
        self.generic_visit(node)
        return node


class _CutoffFilterRewriter(ast.NodeTransformer):
    def __init__(self) -> None:
        self.replacements = 0

    def visit_Name(self, node: ast.Name) -> ast.expr:
        if node.id == "CUTOFF" and isinstance(node.ctx, ast.Load):
            self.replacements += 1
            return ast.copy_location(ast.Name(id="cutoff", ctx=ast.Load()), node)
        return node


def _read_frozen_parquet(frame: pd.DataFrame, *, columns: list[str]) -> pd.DataFrame:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"raw frame missing source columns: {', '.join(missing)}")
    return frame.loc[:, columns].copy()


def _strict_iso_date(value: Any, field: str) -> dt.date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO YYYY-MM-DD string")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use canonical ISO YYYY-MM-DD: {value!r}")
    return parsed


def _validate_price_inputs(
    raw_frame: pd.DataFrame,
    actions_frame: pd.DataFrame,
    code: str,
    cutoff: str,
) -> dict[str, Any]:
    _strict_iso_date(cutoff, "cutoff")
    if not isinstance(code, str) or not code:
        raise ValueError("code must be a non-empty string")
    if not isinstance(raw_frame, pd.DataFrame):
        raise TypeError("raw_frame must be a pandas DataFrame")
    if not isinstance(actions_frame, pd.DataFrame):
        raise TypeError("actions_frame must be a pandas DataFrame")
    missing_raw = [column for column in RAW_COLUMNS if column not in raw_frame.columns]
    if missing_raw:
        raise ValueError(f"raw frame missing source columns: {', '.join(missing_raw)}")
    missing_actions = [column for column in ACTION_COLUMNS if column not in actions_frame.columns]
    if missing_actions:
        raise ValueError(f"actions frame missing source columns: {', '.join(missing_actions)}")

    bars = raw_frame.loc[:, RAW_COLUMNS].dropna(subset=list(OHLC_COLUMNS))
    if bars.empty:
        raise ValueError("adjprice.load cannot prepare an empty frame: its source TR calculation reads row zero")
    try:
        ohlc = bars.loc[:, list(OHLC_COLUMNS)].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("raw OHLC values must be numeric") from exc
    if not np.isfinite(ohlc).all():
        raise ValueError("raw OHLC values must be finite after the source missing-OHLC drop")
    if (ohlc <= 0).any():
        raise ValueError("raw OHLC prices must be positive")

    date_tokens = bars["asof_date"].astype(str).str[:10].tolist()
    for token in date_tokens:
        _strict_iso_date(token, "asof_date")
    if len(set(date_tokens)) != len(date_tokens):
        raise ValueError("raw frame contains duplicate asof_date rows")
    if any(left >= right for left, right in zip(date_tokens, date_tokens[1:])):
        raise ValueError("raw frame asof_date rows must be strictly chronological")

    actions = actions_frame.copy(deep=True).reset_index(drop=True)
    factors = cast(pd.Series, pd.to_numeric(actions["price_factor"], errors="coerce"))
    source_excluded = actions["ex_date"].isna() | factors.isna() | factors.le(0)
    excluded_invalid_action_count = int(source_excluded.sum())
    try:
        source_mask = (actions["ex_date"].notna() & factors.gt(0) & (actions["ex_date"] <= cutoff)).fillna(False)
    except TypeError as exc:
        raise ValueError("actions ex_date values must be source-compatible ISO date strings") from exc

    eligible = actions.loc[source_mask, ["code", "ex_date"]].copy()
    eligible["code"] = eligible["code"].astype(str)
    first_date = date_tokens[0]
    applicable = eligible.loc[(eligible["code"] == code) & (eligible["ex_date"] > first_date)].copy()
    for value in applicable["ex_date"]:
        _strict_iso_date(value, "applied action ex_date")

    applicable_factors = factors.loc[applicable.index].to_numpy(dtype=float)
    if not np.isfinite(applicable_factors).all():
        raise ValueError("applied action price_factor values must be finite")
    if (applicable_factors <= 0).any():
        raise ValueError("applied action price_factor values must be positive")

    duplicate_keys = actions.loc[applicable.index, ["code", "ex_date"]].copy()
    duplicate_keys["code"] = duplicate_keys["code"].astype(str)
    duplicated = duplicate_keys.duplicated(["code", "ex_date"], keep=False)
    if duplicated.any():
        duplicate = duplicate_keys.loc[duplicated].iloc[0]
        raise ValueError(f"duplicate applied action code/ex_date: {duplicate['code']} {duplicate['ex_date']}")

    return {
        "input_rows": int(len(raw_frame)),
        "used_rows": int(len(bars)),
        "dropped_missing_ohlc_rows": int(len(raw_frame) - len(bars)),
        "excluded_invalid_action_rows": excluded_invalid_action_count,
        "applied_action_rows": int(len(applicable)),
        "applied_action_dates": tuple(applicable["ex_date"].tolist()),
    }


def _compile_adjprice(text: str) -> PriceLoader:
    tree = ast.parse(text)
    _require_imports(
        tree,
        [
            ("from", "__future__", 0, (("annotations", None),)),
            ("import", (("sqlite3", None),)),
            ("from", "functools", 0, (("lru_cache", None),)),
            ("from", "pathlib", 0, (("Path", None),)),
            ("import", (("numpy", "np"),)),
            ("import", (("pandas", "pd"),)),
        ],
        "adjprice",
    )
    factors_function = _one_function(tree, "_factors", "adjprice")
    load_function = _one_function(tree, "load", "adjprice")
    if len(factors_function.body) < 3 or not _is_named_assignment(factors_function.body[0], "con"):
        raise ValueError("unexpected frozen adjprice._factors I/O seam")
    if not isinstance(factors_function.body[1], ast.Try):
        raise ValueError("unexpected frozen adjprice._factors query seam")
    factors_function.decorator_list = []
    factors_function.args.args = [ast.arg(arg="actions_frame"), ast.arg(arg="cutoff")]
    factors_function.args.defaults = [ast.Name(id="CUTOFF", ctx=ast.Load())]
    factors_function.body[:2] = [ast.parse("f = actions_frame.copy()").body[0]]
    cutoff_rewriter = _CutoffFilterRewriter()
    factors_function.body = [cutoff_rewriter.visit(node) for node in factors_function.body]
    if cutoff_rewriter.replacements != 1:
        raise ValueError("unexpected frozen adjprice._factors cutoff seam")

    load_function.args.args = [
        *load_function.args.args,
        ast.arg(arg="raw_frame"),
        ast.arg(arg="actions_frame"),
        ast.arg(arg="cutoff"),
    ]
    load_function.args.defaults = [ast.Name(id="CUTOFF", ctx=ast.Load())]
    rewriter = _AdjpriceSeamRewriter()
    rewriter.visit(load_function)
    if rewriter.read_count != 1 or rewriter.factor_call_count != 1:
        raise ValueError("unexpected frozen adjprice.load I/O seams")

    retained: list[ast.stmt] = []
    for node in tree.body:
        if _is_single_import(node, "numpy", "np"):
            retained.append(node)
        elif _is_single_import(node, "pandas", "pd"):
            retained.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
            retained.append(node)
        elif _is_named_assignment(node, "CUTOFF"):
            retained.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            retained.append(node)
        elif node is factors_function or node is load_function:
            retained.append(node)
    tree.body = retained
    ast.fix_missing_locations(tree)
    namespace: dict[str, Any] = {"_read_frozen_parquet": _read_frozen_parquet}
    loaded = _compile(tree, "adjprice.py", namespace)

    def prepare(
        raw_frame: pd.DataFrame,
        actions_frame: pd.DataFrame,
        code: str,
        cutoff: str = DEFAULT_CUTOFF,
    ) -> pd.DataFrame:
        metadata = _validate_price_inputs(raw_frame, actions_frame, code, cutoff)
        result = loaded["load"](code, raw_frame, actions_frame, cutoff)
        generated = result[["Open", "High", "Low", "Close", "div_factor"]].to_numpy(dtype=float)
        if not np.isfinite(generated).all():
            raise ValueError("adjusted OHLC and div_factor output must be finite")
        atr = result["atr14_pct"].to_numpy(dtype=float)
        if np.isinf(atr).any():
            raise ValueError("recomputed Wilder ATR contains an infinite value")
        metadata.update({"code": code, "cutoff": cutoff, "source": "adjprice.py"})
        result.attrs["preparation_metadata"] = metadata
        LOGGER.info(
            "Prepared v4 prices code=%s rows=%d dropped_missing_ohlc=%d applied_actions=%d",
            code,
            metadata["used_rows"],
            metadata["dropped_missing_ohlc_rows"],
            metadata["applied_action_rows"],
        )
        return result

    return prepare


def load_v4_components(
    texts: Mapping[str, str],
) -> tuple[Callable[..., Any], PivotFunction, float, PriceLoader]:
    """Execute registered source after replacing only the declared import and I/O seams."""
    detect_tree = ast.parse(texts["detect.py"])
    pivot_nodes: list[ast.stmt] = [node for node in detect_tree.body if isinstance(node, ast.FunctionDef) and node.name == "pivots_atr"]
    if len(pivot_nodes) != 1:
        raise ValueError("frozen detect.py must declare one pivots_atr function")
    pivot_namespace: dict[str, Any] = {"np": np}
    _compile(ast.Module(body=pivot_nodes, type_ignores=[]), "detect.py", pivot_namespace)
    pivots = cast(PivotFunction, pivot_namespace["pivots_atr"])

    bigrange_tree = ast.parse(texts["bigrange_v4.py"])
    _require_imports(
        bigrange_tree,
        [
            ("from", "__future__", 0, (("annotations", None),)),
            ("import", (("numpy", "np"),)),
            ("from", "detect", 0, (("pivots_atr", None),)),
        ],
        "bigrange_v4",
    )
    if sum(isinstance(node, ast.FunctionDef) for node in bigrange_tree.body) != 1:
        raise ValueError("frozen bigrange_v4.py has unexpected top-level functions")
    bigrange_tree.body = [node for node in bigrange_tree.body if not (isinstance(node, ast.ImportFrom) and node.module == "detect")]
    bigrange_namespace: dict[str, Any] = {"pivots_atr": pivots}
    _compile(bigrange_tree, "bigrange_v4.py", bigrange_namespace)
    bigrange_module = types.ModuleType("bigrange_v4")
    bigrange_module.__dict__.update(bigrange_namespace)

    rule_tree = ast.parse(texts[f"{RULE_ID}.py"])
    _require_imports(
        rule_tree,
        [
            ("from", "__future__", 0, (("annotations", None),)),
            ("import", (("numpy", "np"),)),
            ("import", (("pandas", "pd"),)),
            ("import", (("bigrange_v4", None),)),
            ("from", "detect", 0, (("pivots_atr", None),)),
        ],
        RULE_ID,
    )
    rule_tree.body = [
        node
        for node in rule_tree.body
        if not (_is_single_import(node, "bigrange_v4", None)) and not (isinstance(node, ast.ImportFrom) and node.module == "detect")
    ]
    rule_namespace: dict[str, Any] = {
        "bigrange_v4": bigrange_module,
        "pivots_atr": pivots,
    }
    _compile(rule_tree, f"{RULE_ID}.py", rule_namespace)
    prepare_prices = _compile_adjprice(texts["adjprice.py"])
    return rule_namespace["detect"], pivots, float(rule_namespace["K"]), prepare_prices


def prepare_v4_prices(
    raw_frame: pd.DataFrame,
    actions_frame: pd.DataFrame,
    code: str,
    cutoff: str = DEFAULT_CUTOFF,
    *,
    sources: Path,
) -> pd.DataFrame:
    """Prepare adjusted bars using explicit frames and the registered frozen source archive."""
    from research_core.hhhl_rule_source import load_source_texts

    texts = load_source_texts(Path(sources), RULE_ID)
    _, _, _, prepare_prices = load_v4_components(texts)
    return prepare_prices(raw_frame, actions_frame, code, cutoff)
