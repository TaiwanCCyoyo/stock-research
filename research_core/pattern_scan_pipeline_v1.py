"""Approved fixed-input preparation and measured stock-phase configuration.

All computations consume the canonical immutable raw snapshot. A profile is a
resource observation over preregistered representative stocks, not a selection
of research rules or a claim that Q1--Q6 have been completed.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.artifact_store import file_digest, object_digest, publish_noreplace, read_json, write_json
from research_core.pattern_scan_execution_v1 import run_requests, verify_source
from research_core.pattern_scan_inputs_v1 import ScanSnapshot
from research_core.pattern_scan_live_inputs_v2 import LiveScanInputs
from research_core.research_data_paths import _checked_path
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)


def prepare_requests(
    snapshot: ScanSnapshot | LiveScanInputs, codes: tuple[str, ...], source: dict[str, Any], run_root: Path, *, calculation_authorized: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Prepare only explicit fixed codes with hashes and exclusive resume files."""
    if calculation_authorized is not True:
        raise PermissionError("explicit approved fixed-input calculation authorization required")
    verify_source(source)
    snapshot.verify_after()
    run_root = _checked_path(run_root)
    if not run_root.is_absolute() or run_root.parent != snapshot.roots.primary / ".tmp" / "pattern-scan-execution":
        raise ValueError("prepared run scratch must belong to the explicit primary checkout")
    if not codes or len(set(codes)) != len(codes) or not all(isinstance(code, str) for code in codes):
        raise ValueError("unique original stock codes required")
    membership = snapshot.inventory.set_index("code")
    if any(code not in membership.index or not bool(membership.loc[code, "included"]) for code in codes):
        raise ValueError("prepared code outside fixed ordinary-reference universe")
    run_root.mkdir(parents=True, exist_ok=True)
    directory = _checked_path(run_root / "prepared")
    directory.mkdir(exist_ok=True)
    requests: list[dict[str, Any]] = []
    provenance = (
        {"schema": "pattern-scan-prepared.v2", "input_fingerprint_id": snapshot.input_id}
        if isinstance(snapshot, LiveScanInputs)
        else {"schema": "pattern-scan-prepared.v1", "input_manifest_sha256": snapshot.manifest_sha256}
    )
    before = resource_sample()
    for code in sorted(codes):
        logical = {
            "security_id": f"TW:{code}",
            "input_id": snapshot.input_id,
            "source_id": source["source_id"],
            "price_basis": "price-basis.v2/reference_factor_adjusted",
            "calendar": object_digest(snapshot.calendar.strftime("%Y-%m-%d").tolist()),
        }
        name = object_digest(logical)
        destination = _checked_path(directory / name)
        path, receipt_path = destination / f"{name}.parquet", destination / f"{name}.json"
        if destination.exists():
            receipt = read_json(receipt_path)
            if (
                any(receipt.get(key) != value for key, value in provenance.items())
                or receipt.get("identity") != logical
                or type(receipt.get("rows")) is not int
                or receipt["rows"] != len(snapshot.calendar)
                or file_digest(path) != receipt.get("sha256")
            ):
                raise ValueError("existing prepared input differs or lacks a complete receipt")
        else:
            prices = snapshot.stock(code)
            staging = directory / f".staging-{name}-{uuid.uuid4().hex}"
            staging.mkdir()
            prepared_file = staging / path.name
            with prepared_file.open("xb") as stream:
                prices.to_parquet(stream, index=True)
            digest = file_digest(prepared_file)
            write_json(
                staging / receipt_path.name,
                {
                    **provenance,
                    "identity": logical,
                    "sha256": digest,
                    "rows": len(prices),
                },
            )
            publish_noreplace(staging, destination)
        requests.append({
            "calculation_authorized": True,
            "source": source,
            "primary": str(snapshot.roots.primary),
            "data": str(snapshot.roots.data),
            "run_root": str(run_root),
            "prepared_path": str(path),
            "prepared_sha256": file_digest(path),
            "code": code,
            "industry_ref": str(membership.loc[code, "industry_ref"]),
            "input_id": snapshot.input_id,
        })
    verify_source(source)
    snapshot.verify_after()
    measurement = phase_receipt("fixed_price_preparation", before, resource_sample())
    LOGGER.info("Prepared fixed scan stocks=%d run=%s", len(requests), run_root)
    return requests, measurement


def representative_codes(snapshot: ScanSnapshot | LiveScanInputs) -> tuple[tuple[str, ...], dict[str, str | None]]:
    """Deterministic metadata/coverage strata; no event/outcome-based sampling."""
    eligible = snapshot.inventory.loc[snapshot.inventory["included"], "code"].astype(str)
    allowed = tuple(eligible)
    observations = snapshot.prices.loc[snapshot.prices["Code"].isin(allowed)]
    coverage = observations.groupby("Code", sort=True)["Date"].agg(["min", "max", "nunique"])
    first = snapshot.calendar.get_indexer(pd.DatetimeIndex(coverage["min"]))
    last = snapshot.calendar.get_indexer(pd.DatetimeIndex(coverage["max"]))
    if np.any(first < 0) or np.any(last < 0):
        raise ValueError("representative coverage outside fixed calendar")
    coverage["internal_gap_n"] = last - first + 1 - coverage["nunique"]
    action_count = snapshot.actions.loc[snapshot.actions["code"].isin(allowed)].groupby("code").size()
    strata: dict[str, str | None] = {}
    selectors = {
        "long_history": coverage.loc[coverage["min"].eq(snapshot.calendar[0])].sort_values(["nunique"], ascending=False, kind="stable"),
        "new_listing": coverage.loc[coverage["min"].gt(pd.Timestamp("2019-01-01"))].sort_values(["min"], ascending=False, kind="stable"),
        "missing_calendar_slots": coverage.loc[coverage["internal_gap_n"].gt(0)].sort_values(["internal_gap_n"], ascending=False, kind="stable"),
        "corporate_actions": coverage
        .assign(action_n=action_count.reindex(coverage.index).fillna(0))
        .loc[coverage.index.isin(action_count.index)]
        .sort_values(["action_n"], ascending=False, kind="stable"),
        "truncated_tail": coverage.loc[coverage["max"].lt(snapshot.calendar[-1])].sort_values(["max"], ascending=True, kind="stable"),
    }
    for stratum, rows in selectors.items():
        strata[stratum] = None if rows.empty else str(rows.index[0])
    if strata["long_history"] is None:
        raise ValueError("representative long-history stratum unavailable")
    # One middle-length history makes the estimate less dependent on two tails.
    ordered = coverage.sort_values("nunique", kind="stable")
    strata["middle_history"] = str(ordered.index[len(ordered) // 2])
    return tuple(sorted({code for code in strata.values() if code is not None})), strata


def profile_requests(
    requests: list[dict[str, Any]], *, memory_bytes: int, estimated_worker_bytes: int, stocks_per_process: int = 1, timeout_seconds: float = 600.0
) -> dict[str, Any]:
    """Serial and 1/2/4-worker observation with independent compute directories.

    Every mode computes the same prices from scratch, rather than timing reuse.
    The resulting resource configuration is descriptive and pins its own inputs.
    """
    if not requests:
        raise ValueError("representative fixed requests required")
    profiles = []
    expected: list[dict[str, Any]] | None = None
    original = Path(requests[0]["run_root"])
    for workers in (1, 2, 4):
        run = _checked_path(original.parent / f"{original.name}-profile-w{workers}-{uuid.uuid4().hex}")
        (run / "prepared").mkdir(parents=True)
        # Prepared frames are mutable-input restatement snapshots, not published
        # shared feature/cache versions. Verified physical copies are explicit.
        from research_core.artifact_store import copy_verified

        packets = []
        for request in requests:
            source_path = _checked_path(Path(request["prepared_path"]))
            target = run / "prepared" / source_path.name
            copy_verified(source_path, target, request["prepared_sha256"])
            packets.append({**request, "run_root": str(run), "prepared_path": str(target)})
        receipt = run_requests(
            packets,
            workers=workers,
            memory_bytes=memory_bytes,
            estimated_worker_bytes=estimated_worker_bytes,
            stocks_per_process=stocks_per_process,
            timeout_seconds=timeout_seconds,
        )
        receipt["worker_overheads"] = [
            {
                "stock_codes": [stock["code"] for stock in worker["results"]],
                "bootstrap_and_response_seconds": None
                if "process_wall_seconds" not in worker
                else max(0.0, worker["process_wall_seconds"] - worker["measurement"]["wall_seconds"]),
                "verification_and_protocol_seconds": max(
                    0.0,
                    worker["measurement"]["wall_seconds"]
                    - sum(phase["wall_seconds"] for stock in worker["results"] for phase in stock.get("measurements", [])),
                ),
            }
            for worker in receipt["workers_receipts"]
        ]
        output = [{"code": row["code"], "artifacts": row["artifacts"], "rows": row["rows"]} for row in receipt["results"]]
        if expected is None:
            expected = output
        elif output != expected:
            raise ValueError("serial/parallel file identities or integer rows differ")
        profiles.append(receipt)
    peaks = [worker["job_memory"]["peak_committed_bytes"] for profile in profiles for worker in profile["workers_receipts"]]
    estimate = max(estimated_worker_bytes, int(np.ceil(max(peaks) * 1.25)))
    admissible = [profile for profile in profiles if profile["workers"] * estimate <= memory_bytes]
    if not admissible:
        raise ValueError("measured worker memory cannot fit finite resource budget")
    best = min(admissible, key=lambda profile: (profile["coordinator_measurement"]["wall_seconds"], profile["workers"]))
    return {
        "schema": "pattern-scan-resource-profile.v1",
        "source_id": requests[0]["source"]["source_id"],
        "input_id": requests[0]["input_id"],
        "codes": sorted(request["code"] for request in requests),
        "same_file_identities": True,
        "serial_reference_workers": 1,
        "profiles": profiles,
        "host_after": host_resources(),
        "selected": {
            "workers": best["workers"],
            "stocks_per_process": stocks_per_process,
            "inflight_processes": best["workers"],
            "active_stock_calculations_per_process": 1,
            "memory_cap_bytes": memory_bytes,
            "observed_peak_job_committed_bytes": max(peaks),
            "estimated_worker_bytes": estimate,
            "timeout_seconds": timeout_seconds,
        },
        "limitations": [
            "Profile estimates stock-independent work only; global summaries and publication need separate phase receipts.",
            "Lifetime working-set peaks and committed job memory have different scopes.",
        ],
    }
