"""Git report snapshots are reproducible without changing saved package bytes."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import export_history_title_origins as exporter

Snapshot = tuple[Path, str, Path, dict, dict[str, bytes]]


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        shell=False,
    ).stdout


def item(identity: str, filename: str) -> dict:
    return {
        "id": identity,
        "date": "2020-01-01",
        "title": "已套用展示標題",
        "status": "exploratory",
        "evidenceState": "saved",
        "conclusion": "",
        "originalSummary": "",
        "reportPath": f"tasks/{identity}/{filename}",
        "reviewConfirmed": False,
        "registryEventIds": [],
    }


def write_package(path: Path, items: list[dict]) -> dict:
    history = {"schema": "saved-research-history.v1", "historyComplete": False, "items": items}
    package = {"schema": "saved-research-studio.v1", "runs": [], "researchHistory": history}
    path.write_bytes(gzip.compress(json.dumps(package, ensure_ascii=False).encode("utf-8"), mtime=0))
    return history


@pytest.fixture
def snapshot(tmp_path: Path) -> Snapshot:
    repo = tmp_path / "中文 repo with spaces"
    repo.mkdir()
    git(repo, "init")
    sources = {
        "tasks/研究 一/report.md": "# 原始研究報告\r\n\r\n已保存內容\r\n".encode("utf-8"),
        "tasks/研究二/mission.md": b"\xef\xbb\xbf# Mission snapshot\n\nSaved mission.\n",
        "tasks/noheading/report.md": b"## Only a subheading\n",
    }
    for source_path, raw in sources.items():
        destination = repo / source_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    git(repo, "-c", "core.autocrlf=false", "add", "tasks")
    git(repo, "-c", "user.name=Snapshot Test", "-c", "user.email=snapshot@example.invalid", "commit", "-m", "Snapshot fixtures")
    revision = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    package_path = repo / "immutable package.json.gz"
    history = write_package(package_path, [item("研究 一", "report.md"), item("研究二", "mission.md")])
    return repo, revision, package_path, history, sources


def test_git_report_and_mission_snapshot_hashes_ignore_overlay_and_working_edits(snapshot: Snapshot, tmp_path: Path) -> None:
    repo, revision, package_path, history, sources = snapshot
    package_bytes = package_path.read_bytes()
    (repo / "tasks/研究 一/report.md").write_text("# Uncommitted replacement\n", encoding="utf-8")
    result = exporter.export_title_origins(package_path, revision[:8], tmp_path / "titles.json", repo_root=repo)
    assert result["schema"] == "research-history-title-origins.v1"
    assert result["sourceRevision"] == revision
    assert (
        result["historySha256"]
        == hashlib.sha256(
            json.dumps(
                history,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    for identity, expected in [("研究 一", "原始研究報告"), ("研究二", "Mission snapshot")]:
        saved = result["titles"][identity]
        assert saved["title"] == expected
        assert saved["sourceSha256"] == hashlib.sha256(sources[saved["sourcePath"]]).hexdigest()
    assert package_path.read_bytes() == package_bytes


@pytest.mark.parametrize(
    "bad_path",
    [
        "../report.md",
        "tasks/other/report.md",
        "tasks/研究 一/../report.md",
        "tasks/研究 一/result.md",
        "tasks\\研究 一\\report.md",
        "C:/tasks/研究 一/report.md",
    ],
)
def test_rejects_paths_outside_exact_history_task(snapshot: Snapshot, tmp_path: Path, bad_path: str) -> None:
    repo, revision, package_path, _, _ = snapshot
    record = item("研究 一", "report.md")
    record["reportPath"] = bad_path
    write_package(package_path, [record])
    output = tmp_path / "invalid.json"
    with pytest.raises(ValueError, match="invalid report source path"):
        exporter.export_title_origins(package_path, revision, output, repo_root=repo)
    assert not output.exists()


@pytest.mark.parametrize("identity, message", [("missing", "Git show failed"), ("noheading", "no level-one heading")])
def test_missing_file_or_heading_fails_before_output(snapshot: Snapshot, tmp_path: Path, identity: str, message: str) -> None:
    repo, revision, package_path, _, _ = snapshot
    write_package(package_path, [item(identity, "report.md")])
    output = tmp_path / "invalid.json"
    with pytest.raises(ValueError, match=message):
        exporter.export_title_origins(package_path, revision, output, repo_root=repo)
    assert not output.exists()


def test_existing_output_is_preserved(snapshot: Snapshot, tmp_path: Path) -> None:
    repo, revision, package_path, _, _ = snapshot
    output = tmp_path / "existing.json"
    original = b"existing output\x00"
    output.write_bytes(original)
    with pytest.raises(FileExistsError):
        exporter.export_title_origins(package_path, revision, output, repo_root=repo)
    assert output.read_bytes() == original


def test_different_cwd_is_reproducible_and_cli_stdout_is_summary(
    snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, revision, package_path, _, _ = snapshot
    original_export = exporter.export_title_origins
    monkeypatch.setattr(exporter, "export_title_origins", lambda package, ref, output: original_export(package, ref, output, repo_root=repo))
    outputs = [tmp_path / "first.json", tmp_path / "second.json"]
    for cwd, output in zip([repo, tmp_path], outputs, strict=True):
        monkeypatch.chdir(cwd)
        assert exporter.main(["--package", str(package_path), "--revision", revision, "--output", str(output)]) == 0
        assert json.loads(capsys.readouterr().out) == {"titles": 2, "revision": revision}
    assert outputs[0].read_bytes() == outputs[1].read_bytes()


def test_option_like_revision_cannot_become_git_option(snapshot: Snapshot, tmp_path: Path) -> None:
    repo, _, package_path, _, _ = snapshot
    output = tmp_path / "invalid.json"
    with pytest.raises(ValueError, match="Git rev-parse failed"):
        exporter.export_title_origins(package_path, "--help", output, repo_root=repo)
    assert not output.exists()
