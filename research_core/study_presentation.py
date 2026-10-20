"""Read opt-in study history registrations without changing saved evidence."""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any

from research_core.artifact_store import relative_name, safe_path
from research_core.evidence import EvidenceError, read_json, task_publications, text_field, validate_result

MAX_REGISTRATION_BYTES = 64 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024


def _file(root: Path, relative: str, maximum: int) -> Path:
    relative_name(relative)
    path = safe_path(root / relative)
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise EvidenceError("study presentation source must be a regular file inside its task")
    if path.stat().st_size > maximum:
        raise EvidenceError("study presentation source exceeds size bound")
    return path


def _item(tasks_root: Path, task: dict[str, Any]) -> dict[str, Any]:
    identity = task["task"]
    root = safe_path(tasks_root / identity)
    registration = read_json(_file(root, "presentation.json", MAX_REGISTRATION_BYTES))
    if not isinstance(registration, dict) or registration.get("schema") != "study-presentation.v1":
        raise EvidenceError("study presentation must use study-presentation.v1")
    if registration.get("task_id") != identity:
        raise EvidenceError("study presentation task identity mismatch")
    if registration.get("publication") != task.get("current_publication"):
        raise EvidenceError("study presentation must reference the current publication")
    report_path = task.get("report_path", "report.md")
    if registration.get("report_path") != report_path:
        raise EvidenceError("study presentation report must match the current publication")
    report = _file(root, report_path, MAX_REPORT_BYTES)
    with report.open("rb") as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES or hashlib.sha256(raw).hexdigest() != registration.get("report_sha256"):
        raise EvidenceError("study presentation report digest mismatch")
    content = raw.decode("utf-8-sig")
    summary = text_field(registration.get("summary"), "summary")
    title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), None)
    if registration.get("title") != title or not title or summary not in content:
        raise EvidenceError("study presentation title and summary must quote its report")
    section = registration.get("section")
    if section not in {"method", "market", "design"}:
        raise EvidenceError("study presentation section is invalid")
    # Same character set as the report route, plus the dated task prefix.
    if not re.fullmatch(r"[0-9]{8}-[A-Za-z0-9._-]+", identity):
        raise EvidenceError("study presentation task needs a dated, report-route-safe identity")
    day = date.fromisoformat(f"{identity[:4]}-{identity[4:6]}-{identity[6:8]}").isoformat()
    web_report = registration.get("web_report")
    if not isinstance(web_report, bool):
        raise EvidenceError("study presentation web_report must be boolean")
    web_reason = registration.get("web_report_reason")
    if web_reason is not None and not isinstance(web_reason, str):
        raise EvidenceError("study presentation web_report_reason must be text or null")
    if web_report:
        _file(root, "web-report/index.html", MAX_REPORT_BYTES)
    shared = registration.get("shared_data")
    if not isinstance(shared, list) or any(not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", value) for value in shared):
        raise EvidenceError("study presentation shared_data must contain catalog or family identifiers")
    reason = registration.get("shared_data_reason")
    if reason is not None and not isinstance(reason, str):
        raise EvidenceError("study presentation shared_data_reason must be text or null")
    if not shared:
        text_field(reason, "shared_data_reason")
    outcome = None
    result_relative = task.get("result_path", "research_result.json")
    if (root / result_relative).exists():
        result = validate_result(read_json(_file(root, result_relative, MAX_REGISTRATION_BYTES)))
        if result["study_id"] != identity:
            raise EvidenceError("study presentation result study identity mismatch")
        outcome = result["outcome"]
    return {
        "id": identity,
        "date": day,
        "dateBasis": "task-identifier-date-not-certified-completion-date",
        "title": title,
        "originalTitle": title,
        "section": section,
        "status": "已保存報告",
        "conclusion": summary,
        "originalSummary": summary,
        "reportPath": f"tasks/{identity}/{report_path}",
        "reportSha256": registration["report_sha256"],
        "currentPublication": task.get("current_publication"),
        "reviewConfirmed": False,
        "outcome": outcome,
        "draftStatus": None,
        "summarySource": "formal-report",
        "sourceNote": "逐字引用目前 checkout 已登錄的報告；不代表其他工作目錄的後續進度或最終採用。",
        "evidenceState": "published_report_not_owner_adoption",
        "registryEventIds": [],
        "webReportHref": f"#report/{identity}" if web_report else None,
        "webReportReason": web_reason,
        "sharedData": shared,
        "sharedDataReason": reason,
    }


def project_study_history(history: dict[str, Any], tasks_root: Path) -> dict[str, Any]:
    """Append or replace opted-in report projections after legacy integrity checks."""
    result = copy.deepcopy(history)
    rows = {row["id"]: row for row in result["items"]}
    for root in tasks_root.iterdir() if tasks_root.is_dir() else ():
        if not root.is_dir() or not (root / "presentation.json").exists():
            continue
        # Discover opt-ins before parsing any publication index. Unregistered
        # work-in-progress tasks must not invalidate unrelated history cards.
        root = safe_path(root)
        task: dict[str, Any] = {"task": root.name}
        publications = task_publications(root)
        if publications is not None:
            current = next(item for item in publications["publications"] if item["id"] == publications["current"])
            task.update(
                current_publication=publications["current"],
                report_path=current["report_path"],
                result_path=current["result_path"],
            )
        item = _item(tasks_root, task)
        previous = rows.get(item["id"])
        if previous is not None:
            item["registryEventIds"] = previous.get("registryEventIds", [])
            # Never erase a formal recorded result just because its local card is absent.
            if item["outcome"] is None:
                item["outcome"] = previous.get("outcome")
        rows[item["id"]] = item
    result["items"] = sorted(rows.values(), key=lambda row: (row["date"], row["id"]), reverse=True)
    result["historyProjection"] = "saved-history-plus-registered-checkout-reports"
    return result
