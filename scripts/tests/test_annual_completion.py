import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core import annual_completion as completion
from research_core.annual_rotation_v2 import Entitlement


def fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex, list[dict[str, Any]], Any, dict[str, Any]]:
    dates = pd.DatetimeIndex(["2013-01-02", "2013-06-03", "2014-01-02", "2014-06-02", "2015-01-02", "2015-10-12"])
    raw = []
    for code, values in {
        "1234": [100, 105, 110, 110, 110, 110],
        "5678": [100, 100, 100, 110, 120, 120],
        "9012": [100, 100, 100, 100, 100, 130],
        "0050": [100] * 6,
    }.items():
        raw.append(pd.DataFrame({"Code": code, "Date": dates, "Open": values, "High": values, "Low": values, "Close": values, "Volume": 1.0}))
    prices = pd.concat(raw, ignore_index=True)
    actions = pd.DataFrame(columns=pd.Index(["code", "ex_date", "event_type", "price_factor", "cash_dividend_estimate"]))
    selections = [
        {"year": year, "code": code, "ranking_return": 2.0, "entry_date": start, "exit_date": end, "is_ytd": ytd, "v1_gross_return": 0.1, "v1_net_return": 0.09}
        for year, code, start, end, ytd in [
            (2013, "1234", "2013-01-02", "2014-01-02", False),
            (2014, "5678", "2014-01-02", "2015-01-02", False),
            (2015, "9012", "2015-01-02", "2015-10-12", True),
        ]
    ]
    admission = SimpleNamespace(entitlements=(), unavailable_by_code={}, audit=[], unresolved=[])
    params = {
        "study_id": "synthetic-fixed-sequence",
        "run_id": "synthetic-v2",
        "definition_version": "synthetic.v2",
        "commission": 0.01,
        "stock_sell_tax": 0.03,
        "etf_sell_tax": 0.01,
        "slippage": 0.01,
        "cutoff": "2015-10-12",
        "complete_through_year": 2014,
        "window_start_years": [2013],
        "bootstrap_resamples": 64,
        "preregistration": "preregistration.md",
    }
    return prices, actions, dates, selections, admission, params


def test_compounding_reuses_fixed_identity_and_continuous_benchmark_costs():
    prices, actions, dates, selections, admission, params = fixture()
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    window = result["windows"][0]
    stock_cost = 0.99 * 0.96 / (1.01 * 1.01)
    etf_cost = 0.99 * 0.98 / (1.01 * 1.01)
    assert window["scenarios"]["lapse"]["gross_terminal_multiple"] == pytest.approx(1.32)
    assert window["scenarios"]["lapse"]["net_terminal_multiple"] == pytest.approx(1.32 * stock_cost**2)
    assert window["benchmark"]["net_terminal_multiple"] == pytest.approx(etf_cost)
    assert result["rows"][0]["benchmark"]["net_return"] == pytest.approx(etf_cost - 1)
    assert window["scenarios"]["lapse"]["cagr"] == pytest.approx((1.32 * stock_cost**2) ** (365.2425 / 730) - 1)
    assert window["scenarios"]["lapse"]["paired_diagnostics"]["n_years"] == 2
    assert [row["code"] for row in result["rows"]] == ["1234", "5678", "9012"]
    assert result["execution"]["strategy_v2_calls"] == 3
    assert result["execution"]["scenario_reuses"] == 3
    assert result["execution"]["benchmark_calls"] == 4
    assert result["execution"]["v1_comparison_calls"] == 2
    assert all(row["common_multipliers_match"] for row in result["compatibility"])
    assert result["rows"][0]["v1"]["net_return"] == 0.09


@pytest.mark.parametrize("gate", ["unresolved", "nonadjacent", "missing_year"])
def test_incomplete_or_disconnected_sequence_never_multiplies_a_subset(gate: str):
    prices, actions, dates, selections, admission, params = fixture()
    if gate == "unresolved":
        admission.unresolved = [{"code": "5678", "year": 2014, "reasons": ["unresolved_source_terms"]}]
    elif gate == "nonadjacent":
        selections[1]["entry_date"] = "2014-06-02"
    else:
        selections.pop(1)
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    window = result["windows"][0]["scenarios"]["lapse"]
    assert window["complete"] is False
    assert window["gross_terminal_multiple"] is None
    assert window["net_terminal_multiple"] is None
    assert window["cagr"] is None
    assert window["max_drawdown"] is None
    assert window["paired_diagnostics"] is None
    assert window["reason"] in {"unresolved_fixed_holding", "nonadjacent_rotation_dates", "missing_fixed_holding_year"}


def test_rights_use_two_scenarios_and_one_benchmark_evaluation():
    prices, actions, dates, selections, admission, params = fixture()
    actions.loc[0] = ["1234", dates[1], "EX_RIGHT", 0.95, 0]
    admission.entitlements = (
        Entitlement(
            "1234", "2013-06-03", "2013-06-03", rights_per_old_share=0.2, subscription_price=30, evidence_ids=("source-1",), source_event_type="EX_RIGHT"
        ),
    )
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    row = result["rows"][0]
    assert row["realize"]["gross_return"] > row["lapse"]["gross_return"]
    assert result["windows"][0]["scenarios"]["realize"]["net_terminal_multiple"] > result["windows"][0]["scenarios"]["lapse"]["net_terminal_multiple"]
    assert result["execution"]["strategy_v2_calls"] == 4
    assert result["execution"]["benchmark_calls"] == 4
    assert result["execution"]["scenario_reuses"] == 2


def test_ytd_is_separate_and_raw_mark_vectors_are_not_serialized():
    prices, actions, dates, selections, admission, params = fixture()
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    ytd = result["rows"][-1]
    assert ytd["is_ytd"] is True
    assert ytd["lapse"]["gross_return"] == pytest.approx(0.3)
    assert "cagr" not in ytd["lapse"]
    assert result["windows"][0]["end_year"] == 2014
    serialized = json.dumps(result)
    for field in ('"marks"', "RawOpen", "RawClose", '"Open"', '"Close"'):
        assert field not in serialized


def test_carried_mark_reference_cannot_be_called_complete_daily_drawdown():
    prices, actions, dates, selections, admission, params = fixture()
    prices = prices.loc[~(prices.Code.eq("1234") & prices.Date.eq(dates[1]))]
    admission.unavailable_by_code = {"1234": {"2013-06-03": "H"}}
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    window = result["windows"][0]["scenarios"]["lapse"]
    assert window["complete"] is True
    assert window["complete_equity"] is False
    assert window["max_drawdown"] is None
    assert window["carried_mark_reference_drawdown"] is not None
    assert result["rows"][0]["lapse"]["carried_days"] == 1


def test_rotation_day_close_replaces_old_exit_open_in_drawdown():
    paths = [
        {"marks": [{"date": "2013-01-02", "net": 1.0}, {"date": "2014-01-02", "net": 2.0}], "net_multiplier": 2.0},
        {"marks": [{"date": "2014-01-02", "net": 0.8}, {"date": "2015-01-02", "net": 1.0}], "net_multiplier": 1.0},
    ]
    assert completion._chained_marks(paths) == [1.0, 1.0, 1.6, 2.0]


def report_text() -> str:
    return """## 固定單一領先股結果

| 持有年 | 所選代碼 | 前一年排名報酬 | 日期 | gross | net | 0050 net | 狀態 |
| 2013 | 1234 | +200.00% | 2013-01-02 → 2014-01-02 | +10.00% | +9.00% | 0.00% | 可計 |
| 2014 | 5678 | +200.00% | 2014-01-02 → 2015-01-02 | 未解決 | 未解決 | 0.00% | 未解決 |
| 2015 YTD | 9012 | +200.00% | 2015-01-02 → 2015-10-12 | +30.00% | +29.00% | 0.00% | 可計 |

## 下一節
"""


def test_original_report_parser_keeps_unknowns_and_fixed_dates():
    rows = completion.parse_fixed_selections(report_text())
    assert [row["code"] for row in rows] == ["1234", "5678", "9012"]
    assert rows[0]["ranking_return"] == 2
    assert rows[1]["v1_net_return"] is None
    assert rows[-1]["is_ytd"] is True
    assert rows[-1]["exit_date"] == "2015-10-12"


def test_cli_fingerprints_before_data_reads_and_formats_before_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prices, actions, dates, _, admission, params = fixture()
    producer = tmp_path / "producer"
    producer.mkdir()
    output = tmp_path / "publication"
    output.mkdir()
    (output / "preregistration.md").write_text("existing registered source", encoding="utf-8")
    params_path, report = tmp_path / "params.json", tmp_path / "report.md"
    params_path.write_text(json.dumps(params), encoding="utf-8")
    report.write_text(report_text(), encoding="utf-8")
    events = []
    specs_seen = []
    monkeypatch.setattr(completion, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(completion, "_require_committed_sources", lambda *_: None)
    monkeypatch.setattr(completion, "producer_data_root", lambda: producer)

    def fingerprint(specs: list[Any]) -> dict[str, Any]:
        events.append("fingerprint")
        specs_seen.extend(specs)
        return {"inputs": {}}

    def parquet(_path: Path, *, columns: list[str], **kwargs: Any) -> pd.DataFrame:
        assert events[0] == "fingerprint"
        events.append("parquet")
        if columns == ["Date", "Source"]:
            return pd.DataFrame({"Date": dates, "Source": "official"})
        assert kwargs["filters"] == [("Code", "in", ["0050", "1234", "5678", "9012"]), ("Source", "==", "official")]
        return prices.assign(Source="official")

    def format_outputs(paths: list[Path], _repo: Path) -> float:
        events.append("format")
        assert len(paths) == 3 and all(path.exists() for path in paths)
        return 0.1

    def receipt(path: Path, **kwargs: Any) -> None:
        assert events[-1] == "format"
        assert kwargs["inputs"] == {"inputs": {}}
        events.append("receipt")
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(completion, "fingerprint_inputs", fingerprint)
    monkeypatch.setattr(completion, "read_stable", lambda path, read: read(path))
    monkeypatch.setattr(completion.pd, "read_parquet", parquet)
    monkeypatch.setattr(completion, "readonly_sqlite", lambda _: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(completion.pd, "read_sql_query", lambda *_: actions.assign(source="official", market="TWSE"))
    monkeypatch.setattr(completion, "_format_outputs", format_outputs)
    monkeypatch.setattr(completion, "write_run_receipt", receipt)
    evidence = SimpleNamespace(manifest={"schema": "synthetic"}, retained_bytes=12, verification_seconds=0.01)
    monkeypatch.setitem(
        sys.modules,
        "research_core.annual_completion_evidence",
        SimpleNamespace(load_verified_evidence=lambda _: evidence, build_admission=lambda *_: admission),
    )
    assert completion.main(["--params", str(params_path), "--report", str(report), "--output", str(output)]) == 0
    assert events.count("fingerprint") == 1
    assert events.count("parquet") == 2
    assert events[-2:] == ["format", "receipt"]
    assert next(spec for spec in specs_seen if spec.name == "price_daily").date_column is None
    assert next(spec for spec in specs_seen if spec.name == "corporate_actions").tables == {"corporate_actions": "ex_date"}
    performance = json.loads((output / "performance.json").read_text(encoding="utf-8"))
    assert performance["input_copy_bytes"] == 0
    with pytest.raises(FileExistsError):
        completion.main(["--params", str(params_path), "--report", str(report), "--output", str(output)])
