"""Package tracked web-report folders for a label-triggered static PR preview.

Only files listed by ``git ls-files`` for ``tasks/<id>/web-report/`` are read, and their bytes
come from the git object store, never from the working directory. Every gate violation names
the file and the rule, never the matched content.
"""

from __future__ import annotations

import html
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPORT_FOLDER = "web-report"
REPORT_PATH = re.compile(r"^tasks/([A-Za-z0-9][A-Za-z0-9._-]*)/web-report/")
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 50_000_000
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"

FORBIDDEN_COMPONENTS = frozenset({"derived", "catalog", "archive", "scratch"})
PRODUCER_DATA_MARKER = "stock-data-downloader/data"
SECRET_NAME_PATTERNS = (".env*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*")

# Built from fragments so this source never contains a literal that secret scanners flag.
PRIVATE_KEY_BLOCK = re.compile(rb"-----BEGIN [A-Z ]*PRIV" + rb"ATE KEY( BLOCK)?-----")
TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("github-fine-grained-token", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("aws-access-key-id", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}")),
    ("anthropic-api-key", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}")),
)
# Cloudflare tokens have no documented fixed prefix, so no pattern is claimed for them.
LOCAL_PRIVATE_MARKER = re.compile(rb"(?:artifact[-_ ]?mode|data[-_ ]?mode)[\"'\s:=]{1,8}local-private", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.path}"


@dataclass(frozen=True)
class TrackedFile:
    path: str
    mode: str
    blob: str


class PreviewGateError(Exception):
    def __init__(self, violations: Sequence[Violation]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(str(v) for v in self.violations))


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    """Paths changed on the PR side of the merge base (deleted files included)."""
    merge_base = git(repo, "merge-base", base, head).decode("ascii").strip()
    raw = git(repo, "diff", "--name-only", "-z", merge_base, head, "--")
    return [p.decode("utf-8") for p in raw.split(b"\0") if p]


def report_ids(paths: Iterable[str]) -> list[str]:
    """Report ids whose ``web-report/`` folder has a changed path."""
    return sorted({m.group(1) for p in paths if (m := REPORT_PATH.match(p.replace("\\", "/")))})


def list_tracked(repo: Path, ref: str, report_id: str) -> list[TrackedFile]:
    prefix = f"tasks/{report_id}/{REPORT_FOLDER}/"
    raw = git(repo, "ls-files", "-s", "-z", "--", prefix) if ref == "INDEX" else git(repo, "ls-tree", "-r", "-z", ref, "--", prefix)
    files = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        fields = meta.decode("ascii").split()
        if ref == "INDEX":
            mode, blob = fields[0], fields[1]
        else:
            mode, blob = fields[0], fields[2]
        files.append(TrackedFile(path.decode("utf-8"), mode, blob))
    return files


def read_blob(repo: Path, blob: str) -> bytes:
    return git(repo, "cat-file", "blob", blob)


def _is_link(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(st, "st_file_attributes", 0) & reparse)


def untracked_or_linked(repo: Path, report_id: str, tracked: Iterable[TrackedFile]) -> list[Violation]:
    """Walk the checkout without following links; anything not in the git list is a violation."""
    known = {t.path for t in tracked}
    root = repo / "tasks" / report_id / REPORT_FOLDER
    found: list[Violation] = []
    if _is_link(root):
        return [Violation("link-not-followed", f"tasks/{report_id}/{REPORT_FOLDER}")]
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            rel = path.relative_to(repo).as_posix()
            if _is_link(path):
                found.append(Violation("link-not-followed", rel))
            elif entry.is_dir(follow_symlinks=False):
                stack.append(path)
            elif rel not in known:
                found.append(Violation("not-in-git-list", rel))
    return found


def check_file(rel_to_report: str, full_path: str, mode: str, data: bytes) -> list[Violation]:
    violations: list[Violation] = []
    pure = PurePosixPath(rel_to_report)
    lowered = [part.lower() for part in pure.parts]
    if mode == SYMLINK_MODE:
        violations.append(Violation("symlink-in-git", full_path))
    if mode == GITLINK_MODE:
        violations.append(Violation("submodule-in-git", full_path))
    if FORBIDDEN_COMPONENTS.intersection(lowered[:-1]) or PRODUCER_DATA_MARKER in rel_to_report.lower():
        violations.append(Violation("data-root-path", full_path))
    name = pure.name.lower()
    if any(PurePosixPath(name).match(p) for p in SECRET_NAME_PATTERNS):
        violations.append(Violation("secret-file-name", full_path))
    if len(data) > MAX_FILE_BYTES:
        violations.append(Violation("file-over-25MiB", full_path))
    if PRIVATE_KEY_BLOCK.search(data):
        violations.append(Violation("private-key-block", full_path))
    for rule, pattern in TOKEN_PATTERNS:
        if pattern.search(data):
            violations.append(Violation(f"token-pattern:{rule}", full_path))
    if LOCAL_PRIVATE_MARKER.search(data):
        violations.append(Violation("local-private-artifact", full_path))
    return violations


def shell_page(pr: int, sha: str, branch: str, built_at: str, reports: Sequence[str]) -> str:
    esc = html.escape
    items = "\n".join(
        f'<section><h2>{esc(r)}</h2><iframe src="../reports/{esc(r, quote=True)}/index.html" title="{esc(r, quote=True)}" loading="lazy"></iframe></section>'
        for r in reports
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>PR 預覽 #{pr}</title>
<style>
body{{margin:0;font:14px/1.5 system-ui,sans-serif}}
header{{padding:8px 12px;background:#fff3cd;color:#3b2f00;border-bottom:1px solid #e0c36a}}
header strong{{margin-right:8px}}
h2{{margin:8px 12px;font-size:14px}}
iframe{{width:100%;height:calc(100vh - 90px);min-height:480px;border:0}}
</style>
</head>
<body>
<header><strong>PR 預覽</strong> PR #{pr} · commit <code>{esc(sha[:7])}</code> · 建置 {esc(built_at)} · 分支 <code>{esc(branch)}</code></header>
{items}
</body>
</html>
"""


def build_preview(
    repo: Path,
    out: Path,
    pr: int,
    sha: str,
    branch: str,
    built_at: str,
    ids: Sequence[str],
    ref: str = "INDEX",
) -> dict[str, object]:
    """Gate and write the preview into ``out``; raises PreviewGateError before writing anything."""
    violations: list[Violation] = []
    planned: list[tuple[str, TrackedFile, bytes]] = []
    total = 0
    for report_id in ids:
        tracked = list_tracked(repo, ref, report_id)
        if not tracked:
            continue
        violations.extend(untracked_or_linked(repo, report_id, tracked))
        base = f"tasks/{report_id}/{REPORT_FOLDER}/"
        for item in tracked:
            data = b"" if item.mode in (SYMLINK_MODE, GITLINK_MODE) else read_blob(repo, item.blob)
            total += len(data)
            violations.extend(check_file(item.path[len(base) :], item.path, item.mode, data))
            planned.append((report_id, item, data))
    if total > MAX_TOTAL_BYTES:
        violations.append(Violation("total-over-50MB", f"{total} bytes"))
    if violations:
        raise PreviewGateError(violations)

    built = sorted({rid for rid, _, _ in planned})
    manifest_files = []
    for report_id, item, data in planned:
        base = f"tasks/{report_id}/{REPORT_FOLDER}/"
        target = out / "reports" / report_id / item.path[len(base) :]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest_files.append({"path": f"reports/{report_id}/{item.path[len(base) :]}", "blob": item.blob, "bytes": len(data)})
    (out / "_preview").mkdir(parents=True, exist_ok=True)
    (out / "_preview" / "index.html").write_text(shell_page(pr, sha, branch, built_at, built), encoding="utf-8")
    manifest = {"pr": pr, "sha": sha, "branch": branch, "built_at": built_at, "reports": built, "files": manifest_files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
