"""Verified stock-part barrier and immutable full-period shared publication."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, read_json, verify_files, write_json
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_context_v1 import build_context
from research_core.pattern_scan_cross_section_v1 import cross_section, recent_pattern_values
from research_core.pattern_scan_execution_v1 import verify_source
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_file_bundle_v1 import publish_file_bundle
from research_core.research_data_paths import DataRoots, _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)
SKINNY_COLUMNS = ("security_id", "t0", "calendar_index", "base_eligible", "ret120", "turnover20", "industry_ref", "is_cnh")
GLOBAL_COLUMNS = ("H", "H_applicable", "H_unknown_reason", "K3", "K3_applicable", "K3_unknown_reason", "J", "J_unknown_reason")
FIELDS = {
    "universe": ("universe",),
    "prices": ("prices",),
    "pivots": ("pivots",),
    "features": ("indicators", "common_values"),
    "patterns": ("pattern_states", "detector_unknowns", "raw_events", "cohort_events", "controls", "h1_source_events", "control_unknowns", "control_pairs"),
    "labels": ("base_labels",),
}


def verified_parts(results: list[dict[str, Any]], *, source: dict[str, Any], input_id: str) -> dict[str, Path]:
    """Verify the whole declared stock barrier before any pooled calculation."""
    verify_source(source)
    if not results or len({row["code"] for row in results}) != len(results):
        raise ValueError("nonempty unique stock barrier required")
    parts: dict[str, Path] = {}
    for result in sorted(results, key=lambda row: row["code"]):
        directory = _checked_path(Path(result["output_path"]))
        current = read_json(directory / "receipt.json")
        if current != result or current.get("complete") is not True or current.get("source_id") != source["source_id"] or current.get("input_id") != input_id:
            raise ValueError("stock barrier receipt/source/input differs")
        verify_files(directory, current["artifacts"])
        parts[result["code"]] = directory
    return parts


def build_barrier(parts: dict[str, Path], benchmark: pd.DataFrame, output: Path) -> dict[str, Any]:
    """Build ranks after all stocks, causal PAT, and separately timed context."""
    output = _checked_path(output)
    destination = output
    before = resource_sample()
    codes = tuple(sorted(parts))
    identities = set()
    parent_pins: dict[str, str] = {}
    for code, directory in parts.items():
        part_receipt = read_json(_checked_path(directory / "receipt.json"))
        if part_receipt.get("complete") is not True:
            raise ValueError("incomplete stock part before global barrier")
        verify_files(directory, part_receipt["artifacts"])
        identities.add((part_receipt["source_id"], part_receipt["input_id"]))
        parent_pins[code] = file_digest(directory / "receipt.json")
    if len(identities) != 1:
        raise ValueError("global barrier requires one fixed source and input")
    source_id, input_id = next(iter(identities))
    calendar = cast(pd.DatetimeIndex, benchmark.index)

    # Float hex retains the exact supplied binary value, including ULPs; this
    # logical benchmark pin supplements the original fixed raw input identity.
    def cell(value: Any) -> Any:
        if isinstance(value, (float, np.floating)):
            return float(value).hex()
        if isinstance(value, np.generic):
            return value.item()
        return None if pd.isna(value) else value

    identity = {
        "source_id": source_id,
        "input_id": input_id,
        "stock_receipts": parent_pins,
        "benchmark": object_digest({
            "dates": calendar.strftime("%Y-%m-%d").tolist(),
            "columns": list(benchmark.columns),
            "rows": [[cell(value) for value in row] for row in benchmark.itertuples(index=False, name=None)],
        }),
    }
    if destination.exists():
        saved = read_json(destination / "receipt.json")
        if saved.get("identity") != identity or saved.get("complete") is not True:
            raise ValueError("existing global barrier identity differs or incomplete")
        verify_barrier(saved)
        return saved
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = _checked_path(destination.parent / f".staging-{destination.name}-{uuid.uuid4().hex}")
    output.mkdir()
    expected = tuple(f"TW:{code}" for code in codes)
    pieces = [read_frame(parts[code] / "common_values.parquet", columns=list(SKINNY_COLUMNS)) for code in codes]
    skinny = pd.concat(pieces, ignore_index=True)
    del pieces
    # Repeated identities are categorical to bound the all-stock barrier memory.
    for name in ("security_id", "t0", "industry_ref"):
        skinny[name] = skinny[name].astype("category")
    context = build_context(skinny, benchmark, expected)
    cross = cross_section(skinny, expected_security_ids=expected)
    indices = cross.groupby("security_id", observed=True, sort=False).indices
    n = len(benchmark)
    union: dict[str, np.ndarray] = {pattern: np.empty((len(codes), n), dtype=np.int8) for pattern in PATTERNS}
    closes = pd.DataFrame(index=benchmark.index, columns=pd.Index(expected), dtype=float)
    jump_flags = pd.DataFrame(index=benchmark.index, columns=pd.Index(expected), dtype=bool)
    for ordinal, code in enumerate(codes):
        states = read_frame(parts[code] / "pattern_states.parquet")
        prices = read_frame(parts[code] / "prices.parquet", columns=["Close", "quality_reason"])
        if not states.index.equals(benchmark.index) or not prices.index.equals(benchmark.index):
            raise ValueError("stock part calendar differs at full barrier")
        for pattern in PATTERNS:
            union[pattern][ordinal] = states[pattern].to_numpy(dtype=np.int8)
        closes[f"TW:{code}"] = prices["Close"].to_numpy(dtype=float)
        jump_flags[f"TW:{code}"] = (
            prices["quality_reason"]
            .fillna("")
            .astype(str)
            .str.split("|")
            .map(lambda tokens: bool(set(tokens) & {"unexplained_jump", "unexplained_adjusted_jump"}))
            .to_numpy(dtype=bool)
        )
    # One call supplies every family's same causal window. Its own family is
    # excluded by event_conditions, so compute H1 and then add its omitted H1.
    recent = dict(recent_pattern_values(union, "H1"))
    recent["PAT_other_H1"] = recent_pattern_values(union, "B1")["PAT_other_H1"]
    files: dict[str, Path] = {}
    for ordinal, code in enumerate(codes):
        frame = cross.iloc[indices[f"TW:{code}"]].sort_values("calendar_index").loc[:, list(GLOBAL_COLUMNS)].copy()
        frame.index = benchmark.index
        frame["security_id"] = f"TW:{code}"
        frame["t0"] = calendar.strftime("%Y-%m-%d")
        frame["calendar_index"] = np.arange(n)
        frame["MKT"] = context["MKT"].to_numpy()
        frame["MKT_unknown_reason"] = context["MKT_unknown_reason"].to_numpy()
        for name, values in recent.items():
            frame[name] = values[ordinal]
        path = output / f"{object_digest(code)}.parquet"
        with path.open("xb") as stream:
            frame.to_parquet(stream)
        files[code] = path
    del skinny, cross, union, recent
    for name, frame in (("context", context), ("close_matrix", closes), ("jump_matrix", jump_flags), ("benchmark", benchmark)):
        with (output / f"{name}.parquet").open("xb") as stream:
            frame.to_parquet(stream)
    receipt = {
        "schema": "pattern-scan-barrier.v1",
        "complete": True,
        "identity": identity,
        "source_id": source_id,
        "input_id": input_id,
        "stock_ids": list(expected),
        "calendar": calendar.strftime("%Y-%m-%d").tolist(),
        "global_files": {code: {"path": str(destination / path.name), "sha256": file_digest(path)} for code, path in files.items()},
        "context_coverage": context.attrs["coverage"],
        "measurements": [phase_receipt("global_rank_pattern_context", before, resource_sample())],
    }
    receipt["artifacts"] = [describe_file(output, path) for path in sorted(output.glob("*.parquet"))]
    receipt["sidecars"] = {
        name: {"path": str(destination / f"{name}.parquet"), "sha256": file_digest(output / f"{name}.parquet")}
        for name in ("context", "close_matrix", "jump_matrix", "benchmark")
    }
    verify_files(output, receipt["artifacts"])
    for code, directory in parts.items():
        if file_digest(directory / "receipt.json") != parent_pins[code]:
            raise ValueError("stock ancestor changed during global calculation")
        verify_files(directory, read_json(directory / "receipt.json")["artifacts"])
    write_json(output / "receipt.json", receipt)
    publish_noreplace(output, destination)
    LOGGER.info("Completed global scan barrier stocks=%d sessions=%d", len(codes), n)
    return receipt


def verify_barrier(receipt: dict[str, Any]) -> Path:
    """Every global table, including all four sidecars, is a sealed ancestor."""
    if receipt.get("schema") != "pattern-scan-barrier.v1" or receipt.get("complete") is not True:
        raise ValueError("complete sealed global barrier required")
    directory = _checked_path(Path(next(iter(receipt["global_files"].values()))["path"]).parent)
    if read_json(directory / "receipt.json") != receipt:
        raise ValueError("global barrier receipt identity changed")
    if set(receipt.get("sidecars", {})) != {"context", "close_matrix", "jump_matrix", "benchmark"}:
        raise ValueError("all sealed global sidecars required")
    for record in [*receipt["global_files"].values(), *receipt["sidecars"].values()]:
        path = _checked_path(Path(record["path"]))
        if path.parent != directory or file_digest(path) != record["sha256"]:
            raise ValueError("global barrier payload path or identity changed")
    verify_files(directory, receipt["artifacts"])
    return directory


def metadata(kind: str, source: dict[str, Any], input_id: str, calendar: pd.DatetimeIndex, *, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Discovery identity for one fixed full-period version; no latest aliases."""
    return {
        "data_id": f"pattern-scan-full-2010-v1-{kind}",
        "kind": kind,
        "definition_version": "pattern-scan.v1",
        "parameters": {
            "cutoff": "2026-10-12",
            "horizons": [126, 252],
            "price_basis": "price-basis.v2/reference_factor_adjusted",
            **({"code": source["code"], "execution_policy": "live-input-fingerprint.v2"} if source.get("schema") == "pattern-scan-source.git.v2" else {}),
        },
        "inputs": {"fixed_input_id": input_id, "source_id": source["source_id"], "runtime": source["runtime"]},
        "coverage": {
            "scope": "fixed ordinary-reference universe on full supplied 2010 calendar; current metadata vintage",
            "raw_input_period": {"start": calendar[0].strftime("%Y-%m-%d"), "end": calendar[-1].strftime("%Y-%m-%d"), "reason": None},
            "valid_indicator_period": {
                "start": None,
                "end": None,
                "reason": "Per-security, per-feature known status in payload; no single common indicator start",
            },
            "complete_label_period": {
                "start": calendar[0].strftime("%Y-%m-%d") if len(calendar) > 252 else None,
                "end": calendar[-253].strftime("%Y-%m-%d") if len(calendar) > 252 else None,
                "reason": None if len(calendar) > 252 else "No H252 complete-calendar anchor",
            },
            **(coverage or {}),
        },
        "status": "complete",
        "limitations": [
            "Retrospective fixed-vintage study; current-reference membership is not PIT certification.",
            "Availability and unknowns are explicit in payload; calendar completeness is not label validity.",
            "No strategy acceptance or account simulation.",
        ],
        "backup": {
            "primary_copy": "one physical published cache payload",
            "other_machine": "not_observed",
            "source_snapshot": (
                "input fingerprint in producer-read receipt; producer bytes are not archived by this run"
                if source.get("schema") == "pattern-scan-source.git.v2"
                else "fixed primary task input bundle; retained worktree raw snapshot"
            ),
        },
    }


def publish_stock_versions(
    roots: DataRoots, parts: dict[str, Path], barrier: dict[str, Any], *, source: dict[str, Any], input_id: str
) -> dict[str, dict[str, Any]]:
    """Publish six part-based versions and independent dual-layer market context."""
    verify_source(source)
    if barrier.get("source_id") != source["source_id"] or barrier.get("input_id") != input_id:
        raise ValueError("shared publication source/input differs from barrier")
    for directory in parts.values():
        receipt = read_json(_checked_path(directory / "receipt.json"))
        if receipt.get("source_id") != source["source_id"] or receipt.get("input_id") != input_id or receipt.get("complete") is not True:
            raise ValueError("shared publication source/input differs from stock part")
        verify_files(directory, receipt["artifacts"])
    verify_barrier(barrier)
    calendar = pd.DatetimeIndex(pd.to_datetime(barrier["calendar"]))
    catalog = DataCatalog(roots)
    entries: dict[str, dict[str, Any]] = {}
    for kind, fields in FIELDS.items():
        files = {f"stocks/{object_digest(code)}/{field}.parquet": directory / f"{field}.parquet" for code, directory in parts.items() for field in fields}
        if kind == "features":
            for code, record in barrier["global_files"].items():
                path = _checked_path(Path(record["path"]))
                if file_digest(path) != record["sha256"]:
                    raise ValueError("global feature identity changed before publication")
                files[f"stocks/{object_digest(code)}/global_values.parquet"] = path
        if kind == "prices":
            for sidecar in ("close_matrix", "jump_matrix"):
                files[f"{sidecar}.parquet"] = _checked_path(Path(barrier["sidecars"][sidecar]["path"]))
        entries[kind] = publish_file_bundle(
            catalog, metadata(kind, source, input_id, calendar, coverage={"stock_n": len(parts), "calendar_n": len(calendar)}), files
        )
    directory = _checked_path(Path(next(iter(barrier["global_files"].values()))["path"]).parent)
    entries["market"] = publish_file_bundle(
        catalog,
        metadata("market", source, input_id, calendar, coverage=barrier["context_coverage"]),
        {
            "context.parquet": directory / "context.parquet",
            "benchmark.parquet": directory / "benchmark.parquet",
        },
    )
    verify_source(source)
    return entries
