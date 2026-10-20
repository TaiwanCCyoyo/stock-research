import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from research_core import annual_completion_publication as publication_store
from research_core import annual_completion_report as report
from research_core.annual_completion_report import main, render_report


def _write_publication(root: Path, result: dict, companion: dict) -> None:
    root.mkdir(parents=True)
    identities: dict[str, dict[str, str | int]] = {}
    receipt = {**companion, "schema": publication_store.MEMBER_SCHEMAS["run-receipt.json"], "results": identities}
    for key, name, value in (
        ("results", "results.json", result),
        ("admission", "admission-audit.json", {**companion, "schema": publication_store.MEMBER_SCHEMAS["admission-audit.json"], "unresolved": []}),
        ("performance", "performance.json", {**companion, "schema": publication_store.MEMBER_SCHEMAS["performance.json"]}),
    ):
        raw = json.dumps(value).encode("utf-8")
        (root / name).write_bytes(raw)
        relative_path = (root / name).relative_to(publication_store.REPO_ROOT).as_posix()
        identities[key] = {"path": relative_path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (root / "run-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


@pytest.mark.parametrize("role", ["receipt", "audit", "performance"])
@pytest.mark.parametrize("damage", ["swapped_same_run", "missing_schema", "wrong_schema"])
def test_renderer_rejects_wrong_companion_schemas(role: str, damage: str):
    companions: dict[str, Any] = {
        "receipt": {"schema": "run-receipt.v1", "run_id": "same-run"},
        "audit": {"schema": "annual-completion-admission.v2", "run_id": "same-run", "unresolved": []},
        "performance": {"schema": "annual-completion-performance.v2", "run_id": "same-run"},
    }
    if damage == "swapped_same_run":
        other = {"receipt": "audit", "audit": "performance", "performance": "receipt"}[role]
        companions[role] = dict(companions[other])
    elif damage == "missing_schema":
        companions[role].pop("schema")
    else:
        companions[role]["schema"] = "unrelated.v1"
    result = {"schema": "annual-completion-result.v2", "run_id": "same-run"}
    with pytest.raises(ValueError, match="expected .* schema"):
        render_report(result, **companions, presentation_date="2026-10-16")


@pytest.mark.parametrize("invalid", [None, {}, "", (), 0, False, "missing"])
def test_renderer_requires_explicit_unresolved_list(invalid: Any):
    audit = {"schema": "annual-completion-admission.v2", "run_id": "same-run"}
    if invalid != "missing":
        audit["unresolved"] = invalid
    with pytest.raises(ValueError, match="unresolved must be an explicit list"):
        render_report(
            {"schema": "annual-completion-result.v2", "run_id": "same-run"},
            receipt={"schema": "run-receipt.v1", "run_id": "same-run"},
            audit=audit,
            performance={"schema": "annual-completion-performance.v2", "run_id": "same-run"},
            presentation_date="2026-10-16",
        )


def test_saved_report_renderer_preserves_unknowns_scenarios_and_safe_embedded_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    modeled = {
        "status": "modeled",
        "gross_return": 0.25,
        "net_return": 0.21,
        "complete_equity": False,
        "carried_days": 2,
        "reasons": [],
    }
    unknown = {**modeled, "status": "unknown", "gross_return": None, "net_return": None, "reasons": ["unresolved_fixed_holding"]}
    scenario = {
        "complete": True,
        "gross_terminal_multiple": 1.25,
        "net_terminal_multiple": 1.21,
        "cagr": 0.21,
        "complete_equity": False,
        "max_drawdown": None,
        "carried_mark_reference_drawdown": -0.125,
        "paired_diagnostics": None,
        "reason": None,
    }
    result = {
        "schema": "annual-completion-result.v2",
        "run_id": "synthetic-report",
        "study_id": "20261013-annual-winner-rotation",
        "definition": "synthetic.v2",
        "selection_scope": "fixed-v1 <script>unsafe</script>",
        "cutoff": "2026-10-12",
        "windows": [
            {
                "id": "2013-2025",
                "start_date": "2013-01-02",
                "end_date": "2026-01-02",
                "scenarios": {"lapse": scenario, "realize": {**scenario, "net_terminal_multiple": 1.37}},
                "benchmark": {"gross_terminal_multiple": 1.1, "net_terminal_multiple": 1.09, "cagr": 0.02},
            }
        ],
        "rows": [
            {
                "year": 2013,
                "code": "1234",
                "entry_date": "2013-01-02",
                "exit_date": "2014-01-02",
                "is_ytd": False,
                "ranking_return": 1.5,
                "v1": {"gross_return": None, "net_return": None},
                "lapse": modeled,
                "realize": unknown,
                "benchmark": modeled,
            },
            {
                "year": 2026,
                "code": "5678",
                "entry_date": "2026-01-02",
                "exit_date": "2026-10-12",
                "is_ytd": True,
                "ranking_return": 1.2,
                "v1": {"gross_return": 0.23, "net_return": 0.19},
                "lapse": modeled,
                "realize": modeled,
                "benchmark": modeled,
            },
        ],
    }
    companion = {"run_id": result["run_id"], "parameters": {"commission": 0.001425}, "input_fingerprint": {"path": "PRIVATE-DO-NOT-EMBED"}}
    receipt_data = {**companion, "schema": publication_store.MEMBER_SCHEMAS["run-receipt.json"]}
    audit_data = {**companion, "schema": publication_store.MEMBER_SCHEMAS["admission-audit.json"], "unresolved": []}
    performance_data = {**companion, "schema": publication_store.MEMBER_SCHEMAS["performance.json"]}
    original = deepcopy(result)
    output = render_report(result, receipt=receipt_data, audit=audit_data, performance=performance_data, presentation_date="2026-10-16")
    assert result == original
    assert "<script>unsafe</script>" not in output
    assert "PRIVATE-DO-NOT-EMBED" not in output
    assert "0.1425%" in output
    assert "1.2100 倍" in output and "1.3700 倍" in output
    assert "+21.00%" in output and "+37.00%" in output and "+9.00%" in output
    publication_prefix = "https://github.com/TaiwanCCyoyo/stock-research/blob/main/tasks/20261013-annual-winner-rotation/publications/completion-v2/"
    assert f'href="{publication_prefix}storage-audit.md"' in output
    assert f'href="{publication_prefix}report.md"' in output
    assert f'href="{publication_prefix}publication.zip"' in output
    assert 'href="' + publication_prefix + 'run-receipt.json"' not in output
    assert 'href="' + publication_prefix + 'admission-audit.json"' not in output
    assert "../publications" not in output
    commit_ref = "a" * 40
    pinned_output = render_report(
        result, receipt=receipt_data, audit=audit_data, performance=performance_data, presentation_date="2026-10-16", publication_ref=commit_ref
    )
    assert f"/blob/{commit_ref}/tasks/" in pinned_output
    assert "/blob/main/" not in pinned_output
    for invalid_ref in ("feature/report", "../main", "short", 'main" onclick="alert(1)'):
        with pytest.raises(ValueError, match="publication_ref must"):
            render_report(
                result, receipt=receipt_data, audit=audit_data, performance=performance_data, presentation_date="2026-10-16", publication_ref=invalid_ref
            )
    assert "無成交" not in output
    assert "-12.50%" in output and "完整每日最大回撤" in output
    assert output.count('data-label="v1 原扣成本後">未知') == 2
    assert output.count('data-label="策略扣成本後">未知') == 1
    assert 'type="radio" name="scenario" id="realize"' in output
    assert 'href="v1.html"' in output
    assert "@import" not in output and 'src="' not in output and 'rel="stylesheet"' not in output
    kit_css = (report.KIT / "report-kit.css").read_text(encoding="utf-8")
    font_import = next(line for line in kit_css.splitlines() if line.startswith("@import"))
    assert font_import.count(";") > 1
    assert kit_css.replace(font_import, "") in output
    assert "--gain: #c84c50;" in output and "--paper: #f5f7f4;" in output
    assert "fonts.googleapis.com" not in output and "wght@400;500" not in output
    embedded = output.split('id="report-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(embedded) == result
    assert len(output.encode("utf-8")) < 500 * 1024

    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(publication_store, "REPO_ROOT", tmp_path)
    publication = tmp_path / report.DEFAULT_PUBLICATION_PATH
    _write_publication(publication, result, companion)
    index = tmp_path / "index.html"
    index.write_text("original-report", encoding="utf-8")
    with pytest.raises(ValueError, match="preserve the original"):
        main(["--publication", str(publication), "--output", str(index), "--date", "2026-10-16"])
    assert index.read_text(encoding="utf-8") == "original-report"
    (tmp_path / "v1.html").write_text("original-report", encoding="utf-8")
    assert main(["--publication", str(publication), "--output", str(index), "--date", "2026-10-16", "--publication-ref", commit_ref]) == 0
    assert index.read_text(encoding="utf-8") == pinned_output
    assert (tmp_path / "v1.html").read_text(encoding="utf-8") == "original-report"
    with pytest.raises(ValueError, match="run_id mismatch"):
        render_report(
            result,
            receipt={**receipt_data, "run_id": "other"},
            audit=audit_data,
            performance=performance_data,
            presentation_date="2026-10-16",
        )

    next_result: dict[str, Any] = deepcopy(result)
    next_result["run_id"] = "synthetic-report-v3"
    next_result["windows"][0]["scenarios"]["lapse"]["net_terminal_multiple"] = 1.52
    next_result["rows"][0]["lapse"]["net_return"] = 0.52
    next_companion = {**companion, "run_id": next_result["run_id"]}
    next_publication = publication.with_name("completion-v3")
    _write_publication(next_publication, next_result, next_companion)
    assert (
        main([
            "--publication",
            str(next_publication),
            "--output",
            str(index),
            "--date",
            "2026-10-16",
            "--publication-ref",
            commit_ref,
        ])
        == 0
    )
    next_output = index.read_text(encoding="utf-8")
    next_embedded = next_output.split('id="report-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(next_embedded) == next_result
    assert "1.5200 倍" in next_output and "+52.00%" in next_output
    next_prefix = publication_prefix.replace("/main/", f"/{commit_ref}/").replace("completion-v2", "completion-v3")
    for name in ("results.json", "publication.zip", "report.md"):
        assert f'href="{next_prefix}{name}"' in next_output
    assert "completion-v2" not in next_output
    assert 'href="v1.html"' in next_output
    assert (tmp_path / "v1.html").read_text(encoding="utf-8") == "original-report"

    for invalid_path in (
        "../completion-v3",
        "https://example.com/publication",
        "tasks/other/publications/completion-v3/extra",
        "tasks/other/publications/completion-v3",
        "tasks/other/publications/completion.v3",
    ):
        with pytest.raises(ValueError):
            render_report(
                result,
                receipt=receipt_data,
                audit=audit_data,
                performance=performance_data,
                presentation_date="2026-10-16",
                publication_path=invalid_path,
            )
    for invalid_source in (tmp_path.parent / "outside-publication", tmp_path / "wrong-layer"):
        with pytest.raises(ValueError, match="repository root|publication_path"):
            main(["--publication", str(invalid_source), "--output", str(index)])
    assert index.read_text(encoding="utf-8") == next_output
