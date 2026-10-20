"""The published-artifact inventory runs each reader and reports failures instead of hiding them."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.artifact_store import canonical, publish_new_directory
from research_core.hhhl_variants_query import REQUIRED_COLUMNS, summary_transport
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


def test_variants_portable_publication_passes_and_tampered_chunk_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "fake checkout"
    publication = root / "tasks/20261012-hhhl-v4-variants/publication-v1"
    row: dict[str, Any] = dict.fromkeys(REQUIRED_COLUMNS)
    row.update(
        row_kind="baseline",
        cohort_id="P-clean",
        split_id="development",
        horizon=126,
        calendar_full_n=0,
        hit_n=0,
        loss_n=0,
        flat_win_n=0,
        unknown_n=0,
        censored_n=0,
        known_security_n=0,
        flag_unknown_n=0,
    )
    data = pd.DataFrame([row]).to_parquet(index=False)
    assert isinstance(data, bytes)
    files, descriptor = summary_transport(data, rows=1)
    receipt = {
        "schema_version": "hhhl-variants-publication.v1",
        "dataset_id": "invented-variants",
        "summary": descriptor,
        "local_dataset": {"path": "D:/absent-local-dataset", "manifest_sha256": "0" * 64},
        "execution": {},
    }
    publish_new_directory(publication, {**files, "receipt.json": canonical(receipt)})
    argv = ["--root", str(root), "--local-root", str(tmp_path / "absent local inputs"), "--only", "hhhl-variants"]
    assert inventory.main(argv) == 0
    output = capsys.readouterr().out
    assert "pass" in output and "hhhl-variants-publication.v1" in output
    assert "dataset=invented-variants rows=1" in output
    chunk = publication / descriptor["chunks"][0]["path"]
    original = bytearray(chunk.read_bytes())
    original[0] ^= 1
    chunk.write_bytes(original)
    assert inventory.main(argv) == 1
    output = capsys.readouterr().out
    assert "fail" in output and "hash/size mismatch" in output


@pytest.mark.parametrize("failure", [None, "tampered-result", "wrong-version", "projection-results", "projection-performance"])
def test_annual_completion_inventory_uses_its_reader_without_live_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str | None) -> None:
    root = tmp_path / "synthetic checkout"
    relative = "tasks/20261013-annual-winner-rotation/publications/completion-v2"
    publication = root / relative
    publication.mkdir(parents=True)
    names = {"results": "results.json", "admission": "admission-audit.json", "performance": "performance.json"}
    schemas = {"results": "annual-completion-result.v2", "admission": "annual-completion-admission.v2", "performance": "annual-completion-performance.v2"}
    members = {name: canonical({"schema": schemas[key], "run_id": "synthetic-inventory", "unresolved": []}) for key, name in names.items()}
    identities: dict[str, dict[str, str | int]] = {
        key: {"path": relative + "/" + name, "bytes": len(members[name]), "sha256": hashlib.sha256(members[name]).hexdigest()} for key, name in names.items()
    }
    receipt = {
        "schema": "run-receipt.v1",
        "run_id": "synthetic-inventory",
        "input_fingerprint": {"inputs": {"never_open": {"path": "Z:/unavailable/input.parquet"}}},
        "results": identities,
    }
    if failure == "wrong-version":
        identities["results"]["path"] = relative.replace("completion-v2", "completion-v3") + "/results.json"
    elif failure == "tampered-result":
        members["results.json"] += b" "
    members["run-receipt.json"] = canonical(receipt)
    with zipfile.ZipFile(publication / "publication.zip", "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    if failure is not None and failure.startswith("projection-"):
        name = "results.json" if failure == "projection-results" else "performance.json"
        (publication / name).write_bytes(b'{"changed":"reading copy"}')
    status = inventory.main(["--root", str(root), "--only", "annual-holding-completion"])
    assert status == (0 if failure is None else 1)
    output = capsys.readouterr().out
    assert "annual-holding-completion.v2" in output
    assert ("pass" if failure is None else "fail") in output
    assert "synthetic-inventory" in output if failure is None else "mismatch" in output
