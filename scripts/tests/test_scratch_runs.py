"""Scratch-run labels, liveness by OS lock, delivery identity, dependencies and Windows deletion safety."""

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
OTHER = "20261024-consumer"


def _git(repo: Path, *args: str) -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
    )


def _publish(repo: Path) -> None:
    """Commit everything and point origin/main at it, as a merged PR would."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "results")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")


@pytest.fixture()
def roots(tmp_path: Path) -> tuple[Path, Path]:
    shared, repo = tmp_path / "shared", tmp_path / "repo"
    (shared / "scratch").mkdir(parents=True)
    (repo / "tasks" / TASK).mkdir(parents=True)
    (repo / "tasks" / TASK / "summary.json").write_text('{"v": 1}')
    _git(repo, "init", "-q")
    _publish(repo)
    return shared / "scratch", repo


def _create(roots: tuple[Path, Path], run: str = "q2-q6-v6", task: str = TASK, depends_on: list[str] | None = None) -> sr.ScratchRun:
    scratch, repo = roots
    return sr.create_run(task, run, purpose="resume Q2-Q6", owner="codex", depends_on=depends_on or [], root=scratch, repo_root=repo)


def _verdicts(roots: tuple[Path, Path], now: datetime | None = None) -> dict[str, str]:
    scratch, repo = roots
    return {f"{status.task}/{status.run}": status.verdict for status in sr.survey(scratch, now=now, repo_root=repo)}


def _abandoned(roots: tuple[Path, Path], run: str, files: dict[str, bytes] | None = None) -> Path:
    with _create(roots, run) as created:
        for name, payload in (files or {}).items():
            (created.path / name).parent.mkdir(parents=True, exist_ok=True)
            (created.path / name).write_bytes(payload)
        created.mark("abandoned", reason="superseded")
        return created.path


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
        assert _verdicts(roots) == {f"{TASK}/q2-q6-v6": sr.IN_USE}
        with pytest.raises(sr.ScratchRunError, match="in use"):
            sr.open_run(TASK, "q2-q6-v6", root=scratch, repo_root=repo)
    with sr.open_run(TASK, "q2-q6-v6", root=scratch, repo_root=repo) as resumed:
        resumed.heartbeat(progress={"step": 3, "total": 10, "label": "B3 conditions"})
    status = sr.survey(scratch, repo_root=repo)[0]
    assert (status.verdict, status.progress) == (sr.PAUSED, {"step": 3, "total": 10, "label": "B3 conditions"})


def test_transitions_and_delivery_identity(roots: tuple[Path, Path]) -> None:
    scratch, _ = roots
    final = scratch.parent / "tasks" / TASK / "q2-q6"
    final.mkdir(parents=True)
    (final / "B1.parquet").write_bytes(b"table")
    with _create(roots) as run:
        with pytest.raises(sr.ScratchRunError, match="cannot move"):
            run.mark("delivered", results=[str(final)])
        run.mark("complete")
        with pytest.raises(sr.ScratchRunError, match="must list"):
            run.mark("delivered")
        with pytest.raises(sr.ScratchRunError, match="scratch area"):
            run.mark("delivered", results=[str(run.path)])
        with pytest.raises(sr.ScratchRunError, match="does not exist"):
            run.mark("delivered", results=[str(scratch.parent / "missing")])
        with pytest.raises(sr.ScratchRunError, match="scratch space"):
            run.mark("delivered", results=[".tmp/x"])
        run.mark("delivered", results=[str(final), f"tasks/{TASK}/summary.json", f"tasks/{TASK}"])
        with pytest.raises(sr.ScratchRunError, match="cannot move"):
            run.mark("abandoned", reason="late")
    record = json.loads((scratch / TASK / "q2-q6-v6" / "run.json").read_text())
    kinds = [(result["kind"], result["path"]) for result in record["results"]]
    assert kinds == [("shared", str(final.resolve())), ("repository", f"tasks/{TASK}/summary.json"), ("repository", f"tasks/{TASK}")]
    assert record["results"][0]["files"]["B1.parquet"]["bytes"] == 5
    assert _verdicts(roots) == {f"{TASK}/q2-q6-v6": sr.DELETABLE}


def test_an_unmerged_new_version_of_a_merged_file_is_not_delivered(roots: tuple[Path, Path]) -> None:
    _, repo = roots
    (repo / "tasks" / TASK / "summary.json").write_text('{"v": 2}')
    with _create(roots) as run:
        run.mark("complete")
        with pytest.raises(sr.ScratchRunError, match="differs from origin/main"):
            run.mark("delivered", results=[f"tasks/{TASK}/summary.json"])
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "v2 on a branch only")
        with pytest.raises(sr.ScratchRunError, match="differs from origin/main"):
            run.mark("delivered", results=[f"tasks/{TASK}/summary.json"])
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        run.mark("delivered", results=[f"tasks/{TASK}/summary.json"])


@pytest.mark.parametrize("extra", ["new-result.json", "nested/part.parquet"])
def test_uncommitted_files_in_a_tracked_directory_are_not_delivered(roots: tuple[Path, Path], extra: str) -> None:
    _, repo = roots
    target = repo / "tasks" / TASK / extra
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}")
    with _create(roots) as run:
        run.mark("complete")
        with pytest.raises(sr.ScratchRunError, match="content not on origin/main"):
            run.mark("delivered", results=[f"tasks/{TASK}"])


def test_a_result_later_removed_or_rewritten_sends_the_run_to_the_owner(roots: tuple[Path, Path]) -> None:
    scratch, repo = roots
    final = scratch.parent / "tasks" / TASK
    final.mkdir(parents=True)
    (final / "table.parquet").write_bytes(b"12345")
    with _create(roots) as run:
        run.mark("complete")
        run.mark("delivered", results=[str(final), f"tasks/{TASK}/summary.json"])
    assert _verdicts(roots) == {f"{TASK}/q2-q6-v6": sr.DELETABLE}
    # Same size, different bytes: only the digest check just before deletion sees it.
    (final / "table.parquet").write_bytes(b"54321")
    with pytest.raises(sr.ScratchRunError, match="cannot be verified"):
        sr.clean(scratch, apply=True, repo_root=repo)
    (final / "table.parquet").write_bytes(b"12345")
    # A main that never contained the recorded commit loses the identity.
    _git(repo, "checkout", "-q", "--orphan", "rewritten")
    _git(repo, "rm", "-rqf", ".")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "history rewritten")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert _verdicts(roots) == {f"{TASK}/q2-q6-v6": sr.ASK_OWNER}
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
    assert _verdicts(roots) == {
        f"{TASK}/done": sr.AWAITING_DELIVERY,
        f"{TASK}/stale": sr.PAUSED,
        f"{TASK}/unlabelled": sr.ASK_OWNER,
        "loose-folder/": sr.ASK_OWNER,
    }
    assert _verdicts(roots, now=later)[f"{TASK}/stale"] == sr.ASK_OWNER


def test_clean_is_a_dry_run_unless_applied_and_spares_everything_else(roots: tuple[Path, Path]) -> None:
    scratch, repo = roots
    _abandoned(roots, "gone", {"_temporary/part.parquet": b"x"})
    with _create(roots, "kept"):
        pass
    assert [status.run for status in sr.clean(scratch, repo_root=repo)] == ["gone"]
    assert (scratch / TASK / "gone").is_dir()
    with _create(roots, "busy") as busy:
        busy.mark("abandoned", reason="superseded")
        assert [status.run for status in sr.clean(scratch, apply=True, repo_root=repo)] == ["gone"]
    assert not (scratch / TASK / "gone").exists()
    assert (scratch / TASK / "kept" / "run.json").is_file()
    assert (scratch / TASK / "busy" / "run.json").is_file()


@pytest.mark.parametrize("consumer_open", [True, False], ids=["running-consumer", "paused-consumer"])
@pytest.mark.parametrize("subpath", ["", "_temporary", "_temporary/part.parquet"], ids=["whole-run", "subdirectory", "file"])
def test_unfinished_consumers_keep_the_runs_they_depend_on(roots: tuple[Path, Path], consumer_open: bool, subpath: str) -> None:
    scratch, repo = roots
    producer = _abandoned(roots, "a", {"_temporary/part.parquet": b"x"})
    dependency = producer / subpath if subpath else producer
    consumer = _create(roots, "b", task=OTHER, depends_on=[str(dependency)])
    if not consumer_open:
        consumer.close()
    try:
        assert _verdicts(roots)[f"{TASK}/a"] == sr.IN_USE
        assert sr.clean(scratch, apply=True, repo_root=repo) == []
        assert (producer / "_temporary" / "part.parquet").read_bytes() == b"x"
    finally:
        consumer.close()
    with sr.open_run(OTHER, "b", root=scratch, repo_root=repo) as finished:
        finished.mark("abandoned", reason="done with a")
    assert {status.run for status in sr.clean(scratch, apply=True, repo_root=repo)} == {"a", "b"}
    assert not producer.exists()


def test_a_complete_consumer_still_protects_its_input(roots: tuple[Path, Path]) -> None:
    producer = _abandoned(roots, "a", {"part.parquet": b"x"})
    with _create(roots, "b", task=OTHER, depends_on=[str(producer / "part.parquet")]) as consumer:
        consumer.mark("complete")
    assert _verdicts(roots)[f"{TASK}/a"] == sr.IN_USE


def test_deletion_rechecks_dependents_under_the_deps_lock(roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """A consumer registered after survey but before deletion stops the deletion."""
    scratch, repo = roots
    producer = _abandoned(roots, "a", {"part.parquet": b"x"})
    original = sr.survey

    def survey_then_register(*args: object, **kwargs: object) -> list[sr.RunStatus]:
        statuses = original(*args, **kwargs)  # type: ignore[arg-type]
        _create(roots, "late", task=OTHER, depends_on=[str(producer / "part.parquet")]).close()
        return statuses

    monkeypatch.setattr(sr, "survey", survey_then_register)
    with pytest.raises(sr.ScratchRunError, match="still needed"):
        sr.clean(scratch, apply=True, repo_root=repo)
    assert (producer / "part.parquet").is_file()


@pytest.mark.parametrize("level", ["task", "scratch", "shared"])
def test_dependencies_above_a_single_run_are_refused(roots: tuple[Path, Path], level: str) -> None:
    scratch, _ = roots
    _abandoned(roots, "a", {"part.parquet": b"x"})
    parent = {"task": scratch / TASK, "scratch": scratch, "shared": scratch.parent}[level]
    with pytest.raises(sr.ScratchRunError, match="one scratch run"):
        _create(roots, "b", task=OTHER, depends_on=[str(parent)])
    assert not (scratch / OTHER / "b").exists()


def test_a_parent_dependency_registered_after_the_final_check_is_refused(roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """The race the refusal closes: nothing can claim a whole task directory mid-clean."""
    scratch, repo = roots
    producer = _abandoned(roots, "a", {"part.parquet": b"x"})
    original = sr._dependents
    refused: list[str] = []

    def check_then_register(root: Path, target: Path) -> list[str]:
        found = original(root, target)
        try:
            _create(roots, "late", task=OTHER, depends_on=[str(producer.parent)]).close()
        except sr.ScratchRunError as error:
            refused.append(str(error))
        return found

    monkeypatch.setattr(sr, "_dependents", check_then_register)
    sr.clean(scratch, apply=True, repo_root=repo)
    assert refused and all("one scratch run" in message for message in refused)
    assert not (scratch / OTHER / "late").exists()


def test_registering_a_dependency_waits_for_a_deletion_in_progress(roots: tuple[Path, Path]) -> None:
    scratch, _ = roots
    producer = _abandoned(roots, "a", {"part.parquet": b"x"})
    deleting = sr._lock(producer, sr.DEPS_LOCK_FILE)
    try:
        with pytest.raises(sr.ScratchRunError, match="being cleaned"):
            _create(roots, "b", task=OTHER, depends_on=[str(producer / "part.parquet")])
    finally:
        sr._unlock(deleting)
    assert not (scratch / OTHER / "b").exists()


def test_dependencies_must_be_absolute_and_exist_when_inside_scratch(roots: tuple[Path, Path], tmp_path: Path) -> None:
    scratch, _ = roots
    with pytest.raises(sr.ScratchRunError, match="absolute"):
        _create(roots, "rel", depends_on=["relative/input"])
    with pytest.raises(sr.ScratchRunError, match="does not exist"):
        _create(roots, "ghost", task=OTHER, depends_on=[str(scratch / TASK / "nothing" / "part.parquet")])
    with _create(roots, "dep", depends_on=[str(tmp_path / "input")]) as run:
        assert run.record["depends_on"] == [str((tmp_path / "input").resolve())]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction")
def test_clean_refuses_a_run_containing_a_junction_and_keeps_its_target(roots: tuple[Path, Path], tmp_path: Path) -> None:
    scratch, repo = roots
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.bin").write_bytes(b"keep")
    with _create(roots) as run:
        junction = run.path / "linked"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(precious)], check=True, capture_output=True)
        run.mark("abandoned", reason="test")
    try:
        with pytest.raises(ValueError, match="reparse"):
            sr.clean(scratch, apply=True, repo_root=repo)
    finally:
        os.rmdir(junction)
    assert (precious / "keep.bin").read_bytes() == b"keep"
    assert (scratch / TASK / "q2-q6-v6" / "run.json").is_file()
