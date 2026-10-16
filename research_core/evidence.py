"""Headless discovery and explicit evidence contracts, independent of dashboard code.

Legacy files remain readable and unregistered. File existence, a task name containing
"confirmation", and an execution receipt never establish scientific acceptance.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

from research_core.artifact_store import relative_name, safe_path

RESULT_VERSION = "research-result.v1"
REGISTRY_VERSION = "research-registry.v1"
OUTCOMES = {"not_evaluated", "candidate_failed", "candidate_passed", "invalid_measurement", "data_blocked", "incomplete"}


class EvidenceError(ValueError):
    """Malformed, unavailable or inconsistent evidence (not strategy failure)."""


def finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise EvidenceError("non-finite JSON number")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvidenceError("JSON object keys must be strings")
            finite_json(item)
    elif isinstance(value, list):
        for item in value:
            finite_json(item)
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise EvidenceError("unsupported JSON value")


def read_json(path: Path) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, ValueError) as error:
        raise EvidenceError(f"cannot read JSON {path}: {error}") from error
    finite_json(value)
    return value


def text_field(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{name}: required nonempty string")
    return value


def date_window(value: Any) -> tuple[date, date]:
    if not isinstance(value, dict):
        raise EvidenceError("window: required object")
    try:
        start = date.fromisoformat(text_field(value.get("start"), "start"))
        end = date.fromisoformat(text_field(value.get("end"), "end"))
    except ValueError as error:
        raise EvidenceError("window: invalid dates") from error
    if start > end:
        raise EvidenceError("window: start after end")
    return start, end


def validate_result(value: Any) -> dict[str, Any]:
    """Validate the new report envelope, not the scientific truth of its claims."""
    if not isinstance(value, dict) or value.get("schema_version") != RESULT_VERSION:
        raise EvidenceError(f"result must use {RESULT_VERSION}")
    finite_json(value)
    for name in ("study_id", "candidate_id", "run_id", "phase"):
        text_field(value.get(name), name)
    if value["phase"] not in {"exploration", "discovery", "confirmation", "holdout", "replication"}:
        raise EvidenceError("unknown phase")
    if value.get("outcome") not in OUTCOMES:
        raise EvidenceError("outcome must distinguish research failure from incomplete/invalid evidence")
    versions = value.get("identities")
    if not isinstance(versions, dict):
        raise EvidenceError("identities: required object")
    for key in ("owner_contract", "metric_contract", "execution_contract", "data_snapshot", "code", "runtime"):
        text_field(versions.get(key), f"identities.{key}")
    date_window(value.get("window"))
    metrics = value.get("metrics")
    if not isinstance(metrics, dict):
        raise EvidenceError("metrics: required object")
    for key, metric in metrics.items():
        if not isinstance(metric, dict) or metric.get("unit") not in {"fraction", "percent", "TWD", "count", "trading_days", "ratio"}:
            raise EvidenceError(f"metrics.{key}: explicit supported unit required")
        number = metric.get("value")
        if number is None:
            text_field(metric.get("unavailable_reason"), f"metrics.{key}.unavailable_reason")
        elif isinstance(number, bool) or not isinstance(number, (int, float)):
            raise EvidenceError(f"metrics.{key}.value: number or null required")
        elif "unavailable_reason" in metric:
            raise EvidenceError(f"metrics.{key}: a measured number cannot also be unavailable")
    for key in ("artifacts", "limitations", "supersedes"):
        values = value.get(key)
        if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
            raise EvidenceError(f"{key}: string list required")
        if len(values) != len(set(values)):
            raise EvidenceError(f"{key}: duplicate entries")
    if value["run_id"] in value["supersedes"]:
        raise EvidenceError("a result cannot supersede itself")
    return value


def validate_registry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != REGISTRY_VERSION:
        raise EvidenceError(f"registry must use {REGISTRY_VERSION}")
    if value.get("history_complete") is not False:
        raise EvidenceError("this bootstrap registry does not certify complete exposure history")
    events = value.get("events")
    if not isinstance(events, list):
        raise EvidenceError("events: required list")
    known: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise EvidenceError("event must be an object")
        identity = text_field(event.get("id"), "event.id")
        if identity in known:
            raise EvidenceError("duplicate registry event id")
        known.add(identity)
        for key in ("source", "recorded_on", "note"):
            text_field(event.get(key), key)
        date.fromisoformat(event["recorded_on"])
        if event.get("kind") == "exposure":
            text_field(event.get("scope"), "scope")
            if event.get("state") != "viewed":
                raise EvidenceError("exposure records are positive viewed evidence, never a reset")
            date_window(event.get("window"))
        elif event.get("kind") == "correction":
            targets = event.get("supersedes")
            if not isinstance(targets, list) or not targets or any(not isinstance(target, str) for target in targets):
                raise EvidenceError("correction needs unique superseded evidence references")
            if len(set(targets)) != len(targets):
                raise EvidenceError("duplicate correction target")
            for target in targets:
                text_field(target, "supersedes")
            if identity in targets:
                raise EvidenceError("self correction")
        else:
            raise EvidenceError("unknown event kind")
    return value


def exposure_status(registry: dict[str, Any], scope: str, window: dict[str, str]) -> dict[str, Any]:
    """Any matching overlap is viewed; absence is UNKNOWN, never unseen."""
    validate_registry(registry)
    start, end = date_window(window)
    matches = []
    for event in registry["events"]:
        if event["kind"] != "exposure" or event["scope"] not in {scope, "*"}:
            continue
        left, right = date_window(event["window"])
        if left <= end and start <= right:
            matches.append(event["id"])
    return {"state": "viewed_overlap" if matches else "unknown", "events": matches, "certifies_unseen": False}


def task_catalog(tasks_root: Path) -> list[dict[str, Any]]:
    """List artifact availability without reading economics or opening run folders."""
    if not tasks_root.is_dir():
        return []
    rows = []
    for path in tasks_root.iterdir():
        if not path.is_dir() or path.is_symlink() or not path.resolve().is_relative_to(tasks_root.resolve()):
            continue
        available = {name: (path / name).is_file() for name in ("mission.md", "report.md", "summary.json", "research_result.json")}
        publications = task_publications(path)
        if not any(available.values()) and publications is None:
            continue
        # Never parse a possibly sealed result merely to list a study.
        row = {
            "task": path.name,
            "mtime": path.stat().st_mtime,
            "artifacts": available,
            "evidence_state": "registered_unread" if available["research_result.json"] else "legacy_unregistered",
            "outcome": "unknown",
        }
        if publications is not None:
            current = next(item for item in publications["publications"] if item["id"] == publications["current"])
            row.update(
                current_publication=publications["current"],
                publications=publications["publications"],
                report_path=current["report_path"],
                result_path=current["result_path"],
                evidence_state="registered_unread",
            )
        rows.append(row)
    return sorted(rows, key=lambda item: (item["mtime"], item["task"]), reverse=True)


def safe_identifier(value: Any, name: str) -> str:
    result = text_field(value, name)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", result):
        raise EvidenceError(f"{name}: unsafe identifier")
    return result


def task_publications(task_root: Path) -> dict[str, Any] | None:
    """Resolve an explicit small publication index without reading result cards.

    Paths are relative to this task. Absence preserves legacy discovery; malformed
    indexes never fall back to the root report or infer a newer directory.
    """
    try:
        root = safe_path(task_root)
        index = safe_path(root / "publications.json")
        if not index.exists():
            return None
        if not index.is_file() or index.stat().st_size > 64 * 1024:
            raise EvidenceError("publication index must be a small regular JSON file")
        value = read_json(index)
        if not isinstance(value, dict) or value.get("schema") != "research-publications.v1":
            raise EvidenceError("publication index must use research-publications.v1")
        if value.get("study_id") != root.name:
            raise EvidenceError("publication index study_id must match its task")
        current = safe_identifier(value.get("current"), "publication current")
        entries = value.get("publications")
        if not isinstance(entries, list) or not entries:
            raise EvidenceError("publication index needs a nonempty publications list")
        seen: set[str] = set()
        resolved = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise EvidenceError("publication entry must be an object")
            identity = safe_identifier(entry.get("id"), "publication id")
            if identity in seen:
                raise EvidenceError("duplicate publication id")
            seen.add(identity)
            item = {"id": identity}
            for key, suffix in (("report", ".md"), ("result", ".json")):
                relative = relative_name(text_field(entry.get(key), f"publication {key}"))
                target = safe_path(root / relative)
                if not target.is_relative_to(root) or target.suffix != suffix or not target.is_file():
                    raise EvidenceError(f"publication {key} must name an existing task-local {suffix} file")
                item[f"{key}_path"] = relative
            resolved.append(item)
        if current not in seen:
            raise EvidenceError("publication current does not identify a listed version")
        return {"current": current, "publications": resolved}
    except EvidenceError:
        raise
    except (OSError, ValueError) as error:
        raise EvidenceError(f"invalid publication index for {task_root.name}: {error}") from error
