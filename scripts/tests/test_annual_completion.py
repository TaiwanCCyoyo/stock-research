import hashlib
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core import annual_completion as completion
from research_core import annual_completion_publication as publication
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


def test_committed_source_gate_returns_detached_identity_and_pins_git_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    current: dict[str, Any] = {"commit": "a" * 40, "dirty": False}
    commands = []
    monkeypatch.setattr(completion, "code_identity", lambda _repo: current)

    def git(arguments: list[str], **_kwargs: Any) -> Any:
        commands.append(arguments)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(completion.subprocess, "run", git)
    captured = completion._require_committed_sources(tmp_path, [tmp_path / "runner.py"])
    assert commands[0][-1] == "a" * 40 + ":runner.py"
    current["commit"] = "b" * 40
    assert captured == {"commit": "a" * 40, "dirty": False}
    with pytest.raises(ValueError, match="source identity changed"):
        completion._require_code_identity(tmp_path, captured)


@pytest.mark.parametrize(
    "change",
    ["stable", "foreign_zip", "start_head", "formatter_dirty", "formatter_head", "receipt_code", "receipt_dirty", "post_receipt_head"],
)
@pytest.mark.parametrize("quotes", ["shared", "producer"])
def test_cli_fingerprints_then_formats_and_receipts_before_authoritative_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], change: str, quotes: str
):
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
    committed_checks: list[Path] = []
    starting_identity = {"commit": "a" * 40, "dirty": False}
    current_identity = dict(starting_identity)
    packed: list[Path] = []

    def committed_sources(_repo: Path, paths: list[Path]) -> dict[str, Any]:
        committed_checks.extend(paths)
        checked = dict(current_identity)
        if change == "start_head":
            current_identity["commit"] = "b" * 40  # another commit lands before the run takes its start identity
        return checked

    original_pack = completion.pack_publication

    def pack(root: Path) -> Path:
        packed.append(root)
        return original_pack(root)

    monkeypatch.setattr(completion, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(completion, "TASK", tmp_path)
    monkeypatch.setattr(publication, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(completion, "_require_committed_sources", committed_sources)
    monkeypatch.setattr(completion, "code_identity", lambda _repo, **_kwargs: dict(current_identity))
    monkeypatch.setattr(completion, "pack_publication", pack)
    monkeypatch.setattr(completion, "producer_data_root", lambda: producer)

    def fingerprint(specs: list[Any]) -> dict[str, Any]:
        events.append("fingerprint")
        specs_seen.extend(specs)
        return {"inputs": {}}

    shared_record = {"family": "adjusted-daily-v1", "generation": "g1", "file": "raw.parquet", "sha256": "1" * 64, "status_sha256": "2" * 64}

    def official_quotes(*, codes: list[str], as_of: pd.Timestamp) -> tuple[pd.DataFrame, pd.DatetimeIndex, dict[str, Any]]:
        assert events[0] == "fingerprint"
        events.append("shared_quotes")
        assert codes == ["0050", "1234", "5678", "9012"] and as_of == pd.Timestamp(params["cutoff"])
        return prices.copy(), pd.DatetimeIndex(dates), shared_record

    def parquet(_path: Path, *, columns: list[str], **kwargs: Any) -> pd.DataFrame:
        assert quotes == "producer", "the shared mode never scans price_daily.parquet"
        assert events[0] == "fingerprint"
        events.append("parquet")
        if columns == ["Date", "Source"]:
            return pd.DataFrame({"Date": dates, "Source": "official"})
        assert kwargs["filters"] == [("Code", "in", ["0050", "1234", "5678", "9012"]), ("Source", "==", "official")]
        return prices.assign(Source="official")

    def format_outputs(paths: list[Path], _repo: Path) -> float:
        events.append("format")
        assert len(paths) == 3 and all(path.exists() for path in paths)
        if change == "foreign_zip":
            (output / publication.ARCHIVE).write_bytes(b"foreign authoritative archive")
        elif change == "formatter_dirty":
            current_identity["dirty"] = True
        elif change == "formatter_head":
            current_identity["commit"] = "b" * 40
        return 0.1

    def receipt(path: Path, **kwargs: Any) -> dict[str, Any]:
        assert events[-1] == "format"
        assert kwargs["inputs"] == {"inputs": {}}
        assert kwargs["shared_data"] == ([shared_record] if quotes == "shared" else [])
        assert kwargs["expected_code"] == starting_identity, "drift during the run is recorded by the receipt"
        assert Path(completion.__file__) in kwargs["sources"] and report not in kwargs["sources"]
        listed = {Path(source).name for source in kwargs["sources"]}
        assert {"annual_rotation.py", "annual_rotation_v2.py", "annual_statistics.py", "price_basis.py"} <= listed, "every computing module is listed"
        events.append("receipt")
        identities = {}
        for key, result_path in kwargs["results"].items():
            raw = result_path.read_bytes()
            identities[key] = {"path": result_path.relative_to(tmp_path).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        receipt_code = dict(starting_identity)
        if change == "receipt_code":
            receipt_code["commit"] = "b" * 40
        elif change == "receipt_dirty":
            receipt_code["dirty"] = True
        saved = {"schema": "run-receipt.v1", "run_id": kwargs["run_id"], "results": identities, "code": receipt_code}
        path.write_text(json.dumps(saved), encoding="utf-8")
        if change == "post_receipt_head":
            current_identity["commit"] = "b" * 40
        return saved

    monkeypatch.setattr(completion, "fingerprint_inputs", fingerprint)
    monkeypatch.setattr(completion, "read_stable", lambda path, read: read(path))
    monkeypatch.setattr(completion.pd, "read_parquet", parquet)
    monkeypatch.setattr(completion, "read_official_quotes", official_quotes)
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
    arguments = ["--params", str(params_path), "--report", str(report), "--output", str(output), "--quotes", quotes]
    if change == "start_head":
        with pytest.raises(ValueError, match="while the run was starting"):
            completion.main(arguments)
        assert events == [] and packed == [], "refused before any computation"
        return
    # A commit, checkout or edit during the run is recorded in the receipt, never a reason to drop the result.
    published = {"stable", "formatter_dirty", "formatter_head", "post_receipt_head"}
    if change not in published | {"foreign_zip"}:
        with pytest.raises(ValueError, match="identity"):
            completion.main(arguments)
        assert packed == []
        assert not (output / publication.ARCHIVE).exists()
        assert events.count("receipt") == 1
        assert capsys.readouterr().out == ""
    elif change == "foreign_zip":
        with pytest.raises(FileExistsError):
            completion.main(arguments)
        assert (output / publication.ARCHIVE).read_bytes() == b"foreign authoritative archive"
        assert capsys.readouterr().out == ""
    else:
        assert completion.main(arguments) == 0
        loaded = publication.load_publication(output, repo_root=tmp_path)
        assert loaded["results.json"]["run_id"] == params["run_id"]
        summary = json.loads(capsys.readouterr().out)
        assert summary["packing_seconds"] >= 0
        assert summary["archive_bytes"] == (output / publication.ARCHIVE).stat().st_size
    if change in published | {"foreign_zip"}:
        assert packed == [output]
    assert events.count("fingerprint") == 1
    assert events.count("parquet") == (2 if quotes == "producer" else 0)
    assert events.count("shared_quotes") == (1 if quotes == "shared" else 0)
    assert events[-2:] == ["format", "receipt"]
    assert report in committed_checks
    price_specs = [spec for spec in specs_seen if spec.name == "price_daily"]
    assert [spec.date_column for spec in price_specs] == ([None] if quotes == "producer" else [])
    assert next(spec for spec in specs_seen if spec.name == "corporate_actions").tables == {"corporate_actions": "ex_date"}
    performance = json.loads((output / "performance.json").read_text(encoding="utf-8"))
    assert performance["input_copy_bytes"] == 0
    assert performance["quote_source"] == quotes and performance["market_calendar_scans"] == (1 if quotes == "producer" else 0)
    with pytest.raises(FileExistsError):
        completion.main(["--params", str(params_path), "--report", str(report), "--output", str(output)])


@pytest.mark.parametrize("event_date", ["2014-01-01", "2014-01-02"])
def test_cross_year_uncertainty_affects_the_held_position_through_its_exit(event_date: str):
    prices, actions, dates, selections, admission, params = fixture()
    selections[1]["code"] = "1234"
    admission.unresolved = [{"code": "1234", "year": 2014, "event_dates": [event_date], "reasons": ["unresolved_cross_year_event"]}]
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    assert result["rows"][0]["lapse"]["status"] == "unknown"
    assert result["rows"][1]["lapse"]["status"] == "modeled"


@pytest.mark.parametrize("event_date", ["2012-12-31", "2013-01-02", "2015-10-12"])
def test_event_outside_a_holding_or_on_its_entry_does_not_block_it(event_date: str):
    prices, actions, dates, selections, admission, params = fixture()
    admission.unresolved = [{"code": "1234", "year": 2013, "event_dates": [event_date], "reasons": ["outside_holding"]}]
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    assert result["rows"][0]["lapse"]["status"] == "modeled"


@pytest.mark.parametrize("event_dates", [None, [], ["not-a-date"]])
def test_missing_or_unusable_event_dates_block_same_issuer_without_guessing_year(event_dates: list[str] | None):
    prices, actions, dates, selections, admission, params = fixture()
    selections[1]["code"] = "1234"
    event: dict[str, Any] = {"code": "1234", "year": 1999, "reasons": ["economic_date_unknown"]}
    if event_dates is not None:
        event["event_dates"] = event_dates
    admission.unresolved = [event]
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    assert result["rows"][0]["lapse"]["status"] == "unknown"
    assert result["rows"][1]["lapse"]["status"] == "unknown"
    assert result["rows"][2]["lapse"]["status"] == "modeled"


def test_uncertain_effective_date_inside_holding_is_kept_when_original_date_precedes_entry():
    prices, actions, dates, selections, admission, params = fixture()
    admission.unresolved = [{"code": "1234", "year": 2012, "event_dates": ["2012-12-31", "2013-06-03"], "reasons": ["ownership_unresolved"]}]
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    assert result["rows"][0]["lapse"]["status"] == "unknown"


def test_old_zip_without_expanded_files_is_rejected_before_fingerprinting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output = tmp_path / "publication"
    output.mkdir()
    (output / completion.ARCHIVE).write_bytes(b"old immutable publication")
    (output / "preregistration.md").write_text("existing allowed source", encoding="utf-8")

    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail("existing archive must be rejected before source checks or fingerprinting")

    monkeypatch.setattr(completion, "fingerprint_inputs", forbidden)
    monkeypatch.setattr(completion, "_require_committed_sources", forbidden)
    with pytest.raises(FileExistsError):
        completion.main(["--output", str(output)])
    assert not any((output / name).exists() for name in completion.OUTPUT_NAMES)


def test_dangling_output_link_is_rejected_before_fingerprinting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output = tmp_path / "publication"
    output.mkdir()
    target = output / "results.json"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))

    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail("output links must be rejected before source checks or fingerprinting")

    monkeypatch.setattr(completion, "fingerprint_inputs", forbidden)
    monkeypatch.setattr(completion, "_require_committed_sources", forbidden)
    with pytest.raises(FileExistsError):
        completion.main(["--output", str(output)])


@pytest.mark.parametrize("endpoint", ["entry_date", "exit_date"])
@pytest.mark.parametrize("volume", [0.0, -1.0, None, math.nan, math.inf, "invalid"])
@pytest.mark.parametrize("code", ["1234", "0050"])
def test_fixed_strategy_and_benchmark_endpoints_require_positive_finite_volume(endpoint: str, volume: Any, code: str):
    prices, actions, dates, selections, admission, params = fixture()
    day = pd.Timestamp(str(selections[0][endpoint]))
    prices["Volume"] = prices.Volume.astype(object)
    prices.loc[prices.Code.eq(code) & prices.Date.eq(day), "Volume"] = volume
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    row = result["rows"][0]
    affected = row["benchmark"] if code == "0050" else row["lapse"]
    assert affected["status"] == "unknown"
    assert affected["gross_return"] is None
    assert affected["net_return"] is None
    assert any("endpoint_volume" in reason for reason in affected["reasons"])
    assert row["entry_date"] == selections[0]["entry_date"]
    assert row["exit_date"] == selections[0]["exit_date"]
    if code == "1234":
        assert row["realize"]["status"] == "unknown"
        assert row["benchmark"]["status"] == "modeled"
    else:
        assert row["lapse"]["status"] == "modeled"
        if endpoint == "entry_date":
            assert result["windows"][0]["benchmark"]["status"] == "unknown"


def test_missing_volume_column_keeps_all_fixed_trades_unknown_without_kernel_calls():
    prices, actions, dates, selections, admission, params = fixture()
    result = completion.complete_fixed_sequence(prices.drop(columns="Volume"), actions, dates, selections, admission, params)
    assert all(row[scenario]["status"] == "unknown" for row in result["rows"] for scenario in ("lapse", "realize", "benchmark"))
    assert result["execution"]["kernel_calls"] == 0
    assert result["windows"][0]["benchmark"]["status"] == "unknown"


def test_ytd_close_mark_also_requires_positive_volume():
    prices, actions, dates, selections, admission, params = fixture()
    day = pd.Timestamp(str(selections[-1]["exit_date"]))
    prices.loc[prices.Date.eq(day), "Volume"] = 0
    result = completion.complete_fixed_sequence(prices, actions, dates, selections, admission, params)
    assert result["rows"][-1]["lapse"]["status"] == "unknown"
    assert result["rows"][-1]["benchmark"]["status"] == "unknown"
    assert result["windows"][0]["scenarios"]["lapse"]["complete"] is True


@pytest.mark.parametrize("location", ["external", "different_task", "untracked_alternative", "traversal"])
def test_custom_report_paths_are_rejected_before_any_producer_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str):
    task = tmp_path / "tasks" / "canonical"
    task.mkdir(parents=True)
    (task / "report.md").write_text(report_text(), encoding="utf-8")
    if location == "external":
        report = tmp_path / "external.md"
    elif location == "different_task":
        report = tmp_path / "tasks" / "other" / "report.md"
    elif location == "untracked_alternative":
        report = task / "custom-selections.md"
    else:
        report = task / ".." / "canonical" / "report.md"
    if location != "traversal":
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(report_text(), encoding="utf-8")
    monkeypatch.setattr(completion, "TASK", task)
    monkeypatch.setattr(completion, "REPO_ROOT", tmp_path)

    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail("custom report must be rejected before source/data operations")

    monkeypatch.setattr(completion, "producer_data_root", forbidden)
    monkeypatch.setattr(completion, "fingerprint_inputs", forbidden)
    monkeypatch.setattr(completion, "_require_committed_sources", forbidden)
    with pytest.raises(ValueError, match="canonical task report|traversal forbidden"):
        completion.main(["--report", str(report), "--output", str(tmp_path / "output")])


def test_uncommitted_canonical_report_is_part_of_the_pre_read_source_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    task = tmp_path / "task"
    task.mkdir()
    report = task / "report.md"
    report.write_text(report_text(), encoding="utf-8")
    monkeypatch.setattr(completion, "TASK", task)
    monkeypatch.setattr(completion, "REPO_ROOT", tmp_path)

    def reject_uncommitted(_repo: Path, paths: list[Path]) -> None:
        assert report in paths
        raise ValueError("run source is not committed: report.md")

    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail("uncommitted report must be rejected before producer access")

    monkeypatch.setattr(completion, "_require_committed_sources", reject_uncommitted)
    monkeypatch.setattr(completion, "producer_data_root", forbidden)
    monkeypatch.setattr(completion, "fingerprint_inputs", forbidden)
    with pytest.raises(ValueError, match="source is not committed"):
        completion.main(["--report", str(report), "--output", str(tmp_path / "output")])


def test_output_outside_repository_is_rejected_before_fingerprinting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repository"
    repo.mkdir()
    monkeypatch.setattr(completion, "REPO_ROOT", repo)

    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail("external output must be rejected before source/data operations")

    monkeypatch.setattr(completion, "producer_data_root", forbidden)
    monkeypatch.setattr(completion, "fingerprint_inputs", forbidden)
    monkeypatch.setattr(completion, "_require_committed_sources", forbidden)
    with pytest.raises(ValueError, match="inside the repository"):
        completion.main(["--output", str(tmp_path / "outside")])
