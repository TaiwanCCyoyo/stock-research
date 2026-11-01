from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pandas as pd
import pytest

from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_groups_v1 import PRIMARY
from research_core.pattern_scan_report_v1 import build_q1_report_data, export_q1_report_data


def _fixture(root: Path, *, comparisons: bool = False) -> dict[str, tuple[bytes, int]]:
    root.mkdir()
    before: dict[str, tuple[bytes, int]] = {}
    for target in PATTERNS:
        family = root / target
        family.mkdir()
        rows = []
        for horizon in (126, 252):
            for control in ("pattern", PRIMARY[target]):
                rows.append({
                    "pattern_id": target,
                    "horizon": horizon,
                    "control_id": control,
                    "split": "cross-check",
                    "era": "all",
                    "mkt": "all",
                    "row_kind": "full",
                    "cohort_id": "union",
                    "feature_id": "unconditional",
                    "bin_id": "all",
                    "condition_status": "known",
                    "event_n": 0,
                    "known_n": 0,
                    "hit_n": 0,
                    "loss_n": 0,
                    "unknown_n": None,
                    "censored_n": 0,
                    "distinct_stock_n": 0,
                    "hit_rate": None,
                    "loss_rate": 0.0,
                })
        if comparisons:
            rows.extend(
                {**rows[0], "split": "all", "horizon": horizon, "control_id": control}
                for horizon in (126, 252)
                for control in ("pattern", "C-base-all", "C-base-daily")
            )
        summary = family / f"{target}-summary.parquet"
        annual = family / f"{target}-annual.parquet"
        pd.DataFrame(rows).to_parquet(summary, index=False)
        pd.DataFrame([{"target": target, "year": 2010, "event_n": 0}]).to_parquet(annual, index=False)
        descriptors = {}
        for path in (summary, annual):
            raw = path.read_bytes()
            descriptors[path.name] = {"path": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        receipt = {
            "schema": "run-receipt.v1",
            "run_id": f"fixture-{target}",
            "definition": "pattern-scan-local-q1.v1",
            "parameters": {
                "target": target,
                "stock_count": 1942,
                "input_id": "input-fixed",
                "numerical_source": {"source_id": "source-fixed", "code": {"commit": "historical-source", "dirty": True}},
            },
            "code": {"commit": "996cf6e", "dirty": False, "tree": "executor-code"},
            "results": descriptors,
        }
        receipt_path = family / f"{target}-receipt.json"
        receipt_path.write_text(json.dumps(receipt, separators=(",", ":")), encoding="utf-8")
        for path in (summary, annual, receipt_path):
            before[path.relative_to(root).as_posix()] = (path.read_bytes(), path.stat().st_mtime_ns)
    return before


def test_build_projects_stored_rows_and_all_24_tables(tmp_path: Path) -> None:
    root = tmp_path / "q1"
    before = _fixture(root)
    report, files = build_q1_report_data(root, as_of="2026-10-21")

    assert len(report["questions"][0]["tables"][0]["rows"]) == 48
    assert report["questions"][0]["status"] == "complete"
    assert all(question["status"] == "pending" for question in report["questions"][1:])
    assert len(report["downloads"]) == 24
    assert all(download["href"].startswith("data/tables/") for download in report["downloads"])
    assert len([name for name in files if name.startswith("tables/")]) == 24
    with ZipFile(BytesIO(files["q1-receipts.zip"])) as archive:
        assert set(archive.namelist()) == {f"{target}-receipt.json" for target in PATTERNS}
        for target in PATTERNS:
            assert archive.read(f"{target}-receipt.json") == before[f"{target}/{target}-receipt.json"][0]
    row = report["questions"][0]["tables"][0]["rows"][0]
    assert row["event_n"] == 0 and row["hit_rate"] is None and row["loss_rate"] == 0.0
    numerical_source = next(item for item in report["provenance"] if item["label"] == "數值來源程式")["value"]
    assert "dirty=true" in numerical_source and "歷史" in numerical_source
    assert next(item for item in report["provenance"] if item["label"] == "原始 Q1 收據")["href"] == "data/q1-receipts.zip"
    for relative, (raw, mtime_ns) in before.items():
        source = root / relative
        assert source.read_bytes() == raw
        assert source.stat().st_mtime_ns == mtime_ns
    summary_js = files["summary.js"].decode("utf-8")
    assert summary_js.startswith("window.REPORT_DATA = ") and "NaN" not in summary_js


def test_refuses_missing_family_and_inconsistent_identity(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    _fixture(missing)
    (missing / PATTERNS[-1]).rename(missing / "removed")
    with pytest.raises((FileNotFoundError, ValueError)):
        build_q1_report_data(missing, as_of="2026-10-21")

    inconsistent = tmp_path / "inconsistent"
    _fixture(inconsistent)
    receipt_path = inconsistent / PATTERNS[-1] / f"{PATTERNS[-1]}-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["parameters"]["input_id"] = "different-input"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="inconsistent"):
        build_q1_report_data(inconsistent, as_of="2026-10-21")


def test_refuses_tampered_final_table(tmp_path: Path) -> None:
    root = tmp_path / "tampered"
    _fixture(root)
    with (root / "H1" / "H1-summary.parquet").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="mismatch"):
        build_q1_report_data(root, as_of="2026-10-21")


def test_publication_is_new_directory_only(tmp_path: Path) -> None:
    root = tmp_path / "q1"
    _fixture(root)
    output = tmp_path / "report" / "data"
    export_q1_report_data(root, output, as_of="2026-10-21")
    assert (output / "summary.js").is_file()
    assert (output / "tables" / "H1-summary.parquet").read_bytes() == (root / "H1" / "H1-summary.parquet").read_bytes()
    with pytest.raises(FileExistsError):
        export_q1_report_data(root, output, as_of="2026-10-21")


def test_stored_comparisons_keep_scopes_deltas_and_own_quota_random(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_report_v1 as module

    monkeypatch.setattr(module, "PATTERNS", ("B1",))
    candidate = "fixed-candidate"
    family = tmp_path / "remaining/B1"
    conditions = family / "conditions"
    conditions.mkdir(parents=True)
    (conditions / "run-receipt.json").write_text("{}")
    (conditions / "top-candidates.json").write_text(json.dumps({candidate: [{"feature_id": "C3", "bin_id": "ge60"}]}))
    (family / "q4").mkdir()
    (family / "q4/run-receipt.json").write_text("{}")

    def read(path: Path) -> pd.DataFrame:
        if path.name == "B1-summary.parquet":
            return pd.DataFrame([
                {**module.FACETS, "split": "all", "control_id": control, "horizon": horizon, "known_n": 10, "hit_rate": rate, "loss_rate": 0.4}
                for horizon in (126, 252)
                for control, rate in (("pattern", 0.3), ("C-base-all", 0.2), ("C-base-daily", 0.1 if horizon == 126 else None))
            ])
        if path.name == "coverage.parquet":
            return pd.DataFrame([
                {
                    "group_id": group,
                    "split": "cross-check",
                    "era": "all",
                    "mkt": "all",
                    "episode_n": 100,
                    "coverage_rate": rate,
                    "matched_n": int(rate * 100),
                    "unmatched_n": 100 - int(rate * 100),
                    "unknown_n": 0,
                }
                for group, rate in (
                    ("B1:original", 0.8),
                    ("B1:original:C-base-random", 0.6),
                    ("B1:candidate:fixed-candidate", 0.1),
                    ("B1:candidate:fixed-candidate:C-base-random", 0.02),
                )
            ])
        control = path.parent.name.rsplit("-h", 1)[0]
        rate, count = {"pattern%3Aunion": (0.3, 10), "C-base-no-pattern": (0.2, 20), "C-base-all": (0.25, 30), "C-52w": (0.15, 40)}[control]
        return pd.DataFrame([
            {
                "split": "cross-check",
                "era": "all",
                "mkt": "all",
                "row_kind": "full",
                "feature_id": "candidate",
                "condition_status": "known",
                "candidate_id": candidate,
                "control_id": control,
                "hit_rate": rate,
                "known_n": count,
                "loss_rate": 0.0,
            }
        ])

    monkeypatch.setattr(module, "read_frame", read)
    report: dict[str, Any] = {"questions": [{"id": f"Q{i}", "tables": []} for i in range(1, 7)]}
    module.add_stored_comparisons(report, tmp_path / "q1", tmp_path / "remaining")
    headline = report["comparisonSummary"]["rows"]
    assert headline[0]["baseline_multiple"] == pytest.approx(3)
    assert headline[0]["delta_pp"] == pytest.approx(10)
    assert headline[1]["baseline_multiple"] is None
    row = report["questions"][1]["tables"][0]["rows"][0]
    assert row["pattern_minus_no_pattern_pp"] == pytest.approx(10)
    assert row["pattern_minus_all_pp"] == pytest.approx(5)
    assert (row["pattern_known_n"], row["no_pattern_known_n"], row["all_known_n"]) == (10, 20, 30)
    assert row["loss_rate"] == 0.0
    pairs = report["questions"][3]["tables"][0]["rows"]
    assert pairs[0]["random_coverage_rate"] == 0.6
    assert pairs[1]["random_coverage_rate"] == 0.02
    assert pairs[0]["coverage_delta_pp"] == pytest.approx(20)
    # A checkpoint without its existing phase completion marker is not promoted.
    (conditions / "run-receipt.json").unlink()
    module.add_stored_comparisons(report, tmp_path / "q1", tmp_path / "remaining")
    assert report["questions"][1]["tables"] == []
    assert report["questions"][1]["status"] == "pending"


@pytest.mark.parametrize("families", [(), ("B1",), ("B1", "B4"), ("B1", "H1", "B4")])
def test_available_status_tracks_zero_new_and_all_families(families: tuple[str, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_report_v1 as module

    monkeypatch.setattr(module, "PATTERNS", ("B1", "H1", "B4"))
    report: dict[str, Any] = {"status": "complete", "questions": [{"id": f"Q{i}"} for i in range(1, 7)]}
    provided = {f"Q{i}": list(families) for i in range(2, 7)}
    provided["Q4"] = []  # Conditions do not imply Q4 completion.
    module._set_available_status(report, provided)
    expected = "pending" if not families else "complete" if len(families) == 3 else "partial"
    assert report["questions"][1]["status"] == expected
    assert report["questions"][3]["status"] == "pending"
    assert f"{len(families)}/3" in report["questions"][1]["conclusion"]
    assert all(family in report["questions"][1]["conclusion"] for family in families)
    assert "計算中" not in json.dumps(report, ensure_ascii=False)
    assert report["status"] == "partial"  # No automatic acceptance or hold release.
    assert str(len(families)) in report["overview"][0]["value"]


def test_cli_exports_comparisons_and_rejects_remaining_root_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from scripts.export_pattern_scan_report import main

    q1, remaining, output = tmp_path / "q1", tmp_path / "remaining", tmp_path / "report/data"
    _fixture(q1, comparisons=True)
    remaining.mkdir()
    monkeypatch.setattr(sys, "argv", ["export", "--q1-root", str(q1), "--remaining-root", str(remaining), "--output", str(output), "--as-of", "2026-10-21"])
    assert main() == 0
    report = json.loads((output / "summary.js").read_text(encoding="utf-8").removeprefix("window.REPORT_DATA = ").rstrip(";\n"))
    assert len(report["comparisonSummary"]["rows"]) == 24
    assert report["audit"]["status"] == "unrecorded"
    assert all(question["status"] == "pending" for question in report["questions"][1:])
    with pytest.raises(ValueError, match="overlap original remaining"):
        export_q1_report_data(q1, remaining / "output", as_of="2026-10-21", remaining_root=remaining)


def test_split_scripts_reassemble_losslessly_in_javascript(tmp_path: Path) -> None:
    import shutil
    import subprocess

    from research_core.pattern_scan_report_v1 import split_report_scripts

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the browser's classic script protocol")
    report = {
        "status": "partial",
        "questions": [
            {"id": f"Q{i}", "tables": [{"rows": [{"text": '中文\\"\n</script>', "n": n, "missing": None} for n in range(100)]}, {"rows": []}]}
            for i in range(1, 7)
        ],
    }
    original = json.dumps(report, ensure_ascii=False)
    files = split_report_scripts(report, max_bytes=4000)
    assert split_report_scripts(report, max_bytes=4000) == files
    assert json.dumps(report, ensure_ascii=False) == original
    manifest = json.loads(files["scripts-manifest.json"])
    scripts = manifest["scripts"]
    assert scripts[0] == "summary.js" and len(scripts) > 2
    assert all(len(files[name]) < 4000 for name in scripts)
    program = tmp_path / "roundtrip.cjs"
    program.write_bytes(b"global.window = {};\n" + b"".join(files[name] for name in scripts) + b"process.stdout.write(JSON.stringify(window.REPORT_DATA));\n")
    result = subprocess.run([node, str(program)], check=True, capture_output=True)
    assert json.loads(result.stdout) == {**report, "dataScripts": scripts}


def test_split_scripts_reject_oversized_row_or_metadata() -> None:
    from research_core.pattern_scan_report_v1 import split_report_scripts

    with pytest.raises(ValueError, match="one report row"):
        split_report_scripts({"questions": [{"tables": [{"rows": [{"text": "中" * 1000}]}]}]}, max_bytes=1000)
    with pytest.raises(ValueError, match="metadata"):
        split_report_scripts({"questions": [], "title": "中" * 1000}, max_bytes=1000)


def test_split_publication_returns_ordered_manifest(tmp_path: Path) -> None:
    root = tmp_path / "q1"
    before = _fixture(root)
    output = tmp_path / "report/data"
    report = export_q1_report_data(root, output, as_of="2026-10-31", split_scripts=True, display_csv=True, data_prefix="data/final-v1")
    manifest = json.loads((output / "scripts-manifest.json").read_bytes())
    assert report["dataScripts"] == manifest["scripts"]
    assert all((output / name).stat().st_size < 500 * 1024 for name in manifest["scripts"])
    import csv

    table = report["questions"][0]["tables"][0]
    csv_download = table["downloads"][-1]
    assert csv_download["href"] == "data/final-v1/display/Q1-01.csv"
    with (output / "display/Q1-01.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(table["rows"])
    assert rows[0]["hit_rate"] == "" and rows[0]["loss_rate"] == "0.0"
    assert all(item["href"].startswith("data/final-v1/") for item in report["downloads"])
    for relative, (raw, mtime_ns) in before.items():
        assert (root / relative).read_bytes() == raw
        assert (root / relative).stat().st_mtime_ns == mtime_ns


def test_oversized_display_csv_is_deterministic_lossless_gzip() -> None:
    import gzip

    from research_core.pattern_scan_report_v1 import _display_downloads

    report: dict[str, Any] = {
        "questions": [
            {
                "id": "Q1",
                "tables": [
                    {"title": "large", "columns": [{"key": "text"}], "rows": [{"text": "x" * 600000}]},
                    {"title": "small", "columns": [{"key": "text"}], "rows": [{"text": "zero"}]},
                ],
            }
        ],
        "downloads": [],
    }
    files: dict[str, bytes] = {}
    _display_downloads(report, files)
    raw = b"\xef\xbb\xbftext\n" + b"x" * 600000 + b"\n"
    assert gzip.decompress(files["display/Q1-01.csv.gz"]) == raw
    assert files["display/Q1-01.csv.gz"] == gzip.compress(raw, mtime=0)
    assert files["display/Q1-02.csv"] == b"\xef\xbb\xbftext\nzero\n"
    assert "display/Q1-01.csv" not in files
    compressed = report["downloads"][0]
    assert compressed["href"] == "data/display/Q1-01.csv.gz"
    assert "CSV.gz" in compressed["label"]
    assert compressed["bytes"] == len(files["display/Q1-01.csv.gz"])
    assert compressed["sha256"] == hashlib.sha256(files["display/Q1-01.csv.gz"]).hexdigest()
