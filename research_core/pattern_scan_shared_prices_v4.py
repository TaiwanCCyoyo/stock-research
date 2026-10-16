"""Pinned shared as-of prices with the original PR17 calendar and frame shape."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core import maintained_adjusted_daily as maintained
from research_core.artifact_store import object_digest
from research_core.research_data_paths import _artifact_name, checked_path

LOGGER = logging.getLogger(__name__)
SCHEMA = "pattern-scan-shared-prices.v4"
BASIS = "reference_factor_adjusted"
DEFINITION = "price-basis.v2"
CUTOFF = "2026-10-12"
START = "2010-01-04"
SESSIONS = 4110
SHA256 = re.compile(r"[0-9a-f]{64}")
INPUT_ROLES = ("price_daily", "corporate_actions")


def _root(root: Path) -> Path:
    if not root.is_absolute():
        raise ValueError("explicit absolute external shared root required")
    root = checked_path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"shared root unavailable: {root}")
    code_root = Path(__file__).absolute().parent.parent
    if root.is_relative_to(code_root) or code_root.is_relative_to(root):
        raise ValueError("shared root must be outside the code checkout")
    if any((ancestor / ".git").exists() for ancestor in (root, *root.parents)):
        raise ValueError("shared root must be outside every checkout/worktree")
    return root


def _calendar(calendar: pd.DatetimeIndex) -> dict[str, Any]:
    if (
        not isinstance(calendar, pd.DatetimeIndex)
        or calendar.dtype != np.dtype("datetime64[ns]")
        or calendar.hasnans
        or calendar.tz is not None
        or len(calendar) != SESSIONS
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or any(day != day.normalize() for day in calendar)
        or calendar[0] != pd.Timestamp(START)
        or calendar[-1] != pd.Timestamp(CUTOFF)
        or (calendar.name is not None and not isinstance(calendar.name, str))
    ):
        raise ValueError("shared prices require the approved 4110-session naive daily calendar")
    dates = calendar.strftime("%Y-%m-%d").tolist()
    return {"dates": dates, "sha256": object_digest(dates), "sessions": len(dates), "name": calendar.name}


def _descriptor(directory: Path, metadata: dict[str, Any], filename: str) -> dict[str, Any]:
    if (
        metadata.get("file") != filename
        or type(metadata.get("bytes")) is not int
        or metadata["bytes"] < 0
        or not isinstance(metadata.get("sha256"), str)
        or SHA256.fullmatch(metadata["sha256"]) is None
    ):
        raise ValueError("invalid shared as-of input descriptor")
    path = checked_path(directory / filename)
    if not path.is_file() or path.stat().st_size != metadata["bytes"]:
        raise ValueError(f"shared as-of input missing or size differs: {path}")
    # The maintained reader verifies these payload hashes once per physical
    # file identity per process. Binding metadata must not duplicate that scan.
    return {"path": str(path), "bytes": metadata["bytes"], "sha256": metadata["sha256"]}


def make_price_reference(
    root: Path,
    generation: str,
    calendar: pd.DatetimeIndex,
    *,
    expected_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind one external generation; never choose current or build a fallback."""
    root = _root(root)
    calendar_record = _calendar(calendar)
    if not isinstance(generation, str) or not generation or generation != generation.strip() or generation.startswith(".") or "/" in _artifact_name(generation):
        raise ValueError("one explicit shared generation required")
    try:
        directory = checked_path(root / "derived" / maintained.FAMILY / "generations" / generation)
        checked_path(directory / "status.json")
        status = maintained.current_generation(root, generation=generation)
        if (
            status.get("schema") != maintained.SCHEMA
            or status.get("family") != maintained.FAMILY
            or status.get("generation") != generation
            or checked_path(Path(status["path"])) != directory
            or not isinstance(status.get("status_sha256"), str)
            or SHA256.fullmatch(status["status_sha256"]) is None
            or status["source_policy"]["kept"] != "official"
            or status["definition"]["prices"] != DEFINITION
        ):
            raise ValueError("shared generation definition/source/status identity differs")
        asof = cast(pd.Timestamp, pd.Timestamp(status["asof"]))
        if pd.isna(asof) or asof.tzinfo is not None or asof != asof.normalize() or asof < pd.Timestamp(CUTOFF):
            raise ValueError("shared generation does not cover the study cutoff")
        actual = status["input_fingerprint"]["inputs"]
        fingerprint = {role: actual[role] for role in INPUT_ROLES}
        if any(not isinstance(entry, dict) or not entry for entry in fingerprint.values()):
            raise ValueError("shared generation requires price/actions input fingerprints")
        if expected_fingerprint is not None:
            expected = {role: expected_fingerprint["inputs"][role] for role in INPUT_ROLES}
            if object_digest(expected) != object_digest(fingerprint):
                raise ValueError("shared price/actions input fingerprints differ")
        inputs = {
            "raw": _descriptor(directory, status["bases"]["raw"], "raw.parquet"),
            "actions": _descriptor(directory, status["as_of_inputs"]["actions"], "actions.parquet"),
            "calendar": _descriptor(directory, status["as_of_inputs"]["calendar"], "calendar.parquet"),
        }
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"incomplete shared generation metadata: {error}") from error
    reference = {
        "schema": SCHEMA,
        "root": str(root),
        "generation": generation,
        "status_sha256": status["status_sha256"],
        "basis": BASIS,
        "definition": DEFINITION,
        "source_policy": "official",
        "cutoff": CUTOFF,
        "calendar": calendar_record,
        "inputs": inputs,
        "input_fingerprint": fingerprint,
    }
    LOGGER.debug("Bound shared PR17 prices generation=%s status=%s calendar=%s", generation, reference["status_sha256"], calendar_record["sha256"])
    return reference


def read_reference_frame(
    reference: dict[str, Any],
    code: str,
    *,
    stock_part: bool = False,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Read exact as-of values, restoring index/stock metadata without coercion."""
    if not isinstance(code, str) or not code or code != code.strip():
        raise ValueError("original nonblank stock code string required")
    if type(stock_part) is not bool:
        raise ValueError("stock_part must be boolean")
    try:
        calendar_record = reference["calendar"]
        dates = calendar_record["dates"]
        if not isinstance(dates, list) or any(not isinstance(day, str) for day in dates):
            raise ValueError("invalid pinned calendar dates")
        calendar = pd.DatetimeIndex(pd.to_datetime(dates), name=calendar_record["name"])
        if _calendar(calendar) != calendar_record:
            raise ValueError("pinned calendar identity differs")
        current = make_price_reference(
            Path(reference["root"]),
            reference["generation"],
            calendar,
            expected_fingerprint={"inputs": reference["input_fingerprint"]},
        )
        if object_digest(current) != object_digest(reference):
            raise ValueError("pinned shared generation/reference changed")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"invalid shared price reference: {error}") from error
    frame, record = maintained.read_adjusted_daily(
        BASIS, root=Path(reference["root"]), generation=reference["generation"], as_of=CUTOFF, calendar=calendar, codes=[code]
    )
    expected_record = {
        "family": maintained.FAMILY,
        "generation": reference["generation"],
        "status_sha256": reference["status_sha256"],
        "basis": BASIS,
        "definition": DEFINITION,
        "as_of": CUTOFF,
        "actions_sha256": reference["inputs"]["actions"]["sha256"],
        "codes": 1,
        "calendar": {"source": "caller", "sessions": SESSIONS, "first": START, "last": CUTOFF, "sha256": calendar_record["sha256"]},
    }
    if any(object_digest(record.get(key)) != object_digest(value) for key, value in expected_record.items()):
        raise ValueError("shared as-of read returned different pinned identities")
    if not frame.columns.is_unique or frame.columns.tolist() != maintained.ARROW_SCHEMA.names:
        raise ValueError("shared as-of read requires the full ordered price schema")
    codes = cast(pd.Series, frame["Code"])
    if len(frame) != SESSIONS or not bool(codes.map(lambda value: isinstance(value, str) and value == code).all()):
        raise ValueError("shared as-of read returned different stock identities or row count")
    observed = cast(pd.Series, frame["Date"])
    if observed.dtype != calendar.dtype or not pd.DatetimeIndex(observed).equals(calendar):
        raise ValueError("shared as-of read changed calendar date order/dtype")
    prices = frame.drop(columns=["Code", "Date"]).copy()
    prices.index = calendar
    if stock_part:
        prices = as_stock_prices(prices, code)
    if columns is not None:
        if isinstance(columns, str) or len(set(columns)) != len(columns) or any(name not in prices.columns for name in columns):
            raise ValueError("requested shared price columns must be unique known columns")
        prices = cast(pd.DataFrame, prices.loc[:, list(columns)])
    LOGGER.debug("Read pinned PR17 prices code=%s generation=%s rows=%d stock_part=%s", code, reference["generation"], len(prices), stock_part)
    return prices


def as_stock_prices(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    """Append stock_phase's three metadata columns without another shared read."""
    if not isinstance(code, str) or not code or code != code.strip():
        raise ValueError("original nonblank stock code string required")
    if not frame.columns.is_unique or frame.columns.tolist() != maintained.ARROW_SCHEMA.names[2:]:
        raise ValueError("stock prices require the full ordered price schema")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("stock prices require the approved calendar index")
    _calendar(frame.index)
    result = frame.copy()
    result["security_id"] = f"TW:{code}"
    result["calendar_index"] = np.arange(len(frame), dtype=np.int64)
    result["asof_date"] = np.asarray(frame.index.strftime("%Y-%m-%d"), dtype=object)
    return result
