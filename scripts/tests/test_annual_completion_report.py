import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from research_core.annual_completion_report import main, render_report


def test_saved_report_renderer_preserves_unknowns_scenarios_and_safe_embedded_data(tmp_path: Path):
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
    original = deepcopy(result)
    output = render_report(result, receipt=companion, audit=companion, performance=companion, presentation_date="2026-10-16")
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
    pinned_output = render_report(result, receipt=companion, audit=companion, performance=companion, presentation_date="2026-10-16", publication_ref=commit_ref)
    assert f"/blob/{commit_ref}/tasks/" in pinned_output
    assert "/blob/main/" not in pinned_output
    for invalid_ref in ("feature/report", "../main", "short", 'main" onclick="alert(1)'):
        with pytest.raises(ValueError, match="publication_ref must"):
            render_report(result, receipt=companion, audit=companion, performance=companion, presentation_date="2026-10-16", publication_ref=invalid_ref)
    assert "無成交" not in output
    assert "-12.50%" in output and "完整每日最大回撤" in output
    assert output.count('data-label="v1 原扣成本後">未知') == 2
    assert output.count('data-label="策略扣成本後">未知') == 1
    assert 'type="radio" name="scenario" id="realize"' in output
    assert 'href="v1.html"' in output
    assert "@import" not in output and 'src="' not in output and 'rel="stylesheet"' not in output
    embedded = output.split('id="report-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(embedded) == result
    assert len(output.encode("utf-8")) < 500 * 1024

    publication = tmp_path / "publication"
    publication.mkdir()
    identities: dict[str, dict[str, str | int]] = {}
    receipt = {**companion, "schema": "run-receipt.v1", "results": identities}
    for key, name, value in (
        ("results", "results.json", result),
        ("admission", "admission-audit.json", companion),
        ("performance", "performance.json", companion),
    ):
        raw = json.dumps(value).encode("utf-8")
        (publication / name).write_bytes(raw)
        identities[key] = {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (publication / "run-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
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
        render_report(result, receipt={"run_id": "other"}, audit=companion, performance=companion, presentation_date="2026-10-16")
