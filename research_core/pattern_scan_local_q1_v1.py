"""Local Q1 reduction using completed stocks, without expanded event files.

One target's integer counts live at a time. Inputs stay at their original paths;
the only new payload is Q1 summary/annual tables under the calling worktree.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.artifact_store import file_digest, publish_noreplace, read_json, verify_files, write_json
from research_core.pattern_scan_barrier_v1 import checkpoint_label_entry
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_event_tables_v1 import project_group_outcomes
from research_core.pattern_scan_groups_v1 import groups_for_pattern
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.pattern_scan_q1_counts_v1 import Q1Counts
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS
from research_core.pattern_scan_receipt_io_v2 import read_scan_receipt
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, assert_inputs_unchanged, code_identity, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
DEFINITION = "pattern-scan-local-q1.v1"
Q1_COLUMNS = (*REQUIRED_COLUMNS, "event_eligibility_excluded")
SOURCE_TABLES = ("indicators", "cohort_events", "controls", "pattern_states", "universe", "base_labels")


def _stamp(path: Path) -> tuple[int, int, int, int]:
    info = checked_path(path).stat()
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


class _Reads:
    """Process-local first-use verification only; never a persistent cache."""

    def __init__(self) -> None:
        self.observed: dict[Path, tuple[str, tuple[int, int, int, int]]] = {}

    def frame(self, root: Path, record: dict[str, Any], *, columns: list[str] | None = None) -> pd.DataFrame:
        path = checked_path(root / record["path"])
        current = record["sha256"], _stamp(path)
        if path in self.observed:
            if self.observed[path] != current:
                raise ValueError("Q1 input changed after first use")
        else:
            verify_files(root, [record])
            self.observed[path] = current
        frame = read_frame(path, **({"columns": columns} if columns is not None else {}))
        if _stamp(path) != current[1]:
            raise ValueError("Q1 input changed while being read")
        return frame

    def unchanged(self) -> None:
        if any(_stamp(path) != record[1] for path, record in self.observed.items()):
            raise ValueError("Q1 source inputs changed during computation")


def _reuse_index(roots: tuple[Path, ...], reads: _Reads) -> dict[tuple[str, str], tuple[Path, dict[str, Any], dict[str, str]]]:
    found: dict[tuple[str, str], tuple[Path, dict[str, Any], dict[str, str]]] = {}
    for root in roots:
        for path in sorted(checked_path(root).glob("*/receipt.json")):
            if path.parent.name.startswith("."):
                continue
            before = _stamp(path)
            row = read_json(checked_path(path))
            digest = file_digest(path)
            if _stamp(path) != before:
                raise ValueError("Q1 reused event receipt changed while being read")
            reads.observed[path] = digest, before
            if row.get("schema") != "pattern-scan-event-part.v1" or row.get("complete") is not True:
                raise ValueError("Q1 reuse requires complete original event receipts")
            identity = row["identity"]
            key = identity["target"], identity["code"]
            if key in found:
                raise ValueError("ambiguous duplicate Q1 event-part reference")
            found[key] = path.parent, row, {"path": str(path), "sha256": digest}
    return found


def _save_table(root: Path, name: str, frame: pd.DataFrame) -> dict[str, Any]:
    if "removed_year" in frame:
        frame["removed_year"] = frame["removed_year"].astype("Int64")
    for column in frame:
        if column.endswith(("_rate", "_bound", "_median")):
            frame[column] = cast(pd.Series, pd.to_numeric(frame[column], errors="raise")).astype(float)
    path = root / name
    with path.open("xb") as stream:
        write_frame(frame, stream, index=False)
    pd.testing.assert_frame_equal(frame, read_frame(path), check_exact=True)
    return {"path": name, "bytes": path.stat().st_size, "rows": len(frame), "compression": "zstd"}


def run_local_q1(stock_result: Path, output: Path, *, repo_root: Path, reuse_event_roots: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Reduce the unchanged complete stock universe; never publish or delete.

    This computes Q1 only. The same original groups, event overlays, fixed
    facets and integer aggregators remain authoritative; Q2--Q6 stay incomplete.
    No feature, base-label, price or global-barrier kernel is called.
    """
    repo_root, stock_result, output = map(checked_path, (repo_root, stock_result, output))
    if not output.is_relative_to(repo_root / ".tmp") or output == repo_root / ".tmp":
        raise ValueError("Q1 output must be below the calling worktree's .tmp")
    if output.exists():
        raise FileExistsError(output)
    executor = code_identity(repo_root)
    if executor["dirty"]:
        raise ValueError("local Q1 requires a clean committed executor")
    run = stock_result.parent
    preparation, barrier_path = run / "derived-preparation.json", run / "global/receipt.json"
    inputs = fingerprint_inputs([
        InputSpec(name, path, live_producer=False) for name, path in (("stocks", stock_result), ("preparation", preparation), ("barrier", barrier_path))
    ])
    stock = read_scan_receipt(stock_result)
    prepared, barrier = read_scan_receipt(preparation), read_scan_receipt(barrier_path)
    rows = stock["pool"]["results"]
    codes = [row["code"] for row in rows]
    if stock.get("phase") != "full_stock_checkpoints" or stock["pool"].get("complete") is not True or not rows or len(set(codes)) != len(codes):
        raise ValueError("local Q1 requires completed unique stock checkpoints")
    if (
        len(rows) != prepared["ordinary_reference_n"]
        or set(codes) != set(barrier["global_files"])
        or barrier.get("complete") is not True
        or barrier["source_id"] != prepared["source"]["source_id"]
        or barrier["input_id"] != prepared["input_id"]
        or len(barrier["calendar"]) != prepared["calendar_n"]
    ):
        raise ValueError("local Q1 original stock/global coverage differs")
    parts = {}
    for row in rows:
        directory = checked_path(Path(row["output_path"]))
        if output.is_relative_to(directory) or directory.is_relative_to(output):
            raise ValueError("Q1 output overlaps original stocks")
        if (
            read_json(directory / "receipt.json") != row
            or row.get("complete") is not True
            or row["source_id"] != prepared["source"]["source_id"]
            or row["input_id"] != prepared["input_id"]
        ):
            raise ValueError("local Q1 original stock receipt differs")
        parts[row["code"]] = directory
    labels = checkpoint_label_entry(parts, source=prepared["source"], input_id=prepared["input_id"])
    pins = {"labels": {"version_id": labels["version_id"], "manifest_sha256": labels["manifest"]["sha256"]}}
    reads = _Reads()
    reuse = _reuse_index(reuse_event_roots, reads)
    calendar = pd.DatetimeIndex(pd.to_datetime(barrier["calendar"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".staging-{output.name}-{uuid.uuid4().hex}")
    staging.mkdir()
    # Largest completed cohort first supplies a conservative observed-stock
    # resource sample. Integer totals and stock-set medians are order invariant.
    rows = sorted(rows, key=lambda row: (-row["rows"]["cohort_events"], row["code"]))
    artifacts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    reused_receipts: dict[str, dict[str, str]] = {}
    before = resource_sample()
    for target in PATTERNS:
        target_before = resource_sample()
        counts = None
        reused_n = projected_n = 0
        for number, row in enumerate(rows, 1):
            stock_before = resource_sample()
            code, directory = row["code"], parts[row["code"]]
            global_record = barrier["global_files"][code]
            global_path = checked_path(Path(global_record["path"]))
            record = {"path": global_path.name, "bytes": global_path.stat().st_size, "sha256": global_record["sha256"]}
            global_frame = reads.frame(global_path.parent, record, columns=["security_id", "t0", "calendar_index", "MKT"])
            if (
                not global_frame.index.equals(calendar)
                or not cast(pd.Series, global_frame["security_id"]).eq(f"TW:{code}").all()
                or global_frame.t0.tolist() != calendar.strftime("%Y-%m-%d").tolist()
                or global_frame.calendar_index.tolist() != list(range(len(calendar)))
            ):
                raise ValueError("Q1 global calendar/security identity differs")
            markets = pd.Series(global_frame.MKT.to_numpy(), index=global_frame.t0)
            prior = reuse.get((target, code))
            if prior is not None:
                event_directory, saved, receipt_pin = prior
                expected = {
                    "code": code,
                    "target": target,
                    "source_id": prepared["source"]["source_id"],
                    "input_id": prepared["input_id"],
                    "stock_request_id": row["request_id"],
                    "global_sha256": global_record["sha256"],
                    "shared_pins": pins,
                }
                if saved["identity"] != expected:
                    raise ValueError("Q1 reused event ancestry differs")
                event_files = {record["path"]: record for record in saved["artifacts"]}
                events = reads.frame(event_directory, event_files["events.parquet"], columns=list(Q1_COLUMNS))
                memberships = reads.frame(event_directory, event_files["group_memberships.parquet"])
                daily = reads.frame(event_directory, event_files["daily_groups.parquet"])
                groups = tuple(name for name in daily if name != "t0")
                reused_receipts[f"{target}/{code}"] = receipt_pin
                reused_n += 1
            else:
                descriptors = {record["path"]: record for record in row["artifacts"]}
                tables = {
                    name: reads.frame(directory, descriptors[f"{name}.parquet"], columns=["quality_reason"] if name == "indicators" else None)
                    for name in SOURCE_TABLES
                }
                quality = cast(pd.Series, tables["indicators"]["quality_reason"])
                if not quality.index.equals(calendar):
                    raise ValueError("Q1 original quality calendar differs")
                grouped = groups_for_pattern(
                    target,
                    tables["cohort_events"],
                    tables["controls"],
                    tables["pattern_states"],
                    tables["universe"],
                    calendar,
                    prepared["source"]["source_id"],
                    prepared["input_id"],
                    security_id=f"TW:{code}",
                )
                projected = project_group_outcomes(
                    grouped, tables["base_labels"], quality, base_label_version_id=labels["version_id"], base_label_manifest_sha256=labels["manifest"]["sha256"]
                )
                events, memberships = projected.events.loc[:, list(Q1_COLUMNS)], projected.group_memberships
                groups = tuple(grouped.events)
                projected_n += 1
                del projected, grouped, tables, quality
            if counts is None:
                counts = Q1Counts(target, groups)
            if counts.groups != groups:
                raise ValueError("Q1 registered groups differ between stocks")
            counts.add_stock(code, events, memberships, markets=markets)
            del events, memberships, global_frame, markets
            if number == 1 or number % 100 == 0 or number == len(rows):
                LOGGER.info(
                    "Local Q1 target=%s stocks=%d/%d reused=%d new_projection=%d count_bytes=%d phase=%s",
                    target,
                    number,
                    len(rows),
                    reused_n,
                    projected_n,
                    counts.memory_nbytes,
                    phase_receipt("stock_reduce", stock_before, resource_sample()),
                )
        assert counts is not None
        summary, annual = counts.finalize()
        count_bytes = counts.memory_nbytes
        del counts
        target_artifacts = [_save_table(staging, f"{target}-summary.parquet", summary), _save_table(staging, f"{target}-annual.parquet", annual)]
        if code_identity(repo_root) != executor:
            raise ValueError("local Q1 executor changed during calculation")
        target_receipt = write_run_receipt(
            staging / f"{target}-receipt.json",
            run_id=f"{output.name}:{target}",
            definition=DEFINITION,
            parameters={
                "target": target,
                "stock_count": len(rows),
                "numerical_source": prepared["source"],
                "input_id": prepared["input_id"],
                "base_labels": pins["labels"],
            },
            inputs=inputs,
            results={record["path"]: staging / record["path"] for record in target_artifacts},
            repo_root=staging,
        )
        artifacts.extend({**record, "sha256": target_receipt["results"][record["path"]]["sha256"]} for record in target_artifacts)
        observations.append({
            "target": target,
            "reused_stock_parts": reused_n,
            "new_in_memory_projections": projected_n,
            "retained_numeric_count_bytes_before_release": count_bytes,
            "measurement": phase_receipt("q1_target", target_before, resource_sample()),
        })
        reads.unchanged()
        assert_inputs_unchanged(inputs)
        LOGGER.info("Local Q1 target complete target=%s summary_rows=%d annual_rows=%d", target, len(summary), len(annual))
        del summary, annual
    reads.unchanged()
    if code_identity(repo_root) != executor:
        raise ValueError("local Q1 executor changed before completion")
    manifest = {
        "schema": DEFINITION,
        "complete": True,
        "scope": "Q1 unconditional only; Q2-Q6 incomplete; no formal/shared publication",
        "stock_count": len(rows),
        "calendar": barrier["calendar"],
        "numerical_source": prepared["source"],
        "input_id": prepared["input_id"],
        "original_producer_fingerprint": prepared["producer_fingerprint"],
        "base_labels": pins["labels"],
        "artifacts": artifacts,
        "reused_event_receipts": reused_receipts,
        "observations": observations,
        "measurement": phase_receipt("local_q1", before, resource_sample()),
        "expanded_event_bytes_written": 0,
        "input_copies_written": 0,
        "shared_writes": False,
        "deletion_performed": False,
    }
    write_json(staging / "manifest.json", manifest)
    write_run_receipt(
        staging / "run_receipt.json",
        run_id=output.name,
        definition=DEFINITION,
        parameters={"targets": list(PATTERNS), "mode": "original_q1_integer_reduction"},
        inputs=inputs,
        results={"manifest": staging / "manifest.json"},
        repo_root=staging,
    )
    publish_noreplace(staging, output)
    LOGGER.info("Local Q1 complete stocks=%d output_bytes=%d", len(rows), sum(record["bytes"] for record in artifacts))
    return manifest
