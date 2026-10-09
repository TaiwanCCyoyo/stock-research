from __future__ import annotations

import hashlib
import math
import os
import sys
from pathlib import Path
from statistics import median
from typing import Any

import pytest

from research_core.opportunity_history_catalog import RULE, SELECTOR
from scripts.build_opportunity_history import PAIRS, ROOT, TASK, canonical, code_identity, descriptor, read_json, resolve_params_artifact, sha, write_json
from scripts.query_opportunity_history import calendar_content_id, series_content_id
from scripts.rebuild_saved_opportunity_catalog import rebuild_saved_catalog
from scripts.tests.opportunity_trusted_fixture_calls import query_manifest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Saved rebuild publication requires Windows mandatory file-sharing guards")


def saved_catalog(task_root: Path) -> Path:
    root = task_root / "catalog-v1"
    for path in (root / "series", root / "chunks", task_root / "inputs", task_root / "method-snapshot", task_root / "runs/native"):
        path.mkdir(parents=True, exist_ok=True)
    (task_root / "inputs/fixture.bin").write_bytes(b"immutable input")
    receipt = {"files": [{"name": "fixture.bin", "snapshot_sha256": sha(task_root / "inputs/fixture.bin")}]}
    params: dict[str, Any] = read_json(ROOT / "tasks" / TASK / "params.json")
    write_json(task_root / "params.json", params)
    identity = code_identity()
    for name in ("analysis", "types"):
        path = task_root / "method-snapshot" / f"{name}.ts"
        path.write_bytes((ROOT / "tasks" / TASK / "method-snapshot" / f"{name}.ts").read_bytes())
        assert sha(path) == identity["source"][name]
    calendar: dict[str, Any] = {"dates": ["2020-01-01", "2020-01-02", "2020-01-03"]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    write_json(root / "series/calendar.json", calendar)
    calendar_ref = descriptor(root / "series/calendar.json", root, 3)
    rows = []
    for code, cohort, role in (("A", "metadata_stock", "stock"), ("U", "unresolved_identity", "unknown")):
        series = {
            "schema_version": "opportunity-series.v1",
            "code": code,
            "security_id": f"sec:{code}",
            "calendar_id": calendar["calendar_id"],
            "cohort": cohort,
            "instrument_role": role,
            "raw": [6.02, 8.127, 10],
            "adjusted": [6.02, 8.127, 10],
            "numeric_flags": {},
            "coverage": {},
        }
        series["series_id"] = series_content_id(series)
        path = root / "series" / f"{code}.json.gz"
        write_json(path, series)
        rows.append({key: series[key] for key in ("code", "security_id", "series_id", "cohort", "instrument_role")} | descriptor(path, root))
    series_manifest = {
        "schema_version": "opportunity-series-manifest.v1",
        "count": 2,
        "rows": rows,
        "calendar_id": calendar["calendar_id"],
        "calendar": calendar_ref,
        "input_receipt": receipt,
    }
    write_json(root / "series-manifest.json", series_manifest)
    context = {
        "series_manifest_sha256": sha(root / "series-manifest.json"),
        "calendar_sha256": calendar_ref["sha256"],
        "input_receipt_sha256": hashlib.sha256(canonical(receipt)).hexdigest(),
        "config_sha256": sha(task_root / "params.json"),
        "code_identity": identity,
        "producer_sha256": "frozen-producer",
        "adapter_sha256": "old-conservative-adapter",
    }
    wave: dict[str, Any] = {
        "start": 0,
        "peak": 2,
        "end": None,
        "observedThrough": 2,
        "maxDrawdown": 0,
        "leftCensored": True,
        "rightCensored": True,
    }
    adjusted = read_json(root / rows[0]["path"])["adjusted"]
    wave["gain"] = (math.exp(math.log(adjusted[2]) - math.log(adjusted[0])) - 1) * 100
    waves = [wave | {"id": "wave-small-0", "scale": "small"}, wave | {"id": "wave-large-1", "scale": "large"}]
    log_returns = [math.log(adjusted[i]) - math.log(adjusted[i - 1]) for i in range(1, len(adjusted))]
    centre = median(log_returns)
    noise = max(1e-4, 1.4826 * median(abs(value - centre) for value in log_returns))
    native = {
        "schema": "opportunity-native-results.v1",
        "security_id": "sec:A",
        "series_id": rows[0]["series_id"],
        "calendar_id": calendar["calendar_id"],
        "input_identity": {"series_sha256": rows[0]["sha256"], "calendar_sha256": calendar_ref["sha256"]},
        "code_identity": identity,
        "source_run_indices": [0, 0, 0],
        "support_records": [],
        "native": [
            {
                "method": method,
                "scale": scale,
                "status": "ok",
                "error": None,
                "result": {"waves": waves, "segments": [], "launches": [], "fit": [6.02, 8.127, 10], "diagnostics": {"noise": noise}},
            }
            for method, scale in sorted(PAIRS)
        ],
        "timing": {"elapsed_ms": 123},
    }
    native_path = task_root / "runs/native/A.json.gz"
    write_json(native_path, native)
    native_receipt = {
        "schema_version": "opportunity-native-receipt.v1",
        "context": context,
        "sha256": sha(native_path),
        "security_id": "sec:A",
        "series_id": rows[0]["series_id"],
    }
    receipt_path = task_root / "runs/native/A.receipt.json"
    write_json(receipt_path, native_receipt)
    write_json(root / "chunks/securities-00000.json.gz", {"rows": [{"security_id": "sec:A"}, {"security_id": "sec:U"}]})
    write_json(root / "chunks/transitions-00000.json.gz", {"rows": [{"old_gain": None, "new_gain": None, "reason": "continuity_jump"}]})
    write_json(root / "classifications.json", {"rows": [{"label": "unknown"}]})
    manifest = {
        "schema_version": "opportunity-local-history-preview.v1",
        "rule": RULE,
        "selector": SELECTOR,
        "security_count": 2,
        "analyzed_security_count": 1,
        "calendar_id": calendar["calendar_id"],
        "calendar": calendar_ref,
        "series_manifest": descriptor(root / "series-manifest.json", root, 2),
        "series": {row["code"]: {key: row[key] for key in ("path", "sha256", "security_id", "series_id")} for row in rows},
        "input_receipt": receipt,
        "config": params,
        "code_identity": identity,
        "producer_identity": context,
        "native": {"A": descriptor(native_path, root, 6) | {"receipt": descriptor(receipt_path, root)}},
        "extras": {"classifications": descriptor(root / "classifications.json", root, 1)},
        "tables": {name: [descriptor(root / "chunks" / f"{name}-00000.json.gz", root, count)] for name, count in (("securities", 2), ("transitions", 1))},
        "performance_preflight": {"elapsed_seconds": 1},
        "source_code_commit": "37cb418",
    }
    write_json(root / "manifest.json", manifest)
    return root / "manifest.json"


def test_rebuild_saved_evidence_restores_exact_run_gain_and_preserves_v1(tmp_path: Path) -> None:
    source_path = saved_catalog(tmp_path / "task")
    task_root = source_path.parent.parent
    before = {path.relative_to(task_root): path.read_bytes() for path in task_root.rglob("*") if path.is_file()}
    source = read_json(source_path)
    native_saved = read_json(task_root / "runs/native/A.json.gz")
    assert native_saved["source_run_indices"] == [0, 0, 0]
    assert read_json(source_path.parent / "series/A.json.gz")["adjusted"] == [6.02, 8.127, 10]
    for record in native_saved["native"]:
        assert [(wave["id"], wave["scale"]) for wave in record["result"]["waves"]] == [("wave-small-0", "small"), ("wave-large-1", "large")]
        assert all(wave["leftCensored"] and wave["rightCensored"] for wave in record["result"]["waves"])
        assert all(wave["gain"] == pytest.approx((10 / 6.02 - 1) * 100) for wave in record["result"]["waves"])
    output = task_root / "catalog-v2"
    manifest = rebuild_saved_catalog(source_path, output)
    result = query_manifest(output / "manifest.json", "A", "2020-01-02")
    assert result["member"] and result["gain"] == pytest.approx(0.35)
    assert manifest["analysis_recomputed"] is False
    assert manifest["gain_policy"] == "exact_pinned_js_run.preview.v2"
    assert manifest["producer_identity"] == source["producer_identity"]
    assert manifest["code_identity"] == source["code_identity"]
    assert manifest["performance_preflight"] == source["performance_preflight"]
    assert manifest["source_manifest"]["sha256"] == sha(source_path)
    native_ref = manifest["native"]["A"]
    assert (output / native_ref["path"]).resolve() == (task_root / "runs/native/A.json.gz").resolve()
    assert native_ref["sha256"] == source["native"]["A"]["sha256"]
    assert sum(ref["count"] for ref in manifest["tables"]["methods"]) == 6
    assert query_manifest(output / "manifest.json", "U", "2020-01-02")["stock_opportunity_count"] == 0
    for path, raw in before.items():
        assert (task_root / path).read_bytes() == raw
    for ref in [source["calendar"], source["series_manifest"], *source["series"].values(), *source["extras"].values()]:
        assert (output / ref["path"]).read_bytes() == (source_path.parent / ref["path"]).read_bytes()
    assert read_json(source_path.parent / "chunks/transitions-00000.json.gz")["rows"][0]["new_gain"] is None
    with pytest.raises(FileExistsError):
        rebuild_saved_catalog(source_path, output)


@pytest.mark.parametrize("declared", [True, False])
def test_rebuild_rebinds_external_params_without_copy(tmp_path: Path, declared: bool) -> None:
    source_path = saved_catalog(tmp_path / "task")
    source = read_json(source_path)
    old_params = source_path.parent.parent / "params.json"
    params = tmp_path / "external params.json"
    params.write_bytes(old_params.read_bytes())
    old_params.unlink()
    if declared:
        source["params_artifact"] = descriptor(params, source_path.parent)
        source_path.unlink()
        write_json(source_path, source)
    original = params.read_bytes()
    output = tmp_path / "another destination" / "catalog-v2"
    manifest = rebuild_saved_catalog(source_path, output, params_path=None if declared else params)
    assert resolve_params_artifact(output / "manifest.json", manifest) == params.resolve()
    assert manifest["params_artifact"] == descriptor(params.resolve(), output)
    assert manifest["params_artifact"]["sha256"] == source["producer_identity"]["config_sha256"]
    assert params.read_bytes() == original
    assert not (output / "params.json").exists()
    assert not (output.parent / "params.json").exists()
    assert query_manifest(output / "manifest.json", "A", "2020-01-02")["gain"] == pytest.approx(0.35)


@pytest.mark.parametrize("tamper", ["input", "params", "native", "table", "receipt_context", "six_records"])
def test_tampered_frozen_evidence_refused_before_output(tmp_path: Path, tamper: str) -> None:
    source_path = saved_catalog(tmp_path / "task")
    task_root = source_path.parent.parent
    if tamper in ("input", "params", "native", "table"):
        paths = {
            "input": task_root / "inputs/fixture.bin",
            "params": task_root / "params.json",
            "native": task_root / "runs/native/A.json.gz",
            "table": source_path.parent / "chunks/securities-00000.json.gz",
        }
        paths[tamper].write_bytes(b"tampered")
    else:
        receipt_path = task_root / "runs/native/A.receipt.json"
        receipt = read_json(receipt_path)
        source = read_json(source_path)
        if tamper == "receipt_context":
            receipt["context"]["code_identity"] = {}
        else:
            native_path = task_root / "runs/native/A.json.gz"
            native = read_json(native_path)
            native["native"].pop()
            native_path.unlink()
            write_json(native_path, native)
            receipt["sha256"] = sha(native_path)
            source["native"]["A"]["sha256"] = sha(native_path)
        receipt_path.unlink()
        write_json(receipt_path, receipt)
        source["native"]["A"]["receipt"]["sha256"] = sha(receipt_path)
        source_path.unlink()
        write_json(source_path, source)
    with pytest.raises(ValueError):
        rebuild_saved_catalog(source_path, task_root / "catalog-v2")
    assert not (task_root / "catalog-v2").exists()


@pytest.mark.parametrize("failed_reference", ["source_manifest", "native", "receipt", "params"])
def test_windows_cross_drive_preflight_leaves_no_partial_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_reference: str,
) -> None:
    source_path = saved_catalog(tmp_path / "task")
    source = read_json(source_path)
    output = source_path.parent.parent / "catalog-v2"
    reference_paths = {
        "source_manifest": source_path,
        "params": source_path.parent.parent / "params.json",
        "native": source_path.parent / source["native"]["A"]["path"],
        "receipt": source_path.parent / source["native"]["A"]["receipt"]["path"],
    }
    expected_failure = reference_paths[failed_reference].resolve()
    original_relpath = os.path.relpath
    visited = []

    def windows_cross_drive(path: Any, start: Any = os.curdir) -> str:
        if Path(start).resolve() == output.resolve():
            visited.append(Path(path).resolve())
            if Path(path).resolve() == expected_failure:
                # Exercise the actual Windows failure boundary, without fake
                # drive syntax that a POSIX host would interpret as a filename.
                raise ValueError("path is on mount 'D:', start on mount 'E:'")
        return original_relpath(path, start)

    def reject_copy(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Cross-drive preflight must finish before any physical copy")

    def reject_adaptation(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Cross-drive rejection must precede native adaptation")

    def reject_process(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Saved-only rebuild must never execute Node or another process")

    monkeypatch.setattr("scripts.build_opportunity_history.os.path.relpath", windows_cross_drive)
    monkeypatch.setattr("scripts.rebuild_saved_opportunity_catalog._copy_reference", reject_copy)
    monkeypatch.setattr("scripts.rebuild_saved_opportunity_catalog.adapt_security", reject_adaptation)
    monkeypatch.setattr("scripts.build_opportunity_history.subprocess.run", reject_process)
    with pytest.raises(ValueError, match="same Windows drive.*mount"):
        rebuild_saved_catalog(source_path, output)
    assert expected_failure in visited
    assert not output.exists()
