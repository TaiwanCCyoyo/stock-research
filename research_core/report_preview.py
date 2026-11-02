"""Gate and package tracked web-report folders for the label-driven static PR preview site.

The site is rebuilt from scratch on every run ("stateless reconcile"): the open, same-repository
PRs that carry the ``preview`` label *now* are listed through the GitHub API, each one's head
commit is read from the git object store (never checked out, never executed), gated, and the
whole site is deployed at once. A PR that is not eligible at listing time is simply absent from
the next deployment, which is how a preview is taken down.

Gate output names a rule and a masked path, never the matched content.
"""

from __future__ import annotations

import base64
import binascii
import html
import io
import json
import os
import re
import shutil
import stat
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

REPORT_FOLDER = "web-report"
REPORT_PATH = re.compile(r"^tasks/([A-Za-z0-9][A-Za-z0-9._-]*)/web-report/")
PREVIEW_LABEL = "preview"
COMMENT_MARKER = "<!-- report-preview -->"

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 50_000_000  # per PR
MAX_SITE_BYTES = 500_000_000  # whole site; GitHub Pages supports up to 1 GB
MAX_ARCHIVE_MEMBERS = 1000
MAX_ARCHIVE_UNPACKED = 100 * 1024 * 1024
MAX_ARCHIVE_RATIO = 200
MAX_PARQUET_UNPACKED = 256 * 1024 * 1024
MAX_IMAGE_URI_BYTES = 256 * 1024  # decoded bytes of one embedded raster image
MAX_IMAGE_URI_TOTAL_BYTES = 1024 * 1024  # decoded bytes of all embedded images in one file
MAX_PULL_PAGES = 20
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

FORBIDDEN_COMPONENTS = frozenset({"derived", "catalog", "archive", "scratch"})
PRODUCER_DATA_MARKER = "stock-data-downloader/data"
SECRET_NAME_PATTERNS = (".env*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*")

# Only these extensions can be published; every one has a decoder or a signature check.
TEXT_EXTENSIONS = frozenset({"html", "htm", "js", "mjs", "cjs", "css", "json", "map", "svg", "txt", "md", "csv", "tsv"})
JSON_EXTENSIONS = frozenset({"json", "map"})
BINARY_SIGNATURES: Mapping[str, tuple[bytes, ...]] = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "ico": (b"\x00\x00\x01\x00",),
    "woff": (b"wOFF",),
    "woff2": (b"wOF2",),
}
SPECIAL_BINARY_EXTENSIONS = frozenset({"webp", "parquet"})
ARCHIVE_EXTENSIONS = frozenset({"zip"})
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | frozenset(BINARY_SIGNATURES) | SPECIAL_BINARY_EXTENSIONS | ARCHIVE_EXTENSIONS

# Built from fragments so this source never contains a literal that secret scanners flag.
_PRIVATE_KEY = r"-----BEGIN [A-Z ]*PRIV" + r"ATE KEY( BLOCK)?-----"
_TOKEN_SOURCES: tuple[tuple[str, str], ...] = (
    ("github-token", r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
    ("github-fine-grained-token", r"\bgithub_pat_[A-Za-z0-9_]{22,}"),
    ("aws-access-key-id", r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ("slack-token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    ("google-api-key", r"\bAIza[0-9A-Za-z_-]{35}"),
    ("anthropic-api-key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
)
# Cloudflare tokens have no documented fixed prefix, so no pattern is claimed for them.
_LOCAL_PRIVATE = r"(?:artifact[-_ ]?mode|data[-_ ]?mode)[\"'\s:=]{1,8}local-private"

TEXT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key-block", re.compile(_PRIVATE_KEY)),
    *((f"token-pattern:{name}", re.compile(src)) for name, src in _TOKEN_SOURCES),
    ("local-private-artifact", re.compile(_LOCAL_PRIVATE, re.IGNORECASE)),
)
BYTE_RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = tuple(
    (name, re.compile(pattern.pattern.encode("ascii"), pattern.flags & re.IGNORECASE)) for name, pattern in TEXT_RULES
)
_MEDIA = r"[A-Za-z0-9!#$&^_.+-]+"
# ``data:`` in any letter case (tab/newline may split it, as browsers strip them) followed by a media-type head.
# JS object keys such as ``data:rows,`` have no ``/`` and do not match; ``data:foo,x`` (plain text) is not gated.
DATA_URI = re.compile(
    r"(?<![A-Za-z0-9])d[\t\r\n]*a[\t\r\n]*t[\t\r\n]*a[\t\r\n]*:"
    rf"(?P<head>(?:{_MEDIA}/{_MEDIA})?(?:\s*;\s*{_MEDIA}(?:=[^,;\s\"'<>)]*)?)*\s*),"
    r"(?P<payload>(?:[A-Za-z0-9+/=_%.~!*:@&$;-]|\s(?=[A-Za-z0-9+/=\s]))*)",
    re.IGNORECASE,
)
IMAGE_URI_HEAD = re.compile(r"image/(?P<kind>png|jpeg|gif|webp)\s*;\s*base64\s*", re.IGNORECASE)
IMAGE_URI_EXT = {"png": "png", "jpeg": "jpg", "gif": "gif", "webp": "webp"}


# ---------------------------------------------------------------------------- masking


def mask(text: str, limit: int = 240) -> str:
    """Redact secret-looking runs and escape control/format characters for logs and comments.

    Escaping matters beyond looks: a raw newline in a file name could start a log line with
    ``::`` and be read by the Actions runner as a workflow command.
    """
    for rule, pattern in TEXT_RULES:
        if rule != "local-private-artifact":
            text = pattern.sub(f"<redacted:{rule}>", text)
    out = []
    for ch in text:
        if unicodedata.category(ch) in {"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"}:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    masked = "".join(out)
    return masked if len(masked) <= limit else masked[: limit - 3] + "..."


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str

    def __str__(self) -> str:
        return f"[{self.rule}] {mask(self.path)}"


@dataclass(frozen=True)
class TrackedFile:
    path: str
    mode: str
    blob: str


class PreviewGateError(Exception):
    def __init__(self, violations: Sequence[Violation]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(str(v) for v in self.violations))


class ReconcileError(Exception):
    """GitHub state could not be determined; nothing may be deployed."""


# ---------------------------------------------------------------------------- git access


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {mask(result.stderr.decode('utf-8', 'replace').strip())}")
    return result.stdout


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    """Paths changed on the PR side of the merge base (deleted files included)."""
    merge_base = git(repo, "merge-base", base, head).decode("ascii").strip()
    raw = git(repo, "diff", "--name-only", "-z", merge_base, head, "--")
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]


def report_ids(paths: Iterable[str]) -> list[str]:
    """Report ids whose ``web-report/`` folder has a changed path."""
    return sorted({m.group(1) for p in paths if (m := REPORT_PATH.match(p.replace("\\", "/")))})


def list_tracked(repo: Path, ref: str, report_id: str) -> list[TrackedFile]:
    """Entries under the report folder at ``ref`` (a commit) or in the index (``ref="INDEX"``)."""
    prefix = f"tasks/{report_id}/{REPORT_FOLDER}/"
    raw = git(repo, "ls-files", "-s", "-z", "--", prefix) if ref == "INDEX" else git(repo, "ls-tree", "-r", "-z", ref, "--", prefix)
    files = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        fields = meta.decode("ascii").split()
        mode, blob = (fields[0], fields[1]) if ref == "INDEX" else (fields[0], fields[2])
        files.append(TrackedFile(path.decode("utf-8", "surrogateescape"), mode, blob))
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
    """Local check mode only: walk the checkout without following links."""
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


# ---------------------------------------------------------------------------- content gate


def scan_text(text: str) -> list[str]:
    return [rule for rule, pattern in TEXT_RULES if pattern.search(text)]


def scan_raw(data: bytes) -> list[str]:
    """Byte-level scan, repeated with NULs removed so UTF-16 text inside a binary is seen too."""
    hits = {rule for rule, pattern in BYTE_RULES if pattern.search(data)}
    if b"\0" in data:
        stripped = data.replace(b"\0", b"")
        hits.update(rule for rule, pattern in BYTE_RULES if pattern.search(stripped))
    return sorted(hits)


def decode_text(data: bytes) -> str | None:
    """Strict decode: UTF-8 (optional BOM) or UTF-16 with a BOM. UTF-32 and anything else: None."""
    try:
        if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
            return None
        if data.startswith(b"\xef\xbb\xbf"):
            return data[3:].decode("utf-8")
        if data.startswith(b"\xff\xfe"):
            return data[2:].decode("utf-16-le")
        if data.startswith(b"\xfe\xff"):
            return data[2:].decode("utf-16-be")
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _json_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _json_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                yield f"{key}: {item}"
            else:
                yield str(key)
                yield from _json_strings(item)


def _signature_ok(ext: str, data: bytes) -> bool:
    if ext == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if ext == "parquet":
        return len(data) >= 12 and data[:4] == b"PAR1" and data[-4:] == b"PAR1"
    if ext == "zip":
        return data[:4] in (b"PK\x03\x04", b"PK\x05\x06")
    return data.startswith(BINARY_SIGNATURES[ext])


def _extension(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    return suffix[1:] if suffix else ""


def check_text_content(ext: str, data: bytes) -> list[str]:
    text = decode_text(data)
    if text is None:
        return ["text-decode-failed"]
    rules = set(scan_text(text))
    if "\0" in text:
        rules.add("text-contains-nul")  # BOM-less UTF-16 decodes as "valid" UTF-8 with NULs
    scan_target = text
    if ext in JSON_EXTENSIONS:
        try:
            json_text = "\n".join(_json_strings(json.loads(text)))
        except ValueError:
            rules.add("json-invalid")
        else:
            rules.update(scan_text(json_text))
            scan_target = json_text  # parsed strings: JSON escapes (\/, \uXXXX) are resolved
    rules.update(_scan_data_uris(scan_target))
    return sorted(rules)


def _scan_data_uris(text: str) -> set[str]:
    """Reject every ``data:`` URI except a small base64 raster image whose bytes match its declared type.

    The scheme is found case-insensitively, tolerating tab/newline splits, HTML entities and percent
    encoding. A URI that only appears after decoding is obfuscated and never allowed.
    """
    rules: set[str] = set()
    allowed: set[tuple[str, str]] = set()
    total = 0
    for match in DATA_URI.finditer(text):
        rule, size = _image_uri_rule(match.group("head"), match.group("payload"))
        if rule:
            rules.add(rule)
            continue
        allowed.add((match.group("head"), match.group("payload")))
        total += size
    if total > MAX_IMAGE_URI_TOTAL_BYTES:
        rules.add("data-uri-image-total-over-limit")
    unquoted = urllib.parse.unquote(text)
    for variant in {html.unescape(text), unquoted, html.unescape(unquoted), urllib.parse.unquote(html.unescape(text))}:
        if variant != text and any((m.group("head"), m.group("payload")) not in allowed for m in DATA_URI.finditer(variant)):
            rules.add("data-uri-obfuscated")
    return rules


def _image_uri_rule(head: str, payload: str) -> tuple[str | None, int]:
    """(rule, decoded size): rule is None when the URI is an allowed small raster image."""
    match = IMAGE_URI_HEAD.fullmatch(head)
    if match is None:
        return "data-uri-not-allowed", 0
    kind = match.group("kind").lower()
    compact = re.sub(r"\s+", "", payload)
    if len(compact) * 3 // 4 > MAX_IMAGE_URI_BYTES + 3:
        return "data-uri-image-over-limit", 0
    try:
        image = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return "data-uri-invalid-base64", 0
    if len(image) > MAX_IMAGE_URI_BYTES:
        return "data-uri-image-over-limit", 0
    if not _signature_ok(IMAGE_URI_EXT[kind], image):
        return "data-uri-signature-mismatch", 0
    return None, len(image)


def _arrow_has_text(arrow_type: Any) -> bool:
    import pyarrow as pa

    if (
        pa.types.is_string(arrow_type)
        or pa.types.is_large_string(arrow_type)
        or pa.types.is_binary(arrow_type)
        or pa.types.is_large_binary(arrow_type)
        or pa.types.is_fixed_size_binary(arrow_type)
        or getattr(pa.types, "is_string_view", lambda _t: False)(arrow_type)
        or getattr(pa.types, "is_binary_view", lambda _t: False)(arrow_type)
    ):
        return True
    if pa.types.is_dictionary(arrow_type):
        return _arrow_has_text(arrow_type.value_type)
    return any(_arrow_has_text(arrow_type.field(i).type) for i in range(arrow_type.num_fields))


def _arrow_buffers(array: Any) -> Iterator[bytes]:
    import pyarrow as pa

    if isinstance(array, pa.DictionaryArray):
        yield from _arrow_buffers(array.dictionary)
        return
    for buffer in array.buffers():
        if buffer is not None:
            yield buffer.to_pybytes()


def check_parquet_content(data: bytes) -> list[str]:
    """Decompress and scan every text-bearing column, column names and file metadata."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return ["parquet-check-unavailable"]
    try:
        parquet = pq.ParquetFile(pa.BufferReader(data))
        metadata = parquet.metadata
        unpacked = sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups))
        if unpacked > MAX_PARQUET_UNPACKED:
            return ["parquet-over-limit"]
        schema = parquet.schema_arrow
        texts = [name.encode("utf-8") for name in schema.names]
        for key, value in (schema.metadata or {}).items():
            texts.extend((key, value))
        rules = set(scan_raw(b"\n".join(texts)))
        table = parquet.read()
        for column in table.columns:
            if not _arrow_has_text(column.type):
                continue
            for chunk in column.chunks:
                rules.update(scan_raw(b"\n".join(_arrow_buffers(chunk))))
    except Exception:  # noqa: BLE001 - any reader failure is a fail-closed gate result
        return ["parquet-invalid"]
    return sorted(rules)


def check_zip_content(data: bytes, display: str) -> list[Violation]:
    """Bounded archive check: plain members only, every member gated like a report file."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        return [Violation("zip-invalid", display)]
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        return [Violation("zip-too-many-members", display)]
    found: list[Violation] = []
    unpacked = 0
    for info in infos:
        where = f"{display}!{info.filename}"
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            found.append(Violation("zip-encrypted-member", where))
            continue
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            found.append(Violation("zip-unsupported-compression", where))
            continue
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in PurePosixPath(name).parts:
            found.append(Violation("zip-unsafe-member-name", where))
            continue
        found.extend(check_path(name, where))
        if _extension(name) in ARCHIVE_EXTENSIONS:
            found.append(Violation("nested-archive", where))
            continue
        if info.file_size > MAX_FILE_BYTES or info.file_size > max(info.compress_size, 1) * MAX_ARCHIVE_RATIO:
            found.append(Violation("zip-member-over-limit", where))
            continue
        try:
            with archive.open(info) as handle:
                member = handle.read(MAX_FILE_BYTES + 1)
        except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError, EOFError):
            found.append(Violation("zip-invalid", where))
            continue
        unpacked += len(member)
        if len(member) > MAX_FILE_BYTES or unpacked > MAX_ARCHIVE_UNPACKED:
            found.append(Violation("zip-over-limit", where))
            break
        found.extend(Violation(rule, where) for rule in content_rules(name, member))
    return found


def content_rules(name: str, data: bytes) -> list[str]:
    """Rules for a non-archive file decided by its extension; unknown formats fail closed."""
    ext = _extension(name)
    if ext not in ALLOWED_EXTENSIONS or ext in ARCHIVE_EXTENSIONS:
        return sorted({"extension-not-allowed", *scan_raw(data)})
    if ext in TEXT_EXTENSIONS:
        return check_text_content(ext, data)
    if not _signature_ok(ext, data):
        return ["signature-mismatch"]
    rules = set(scan_raw(data))
    if ext == "parquet":
        rules.update(check_parquet_content(data))
    return sorted(rules)


def check_path(rel: str, display: str) -> list[Violation]:
    violations: list[Violation] = []
    pure = PurePosixPath(rel)
    lowered = [part.lower() for part in pure.parts]
    if FORBIDDEN_COMPONENTS.intersection(lowered[:-1]) or PRODUCER_DATA_MARKER in rel.lower():
        violations.append(Violation("data-root-path", display))
    if any(PurePosixPath(pure.name.lower()).match(p) for p in SECRET_NAME_PATTERNS):
        violations.append(Violation("secret-file-name", display))
    elif any(part.startswith(".") for part in pure.parts):
        violations.append(Violation("hidden-path", display))  # Pages artifacts drop dotfiles
    if mask(rel, limit=10_000) != rel:
        violations.append(Violation("unsafe-file-name", display))
    return violations


def check_file(rel_to_report: str, full_path: str, mode: str, data: bytes) -> list[Violation]:
    violations: list[Violation] = []
    if mode == SYMLINK_MODE:
        violations.append(Violation("symlink-in-git", full_path))
    if mode == GITLINK_MODE:
        violations.append(Violation("submodule-in-git", full_path))
    violations.extend(check_path(rel_to_report, full_path))
    if len(data) > MAX_FILE_BYTES:
        violations.append(Violation("file-over-25MiB", full_path))
        return violations
    if mode in (SYMLINK_MODE, GITLINK_MODE):
        return violations
    if _extension(rel_to_report) in ARCHIVE_EXTENSIONS:
        if not _signature_ok("zip", data):
            violations.append(Violation("signature-mismatch", full_path))
        else:
            violations.extend(Violation(rule, full_path) for rule in scan_raw(data))
            violations.extend(check_zip_content(data, full_path))
    else:
        violations.extend(Violation(rule, full_path) for rule in content_rules(rel_to_report, data))
    return violations


# ---------------------------------------------------------------------------- packaging

_NOINDEX = '<meta name="robots" content="noindex, nofollow, noarchive">'
_STYLE = "body{margin:0;font:14px/1.5 system-ui,sans-serif}header{padding:8px 12px;background:#fff3cd;color:#3b2f00;border-bottom:1px solid #e0c36a}"


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
{_NOINDEX}
<title>PR 預覽 #{pr}</title>
<style>
{_STYLE}
header strong{{margin-right:8px}}
h2{{margin:8px 12px;font-size:14px}}
iframe{{width:100%;height:calc(100vh - 90px);min-height:480px;border:0}}
</style>
</head>
<body>
<header><strong>PR 預覽</strong> PR #{pr} · commit <code>{esc(sha[:7])}</code> · 建置 {esc(built_at)} · 分支 <code>{esc(mask(branch))}</code></header>
{items}
</body>
</html>
"""


@dataclass(frozen=True)
class PlannedFile:
    report_id: str
    rel: str
    blob: str
    data: bytes


def gate_reports(repo: Path, ref: str, ids: Sequence[str]) -> list[PlannedFile]:
    """Gate every tracked file of ``ids`` at ``ref``; raises PreviewGateError with all violations."""
    violations: list[Violation] = []
    planned: list[PlannedFile] = []
    total = 0
    for report_id in ids:
        base = f"tasks/{report_id}/{REPORT_FOLDER}/"
        tracked = list_tracked(repo, ref, report_id)
        if not tracked:
            continue  # the PR deleted this report
        if ref == "INDEX":
            violations.extend(untracked_or_linked(repo, report_id, tracked))
        if not any(item.path == base + "index.html" and item.mode.startswith("100") for item in tracked):
            violations.append(Violation("missing-index-html", base + "index.html"))
        for item in tracked:
            data = b"" if item.mode in (SYMLINK_MODE, GITLINK_MODE) else read_blob(repo, item.blob)
            total += len(data)
            violations.extend(check_file(item.path[len(base) :], item.path, item.mode, data))
            planned.append(PlannedFile(report_id, item.path[len(base) :], item.blob, data))
    if total > MAX_TOTAL_BYTES:
        violations.append(Violation("total-over-50MB", f"{total} bytes"))
    if violations:
        raise PreviewGateError(violations)
    return planned


def write_preview(out: Path, planned: Sequence[PlannedFile], pr: int, sha: str, branch: str, built_at: str) -> dict[str, object]:
    built = sorted({p.report_id for p in planned})
    manifest_files = []
    for item in planned:
        target = out / "reports" / item.report_id / item.rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.data)
        manifest_files.append({"path": f"reports/{item.report_id}/{item.rel}", "blob": item.blob, "bytes": len(item.data)})
    (out / "_preview").mkdir(parents=True, exist_ok=True)
    (out / "_preview" / "index.html").write_text(shell_page(pr, sha, branch, built_at, built), encoding="utf-8")
    manifest = {"pr": pr, "sha": sha, "branch": mask(branch), "built_at": built_at, "reports": built, "files": manifest_files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def build_preview(repo: Path, out: Path, pr: int, sha: str, branch: str, built_at: str, ids: Sequence[str], ref: str = "INDEX") -> dict[str, object]:
    """Gate and write one PR's preview into ``out``; raises PreviewGateError before writing anything."""
    planned = gate_reports(repo, ref, ids)
    return write_preview(out, planned, pr, sha, branch, built_at)


# ---------------------------------------------------------------------------- reconcile


@dataclass(frozen=True)
class PullRequest:
    number: int
    head_sha: str
    head_ref: str


def _required(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ReconcileError(f"pull request payload is missing {'.'.join(keys)}")
        value = value[key]
    return value


def eligible_pulls(raw_pulls: Sequence[Mapping[str, Any]], repository: str, base_branch: str = "main") -> list[PullRequest]:
    """Open, same-repository PRs into ``base_branch`` that carry the preview label right now.

    A malformed payload raises ReconcileError (fail closed) instead of being skipped.
    """
    eligible = []
    for raw in raw_pulls:
        number = _required(raw, "number")
        sha = _required(raw, "head", "sha")
        labels = _required(raw, "labels")
        head_repo = _required(raw, "head", "repo")
        if not isinstance(number, int) or not isinstance(sha, str) or not SHA_PATTERN.match(sha) or not isinstance(labels, list):
            raise ReconcileError("pull request payload has an unexpected shape")
        if _required(raw, "state") != "open":
            continue
        if _required(raw, "base", "ref") != base_branch or _required(raw, "base", "repo", "full_name") != repository:
            continue
        if not isinstance(head_repo, dict) or head_repo.get("full_name") != repository:
            continue  # fork PRs (or a deleted fork) are never published
        if PREVIEW_LABEL not in {label.get("name") for label in labels if isinstance(label, dict)}:
            continue
        eligible.append(PullRequest(number, sha, str(_required(raw, "head", "ref"))))
    return sorted(eligible, key=lambda p: p.number)


@dataclass
class PrOutcome:
    status: str  # "included" | "rejected" | "no-reports"
    bytes: int = 0
    violations: list[str] = field(default_factory=list)


@dataclass
class SitePlan:
    included: dict[int, str] = field(default_factory=dict)
    rejected: dict[int, dict[str, Any]] = field(default_factory=dict)
    no_reports: list[int] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "included": {str(k): v for k, v in sorted(self.included.items())},
            "rejected": {str(k): v for k, v in sorted(self.rejected.items())},
            "no_reports": sorted(self.no_reports),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SitePlan:
        return cls(
            included={int(k): str(v) for k, v in data["included"].items()},
            rejected={int(k): dict(v) for k, v in data["rejected"].items()},
            no_reports=[int(n) for n in data["no_reports"]],
        )


def plan_site(
    pulls: Sequence[PullRequest],
    build: Callable[[PullRequest], PrOutcome],
    max_site_bytes: int = MAX_SITE_BYTES,
    drop: Callable[[int], None] | None = None,
) -> SitePlan:
    """Build each eligible PR; a rejected PR is left out without stopping the others.

    ``drop`` removes the output of a PR that was built but pushed the site over its cap.
    """
    plan = SitePlan()
    total = 0
    for pull in pulls:
        outcome = build(pull)
        if outcome.status == "included" and total + outcome.bytes > max_site_bytes:
            if drop is not None:
                drop(pull.number)
            violations = [str(Violation("site-over-limit", f"pr-{pull.number}"))]
            plan.rejected[pull.number] = {"sha": pull.head_sha, "violations": violations}
            continue
        if outcome.status == "included":
            total += outcome.bytes
            plan.included[pull.number] = pull.head_sha
        elif outcome.status == "no-reports":
            plan.no_reports.append(pull.number)
        else:
            plan.rejected[pull.number] = {"sha": pull.head_sha, "violations": outcome.violations}
    return plan


def stale_entries(included: Mapping[int, str], current: Sequence[PullRequest]) -> list[str]:
    """Built entries that are no longer eligible at the same head; empty means safe to deploy."""
    now = {p.number: p.head_sha for p in current}
    problems = []
    for number, sha in sorted(included.items()):
        if number not in now:
            problems.append(f"PR #{number} is no longer eligible")
        elif now[number] != sha:
            problems.append(f"PR #{number} head moved from {sha[:7]} to {now[number][:7]}")
    return problems


def site_index(plan: SitePlan, built_at: str, gate_commit: str) -> str:
    esc = html.escape
    rows = "\n".join(f'<li><a href="pr-{n}/_preview/">PR #{n}</a> · commit <code>{esc(sha[:7])}</code></li>' for n, sha in sorted(plan.included.items()))
    body = f"<ul>\n{rows}\n</ul>" if rows else "<p>目前沒有預覽。</p>"
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{_NOINDEX}
<title>報告預覽</title>
<style>{_STYLE}main{{padding:0 16px}}</style>
</head>
<body>
<header><strong>報告預覽</strong> 建置 {esc(built_at)} · 閘門 commit <code>{esc(gate_commit[:7])}</code></header>
<main>{body}</main>
</body>
</html>
"""


def write_site_root(site: Path, plan: SitePlan, built_at: str, gate_commit: str) -> None:
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(site_index(plan, built_at, gate_commit), encoding="utf-8")
    (site / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    previews = [{"pr": n, "sha": sha, "path": f"pr-{n}/_preview/"} for n, sha in sorted(plan.included.items())]
    record = {"generated_at": built_at, "gate_commit": gate_commit, "previews": previews}
    (site / "previews.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def build_pull(repo: Path, site: Path, pull: PullRequest, base_ref: str, built_at: str, fetch: Callable[[str], None]) -> PrOutcome:
    """Read one PR head as git objects only (never checked out or executed) and package it."""
    try:
        fetch(pull.head_sha)
        resolved = git(repo, "rev-parse", "--verify", f"{pull.head_sha}^{{commit}}").decode("ascii").strip()
        if resolved != pull.head_sha:
            return PrOutcome("rejected", violations=[f"[head-mismatch] pr-{pull.number}"])
        ids = report_ids(changed_files(repo, base_ref, pull.head_sha))
    except RuntimeError:
        return PrOutcome("rejected", violations=[f"[head-unavailable] pr-{pull.number}"])
    if not ids:
        return PrOutcome("no-reports")
    try:
        planned = gate_reports(repo, pull.head_sha, ids)
    except PreviewGateError as error:
        return PrOutcome("rejected", violations=[str(v) for v in error.violations])
    except RuntimeError:
        return PrOutcome("rejected", violations=[f"[git-read-failed] pr-{pull.number}"])
    if not planned:
        return PrOutcome("no-reports")
    out = site / f"pr-{pull.number}"
    if out.exists():
        shutil.rmtree(out)
    write_preview(out, planned, pull.number, pull.head_sha, pull.head_ref, built_at)
    return PrOutcome("included", bytes=sum(len(p.data) for p in planned))


def remove_pull_output(site: Path, number: int) -> None:
    out = site / f"pr-{number}"
    if out.exists():
        shutil.rmtree(out)


# ---------------------------------------------------------------------------- GitHub API


class GitHubApi(Protocol):
    def get(self, path: str) -> Any: ...

    def send(self, method: str, path: str, body: Mapping[str, Any]) -> Any: ...


class UrllibGitHubApi:
    """Minimal REST client; any HTTP, network or JSON failure raises ReconcileError."""

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self.token = token
        self.base_url = base_url

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        request = urllib.request.Request(  # noqa: S310 - fixed https base URL
            self.base_url + path,
            method=method,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "stock-research-report-preview",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8") or "null")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            raise ReconcileError(f"GitHub API {method} {path.split('?')[0]} failed: {type(error).__name__}") from error

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def send(self, method: str, path: str, body: Mapping[str, Any]) -> Any:
        return self._request(method, path, body)


def _paginate(api: GitHubApi, path: str) -> list[Any]:
    items: list[Any] = []
    separator = "&" if "?" in path else "?"
    for page in range(1, MAX_PULL_PAGES + 1):
        batch = api.get(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ReconcileError("GitHub API returned an unexpected list payload")
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise ReconcileError("too many pages; refusing to guess the rest")


def list_open_pulls(api: GitHubApi, repository: str, base_branch: str = "main") -> list[Any]:
    return _paginate(api, f"/repos/{repository}/pulls?state=open&base={base_branch}")


# ---------------------------------------------------------------------------- PR comments


def comment_plan(plan: SitePlan, previous: set[int] | None, deployed_at: str, page_url: str, run_url: str) -> dict[int, tuple[str, str]]:
    """Comment bodies, keyed by PR, written only after a successful deployment.

    The state key lets repeated scheduled runs skip comments whose state has not changed.
    """
    bodies: dict[int, tuple[str, str]] = {}
    root = page_url.rstrip("/")
    cache_note = "Pages 的快取可能讓舊內容再顯示幾分鐘；網址公開但不易猜，不是存取控制。"
    for number, sha in plan.included.items():
        key = f"deployed:{sha}"
        bodies[number] = (
            key,
            f"PR 預覽已部署：{root}/pr-{number}/_preview/\n\n- commit：`{sha[:7]}`\n- 部署完成：{deployed_at}\n- 執行紀錄：{run_url}\n- {cache_note}",
        )
    for number, info in plan.rejected.items():
        lines = "\n".join(f"  - `{v}`" for v in info["violations"][:20])
        key = f"rejected:{info['sha']}"
        bodies[number] = (
            key,
            f"PR 預覽未發布（閘門未通過，舊版本已不在網站上）。\n\n- commit：`{str(info['sha'])[:7]}`\n"
            f"- 部署完成：{deployed_at}\n- 規則與檔名（已遮罩）：\n{lines}\n- 執行紀錄：{run_url}",
        )
    for number in sorted((previous or set()) - set(plan.included) - set(plan.rejected)):
        bodies[number] = ("removed", f"PR 預覽已撤下（PR 關閉、移除 preview 標籤或不再含報告變更）。\n\n- 撤下部署完成：{deployed_at}\n- {cache_note}")
    return bodies


def _marker(key: str) -> str:
    return f"{COMMENT_MARKER}\n<!-- report-preview-state: {key} -->"


def apply_comments(api: GitHubApi, repository: str, bodies: Mapping[int, tuple[str, str]]) -> list[str]:
    """Create or update the single marker comment per PR; returns a log of actions taken."""
    log = []
    for number, (key, body) in sorted(bodies.items()):
        comments = _paginate(api, f"/repos/{repository}/issues/{number}/comments")
        existing = next((c for c in comments if isinstance(c, dict) and str(c.get("body", "")).startswith(COMMENT_MARKER)), None)
        text = f"{_marker(key)}\n{body}\n"
        if existing is not None and _marker(key) in str(existing.get("body", "")):
            log.append(f"PR #{number}: unchanged ({key.split(':')[0]})")
            continue
        if existing is None:
            if key == "removed":
                continue  # never announced, nothing to retract
            api.send("POST", f"/repos/{repository}/issues/{number}/comments", {"body": text})
        else:
            api.send("PATCH", f"/repos/{repository}/issues/comments/{existing['id']}", {"body": text})
        log.append(f"PR #{number}: {key.split(':')[0]}")
    return log


def read_previous(url: str) -> set[int] | None:
    """Best-effort read of the live site's preview list; None when it cannot be read."""
    try:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - Pages URL from the API
            record = json.loads(response.read().decode("utf-8"))
        return {int(item["pr"]) for item in record["previews"]}
    except urllib.error.HTTPError as error:
        return set() if error.code == 404 else None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError, OSError):
        return None
