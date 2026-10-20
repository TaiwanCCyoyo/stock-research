"""Bounded Q5--Q6 reductions over original PR17 inputs, without temp digests."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from dataclasses import asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

from research_core.artifact_store import read_json, write_json
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_followup_batches_v3 import summarize_followup_batches
from research_core.pattern_scan_followup_v1 import FollowupTables, followup_values
from research_core.pattern_scan_reporting_v1 import candidate_membership

if TYPE_CHECKING:
    from research_core.pattern_scan_local_inputs_v5 import LocalInputs

LOGGER = logging.getLogger(__name__)
HORIZONS = (126, 252)
RESULT_NAMES = (
    "path_summary",
    "first_flag_summary",
    "flag_summary",
    "landmark_summary",
    "tradeoff_points",
    "exclusions",
    "path_by_outcome",
    "first_flag_by_outcome",
    "holding_by_outcome",
)


def _write(path: Path, frame: pd.DataFrame, *, incomplete: bool = False) -> None:
    with path.open("wb" if incomplete else "xb") as stream:
        frame.to_parquet(stream, index=False, compression="zstd")


def _save_progress(path: Path, scope: dict[str, Any], completed: set[str], empty: set[str]) -> None:
    staged = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    write_json(staged, {**scope, "completed": sorted(completed), "empty": sorted(empty)})
    os.replace(staged, path)


def _feeds(
    group: str,
    horizon: int,
    *,
    inputs: LocalInputs,
    target: str,
    projections: dict[str, tuple[Path, dict[str, set[str]], pd.Series, list[int]]],
) -> Iterator[tuple[FollowupTables, pd.DataFrame]]:
    """Retain only one stock's requested group/horizon projection at a time."""
    for code, (directory, memberships, markets, anchors) in projections.items():
        event_ids = memberships[group]
        if not event_ids:
            continue
        chunks = []
        for field in fields(FollowupTables):
            frame = pd.read_parquet(directory / f"{field.name}.parquet", filters=[("horizon", "==", horizon)])
            frame = cast(pd.DataFrame, frame.loc[frame.event_id.isin(event_ids)].copy())
            frame["group_id"], frame["target_pattern_id"] = group, target
            frame["mkt"] = frame.event_id.map(markets)
            chunks.append(frame)
        tables = FollowupTables(*chunks)
        del chunks
        holding = inputs.holding(code, anchors)
        holding = holding.loc[holding.horizon.eq(horizon)].copy()
        yield tables, holding
        del tables, holding


def run_followup(
    inputs: LocalInputs,
    target: str,
    candidates: dict[str, tuple[Atom, ...]],
    output: Path,
) -> list[Path]:
    """Write nine final tables, retaining one target's disposable projections.

    The caller owns target-level completion and final result hashes/receipt.
    ``_temporary`` contains zstd projections and a completed-stock list; it has
    no digests or per-file receipts and is never an input identity. Do not switch
    the original price/indicator/event generations while this phase runs.
    """
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target must be a nonblank original pattern identity")
    selected = {identifier: atoms for identifier, atoms in candidates.items() if identifier != target}
    if len(selected) > 10 or (target in candidates and candidates[target]):
        raise ValueError("followup accepts at most ten candidates and an empty original-pattern marker")
    if any(not isinstance(identifier, str) or not identifier.strip() or not atoms for identifier, atoms in selected.items()):
        raise ValueError("selected candidates require nonblank identities and nonempty atoms")
    final_paths = [output / f"{name}.parquet" for name in RESULT_NAMES]
    if any(path.exists() for path in final_paths):
        raise FileExistsError("parent target progress must reuse completed followup results instead of overwriting them")
    temporary = output / "_temporary"
    temporary.mkdir(parents=True, exist_ok=True)
    scope: dict[str, Any] = {
        "schema": "pattern-scan-local-followup-progress.v5",
        "target": target,
        "candidate_atoms": {identifier: [asdict(atom) for atom in atoms] for identifier, atoms in sorted(selected.items())},
        "codes": sorted(inputs.codes),
        "source_id": getattr(inputs, "source_id", None),
        "input_id": getattr(inputs, "input_id", None),
    }
    progress_path = temporary / "progress.json"
    progress: dict[str, Any] = read_json(progress_path) if progress_path.exists() else {**scope, "completed": [], "empty": []}
    if any(progress.get(name) != value for name, value in scope.items()):
        raise ValueError("followup temporary scope differs from original inputs or fixed candidates")
    completed, empty = set(progress["completed"]), set(progress["empty"])
    if len(completed) != len(progress["completed"]) or not empty.issubset(completed) or not completed.issubset(inputs.codes):
        raise ValueError("invalid followup completed-stock progress")
    if not progress_path.exists():
        _save_progress(progress_path, scope, completed, empty)
    groups = {target: target, **dict.fromkeys(selected, target)}
    projections: dict[str, tuple[Path, dict[str, set[str]], pd.Series, list[int]]] = {}
    for code in sorted(inputs.codes):
        if code in empty:
            continue
        bound = inputs.bound(target, code)
        original = pd.concat([inputs.group_frame(bound, "pattern:union", horizon) for horizon in HORIZONS], ignore_index=True)
        if original.empty:
            completed.add(code)
            empty.add(code)
            _save_progress(progress_path, scope, completed, empty)
            continue
        first = original.loc[original.horizon.eq(HORIZONS[0])]
        memberships = {target: set(original.event_id)}
        for identifier, atoms in selected.items():
            memberships[identifier] = set(first.loc[candidate_membership(first, atoms) == 1, "event_id"])
        markets = cast(pd.Series, original.drop_duplicates("event_id").set_index("event_id")["mkt"]).copy()
        directory = temporary / code
        if code in completed:
            if not all((directory / f"{field.name}.parquet").is_file() for field in fields(FollowupTables)):
                raise ValueError("completed followup stock projection is missing")
        else:
            stock = inputs.stock(code)
            observations = followup_values(original, stock["indicators"], stock["pivots"])
            directory.mkdir(exist_ok=True)
            # A stock without its completion entry is an interrupted attempt;
            # rewrite only that stock's disposable projection, never results.
            for field in fields(FollowupTables):
                _write(directory / f"{field.name}.parquet", getattr(observations, field.name), incomplete=True)
            del observations, stock
            completed.add(code)
            _save_progress(progress_path, scope, completed, empty)
        # Reuse the caller's common holding projection. Keeping its anchors
        # avoids making another per-target copy of that intermediate table.
        anchors = sorted(set(int(day) for day in first.calendar_index))
        projections[code] = directory, memberships, markets, anchors
        LOGGER.info("Followup projections complete target=%s stock=%s events=%d", target, code, len(original))
        del original, first, bound

    def feeds(group: str, horizon: int) -> Iterator[tuple[FollowupTables, pd.DataFrame]]:
        return _feeds(group, horizon, inputs=inputs, target=target, projections=projections)

    followup, failure, _measurements = summarize_followup_batches(groups, feeds)
    frames = {field.name: getattr(result, field.name) for result in (followup, failure) for field in fields(result)}
    for name, path in zip(RESULT_NAMES, final_paths, strict=True):
        _write(path, frames[name])
    LOGGER.info("Followup summary complete target=%s groups=%d result_tables=%d", target, len(groups), len(final_paths))
    return final_paths
