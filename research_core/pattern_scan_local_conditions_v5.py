"""Bounded Q2/Q3 reduction over the unchanged original PR17 stock inputs.

Only completed result tables and the development selection are retained here.
The caller owns final-result hashing and the run receipt. Cell digests below
are the existing algorithmic cell identities, never file or input hashes.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research_core.artifact_store import object_digest, publish_noreplace, read_json, write_json
from research_core.hhhl_variants_selection import Atom, Candidate, DevelopmentCounts, SelectionResult, candidate_id, split_for_code
from research_core.pattern_scan_candidate_coverage_v1 import CandidateCoverage
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_dense_counts_v1 import DenseCounts
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern
from research_core.pattern_scan_groups_v1 import PRIMARY
from research_core.pattern_scan_membership_v1 import StockCountPlan, membership_inventory
from research_core.pattern_scan_parquet_v1 import write_frame
from research_core.pattern_scan_reporting_v1 import top_confirmation_candidates
from research_core.pattern_scan_summary_store_v1 import YEARS

if TYPE_CHECKING:
    from research_core.pattern_scan_local_inputs_v5 import LocalInputs

LOGGER = logging.getLogger(__name__)
_KNOWN = ("hit", "loss", "flat-win")
_MISSING = frozenset(("unknown", "not_applicable", "feature_unknown", "warmup_insufficient"))
StockFrames = Callable[[], Iterable[tuple[str, pd.DataFrame]]]


def _key(atom: Atom) -> tuple[str, str]:
    return atom.feature_id, atom.bin_id


def _development(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    required = {"event_id", "security_id", "horizon", "calendar_full", "effective_label", "event_main_eligible"}
    if not frame.columns.is_unique or not required.issubset(frame) or frame.event_id.duplicated().any():
        raise ValueError("development selection requires unique event identities and outcome columns")
    if not frame.empty and (not frame.security_id.eq(f"TW:{code}").all() or not frame.horizon.eq(126).all()):
        raise ValueError("development selection stock/horizon differs")
    if split_for_code(code) != "development":
        return frame.iloc[:0]
    return cast(pd.DataFrame, frame.loc[frame.event_main_eligible.astype(bool) & frame.calendar_full.astype(bool) & frame.effective_label.isin(_KNOWN)])


def _add(counts: list[int], labels: np.ndarray, mask: np.ndarray) -> None:
    for index, label in enumerate(_KNOWN):
        counts[index] += int(np.count_nonzero(mask & (labels == label)))
    counts[3] += int(bool(np.any(mask)))


def _observed(frame: pd.DataFrame, atom: Atom) -> np.ndarray:
    return (frame[f"{atom.feature_id}_status"].eq("known") & frame[f"{atom.feature_id}_bin"].eq(atom.bin_id)).to_numpy(dtype=bool)


def select_streaming(target: str, frames: StockFrames, atoms: tuple[Atom, ...]) -> SelectionResult:
    """Select with two bounded stock passes and the legacy exact integer rules.

    ``frames`` yields original union/H126 batches once per code on each pass.
    No SelectionEvent list, whole-market event frame or event-ID set is kept.
    The second pass obtains exact conjunction DevelopmentCounts, including
    zero intersections, after the family-distinct single selection is fixed.
    """
    if target not in PATTERNS or len({_key(atom) for atom in atoms}) != len(atoms):
        raise ValueError("selection requires a registered pattern and unique atoms")
    families: dict[str, str] = {}
    for atom in atoms:
        if atom.feature_id in families and families[atom.feature_id] != atom.family:
            raise ValueError("feature has inconsistent resolved families")
        families[atom.feature_id] = atom.family
    eligible = tuple(atom for atom in atoms if atom.selectable and atom.family != "K" and atom.bin_id not in _MISSING)
    singles = {atom: [0, 0, 0, 0] for atom in eligible}
    total = [0, 0, 0, 0]
    codes: set[str] = set()
    for code, supplied in frames():
        if code in codes:
            raise ValueError("duplicate complete selection stock feed")
        codes.add(code)
        frame = _development(supplied, code)
        labels = frame.effective_label.to_numpy(dtype=object)
        _add(total, labels, np.ones(len(frame), dtype=bool))
        for atom in eligible:
            _add(singles[atom], labels, _observed(frame, atom))
    ranked = [(atom, DevelopmentCounts(*counts)) for atom, counts in singles.items() if sum(counts[:3]) >= 100 and counts[3] >= 30]
    ranked.sort(key=lambda item: (-Fraction(item[1].hit, item[1].known), *_key(item[0])))
    selected: list[Atom] = []
    used: set[str] = set()
    for atom, _ in ranked:
        if atom.family not in used:
            selected.append(atom)
            used.add(atom.family)
            if len(selected) == 8:
                break
    members = [tuple(sorted(group, key=_key)) for size in (1, 2, 3) for group in combinations(selected, size)]
    conjunctions = [[0, 0, 0, 0] for _ in members]
    if members:
        second_codes: set[str] = set()
        for code, supplied in frames():
            if code in second_codes:
                raise ValueError("duplicate complete selection stock feed")
            second_codes.add(code)
            frame = _development(supplied, code)
            labels = frame.effective_label.to_numpy(dtype=object)
            observed = {atom: _observed(frame, atom) for atom in selected}
            for group, counts in zip(members, conjunctions, strict=True):
                mask = np.ones(len(frame), dtype=bool)
                for atom in group:
                    mask &= observed[atom]
                _add(counts, labels, mask)
        if second_codes != codes:
            raise ValueError("selection stock coverage changed between bounded passes")
    candidates = tuple(
        Candidate(f"pattern-scan.v1:{quote(target, safe='')}:{candidate_id(group).partition(':')[2]}", group, DevelopmentCounts(*counts))
        for group, counts in zip(members, conjunctions, strict=True)
    )
    LOGGER.info("Local Q2/Q3 selection target=%s development_known=%d selected=%d candidates=%d", target, sum(total[:3]), len(selected), len(candidates))
    return SelectionResult(tuple(selected), candidates, DevelopmentCounts(*total))


def _metadata(target: str, group: str, horizon: int) -> dict[str, Any]:
    if group.startswith("pattern:"):
        return {"pattern_id": target, "control_id": "pattern", "cohort_id": group.partition(":")[2], "horizon": horizon}
    return {"pattern_id": target, "control_id": group, "cohort_id": "union", "horizon": horizon, "primary_control_id": PRIMARY[target]}


def _normalize(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    identifiers = cast(pd.Series, frame["candidate_id"]) if "candidate_id" in frame else pd.Series("", index=frame.index)
    frame["candidate_id"] = identifiers.fillna("").astype("string")
    source = cast(pd.Series, frame["candidate_atoms"]) if "candidate_atoms" in frame else pd.Series(None, index=frame.index, dtype=object)
    frame["candidate_atoms_json"] = source.map(lambda value: json.dumps(value, sort_keys=True) if isinstance(value, list) else "[]").astype("string")
    frame = frame.drop(columns="candidate_atoms", errors="ignore")
    if "removed_year" in frame:
        frame["removed_year"] = frame["removed_year"].astype("Int64")
    for column in frame:
        if column.endswith(("_rate", "_bound", "_median")):
            frame[column] = cast(pd.Series, pd.to_numeric(cast(pd.Series, frame[column]), errors="raise")).astype(float)
    return frame.reindex(sorted(frame.columns), axis=1)


class _SummaryWriter:
    """Buffer final rows with one stable schema, including all-null chunks."""

    def __init__(self, path: Path, limit: int) -> None:
        self.path, self.limit = path, limit
        self.rows: list[dict[str, Any]] = []
        self.writer: pq.ParquetWriter | None = None

    def append(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        if len(self.rows) >= self.limit:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pandas(_normalize(self.rows), preserve_index=False)
        if self.writer is None:
            if self.path.exists():
                raise FileExistsError(self.path)
            self.writer = pq.ParquetWriter(self.path, table.schema, compression="zstd")
        self.writer.write_table(table)
        self.rows.clear()

    def close(self) -> None:
        try:
            self.flush()
        finally:
            if self.writer is not None:
                self.writer.close()


def _rates(summary: dict[str, Any], applicable: bool) -> dict[str, Any]:
    if not applicable:
        for key in summary:
            if key.endswith(("_rate", "_bound")):
                summary[key] = None
    return summary


def _summarize_group(
    frames: StockFrames,
    target: str,
    group: str,
    horizon: int,
    candidates: dict[str, tuple[Atom, ...]],
    output: Path,
) -> tuple[list[Path], list[dict[str, Any]]]:
    metadata = _metadata(target, group, horizon)
    # Q1 is already complete; combinations are reported only in confirmation.
    inventory = tuple(
        row
        for row in membership_inventory(metadata, candidates)
        if row["feature_id"] != "unconditional" and (row["feature_id"] != "candidate" or row["split"] == "cross-check")
    )
    identifiers = tuple(object_digest(row) for row in inventory)
    accumulator = DenseCounts(identifiers, horizon)
    plan = StockCountPlan(inventory, max_membership_rows=2_000_000)
    coverage = CandidateCoverage(metadata, candidates)
    for _, frame in frames():
        accumulator.add_stock(plan.matrix(frame))
        if candidates:
            coverage.add_stock(frame)
    name = f"{target}-{quote(group, safe='')}-h{horizon}"
    paths = [output / f"{name}-{kind}.parquet" for kind in ("summary", "annual", "candidate-coverage")]
    summary_writer, annual_writer = _SummaryWriter(paths[0], 2048), _SummaryWriter(paths[1], 8192)
    top_rows: list[dict[str, Any]] = []
    try:
        for meta, cell in zip(inventory, identifiers, strict=True):
            applicable = meta["condition_status"] != "not_applicable"
            total = _rates(accumulator.summarize(cell), applicable)
            removed, dropped = accumulator.drop_best_year(cell)
            dropped = _rates(dropped, applicable)
            summary_writer.append({**meta, **total, "row_kind": "full", "removed_year": None})
            summary_writer.append({**meta, **dropped, "row_kind": "drop_best_year", "removed_year": removed})
            for year, summary in zip(YEARS, accumulator.annual_summary(cell), strict=True):
                annual_writer.append({**meta, **_rates(summary, applicable), "year": year})
            if (
                meta["feature_id"] == "candidate"
                and meta["condition_status"] == "known"
                and horizon == 252
                and group == "pattern:union"
                and meta["era"] == meta["mkt"] == "all"
            ):
                top_rows.append({**meta, **total})
    finally:
        summary_writer.close()
        annual_writer.close()
    with paths[2].open("xb") as stream:
        write_frame(coverage.finalize(), stream, index=False)
    LOGGER.info(
        "Local Q2/Q3 group complete target=%s group=%s horizon=%d cells=%d count_bytes=%d", target, group, horizon, len(inventory), accumulator.memory_nbytes
    )
    return paths, top_rows


def _progress(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".progress-{path.stem}-{uuid.uuid4().hex}.json")
    write_json(temporary, value)
    temporary.replace(path)


def _selection_record(path: Path, target: str) -> tuple[dict[str, Any], dict[str, tuple[Atom, ...]]]:
    """Read the final selected record, without inspecting any input payload."""
    saved = read_json(path)
    selected = tuple(Atom(**row) for row in saved["selected_atoms"])
    candidates = tuple(
        Candidate(row["candidate_id"], tuple(Atom(**atom) for atom in row["atoms"]), DevelopmentCounts(**row["development_counts"]))
        for row in saved["candidates"]
    )
    if len(selected) > 8 or len({atom.family for atom in selected}) != len(selected) or len(candidates) > 92:
        raise ValueError("saved selection exceeds the approved candidate inventory")
    identifiers = [candidate.candidate_id for candidate in candidates]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("saved selection has duplicate candidates")
    for candidate in candidates:
        expected = f"pattern-scan.v1:{quote(target, safe='')}:{candidate_id(candidate.atoms).partition(':')[2]}"
        if candidate.candidate_id != expected or not set(candidate.atoms).issubset(selected):
            raise ValueError("saved candidate identity differs from the selected atoms")
    result = SelectionResult(selected, candidates, DevelopmentCounts(**saved["development_counts"]))
    return asdict(result), {candidate.candidate_id: candidate.atoms for candidate in candidates}


def _group_paths(directory: Path, target: str, group: str, horizon: int) -> list[Path]:
    name = f"{target}-{quote(group, safe='')}-h{horizon}"
    paths = [directory / f"{name}-{kind}.parquet" for kind in ("summary", "annual", "candidate-coverage")]
    schemas = (
        {
            "pattern_id",
            "control_id",
            "cohort_id",
            "horizon",
            "feature_id",
            "candidate_id",
            "condition_status",
            "split",
            "era",
            "mkt",
            "known_n",
            "hit_n",
            "row_kind",
        },
        {"pattern_id", "feature_id", "year", "event_n", "known_n", "hit_n"},
        {"candidate_id", "split", "era", "mkt", "true_n", "false_n", "feature_unknown_n", "not_applicable_n", "event_n"},
    )
    for path, columns in zip(paths, schemas, strict=True):
        if not path.is_file() or not columns.issubset(pq.read_schema(path).names):
            raise ValueError(f"completed Q2/Q3 group is missing its final table/schema: {path}")
    return paths


def _confirmation_rows(path: Path) -> list[dict[str, Any]]:
    columns = ["pattern_id", "candidate_id", "horizon", "split", "era", "mkt", "control_id", "cohort_id", "known_n", "hit_n"]
    frame = pd.read_parquet(
        path,
        columns=columns,
        filters=[
            ("feature_id", "==", "candidate"),
            ("condition_status", "==", "known"),
            ("row_kind", "==", "full"),
            ("split", "==", "cross-check"),
            ("era", "==", "all"),
            ("mkt", "==", "all"),
        ],
    )
    return cast(list[dict[str, Any]], frame.to_dict("records"))


def run_conditions(
    inputs: LocalInputs, target: str, output: Path, *, on_progress: Callable[[int, int], None] | None = None
) -> tuple[dict[str, Any], dict[str, tuple[Atom, ...]], list[Path]]:
    """Write one target's Q2/Q3 final tables, reusing original event parts.

    Missing event projections are materialized once in un-hashed target scratch.
    A completed original part stays in place. Target progress records completed
    group/horizon directories, without per-file receipts or payload hashes.
    A failed group retains its unique staging; only that group is retried.
    """
    if target not in PATTERNS or not inputs.codes or len(set(inputs.codes)) != len(inputs.codes):
        raise ValueError("Q2/Q3 requires one registered pattern and unique complete stocks")
    output.mkdir(parents=True, exist_ok=True)
    progress_directory = inputs.temporary / "conditions-progress"
    progress_directory.mkdir(parents=True, exist_ok=True)
    progress_path = progress_directory / f"{target}.json"
    identity = {"target": target, "source_id": inputs.source_id, "input_id": inputs.input_id, "codes": list(inputs.codes), "output": str(output.absolute())}
    cached = False
    if progress_path.exists():
        progress = read_json(progress_path)
        if progress.get("schema") != "pattern-scan-local-conditions-progress.v5" or progress.get("identity") != identity:
            raise ValueError("Q2/Q3 continuation identity differs from its completed progress")
        groups = tuple(progress["groups"])
        if not groups or len(set(groups)) != len(groups) or any(not isinstance(group, str) or not group for group in groups):
            raise ValueError("Q2/Q3 progress requires unique registered groups")
    else:
        inputs.cache_target(target, inputs.temporary / "events" / target)
        cached = True
        first = inputs.bound(target, inputs.codes[0])
        groups = tuple(first.daily_groups)
        del first
        progress = {
            "schema": "pattern-scan-local-conditions-progress.v5",
            "identity": identity,
            "groups": list(groups),
            "selection_complete": False,
            "completed": {},
        }
        _progress(progress_path, progress)
    expected_groups = {f"{quote(group, safe='')}-h{horizon}" for group in groups for horizon in (126, 252)}
    if not isinstance(progress.get("completed"), dict) or not set(progress["completed"]).issubset(expected_groups):
        raise ValueError("Q2/Q3 progress includes unregistered completed groups")
    if not cached and (progress["selection_complete"] is not True or len(progress["completed"]) < len(expected_groups)):
        inputs.cache_target(target, inputs.temporary / "events" / target)

    def selection_frames() -> Iterable[tuple[str, pd.DataFrame]]:
        for code in inputs.codes:
            if split_for_code(code) == "development":
                yield code, inputs.group_frame(inputs.bound(target, code), "pattern:union", 126)

    selection_path = output / f"{target}-selection.json"
    if not selection_path.exists():
        if progress["selection_complete"] is True:
            raise ValueError("completed Q2/Q3 selection record is missing")
        selection = select_streaming(target, selection_frames, atoms_for_pattern(target))
        staging_selection = output / f".staging-{target}-selection-{uuid.uuid4().hex}.json"
        write_json(staging_selection, asdict(selection))
        publish_noreplace(staging_selection, selection_path)
    selected, candidates = _selection_record(selection_path, target)
    if progress["selection_complete"] is not True:
        progress["selection_complete"] = True
        _progress(progress_path, progress)
    paths = [selection_path]
    main_groups = {"pattern:union", "C-base-no-pattern", "C-base-all", PRIMARY[target]}
    confirmation: list[dict[str, Any]] = []
    for group in groups:
        for horizon in (126, 252):

            def frames() -> Iterable[tuple[str, pd.DataFrame]]:
                for code in inputs.codes:
                    yield code, inputs.group_frame(inputs.bound(target, code), group, horizon)

            name = f"{quote(group, safe='')}-h{horizon}"
            destination = output / name
            if name in progress["completed"] and progress["completed"][name] != name:
                raise ValueError("completed Q2/Q3 group directory differs from progress")
            if name in progress["completed"] and not destination.is_dir():
                raise ValueError("completed Q2/Q3 group directory is missing")
            top_rows = None
            if not destination.exists():
                staging = output / f".staging-{name}-{uuid.uuid4().hex}"
                staging.mkdir()
                staged_paths, top_rows = _summarize_group(frames, target, group, horizon, candidates if group in main_groups else {}, staging)
                publish_noreplace(staging, destination)
                group_paths = [destination / path.name for path in staged_paths]
            else:
                group_paths = _group_paths(destination, target, group, horizon)
            if name not in progress["completed"]:
                progress["completed"][name] = name
                _progress(progress_path, progress)
            paths.extend(group_paths)
            if on_progress is not None:
                on_progress(len(progress["completed"]), len(expected_groups))
            if group == "pattern:union" and horizon == 252:
                confirmation.extend(top_rows if top_rows is not None else _confirmation_rows(group_paths[0]))
    if confirmation:
        identifiers = top_confirmation_candidates(pd.DataFrame(confirmation)).get(target, ())
        top = {identifier: candidates[identifier] for identifier in identifiers}
    else:
        top = {}
    LOGGER.info("Local Q2/Q3 target complete target=%s groups=%d final_files=%d top_candidates=%d", target, len(groups), len(paths), len(top))
    return selected, top, paths
