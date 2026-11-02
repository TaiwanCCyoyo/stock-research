"""Gates, shell page and manifest of the label-triggered report preview."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from research_core import report_preview as rp
from scripts import report_preview as cli

REPORT = "20261101-demo"
BASE = f"tasks/{REPORT}/web-report"
# Fake secrets are assembled at run time so no scanner-visible literal is stored.
FAKE_KEY = ("-----BEGIN " + "RSA PRIV" + "ATE KEY-----\nnot-a-real-key\n").encode()
FAKE_GH = ("gh" + "p_" + "x" * 36).encode()
FAKE_AWS = ("AK" + "IA" + "X" * 16).encode()


def git(repo: Path, *args: str, data: bytes | None = None) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True)
    return out.stdout.decode()


def make_repo(root: Path, files: dict[str, bytes]) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "tag", "base")
    for rel, data in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "report", "--allow-empty")
    return repo


GOOD = {f"{BASE}/index.html": b"<html>ok</html>", f"{BASE}/data/summary.js": b"var x=1;"}


def build(repo: Path, tmp_path: Path):
    return rp.build_preview(repo, tmp_path / "out", 147, "a" * 40, "claude/<b>", "2026-11-02 00:00 UTC", [REPORT])


def rules(excinfo: pytest.ExceptionInfo[rp.PreviewGateError]) -> set[str]:
    return {v.rule for v in excinfo.value.violations}


def test_pass_writes_shell_manifest_and_untouched_bytes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, GOOD)
    manifest = build(repo, tmp_path)
    out = tmp_path / "out"
    assert (out / "reports" / REPORT / "index.html").read_bytes() == GOOD[f"{BASE}/index.html"]
    shell = (out / "_preview" / "index.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in shell
    assert "PR 預覽" in shell and "#147" in shell and "aaaaaaa" in shell and "2026-11-02 00:00 UTC" in shell
    assert f'src="../reports/{REPORT}/index.html"' in shell
    assert "claude/&lt;b&gt;" in shell and "claude/<b>" not in shell
    saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest
    blob = git(repo, "rev-parse", f"HEAD:{BASE}/index.html").strip()
    assert {"path": f"reports/{REPORT}/index.html", "blob": blob, "bytes": 15} in saved["files"]
    assert saved["pr"] == 147 and saved["sha"] == "a" * 40


def test_report_ids_from_changes() -> None:
    paths = [f"{BASE}/index.html", "tasks/other/mission.md", "tasks/b.1/web-report/kit/x.js", "docs/a.md"]
    assert rp.report_ids(paths) == [REPORT, "b.1"]


def test_changed_files_uses_merge_base(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, GOOD)
    assert rp.report_ids(rp.changed_files(repo, "base", "HEAD")) == [REPORT]


@pytest.mark.parametrize(
    ("files", "rule"),
    [
        ({f"{BASE}/.env.local": b"A=1"}, "secret-file-name"),
        ({f"{BASE}/cert.pem": b"x"}, "secret-file-name"),
        ({f"{BASE}/id_rsa": b"x"}, "secret-file-name"),
        ({f"{BASE}/derived/a.json": b"{}"}, "data-root-path"),
        ({f"{BASE}/Catalog/a.json": b"{}"}, "data-root-path"),
        ({f"{BASE}/archive/a.json": b"{}"}, "data-root-path"),
        ({f"{BASE}/scratch/a.json": b"{}"}, "data-root-path"),
        ({f"{BASE}/stock-data-downloader/data/a.csv": b"x"}, "data-root-path"),
        ({f"{BASE}/notes.txt": FAKE_KEY}, "private-key-block"),
        ({f"{BASE}/a.js": b"t='" + FAKE_GH + b"'"}, "token-pattern:github-token"),
        ({f"{BASE}/a.js": b"k=" + FAKE_AWS}, "token-pattern:aws-access-key-id"),
        ({f"{BASE}/artifact-mode.json": b'{"artifactMode": "local-private"}'}, "local-private-artifact"),
    ],
)
def test_gate_rules_fail_without_leaking_content(tmp_path: Path, files: dict[str, bytes], rule: str) -> None:
    repo = make_repo(tmp_path, {**GOOD, **files})
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert rule in rules(excinfo)
    text = str(excinfo.value)
    for secret in (FAKE_KEY, FAKE_GH, FAKE_AWS):
        assert secret.decode() not in text
    assert not (tmp_path / "out").exists()


def test_file_over_25_mib(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "MAX_FILE_BYTES", 10)
    repo = make_repo(tmp_path, {**GOOD, f"{BASE}/big.bin": b"0" * 11})
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert "file-over-25MiB" in rules(excinfo)


def test_limit_constants() -> None:
    assert rp.MAX_FILE_BYTES == 25 * 1024 * 1024
    assert rp.MAX_TOTAL_BYTES == 50_000_000


def test_total_over_limit(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "MAX_TOTAL_BYTES", 20)
    repo = make_repo(tmp_path, GOOD)
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert "total-over-50MB" in rules(excinfo)


def test_untracked_and_ignored_files_fail(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, GOOD)
    (repo / BASE / "stray.txt").write_text("local only", encoding="utf-8")
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert ("not-in-git-list", f"{BASE}/stray.txt") in {(v.rule, v.path) for v in excinfo.value.violations}


def test_symlink_recorded_in_git_fails_on_any_platform(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, GOOD)
    blob = git(repo, "hash-object", "-w", "--stdin", data=b"../../secret").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},{BASE}/link.html")
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert "symlink-in-git" in rules(excinfo)


def test_filesystem_link_is_not_followed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, GOOD)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("outside", encoding="utf-8")
    try:
        os.symlink(outside, repo / BASE / "linked", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this Windows account cannot create symlinks; the git-recorded symlink test covers the gate")
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert "link-not-followed" in rules(excinfo)


def run_cli(repo: Path, out: Path) -> int:
    return cli.main(["--repo", str(repo), "--base", "base", "--head", "HEAD", "--out", str(out), "--pr", "1", "--branch", "b"])


def test_cli_exit_codes(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    bad = make_repo(tmp_path / "a", {**GOOD, f"{BASE}/.env": b"A=1"})
    assert run_cli(bad, tmp_path / "o1") == 1
    assert "secret-file-name" in caplog.text
    assert run_cli(make_repo(tmp_path / "b", GOOD), tmp_path / "o2") == 0
    assert run_cli(make_repo(tmp_path / "c", {}), tmp_path / "o3") == 3
