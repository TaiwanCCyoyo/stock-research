"""Read-only, source-pinned direction discussion artifacts for the local dashboard."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from research_core.artifact_store import read_json, safe_path

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_ID_RE = re.compile(r"^[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION_RE = re.compile(r"^[a-fA-F0-9]{40}$")
QUESTION_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*#Q[1-9][0-9]*$")
CHOICE_ID_RE = re.compile(r"^C[1-9][0-9]*$")
OPTION_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
BRANCH_IDS = {"supports", "does-not-support", "unclear"}
MAX_DRAFT_BYTES = 256 * 1024
MAX_MODEL_BYTES = 256 * 1024
GIT_TIMEOUT_SECONDS = 5

MESSAGE_DRAFT_ONLY = "尚無可對照此草稿版本的互動模型；可先閱讀原始方向草稿。"
MESSAGE_UNAVAILABLE = "互動討論資料目前無法確認與草稿版本一致；可先閱讀安全讀取的原始草稿。"


class DirectionDiscussionNotFound(LookupError):
    """The requested task does not contain a discoverable direction draft."""


class DirectionDiscussionUnavailable(RuntimeError):
    """A configured private source could not be read safely."""


class _UnsafeArtifact(ValueError):
    pass


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique_strings(values: list[Any]) -> bool:
    return all(isinstance(value, str) for value in values) and len(set(values)) == len(values)


def _validate_model_shape(model: dict[str, Any], task_id: str, draft_path: str) -> str:
    """Validate renderer-required structure without interpreting research prose."""
    if model.get("schema") != "direction-discussion.v1" or model.get("demo") is not False:
        raise ValueError("unsupported or demo discussion model")

    source = model.get("source")
    if not isinstance(source, dict):
        raise ValueError("discussion source must be an object")
    revision = source.get("revision")
    if source.get("taskId") != task_id or source.get("draftPath") != draft_path or not isinstance(revision, str) or REVISION_RE.fullmatch(revision) is None:
        raise ValueError("discussion source does not identify this task and draft")

    if not _nonempty_text(model.get("ownerPurpose")) or model.get("purposeStatus") not in {"pending", "confirmed"}:
        raise ValueError("discussion purpose fields are invalid")

    outcomes = model.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 3 or not all(isinstance(item, dict) for item in outcomes):
        raise ValueError("discussion outcomes must contain three objects")
    outcome_ids = [item.get("id") for item in outcomes]
    if not _unique_strings(outcome_ids) or set(outcome_ids) != BRANCH_IDS:
        raise ValueError("discussion outcome IDs are invalid")
    for item in outcomes:
        if not all(_nonempty_text(item.get(key)) for key in ("title", "headline", "decision", "limitation")):
            raise ValueError("discussion outcome fields are incomplete")

    choices = model.get("choices")
    questions = model.get("questions")
    if not isinstance(choices, list) or not isinstance(questions, list):
        raise ValueError("discussion choices and questions must be lists")
    if not all(isinstance(item, dict) for item in choices + questions):
        raise ValueError("discussion choices and questions must contain objects")

    choice_ids = [choice.get("id") for choice in choices]
    if not _unique_strings(choice_ids):
        raise ValueError("discussion choice IDs are duplicated or invalid")
    for choice in choices:
        if CHOICE_ID_RE.fullmatch(choice["id"]) is None or not _nonempty_text(choice.get("question")):
            raise ValueError("discussion choice fields are invalid")
        options = choice.get("options")
        if not isinstance(options, list) or len(options) < 2 or not all(isinstance(option, dict) for option in options):
            raise ValueError("each discussion choice needs at least two options")
        option_ids = [option.get("id") for option in options]
        if not _unique_strings(option_ids):
            raise ValueError("discussion option IDs are duplicated or invalid")
        for option in options:
            if (
                not isinstance(option["id"], str)
                or OPTION_ID_RE.fullmatch(option["id"]) is None
                or not _nonempty_text(option.get("label"))
                or not _nonempty_text(option.get("impact"))
            ):
                raise ValueError("discussion option fields are invalid")

    question_refs = [question.get("reference") for question in questions]
    if not _unique_strings(question_refs):
        raise ValueError("discussion question references are duplicated or invalid")
    for question in questions:
        if QUESTION_REFERENCE_RE.fullmatch(question["reference"]) is None:
            raise ValueError("discussion question reference is invalid")
        if not all(_nonempty_text(question.get(key)) for key in ("question", "status", "reason", "source")):
            raise ValueError("discussion question fields are incomplete")
    return revision


def _safe_regular_file(path: Path, max_bytes: int) -> tuple[Path, os.stat_result]:
    try:
        checked = safe_path(path)
        info = checked.lstat()
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as error:
        raise _UnsafeArtifact("unsafe artifact path") from error
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise _UnsafeArtifact("artifact must be an unlinked regular file")
    if info.st_size > max_bytes:
        raise _UnsafeArtifact("artifact exceeds size limit")
    return checked, info


def _read_bounded_file(path: Path, max_bytes: int) -> bytes:
    checked, _ = _safe_regular_file(path, max_bytes)
    try:
        with checked.open("rb") as stream:
            payload = stream.read(max_bytes + 1)
    except OSError as error:
        raise _UnsafeArtifact("artifact could not be read") from error
    if len(payload) > max_bytes:
        raise _UnsafeArtifact("artifact exceeds size limit")
    return payload


class DirectionDiscussionReader:
    """Read task drafts and only expose models pinned to the exact current draft bytes."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (Path(repo_root) if repo_root is not None else REPO_ROOT).absolute()

    @staticmethod
    def _unavailable(task_id: str, markdown: str | None = None) -> dict[str, Any]:
        return {
            "schema": "direction-draft.v1",
            "taskId": task_id,
            "status": "unavailable",
            "revision": None,
            "draftMarkdown": markdown,
            "model": None,
            "message": MESSAGE_UNAVAILABLE,
        }

    def _directory(self, path: Path) -> Path:
        try:
            checked = safe_path(path)
            info = checked.lstat()
        except FileNotFoundError:
            raise
        except (OSError, ValueError) as error:
            raise _UnsafeArtifact("unsafe directory path") from error
        if not stat.S_ISDIR(info.st_mode):
            raise _UnsafeArtifact("expected a regular directory")
        return checked

    def _tasks_root(self) -> Path:
        root = self._directory(self.repo_root)
        try:
            return self._directory(root / "tasks")
        except FileNotFoundError:
            return root / "tasks"

    def _read_draft(self, task_id: str) -> tuple[bytes, str]:
        task_dir = self._task_directory(task_id)
        raw = _read_bounded_file(task_dir / "direction-draft.md", MAX_DRAFT_BYTES)
        try:
            markdown = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _UnsafeArtifact("draft is not UTF-8") from error
        return raw, markdown

    def _task_directory(self, task_id: str) -> Path:
        try:
            root = self._directory(self.repo_root)
            tasks_root = self._directory(root / "tasks")
        except FileNotFoundError as error:
            raise DirectionDiscussionUnavailable("task root is missing") from error
        try:
            return self._directory(tasks_root / task_id)
        except FileNotFoundError as error:
            raise DirectionDiscussionNotFound(task_id) from error

    def _read_model(self, task_id: str) -> dict[str, Any] | None:
        model_path = self._tasks_root() / task_id / "preview" / "direction-discussion.json"
        try:
            checked, _ = _safe_regular_file(model_path, MAX_MODEL_BYTES)
        except FileNotFoundError:
            return None
        return read_json(checked, max_bytes=MAX_MODEL_BYTES)

    def _git(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        try:
            return subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True,
                check=False,
                env=environment,
                timeout=GIT_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("source revision could not be checked") from error

    def _source_matches(self, revision: str, task_id: str, draft_bytes: bytes) -> bool:
        revision = revision.lower()
        commit = self._git("cat-file", "-t", revision)
        if commit.returncode or commit.stdout.strip() != b"commit":
            return False
        relative = f"tasks/{task_id}/direction-draft.md"
        object_name = f"{revision}:{relative}"
        entry = self._git("ls-tree", revision, "--", relative)
        fields = entry.stdout.rstrip(b"\r\n").split(None, 2)
        if entry.returncode or len(fields) != 3 or fields[0] not in {b"100644", b"100755"} or fields[1] != b"blob":
            return False
        blob_id = fields[2].split(b"\t", 1)[0]
        if re.fullmatch(rb"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", blob_id) is None:
            return False
        size = self._git("cat-file", "-s", blob_id.decode("ascii"))
        if size.returncode:
            return False
        try:
            blob_size = int(size.stdout.strip())
        except ValueError:
            return False
        if not 0 <= blob_size <= MAX_DRAFT_BYTES:
            return False
        shown = self._git("show", object_name)
        return shown.returncode == 0 and len(shown.stdout) <= MAX_DRAFT_BYTES and shown.stdout == draft_bytes

    def _inspect(self, task_id: str, raw: bytes, markdown: str) -> dict[str, Any]:
        try:
            model = self._read_model(task_id)
        except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError, _UnsafeArtifact) as error:
            LOGGER.warning("direction discussion model unavailable for task %s: %s", task_id, type(error).__name__)
            return self._unavailable(task_id, markdown)
        if model is None:
            return {
                "schema": "direction-draft.v1",
                "taskId": task_id,
                "status": "draft-only",
                "revision": None,
                "draftMarkdown": markdown,
                "model": None,
                "message": MESSAGE_DRAFT_ONLY,
            }
        draft_path = f"tasks/{task_id}/direction-draft.md"
        try:
            revision = _validate_model_shape(model, task_id, draft_path)
            if not self._source_matches(revision, task_id, raw):
                return self._unavailable(task_id, markdown)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            LOGGER.warning("direction discussion source unavailable for task %s: %s", task_id, type(error).__name__)
            return self._unavailable(task_id, markdown)
        return {
            "schema": "direction-draft.v1",
            "taskId": task_id,
            "status": "ready",
            "revision": revision,
            "draftMarkdown": markdown,
            "model": model,
            "message": None,
        }

    def _inspect_task(self, task_id: str, *, missing_is_not_found: bool) -> dict[str, Any]:
        try:
            raw, markdown = self._read_draft(task_id)
        except DirectionDiscussionNotFound:
            raise
        except FileNotFoundError as error:
            if missing_is_not_found:
                raise DirectionDiscussionNotFound(task_id) from error
            raise
        except (OSError, ValueError, _UnsafeArtifact) as error:
            LOGGER.warning("direction draft unavailable for task %s: %s", task_id, type(error).__name__)
            return self._unavailable(task_id)
        return self._inspect(task_id, raw, markdown)

    def list_items(self) -> list[dict[str, Any]]:
        try:
            tasks_root = self._tasks_root()
            entries = list(tasks_root.iterdir()) if tasks_root.exists() else []
        except (OSError, ValueError, _UnsafeArtifact) as error:
            raise DirectionDiscussionUnavailable("task drafts are unavailable") from error
        items: list[dict[str, Any]] = []
        for entry in entries:
            task_id = entry.name
            if TASK_ID_RE.fullmatch(task_id) is None:
                continue
            try:
                self._directory(entry)
                detail = self._inspect_task(task_id, missing_is_not_found=False)
            except DirectionDiscussionNotFound:
                continue
            except FileNotFoundError:
                continue
            except (OSError, ValueError, _UnsafeArtifact) as error:
                LOGGER.warning("direction draft unavailable for task %s: %s", task_id, type(error).__name__)
                detail = self._unavailable(task_id)
            if detail["status"] == "unavailable" and detail["draftMarkdown"] is None:
                # An unsafe task path is never read or exposed as a discovered draft.
                try:
                    self._directory(entry)
                except (OSError, ValueError, _UnsafeArtifact):
                    continue
            item = {key: detail[key] for key in ("taskId", "status", "revision", "message")}
            item["title"] = detail["model"]["ownerPurpose"] if detail["model"] is not None else "方向草稿"
            items.append(item)
        return sorted(items, key=lambda item: item["taskId"])

    def detail(self, task_id: str) -> dict[str, Any]:
        if TASK_ID_RE.fullmatch(task_id) is None:
            raise DirectionDiscussionNotFound(task_id)
        try:
            return self._inspect_task(task_id, missing_is_not_found=True)
        except FileNotFoundError as error:
            raise DirectionDiscussionNotFound(task_id) from error
