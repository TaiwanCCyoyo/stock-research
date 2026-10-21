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


def _fixture(root: Path) -> dict[str, tuple[bytes, int]]:
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
