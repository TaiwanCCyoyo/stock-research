"""Deterministic retained event and candidate audits, never outcome sampling."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import file_digest, read_json, verify_files
from research_core.derived_features_selective_v1 import PIVOT_DTYPES
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_analysis_v1 import group_frame
from research_core.pattern_scan_barrier_v1 import verified_parts, verify_barrier
from research_core.pattern_scan_conditions_v1 import FEATURES
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_event_conditions_v1 import H1_FIELDS
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.pattern_scan_reporting_v1 import candidate_membership
from research_core.pattern_scan_stock_v1 import h1_values
from research_core.research_data_catalog import DataCatalog, verify_entry
from research_core.research_data_paths import DataRoots

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditTables:
    raw_events: pd.DataFrame
    cold_events: pd.DataFrame
    conditions: pd.DataFrame
    candidates: pd.DataFrame
    pivots: pd.DataFrame


def read_legacy_h1(roots: DataRoots, catalog_snapshot: str) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """Read only the explicitly registered retained v4 raw-pattern evidence.

    The old eligibility column is retained, never used as a new S6 filter.
    Original hz_top/Z2 fields remain named provenance; no lower/support mapping
    is manufactured from incomplete historical metadata.
    """
    if not isinstance(catalog_snapshot, str) or not catalog_snapshot.strip() or catalog_snapshot == "latest":
        raise ValueError("explicit immutable legacy catalog snapshot required")
    descriptor: dict[str, Any] = {"catalog_snapshot": catalog_snapshot, "data_id": "hhhl-v4-descriptive", "status": "unknown", "reason": None}
    try:
        snapshot = DataCatalog(roots).read(catalog_snapshot)
    except FileNotFoundError:
        return None, {**descriptor, "reason": "catalog_snapshot_unavailable"}
    rows = [entry for entry in snapshot["entries"] if entry["data_id"] == "hhhl-v4-descriptive"]
    if not rows:
        return None, {**descriptor, "reason": "legacy_not_registered_in_pinned_catalog"}
    if len(rows) != 1 or rows[0]["reader"] != "metadata_only":
        raise ValueError("one exact metadata-only registered legacy v4 version required")
    entry = rows[0]
    manifest = verify_entry(entry, roots)
    descriptor.update(
        version_id=entry["version_id"],
        definition_version=entry["definition_version"],
        manifest=entry["manifest"],
        coverage=entry["coverage"],
        limitations=entry["limitations"],
        legacy_window=manifest.get("window"),
        original_rule=manifest.get("rule"),
        eligibility_scope="Retained old base_eligible is provenance; not filtered or equal to current S6",
    )
    artifacts = manifest.get("artifacts", {})
    record = artifacts.get("events.parquet") if isinstance(artifacts, dict) else None
    if not isinstance(record, dict) or not {"sha256", "bytes"}.issubset(record):
        return None, {**descriptor, "reason": "legacy_events_descriptor_unavailable"}
    relative = (Path(entry["manifest"]["path"]).parent / "events.parquet").as_posix()
    path = roots.artifact_path(entry["manifest"]["scope"], relative)
    if not path.is_file():
        return None, {**descriptor, "reason": "retained_legacy_events_unavailable"}

    def verify_payload() -> None:
        if path.stat().st_size != record["bytes"] or file_digest(path) != record["sha256"]:
            raise ValueError("retained legacy events hash/size mismatch")
        verify_entry(entry, roots)

    verify_payload()
    table = read_frame(path)
    if not table.columns.is_unique or not {"security_id", "pattern"}.issubset(table):
        raise ValueError("legacy events require explicit raw-pattern membership")
    date_column = "asof_date" if "asof_date" in table else "t0" if "t0" in table else None
    if date_column is None:
        raise ValueError("legacy events lack declared confirmation date")
    pattern = cast(pd.Series, table["pattern"])
    if not pattern.map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError("legacy raw pattern observations must be known boolean")
    selected = cast(pd.DataFrame, table.loc[pattern.eq(True)]).copy()
    confirmation_dates = cast(pd.Series, pd.to_datetime(selected[date_column], errors="raise"))
    if confirmation_dates.isna().any() or not confirmation_dates.eq(confirmation_dates.dt.normalize()).all():
        raise ValueError("legacy confirmation dates must be known midnight sessions")
    selected["t0"] = confirmation_dates.dt.strftime("%Y-%m-%d")
    if selected.security_id.isna().any() or selected.t0.isna().any():
        raise ValueError("legacy event stock/date identity missing")
    if {"has_old", "has_recent_far"}.issubset(selected):
        for field in ("has_old", "has_recent_far"):
            if not cast(pd.Series, selected[field]).map(lambda value: isinstance(value, (bool, np.bool_))).all():
                raise ValueError("declared legacy overhead observations must be boolean")
        selected["subtype_id"] = np.where(selected.has_old | selected.has_recent_far, "P-over", "P-clean")
    elif "subtype_id" not in selected:
        descriptor["subtype_reason"] = "no_declared_subtype_or_overhead_fields"
    verify_payload()
    descriptor.update(
        status="available", reason=None, events_descriptor={"path": relative, **record}, retained_pattern_rows=len(selected), base_eligibility_filtered=False
    )
    LOGGER.info("Read pinned legacy H1 events=%d snapshot=%s", len(selected), catalog_snapshot)
    return selected.reset_index(drop=True), descriptor


def _same(left: Any, right: Any) -> bool:
    if pd.isna(left) or pd.isna(right):
        return bool(pd.isna(left) and pd.isna(right))
    if isinstance(left, (float, np.floating)) and isinstance(right, (float, np.floating)):
        return bool(np.isclose(left, right, rtol=1e-12, atol=1e-12))
    return bool(left == right)


def _known(value: Any) -> Any:
    return None if pd.isna(value) else value.item() if isinstance(value, np.generic) else value


def legacy_overlap_audit(current: pd.DataFrame, legacy: pd.DataFrame | None) -> pd.DataFrame:
    """Outer stock/date overlap after 2019; unavailable evidence stays unknown."""
    columns = pd.Index(("security_id", "t0", "current_n", "legacy_n", "status", "reason", "metadata_differences_json"))
    if legacy is None:
        return pd.DataFrame(
            [
                {
                    "security_id": None,
                    "t0": None,
                    "current_n": len(current),
                    "legacy_n": None,
                    "status": "unknown",
                    "reason": "legacy_unavailable",
                    "metadata_differences_json": "[]",
                }
            ],
            columns=columns,
        )
    for frame in (current, legacy):
        if not {"security_id", "t0"}.issubset(frame) or cast(pd.Series, frame[["security_id", "t0"]].isna().any()).any():
            raise ValueError("legacy overlap requires explicit stock/date identities")
        for day in frame.t0:
            if not isinstance(day, str) or cast(pd.Timestamp, pd.Timestamp(day)).strftime("%Y-%m-%d") != day:
                raise ValueError("legacy overlap dates must be canonical ISO")
    current = cast(pd.DataFrame, current.loc[current.t0.ge("2019-01-01")])
    legacy = cast(pd.DataFrame, legacy.loc[legacy.t0.ge("2019-01-01")])
    current_keys = current.groupby(["security_id", "t0"]).size()
    legacy_keys = legacy.groupby(["security_id", "t0"]).size()
    rows = []
    keys = cast(set[tuple[str, str]], set(current_keys.index) | set(legacy_keys.index))
    for security, day in sorted(keys):
        left = current.loc[current.security_id.eq(security) & current.t0.eq(day)]
        right = legacy.loc[legacy.security_id.eq(security) & legacy.t0.eq(day)]
        differences = []
        for name in ("subtype_id", "pivot", "support", "lower"):
            if name in left and name in right:
                l_values = sorted(json.dumps(_known(value), default=str) for value in left[name])
                r_values = sorted(json.dumps(_known(value), default=str) for value in right[name])
                if l_values != r_values:
                    differences.append({"field": name, "current": l_values, "legacy": r_values})
        ln, rn = len(left), len(right)
        status = "current_only" if rn == 0 else "legacy_only" if ln == 0 else "different" if ln != rn or differences else "matched_observation"
        rows.append({
            "security_id": security,
            "t0": day,
            "current_n": ln,
            "legacy_n": rn,
            "status": status,
            "reason": "membership_or_metadata_difference" if status != "matched_observation" else "observed_rows_only_not_eligibility_parity",
            "metadata_differences_json": json.dumps(differences, sort_keys=True),
        })
    return pd.DataFrame(rows, columns=columns)


def build_audit(
    parts: Mapping[str, Path],
    event_parts: Mapping[str, Mapping[str, Path]],
    selections: Mapping[str, Any],
    *,
    source: dict[str, Any],
    input_id: str,
    barrier: dict[str, Any],
) -> AuditTables:
    """Audit first ten raw/cold events and first five declared candidates.

    Ordering is target/security/date/event ID and target/candidate ID. All stock
    parts, event parts and global receipts are verified before sample selection.
    Missing legacy evidence is reported separately by legacy_overlap_audit.
    """
    verified_parts([read_json(directory / "receipt.json") for directory in parts.values()], source=source, input_id=input_id)
    verify_barrier(barrier)
    order = ["pattern_id", "security_id", "t0", "event_id"]
    raw: pd.DataFrame | None = None
    cold: pd.DataFrame | None = None

    def sample(previous: pd.DataFrame | None, rows: pd.DataFrame) -> pd.DataFrame:
        local = rows.sort_values(order, kind="stable").head(10)
        combined = local if previous is None else pd.concat([previous, local], ignore_index=True)
        return combined.sort_values(order, kind="stable").head(10).reset_index(drop=True)

    for code, directory in sorted(parts.items()):
        raw = sample(raw, read_frame(directory / "raw_events.parquet"))
    for target, stocks in sorted(event_parts.items()):
        for code, directory in sorted(stocks.items()):
            receipt = read_json(directory / "receipt.json")
            identity = receipt["identity"]
            if receipt.get("complete") is not True or identity["source_id"] != source["source_id"] or identity["input_id"] != input_id:
                raise ValueError("audit event part identity differs")
            verify_files(directory, receipt["artifacts"])
            events = read_frame(directory / "events.parquet")
            cold = sample(cold, events.loc[events.pattern_id.eq(target) & events.horizon.eq(126)])
    if raw is None or cold is None:
        raise ValueError("audit requires declared stock and event-part collections")
    contexts: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    stored_conditions: dict[tuple[str, str], pd.DataFrame] = {}
    for code in sorted({row["security_id"][3:] for row in cold.to_dict("records")}):
        directory = parts[code]
        indicators = read_frame(directory / "indicators.parquet")
        pivots = read_frame(directory / "pivots.parquet")
        common = read_frame(directory / "common_values.parquet")
        global_record = barrier["global_files"][code]
        global_path = Path(global_record["path"])
        if file_digest(global_path) != global_record["sha256"]:
            raise ValueError("audit global identity changed")
        global_values = read_frame(global_path)
        if not global_values.index.equals(indicators.index):
            raise ValueError("audit global common calendar differs")
        for name in global_values:
            if name not in {"security_id", "t0", "calendar_index"}:
                common[name] = global_values[name]
        contexts[code] = indicators, pivots, common
    for target, code in sorted({(row["pattern_id"], row["security_id"][3:]) for row in cold.to_dict("records")}):
        stored_conditions[(target, code)] = read_frame(event_parts[target][code] / "conditions.parquet").set_index("event_id")
    condition_rows: list[dict[str, Any]] = []
    pivot_rows: list[dict[str, Any]] = []
    for event in cold.to_dict("records"):
        code = event["security_id"][3:]
        frame, supplied_pivots, common = contexts[code]
        t = int(event["calendar_index"])
        details = json.loads(event["details_json"])
        for key, value in details.items():
            if "confirmation" in key and key.endswith("_index") and (not isinstance(value, int) or value > t):
                raise ValueError("event references a future pivot/structure confirmation")
            if "confirmed" in key and key.endswith("date") and pd.Timestamp(value) > frame.index[t]:
                raise ValueError("event references a future confirmation date")
        available = supplied_pivots.loc[supplied_pivots.confirmation_index.le(t)]
        for row in available.to_dict("records"):
            if pd.Timestamp(row["confirmed_at"]) > frame.index[t]:
                raise ValueError("pivot index/date availability differs")
            pivot_rows.append({"event_id": event["event_id"], "t0": event["t0"], "future_pivots_excluded_n": len(supplied_pivots) - len(available), **row})
        independent = calculate_common_values(frame.iloc[: t + 1], available).iloc[t]
        h1 = h1_values(pd.DataFrame([event]), frame).iloc[0] if event["pattern_id"] == "H1" else None
        stored = stored_conditions[(event["pattern_id"], code)].loc[event["event_id"]]
        for feature in FEATURES:
            if feature in H1_FIELDS:
                expected, origin = (h1[feature] if h1 is not None else None), "H1_source_override" if h1 is not None else "not_applicable"
            elif feature == "G" and h1 is not None:
                expected, origin = h1[feature], "H1_source_override"
            elif feature == "SR_support":
                expected = float(frame.Close.iloc[t]) / event["support"] - 1 if pd.notna(event["support"]) else None
                origin = "event_support_override"
            elif feature == f"PAT_other_{event['pattern_id']}":
                expected, origin = None, "not_applicable"
            elif feature in {"SR_a", "SR_b"}:
                expected, origin = independent.get(feature), "past_only_public_pivot_definition"
            else:
                expected, origin = common.iloc[t].get(feature), "common_or_global_t0"
                if feature.startswith("PAT_other_"):
                    expected = None if pd.isna(expected) or expected == -1 else bool(expected)
            actual = stored[feature]
            # Explicit applicability can intentionally suppress a supplied value.
            if stored[f"{feature}_status"] == "not_applicable":
                expected = None
            same = _same(actual, expected)
            condition_rows.append({
                "event_id": event["event_id"],
                "feature_id": feature,
                "stored_value_json": json.dumps(_known(actual), default=str),
                "expected_value_json": json.dumps(_known(expected), default=str),
                "status": stored[f"{feature}_status"],
                "reason": stored[f"{feature}_reason"],
                "reference": origin,
                "matches": same,
            })
            if not same:
                raise ValueError(f"stored audited condition differs: {feature}")
    candidate_rows = []
    declared = sorted((target, row["candidate_id"], row) for target, selected in selections.items() for row in selected["candidates"])
    for target, identifier, candidate in declared[:5]:
        atoms = tuple(Atom(**atom) for atom in candidate["atoms"])
        for code, directory in sorted(event_parts[target].items()):
            frame = group_frame(directory, "pattern:union", 126)
            fast = candidate_membership(frame, atoms)
            slow = []
            for row in frame.to_dict("records"):
                statuses = [row[f"{atom.feature_id}_status"] for atom in atoms]
                slow.append(
                    -2
                    if "not_applicable" in statuses
                    else 0
                    if any(row[f"{atom.feature_id}_status"] == "known" and row[f"{atom.feature_id}_bin"] != atom.bin_id for atom in atoms)
                    else -1
                    if "feature_unknown" in statuses
                    else 1
                )
            if not np.array_equal(fast, np.asarray(slow, dtype=np.int8)):
                raise ValueError("candidate audit membership differs")
            candidate_rows.append({
                "target": target,
                "candidate_id": identifier,
                "security_id": f"TW:{code}",
                "event_n": len(frame),
                "known_matching_event_ids_json": json.dumps(sorted(frame.loc[fast == 1, "event_id"].tolist())),
                "membership_states_json": json.dumps([int(value) for value in fast]),
                "matches": True,
            })
    LOGGER.info("Audited retained raw=%d cold=%d conditions=%d candidates=%d", len(raw), len(cold), len(condition_rows), len(candidate_rows))
    return AuditTables(
        raw,
        cold,
        pd.DataFrame(
            condition_rows, columns=pd.Index(("event_id", "feature_id", "stored_value_json", "expected_value_json", "status", "reason", "reference", "matches"))
        ),
        pd.DataFrame(
            candidate_rows,
            columns=pd.Index(("target", "candidate_id", "security_id", "event_n", "known_matching_event_ids_json", "membership_states_json", "matches")),
        ),
        pd.DataFrame(pivot_rows, columns=pd.Index(("event_id", "t0", "future_pivots_excluded_n", *PIVOT_DTYPES))),
    )
