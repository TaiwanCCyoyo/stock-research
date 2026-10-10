"""The archived labels must keep reproducing every published batch 2-5 acceptance number."""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]


def test_archive_reproduces_published_batch_results() -> None:
    run = subprocess.run([sys.executable, "-X", "utf8", str(TASK / "recompute.py"), "--check"], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all published numbers reproduced" in run.stdout


def test_capture_refuses_sources_that_differ_from_the_archive(tmp_path: Path) -> None:
    import zipfile

    with zipfile.ZipFile(TASK / "data" / "rule_sources.zip") as z:
        for name in z.namelist():
            if name.startswith("rules/"):
                (tmp_path / name.removeprefix("rules/")).write_bytes(z.read(name))
    (tmp_path / "bigrange.py").write_text("# edited\n", encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(TASK / "capture_rule_hits.py"),
            "--source",
            str(tmp_path),
            "--tables",
            str(tmp_path / "no-tables"),
            "--actions",
            str(tmp_path / "no-actions.sqlite"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode != 0
    assert "bigrange.py differs from data/rule_sources.zip" in run.stderr


def test_builder_refuses_an_incomplete_export_before_writing(tmp_path: Path) -> None:
    import zipfile

    source, export, out = tmp_path / "source", tmp_path / "export", tmp_path / "out"
    source.mkdir()
    with zipfile.ZipFile(TASK / "data" / "chart_sets.zip") as z:
        for name in z.namelist():
            if name.startswith("sets/"):
                (source / name.removeprefix("sets/")).write_bytes(z.read(name))
    (export / "labels_r1" / "labels").mkdir(parents=True)  # every other page is missing
    run = subprocess.run(
        [sys.executable, "-X", "utf8", str(TASK / "build_label_archive.py"), "--export", str(export), "--source", str(source), "--out", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode != 0
    assert "r1: 0 documents / 0 distinct ids (expected 30)" in run.stderr
    assert not out.exists() or not any(out.iterdir())


def _rebuild_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Recreate the builder's inputs from the committed archive itself."""
    import json
    import zipfile

    sys.path.insert(0, str(TASK))
    from build_label_archive import PAGES

    source, export = tmp_path / "source", tmp_path / "export"
    labels = json.loads((TASK / "data" / "owner_labels.json").read_text(encoding="utf-8"))["pages"]
    for pid, (_url, coll, sub, _dump, _cset) in PAGES.items():
        folder = export / sub / coll
        folder.mkdir(parents=True)
        for doc in labels[pid]["documents"]:
            (folder / f"{doc['id']}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    for archive in ("chart_sets.zip", "history.zip", "rule_sources.zip"):
        with zipfile.ZipFile(TASK / "data" / archive) as z:
            for name in z.namelist():
                prefix = next((x for x in ("sets/", "pages/", "earlier_dumps/", "rules/") if name.startswith(x)), None)
                if prefix:
                    target = source / name.removeprefix(prefix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(z.read(name))
    return source, export


def _build(source: Path, export: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(TASK / "build_label_archive.py"), "--export", str(export), "--source", str(source), "--out", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_builder_reproduces_the_committed_archive_and_refuses_a_missing_dump(tmp_path: Path) -> None:
    import json
    import shutil
    import zipfile

    source, export = _rebuild_inputs(tmp_path)
    good = _build(source, export, tmp_path / "good")
    assert good.returncode == 0, good.stderr
    for archive in ("chart_sets.zip", "history.zip", "rule_sources.zip"):
        with zipfile.ZipFile(TASK / "data" / archive) as a, zipfile.ZipFile(tmp_path / "good" / archive) as b:
            assert json.loads(a.read("manifest.json")) == json.loads(b.read("manifest.json")), archive

    shutil.rmtree(source / "reviews_dump")
    bad = _build(source, export, tmp_path / "bad")
    assert bad.returncode != 0
    assert "reviews_dump: 0 files" in bad.stderr
    assert not (tmp_path / "bad").exists() or not any((tmp_path / "bad").iterdir())


def test_builder_refuses_duplicate_ids_in_the_export(tmp_path: Path) -> None:
    source, export = _rebuild_inputs(tmp_path)
    folder = export / "labels_b2" / "labels"
    files = sorted(folder.glob("*.json"))
    files[1].write_bytes(files[0].read_bytes())  # 30 files, 29 distinct ids
    run = _build(source, export, tmp_path / "out")
    assert run.returncode != 0
    assert "b2: 30 documents / 29 distinct ids" in run.stderr
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_order_requires_every_chart_set_before_the_first_save() -> None:
    sys.path.insert(0, str(TASK))
    from record_timeline import order_holds

    prereg, first = "2026-10-08T03:00:00.000+00:00", "2026-10-08T03:30:00.000Z"
    assert order_holds(prereg, ["2026-10-08T03:10:00.000+00:00", "2026-10-08T03:20:00.000+00:00"], first)
    # second chart set written after the owner started: must fail even though the first one is fine
    assert not order_holds(prereg, ["2026-10-08T03:10:00.000+00:00", "2026-10-08T03:40:00.000+00:00"], first)
    # a chart set written before the preregistration must fail too
    assert not order_holds(prereg, ["2026-10-08T02:50:00.000+00:00", "2026-10-08T03:10:00.000+00:00"], first)
    assert not order_holds(prereg, [], first)


def test_builder_refuses_a_dump_whose_content_drifted_from_the_export(tmp_path: Path) -> None:
    import json

    source, export = _rebuild_inputs(tmp_path)
    target = sorted((source / "b3b_dump").rglob("*.json"))[0]
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["verdict"] = "CORRUPTED"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    run = _build(source, export, tmp_path / "out")
    assert run.returncode != 0
    assert "fields ['verdict'] differ from the fresh export" in run.stderr
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_recompute_rejects_a_timeline_receipt_for_a_different_preregistration(tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    prereg = copy / "batch5-preregistration.md"
    prereg.write_bytes(prereg.read_bytes() + b"edited after the fact")
    run = subprocess.run([sys.executable, "-X", "utf8", str(copy / "recompute.py"), "--check"], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode != 0
    assert "batch 5: timeline receipt is not about the committed preregistration" in run.stderr


def test_builder_pins_the_historical_values_of_documented_differences(tmp_path: Path) -> None:
    import json

    source, export = _rebuild_inputs(tmp_path)
    target = next((source / "labels_b2_dump").rglob("b2-14-3015-2025-09-11.json"))
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["verdict"] = "CORRUPTED"  # still only the documented fields differ, but the old value is wrong
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    run = _build(source, export, tmp_path / "out")
    assert run.returncode != 0
    assert "historical values differ from the pinned digest" in run.stderr


def test_recompute_requires_a_complete_timeline_receipt(tmp_path: Path) -> None:
    import json
    import shutil
    import zipfile

    for drop_batch in (True, False):
        copy = tmp_path / f"task-{drop_batch}"
        shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        path = copy / "data" / "timeline_receipt.zip"
        with zipfile.ZipFile(path) as z:
            receipt = json.loads(z.read("receipt.json"))
        if drop_batch:
            del receipt["batches"]["5"]
        else:
            receipt["batches"]["5"]["chart_sets"] = [x for x in receipt["batches"]["5"]["chart_sets"] if x["file"] != "set_b5b.json"]
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("receipt.json", json.dumps(receipt))
        run = subprocess.run([sys.executable, "-X", "utf8", str(copy / "recompute.py"), "--check"], capture_output=True, text=True, encoding="utf-8")
        assert run.returncode != 0
        assert ("covers batches" if drop_batch else "lists chart sets") in run.stderr


def _check_copy(tmp_path: Path, name: str, edit: Callable[[Path], None]) -> subprocess.CompletedProcess:
    import shutil

    copy = tmp_path / name
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    edit(copy)
    return subprocess.run([sys.executable, "-X", "utf8", str(copy / "recompute.py"), "--check"], capture_output=True, text=True, encoding="utf-8")


def test_recompute_rejects_hits_that_do_not_match_the_input_receipt(tmp_path: Path) -> None:
    import json

    def add_event(copy: Path) -> None:
        path = copy / "data" / "rule_hits.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        chart = next(iter(doc["batches"]["b3a"].values()))
        chart["events"]["v1"].append(chart["sessions"][0])
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    run = _check_copy(tmp_path, "hits", add_event)
    assert run.returncode != 0
    assert "does not match the hits digest" in run.stderr


def test_recompute_rehashes_zip_members_instead_of_trusting_the_manifest(tmp_path: Path) -> None:
    import json
    import zipfile

    def corrupt_bar(copy: Path) -> None:
        path = copy / "data" / "chart_sets.zip"
        with zipfile.ZipFile(path) as z:
            members = {n: z.read(n) for n in z.namelist()}
        items = json.loads(members["sets/set_b5b.json"])
        items[0]["bars"][0][4] += 1.0
        members["sets/set_b5b.json"] = json.dumps(items).encode("utf-8")
        with zipfile.ZipFile(path, "w") as z:
            for n, data in members.items():
                z.writestr(n, data)

    run = _check_copy(tmp_path, "zip", corrupt_bar)
    assert run.returncode != 0
    assert "chart_sets.zip: members ['sets/set_b5b.json'] do not match their manifest SHA-256" in run.stderr


def test_recompute_rejects_an_edited_owner_document(tmp_path: Path) -> None:
    import json

    def edit_note(copy: Path) -> None:
        path = copy / "data" / "owner_labels.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["pages"]["r1"]["documents"][0]["note"] = "edited"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    run = _check_copy(tmp_path, "labels", edit_note)
    assert run.returncode != 0
    assert "differs from the labels_dump2 dump beyond the documented change" in run.stderr


def test_recompute_requires_full_input_receipt_coverage(tmp_path: Path) -> None:
    import json
    import zipfile

    def empty_coverage(copy: Path) -> None:
        path = copy / "data" / "rule_hits_inputs.zip"
        with zipfile.ZipFile(path) as z:
            receipt = json.loads(z.read("inputs.json"))
        receipt["atlas_tables"], receipt["factor_rows_applied"] = {}, {}
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("inputs.json", json.dumps(receipt))

    run = _check_copy(tmp_path, "receipt", empty_coverage)
    assert run.returncode != 0
    assert "does not pin every atlas table" in run.stderr


def test_recompute_rejects_consistent_rewrites_of_archived_evidence(tmp_path: Path) -> None:
    import hashlib
    import json
    import zipfile

    def rewrite_history(copy: Path) -> None:  # change the b2-14 dump and update the manifest to match
        path = copy / "data" / "history.zip"
        with zipfile.ZipFile(path) as z:
            members = {n: z.read(n) for n in z.namelist()}
        name = "earlier_dumps/labels_b2_dump/labels/b2-14-3015-2025-09-11.json"
        doc = json.loads(members[name])
        doc["verdict"] = "CORRUPTED"
        members[name] = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        manifest = json.loads(members["manifest.json"])
        manifest[name] = hashlib.sha256(members[name]).hexdigest()
        members["manifest.json"] = json.dumps(manifest).encode("utf-8")
        with zipfile.ZipFile(path, "w") as z:
            for n, data in members.items():
                z.writestr(n, data)

    run = _check_copy(tmp_path, "history", rewrite_history)
    assert run.returncode != 0
    assert "historical values differ from the pinned digest" in run.stderr

    def empty_factor_rows(copy: Path) -> None:  # keep every code, drop every row
        path = copy / "data" / "rule_hits_inputs.zip"
        with zipfile.ZipFile(path) as z:
            receipt = json.loads(z.read("inputs.json"))
        receipt["factor_rows_applied"] = {c: [] for c in receipt["factor_rows_applied"]}
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("inputs.json", json.dumps(receipt))

    run = _check_copy(tmp_path, "factors", empty_factor_rows)
    assert run.returncode != 0
    assert "['rule_hits_inputs.zip'] differ from their pinned digests" in run.stderr


def test_swap_in_restores_both_previous_outputs_when_a_replace_fails(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    import os

    sys.path.insert(0, str(TASK))
    import archive_io

    a, b = tmp_path / "rule_hits.json", tmp_path / "rule_hits_inputs.zip"
    a.write_bytes(b"old hits")
    b.write_bytes(b"old receipt")
    real = os.replace

    def flaky(src, dst):  # noqa: ANN001, ANN202
        if str(src).endswith("rule_hits_inputs.zip.partial"):
            raise PermissionError("locked")
        return real(src, dst)

    monkeypatch.setattr(archive_io.os, "replace", flaky)
    try:
        archive_io.swap_in({a: b"new hits", b: b"new receipt"})
    except PermissionError:
        pass
    else:
        raise AssertionError("swap_in should have raised")
    assert a.read_bytes() == b"old hits"
    assert b.read_bytes() == b"old receipt"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rule_hits.json", "rule_hits_inputs.zip"]


def test_recompute_rejects_an_edited_published_result(tmp_path: Path) -> None:
    def edit_result(copy: Path) -> None:
        path = copy / "batch5-result.md"
        path.write_bytes(path.read_bytes().replace(b"|  15 |    7 |", b"|  14 |    8 |", 1))

    run = _check_copy(tmp_path, "result", edit_result)
    assert run.returncode != 0
    assert "['batch5-result.md'] differ from their pinned digests" in run.stderr


def test_builder_treats_a_missing_field_and_a_null_field_as_different(tmp_path: Path) -> None:
    import json

    source, export = _rebuild_inputs(tmp_path)
    target = sorted((source / "b3b_dump").rglob("*.json"))[0]
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["extra_null"] = None
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    run = _build(source, export, tmp_path / "out")
    assert run.returncode != 0
    assert "fields ['extra_null'] differ from the fresh export" in run.stderr


def test_recompute_rejects_edited_archive_metadata(tmp_path: Path) -> None:
    import json

    def edit_export_date(copy: Path) -> None:
        path = copy / "data" / "owner_labels.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["exported_on"] = "2026-01-01"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    run = _check_copy(tmp_path, "metadata", edit_export_date)
    assert run.returncode != 0
    assert "['owner_labels.json'] differ from their pinned digests" in run.stderr


def test_recompute_rejects_edited_rule_hits_provenance(tmp_path: Path) -> None:
    import json

    def edit_provenance(copy: Path) -> None:
        path = copy / "data" / "rule_hits.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["atlas_tables"] = "somewhere/else"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    run = _check_copy(tmp_path, "provenance", edit_provenance)
    assert run.returncode != 0
    assert "['rule_hits.json'] differ from their pinned digests" in run.stderr


def test_swap_in_keeps_current_files_when_moving_one_aside_fails(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    import os

    sys.path.insert(0, str(TASK))
    import archive_io

    a, b = tmp_path / "rule_hits.json", tmp_path / "rule_hits_inputs.zip"
    a.write_bytes(b"current-a")
    b.write_bytes(b"current-b")
    real = os.replace

    def flaky(src, dst):  # noqa: ANN001, ANN202
        if str(dst).endswith("rule_hits_inputs.zip.previous"):
            raise PermissionError("locked")
        return real(src, dst)

    monkeypatch.setattr(archive_io.os, "replace", flaky)
    try:
        archive_io.swap_in({a: b"new-a", b: b"new-b"})
    except PermissionError:
        pass
    else:
        raise AssertionError("swap_in should have raised")
    assert (a.read_bytes(), b.read_bytes()) == (b"current-a", b"current-b")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rule_hits.json", "rule_hits_inputs.zip"]


def test_swap_in_refuses_leftovers_from_an_interrupted_run(tmp_path: Path) -> None:
    sys.path.insert(0, str(TASK))
    import archive_io

    a, b = tmp_path / "rule_hits.json", tmp_path / "rule_hits_inputs.zip"
    a.write_bytes(b"current-a")
    b.write_bytes(b"current-b")
    (tmp_path / "rule_hits_inputs.zip.previous").write_bytes(b"stale-b")
    try:
        archive_io.swap_in({a: b"new-a", b: b"new-b"})
    except SystemExit as exc:
        assert "leftover files from an interrupted run" in str(exc)
    else:
        raise AssertionError("swap_in should have refused")
    assert (a.read_bytes(), b.read_bytes()) == (b"current-a", b"current-b")


def test_timeline_stamp_refuses_a_file_replaced_while_it_was_read(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    import os

    sys.path.insert(0, str(TASK))
    import record_timeline

    target = tmp_path / "set_b5b.json"
    target.write_bytes(b"old content")
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))

    def read_then_replace(path: Path) -> bytes:
        data = path.read_bytes()
        path.write_bytes(b"newer, longer content")  # refreshed between the read and the metadata
        return data

    monkeypatch.setattr(record_timeline, "_read", read_then_replace)
    try:
        record_timeline.stamp(target)
    except SystemExit as exc:
        assert "changed while it was being recorded" in str(exc)
    else:
        raise AssertionError("stamp should have refused")
    monkeypatch.undo()
    row, data = record_timeline.stamp(target)  # a quiet file is recorded normally
    assert row["bytes"] == len(data) == len(b"newer, longer content")


def test_capture_refuses_a_tampered_chart_set_before_running(tmp_path: Path) -> None:
    import json
    import shutil
    import zipfile

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    rules = tmp_path / "rules"
    rules.mkdir()
    with zipfile.ZipFile(copy / "data" / "rule_sources.zip") as z:
        for name in z.namelist():
            if name.startswith("rules/"):
                (rules / name.removeprefix("rules/")).write_bytes(z.read(name))
    path = copy / "data" / "chart_sets.zip"
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    items = json.loads(members["sets/label_set_b5a.json"])
    items[0]["date"] = "2099-01-01"
    members["sets/label_set_b5a.json"] = json.dumps(items).encode("utf-8")  # manifest left stale
    with zipfile.ZipFile(path, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    before = (copy / "data" / "rule_hits.json").read_bytes()
    run = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(copy / "capture_rule_hits.py"),
            "--source",
            str(rules),
            "--tables",
            str(tmp_path / "no-tables"),
            "--actions",
            str(tmp_path / "no-actions.sqlite"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode != 0
    assert "chart_sets.zip: members ['sets/label_set_b5a.json'] do not match their manifest SHA-256" in run.stderr
    assert (copy / "data" / "rule_hits.json").read_bytes() == before


def test_timeline_refuses_to_write_an_invalid_receipt(tmp_path: Path) -> None:
    import shutil
    import zipfile

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    source = tmp_path / "source"
    source.mkdir()
    for n in range(2, 6):
        (source / f"batch{n}-preregistration.md").write_bytes((copy / f"batch{n}-preregistration.md").read_bytes())
    with zipfile.ZipFile(copy / "data" / "chart_sets.zip") as z:
        for name in z.namelist():
            if name.startswith("sets/"):
                (source / name.removeprefix("sets/")).write_bytes(z.read(name))
    (source / "batch5-preregistration.md").write_bytes(b"a different preregistration")
    before = (copy / "data" / "timeline_receipt.zip").read_bytes()
    run = subprocess.run(
        [sys.executable, "-X", "utf8", str(copy / "record_timeline.py"), "--source", str(source)], capture_output=True, text=True, encoding="utf-8"
    )
    assert run.returncode != 0
    assert "batch 5: preregistration differs from the committed copy" in run.stderr
    assert (copy / "data" / "timeline_receipt.zip").read_bytes() == before


def test_capture_refuses_a_consistently_rebuilt_rule_archive(tmp_path: Path) -> None:
    import hashlib
    import json
    import shutil
    import zipfile

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    path = copy / "data" / "rule_sources.zip"
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members["rules/bigrange.py"] += b"# rebuilt"
    manifest = json.loads(members["manifest.json"])
    manifest["rules/bigrange.py"] = hashlib.sha256(members["rules/bigrange.py"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(path, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    rules = tmp_path / "rules"  # --source points at the same, rebuilt bytes
    rules.mkdir()
    for n, data in members.items():
        if n.startswith("rules/"):
            (rules / n.removeprefix("rules/")).write_bytes(data)
    before = (copy / "data" / "rule_hits.json").read_bytes()
    run = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(copy / "capture_rule_hits.py"),
            "--source",
            str(rules),
            "--tables",
            str(tmp_path / "no-tables"),
            "--actions",
            str(tmp_path / "no-actions.sqlite"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode != 0
    assert "rule_sources.zip differs from its pinned digest" in run.stderr
    assert (copy / "data" / "rule_hits.json").read_bytes() == before


def test_builder_refuses_a_chart_set_with_a_repeated_id(tmp_path: Path) -> None:
    import json

    source, export = _rebuild_inputs(tmp_path)
    path = source / "set_b3b.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    items.append(items[0])
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    run = _build(source, export, tmp_path / "out")
    assert run.returncode != 0
    assert "set_b3b: 33 items but 32 distinct ids" in run.stderr


def test_timeline_refuses_a_consistently_rebuilt_chart_set_archive(tmp_path: Path) -> None:
    import hashlib
    import json
    import shutil
    import zipfile

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    path = copy / "data" / "chart_sets.zip"
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    name = "sets/label_set_b5a.json"
    items = json.loads(members[name])
    items[0]["date"] = "2099-01-01"
    members[name] = json.dumps(items).encode("utf-8")
    manifest = json.loads(members["manifest.json"])
    manifest[name] = hashlib.sha256(members[name]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(path, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    source = tmp_path / "source"
    source.mkdir()
    for batch in range(2, 6):
        (source / f"batch{batch}-preregistration.md").write_bytes((copy / f"batch{batch}-preregistration.md").read_bytes())
    for n, data in members.items():
        if n.startswith("sets/"):
            (source / n.removeprefix("sets/")).write_bytes(data)
    before = (copy / "data" / "timeline_receipt.zip").read_bytes()
    run = subprocess.run(
        [sys.executable, "-X", "utf8", str(copy / "record_timeline.py"), "--source", str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode != 0
    assert "chart_sets.zip differs from its pinned digest" in run.stderr
    assert (copy / "data" / "timeline_receipt.zip").read_bytes() == before


def test_recompute_uses_the_snapshot_it_verified_even_if_the_file_is_replaced(tmp_path: Path) -> None:
    import importlib.util
    import json
    import shutil
    import zipfile

    copy = tmp_path / "task"
    shutil.copytree(TASK, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    sys.path.insert(0, str(copy))
    spec = importlib.util.spec_from_file_location("recompute_copy", copy / "recompute.py")
    assert spec is not None and spec.loader is not None
    recompute = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recompute)
    recompute.verified_zip("chart_sets.zip")  # verified: this is the snapshot every later step must use
    path = copy / "data" / "chart_sets.zip"
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    original = json.loads(members["sets/set_b5b.json"])
    tampered = json.loads(members["sets/set_b5b.json"])
    tampered[0]["kind"] = "control" if tampered[0]["kind"] == "rule" else "rule"
    members["sets/set_b5b.json"] = json.dumps(tampered).encode("utf-8")  # manifest left as pinned
    with zipfile.ZipFile(path, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    _docs, sets, _hits = recompute.load()
    assert sets["b5b"] == original


def test_swap_in_cleans_up_staged_files_when_a_later_write_fails(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    sys.path.insert(0, str(TASK))
    import archive_io

    a, b = tmp_path / "rule_hits.json", tmp_path / "rule_hits_inputs.zip"
    a.write_bytes(b"current-a")
    b.write_bytes(b"current-b")
    real = Path.write_bytes

    def full_disk(self: Path, data: bytes) -> int:
        if self.name == "rule_hits_inputs.zip.partial":
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", full_disk)
    try:
        archive_io.swap_in({a: b"new-a", b: b"new-b"})
    except OSError:
        pass
    else:
        raise AssertionError("swap_in should have raised")
    monkeypatch.undo()
    assert (a.read_bytes(), b.read_bytes()) == (b"current-a", b"current-b")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rule_hits.json", "rule_hits_inputs.zip"]
    archive_io.swap_in({a: b"new-a", b: b"new-b"})  # a retry is not blocked by leftovers
    assert (a.read_bytes(), b.read_bytes()) == (b"new-a", b"new-b")


def test_swap_in_treats_a_locked_backup_as_cleanup_and_finishes_it_next_run(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    sys.path.insert(0, str(TASK))
    import archive_io

    a, b = tmp_path / "rule_hits.json", tmp_path / "rule_hits_inputs.zip"
    a.write_bytes(b"old-a")
    b.write_bytes(b"old-b")
    real = Path.unlink

    def locked(self: Path, missing_ok: bool = False) -> None:
        if self.name == "rule_hits_inputs.zip.previous":
            raise PermissionError("locked by another process")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    pending = archive_io.swap_in({a: b"new-a", b: b"new-b"})  # succeeds: the swap itself committed
    monkeypatch.undo()
    assert (a.read_bytes(), b.read_bytes()) == (b"new-a", b"new-b")
    assert [p.name for p in pending] == ["rule_hits_inputs.zip.previous"]
    assert (tmp_path / "rule_hits_inputs.zip.previous.committed").exists()
    archive_io.swap_in({a: b"newer-a", b: b"newer-b"})  # the next run removes the marked backup and proceeds
    assert (a.read_bytes(), b.read_bytes()) == (b"newer-a", b"newer-b")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rule_hits.json", "rule_hits_inputs.zip"]
