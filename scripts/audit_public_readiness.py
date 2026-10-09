"""Bounded, offline Git-content audit; findings never include matched values.

This is a triage aid, not a data-license or comprehensive privacy certification.
Only objects reachable from explicit refs are read. No worktree file is opened.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import lzma
import re
import struct
import subprocess
import sys
import zipfile
import zlib
from array import array
from bisect import bisect_right
from pathlib import Path

LOGGER = logging.getLogger(__name__)
RULES = [
    ("github_token", "CRITICAL", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})")),
    ("private_key", "CRITICAL", re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("aws_access_key", "CRITICAL", re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    ("credential_url", "CRITICAL", re.compile(rb"https?://[^\s/<>\"']+@")),
    ("windows_user_path", "LOW", re.compile(rb"[A-Za-z]:[\\/]Users[\\/][^\s\\/\"']+", re.I)),
]
PARTS = re.compile(r"^(.*?)(?:\.(\d+)\.bin|\.part-(\d+)\.bin|\.part(\d+))$")


def safe(value: str) -> str:
    """Sanitize even attacker-controlled filenames/ref names, not just content."""
    data = value.encode("utf-8", "replace")
    for _, _, pattern in RULES:
        data = pattern.sub(b"[REDACTED]", data)
    data = re.sub(rb"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", b"[EMAIL]", data)
    return data.decode("utf-8", "replace")


class AuditError(Exception):
    pass


def git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    except OSError:
        raise AuditError("git_unavailable") from None
    if result.returncode:
        raise AuditError("git_operation_failed")
    return result.stdout


class Scanner:
    def __init__(
        self,
        max_bytes: int = 16 * 1024 * 1024,
        max_total: int = 128 * 1024 * 1024,
        max_entries: int = 2000,
        max_depth: int = 3,
        max_findings: int = 2000,
        max_decoder_memory: int = 64 * 1024 * 1024,
        max_zip_metadata: int = 1024 * 1024,
    ):
        self.max_bytes, self.max_total = max_bytes, max_total
        self.max_entries, self.max_depth = max_entries, max_depth
        self.max_findings, self.max_decoder_memory = max_findings, max_decoder_memory
        self.max_zip_metadata = max_zip_metadata
        self.finding_limit_hit = False
        self.total = self.entries = 0
        self.findings: list[dict] = []
        self.gaps: list[dict] = []
        self.inventory: list[dict] = []

    def gap(self, meta: dict, reason: str):
        self.gaps.append({**meta, "reason": reason})

    def zip_preflight(self, data: bytes, meta: dict) -> bool:
        """Bound central-directory bytes and actual records before ZipFile allocates.

        EOCD counts are untrusted: walk fixed headers without decoding names or
        constructing ZipInfo objects. ZIP64/multi-disk formats remain explicit gaps.
        """
        end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
        if end < 0 or end + 22 > len(data):
            raise zipfile.BadZipFile
        disk, cd_disk, disk_count, count, size, offset, comment = struct.unpack_from("<4H2LH", data, end + 4)
        if end + 22 + comment != len(data):
            raise zipfile.BadZipFile
        if count == 0xFFFF or size == 0xFFFFFFFF or offset == 0xFFFFFFFF or data[max(0, end - 20) : end - 16] == b"PK\x06\x07":
            self.gap(meta, "unsupported_zip64_metadata_bound")
            return False
        if disk or cd_disk or disk_count != count:
            self.gap(meta, "unsupported_multidisk_zip")
            return False
        if size > self.max_zip_metadata:
            self.gap(meta, "archive_metadata_limit")
            return False
        # Match ZipFile's concatenated-prefix handling, without trusting offset.
        start = end - size
        if start < 0 or offset > start:
            raise zipfile.BadZipFile
        cursor, actual = start, 0
        while cursor < end:
            if cursor + 46 > end or data[cursor : cursor + 4] != b"PK\x01\x02":
                raise zipfile.BadZipFile
            actual += 1
            if self.entries + actual > self.max_entries:
                self.gap(meta, "archive_entry_limit")
                return False
            name_size, extra_size, comment_size = struct.unpack_from("<3H", data, cursor + 28)
            cursor += 46 + name_size + extra_size + comment_size
            if cursor > end:
                raise zipfile.BadZipFile
        if actual != count:
            raise zipfile.BadZipFile
        self.entries += actual  # Include directories and reserve nested/global budget.
        return True

    def scan(self, data: bytes, meta: dict, depth: int = 0, expand: bool = True):
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                data = data.decode("utf-16").encode("utf-8")
            except UnicodeError:
                self.gap(meta, "invalid_utf16_text")
        # Build the line index once, without repeatedly copying/scanning prefixes.
        if not self.finding_limit_hit:
            newlines = array("Q", (m.start() for m in re.finditer(b"\n", data)))
            for rule, severity, pattern in RULES:
                for match in pattern.finditer(data):
                    if len(self.findings) >= self.max_findings:
                        self.gap(meta, "finding_limit")
                        self.finding_limit_hit = True
                        break
                    self.findings.append({**meta, "line": bisect_right(newlines, match.start()) + 1, "rule": rule, "severity": severity})
                if self.finding_limit_hit:
                    break
        if not expand:
            return
        name = meta.get("member", meta.get("path", "")).lower()
        is_zip = data.startswith(b"PK\x03\x04") or name.endswith(".zip")
        is_gzip = data.startswith(b"\x1f\x8b") or name.endswith(".gz")
        is_xz = data.startswith(b"\xfd7zXZ\x00") or name.endswith(".xz")
        if data.startswith((b"PAR1", b"SQLite format 3")) or name.endswith((".parquet", ".sqlite", ".db")):
            self.gap(meta, "opaque_structured_data")
        if not (is_zip or is_gzip or is_xz):
            return
        if depth >= self.max_depth:
            self.gap(meta, "archive_depth_limit")
            return
        try:
            if is_zip:
                if not self.zip_preflight(data, meta):
                    return
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for entry in archive.infolist():
                        if entry.is_dir():
                            continue
                        child = {**meta, "member": safe(meta.get("member", "") + "!" + entry.filename)}
                        self.inventory.append({**child, "size": entry.file_size, "extension": safe(Path(entry.filename).suffix)})
                        if entry.flag_bits & 1:
                            self.gap(child, "encrypted_archive_member")
                            continue
                        if entry.compress_type == zipfile.ZIP_LZMA:
                            self.gap(child, "unsupported_zip_lzma_memory_bound")
                            continue
                        if entry.file_size > self.max_bytes or self.total + entry.file_size > self.max_total:
                            self.gap(child, "archive_expansion_limit")
                            continue
                        with archive.open(entry) as stream:
                            expanded = stream.read(self.max_bytes + 1)
                        self.consume(expanded, child, depth)
            else:
                bound = min(self.max_bytes, max(0, self.max_total - self.total))
                if is_gzip:
                    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
                        expanded = stream.read(bound + 1)
                else:
                    expanded_buffer = bytearray()
                    remaining = data
                    while remaining and len(expanded_buffer) <= bound:
                        decoder = lzma.LZMADecompressor(memlimit=min(self.max_decoder_memory, self.max_total))
                        try:
                            expanded_buffer.extend(decoder.decompress(remaining, max_length=bound + 1 - len(expanded_buffer)))
                        except lzma.LZMAError as error:
                            if "Memory usage limit exceeded" in str(error):
                                self.gap(meta, "archive_decoder_memory_limit")
                                return
                            raise
                        if len(expanded_buffer) > bound:
                            break
                        if not decoder.eof:
                            raise EOFError
                        remaining = decoder.unused_data
                    expanded = bytes(expanded_buffer)
                self.consume(expanded, {**meta, "member": safe(name + "!stream")}, depth)
        except (OSError, EOFError, ValueError, RuntimeError, zipfile.BadZipFile, lzma.LZMAError, zlib.error):
            self.gap(meta, "malformed_or_unreadable_archive")

    def consume(self, data: bytes, meta: dict, depth: int):
        if len(data) > self.max_bytes or self.total + len(data) > self.max_total:
            self.gap(meta, "archive_expansion_limit")
            return
        self.total += len(data)
        self.scan(data, meta, depth + 1)


def tree(repo: Path, sha: str) -> dict[str, str]:
    result = {}
    for record in git(repo, "ls-tree", "--full-tree", "-r", "-z", sha).split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        _, kind, oid = header.split()
        if kind == b"blob":
            result[path.decode("utf-8", "replace")] = oid.decode("ascii")
    return result


def read_blobs(repo: Path, objects: dict[str, set[str]], scanner: Scanner):
    """One batch process; bounded reads including oversized-object draining."""
    with subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        assert process.stdin is not None and process.stdout is not None
        for oid, paths in objects.items():
            process.stdin.write((oid + "\n").encode("ascii"))
            process.stdin.flush()
            fields = process.stdout.readline().split()
            if len(fields) != 3:
                raise AuditError("git_object_read_failed")
            size = int(fields[2])
            if size > scanner.max_bytes:
                remaining = size
                while remaining:
                    chunk = process.stdout.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise AuditError("git_object_read_failed")
                    remaining -= len(chunk)
                process.stdout.read(1)
                for path in sorted(paths):
                    scanner.gap({"blob": oid, "path": safe(path)}, "blob_size_limit")
                yield oid, None
            else:
                data = process.stdout.read(size)
                process.stdout.read(1)
                if len(data) != size:
                    raise AuditError("git_object_read_failed")
                yield oid, data
        process.stdin.close()
        if process.wait():
            raise AuditError("git_object_read_failed")


def audit(repo: Path, refs: list[str], history: bool, **limits) -> dict:
    top = Path(git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if top != repo.resolve():
        raise AuditError("repository_root_required")
    scanner = Scanner(**limits)
    LOGGER.info("Auditing explicit repository %s (%d refs, history=%s)", safe(str(repo)), len(refs), history)
    resolved = [{"ref": safe(ref), "sha": git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode("ascii").strip()} for ref in refs]
    trees = {item["sha"]: tree(repo, item["sha"]) for item in resolved}
    objects: dict[str, set[str]] = {}
    for paths in trees.values():
        for path, oid in paths.items():
            objects.setdefault(oid, set()).add(path)
    if history:
        for record in git(repo, "rev-list", "--objects", *trees).splitlines():
            history_oid, _, history_path = record.partition(b" ")
            objects.setdefault(history_oid.decode("ascii"), set()).add(history_path.decode("utf-8", "replace"))
        # rev-list names only one path per object. Raw history preserves aliases,
        # renames (as delete/add), and deleted segment names for every reachable ref.
        records = git(repo, "log", "--format=", "--raw", "-z", "--no-abbrev", "--no-renames", "--root", "-m", *trees).split(b"\0")
        index = 0
        while index < len(records):
            header = records[index].lstrip(b"\n")
            index += 1
            if not header.startswith(b":"):
                continue
            if index >= len(records):
                raise AuditError("git_history_inventory_failed")
            path = records[index].decode("utf-8", "replace")
            index += 1
            fields = header.split()
            if len(fields) != 5:
                raise AuditError("git_history_inventory_failed")
            for raw_oid in fields[2:4]:
                if raw_oid.strip(b"0"):
                    objects.setdefault(raw_oid.decode("ascii"), set()).add(path)
        # Filter commit/tree objects through batch metadata before reading content.
        metadata = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch-check"], input=("\n".join(objects) + "\n").encode("ascii"), capture_output=True)
        if metadata.returncode:
            raise AuditError("git_object_inventory_failed")
        blob_ids = {line.split()[0].decode("ascii") for line in metadata.stdout.splitlines() if len(line.split()) == 3 and line.split()[1] == b"blob"}
        objects = {oid: paths for oid, paths in objects.items() if oid in blob_ids}
    part_ids = {oid for paths in trees.values() for path, oid in paths.items() if PARTS.match(path)}
    parts = {}
    part_bytes = 0
    for oid, data in read_blobs(repo, objects, scanner):
        if data is not None:
            for path in sorted(objects[oid]):
                meta = {"blob": oid, "path": safe(path)}
                is_part = bool(PARTS.match(path))
                scanner.scan(data, meta, expand=not is_part)
                if history and is_part:
                    scanner.gap(meta, "historical_segment_combinations_not_reassembled")
            if oid in part_ids and part_bytes + len(data) <= scanner.max_total:
                parts[oid] = data
                part_bytes += len(data)
    for sha, paths in trees.items():
        groups: dict[str, list[tuple[int, str, str]]] = {}
        for path, oid in paths.items():
            match = PARTS.match(path)
            if match:
                groups.setdefault(match[1], []).append((int(next(x for x in match.groups()[1:] if x)), path, oid))
        for base, entries in groups.items():
            entries.sort()
            meta = {"ref_sha": sha, "path": safe(base), "blob": "reassembled"}
            indices = [x[0] for x in entries]
            if indices[0] not in (0, 1) or indices != list(range(indices[0], indices[0] + len(indices))):
                scanner.gap(meta, "missing_archive_segments")
                continue
            if any(oid not in parts for _, _, oid in entries) or sum(len(parts.get(oid, b"")) for _, _, oid in entries) > scanner.max_bytes:
                scanner.gap(meta, "segment_reassembly_limit")
                continue
            scanner.scan(b"".join(parts[oid] for _, _, oid in entries), meta)
    return {
        "repo": safe(str(repo.resolve())),
        "refs": resolved,
        "history": history,
        "blobs": len(objects),
        "findings": scanner.findings,
        "coverage_gaps": scanner.gaps,
        "limits": {
            "max_bytes": scanner.max_bytes,
            "max_total": scanner.max_total,
            "max_entries": scanner.max_entries,
            "max_depth": scanner.max_depth,
            "max_findings": scanner.max_findings,
            "max_decoder_memory": scanner.max_decoder_memory,
            "max_zip_metadata": scanner.max_zip_metadata,
        },
        "expanded_bytes": scanner.total,
        "archive_inventory": scanner.inventory,
        "scope_complete": not scanner.gaps,
        "excluded": [
            "untracked_and_ignored_files",
            "submodule_contents",
            "remote_only_refs",
            "release_assets",
            "unreachable_objects",
            "commit_metadata",
            "personal_data_semantics_and_redistribution_rights",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", required=True, type=Path)
    parser.add_argument("--ref", action="append")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--max-total", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--max-entries", type=int, default=2000)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-findings", type=int, default=2000)
    parser.add_argument("--max-decoder-memory", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-zip-metadata", type=int, default=1024 * 1024)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    limit_keys = ("max_bytes", "max_total", "max_entries", "max_depth", "max_findings", "max_decoder_memory", "max_zip_metadata")
    if any(getattr(args, key) <= 0 for key in limit_keys):
        sys.stdout.write(json.dumps({"schema_version": 1, "error": "limits_must_be_positive", "repositories": []}) + "\n")
        return 2
    reports = []
    for repo in args.repo:
        try:
            reports.append(audit(repo, args.ref or ["HEAD"], args.history, **{key: getattr(args, key) for key in limit_keys}))
        except (AuditError, OSError, ValueError):
            reports.append({"repo": safe(str(repo)), "error": "audit_failed", "scope_complete": False})
    sys.stdout.write(json.dumps({"schema_version": 1, "repositories": reports}, ensure_ascii=True, indent=2) + "\n")
    if any(f["severity"] == "CRITICAL" for report in reports for f in report.get("findings", [])):
        return 1
    return 2 if any(not report["scope_complete"] for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
