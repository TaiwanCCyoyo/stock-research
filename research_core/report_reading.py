"""Git-managed reading editions, independent of frozen study-card provenance."""

from __future__ import annotations

import logging
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from research_core.artifact_store import relative_name, safe_path
from research_core.json_integrity import strict_json_object
from research_core.study_cards import SCHEMA_PATH, TASK_PATTERN

LOGGER = logging.getLogger(__name__)
MAX_RECORD_BYTES = 64 * 1024
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 1000
MAX_SOURCES = 32

_TEXT = {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": r"\S"}
_DATE = {"type": "string", "format": "date", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
READING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "task_id", "state", "reason", "updated_at", "edition", "question", "answer", "limitation", "data_period", "sources"],
    "properties": {
        "schema": {"const": "report-reading.v1"},
        "task_id": {"type": "string", "pattern": r"^[0-9]{8}-[a-z0-9][a-z0-9-]*$", "maxLength": 180},
        "state": {"enum": ["ready", "in_progress", "history"]},
        "reason": _TEXT,
        "updated_at": _DATE,
        "edition": {"type": ["string", "null"], "maxLength": 500},
        "question": _TEXT,
        "answer": _TEXT,
        "limitation": _TEXT,
        "data_period": {
            "anyOf": [
                {"type": "null"},
                {"type": "object", "additionalProperties": False, "required": ["from", "to"], "properties": {"from": _DATE, "to": _DATE}},
            ]
        },
        "sources": {
            "type": "array",
            "maxItems": MAX_SOURCES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "path"],
                "properties": {"label": _TEXT, "path": {"type": "string", "minLength": 1, "maxLength": 500}},
            },
        },
    },
}
_READING_VALIDATOR = Draft202012Validator(READING_SCHEMA, format_checker=FormatChecker())


class ReportReadingError(ValueError):
    """Reading metadata or a declared Markdown source cannot be safely read."""


def _bytes(path: Path, limit: int) -> bytes:
    with safe_path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ReportReadingError("reading file exceeds size limit")
    return raw


def _object(path: Path) -> dict[str, Any]:
    return strict_json_object(_bytes(path, MAX_RECORD_BYTES))


def _task(root: Path, identity: str) -> Path:
    if not TASK_PATTERN.fullmatch(identity) or len(identity) > 180:
        raise ReportReadingError("invalid task identity")
    task = safe_path(root / identity)
    if not task.is_dir():
        raise ReportReadingError("task unavailable")
    return task


def _markdown(root: Path, name: str) -> str:
    relative_name(name)
    path = safe_path(root / name)
    if path.suffix.lower() != ".md" or not path.is_file() or not path.is_relative_to(safe_path(root)):
        raise ReportReadingError("Markdown must be an existing file inside its declared root")
    return _bytes(path, MAX_MARKDOWN_BYTES).decode("utf-8-sig")


def _source(root: Path, name: str) -> str:
    relative_name(name)
    parts = name.split("/")
    if len(parts) < 2:
        raise ReportReadingError("source must be inside a task")
    _task(root, parts[0])
    return _markdown(root, name)


@lru_cache(maxsize=1)
def _card_validator() -> Draft202012Validator:
    return Draft202012Validator(_object(SCHEMA_PATH), format_checker=FormatChecker())


class ReportReadings:
    """Bounded, read-only access to explicitly registered reading editions."""

    def __init__(self, tasks_root: Path) -> None:
        self.tasks_root = tasks_root

    def record(self, identity: str) -> dict[str, Any] | None:
        task = _task(self.tasks_root, identity)
        path = safe_path(task / "reading.json")
        if not path.exists():
            return None
        value = _object(path)
        if next(_READING_VALIDATOR.iter_errors(value), None) is not None or value["task_id"] != identity:
            raise ReportReadingError("invalid reading registration")
        period = value["data_period"]
        if period is not None and period["from"] > period["to"]:
            raise ReportReadingError("reversed reading period")
        edition = _markdown(task, value["edition"]) if value["edition"] is not None else None
        for source in value["sources"]:
            _source(self.tasks_root, source["path"])
        if value["state"] == "ready":
            if edition is None or not value["sources"]:
                raise ReportReadingError("ready reading requires an edition and sources")
            if value["answer"] not in edition or value["limitation"] not in edition:
                raise ReportReadingError("reading summary must occur in the edition")
        return value

    def read(self) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        original_reports: list[str] = []
        warnings: list[dict[str, str]] = []
        try:
            root = safe_path(self.tasks_root)
            tasks = list(islice((item for item in root.iterdir() if TASK_PATTERN.fullmatch(item.name)), MAX_RECORDS + 1))
            if len(tasks) > MAX_RECORDS:
                raise ReportReadingError("too many reading tasks")
        except (OSError, ValueError):
            return {"readings": [], "reading_warnings": [{"task_id": "", "code": "readings_unavailable", "message": "閱讀版本目錄目前無法讀取。"}]}
        for task in sorted(tasks, key=lambda item: item.name, reverse=True):
            try:
                record = self.record(task.name)
                if record is not None:
                    records.append(record)
                if record is None or record["edition"] is None:
                    try:
                        self.document(task.name)
                        original_reports.append(task.name)
                    except (OSError, ValueError, RecursionError):
                        pass  # An unavailable original is not a broken reading edition.
            except (OSError, ValueError, RecursionError):
                LOGGER.warning("Reading registration unavailable: task=%s", task.name)
                warnings.append({"task_id": task.name, "code": "reading_unavailable", "message": "閱讀版本或引用來源無法核對，暫時列為待整理。"})
        return {"readings": records, "reading_warnings": warnings, "original_reports": original_reports}

    def document(self, identity: str) -> dict[str, Any]:
        task = _task(self.tasks_root, identity)
        reading = self.record(identity)
        if reading is not None and reading["edition"] is not None:
            return {
                "task_id": identity,
                "reading": reading,
                "markdown": _markdown(task, reading["edition"]),
                "sources": reading["sources"],
                "state": reading["state"],
                "reason": reading["reason"],
            }
        card = _object(task / "study.json")
        if next(_card_validator().iter_errors(card), None) is not None or card["task_id"] != identity:
            raise ReportReadingError("original report registration is invalid")
        period = card["data_period"]
        if period is not None and period["from"] > period["to"]:
            raise ReportReadingError("original report period is reversed")
        name = card["report"]["markdown"]
        if name is None:
            raise ReportReadingError("no Markdown report is registered")
        return {
            "task_id": identity,
            "reading": reading,
            "markdown": _markdown(task, name),
            "sources": reading["sources"] if reading is not None else [],
            "state": reading["state"] if reading is not None else "history",
            "reason": reading["reason"] if reading is not None else "原始報告，尚未完成閱讀版核對；內容可能與舊登錄不同，請以原文及既有來源提醒為準。",
        }

    def source(self, identity: str, index: int) -> dict[str, str]:
        reading = self.record(identity)
        if reading is None or index < 0 or index >= len(reading["sources"]):
            raise ReportReadingError("source is not registered")
        source = reading["sources"][index]
        return {"markdown": _source(self.tasks_root, source["path"]), "label": source["label"]}
