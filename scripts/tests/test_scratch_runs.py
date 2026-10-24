"""Scratch-run labels, liveness by OS lock, the cleaning rules and Windows deletion safety."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from research_core import scratch_runs as sr

TASK = "20261013-pattern-scan"


@pytest.fixture()
def roots(tmp_path: Path) -> tuple[Path, Path]:
    shared, repo = tmp_path / "shared", tmp_path / "repo"
    (shared / "scratch").mkdir(parents=True)
    (repo / "tasks" / TASK).mkdir(parents=True)
    (repo / "tasks" / TASK / "summary.json").write_text("{}")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "results")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return shared / "scratch", repo


def _git(repo: Path, *args: str) -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args], cwd=repo, env=environment, check=True, capture_output=True)


def _create(roots: tuple[Path, Path], run: str = "q2-q6-v6") -> sr.ScratchRun:
    scratch, repo = roots
    return sr.create_run(TASK, run, purpose="resume Q2-Q6", owner="codex", root=scratch, repo_root=repo)


def _verdicts(scratch: Path, now: datetime | None = None, repo: Path | None = None) -> dict[str, str]:
    return {f"{status.task}/{status.run}": status.verdict for status in sr.survey(scratch, now=now, repo_root=repo)}


def test_create_writes_a_running_label_and_refuses_a_duplicate(roots: tuple[Path, Path]) -> None:
    with _create(roots) as run:
        record = json.loads((run.path / "run.json").read_text())
        assert (record["schema"], record["task"], record["state"], record["owner"]) == (sr.SCHEMA, TASK, "running", "codex")
    with pytest.raises(sr.ScratchRunError, match="already exists"):
        _create(roots)


@pytest.mark.parametrize("task,run", [("pattern-scan", "v1"), (TASK, "../x"), (TASK, "Upper"), ("20261013-x/..", "v1")])
def test_ids_are_validated(roots: tuple[Path, Path], task: str, run: str) -> None:
    with pytest.raises(sr.ScratchRunError):
        sr.create_run(task, run, purpose="p", owner="o", root=roots[0], repo_root=roots[1])


def test_open_run_is_refused_while_another_holder_has_the_lock(roots: tuple[Path, Path]) -> None:
    scratch, repo = roots
    with _create(roots):
        assert _verdicts(scratch) == {f"{TASK}/q2-q6-v6": sr.IN_USE}
        with pytest.raises(sr.ScratchRunError, match="in use"):
            sr.open_run(TASK, "q2-q6-v6", root=scratch, repo_root=repo)
    with sr.open_run(TASK, "q2-q6-v6", root=scratch, repo_root=repo) as resumed:
        resumed.heartbeat(progress={"step": 3, "total": 10, "label": "B3 conditions"})
    status = sr.survey(scratch)[0]
    assert (status.verdict, status.progress) == (sr.PAUSED, {"step": 3, "total": 10, "label": "B3 conditions"})


def test_transitions_and_delivery_rules(roots: tuple[Path, Path]) -> None:
    scratch, repo = roots
    shared = scratch.parent
    (repo / "tasks" / TASK / "uncommitted.json").write_text("{}")
    final = shared / "tasks" / TASK / "q2-q6"
    final.mkdir(parents=True)
    with _create(roots) as run:
        with pytest.raises(sr.ScratchRunError, match="cannot move"):
            run.mark("delivered", results=[str(final)])
        run.mark("complete")
        with pytest.raises(sr.ScratchRunError, match="must list"):
            run.mark("delivered")
        with pytest.raises(sr.ScratchRunError, match="scratch area"):
            run.mark("delivered", results=[str(run.path)])
        with pytest.raises(sr.ScratchRunError, match="does not exist"):
            run.mark("delivered", results=[str(shared / "missing")])
        with pytest.raises(sr.ScratchRunError, match="scratch space"):
            (repo / ".tmp").mkdir()
            run.mark("delivered", results=[".tmp"])
        with pytest.raises(sr.ScratchRunError, match="not on origin/main"):
            run.mark("delivered", results=[f"tasks/{TASK}/uncommitted.json"])
        run.mark("delivered", results=[str(final), f"tasks/{TASK}/summary.json"])
        with pytest.raises(sr.ScratchRunError, match="cannot move"):
            run.mark("abandoned", reason="late")
    assert _verdicts(scratch, repo=repo) == {f"{TASK}/q2-q6-v6": sr.DELETABLE}
    (repo / "tasks" / TASK / "summary.json").unlink()
    _git(repo, "commit", "-q", "-am", "drop results")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert _verdicts(scratch, repo=repo) == {f"{TASK}/q2-q6-v6": sr.ASK_OWNER}
    assert sr.clean(scratch, apply=True, repo_root=repo) == []
    assert (scratch / TASK / "q2-q6-v6" / "run.json").is_file()


def test_abandon_needs_a_reason(roots: tuple[Path, Path]) -> None:
    with _create(roots) as run:
        with pytest.raises(sr.ScratchRunError, match="reason"):
            run.mark("abandoned", reason=" ")
        run.mark("abandoned", reason="owner stopped Q2-Q6")


def test_survey_classifies_stale_complete_and_unlabelled(roots: tuple[Path, Path]) -> None:
    scratch, _ = roots
    with _create(roots, "stale"):
        pass
    with _create(roots, "done") as run:
        run.mark("complete")
    (scratch / TASK / "unlabelled").mkdir()
    (scratch / "loose-folder").mkdir()
    later = datetime.now(timezone.utc) + sr.STALE_AFTER + timedelta(days=1)
    assert _verdicts(scratch) == {
        f"{TASK}/done": sr.AWAITING_DELIVERY,
        f"{TASK}/stale": sr.PAUSED,
        f"{TASK}/unlabelled": sr.ASK_OWNER,
        "loose-folder/": sr.ASK_OWNER,
    }
    assert _verdicts(scratch, now=later)[f"{TASK}/stale"] == sr.ASK_OWNER


def test_delivered_run_whose_results_vanished_goes_to_the_owner(roots: tuple[Path, Path]) -> None:
    scratch = roots[0]
    final = scratch.parent / "tasks" / TASK
    final.mkdir(parents=True)
    with _create(roots) as run:
        run.mark("complete")
        run.mark("delivered", results=[str(final)])
    final.rmdir()
    assert _verdicts(scratch) == {f"{TASK}/q2-q6-v6": sr.ASK_OWNER}


def test_clean_is_a_dry_run_unless_applied_and_spares_everything_else(roots: tuple[Path, Path]) -> None:
    scratch = roots[0]
    with _create(roots, "gone") as run:
        (run.path / "_temporary").mkdir()
        (run.path / "_temporary" / "part.parquet").write_bytes(b"x")
        run.mark("abandoned", reason="superseded")
    with _create(roots, "kept"):
        pass
    assert [status.run for status in sr.clean(scratch)] == ["gone"]
    assert (scratch / TASK / "gone").is_dir()
    with _create(roots, "busy") as busy:
        busy.mark("abandoned", reason="superseded")
        assert [status.run for status in sr.clean(scratch, apply=True)] == ["gone"]
    assert not (scratch / TASK / "gone").exists()
    assert (scratch / TASK / "kept" / "run.json").is_file()
    assert (scratch / TASK / "busy" / "run.json").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction")
def test_clean_refuses_a_run_containing_a_junction_and_keeps_its_target(roots: tuple[Path, Path], tmp_path: Path) -> None:
    scratch = roots[0]
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.bin").write_bytes(b"keep")
    with _create(roots) as run:
        junction = run.path / "linked"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(precious)], check=True, capture_output=True)
        run.mark("abandoned", reason="test")
    try:
        with pytest.raises(ValueError, match="reparse"):
            sr.clean(scratch, apply=True)
    finally:
        os.rmdir(junction)
    assert (precious / "keep.bin").read_bytes() == b"keep"
    assert (scratch / TASK / "q2-q6-v6" / "run.json").is_file()


def test_dependencies_are_recorded_as_absolute_paths(roots: tuple[Path, Path], tmp_path: Path) -> None:
    scratch, repo = roots
    with pytest.raises(sr.ScratchRunError, match="absolute"):
        sr.create_run(TASK, "rel", purpose="p", owner="o", depends_on=["relative/input"], root=scratch, repo_root=repo)
    with sr.create_run(TASK, "dep", purpose="p", owner="o", depends_on=[str(tmp_path / "input")], root=scratch, repo_root=repo) as run:
        assert run.record["depends_on"] == [str(tmp_path / "input")]
