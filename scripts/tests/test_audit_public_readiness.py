"""Functional audits use synthetic credentials in disposable Git repositories."""

import importlib.util
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("audit_public_readiness", Path(__file__).parents[1] / "audit_public_readiness.py")
assert SPEC and SPEC.loader
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    run(tmp_path, "init")
    run(tmp_path, "config", "user.name", "Audit Fixture")
    run(tmp_path, "config", "user.email", "fixture@example.invalid")
    return tmp_path


def commit(repo: Path) -> None:
    run(repo, "add", ".")
    run(repo, "commit", "-m", "Fixture")


def token() -> str:
    return "gh" + "p_" + "A" * 36


def zipped(value: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("evidence.txt", value)
    return stream.getvalue()


@pytest.mark.parametrize("forged_count", [False, True])
@pytest.mark.parametrize("directories", [False, True])
def test_zip_member_amplification_rejected_before_reader(monkeypatch: pytest.MonkeyPatch, forged_count: bool, directories: bool) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for index in range(100):
            archive.writestr(f"entry-{index}" + ("/" if directories else ""), b"")
    payload = bytearray(stream.getvalue())
    if forged_count:
        end = payload.rfind(b"PK\x05\x06")
        payload[end + 8 : end + 12] = b"\x01\x00" * 2
    monkeypatch.setattr(scanner.zipfile, "ZipFile", lambda *a, **k: pytest.fail("reader allocated before preflight"))
    instance = scanner.Scanner(max_entries=10)
    instance.scan(bytes(payload), {"path": "many.zip"})
    assert [gap["reason"] for gap in instance.gaps] == ["archive_entry_limit"]
    assert not instance.inventory


def test_zip_metadata_amplification_rejected_before_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("small.txt")
        info.comment = b"A" * 10000
        archive.writestr(info, b"safe")
    monkeypatch.setattr(scanner.zipfile, "ZipFile", lambda *a, **k: pytest.fail("reader allocated before preflight"))
    instance = scanner.Scanner(max_zip_metadata=1024)
    instance.scan(stream.getvalue(), {"path": "metadata.zip"})
    assert [gap["reason"] for gap in instance.gaps] == ["archive_metadata_limit"]


@pytest.mark.parametrize("kind", ["count", "length", "zip64", "multidisk"])
def test_untrusted_zip_metadata_rejected_before_reader(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    payload = bytearray(zipped("safe"))
    end = payload.rfind(b"PK\x05\x06")
    if kind == "count":
        payload[end + 8 : end + 12] = b"\x00" * 4
    elif kind == "length":
        central = payload.index(b"PK\x01\x02")
        payload[central + 28 : central + 30] = b"\xff\xff"
    elif kind == "zip64":
        payload[end + 8 : end + 12] = b"\xff" * 4
    else:
        payload[end + 4 : end + 6] = b"\x01\x00"
    monkeypatch.setattr(scanner.zipfile, "ZipFile", lambda *a, **k: pytest.fail("reader allocated before preflight"))
    instance = scanner.Scanner()
    instance.scan(bytes(payload), {"path": "untrusted.zip"})
    reason = {"zip64": "unsupported_zip64_metadata_bound", "multidisk": "unsupported_multidisk_zip"}.get(kind, "malformed_or_unreadable_archive")
    assert [gap["reason"] for gap in instance.gaps] == [reason]


def test_zip_nested_directory_budget_is_global() -> None:
    nested = zipped(token())
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("folder/", b"")
        archive.writestr("nested.zip", nested)
    instance = scanner.Scanner(max_entries=2)
    instance.scan(stream.getvalue(), {"path": "outer.zip"})
    assert instance.entries == 2
    assert any(gap["reason"] == "archive_entry_limit" and gap.get("member") == "!nested.zip" for gap in instance.gaps)


def test_zip_exact_limits_and_concatenated_prefix() -> None:
    payload = zipped(token())
    end = payload.rfind(b"PK\x05\x06")
    size = int.from_bytes(payload[end + 12 : end + 16], "little")
    instance = scanner.Scanner(max_entries=1, max_zip_metadata=size)
    instance.scan(b"prefix" + payload, {"path": "prefixed.zip"})
    assert not instance.gaps
    assert instance.entries == 1
    assert any(f.get("member") == "!evidence.txt" for f in instance.findings)


def test_deleted_history_secret_and_ignored_env(repo: Path) -> None:
    (repo / "old.txt").write_text(token(), encoding="utf-8")
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    commit(repo)
    (repo / "old.txt").unlink()
    (repo / ".env").write_text(token(), encoding="utf-8")
    commit(repo)
    assert not scanner.audit(repo, ["HEAD"], False)["findings"]
    report = scanner.audit(repo, ["HEAD"], True)
    assert report["findings"][0]["path"] == "old.txt"
    assert token() not in json.dumps(report)
    assert not any(f["path"] == ".env" for f in report["findings"])


def test_archive_secret_and_split_reassembly(repo: Path) -> None:
    archive = zipped(token())
    (repo / "direct.zip").write_bytes(archive)
    midpoint = len(archive) // 2
    (repo / "split.zip.001.bin").write_bytes(archive[:midpoint])
    (repo / "split.zip.002.bin").write_bytes(archive[midpoint:])
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], False)
    assert any(f.get("member") == "!evidence.txt" and f["path"] == "direct.zip" for f in report["findings"])
    assert any(f["blob"] == "reassembled" for f in report["findings"])
    assert token() not in json.dumps(report)
    assert report["archive_inventory"]


def test_bounded_archive_reports_gap(repo: Path) -> None:
    (repo / "large.zip").write_bytes(zipped("A" * 10000))
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], False, max_bytes=1000)
    assert not report["scope_complete"]
    assert any(g["reason"] == "archive_expansion_limit" for g in report["coverage_gaps"])


def test_scope_does_not_walk_other_repo_or_ignored_content(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    (repo / "safe.txt").write_text("safe", encoding="utf-8")
    commit(repo)
    other = tmp_path_factory.mktemp("unrelated")
    (other / ".env").write_text(token(), encoding="utf-8")
    (repo / "nested-private").mkdir()
    (repo / "nested-private" / ".env").write_text(token(), encoding="utf-8")
    assert not scanner.audit(repo, ["HEAD"], True)["findings"]


def test_safe_json_includes_no_filename_secret(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / (token() + ".txt")).write_text(token(), encoding="utf-8")
    commit(repo)
    assert scanner.main(["--repo", str(repo)]) == 1
    output = capsys.readouterr().out
    assert token() not in output
    assert "[REDACTED]" in output


def test_git_errors_suppress_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert scanner.main(["--repo", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["repositories"][0]["error"] == "audit_failed"


def test_gzip_xz_and_historical_split_gap(repo: Path) -> None:
    import gzip
    import lzma

    (repo / "payload.gz").write_bytes(gzip.compress(token().encode()))
    content = lzma.compress(token().encode())
    (repo / "payload.xz.part000").write_bytes(content[:20])
    (repo / "payload.xz.part001").write_bytes(content[20:])
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], True)
    assert any(f["path"] == "payload.gz" and f.get("member") for f in report["findings"])
    assert any(f["blob"] == "reassembled" for f in report["findings"])
    assert any(g["reason"] == "historical_segment_combinations_not_reassembled" for g in report["coverage_gaps"])


def test_utf16_and_credential_url_without_password(repo: Path) -> None:
    (repo / "encoded.txt").write_bytes(token().encode("utf-16"))
    (repo / "url.txt").write_text("https://" + "livepasswordtoken" + "@example.invalid/repo", encoding="utf-8")
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], False)
    assert any(f["rule"] == "github_token" and f["path"] == "encoded.txt" for f in report["findings"])
    assert any(f["rule"] == "credential_url" and f["path"] == "url.txt" for f in report["findings"])
    assert token() not in json.dumps(report)
    assert "livepasswordtoken" not in json.dumps(report)


def test_invalid_limits_do_not_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert scanner.main(["--repo", str(tmp_path), "--max-bytes", "-1"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "limits_must_be_positive"


def test_same_blob_keeps_archive_path_semantics(repo: Path) -> None:
    for name in ("a.zip", "z.txt"):
        (repo / name).write_bytes(b"malformed archive")
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], False)
    assert not report["scope_complete"]
    assert any(g["path"] == "a.zip" and g["reason"] == "malformed_or_unreadable_archive" for g in report["coverage_gaps"])


def test_deleted_historical_segments_cannot_pass_complete(repo: Path) -> None:
    import lzma

    content = lzma.compress(token().encode())
    (repo / "old.xz.part000").write_bytes(content[:3])
    (repo / "old.xz.part001").write_bytes(content[3:])
    commit(repo)
    for path in repo.glob("old.xz.part*"):
        path.unlink()
    (repo / "safe.txt").write_text("safe", encoding="utf-8")
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], True)
    assert not report["scope_complete"]
    assert any(g["reason"] == "historical_segment_combinations_not_reassembled" for g in report["coverage_gaps"])


def test_dense_matches_are_bounded_and_lines_are_correct() -> None:
    instance = scanner.Scanner(max_findings=7)
    instance.scan((token() + "\n").encode() * 40000, {"path": "dense.txt"})
    assert len(instance.findings) == 7
    assert [f["line"] for f in instance.findings] == list(range(1, 8))
    assert any(g["reason"] == "finding_limit" for g in instance.gaps)


def test_historical_alias_is_not_lost(repo: Path) -> None:
    (repo / "a.zip").write_bytes(b"malformed archive")
    (repo / "z.txt").write_bytes(b"malformed archive")
    commit(repo)
    (repo / "a.zip").unlink()
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], True)
    assert any(g["path"] == "a.zip" and g["reason"] == "malformed_or_unreadable_archive" for g in report["coverage_gaps"])


def test_xz_decoder_memory_is_bounded(repo: Path) -> None:
    import lzma

    payload = lzma.compress(b"A" * 1000, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 32 * 1024 * 1024}])
    (repo / "large-dictionary.xz").write_bytes(payload)
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], False, max_bytes=1024, max_total=2048)
    assert not report["scope_complete"]
    assert any(g["reason"] == "archive_decoder_memory_limit" for g in report["coverage_gaps"])


def test_zip_lzma_is_explicit_gap(repo: Path) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_LZMA) as archive:
        archive.writestr("small.txt", "safe")
    (repo / "lzma.zip").write_bytes(stream.getvalue())
    commit(repo)
    report = scanner.audit(repo, ["HEAD"], False)
    assert not report["scope_complete"]
    assert any(g["reason"] == "unsupported_zip_lzma_memory_bound" for g in report["coverage_gaps"])


@pytest.mark.parametrize("kind", ["gzip", "zip"])
def test_corrupt_deflate_returns_safe_json(repo: Path, capsys: pytest.CaptureFixture[str], kind: str) -> None:
    payload: bytes | bytearray
    if kind == "gzip":
        payload = b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"\x07" + b"\x00" * 8
        name = "corrupt.gz"
    else:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("bad.txt", b"\x07" * 20)
        payload = bytearray(stream.getvalue())
        payload[8:10] = (zipfile.ZIP_DEFLATED).to_bytes(2, "little")
        central = payload.index(b"PK\x01\x02")
        payload[central + 10 : central + 12] = (zipfile.ZIP_DEFLATED).to_bytes(2, "little")
        name = "corrupt.zip"
    (repo / name).write_bytes(payload)
    commit(repo)
    assert scanner.main(["--repo", str(repo)]) == 2
    report = json.loads(capsys.readouterr().out)["repositories"][0]
    assert any(g["reason"] == "malformed_or_unreadable_archive" for g in report["coverage_gaps"])
