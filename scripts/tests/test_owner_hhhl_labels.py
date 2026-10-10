"""The owner-hhhl-labels.v1 archive keeps reproducing the published batch 2-5 numbers and refuses tampering."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from research_core import owner_hhhl_labels as labels
from scripts import build_owner_hhhl_labels, capture_owner_hhhl_rule_hits, verify_owner_hhhl_labels


def test_verifier_reproduces_every_published_number(capsys: pytest.CaptureFixture[str]) -> None:
    assert verify_owner_hhhl_labels.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith("all published numbers reproduced")
    assert out.count(" ok\n") == sum(len(rows) for rows in verify_owner_hhhl_labels.EXPECTED.values())


def test_order_requires_every_chart_set_before_the_first_save() -> None:
    prereg, first = "2026-10-08T03:00:00.000+00:00", "2026-10-08T03:30:00.000Z"
    assert labels.order_holds(prereg, ["2026-10-08T03:10:00.000+00:00", "2026-10-08T03:20:00.000+00:00"], first)
    assert not labels.order_holds(prereg, ["2026-10-08T03:10:00.000+00:00", "2026-10-08T03:40:00.000+00:00"], first)
    assert not labels.order_holds(prereg, ["2026-10-08T02:50:00.000+00:00", "2026-10-08T03:10:00.000+00:00"], first)
    assert not labels.order_holds(prereg, [], first)


def _rewrite_zip(path: Path, edit: Callable[[dict[str, bytes]], None]) -> None:
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    edit(members)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def _edit_json(path: Path, edit: Callable[[dict], None]) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    edit(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _corrupt_bar(members: dict[str, bytes]) -> None:  # member changed, manifest left alone
    items = json.loads(members["sets/set_b5b.json"])
    items[0]["bars"][0][4] += 1.0
    members["sets/set_b5b.json"] = json.dumps(items).encode("utf-8")


def _rewrite_history_consistently(members: dict[str, bytes]) -> None:  # member and manifest both updated
    name = "earlier_dumps/labels_b2_dump/labels/b2-14-3015-2025-09-11.json"
    doc = json.loads(members[name])
    doc["verdict"] = "CORRUPTED"
    members[name] = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    manifest = json.loads(members["manifest.json"])
    manifest[name] = hashlib.sha256(members[name]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode("utf-8")


def _receipt(edit: Callable[[dict], None], member: str) -> Callable[[dict[str, bytes]], None]:
    def apply(members: dict[str, bytes]) -> None:
        doc = json.loads(members[member])
        edit(doc)
        members[member] = json.dumps(doc).encode("utf-8")

    return apply


def _add_rule_event(doc: dict) -> None:
    chart = next(iter(doc["batches"]["b3a"].values()))
    chart["events"]["v1"].append(chart["sessions"][0])


TAMPERING: dict[str, tuple[Callable[[Path], object], str]] = {
    "zip member": (lambda d: _rewrite_zip(d / "data/chart_sets.zip", _corrupt_bar), "members ['sets/set_b5b.json'] do not match their manifest SHA-256"),
    "consistent zip rewrite": (lambda d: _rewrite_zip(d / "data/history.zip", _rewrite_history_consistently), "history.zip differs from its pinned digest"),
    "owner document": (
        lambda d: _edit_json(d / "data/owner_labels.json", lambda doc: doc["pages"]["r1"]["documents"][0].update(note="edited")),
        "differs from the labels_dump2 dump beyond the documented change",
    ),
    "rule hits": (lambda d: _edit_json(d / "data/rule_hits.json", _add_rule_event), "does not match the hits digest"),
    "receipt coverage": (
        lambda d: _rewrite_zip(d / "data/rule_hits_inputs.zip", _receipt(lambda r: r.update(atlas_tables={}), "inputs.json")),
        "does not pin every atlas table",
    ),
    "receipt factor rows": (
        lambda d: _rewrite_zip(
            d / "data/rule_hits_inputs.zip", _receipt(lambda r: r.update(factor_rows_applied={c: [] for c in r["factor_rows_applied"]}), "inputs.json")
        ),
        "['rule_hits_inputs.zip'] differ from their pinned digests",
    ),
    "timeline batch": (lambda d: _rewrite_zip(d / "data/timeline_receipt.zip", _receipt(lambda r: r["batches"].pop("5"), "receipt.json")), "covers batches"),
    "preregistration": (
        lambda d: (d / "batch5-preregistration.md").write_bytes(b"edited after the fact"),
        "batch 5: timeline receipt is not about the committed preregistration",
    ),
    "published result": (lambda d: (d / "batch3-result.md").write_bytes(b"edited"), "['batch3-result.md'] differ from their pinned digests"),
}


@pytest.mark.parametrize("case", sorted(TAMPERING))
def test_archive_refuses_tampered_evidence(tmp_path: Path, case: str) -> None:
    copy = tmp_path / "task"
    shutil.copytree(labels.TASK_DIR, copy, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    edit, message = TAMPERING[case]
    edit(copy)
    with pytest.raises(labels.ArchiveError) as error:
        labels.load(copy)
    assert message in str(error.value)


def _rebuild_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Recreate the builder's inputs from the committed archive itself."""
    source, export = tmp_path / "source", tmp_path / "export"
    pages = json.loads((labels.TASK_DIR / "data/owner_labels.json").read_text(encoding="utf-8"))["pages"]
    for pid, (_url, coll, sub, _dump, _cset) in labels.PAGES.items():
        folder = export / sub / coll
        folder.mkdir(parents=True)
        for doc in pages[pid]["documents"]:
            (folder / f"{doc['id']}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    for archive in ("chart_sets.zip", "history.zip", "rule_sources.zip"):
        with zipfile.ZipFile(labels.TASK_DIR / "data" / archive) as z:
            for name in z.namelist():
                prefix = next((x for x in ("sets/", "pages/", "earlier_dumps/", "rules/") if name.startswith(x)), None)
                if prefix:
                    target = source / name.removeprefix(prefix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(z.read(name))
    return source, export


def test_builder_reproduces_the_committed_archive_into_a_new_directory_only(tmp_path: Path) -> None:
    source, export = _rebuild_inputs(tmp_path)
    out = tmp_path / "rebuilt"
    build_owner_hhhl_labels.main(["--export", str(export), "--source", str(source), "--out", str(out)])
    for archive in ("chart_sets.zip", "history.zip", "rule_sources.zip"):
        with zipfile.ZipFile(labels.TASK_DIR / "data" / archive) as a, zipfile.ZipFile(out / archive) as b:
            assert json.loads(a.read("manifest.json")) == json.loads(b.read("manifest.json")), archive
    assert labels.contract_digest(json.loads((out / "owner_labels.json").read_text(encoding="utf-8"))) == labels.PINNED["owner_labels.json"]

    with pytest.raises(SystemExit, match="already exists"):
        build_owner_hhhl_labels.main(["--export", str(export), "--source", str(source), "--out", str(out)])
    shutil.rmtree(source / "reviews_dump")
    with pytest.raises(SystemExit, match="reviews_dump: 0 files"):
        build_owner_hhhl_labels.main(["--export", str(export), "--source", str(source), "--out", str(tmp_path / "bad")])
    assert not (tmp_path / "bad").exists()


def test_capture_refuses_rule_sources_that_differ_from_the_archive(tmp_path: Path) -> None:
    with zipfile.ZipFile(labels.TASK_DIR / "data/rule_sources.zip") as z:
        for name in z.namelist():
            if name.startswith("rules/"):
                (tmp_path / name.removeprefix("rules/")).write_bytes(z.read(name))
    (tmp_path / "bigrange.py").write_text("# edited\n", encoding="utf-8")
    argv = ["--source", str(tmp_path), "--tables", str(tmp_path / "no-tables"), "--actions", str(tmp_path / "none.sqlite"), "--out", str(tmp_path / "out")]
    with pytest.raises(SystemExit, match="bigrange.py differs from data/rule_sources.zip"):
        capture_owner_hhhl_rule_hits.main(argv)
    assert not (tmp_path / "out").exists()
