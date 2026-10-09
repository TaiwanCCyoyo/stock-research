import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import worktree_inventory as wi

SCRIPT = Path(wi.__file__).resolve()


def test_human_output_surfaces_pr_head_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = {
        "path": "checkout",
        "branch": "topic",
        "head": "new-head",
        "last_commit_date": "2026-10-08",
        "status": {"tracked_dirty": 0, "untracked": 0},
        "ignored": {"bytes": 0, "errors": []},
        "errors": [],
        "pr": wi.classify_prs([pr(1, "MERGED", "old-head")], "new-head"),
    }
    monkeypatch.setattr(wi, "inventory", lambda *args: {"worktrees": [entry]})
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert wi.main() == 0
    output = capsys.readouterr().out
    assert "base=main final_head=old-head matches_head=False" in output
    assert "do not clean up based on this PR state" in output


def run_git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", "user.name=Inventory Test", "-c", "user.email=inventory@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def test_real_cli_dirty_ignored_and_detached_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    run_git(repo, "init", "--initial-branch=main")
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "Initial fixture")
    probe = tmp_path / "probe with spaces"
    run_git(repo, "worktree", "add", "--detach", str(probe), "HEAD")
    (repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (repo / "ignored" / "nested").mkdir(parents=True)
    (repo / "ignored" / "a.bin").write_bytes(b"12345")
    (repo / "ignored" / "nested" / "b.bin").write_bytes(b"123")
    before = run_git(repo, "status", "--porcelain=v1", "-z")
    index_before = (repo / ".git" / "index").read_bytes()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--json", "--no-pr"],
        capture_output=True,
        check=True,
        timeout=30,
    )
    output = json.loads(result.stdout)
    entries = {Path(entry["path"]).resolve(): entry for entry in output["worktrees"]}
    primary = entries[repo.resolve()]
    assert primary["branch"] == "main"
    assert primary["status"] == {"tracked_dirty": 1, "untracked": 1}
    assert primary["ignored"] == {"bytes": 8, "measured_bytes": 8, "errors": [], "excluded_paths": []}
    assert primary["last_commit_date"]
    assert primary["pr"]["classification"] == "unknown"
    assert "--no-pr" in primary["pr"]["reason"]
    detached = entries[probe.resolve()]
    assert detached["detached"] is True
    assert detached["probe_candidate"] is True
    assert detached["status"] == {"tracked_dirty": 0, "untracked": 0}
    assert "ownership unknown" in detached["pr"]["reason"]
    assert run_git(repo, "status", "--porcelain=v1", "-z") == before
    assert (repo / ".git" / "index").read_bytes() == index_before

    human = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--no-pr"],
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert b"tracked_dirty" in human.stdout
    assert b"ignored_bytes=8" in human.stdout


def test_real_nested_worktree_is_measured_independently(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "--initial-branch=main")
    (repo / ".gitignore").write_text(".worktrees/\nignored/\n", encoding="utf-8")
    (repo / "tracked.bin").write_bytes(b"tracked contents" * 10)
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "Nested worktree fixture")
    probe = repo / ".worktrees" / "probe"
    run_git(repo, "worktree", "add", "--detach", str(probe), "HEAD")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "data.bin").write_bytes(b"123")
    (repo / ".worktrees" / "unregistered").mkdir()
    (repo / ".worktrees" / "unregistered" / "data.bin").write_bytes(b"1234")
    (probe / "ignored").mkdir()
    (probe / "ignored" / "data.bin").write_bytes(b"1234567")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--json", "--no-pr"],
        capture_output=True,
        check=True,
        timeout=30,
    )
    entries = {wi.lexical_path(Path(entry["path"])): entry for entry in json.loads(result.stdout)["worktrees"]}
    primary = entries[wi.lexical_path(repo)]["ignored"]
    assert primary["bytes"] == 7
    assert primary["errors"] == []
    assert primary["excluded_paths"] == [str(wi.lexical_path(probe))]
    linked = entries[wi.lexical_path(probe)]["ignored"]
    assert linked["bytes"] == 7
    assert linked["errors"] == []
    assert linked["excluded_paths"] == []


def test_ignored_listing_inside_registered_worktree_is_excluded(tmp_path: Path) -> None:
    registered = tmp_path / ".worktrees" / "probe"
    # No stat or traversal is needed even if Git lists a descendant directly.
    result = wi.ignored_size(
        tmp_path,
        b".worktrees/probe/ignored/data.bin\0",
        [registered / ".." / "probe"],
    )
    assert result == {
        "bytes": 0,
        "measured_bytes": 0,
        "errors": [],
        "excluded_paths": [str(wi.lexical_path(registered))],
    }


def test_nul_paths_and_rename_count() -> None:
    output = b"worktree /tmp/path\nwith newline\0HEAD abc\0branch refs/heads/topic\0\0"
    assert wi.parse_worktrees(output)[0]["path"] == "/tmp/path\nwith newline"
    assert wi.status_counts(b"R  renamed\0original\0 M changed\0?? new\0") == {
        "tracked_dirty": 2,
        "untracked": 1,
    }


def pr(number: int, state: str, head: str = "head") -> dict:
    return {
        "number": number,
        "isCrossRepository": False,
        "state": state,
        "headRefOid": head,
        "mergedAt": "2026-10-08T00:00:00Z" if state == "MERGED" else None,
        "baseRefName": "main",
        "url": f"https://example.invalid/pull/{number}",
    }


@pytest.mark.parametrize(
    "state,classification",
    [
        ("OPEN", "open_pr"),
        ("MERGED", "merged_pr"),
        ("CLOSED", "closed_unmerged_pr"),
    ],
)
def test_pr_state_classification(state: str, classification: str) -> None:
    # A merged PR remains merged even when its original HEAD is no longer local.
    result = wi.classify_prs([pr(1, state, "old-head")], "local-head")
    assert result["classification"] == classification
    assert result["number"] == 1
    assert result["matches_head"] is False


def test_multiple_prs_require_unique_head_match() -> None:
    assert wi.classify_prs([], "head")["classification"] == "no_pr"
    candidates = [pr(1, "MERGED", "old"), pr(2, "OPEN")]
    assert wi.classify_prs(candidates, "head")["number"] == 2
    assert wi.classify_prs(candidates, "other")["classification"] == "ambiguous"
    assert wi.classify_prs([pr(1, "MERGED"), pr(2, "OPEN")], "head")["classification"] == "ambiguous"
    assert wi.classify_prs([pr(1, "UNRECOGNIZED")], "head")["classification"] == "unknown"


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("gh executable missing"),
        RuntimeError("authentication failed"),
        RuntimeError("query timed out"),
    ],
)
def test_pr_query_failures_are_unknown(monkeypatch: pytest.MonkeyPatch, failure: RuntimeError) -> None:
    def fail(*args: object) -> bytes:
        raise failure

    monkeypatch.setattr(wi, "run_command", fail)
    result = wi.query_pr(Path.cwd(), "topic", "head")
    assert result["classification"] == "unknown"
    assert result["reason"] == str(failure)


@pytest.mark.parametrize("response", [b"not-json", b"{}", b"[1]"])
def test_malformed_pr_output_is_unknown(monkeypatch: pytest.MonkeyPatch, response: bytes) -> None:
    monkeypatch.setattr(wi, "run_command", lambda *args: response)
    assert wi.query_pr(Path.cwd(), "topic", "head")["classification"] == "unknown"


def test_pr_query_limit_and_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wi, "verify_source_repository", lambda *args: "github.com/owner/repo")
    calls = []

    def query(args: list[str], cwd: Path) -> bytes:
        calls.append(args)
        return json.dumps([pr(1, "OPEN")]).encode()

    monkeypatch.setattr(wi, "run_command", query)
    assert wi.query_pr(Path.cwd(), "topic", "head")["classification"] == "open_pr"
    assert calls[0][calls[0].index("--head") + 1] == "topic"
    assert "--limit" in calls[0]
    monkeypatch.setattr(wi, "PR_LIMIT", 1)
    assert wi.query_pr(Path.cwd(), "topic", "head")["classification"] == "unknown"


def test_ignored_missing_file_reports_unknown(tmp_path: Path) -> None:
    result = wi.ignored_size(tmp_path, b"missing.bin\0")
    assert result["bytes"] is None
    assert result["measured_bytes"] == 0
    assert result["errors"]


@pytest.mark.parametrize("cross_repository", [True, None])
def test_fork_or_unknown_pr_head_is_not_local_merge(
    monkeypatch: pytest.MonkeyPatch,
    cross_repository: bool | None,
) -> None:
    candidate = pr(1, "MERGED")
    candidate["isCrossRepository"] = cross_repository
    monkeypatch.setattr(wi, "verify_source_repository", lambda *args: "github.com/owner/repo")
    monkeypatch.setattr(wi, "run_command", lambda *args: json.dumps([candidate]).encode())
    result = wi.query_pr(Path.cwd(), "topic", "head")
    assert result["classification"] == "unknown"
    assert "association unknown" in result["reason"]


def test_source_repository_checks_branch_remote_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def source(repo: Path, *args: str) -> bytes:
        if args[0] == "for-each-ref":
            return b"fork-remote\n"
        assert args == ("remote", "get-url", "fork-remote")
        return b"git@github.com:owner/repo.git\n"

    monkeypatch.setattr(wi, "git", source)
    monkeypatch.setattr(wi, "run_command", lambda *args: b'{"url":"https://github.com/owner/repo"}')
    assert wi.verify_source_repository(Path.cwd(), "topic") == "github.com/owner/repo"
    monkeypatch.setattr(wi, "run_command", lambda *args: b'{"url":"https://github.com/other/repo"}')
    with pytest.raises(ValueError, match="association unknown"):
        wi.verify_source_repository(Path.cwd(), "topic")
    monkeypatch.setattr(wi, "run_command", lambda *args: b'{"url":"https://enterprise.invalid/owner/repo"}')
    with pytest.raises(ValueError, match="association unknown"):
        wi.verify_source_repository(Path.cwd(), "topic")


@pytest.mark.parametrize(
    "mode,attributes",
    [
        (stat.S_IFLNK, 0),
        (stat.S_IFDIR, 0x400),
    ],
)
def test_ignored_links_and_junctions_are_not_followed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: int,
    attributes: int,
) -> None:
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda self: SimpleNamespace(
            st_mode=mode,
            st_file_attributes=attributes,
        ),
    )

    def no_scan(*args: object) -> None:
        pytest.fail("Must not scan a symlink or Windows junction")

    monkeypatch.setattr(os, "scandir", no_scan)
    result = wi.ignored_size(tmp_path, b"link\0")
    assert result["bytes"] is None
    assert "Not followed" in result["errors"][0]


def test_subprocess_read_only_environment_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def query(args: list[str], **kwargs: Any) -> SimpleNamespace:
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        assert kwargs["timeout"] == wi.COMMAND_TIMEOUT
        return SimpleNamespace(returncode=0, stdout=b"result", stderr=b"")

    monkeypatch.setattr(subprocess, "run", query)
    assert wi.run_command(["git", "status"], Path.cwd()) == b"result"


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("missing executable"),
        subprocess.TimeoutExpired("git", 30),
    ],
)
def test_subprocess_failures_are_bounded(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError):
        wi.run_command(["git", "status"], Path.cwd())
