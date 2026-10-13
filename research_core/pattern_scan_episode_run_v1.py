"""Exclusive scratch Q4 orchestration over caller-pinned completed stock parts."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, read_json, safe_path, verify_files, write_json
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_analysis_v1 import group_frame
from research_core.pattern_scan_candidate_daily_v1 import daily_candidate_states
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_episode_tables_v1 import (
    OBSERVATION_COLUMNS,
    daily_base_coverage,
    grouped_coverage,
    observe_group,
    per_stock_episodes,
    random_control_coverage,
    summarize_coverage,
)
from research_core.pattern_scan_execution_v1 import verify_source
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.pattern_scan_reporting_v1 import ERAS, MARKETS, candidate_membership
from research_core.pattern_scan_shared_v1 import SharedInputs

LOGGER = logging.getLogger(__name__)


def _pin(path: Path) -> dict[str, str]:
    checked = safe_path(path)
    return {"path": str(checked), "sha256": file_digest(checked)}


def _part(directory: Path, source_id: str, input_id: str, *, event: bool) -> dict[str, str]:
    directory = safe_path(directory)
    receipt = read_json(directory / "receipt.json")
    if receipt.get("complete") is not True:
        raise ValueError("episode ancestor part is incomplete")
    identity = receipt.get("identity", {}) if event else receipt
    if identity.get("source_id") != source_id or identity.get("input_id") != input_id:
        raise ValueError("episode ancestor source/input differs")
    verify_files(directory, receipt["artifacts"])
    return _pin(directory / "receipt.json")


def _write(directory: Path, name: str, frame: pd.DataFrame, artifacts: list[dict[str, Any]]) -> None:
    path = safe_path(directory / name)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)
    artifacts.append(describe_file(directory, path))


def _group_id(target: str, candidate: str | None) -> str:
    return f"{target}:original" if candidate is None else f"{target}:candidate:{candidate}"


def run_episodes(
    parts: dict[str, Path],
    barrier: dict[str, Any],
    event_parts: dict[str, dict[str, Path]],
    selections: dict[str, Any],
    top_candidates: dict[str, tuple[str, ...]],
    output: Path,
    *,
    source: dict[str, Any],
    input_id: str,
    shared: SharedInputs | None = None,
) -> dict[str, Any]:
    """Build original/top-candidate Q4 with observed and quota-matched controls.

    The caller supplies exactly its externally selected H252 cross-check top IDs.
    No selection or market discovery is performed here. Completion is exclusive;
    interrupted staging is retained and never represented by a success receipt.
    A completed output can be reused only after all current ancestors and every
    payload are verified. No formal catalog publication occurs in this adapter.
    """
    verify_source(source)
    if shared is not None:
        shared.validate_scope(tuple(parts), source, input_id)
    source_id = source["source_id"]
    if not parts or set(event_parts) != set(PATTERNS) or set(selections) != set(PATTERNS) or not set(top_candidates).issubset(PATTERNS):
        raise ValueError("episode run requires every approved pattern and fixed stock parts")
    if (
        barrier.get("complete") is not True
        or barrier.get("source_id") != source_id
        or barrier.get("input_id") != input_id
        or set(barrier["global_files"]) != set(parts)
    ):
        raise ValueError("episode barrier identity or stock pool differs")
    candidates: dict[str, dict[str, tuple[Atom, ...]]] = {}
    ancestors: dict[str, dict[str, str]] = {}
    for target in PATTERNS:
        if set(event_parts[target]) != set(parts):
            raise ValueError("episode event parts do not match fixed stock pool")
        available = {row["candidate_id"]: tuple(Atom(**atom) for atom in row["atoms"]) for row in selections[target]["candidates"]}
        requested = tuple(top_candidates.get(target, ()))
        if len(requested) > 10 or len(set(requested)) != len(requested) or not set(requested).issubset(available):
            raise ValueError("Q4 top IDs must be unique supplied selected candidates, at most ten")
        candidates[target] = {identifier: available[identifier] for identifier in requested}
    for code, directory in sorted(parts.items()):
        ancestors[f"stock:{code}"] = _part(directory, source_id, input_id, event=False)
        global_record = barrier["global_files"][code]
        ancestors[f"global:{code}"] = _pin(Path(global_record["path"]))
        if ancestors[f"global:{code}"]["sha256"] != global_record["sha256"]:
            raise ValueError("episode global feature file changed")
        for target in PATTERNS:
            ancestors[f"event:{target}:{code}"] = _part(event_parts[target][code], source_id, input_id, event=True)
    identity = {
        "source_id": source_id,
        "input_id": input_id,
        "barrier_id": object_digest(barrier),
        "ancestors": ancestors,
        "selection_id": object_digest(selections),
        "top_candidates": {target: list(candidates[target]) for target in PATTERNS},
        **({"shared_read_pins": shared.pins} if shared is not None else {}),
    }
    output = safe_path(output)
    if output.exists():
        receipt = read_json(output / "receipt.json")
        if receipt.get("complete") is not True or receipt.get("identity") != identity:
            raise ValueError("existing episode output is incomplete or has a different identity")
        verify_files(output, receipt["artifacts"])
        expected_files = {record["path"]: str(safe_path(output / record["path"])) for record in receipt["artifacts"]}
        if receipt.get("files") != expected_files:
            raise ValueError("episode output file map differs from verified payload paths")
        verify_source(source)
        return receipt
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = safe_path(output.parent / f".staging-{output.name}-{uuid.uuid4().hex}")
    staging.mkdir()
    artifacts: list[dict[str, Any]] = []
    observations: list[pd.DataFrame] = []
    groups: dict[str, dict[str, Any]] = {"C-base-daily": {"control_id": "C-base-daily", "candidate_id": None, "pattern_id": None}}
    for target in PATTERNS:
        for candidate in (None, *candidates[target]):
            identifier = _group_id(target, candidate)
            for suffix, control in (("", "pattern"), (":C-52w", "C-52w"), (":C-base-random", "C-base-random")):
                groups[identifier + suffix] = {"pattern_id": target, "candidate_id": candidate, "control_id": control}
    for code, directory in sorted(parts.items()):
        security_id = f"TW:{code}"
        prices = read_frame(directory / "prices.parquet") if shared is None else shared.read_stock(code, "prices")
        labels = read_frame(directory / "base_labels.parquet") if shared is None else shared.read_stock(code, "base_labels")
        dates = tuple(barrier["calendar"])
        if not isinstance(prices.index, pd.DatetimeIndex) or prices.index.strftime("%Y-%m-%d").tolist() != list(dates):
            raise ValueError("episode stock prices differ from common calendar")
        closes = [None if pd.isna(value) else float(value) for value in prices["Close"]]
        reasons = [None if pd.isna(value) else str(value) for value in prices["quality_reason"]]
        episodes, admission = per_stock_episodes(closes, labels, reasons, security_id, dates=dates)
        global_values = read_frame(ancestors[f"global:{code}"]["path"]) if shared is None else shared.read_global(code)
        if not global_values.index.equals(prices.index):
            raise ValueError("episode global values differ from calendar")
        anchor_mkt = global_values["MKT"].fillna("unknown").tolist()
        stem = object_digest(code)
        _write(staging, f"{stem}-admission.parquet", admission, artifacts)
        episode_rows = [
            {"security_id": security_id, "episode_id": object_digest({"security_id": security_id, "start_indices": item.start_indices}), **asdict(item)}
            for item in episodes
        ]
        _write(
            staging,
            f"{stem}-episodes.parquet",
            pd.DataFrame(episode_rows, columns=pd.Index(["security_id", "episode_id", "start_indices", "anchor_index", "peak_index", "status", "reason"])),
            artifacts,
        )
        daily_diagnostic_written = False
        common: pd.DataFrame | None = None
        indicators: pd.DataFrame | None = None
        raw_events: pd.DataFrame | None = None
        pattern_states: pd.DataFrame | None = None
        for target in PATTERNS:
            event_directory = event_parts[target][code]
            daily = read_frame(event_directory / "daily_groups.parquet")
            if daily["t0"].tolist() != list(dates):
                raise ValueError("daily episode group dates differ")
            retained = group_frame(event_directory, "pattern:union", 126)
            pool = group_frame(event_directory, "C-base-all", 126)
            pool = cast(pd.DataFrame, pool.loc[pool.base_eligible.eq(True)]).copy()
            pool_pin = object_digest(pool.loc[:, ["security_id", "t0", "calendar_index"]].to_dict("records"))
            c52 = group_frame(event_directory, "C-52w", 126)
            if not daily_diagnostic_written:
                diagnostic = daily_base_coverage(episodes, closes, dates, daily["C-base-daily"].tolist(), anchor_mkt, security_id, group_id="C-base-daily")
                observations.append(diagnostic)
                daily_diagnostic_written = True
            candidate_states: dict[str, np.ndarray] = {}
            if candidates[target]:
                if common is None:
                    common = read_frame(directory / "common_values.parquet") if shared is None else shared.read_stock(code, "common_values")
                    for column in global_values:
                        common[column] = global_values[column].to_numpy()
                    indicators = read_frame(directory / "indicators.parquet") if shared is None else shared.read_stock(code, "indicators")
                    raw_events = read_frame(directory / "raw_events.parquet") if shared is None else shared.read_stock(code, "raw_events")
                    pattern_states = read_frame(directory / "pattern_states.parquet") if shared is None else shared.read_stock(code, "pattern_states")
                assert indicators is not None and raw_events is not None and pattern_states is not None
                candidate_states = dict(
                    daily_candidate_states(
                        target,
                        raw_events,
                        indicators,
                        common,
                        pattern_states[target].to_numpy(dtype=np.int8),
                        security_id=security_id,
                        definition_id=source_id,
                        input_id=input_id,
                        candidates=candidates[target],
                    )
                )
            stock_rows: list[pd.DataFrame] = []
            draw_rows: list[pd.DataFrame] = []
            quota_rows: list[pd.DataFrame] = []
            for candidate in (None, *candidates[target]):
                identifier = _group_id(target, candidate)
                targets = (
                    retained if candidate is None else cast(pd.DataFrame, retained.loc[candidate_membership(retained, candidates[target][candidate]) == 1])
                )
                states = daily["pattern:union"].tolist() if candidate is None else candidate_states[candidate].tolist()
                stock_rows.append(
                    observe_group(episodes, closes, dates, targets.calendar_index.astype(int).tolist(), states, anchor_mkt, security_id, identifier)
                )
                stock_rows.append(
                    observe_group(
                        episodes,
                        closes,
                        dates,
                        c52.calendar_index.astype(int).tolist(),
                        daily["C-52w"].tolist(),
                        anchor_mkt,
                        security_id,
                        identifier + ":C-52w",
                    )
                )
                random_rows, drawn, quota = random_control_coverage(
                    pool,
                    targets,
                    group_id=identifier + ":C-base-random",
                    episodes=episodes,
                    closes=closes,
                    dates=dates,
                    anchor_regime=anchor_mkt,
                    security_id=security_id,
                    pool_pin=pool_pin,
                )
                stock_rows.append(random_rows)
                drawn["group_id"], quota["group_id"] = identifier + ":C-base-random", identifier + ":C-base-random"
                draw_rows.append(drawn)
                quota_rows.append(quota)
            compact = pd.concat(stock_rows, ignore_index=True)
            observations.append(compact)
            _write(staging, f"{stem}-{target}-observed.parquet", compact, artifacts)
            _write(staging, f"{stem}-{target}-draws.parquet", pd.concat(draw_rows, ignore_index=True), artifacts)
            _write(staging, f"{stem}-{target}-quotas.parquet", pd.concat(quota_rows, ignore_index=True), artifacts)
        LOGGER.info("Completed Q4 stock=%s episodes=%d", code, len(episodes))
    all_rows = pd.concat(observations, ignore_index=True) if observations else pd.DataFrame(columns=pd.Index(OBSERVATION_COLUMNS))
    _write(staging, "observations.parquet", all_rows, artifacts)
    coverage = [row for row in grouped_coverage(all_rows) if row["split"] != "all"]
    observed_groups = set(all_rows.group_id)
    empty = pd.DataFrame(columns=pd.Index(OBSERVATION_COLUMNS))
    for group in set(groups) - observed_groups:
        coverage.extend(
            {"group_id": group, "split": split, "era": era, "mkt": market, **summarize_coverage(empty)}
            for split, era, market in product(("development", "cross-check"), ERAS, MARKETS)
        )
    coverage_frame = pd.DataFrame([{**row, **groups[cast(str, row["group_id"])]} for row in coverage])
    _write(staging, "coverage.parquet", coverage_frame, artifacts)
    verify_source(source)
    for record in ancestors.values():
        if file_digest(Path(record["path"])) != record["sha256"]:
            raise ValueError("episode ancestor changed during execution")
    # Receipt identity alone cannot certify unchanged ancestor payload bytes.
    # Verify the full declared inventories again immediately before completion.
    for code, directory in sorted(parts.items()):
        if _part(directory, source_id, input_id, event=False) != ancestors[f"stock:{code}"]:
            raise ValueError("episode stock ancestor changed during execution")
        for target in PATTERNS:
            if _part(event_parts[target][code], source_id, input_id, event=True) != ancestors[f"event:{target}:{code}"]:
                raise ValueError("episode event ancestor changed during execution")
    verify_files(staging, artifacts)
    files = {record["path"]: str(output / record["path"]) for record in artifacts}
    receipt = {
        "schema": "pattern-scan-episodes.v1",
        "complete": True,
        "identity": identity,
        "artifacts": artifacts,
        "files": files,
        "group_registry": groups,
        "episode_observation_n": len(all_rows),
        "coverage_cell_n": len(coverage_frame),
    }
    write_json(staging / "receipt.json", receipt)
    publish_noreplace(staging, output)
    return receipt
