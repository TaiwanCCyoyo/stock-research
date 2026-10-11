"""The published-artifact inventory runs each reader and reports failures instead of hiding them."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts import verify_published_artifacts as inventory


def test_tracked_publication_passes_and_missing_local_input_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "rows.json"
    argv = ["--only", "owner-hhhl", "hhhl-v1", "--local-root", str(tmp_path / "no-local-artifacts"), "--json", str(out)]
    assert inventory.main(argv) == 1  # an unverified local-only artifact is not a pass
    rows = {row["check"]: row["status"] for row in json.loads(out.read_text(encoding="utf-8"))}
    assert rows == {"owner-hhhl-labels.v1": "pass", "hhhl-v1 publication": "local-missing"}
    assert inventory.main([*argv, "--allow-local-missing"]) == 0
    assert "local-missing" in capsys.readouterr().out


def test_a_failing_reader_fails_the_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def broken(_root: Path, _local: Path) -> tuple[str, str]:
        raise ValueError("synthetic reader failure")

    monkeypatch.setattr(inventory, "CHECKS", [inventory.Check("synthetic", broken)])
    assert inventory.main(["--local-root", str(tmp_path)]) == 1


def _v1_publication(tmp_path: Path, edit: object = None) -> tuple[Path, Path]:
    base = "tasks/20261009-hhhl-pattern-probability/publication-v1"
    members = {"outputs/a.json": b"{}", "outputs/b.json": b"[1]"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, body in members.items():
            z.writestr(name, body)
    bundle = buffer.getvalue()
    manifest = {
        "bundle": {
            "path": "bundle.zip",
            "sha256": hashlib.sha256(bundle).hexdigest(),
            "bytes": len(bundle),
            "members": {n: hashlib.sha256(b).hexdigest() for n, b in members.items()},
        }
    }
    if callable(edit):
        edit(manifest["bundle"]["members"])
    root, local = tmp_path / "checkout", tmp_path / "local"
    (root / base).mkdir(parents=True)
    (local / base).mkdir(parents=True)
    (root / base / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (local / base / "bundle.zip").write_bytes(bundle)
    return root, local


def _swap(members: dict[str, str]) -> None:
    members["outputs/a.json"], members["outputs/b.json"] = members["outputs/b.json"], members["outputs/a.json"]


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (None, "pass"),
        (lambda m: m.update({"outputs/a.json": None}), "fail"),
        (lambda m: m.pop("outputs/b.json"), "fail"),
        (_swap, "fail"),
    ],
    ids=["exact", "null-digest", "missing-member", "swapped-digests"],
)
def test_v1_bundle_members_must_match_their_declared_digests_exactly(tmp_path: Path, edit: object, expected: str) -> None:
    root, local = _v1_publication(tmp_path, edit)
    status, _detail = inventory.hhhl_v1_publication(root, local)
    assert status == expected
