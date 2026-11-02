"""Gate, packaging, reconcile state machine and comments of the label-driven report preview."""

import base64
import gzip
import io
import json
import os
import subprocess
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from research_core import report_preview as rp
from scripts import report_preview as cli

REPORT = "20261101-demo"
BASE = f"tasks/{REPORT}/web-report"
REPO_NAME = "owner/repo"
# Fake secrets are assembled at run time so no scanner-visible literal is stored; the key
# "block" is only a header line plus obviously fake text.
FAKE_KEY_TEXT = "-----BEGIN " + "RSA PRIV" + "ATE KEY-----\nnot-a-real-key\n"
FAKE_KEY = FAKE_KEY_TEXT.encode()
FAKE_GH = "gh" + "p_" + "x" * 36
FAKE_AWS = "AK" + "IA" + "X" * 16
LOCAL_PRIVATE_JSON = '{"artifactMode": "local-private"}'
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
SHA_A = "a" * 40
SHA_B = "b" * 40


def git(repo: Path, *args: str, data: bytes | None = None) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True)
    return out.stdout.decode()


def make_repo(root: Path, files: dict[str, bytes]) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.autocrlf", "false")
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


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def parquet_bytes(values: list[str]) -> bytes:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    buffer = io.BytesIO()
    pq.write_table(pa.table({"note": values, "n": list(range(len(values)))}), buffer, compression="gzip", write_statistics=False)
    return buffer.getvalue()


GOOD = {f"{BASE}/index.html": b"<html>ok</html>", f"{BASE}/data/summary.js": b"var x=1;"}


def build(repo: Path, tmp_path: Path) -> dict[str, object]:
    return rp.build_preview(repo, tmp_path / "out", 147, SHA_A, "claude/<b>", "2026-11-02 00:00 UTC", [REPORT])


def rules(excinfo: pytest.ExceptionInfo[rp.PreviewGateError]) -> set[str]:
    return {v.rule for v in excinfo.value.violations}


# ---------------------------------------------------------------------------- packaging


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


def test_report_ids_from_changes() -> None:
    paths = [f"{BASE}/index.html", "tasks/other/mission.md", "tasks/b.1/web-report/kit/x.js", "docs/a.md"]
    assert rp.report_ids(paths) == [REPORT, "b.1"]


def test_commit_mode_reads_objects_not_the_working_tree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, GOOD)
    head = git(repo, "rev-parse", "HEAD").strip()
    (repo / BASE / "stray.txt").write_text("local only", encoding="utf-8")
    (repo / BASE / "index.html").write_bytes(b"changed on disk")
    planned = rp.gate_reports(repo, head, [REPORT])
    by_name = {p.rel: p.data for p in planned}
    assert by_name["index.html"] == b"<html>ok</html>" and "stray.txt" not in by_name


def test_missing_index_html_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {f"{BASE}/data/summary.js": b"var x=1;"})
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert "missing-index-html" in rules(excinfo)


# ---------------------------------------------------------------------------- gate rules


@pytest.mark.parametrize(
    ("files", "rule"),
    [
        ({f"{BASE}/.env.local": b"A=1"}, "secret-file-name"),
        ({f"{BASE}/cert.pem": b"x"}, "secret-file-name"),
        ({f"{BASE}/id_rsa": b"x"}, "secret-file-name"),
        ({f"{BASE}/.hidden/a.js": b"1"}, "hidden-path"),
        ({f"{BASE}/derived/a.json": b"{}"}, "data-root-path"),
        ({f"{BASE}/Catalog/a.json": b"{}"}, "data-root-path"),
        ({f"{BASE}/stock-data-downloader/data/a.csv": b"x"}, "data-root-path"),
        ({f"{BASE}/notes.txt": FAKE_KEY}, "private-key-block"),
        ({f"{BASE}/a.js": b"t='" + FAKE_GH.encode() + b"'"}, "token-pattern:github-token"),
        ({f"{BASE}/a.js": b"k=" + FAKE_AWS.encode()}, "token-pattern:aws-access-key-id"),
        ({f"{BASE}/mode.json": LOCAL_PRIVATE_JSON.encode()}, "local-private-artifact"),
        # dot's three misses on PR #149
        ({f"{BASE}/data/bundle.zip": zip_bytes({"cert.pem": FAKE_KEY})}, "private-key-block"),
        ({f"{BASE}/data/bundle.zip": zip_bytes({"cert.pem": FAKE_KEY})}, "secret-file-name"),
        ({f"{BASE}/notes.txt": b"\xff\xfe" + FAKE_KEY_TEXT.encode("utf-16-le")}, "private-key-block"),
        ({f"{BASE}/notes.txt": b"\xfe\xff" + FAKE_KEY_TEXT.encode("utf-16-be")}, "private-key-block"),
        ({f"{BASE}/mode.json": b"\xff\xfe" + LOCAL_PRIVATE_JSON.encode("utf-16-le")}, "local-private-artifact"),
        # BOM-less UTF-16 decodes as "valid" UTF-8 full of NULs
        ({f"{BASE}/notes.txt": FAKE_KEY_TEXT.encode("utf-16-le")}, "text-contains-nul"),
        ({f"{BASE}/mode.json": b'{"artifact\\u004dode": "local-private"}'}, "local-private-artifact"),
        ({f"{BASE}/a.html": b'<img src="data:text/plain;base64,' + __import__("base64").b64encode(FAKE_KEY) + b'">'}, "private-key-block"),
        ({f"{BASE}/img.png": PNG + FAKE_KEY_TEXT.encode("utf-16-le")}, "private-key-block"),
        ({f"{BASE}/img.png": b"GIF89a not a png"}, "signature-mismatch"),
        ({f"{BASE}/table.parquet": b"PK\x03\x04 not parquet"}, "signature-mismatch"),
        ({f"{BASE}/data.zip": b"not a zip at all"}, "signature-mismatch"),
        ({f"{BASE}/tool.exe": b"MZ"}, "extension-not-allowed"),
        ({f"{BASE}/data.tar.gz": b"\x1f\x8b"}, "extension-not-allowed"),
        ({f"{BASE}/LICENSE": b"x"}, "extension-not-allowed"),
        ({f"{BASE}/bad.txt": b"\xff\xfe\x00\x00x\x00\x00\x00"}, "text-decode-failed"),
        ({f"{BASE}/bad.css": b"\xc3\x28"}, "text-decode-failed"),
        ({f"{BASE}/bad.json": b"{"}, "json-invalid"),
        ({f"{BASE}/data/nested.zip": zip_bytes({"inner.zip": zip_bytes({"a.json": b"{}"})})}, "nested-archive"),
        ({f"{BASE}/data/odd.zip": zip_bytes({"payload.bin": b"x"})}, "extension-not-allowed"),
        ({f"{BASE}/data/up.zip": zip_bytes({"../escape.json": b"{}"})}, "zip-unsafe-member-name"),
    ],
)
def test_gate_rules_fail_without_leaking_content(tmp_path: Path, files: dict[str, bytes], rule: str) -> None:
    repo = make_repo(tmp_path, {**GOOD, **files})
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert rule in rules(excinfo)
    text = str(excinfo.value)
    for secret in (FAKE_KEY_TEXT, FAKE_GH, FAKE_AWS, "not-a-real-key"):
        assert secret not in text
    assert not (tmp_path / "out").exists()


def test_allowed_formats_pass(tmp_path: Path) -> None:
    files = {
        f"{BASE}/img.png": PNG,
        f"{BASE}/a.svg": b"<svg/>",
        f"{BASE}/a.webp": b"RIFF\0\0\0\0WEBPVP8 ",
        f"{BASE}/receipts.zip": zip_bytes({"H1-receipt.json": b'{"ok": true}'}),
        f"{BASE}/bom.csv": b"\xef\xbb\xbfa,b\n1,2\n",
        f"{BASE}/u16.md": "# 標題\n".encode("utf-16"),
    }
    repo = make_repo(tmp_path, {**GOOD, **files})
    build(repo, tmp_path)


def test_parquet_columns_are_decompressed_and_scanned(tmp_path: Path) -> None:
    clean = parquet_bytes(["fine"] * 50)
    leaky = parquet_bytes(["fine"] * 50 + [FAKE_KEY_TEXT])
    assert FAKE_KEY not in leaky  # compressed pages hide the text from a raw byte scan
    assert rp.content_rules("t.parquet", clean) == []
    assert "private-key-block" in rp.content_rules("t.parquet", leaky)


def test_zip_member_limits(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "MAX_ARCHIVE_RATIO", 2)
    found = rp.check_zip_content(zip_bytes({"big.json": b"[" + b"0," * 5000 + b"0]"}), "x.zip")
    assert {v.rule for v in found} == {"zip-member-over-limit"}


def test_file_over_25_mib(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "MAX_FILE_BYTES", 10)
    repo = make_repo(tmp_path, {**GOOD, f"{BASE}/big.txt": b"0" * 11})
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert "file-over-25MiB" in rules(excinfo)


def test_limit_constants() -> None:
    assert rp.MAX_FILE_BYTES == 25 * 1024 * 1024
    assert rp.MAX_TOTAL_BYTES == 50_000_000
    assert rp.MAX_SITE_BYTES < 1_000_000_000


def test_total_over_limit(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "MAX_TOTAL_BYTES", 20)
    repo = make_repo(tmp_path, GOOD)
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    assert "total-over-50MB" in rules(excinfo)


def test_untracked_files_fail_in_local_check(tmp_path: Path) -> None:
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


# ---------------------------------------------------------------------------- masking


def test_file_name_with_token_is_masked(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {**GOOD, f"{BASE}/.env.{FAKE_GH}": b"A=1"})
    with pytest.raises(rp.PreviewGateError) as excinfo:
        build(repo, tmp_path)
    text = str(excinfo.value)
    assert FAKE_GH not in text and "<redacted:token-pattern:github-token>" in text
    assert "unsafe-file-name" in rules(excinfo)


def test_mask_escapes_control_and_format_characters() -> None:
    masked = rp.mask("a\n::stop-commands::x\x1b[0m‮b")
    assert "\n" not in masked and "\x1b" not in masked and "‮" not in masked
    assert "\\u000a::stop-commands" in masked and "\\u202e" in masked
    assert str(rp.Violation("r", "x\r\ny")) == "[r] x\\u000d\\u000ay"


# ---------------------------------------------------------------------------- reconcile


def pull(number: int, sha: str = SHA_A, labels: tuple[str, ...] = ("preview",), state: str = "open", fork: bool = False) -> dict[str, Any]:
    head_repo = {"full_name": "someone/fork" if fork else REPO_NAME}
    return {
        "number": number,
        "state": state,
        "labels": [{"name": name} for name in labels],
        "head": {"sha": sha, "ref": f"branch-{number}", "repo": head_repo},
        "base": {"ref": "main", "repo": {"full_name": REPO_NAME}},
    }


def test_eligible_pulls_keep_only_current_labelled_same_repo_open() -> None:
    raw = [
        pull(3),
        pull(1, labels=()),  # label removed
        pull(2, state="closed"),  # PR closed
        pull(4, fork=True),  # fork PR
        pull(5, labels=("other", "preview")),
        {**pull(6), "head": {"sha": SHA_A, "ref": "x", "repo": None}},  # deleted fork
        {**pull(7), "base": {"ref": "release", "repo": {"full_name": REPO_NAME}}},
    ]
    assert [p.number for p in rp.eligible_pulls(raw, REPO_NAME)] == [3, 5]


@pytest.mark.parametrize("bad", [{"number": 1}, {**pull(1), "head": {"sha": "zz", "ref": "x", "repo": {}}}, {**pull(1), "labels": None}])
def test_malformed_payload_fails_closed(bad: dict[str, Any]) -> None:
    with pytest.raises(rp.ReconcileError):
        rp.eligible_pulls([bad], REPO_NAME)


def outcome_for(statuses: dict[int, rp.PrOutcome]) -> Any:
    return lambda p: statuses[p.number]


def test_plan_site_excludes_rejected_without_blocking_others() -> None:
    pulls = [rp.PullRequest(1, SHA_A, "a"), rp.PullRequest(2, SHA_B, "b"), rp.PullRequest(3, SHA_A, "c")]
    plan = rp.plan_site(
        pulls,
        outcome_for({1: rp.PrOutcome("included", 10), 2: rp.PrOutcome("rejected", violations=["[r] x"]), 3: rp.PrOutcome("no-reports")}),
    )
    assert plan.included == {1: SHA_A}
    assert plan.rejected == {2: {"sha": SHA_B, "violations": ["[r] x"]}}
    assert plan.no_reports == [3]


def test_plan_site_cap_drops_overflowing_pr() -> None:
    dropped: list[int] = []
    pulls = [rp.PullRequest(1, SHA_A, "a"), rp.PullRequest(2, SHA_B, "b")]
    plan = rp.plan_site(pulls, outcome_for({1: rp.PrOutcome("included", 60), 2: rp.PrOutcome("included", 60)}), max_site_bytes=100, drop=dropped.append)
    assert plan.included == {1: SHA_A} and dropped == [2]
    assert "site-over-limit" in plan.rejected[2]["violations"][0]


def test_stale_entries_detect_removal_and_head_move() -> None:
    built = {1: SHA_A, 2: SHA_A}
    assert rp.stale_entries(built, [rp.PullRequest(1, SHA_A, "a"), rp.PullRequest(2, SHA_A, "b"), rp.PullRequest(9, SHA_B, "z")]) == []
    problems = rp.stale_entries(built, [rp.PullRequest(2, SHA_B, "b")])
    assert problems == ["PR #1 is no longer eligible", "PR #2 head moved from aaaaaaa to bbbbbbb"]


class FakeApi:
    def __init__(self, pulls: list[dict[str, Any]] | Exception, comments: dict[int, list[dict[str, Any]]] | None = None) -> None:
        self.pulls = pulls
        self.comments = comments or {}
        self.sent: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, path: str) -> Any:
        if "/pulls?" in path:
            if isinstance(self.pulls, Exception):
                raise self.pulls
            return self.pulls if path.endswith("page=1") else []
        number = int(path.split("/issues/")[1].split("/")[0])
        return self.comments.get(number, []) if path.endswith("page=1") else []

    def send(self, method: str, path: str, body: Mapping[str, Any]) -> Any:
        self.sent.append((method, path, dict(body)))
        return {}


def reconcile_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = make_repo(tmp_path, GOOD)
    return repo, git(repo, "rev-parse", "HEAD").strip()


def run_reconcile(tmp_path: Path, repo: Path, api: FakeApi, monkeypatch: MonkeyPatch) -> tuple[int, Path, Path]:
    monkeypatch.setattr(rp, "git", _git_without_fetch)
    site, state = tmp_path / "site", tmp_path / "state.json"
    argv = [
        "reconcile",
        "--repository",
        REPO_NAME,
        "--state",
        str(state),
        "--repo",
        str(repo),
        "--site",
        str(site),
        "--base-ref",
        "base",
        "--gate-commit",
        "c" * 40,
    ]
    args = cli.parser().parse_args(argv)
    return cli.cmd_reconcile(args, api), site, state


_real_git = rp.git


def _git_without_fetch(repo: Path, *args: str) -> bytes:
    return b"" if args[0] == "fetch" else _real_git(repo, *args)


def test_reconcile_builds_only_currently_eligible(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    repo, head = reconcile_repo(tmp_path)
    api = FakeApi([pull(10, head), pull(11, head, labels=()), pull(12, head, fork=True)])
    code, site, state = run_reconcile(tmp_path, repo, api, monkeypatch)
    assert code == 0
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["included"] == {"10": head} and saved["rejected"] == {}
    assert (site / "pr-10" / "reports" / REPORT / "index.html").exists()
    assert not (site / "pr-11").exists() and not (site / "pr-12").exists()
    previews = json.loads((site / "previews.json").read_text(encoding="utf-8"))
    assert [p["pr"] for p in previews["previews"]] == [10]
    assert (site / "robots.txt").read_text(encoding="utf-8") == "User-agent: *\nDisallow: /\n"


def test_reconcile_with_no_eligible_pr_still_writes_placeholder_site(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    repo, _ = reconcile_repo(tmp_path)
    code, site, _ = run_reconcile(tmp_path, repo, FakeApi([]), monkeypatch)
    assert code == 0
    assert "目前沒有預覽" in (site / "index.html").read_text(encoding="utf-8")
    assert sorted(p.name for p in site.iterdir()) == ["index.html", "previews.json", "robots.txt"]


def test_reconcile_api_failure_fails_closed(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    repo, _ = reconcile_repo(tmp_path)
    code, site, state = run_reconcile(tmp_path, repo, FakeApi(rp.ReconcileError("boom")), monkeypatch)
    assert code == 1 and not site.exists() and not state.exists()


def test_reconcile_unknown_head_is_rejected_not_published(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    repo, head = reconcile_repo(tmp_path)
    code, site, state = run_reconcile(tmp_path, repo, FakeApi([pull(10, head), pull(11, "d" * 40)]), monkeypatch)
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert code == 0 and saved["included"] == {"10": head}
    assert "head-unavailable" in saved["rejected"]["11"]["violations"][0]
    assert not (site / "pr-11").exists()


def test_verify_refuses_stale_build(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"included": {"10": SHA_A}, "rejected": {}, "no_reports": []}), encoding="utf-8")
    args = cli.parser().parse_args(["verify", "--repository", REPO_NAME, "--state", str(state)])
    assert cli.cmd_verify(args, FakeApi([pull(10, SHA_A)])) == 0
    assert cli.cmd_verify(args, FakeApi([pull(10, SHA_A, labels=())])) == 1  # label removed after build
    assert cli.cmd_verify(args, FakeApi([pull(10, SHA_A, state="closed")])) == 1  # closed after build
    assert cli.cmd_verify(args, FakeApi([pull(10, SHA_B)])) == 1  # new push after build
    assert cli.cmd_verify(args, FakeApi(rp.ReconcileError("down"))) == 1
    assert "no longer eligible" in caplog.text and "head moved" in caplog.text


# ---------------------------------------------------------------------------- comments


def test_comment_plan_and_idempotent_apply() -> None:
    plan = rp.SitePlan(included={10: SHA_A}, rejected={11: {"sha": SHA_B, "violations": ["[secret-file-name] x/.env"]}})
    bodies = rp.comment_plan(plan, {10, 12}, "2026-11-02 01:00 UTC", "https://o.github.io/r/", "https://run")
    assert set(bodies) == {10, 11, 12}
    assert "https://o.github.io/r/pr-10/_preview/" in bodies[10][1] and "aaaaaaa" in bodies[10][1]
    assert "閘門未通過" in bodies[11][1] and bodies[12][0] == "removed"

    existing = {10: [{"id": 5, "body": f"{rp.COMMENT_MARKER}\n<!-- report-preview-state: deployed:{SHA_A} -->\nold"}]}
    api = FakeApi([], existing)
    log = rp.apply_comments(api, REPO_NAME, bodies)
    methods = [(m, p) for m, p, _ in api.sent]
    assert ("POST", f"/repos/{REPO_NAME}/issues/11/comments") in methods
    assert all("/issues/12/" not in p for _, p in methods)  # never announced, nothing to retract
    assert "PR #10: unchanged (deployed)" in log


def test_comment_reports_rejections_as_failure(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"included": {}, "rejected": {"11": {"sha": SHA_B, "violations": ["[r] x"]}}, "no_reports": [], "previous": None}), encoding="utf-8"
    )
    args = cli.parser().parse_args(["comment", "--repository", REPO_NAME, "--state", str(state), "--page-url", "https://p/", "--run-url", "https://r"])
    assert cli.cmd_comment(args, FakeApi([])) == 4


def test_cli_check_exit_codes(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    def run(repo: Path) -> int:
        return cli.main(["check", "--repo", str(repo), "--base", "base", "--head", "HEAD"])

    assert run(make_repo(tmp_path / "a", {**GOOD, f"{BASE}/.env": b"A=1"})) == 1
    assert "secret-file-name" in caplog.text
    assert run(make_repo(tmp_path / "b", GOOD)) == 0
    assert run(make_repo(tmp_path / "c", {})) == 3


# ---- data: URIs go through the same format-aware gate as files (dot's P1 on PR #149) ----


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _uri_rules(page: bytes, name: str = "index.html") -> set[str]:
    return {v.rule for v in rp.check_file(name, f"{BASE}/{name}", "100644", page)}


def _link(data: bytes, mime: str = "application/zip") -> bytes:
    return f'<a download="notes.zip" href="data:{mime};base64,{_b64(data)}">x</a>'.encode()


def test_direct_and_embedded_zip_are_rejected_alike() -> None:
    archive = zip_bytes({"notes.txt": FAKE_KEY})
    direct = {v.rule for v in rp.check_file("x.zip", f"{BASE}/x.zip", "100644", archive)}
    assert "private-key-block" in direct
    assert "private-key-block" in _uri_rules(_link(archive))
    assert "private-key-block" in _uri_rules(_link(archive, "image/png"))  # declared MIME is not trusted


def test_embedded_formats_and_encodings() -> None:
    assert "private-key-block" in _uri_rules(_link(gzip.compress(FAKE_KEY), "text/plain"))
    assert "private-key-block" in _uri_rules(_link(FAKE_KEY_TEXT.encode("utf-16"), "text/plain"))
    assert "private-key-block" in _uri_rules(f'<a href="data:text/plain,{quote(FAKE_KEY_TEXT)}">x</a>'.encode())
    css = f"a{{background:url(data:application/zip;base64,{_b64(zip_bytes({'n.txt': FAKE_KEY}))})}}".encode()
    assert "private-key-block" in _uri_rules(css, "s.css")
    js = f'var d="data:application/zip;base64,{_b64(zip_bytes({"n.txt": FAKE_KEY}))}";'.encode()
    assert "private-key-block" in _uri_rules(js, "a.js")
    assert "data-uri-invalid-base64" in _uri_rules(b'<a href="data:text/plain;base64,@@@@not base64@@@@">x</a>')
    assert "embedded-unknown-binary" in _uri_rules(_link(b"\x7fELF\x00\xff\xfe binary"))


def test_embedded_depth_and_size_limits() -> None:
    page = FAKE_KEY
    for _ in range(rp.MAX_EMBED_DEPTH + 1):
        page = f"data:text/html;base64,{_b64(page)}".encode()
    assert "data-uri-too-deep" in _uri_rules(b'<a href="' + page + b'">x</a>')
    shallow = b'<a href="data:text/html;base64,' + _b64(b'<a href="data:text/plain;base64,' + _b64(FAKE_KEY).encode() + b'">').encode() + b'">x</a>'
    assert "private-key-block" in _uri_rules(shallow)  # within the limit it is still scanned


def test_embedded_decoded_size_is_capped(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "MAX_DATA_URI_BYTES", 1024)
    assert "data-uri-over-limit" in _uri_rules(_link(b"A" * 2048, "text/plain"))
    assert "data-uri-over-limit" in _uri_rules(_link(gzip.compress(b"A" * 100_000), "application/gzip"))  # decompression bomb
    two = _link(b"A" * 700, "text/plain") * 2  # the cap is cumulative per file
    assert "data-uri-over-limit" in _uri_rules(two)


def test_small_embedded_image_still_passes() -> None:
    page = f'<img src="data:image/png;base64,{_b64(PNG)}"><p style="background:url(data:image/png;base64,{_b64(PNG)})">'.encode()
    assert _uri_rules(page) == set()
