"""Source-checked study cards; saved reports and legacy packages stay read-only."""

from __future__ import annotations

import copy
import logging
import re
import subprocess
import zlib
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from research_core.artifact_store import file_digest, relative_name, safe_path
from research_core.evidence import finite_json
from research_core.json_integrity import strict_json_object
from research_core.saved_research_studio import StudioError, read_studio_package, synthetic_studio_package
from research_core.scratch_runs import ScratchRunError, read_run
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "tasks/20261024-data-homes-and-scratch/study-card-v2.schema.json"
TASK_PATTERN = re.compile(r"[0-9]{8}-[a-z0-9][a-z0-9-]*")
MAX_CARD_BYTES = 64 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
LEGACY_TEXT_FIELDS = ("originalSummary", "conclusion", "originalTitle", "title", "sourceNote", "summary")


class StudyCardError(ValueError):
    """A card or its evidence cannot be verified."""


def _json(path: Path) -> dict[str, Any]:
    with safe_path(path).open("rb") as stream:
        raw = stream.read(MAX_CARD_BYTES + 1)
    if len(raw) > MAX_CARD_BYTES:
        raise StudyCardError("card exceeds size bound")
    try:
        value = strict_json_object(raw)
        finite_json(value)
    except (ValueError, RecursionError) as error:
        raise StudyCardError("invalid card JSON") from error
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = _json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _report_file(task: Path, name: str) -> Path:
    try:
        relative_name(name)
        path = safe_path(task / name)
    except ValueError as error:
        raise StudyCardError("unsafe report path") from error
    if not path.resolve().is_relative_to(task.resolve()) or not path.is_file():
        raise StudyCardError("report must be an existing file inside its task")
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise StudyCardError("report exceeds size bound")
    return path


def _warning(task: str, code: str, message: str) -> dict[str, str]:
    LOGGER.warning("Study card warning: task=%s code=%s", task, code)
    return {"task_id": task, "code": code, "message": message}


def read_study_card(
    task_root: Path,
    *,
    legacy_history: dict[str, dict[str, Any]] | None = None,
    shared_root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Validate one saved card; digest/run warnings retain the verified content.

    ``progress`` and ``run_state`` are response-only fields. A legacy excerpt
    must occur within one original history text field, never joined fields or a
    current-checkout history projection.
    """
    task = safe_path(task_root)
    card = _json(task / "study.json")
    error = next(_validator().iter_errors(card), None)
    if error is not None:
        raise StudyCardError("card does not match study-card.v2")
    if card["task_id"] != task.name:
        raise StudyCardError("card task identity mismatch")
    period = card["data_period"]
    if period is not None and period["from"] > period["to"]:
        raise StudyCardError("data period is reversed")
    reports = {key: _report_file(task, name) for key, name in card["report"].items() if name is not None}
    report = reports.get("markdown") or reports.get("web_report")
    provenance = card["provenance"]
    legacy_id = provenance["legacy_history_id"]
    if legacy_id is not None:
        if legacy_id != task.name or legacy_history is None or legacy_id not in legacy_history:
            raise StudyCardError("original legacy history item is unavailable")
        row = legacy_history[legacy_id]
        sources = [row[key] for key in LEGACY_TEXT_FIELDS if isinstance(row.get(key), str)]
    else:
        sources = [report.read_text(encoding="utf-8-sig")] if report is not None else []
    excerpts = [provenance["answer_source"], *(number["source_excerpt"] for number in card["key_numbers"])]
    for excerpt in excerpts:
        if excerpt is not None and (not excerpt.strip() or not any(excerpt in source for source in sources)):
            raise StudyCardError("excerpt is not contiguous original source text")
    warnings = []
    if report is None and legacy_id is None:
        warnings.append(_warning(task.name, "source_unavailable", "原始報告尚未找到，目前只保留待核對的任務卡片。"))
    digest = provenance["report_sha256"]
    if digest is not None:
        if report is None:
            raise StudyCardError("report digest requires a report file")
        if file_digest(report) != digest:
            warnings.append(_warning(task.name, "report_sha256_mismatch", "報告內容與登錄時不同，請核對這張卡片的來源。"))
    scratch = card["scratch_run"]
    if scratch is not None:
        try:
            root = shared_root if shared_root is not None else shared_data_root()
            run = read_run(root / "scratch" / task.name / scratch["run"])
            progress = run.get("progress")
            finite_json(progress)
            if progress is not None and not isinstance(progress, dict):
                raise StudyCardError("run progress must be an object")
            card["progress"] = copy.deepcopy(progress)
            card["run_state"] = run["state"]
        except (OSError, ValueError, ScratchRunError, subprocess.SubprocessError, RecursionError):
            warnings.append(_warning(task.name, "scratch_unavailable", "目前無法讀取執行進度，研究卡片仍可閱讀。"))
    return card, warnings


class StudyCards:
    """Read each task independently, caching only the immutable legacy package."""

    def __init__(self, tasks_root: Path, *, package_path: Path | None = None, shared_root: Path | None = None) -> None:
        self.tasks_root = tasks_root
        self.package_path = package_path
        self.shared_root = shared_root
        self._history: dict[str, dict[str, Any]] | None = None
        self._history_lock = Lock()

    def _legacy_history(self) -> dict[str, dict[str, Any]]:
        with self._history_lock:
            if self._history is None:
                if self.package_path is None or not self.package_path.is_absolute():
                    raise StudyCardError("absolute saved package path is required for legacy cards")
                package = read_studio_package(self.package_path)
                self._history = {row["id"]: row for row in package["researchHistory"]["items"]}
        return self._history

    def read(self, *, include_tooling: bool = False) -> dict[str, Any]:
        cards: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []
        try:
            tasks = sorted(safe_path(self.tasks_root).iterdir(), key=lambda path: path.name, reverse=True)
        except (OSError, ValueError):
            return {"cards": [], "warnings": [_warning("", "tasks_unavailable", "研究目錄目前無法讀取。請檢查本機設定。生效前不顯示研究卡片。")]}
        history: dict[str, dict[str, Any]] | None = None
        history_failed = False
        for task in tasks:
            try:
                if not task.is_dir():
                    continue
                if not TASK_PATTERN.fullmatch(task.name) and not (task / "study.json").is_file():
                    continue
                registration = _json(task / "study.json")
                if isinstance(registration.get("provenance"), dict) and registration["provenance"].get("legacy_history_id") is not None:
                    if history is None and not history_failed:
                        try:
                            history = self._legacy_history()
                        except (OSError, ValueError, StudioError, EOFError, zlib.error):
                            history_failed = True
                            LOGGER.warning("Original study-card history is unavailable")
                    if history_failed:
                        warnings.append(_warning(task.name, "legacy_unavailable", "舊研究的原始記錄目前無法核對，這張卡片暫時不顯示。"))
                        continue
                card, card_warnings = read_study_card(task, legacy_history=history, shared_root=self.shared_root)
                warnings.extend(card_warnings)
                if include_tooling or card["kind"] != "tooling":
                    cards.append(card)
            except (OSError, ValueError, RecursionError):
                warnings.append(_warning(task.name, "invalid_card", "研究卡片或引用來源無法核對，請檢查該任務的登錄。"))
        return {"cards": cards, "warnings": warnings}


def synthetic_study_cards(*, include_tooling: bool = False) -> dict[str, Any]:
    """Four deliberately fictional scenarios, with no local artifact reads."""
    rows = [
        ("20990101-fictional-complete", "study", "虛構示範：紙飛機條件有幫助嗎？", "虛構示範已完成，只用來展示研究卡片。", "mixed", "delivered"),
        ("20990102-fictional-running", "study", "虛構示範：彩色積木的比較進度", "虛構比較正在進行，尚未產生結論。", "running", "code_merged"),
        ("20990103-fictional-tooling", "tooling", "虛構示範：整理閱讀工具", "這是虛構的開發工作示範。", "not_evaluated", "code_merged"),
        ("20990104-fictional-account", "study", "虛構示範：早期帳戶模擬", "這是虛構的舊帳戶資料，只供介面示範。", "archived", None),
    ]
    cards = []
    for identity, kind, question, answer, verdict, delivery in rows:
        card: dict[str, Any] = {
            "schema": "study-card.v2",
            "task_id": identity,
            "kind": kind,
            "question": question,
            "answer": answer,
            "verdict": verdict,
            "data_period": None,
            "key_numbers": [],
            "limitation": "全部內容與進度均為虛構，不能作為投資或研究依據。",
            "report": {"web_report": None, "markdown": None},
            "account_run": None,
            "delivery_state": delivery,
            "scratch_run": None,
            "provenance": {"answer_source": None, "report_sha256": None, "publication": None, "shared_data": [], "legacy_history_id": None},
        }
        if verdict == "running":
            card.update(progress={"step": 2, "total": 5, "label": "虛構示範步驟"}, run_state="running")
        if verdict == "archived":
            card["account_run"] = {"run_id": synthetic_studio_package()["runs"][0]["id"], "period_note": "虛構帳戶示範（舊資料）"}
        if include_tooling or kind != "tooling":
            cards.append(card)
    return {"cards": cards, "warnings": []}
