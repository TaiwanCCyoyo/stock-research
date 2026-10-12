"""Physical caller snapshots into the existing fresh-source worker boundary.

Scratch inputs are retained under this implementation checkout's .tmp. These
are snapshots of caller-provided frames, never links or copies of shared stores.
The existing cache SourceFinder owns fresh imports and source-byte binding.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core import cache_execution
from research_core.artifact_store import file_digest
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DataRoots, _checked_path

LOGGER = logging.getLogger(__name__)
SHA256 = re.compile(r"[0-9a-f]{64}")


def _authorize(calculation_authorized: bool) -> None:
    if calculation_authorized is not True:
        raise PermissionError("explicit calculation authorization required")


def _scratch() -> Path:
    implementation = _checked_path(Path(__file__).absolute().parents[1])
    directory = _checked_path(implementation / ".tmp" / "research-data-execution" / str(uuid.uuid4()))
    directory.mkdir(parents=True, exist_ok=False)
    return _checked_path(directory)


def _write_frame(directory: Path, filename: str, frame: pd.DataFrame) -> dict[str, str]:
    path = _checked_path(directory / filename)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=True)
    _checked_path(path)
    return {"path": str(path), "sha256": file_digest(path)}


def _roots(catalog: DataCatalog) -> dict[str, str]:
    return {"primary": str(catalog.roots.primary), "data": str(catalog.roots.data)}


def execute_features(
    catalog: DataCatalog,
    prepared: dict[str, pd.DataFrame],
    features: Iterable[str],
    factor_ids: dict[str, str],
    price_basis: str,
    base: dict[str, Any] | None,
    calculation_authorized: bool,
) -> dict[str, Any]:
    """Snapshot prepared caller frames and calculate in a fresh interpreter."""
    _authorize(calculation_authorized)
    if isinstance(features, (str, bytes)):
        raise TypeError("features must be an iterable of names, not a string")
    names = list(features)
    directory = _scratch()
    inputs = {code: _write_frame(directory, f"stock-{number}.parquet", frame) for number, (code, frame) in enumerate(prepared.items())}
    payload = {
        "kind": "features",
        "roots": _roots(catalog),
        "scratch": str(directory),
        "inputs": inputs,
        "features": names,
        "factor_ids": factor_ids,
        "price_basis": price_basis,
        "base": base,
        "calculation_authorized": True,
    }
    LOGGER.debug("Executing fresh research features stocks=%d scratch=%s", len(inputs), directory)
    return cache_execution.execute("research-data", payload)


def execute_forward(
    catalog: DataCatalog,
    code: str,
    dates: pd.DatetimeIndex,
    closes: np.ndarray,
    price_basis: str,
    factor_id: str,
    horizon: int | None,
    context_layer: str | None,
    base: dict[str, Any] | None,
    calculation_authorized: bool,
) -> dict[str, Any]:
    """Snapshot caller close/calendar values before fresh forward execution."""
    _authorize(calculation_authorized)
    frame = pd.DataFrame({"Close": closes}, index=dates)
    directory = _scratch()
    payload = {
        "kind": "forward",
        "roots": _roots(catalog),
        "scratch": str(directory),
        "input": _write_frame(directory, "forward.parquet", frame),
        "code": code,
        "price_basis": price_basis,
        "factor_id": factor_id,
        "horizon": horizon,
        "context_layer": context_layer,
        "base": base,
        "calculation_authorized": True,
    }
    LOGGER.debug("Executing fresh research forward rows=%d scratch=%s", len(frame), directory)
    return cache_execution.execute("research-data", payload)


def _verify_pin(pin: dict[str, Any], directory: Path) -> Path:
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"}:
        raise ValueError("invalid frozen research input pin")
    if not isinstance(pin["path"], str) or not isinstance(pin["sha256"], str) or not SHA256.fullmatch(pin["sha256"]):
        raise ValueError("invalid frozen research input pin types")
    supplied = Path(pin["path"])
    if not supplied.is_absolute():
        raise ValueError("frozen input path must be absolute")
    path = _checked_path(supplied)
    if path.parent != directory or path.suffix != ".parquet":
        raise ValueError("frozen input must be directly inside execution scratch")
    if file_digest(path) != pin["sha256"]:
        raise ValueError("frozen research input hash mismatch")
    return path


def _read_frame(pin: dict[str, Any], directory: Path) -> pd.DataFrame:
    path = _verify_pin(pin, directory)
    frame = pd.read_parquet(path)
    _verify_pin(pin, directory)
    return frame


def _execute_in_process(payload: dict[str, Any]) -> dict[str, Any]:
    """Fresh worker dispatch; frozen input hashes are checked around all use."""
    from research_core import research_data_incremental as incremental

    _authorize(payload["calculation_authorized"])
    implementation = _checked_path(Path(__file__).absolute().parents[1])
    directory = _checked_path(Path(payload["scratch"]))
    if directory.parent != implementation / ".tmp" / "research-data-execution":
        raise ValueError("execution scratch belongs to a different checkout")
    try:
        identifier = uuid.UUID(directory.name)
    except ValueError as error:
        raise ValueError("invalid execution scratch identifier") from error
    if str(identifier) != directory.name or not directory.is_dir():
        raise ValueError("invalid execution scratch directory")
    roots = DataRoots(primary=Path(payload["roots"]["primary"]), data=Path(payload["roots"]["data"]))
    catalog = DataCatalog(roots)
    pins: list[dict[str, Any]]
    if payload["kind"] == "features":
        pins = list(payload["inputs"].values())
        prepared = {code: _read_frame(pin, directory) for code, pin in payload["inputs"].items()}
        for pin in pins:
            _verify_pin(pin, directory)
        receipt = incremental._build_incremental_features_in_process(
            catalog,
            prepared,
            payload["features"],
            factor_ids=payload["factor_ids"],
            price_basis=payload["price_basis"],
            base=payload["base"],
            calculation_authorized=True,
        )
    elif payload["kind"] == "forward":
        pins = [payload["input"]]
        frame = _read_frame(payload["input"], directory)
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.columns.tolist() != ["Close"]:
            raise ValueError("frozen forward frame requires Close and a DatetimeIndex")
        _verify_pin(payload["input"], directory)
        receipt = incremental._publish_forward_series_in_process(
            catalog,
            payload["code"],
            frame.index,
            frame["Close"].to_numpy(),
            price_basis=payload["price_basis"],
            factor_id=payload["factor_id"],
            horizon=payload["horizon"],
            context_layer=payload["context_layer"],
            base=payload["base"],
            calculation_authorized=True,
        )
    else:
        raise ValueError("unknown research-data execution kind")
    for pin in pins:
        _verify_pin(pin, directory)
    if not isinstance(receipt, dict):
        raise ValueError("research-data execution did not return a receipt")
    LOGGER.debug("Finished fresh research-data kind=%s frozen_inputs=%d", payload["kind"], len(pins))
    return receipt
