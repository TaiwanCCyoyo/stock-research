"""Read-only, source-pinned direction discussion API tests over synthetic task files."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api import direction_discussions as api_module
from research_api.direction_discussions import create_direction_discussions_router
from research_core.direction_discussions import MAX_MODEL_BYTES

TASK_ID = "20261102-direction-discussion-test"
DRAFT_PATH = f"tasks/{TASK_ID}/direction-draft.md"
DRAFT_TEXT = "---\ntask_id: synthetic\nstage: discussing\n---\n\n測試草稿。\n"


def api_client(repo_root: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "local-private") -> TestClient:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", mode)
    application = FastAPI()
    application.include_router(create_direction_discussions_router(repo_root=repo_root))
    return TestClient(application)


def make_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repository"
    repo.mkdir()
    empty_template = tmp_path / "empty-git-template"
    empty_template.mkdir()
    task = repo / "tasks" / TASK_ID
    task.mkdir(parents=True)
    draft = task / "direction-draft.md"
    draft.write_text(DRAFT_TEXT, encoding="utf-8", newline="\n")
    git_environment = os.environ.copy()
    git_environment["GIT_CONFIG_NOSYSTEM"] = "1"
    global_config = tmp_path / "empty.gitconfig"
    global_config.write_text("", encoding="utf-8")
    git_environment["GIT_CONFIG_GLOBAL"] = str(global_config)

    def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
            env=git_environment,
            timeout=10,
        )

    run_git("init", f"--template={empty_template}")
    run_git("config", "user.name", "Test User")
    run_git("config", "user.email", "test@example.invalid")
    run_git("add", "--", DRAFT_PATH)
    run_git("-c", f"core.hooksPath={empty_template}", "-c", "commit.gpgsign=false", "commit", "-m", "add synthetic direction draft")
    revision = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=git_environment,
        timeout=10,
    ).stdout.strip()
    return repo, task, revision


def valid_model(task_id: str = TASK_ID, revision: str = "0" * 40, draft_path: str | None = None) -> dict[str, Any]:
    return {
        "schema": "direction-discussion.v1",
        "demo": False,
        "source": {
            "taskId": task_id,
            "draftPath": draft_path or f"tasks/{task_id}/direction-draft.md",
            "revision": revision,
        },
        "ownerPurpose": "了解訊號是否值得進一步研究",
        "purposeStatus": "pending",
        "outcomes": [
            {
                "id": "supports",
                "title": "如果成立",
                "headline": "條件成立的比例為 ▢▢%。",
                "decision": "把方向列為後續候選。",
                "limitation": "這不是停損規則。",
            },
            {
                "id": "does-not-support",
                "title": "如果不成立",
                "headline": "條件不成立時比例為 ▢▢%。",
                "decision": "重新選擇研究方向。",
                "limitation": "不代表其他訊號都無效。",
            },
            {
                "id": "unclear",
                "title": "如果分不出來",
                "headline": "目前還不能區分。",
                "decision": "先處理證據限制。",
                "limitation": "不確定不等於無效。",
            },
        ],
        "choices": [
            {
                "id": "C1",
                "question": "這次要回答到哪一步？",
                "options": [
                    {"id": "screen", "label": "先篩選候選", "impact": "工作較少，仍不代表有停損方法。"},
                    {"id": "compare", "label": "比較實際出場", "impact": "需要更多研究範圍與工作。"},
                ],
            }
        ],
        "questions": [
            {
                "reference": "20261031-prior#Q1",
                "question": "前作問題是否仍重要？",
                "status": "open",
                "reason": "尚未提供來源。",
                "source": "合成測試資料。",
            }
        ],
    }


def write_model(task: Path, model: dict[str, Any]) -> Path:
    preview = task / "preview"
    preview.mkdir(exist_ok=True)
    path = preview / "direction-discussion.json"
    path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    return path


def test_missing_model_returns_draft_only_and_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _, _ = make_repo(tmp_path)
    client = api_client(repo, monkeypatch)

    detail = client.get(f"/direction-drafts/{TASK_ID}")
    listing = client.get("/direction-drafts")

    assert detail.status_code == 200
    assert detail.json() == {
        "schema": "direction-draft.v1",
        "mode": "local-private",
        "taskId": TASK_ID,
        "status": "draft-only",
        "revision": None,
        "draftMarkdown": DRAFT_TEXT,
        "model": None,
        "message": "尚無可對照此草稿版本的互動模型；可先閱讀原始方向草稿。",
    }
    assert listing.json() == {
        "schema": "direction-drafts.v1",
        "mode": "local-private",
        "items": [
            {
                "taskId": TASK_ID,
                "status": "draft-only",
                "revision": None,
                "message": "尚無可對照此草稿版本的互動模型；可先閱讀原始方向草稿。",
            }
        ],
    }
    assert detail.headers["cache-control"] == listing.headers["cache-control"] == "no-store"


def test_matching_committed_model_is_ready_and_listing_is_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, task, revision = make_repo(tmp_path)
    model = valid_model(revision=revision)
    write_model(task, model)
    other_task = repo / "tasks" / "20261101-older-draft"
    other_task.mkdir()
    (other_task / "direction-draft.md").write_text("older synthetic draft", encoding="utf-8")
    client = api_client(repo, monkeypatch)

    detail = client.get(f"/direction-drafts/{TASK_ID}")
    listing = client.get("/direction-drafts")

    assert detail.status_code == 200
    assert detail.json()["status"] == "ready"
    assert detail.json()["revision"] == revision
    assert detail.json()["draftMarkdown"] == DRAFT_TEXT
    assert detail.json()["model"] == model
    assert detail.json()["mode"] == "local-private"
    assert [item["taskId"] for item in listing.json()["items"]] == ["20261101-older-draft", TASK_ID]
    assert listing.json()["items"][1]["revision"] == revision


def test_dirty_draft_mismatch_hides_model_but_keeps_safe_raw_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, task, revision = make_repo(tmp_path)
    write_model(task, valid_model(revision=revision))
    changed = DRAFT_TEXT + "草稿已修改。\n"
    (task / "direction-draft.md").write_text(changed, encoding="utf-8", newline="\n")
    client = api_client(repo, monkeypatch)

    detail = client.get(f"/direction-drafts/{TASK_ID}").json()

    assert detail["status"] == "unavailable"
    assert detail["revision"] is None
    assert detail["draftMarkdown"] == changed
    assert detail["model"] is None
    assert detail["message"]


def test_unknown_commit_returns_unavailable_with_raw_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, task, _ = make_repo(tmp_path)
    write_model(task, valid_model(revision="f" * 40))
    detail = api_client(repo, monkeypatch).get(f"/direction-drafts/{TASK_ID}").json()

    assert detail["status"] == "unavailable"
    assert detail["draftMarkdown"] == DRAFT_TEXT
    assert detail["model"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"source": {"taskId": "20261101-other-task"}},
        {"source": {"draftPath": "tasks/20261101-other-task/direction-draft.md"}},
    ],
)
def test_mismatched_task_or_draft_path_never_returns_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, dict[str, str]]) -> None:
    repo, task, revision = make_repo(tmp_path)
    model = valid_model(revision=revision)
    model["source"].update(change["source"])
    write_model(task, model)

    detail = api_client(repo, monkeypatch).get(f"/direction-drafts/{TASK_ID}").json()

    assert detail["status"] == "unavailable"
    assert detail["draftMarkdown"] == DRAFT_TEXT
    assert detail["model"] is None


@pytest.mark.parametrize("payload", [b"{broken", b"x" * (MAX_MODEL_BYTES + 1)], ids=["malformed", "oversize"])
def test_malformed_or_oversize_model_is_unavailable_with_safe_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    repo, task, _ = make_repo(tmp_path)
    model_path = task / "preview" / "direction-discussion.json"
    model_path.parent.mkdir()
    model_path.write_bytes(payload)

    detail = api_client(repo, monkeypatch).get(f"/direction-drafts/{TASK_ID}").json()

    assert detail["status"] == "unavailable"
    assert detail["draftMarkdown"] == DRAFT_TEXT
    assert detail["model"] is None
    assert detail["message"]


def test_hardlinked_model_is_rejected_without_losing_safe_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, task, revision = make_repo(tmp_path)
    source = tmp_path / "outside-model.json"
    source.write_text(json.dumps(valid_model(revision=revision)), encoding="utf-8")
    model_path = task / "preview" / "direction-discussion.json"
    model_path.parent.mkdir()
    try:
        os.link(source, model_path)
    except OSError as error:
        pytest.skip(f"hard links unavailable on this test filesystem: {error}")

    detail = api_client(repo, monkeypatch).get(f"/direction-drafts/{TASK_ID}").json()

    assert detail["status"] == "unavailable"
    assert detail["draftMarkdown"] == DRAFT_TEXT
    assert detail["model"] is None


def test_symlinked_draft_is_not_returned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, task, _ = make_repo(tmp_path)
    draft = task / "direction-draft.md"
    draft.unlink()
    outside = tmp_path / "outside-draft.md"
    outside.write_text(DRAFT_TEXT, encoding="utf-8")
    try:
        draft.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks unavailable on this test system: {error}")

    detail = api_client(repo, monkeypatch).get(f"/direction-drafts/{TASK_ID}").json()

    assert detail["status"] == "unavailable"
    assert detail["draftMarkdown"] is None
    assert detail["model"] is None


def test_public_mode_never_constructs_private_reader_or_reads_private_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_root = tmp_path / "private-root"
    task = private_root / "tasks" / TASK_ID
    task.mkdir(parents=True)
    (task / "direction-draft.md").write_text(DRAFT_TEXT, encoding="utf-8")

    def fail_if_constructed(*args: object, **kwargs: object) -> None:
        raise AssertionError("public mode constructed a private reader")

    monkeypatch.setattr(api_module, "DirectionDiscussionReader", fail_if_constructed)
    client = api_client(private_root, monkeypatch, mode="public-synthetic")

    assert client.get("/direction-drafts").json() == {
        "schema": "direction-drafts.v1",
        "mode": "public-synthetic",
        "items": [],
    }
    detail = client.get(f"/direction-drafts/{TASK_ID}")
    assert detail.status_code == 404
    assert private_root.exists()


@pytest.mark.parametrize(
    ("mode", "header"),
    [
        ("local-private", "public-synthetic"),
        ("public-synthetic", "local-private"),
        ("unknown-mode", "unknown-mode"),
    ],
)
def test_mode_mismatch_and_unknown_mode_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, header: str) -> None:
    client = api_client(tmp_path / "unused", monkeypatch, mode=mode)

    response = client.get("/direction-drafts", headers={"X-Research-Data-Mode": header})

    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "unavailable"
    assert response.headers["Cache-Control"] == "no-store"


def test_unknown_or_invalid_task_id_is_not_fabricated_and_post_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _, _ = make_repo(tmp_path)
    client = api_client(repo, monkeypatch)

    assert client.get("/direction-drafts/20261102-missing-task").status_code == 404
    assert client.get("/direction-drafts/wrong-id").status_code == 404
    assert client.post("/direction-drafts").status_code == 405
