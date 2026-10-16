import hashlib
import io
import json
import stat
import struct
import zipfile
from pathlib import Path
from typing import Any

import pytest

from research_core import annual_completion_publication as publication


def encoded(value: Any) -> bytes:
    return json.dumps(value, indent=3).encode("utf-8") + b"\n"


def fixture(tmp_path: Path) -> dict[str, bytes]:
    members = {name: encoded({"run_id": "synthetic-run", "name": name, "value": 1.25}) for name in publication.RESULT_NAMES.values()}
    receipt = {
        "schema": "run-receipt.v1",
        "run_id": "synthetic-run",
        "input_fingerprint": {"inputs": {"never_open": {"path": "Z:/unavailable/huge-input.parquet", "sha256": "0" * 64}}},
        "results": {
            key: {"path": "tasks/synthetic/" + name, "bytes": len(members[name]), "sha256": hashlib.sha256(members[name]).hexdigest()}
            for key, name in publication.RESULT_NAMES.items()
        },
    }
    members["run-receipt.json"] = encoded(receipt)
    for name, raw in members.items():
        (tmp_path / name).write_bytes(raw)
    return members


def archive_bytes(members: dict[str, bytes], *, extra: tuple[zipfile.ZipInfo | str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
        if extra is not None:
            with pytest.warns(UserWarning) if isinstance(extra[0], str) and extra[0] in members else _no_warning():
                archive.writestr(*extra)
    return buffer.getvalue()


class _no_warning:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: Any) -> None:
        return None


def test_pack_preserves_exact_four_raw_members_and_does_not_overwrite(tmp_path: Path):
    members = fixture(tmp_path)
    archive = publication.pack_publication(tmp_path)
    assert archive.stat().st_size <= 500 * 1024
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == set(publication.MEMBERS)
        assert len(zipped.infolist()) == 4
        assert {name: zipped.read(name) for name in zipped.namelist()} == members
    assert publication.load_publication(tmp_path)["results.json"]["value"] == 1.25
    assert all((tmp_path / name).read_bytes() == raw for name, raw in members.items())
    before = archive.read_bytes()
    with pytest.raises(FileExistsError):
        publication.pack_publication(tmp_path)
    assert archive.read_bytes() == before


@pytest.mark.parametrize("packed", [False, True])
def test_load_hashes_only_three_consumed_small_results_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, packed: bool):
    members = fixture(tmp_path)
    if packed:
        publication.pack_publication(tmp_path)
    original = hashlib.sha256
    hashed = []

    def hash_once(raw: bytes = b"") -> Any:
        hashed.append(raw)
        return original(raw)

    monkeypatch.setattr(publication.hashlib, "sha256", hash_once)
    result = publication.load_publication(tmp_path)
    assert set(result) == set(publication.MEMBERS)
    assert len(hashed) == 3
    assert hashed == [members[name] for name in publication.RESULT_NAMES.values()]


def test_existing_zip_is_authoritative_and_never_falls_back_to_plain(tmp_path: Path):
    fixture(tmp_path)
    (tmp_path / publication.ARCHIVE).write_bytes(b"corrupt ZIP")
    with pytest.raises(ValueError, match="invalid publication ZIP"):
        publication.load_publication(tmp_path)


@pytest.mark.parametrize("failure", ["hash", "bytes", "wrong_filename", "missing_identity", "extra_identity", "run_id"])
def test_receipt_identity_failures_are_rejected(tmp_path: Path, failure: str):
    members = fixture(tmp_path)
    receipt = json.loads(members["run-receipt.json"])
    if failure == "hash":
        receipt["results"]["results"]["sha256"] = "0" * 64
    elif failure == "bytes":
        receipt["results"]["results"]["bytes"] += 1
    elif failure == "wrong_filename":
        receipt["results"]["results"]["path"] = "other.json"
    elif failure == "missing_identity":
        receipt["results"].pop("performance")
    elif failure == "extra_identity":
        receipt["results"]["unexpected"] = receipt["results"]["results"]
    else:
        receipt["run_id"] = "different-run"
    (tmp_path / "run-receipt.json").write_bytes(encoded(receipt))
    with pytest.raises(ValueError):
        publication.load_publication(tmp_path)
    with pytest.raises(ValueError):
        publication.pack_publication(tmp_path)


@pytest.mark.parametrize("name", ["unexpected.json", "../results.json", "/results.json", "C:/results.json", "captured\\results.json"])
def test_extra_or_unsafe_zip_members_are_rejected(tmp_path: Path, name: str):
    members = fixture(tmp_path)
    (tmp_path / publication.ARCHIVE).write_bytes(archive_bytes(members, extra=(name, b"{}")))
    with pytest.raises(ValueError):
        publication.load_publication(tmp_path)


def test_duplicate_zip_member_is_rejected(tmp_path: Path):
    members = fixture(tmp_path)
    (tmp_path / publication.ARCHIVE).write_bytes(archive_bytes(members, extra=("results.json", b"{}")))
    with pytest.raises(ValueError, match="duplicate"):
        publication.load_publication(tmp_path)


def test_symlink_zip_member_is_rejected_without_extracting(tmp_path: Path):
    members = fixture(tmp_path)
    info = zipfile.ZipInfo("results.json")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, raw in members.items():
            archive.writestr(info if name == "results.json" else name, raw)
    (tmp_path / publication.ARCHIVE).write_bytes(buffer.getvalue())
    with pytest.raises(ValueError, match="nonregular"):
        publication.load_publication(tmp_path)


def test_encrypted_zip_flag_is_rejected_before_decompression(tmp_path: Path):
    members = fixture(tmp_path)
    raw = bytearray(archive_bytes(members))
    # Set encryption in both local and central headers without requiring an
    # encryption library or constructing any external inputs.
    for marker, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        cursor = 0
        while (cursor := raw.find(marker, cursor)) >= 0:
            current = struct.unpack_from("<H", raw, cursor + offset)[0]
            struct.pack_into("<H", raw, cursor + offset, current | 1)
            cursor += 4
    (tmp_path / publication.ARCHIVE).write_bytes(raw)
    with pytest.raises(ValueError, match="encrypted"):
        publication.load_publication(tmp_path)


def test_plain_and_compressed_size_limits_are_enforced(tmp_path: Path):
    members = fixture(tmp_path)
    (tmp_path / "results.json").write_bytes(b" " * (publication.MAX_MEMBER_BYTES + 1))
    with pytest.raises(ValueError, match="byte limit"):
        publication.pack_publication(tmp_path)
    (tmp_path / publication.ARCHIVE).write_bytes(b" " * (publication.MAX_ARCHIVE_BYTES + 1))
    with pytest.raises(ValueError, match="byte limit"):
        publication.load_publication(tmp_path)
    (tmp_path / publication.ARCHIVE).write_bytes(archive_bytes({**members, "results.json": b" " * (publication.MAX_MEMBER_BYTES + 1)}))
    with pytest.raises(ValueError, match="member exceeds byte limit"):
        publication.load_publication(tmp_path)


@pytest.mark.parametrize("raw", [b'{"run_id":"synthetic-run","run_id":"synthetic-run"}', b'{"run_id":"synthetic-run","value":NaN}', b"[]"])
def test_ambiguous_or_non_object_json_is_rejected(tmp_path: Path, raw: bytes):
    fixture(tmp_path)
    (tmp_path / "results.json").write_bytes(raw)
    with pytest.raises(ValueError):
        publication.load_publication(tmp_path)


def test_cli_packages_synthetic_publication(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    fixture(tmp_path)
    assert publication.main(["--publication", str(tmp_path)]) == 0
    assert str(tmp_path / publication.ARCHIVE) in capsys.readouterr().out
    assert publication.load_publication(tmp_path)["run-receipt.json"]["run_id"] == "synthetic-run"
