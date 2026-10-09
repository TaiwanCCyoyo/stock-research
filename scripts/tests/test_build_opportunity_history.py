from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts import build_opportunity_history as producer
from scripts.build_opportunity_history import PAIRS, build_catalog, code_identity, descriptor, read_json, sha, write_json
from scripts.opportunity_history_native_validation import _derive_source, expected_support_records
from scripts.query_opportunity_history import calendar_content_id, series_content_id
from scripts.query_opportunity_history import query_manifest as query_history


def query_manifest(manifest_path: Path, code: str, date: str) -> dict[str, Any]:
    """Explicitly pin this test-owned synthetic publication."""
    return query_history(manifest_path, code, date, expected_manifest_sha256=sha(manifest_path))


def fixture_params(root: Path) -> Path:
    """Pin original bytes on the fixture's drive; production still rejects cross-drive refs."""
    path = root / "fixture-params.json"
    raw = (producer.ROOT / "tasks" / producer.TASK / "params.json").read_bytes()
    if path.exists():
        assert path.read_bytes() == raw
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return path


def inputs(root: Path) -> Path:
    root.mkdir()
    (root / "series").mkdir()
    calendar: dict[str, Any] = {"dates": ["2020-01-01", "2020-01-02", "2020-01-03"]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    write_json(root / "series/calendar.json", calendar)
    rows = []
    for code, cohort, role in [
        ("A", "metadata_stock", "stock"),
        ("B", "innovation_board", "stock"),
        ("C", "unresolved_identity", "unknown"),
        ("0050", "benchmark", "benchmark"),
    ]:
        series = {
            "schema_version": "opportunity-series.v1",
            "security_id": f"security:{code}",
            "code": code,
            "name": code,
            "calendar_id": calendar["calendar_id"],
            "cohort": cohort,
            "instrument_role": role,
            "raw": [100, None, 102],
            "adjusted": [100, None, 102],
            "sources": ["official", None, "shioaji"],
            "numeric_flags": {},
            "coverage_caveats": ["availability_unknown"],
            "coverage": {"date_count": 2, "missing_count": 1, "usable_adjusted_count": 2},
        }
        series["series_id"] = series_content_id(series)
        path = root / "series" / f"{code}.json.gz"
        write_json(path, series)
        rows.append(
            {key: series[key] for key in ("code", "name", "security_id", "series_id", "cohort", "instrument_role", "coverage")} | descriptor(path, root)
        )
    manifest = {
        "schema_version": "opportunity-series-manifest.v1",
        "calendar_id": calendar["calendar_id"],
        "calendar": descriptor(root / "series/calendar.json", root, 3),
        "count": 4,
        "rows": rows,
        "price_basis": "permanent-reference-factor-close.preview.v1",
        "input_receipt": {"files": [{"name": "fixture", "snapshot_sha256": "frozen"}]},
    }
    write_json(root / "series-manifest.json", manifest)
    return root / "series-manifest.json"


def fake_runner(calls: list[str]) -> Callable[[Path, Path, Path], None]:
    def run(series_path: Path, calendar_path: Path, output_path: Path) -> None:
        series = read_json(series_path)
        calls.append(series["code"])
        native = {
            "schema": "opportunity-native-results.v1",
            **{key: series[key] for key in ("security_id", "series_id", "calendar_id")},
            "input_identity": {"series_sha256": sha(series_path), "calendar_sha256": sha(calendar_path)},
            "code_identity": code_identity(),
            "native": [
                {
                    "method": method,
                    "scale": scale,
                    "status": "ok",
                    "result": {"segments": [], "launches": [], "waves": [], "fit": [100, None, 102], "diagnostics": {"converged": False}},
                    "error": None,
                }
                for method, scale in sorted(PAIRS)
            ],
            "support_records": [],
        }
        expected = _derive_source({"series": series, "calendar": read_json(calendar_path), "native": native})
        native["source_run_indices"] = expected["source_run_indices"]
        for record, derived in zip(native["native"], expected["records"], strict=True):
            record["result"].update(waves=derived["waves"], segments=derived["phases"], launches=derived["launches"])
            record["result"]["diagnostics"]["noise"] = expected["noise"]
        native["support_records"] = expected_support_records(native)
        write_json(output_path, native)

    return run


@pytest.mark.parametrize("resume", [False, True])
def test_empty_calendar_rejected_before_outputs(tmp_path: Path, resume: bool) -> None:
    root = tmp_path / "catalog"
    (root / "series").mkdir(parents=True)
    calendar: dict[str, Any] = {"dates": []}
    calendar["calendar_id"] = calendar_content_id(calendar)
    calendar_path = root / "series/calendar.json"
    write_json(calendar_path, calendar)
    source = root / "series-manifest.json"
    write_json(
        source,
        {
            "schema_version": "opportunity-series-manifest.v1",
            "calendar_id": calendar["calendar_id"],
            "calendar": descriptor(calendar_path, root, 0),
            "count": 0,
            "rows": [],
            "price_basis": "permanent-reference-factor-close.preview.v1",
            "input_receipt": {"files": []},
        },
    )
    params = fixture_params(root)
    native_dir = tmp_path / "native"
    if resume:
        native_dir.mkdir()
        (native_dir / "retained.failure.json").write_bytes(b"earlier native evidence")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    calls: list[str] = []
    with pytest.raises(ValueError, match="^Empty history calendar$"):
        build_catalog(source, native_dir, params_path=params, runner=fake_runner(calls), resume=resume, progress=lambda _: None)
    assert calls == []
    assert native_dir.exists() is resume
    assert not (root / "chunks").exists()
    assert not (root / "manifest.json").exists()
    assert not (root / "publication.failure.json").exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_nonempty_calendar_without_eligible_stocks_publishes(tmp_path: Path) -> None:
    source = inputs(tmp_path / "catalog")
    content = read_json(source)
    content["rows"] = [row for row in content["rows"] if row["code"] in {"C", "0050"}]
    content["count"] = len(content["rows"])
    source.unlink()
    write_json(source, content)
    calls: list[str] = []
    manifest = build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=fake_runner(calls), progress=lambda _: None)
    assert calls == []
    assert manifest["security_count"] == 2
    assert manifest["analyzed_security_count"] == 0
    assert manifest["window"] == {"start": "2020-01-01", "end": "2020-01-03"}
    assert manifest["native"] == {}
    assert read_json(source.parent / "manifest.json") == manifest
    securities = [row for ref in manifest["tables"]["securities"] for row in read_json(source.parent / ref["path"])["rows"]]
    assert {row["code"] for row in securities} == {"C", "0050"}
    assert all(not row["stock_opportunity_eligible"] for row in securities)


def single_date_excluded_inputs(root: Path) -> Path:
    source = inputs(root)
    calendar: dict[str, Any] = {"dates": ["2020-01-01"]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    calendar_path = root / "series/calendar.json"
    calendar_path.unlink()
    write_json(calendar_path, calendar)
    series_path = root / "series/C.json.gz"
    series = read_json(series_path)
    series.update(
        calendar_id=calendar["calendar_id"],
        raw=[100],
        adjusted=[100],
        sources=["official"],
        coverage={"date_count": 1, "missing_count": 0, "usable_adjusted_count": 1},
    )
    series["series_id"] = series_content_id(series)
    series_path.unlink()
    write_json(series_path, series)
    content = read_json(source)
    content.update(
        calendar_id=calendar["calendar_id"],
        calendar=descriptor(calendar_path, root, 1),
        count=1,
        rows=[
            {key: series[key] for key in ("code", "name", "security_id", "series_id", "cohort", "instrument_role", "coverage")} | descriptor(series_path, root)
        ],
    )
    source.unlink()
    write_json(source, content)
    return source


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("count", [True, 1.0], ids=["bool", "integral_float"])
@pytest.mark.parametrize("field", ["source", "calendar"])
def test_manifest_counts_require_strict_integers_before_outputs(tmp_path: Path, resume: bool, count: Any, field: str) -> None:
    source = single_date_excluded_inputs(tmp_path / "catalog")
    content = read_json(source)
    target = content if field == "source" else content["calendar"]
    target["count"] = count
    source.unlink()
    write_json(source, content)
    root = source.parent
    params = fixture_params(root)
    native_dir = tmp_path / "native"
    if resume:
        native_dir.mkdir()
        (native_dir / "retained.failure.json").write_bytes(b"earlier native evidence")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    calls: list[str] = []
    message = "Invalid series manifest schema/count" if field == "source" else "Calendar identity/count mismatch"
    with pytest.raises(ValueError, match=message):
        build_catalog(source, native_dir, params_path=params, runner=fake_runner(calls), resume=resume, progress=lambda _: None)
    assert calls == []
    assert native_dir.exists() is resume
    assert not (root / "chunks").exists()
    assert not (root / "manifest.json").exists()
    assert not (root / "publication.failure.json").exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("source_count", [0, 1])
def test_integer_counts_with_nonempty_calendar_publish(tmp_path: Path, source_count: int) -> None:
    source = single_date_excluded_inputs(tmp_path / "catalog")
    if source_count == 0:
        content = read_json(source)
        content.update(count=0, rows=[])
        source.unlink()
        write_json(source, content)
    calls: list[str] = []
    manifest = build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=fake_runner(calls), progress=lambda _: None)
    assert calls == []
    assert manifest["security_count"] == source_count
    assert manifest["analyzed_security_count"] == 0
    assert manifest["window"] == {"start": "2020-01-01", "end": "2020-01-01"}
    assert manifest["calendar"]["count"] == 1
    assert read_json(source.parent / "manifest.json") == manifest


def excluded_security_id_inputs(root: Path, security_ids: dict[str, Any]) -> Path:
    source = inputs(root)
    content = read_json(source)
    content["rows"] = [row for row in content["rows"] if row["code"] in security_ids]
    content["count"] = len(content["rows"])
    for row in content["rows"]:
        series_path = root / row["path"]
        series = read_json(series_path)
        series["security_id"] = security_ids[row["code"]]
        series["series_id"] = series_content_id(series)
        series_path.unlink()
        write_json(series_path, series)
        row.update(security_id=series["security_id"], series_id=series["series_id"], sha256=sha(series_path))
    source.unlink()
    write_json(source, content)
    return source


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize(
    "security_id",
    ["security:0050", "", " \t\n", "\ufeff", " \ufeff\t\ufeff\n", None, 1, ["security:C"]],
    ids=["duplicate", "empty", "whitespace", "bom", "mixed_bom_whitespace", "null", "integer", "list"],
)
def test_invalid_or_duplicate_security_ids_rejected_before_outputs(tmp_path: Path, resume: bool, security_id: Any) -> None:
    source = excluded_security_id_inputs(tmp_path / "catalog", {"C": security_id, "0050": "security:0050"})
    root = source.parent
    params = fixture_params(root)
    native_dir = tmp_path / "native"
    if resume:
        native_dir.mkdir()
        (native_dir / "retained.failure.json").write_bytes(b"earlier native evidence")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    calls: list[str] = []
    with pytest.raises(ValueError, match="^Invalid or duplicate security_id in series manifest$"):
        build_catalog(source, native_dir, params_path=params, runner=fake_runner(calls), resume=resume, progress=lambda _: None)
    assert calls == []
    assert native_dir.exists() is resume
    assert not (root / "chunks").exists()
    assert not (root / "manifest.json").exists()
    assert not (root / "publication.failure.json").exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_valid_security_ids_preserve_raw_whitespace_and_distinctness(tmp_path: Path) -> None:
    security_ids = {"C": " \tsecurity:shared\n", "0050": "security:shared"}
    source = excluded_security_id_inputs(tmp_path / "catalog", security_ids)
    calls: list[str] = []
    manifest = build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=fake_runner(calls), progress=lambda _: None)
    assert calls == []
    assert manifest["security_count"] == 2
    assert manifest["analyzed_security_count"] == 0
    assert {code: ref["security_id"] for code, ref in manifest["series"].items()} == security_ids
    assert read_json(source.parent / "manifest.json") == manifest
    securities = [row for ref in manifest["tables"]["securities"] for row in read_json(source.parent / ref["path"])["rows"]]
    assert {row["code"]: row["security_id"] for row in securities} == security_ids
    for code, ref in manifest["series"].items():
        assert read_json(source.parent / ref["path"])["security_id"] == security_ids[code]


def test_all_roles_six_records_chunks_extras_and_query(tmp_path: Path) -> None:
    source = inputs(tmp_path / "catalog")
    calls: list[str] = []
    progress: list[str] = []
    extra_path = source.parent / "sources.json"
    write_json(extra_path, {"rows": [{"locator": "synthetic"}]})
    manifest = build_catalog(
        source,
        tmp_path / "native",
        params_path=fixture_params(source.parent),
        runner=fake_runner(calls),
        progress=progress.append,
        chunk_rows=2,
        extras={"sources": descriptor(extra_path, source.parent, 1)},
    )
    assert sorted(calls) == ["A", "B"]
    assert manifest["security_count"] == 4 and manifest["analyzed_security_count"] == 2
    assert len(progress) == 4
    for refs in manifest["tables"].values():
        for ref in refs:
            path = source.parent / ref["path"]
            assert ref["path"].startswith("chunks/")
            assert sha(path) == ref["sha256"]
            assert len(read_json(path)["rows"]) == ref["count"] <= 2
    assert sum(r["count"] for r in manifest["tables"]["methods"]) == 12
    securities = [row for ref in manifest["tables"]["securities"] for row in read_json(source.parent / ref["path"])["rows"]]
    assert len(securities) == 4
    assert all(row["coverage"]["missing_count"] == 1 for row in securities)
    assert sum(row["stock_opportunity_eligible"] for row in securities) == 2
    assert query_manifest(source.parent / "manifest.json", "0050", "2020-01-01")["stock_opportunity_count"] == 0
    for code, ref in manifest["native"].items():
        assert len(read_json(source.parent / ref["path"])["native"]) == 6
        assert read_json(source.parent / ref["receipt"]["path"])["sha256"] == ref["sha256"]
    with pytest.raises(FileExistsError):
        build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=fake_runner(calls), resume=True)


def test_resume_verified_native_without_reexecution(tmp_path: Path) -> None:
    first = inputs(tmp_path / "first")
    second = inputs(tmp_path / "second")
    calls: list[str] = []
    original = build_catalog(first, tmp_path / "native", params_path=fixture_params(first.parent), runner=fake_runner(calls), progress=lambda _: None)

    def never(*_: Any) -> None:
        raise AssertionError("verified native must not run again")

    resumed = build_catalog(second, tmp_path / "native", params_path=fixture_params(second.parent), runner=never, resume=True, progress=lambda _: None)
    assert sorted(calls) == ["A", "B"]
    assert original["tables"] == resumed["tables"]
    assert original["producer_identity"] == resumed["producer_identity"]


def _assert_publication_failure(root: Path, stage: str, original_source_sha: str) -> None:
    failure = read_json(root / "publication.failure.json")
    assert failure["schema_version"] == "opportunity-publication-failure.v1"
    assert failure["stage"] == stage
    assert failure["context"]["series_manifest_sha256"] == original_source_sha
    assert failure["error"]["name"] == "ValueError"
    assert isinstance(failure["error"]["message"], str) and failure["error"]["message"]
    assert not (root / "manifest.json").exists()


@pytest.mark.parametrize(
    "artifact", ["processed_series", "calendar", "params", "series_manifest", "extras", "extras_resigned", "excluded_series", "native", "receipt"]
)
def test_after_native_rejects_changed_frozen_artifacts_without_discarding_bytes(tmp_path: Path, artifact: str) -> None:
    source = inputs(tmp_path / "catalog")
    root = source.parent
    params = fixture_params(root)
    extra = root / "sources.json"
    write_json(extra, {"rows": [{"locator": "frozen"}]})
    extras = {"sources": descriptor(extra, root, 1)}
    source_sha = sha(source)
    native_dir = tmp_path / "native"
    native_dir.mkdir()
    error_path = native_dir / "unrelated.failure.json"
    error_path.write_bytes(b"retained earlier failure evidence")
    successful = fake_runner([])
    preserved: dict[Path, bytes] = {}
    changed: dict[Path, bytes] = {}

    def run(series_path: Path, calendar_path: Path, output_path: Path) -> None:
        successful(series_path, calendar_path, output_path)
        if read_json(series_path)["code"] == "B":
            target = {
                "processed_series": root / "series/A.json.gz",
                "calendar": calendar_path,
                "params": params,
                "series_manifest": source,
                "extras": extra,
                "extras_resigned": extra,
                "excluded_series": root / "series/0050.json.gz",
                "native": native_dir / "A.json.gz",
                "receipt": native_dir / "A.receipt.json",
            }[artifact]
            # Whitespace keeps parsed JSON unchanged and proves raw bytes are pinned.
            target.write_bytes(target.read_bytes() + b" \n")
            if artifact == "extras_resigned":
                extras["sources"]["sha256"] = sha(extra)
            changed[target] = target.read_bytes()
            preserved.update({path: path.read_bytes() for path in native_dir.iterdir()})

    with pytest.raises(ValueError):
        build_catalog(source, native_dir, params_path=params, runner=run, workers=1, extras=extras, progress=lambda _: None)
    assert not (root / "chunks").exists()
    assert changed and all(path.read_bytes() == raw for path, raw in changed.items())
    assert all(path.read_bytes() == raw for path, raw in preserved.items())
    _assert_publication_failure(root, "after_native", source_sha)
    if artifact == "processed_series":
        diagnostic_path = root / "publication.failure.json"
        diagnostic_bytes = diagnostic_path.read_bytes()
        with pytest.raises(FileExistsError):
            build_catalog(source, native_dir, params_path=params, runner=run, resume=True, workers=1, extras=extras, progress=lambda _: None)
        assert diagnostic_path.read_bytes() == diagnostic_bytes
        assert all(path.read_bytes() == raw for path, raw in preserved.items())


@pytest.mark.parametrize("artifact", ["processed_series", "series_manifest"])
def test_resume_postflight_rejects_progress_callback_input_change(tmp_path: Path, artifact: str) -> None:
    first = inputs(tmp_path / "first")
    source = inputs(tmp_path / "resumed")
    native_dir = tmp_path / "native"
    build_catalog(first, native_dir, params_path=fixture_params(first.parent), runner=fake_runner([]), workers=1, progress=lambda _: None)
    params = fixture_params(source.parent)
    source_sha = sha(source)
    native_before = {path: path.read_bytes() for path in native_dir.iterdir()}
    target = source.parent / "series/A.json.gz" if artifact == "processed_series" else source
    changed: list[bytes] = []

    def never(*_: Any) -> None:
        raise AssertionError("Resume must use saved successful native")

    def progress(message: str) -> None:
        if json.loads(message)["code"] == "A":
            target.write_bytes(target.read_bytes() + b" \n")
            changed.append(target.read_bytes())

    with pytest.raises(ValueError):
        build_catalog(source, native_dir, params_path=params, runner=never, resume=True, workers=1, progress=progress)
    assert changed and target.read_bytes() == changed[0]
    assert {path: path.read_bytes() for path in native_dir.iterdir()} == native_before
    assert not (source.parent / "chunks").exists()
    _assert_publication_failure(source.parent, "after_native", source_sha)


@pytest.mark.parametrize("artifact", ["params", "extras"])
def test_before_manifest_rejects_change_during_chunk_export_and_preserves_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: str) -> None:
    source = inputs(tmp_path / "catalog")
    root = source.parent
    params = fixture_params(root)
    extra = root / "sources.json"
    write_json(extra, {"rows": [{"locator": "frozen"}]})
    extras = {"sources": descriptor(extra, root, 1)}
    source_sha = sha(source)
    native_dir = tmp_path / "native"
    original_write = producer.write_json
    retained: dict[Path, bytes] = {}
    changed: list[bytes] = []
    target = params if artifact == "params" else extra

    def write_then_change(path: Path, payload: Any) -> None:
        original_write(path, payload)
        if path.parent == root / "chunks" and not retained:
            retained[path] = path.read_bytes()
            retained.update({native: native.read_bytes() for native in native_dir.iterdir()})
            target.write_bytes(target.read_bytes() + b" \n")
            changed.append(target.read_bytes())

    monkeypatch.setattr(producer, "write_json", write_then_change)
    with pytest.raises(ValueError):
        build_catalog(source, native_dir, params_path=params, runner=fake_runner([]), workers=1, extras=extras, progress=lambda _: None)
    assert retained and all(path.read_bytes() == raw for path, raw in retained.items())
    assert changed and target.read_bytes() == changed[0]
    assert (root / "chunks").is_dir()
    _assert_publication_failure(root, "before_manifest", source_sha)


def test_before_manifest_rejects_changed_previous_chunk_and_preserves_written_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = inputs(tmp_path / "catalog")
    root = source.parent
    params = fixture_params(root)
    source_sha = sha(source)
    native_dir = tmp_path / "native"
    original_write = producer.write_json
    chunks: list[Path] = []
    retained: dict[Path, bytes] = {}
    changed_bytes = b"changed chunk bytes"

    def write_then_change_previous_chunk(path: Path, payload: Any) -> None:
        original_write(path, payload)
        if path.parent == root / "chunks":
            chunks.append(path)
            if len(chunks) == 2:
                # The first descriptor already captured its original file hash.
                chunks[0].write_bytes(changed_bytes)
            retained.update({chunk: chunk.read_bytes() for chunk in chunks})
            retained.update({native: native.read_bytes() for native in native_dir.iterdir()})

    monkeypatch.setattr(producer, "write_json", write_then_change_previous_chunk)
    with pytest.raises(ValueError):
        build_catalog(source, native_dir, params_path=params, runner=fake_runner([]), workers=1, chunk_rows=2, progress=lambda _: None)
    assert len(chunks) >= 2
    assert chunks[0].read_bytes() == changed_bytes
    assert all(path.read_bytes() == raw for path, raw in retained.items())
    assert set((root / "chunks").iterdir()) == set(chunks)
    _assert_publication_failure(root, "before_manifest", source_sha)


def test_native_cross_drive_reference_rejected_before_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = inputs(tmp_path / "catalog")
    directory = tmp_path / "native"
    source_hash = sha(source)
    calls: list[str] = []
    relative_path = producer.os.path.relpath

    def cross_drive(path: Any, start: Any = None) -> str:
        # Simulate Windows relpath's cross-drive error using real fixture paths.
        if Path(path) == directory or directory in Path(path).parents:
            raise ValueError("path is on a different mount from start")
        return relative_path(path, start)

    with monkeypatch.context() as patch:
        patch.setattr(producer.os.path, "relpath", cross_drive)
        with pytest.raises(ValueError, match="Native directory cannot be referenced relative to catalog root"):
            build_catalog(source, directory, params_path=fixture_params(source.parent), runner=fake_runner(calls), progress=lambda _: None)
    assert calls == []
    assert not directory.exists()
    assert not (source.parent / "chunks").exists()
    assert not (source.parent / "manifest.json").exists()
    assert sha(source) == source_hash

    manifest = build_catalog(source, directory, params_path=fixture_params(source.parent), runner=fake_runner(calls), progress=lambda _: None)
    assert sorted(calls) == ["A", "B"]
    assert manifest["analyzed_security_count"] == 2
    assert directory.is_dir()
    assert (source.parent / "manifest.json").is_file()


def test_params_cross_drive_rejected_before_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = inputs(tmp_path / "catalog")
    params = tmp_path / "custom params.json"
    params.write_bytes((producer.ROOT / "tasks" / producer.TASK / "params.json").read_bytes())
    native = tmp_path / "native"
    relative_path = producer.os.path.relpath
    calls: list[str] = []

    def cross_drive(path: Any, start: Any = None) -> str:
        if Path(path).resolve() == params.resolve():
            raise ValueError("path is on mount 'D:', start on mount 'E:'")
        return relative_path(path, start)

    monkeypatch.setattr(producer.os.path, "relpath", cross_drive)
    with pytest.raises(ValueError, match="Params artifact.*same Windows drive.*mount"):
        build_catalog(source, native, params_path=params, runner=fake_runner(calls), progress=lambda _: None)
    assert calls == []
    assert not native.exists()
    assert not (source.parent / "chunks").exists()
    assert not (source.parent / "manifest.json").exists()


@pytest.mark.parametrize("artifact", ["calendar", "series"])
def test_content_identity_checked_before_outputs(tmp_path: Path, artifact: str) -> None:
    source_path = inputs(tmp_path / "catalog")
    source = read_json(source_path)
    reference = source["calendar"] if artifact == "calendar" else source["rows"][0]
    artifact_path = source_path.parent / reference["path"]
    content = read_json(artifact_path)
    if artifact == "calendar":
        content["dates"][0] = "2019-12-31"
    else:
        content["adjusted"][0] = 99
    artifact_path.unlink()
    write_json(artifact_path, content)
    reference["sha256"] = sha(artifact_path)
    source_path.unlink()
    write_json(source_path, source)
    calls: list[str] = []
    with pytest.raises(ValueError, match="content identity"):
        build_catalog(source_path, tmp_path / "native", params_path=fixture_params(source_path.parent), runner=fake_runner(calls), progress=lambda _: None)
    assert calls == []
    assert not (tmp_path / "native").exists()
    assert not (source_path.parent / "chunks").exists()


@pytest.mark.parametrize("mutation", ["hash", "context", "six_records", "schema", "missing_receipt"])
def test_resume_rejects_unverified_native(tmp_path: Path, mutation: str) -> None:
    first = inputs(tmp_path / "first")
    second = inputs(tmp_path / "second")
    directory = tmp_path / "native"
    build_catalog(first, directory, params_path=fixture_params(first.parent), runner=fake_runner([]), progress=lambda _: None)
    receipt_path, native_path = directory / "A.receipt.json", directory / "A.json.gz"
    receipt = read_json(receipt_path)
    if mutation == "missing_receipt":
        receipt_path.unlink()
    elif mutation == "context":
        receipt["context"]["config_sha256"] = "wrong"
        receipt_path.write_text(json.dumps(receipt))
    elif mutation == "hash":
        native_path.write_bytes(b"corrupt")
    else:
        native = read_json(native_path)
        if mutation == "six_records":
            native["native"].pop()
        else:
            native["schema"] = "wrong"
        native_path.unlink()
        write_json(native_path, native)
        receipt["sha256"] = sha(native_path)
        receipt_path.write_text(json.dumps(receipt))
    with pytest.raises((ValueError, FileExistsError)):
        build_catalog(second, directory, params_path=fixture_params(second.parent), runner=fake_runner([]), resume=True, progress=lambda _: None)


def test_process_failure_preserved_and_input_hash_rejected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    source = inputs(tmp_path / "catalog")

    def failed(*_: Any) -> None:
        raise subprocess.CalledProcessError(1, "synthetic-node", stderr="synthetic process error")

    native_dir = tmp_path / "native"
    with pytest.raises(subprocess.CalledProcessError):
        build_catalog(source, native_dir, params_path=fixture_params(source.parent), runner=failed, progress=lambda _: None)
    diagnostic = read_json(native_dir / "A.failure.json")
    assert diagnostic["schema_version"] == "opportunity-native-process-failure.v1"
    assert diagnostic["process"]["returncode"] == 1
    assert diagnostic["process"]["stderr"] == "synthetic process error"
    assert diagnostic["process"]["stdout"] is None
    assert diagnostic["input_identity"]["series_sha256"] == sha(source.parent / "series/A.json.gz")
    assert diagnostic["context"]["series_manifest_sha256"] == sha(source)
    assert diagnostic["retained_output"] is None
    assert "Native runner failed code=A" in caplog.text
    assert not (native_dir / "A.json.gz").exists()
    assert not (native_dir / "A.receipt.json").exists()
    assert not (source.parent / "manifest.json").exists()
    assert not (source.parent / "chunks").exists()
    other = inputs(tmp_path / "other")
    (other.parent / "series/A.json.gz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_catalog(other, tmp_path / "other-native", params_path=fixture_params(other.parent), runner=fake_runner([]), progress=lambda _: None)


@pytest.mark.parametrize("failed_code", ["A", "B"])
def test_process_failure_preserves_runner_output_and_prior_success(tmp_path: Path, failed_code: str) -> None:
    source = inputs(tmp_path / "catalog")
    native_dir = tmp_path / "native"
    calls: list[str] = []
    successful = fake_runner(calls)
    original_error = subprocess.CalledProcessError(9, ["synthetic-node", "--fixture"], output="captured stdout", stderr="captured stderr")
    retained = b"unverified runner output bytes"

    def run(series_path: Path, calendar_path: Path, output_path: Path) -> None:
        if read_json(series_path)["code"] == failed_code:
            output_path.write_bytes(retained)
            raise original_error
        successful(series_path, calendar_path, output_path)

    with pytest.raises(subprocess.CalledProcessError) as caught:
        build_catalog(source, native_dir, params_path=fixture_params(source.parent), runner=run, workers=1, progress=lambda _: None)
    assert caught.value is original_error
    assert (native_dir / f"{failed_code}.json.gz").read_bytes() == retained
    failure = read_json(native_dir / f"{failed_code}.failure.json")
    assert failure["process"] == {"command": ["synthetic-node", "--fixture"], "returncode": 9, "stdout": "captured stdout", "stderr": "captured stderr"}
    assert failure["retained_output"]["sha256"] == sha(native_dir / f"{failed_code}.json.gz")
    assert not (native_dir / f"{failed_code}.receipt.json").exists()
    if failed_code == "B":
        assert calls == ["A"]
        assert read_json(native_dir / "A.receipt.json")["sha256"] == sha(native_dir / "A.json.gz")
    else:
        assert calls == []
    assert not (source.parent / "manifest.json").exists()
    assert not (source.parent / "chunks").exists()
    before = {path: path.read_bytes() for path in native_dir.iterdir()}
    with pytest.raises(FileExistsError, match="failure evidence exists"):
        build_catalog(source, native_dir, params_path=fixture_params(source.parent), runner=run, resume=True, workers=1, progress=lambda _: None)
    assert {path: path.read_bytes() for path in native_dir.iterdir()} == before


@pytest.mark.parametrize("status", ["error", "partial", "unknown", "missing_scope", "conflicting_error"])
def test_normal_runner_incomplete_scope_rejects_publication(tmp_path: Path, status: str) -> None:
    source = inputs(tmp_path / "catalog")
    native_dir = tmp_path / "native"
    successful = fake_runner([])
    retained: list[bytes] = []

    def run(series_path: Path, calendar_path: Path, output_path: Path) -> None:
        successful(series_path, calendar_path, output_path)
        native = read_json(output_path)
        if status == "missing_scope":
            native["native"].pop()
        elif status == "conflicting_error":
            native["native"][0]["error"] = {"message": "failure contradicts successful scope"}
        else:
            native["native"][0].update({"status": status, "result": None, "error": {"message": "retained method failure"}})
        output_path.unlink()
        write_json(output_path, native)
        retained.append(output_path.read_bytes())

    with pytest.raises(ValueError, match="six successful scopes|six method/scale"):
        build_catalog(source, native_dir, params_path=fixture_params(source.parent), runner=run, workers=1, progress=lambda _: None)
    assert (native_dir / "A.json.gz").read_bytes() == retained[0]
    assert not (native_dir / "A.receipt.json").exists()
    assert not (source.parent / "manifest.json").exists()
    assert not (source.parent / "chunks").exists()


@pytest.mark.parametrize("status", ["error", "partial"])
def test_resume_incomplete_native_keeps_existing_evidence(tmp_path: Path, status: str) -> None:
    first = inputs(tmp_path / "first")
    second = inputs(tmp_path / "second")
    native_dir = tmp_path / "native"
    build_catalog(first, native_dir, params_path=fixture_params(first.parent), runner=fake_runner([]), workers=1, progress=lambda _: None)
    output = native_dir / "A.json.gz"
    native = read_json(output)
    native["native"][0].update({"status": status, "result": None, "error": {"message": "old saved failure"}})
    output.unlink()
    write_json(output, native)
    receipt_path = native_dir / "A.receipt.json"
    receipt = read_json(receipt_path)
    receipt["sha256"] = sha(output)
    receipt_path.unlink()
    write_json(receipt_path, receipt)
    before = {path: path.read_bytes() for path in native_dir.iterdir()}

    def never(*_: Any) -> None:
        pytest.fail("Resume of incomplete saved native must not run methods")

    with pytest.raises(ValueError, match="six successful scopes"):
        build_catalog(second, native_dir, params_path=fixture_params(second.parent), runner=never, resume=True, workers=1, progress=lambda _: None)
    assert {path: path.read_bytes() for path in native_dir.iterdir()} == before
    assert not (second.parent / "manifest.json").exists()
    assert not (second.parent / "chunks").exists()


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("mutation", ["missing_runs", "wave", "noise", "phase", "launch"])
def test_successful_scopes_with_false_source_semantics_cannot_publish(tmp_path: Path, resume: bool, mutation: str) -> None:
    source = inputs(tmp_path / "catalog")
    native_dir = tmp_path / "native"
    params = fixture_params(source.parent)
    successful = fake_runner([])
    preserved: dict[Path, bytes] = {}

    def corrupt(native_path: Path) -> None:
        native = read_json(native_path)
        if mutation == "missing_runs":
            native.pop("source_run_indices")
        for record in native["native"]:
            result = record["result"]
            if mutation == "wave":
                result["waves"] = [
                    {
                        "id": "false-wave",
                        "start": 0,
                        "peak": 0,
                        "end": None,
                        "observedThrough": 0,
                        "gain": 0,
                        "maxDrawdown": 0,
                        "scale": "small",
                        "leftCensored": True,
                        "rightCensored": True,
                    }
                ]
            elif mutation == "noise":
                result["diagnostics"]["noise"] += 0.5
            elif mutation == "phase":
                result["segments"] = [{"start": 0, "end": 0, "slope": 0.01, "phase": "falling"}]
            elif mutation == "launch":
                result["launches"] = [
                    {
                        "id": "launch-0-reversal",
                        "index": 0,
                        "rangeStart": 0,
                        "rangeEnd": 0,
                        "kind": "reversal",
                        "preSlope": -0.01,
                        "postSlope": 0.01,
                        "sustainSessions": 0,
                        "relativeStrength": 1,
                        "forwardGain": 0,
                        "forwardEnd": 0,
                        "drawdown": 0,
                        "outcome": "unresolved",
                        "support": 1,
                    }
                ]
        native["support_records"] = expected_support_records(native)
        assert all(record["status"] == "ok" and record["error"] is None for record in native["native"])
        native_path.unlink()
        write_json(native_path, native)
        preserved[native_path] = native_path.read_bytes()

    def invalid_runner(series_path: Path, calendar_path: Path, output_path: Path) -> None:
        successful(series_path, calendar_path, output_path)
        corrupt(output_path)

    if resume:
        first = inputs(tmp_path / "first")
        build_catalog(first, native_dir, params_path=fixture_params(first.parent), runner=successful, workers=1, progress=lambda _: None)
        native_path = native_dir / "A.json.gz"
        corrupt(native_path)
        receipt_path = native_dir / "A.receipt.json"
        receipt = read_json(receipt_path)
        receipt["sha256"] = sha(native_path)
        receipt_path.unlink()
        write_json(receipt_path, receipt)
        preserved.update({path: path.read_bytes() for path in native_dir.iterdir()})

        def never(*_: Any) -> None:
            pytest.fail("Re-signed saved semantic corruption must fail without re-running methods")

        runner = never
    else:
        runner = invalid_runner
    with pytest.raises(ValueError, match="source_run_indices|Original source"):
        build_catalog(source, native_dir, params_path=params, runner=runner, resume=resume, workers=1, progress=lambda _: None)
    assert preserved and all(path.read_bytes() == raw for path, raw in preserved.items())
    if not resume:
        assert not (native_dir / "A.receipt.json").exists()
    assert not (source.parent / "manifest.json").exists()
    assert not (source.parent / "chunks").exists()
