"""Synthetic compatibility checks; no actual 25-case or market reads."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts import validate_hhhl_cache_compatibility as validator


@pytest.fixture(autouse=True)
def private_fault_injection_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only private synthetic tests bypass the public fresh-worker boundary."""
    monkeypatch.setattr(validator.cache_execution, "require_loaded", lambda paths: None)


def bars(periods: int = 40) -> pd.DataFrame:
    return pd.DataFrame({
        "Code": "1234",
        "Date": pd.date_range("2020-01-01", periods=periods),
        "Open": 100.0,
        "High": 101.0,
        "Low": 99.0,
        "Close": 100.0,
        "Volume": 100.0,
    })


def factors(rows: tuple | list = ()) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=pd.Index(validator.ACTION_COLUMNS))


def test_verified_legacy_ast_uses_supplied_factors_and_first_day_record() -> None:
    raw = bars(20)
    raw.loc[4, "Close"] = np.nan
    actions = factors([
        ("1234", "2020-01-10", "CASH_DIVIDEND", 0.8),
        ("1234", "2020-01-10", "ETF_SPLIT", 0.5),
        ("1234", "2020-01-16", "ETF_SPLIT", 0.5),
        ("1234", "2020-02-01", "ETF_SPLIT", 0.5),
        ("9999", "2020-01-02", "ETF_SPLIT", 0.1),
    ])
    original = raw.copy(deep=True)
    legacy = validator.legacy_prices(raw, actions, "1234", "2020-01-20")
    assert len(legacy) == 19
    assert legacy.div_factor.tolist() == [0.4] * 8 + [0.5] * 6 + [1.0] * 5
    assert legacy.Close.tolist() == [40.0] * 8 + [50.0] * 6 + [100.0] * 5
    assert legacy.atr14_pct.iloc[:13].isna().all()
    assert legacy.atr14_pct.iloc[13:].notna().all()
    pd.testing.assert_frame_equal(raw, original)


def test_quality_gap_restarts_detector_and_preserves_calendar_event_dates() -> None:
    raw = bars(8).rename(columns={"Date": "asof_date"})
    raw["Quality"] = [True, True, True, False, True, True, True, True]
    lengths = []

    def detector(frame: pd.DataFrame) -> list[dict[str, Any]]:
        lengths.append(len(frame))
        return [{"t": len(frame) - 1, "pattern": True, "cat": "range", "scale": "big_range", "blocking": [], "bonus_levels": [], "hz_top": 100.0, "restart": 0}]

    events = validator.dated_events(raw, detector, reset_gaps=True)
    assert lengths == [3, 4]
    assert set(events) == {"2020-01-03", "2020-01-08"}
    assert events["2020-01-08"]["restart_date"] == "2020-01-05"


def test_synthetic_input_receipt_projects_raw_only_and_exposes_gap_difference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = bars()
    raw.loc[20, ["Open", "High", "Low", "Close"]] = np.nan
    raw["label_126"] = "MUST NEVER BE PROJECTED"
    raw.to_parquet(tmp_path / "prices.parquet", index=False)
    factors().to_parquet(tmp_path / "actions.parquet", index=False)
    (tmp_path / "calendar.json").write_text(json.dumps({"basis": "synthetic", "dates": raw.Date.dt.strftime("%Y-%m-%d").tolist()}), encoding="utf-8")
    (tmp_path / "cases.json").write_text(json.dumps([{"id": "synthetic", "code": "1234", "date": "2020-02-09", "kind": "rule"}]), encoding="utf-8")
    original_read = pd.read_parquet
    reads = []

    def projected_read(path: Path, *, columns: list[str]) -> pd.DataFrame:
        reads.append((Path(path).name, columns))
        assert "label_126" not in columns
        return original_read(path, columns=columns)

    monkeypatch.setattr(validator.pd, "read_parquet", projected_read)
    report = validator._validate_in_process(inputs=tmp_path, cutoff="2020-02-09")
    assert reads == [("prices.parquet", validator.RAW_COLUMNS), ("actions.parquet", validator.ACTION_COLUMNS)]
    assert report["no_forward_outcomes_read"] is True
    assert set(report["input_sha256"]) == {"prices.parquet", "actions.parquet", "calendar.json", "cases.json"}
    assert "adjprice.py" in report["source_sha256"]
    symbol = report["symbols"][0]
    assert symbol["legacy_rows"] == 39 and symbol["new_rows"] == 40
    assert symbol["quality_gaps"] == [{"date": "2020-01-21", "reason": "invalid_ohlc"}]
    assert symbol["price_differences"]["atr14_pct"]["changed_rows"] >= 13
    json.dumps(report, allow_nan=False)


def test_expectations_preserve_pattern_empty_bonus_and_old_pressure_tolerance() -> None:
    rule = {"kind": "rule"}
    old = {"kind": "old_pressure"}
    event = {"pattern": True, "scale": "small_range", "bonus_levels": [{"age": "old", "level": 20.483011145774455}]}
    assert validator.expectation(old, event)
    assert not validator.expectation(rule, event)
    assert validator.expectation(rule, {**event, "bonus_levels": []})
    assert not validator.expectation(old, {**event, "scale": "big_range"})
    assert not validator.expectation(old, {**event, "bonus_levels": [{"age": "old", "level": 20.54}]})
    assert not validator.expectation(rule, None)


def test_cases_with_forward_outcome_fields_are_rejected_before_table_read(tmp_path: Path) -> None:
    for name in ("prices.parquet", "actions.parquet", "calendar.json"):
        (tmp_path / name).write_bytes(b"never read")
    (tmp_path / "cases.json").write_text(json.dumps([{"id": "x", "code": "1234", "date": "2020-01-01", "kind": "rule", "label_126": 1}]), encoding="utf-8")
    with pytest.raises(ValueError, match="no forward outcomes"):
        validator._validate_in_process(inputs=tmp_path, cutoff="2020-01-01")


def synthetic_inventory_inputs(directory: Path) -> list[dict[str, str]]:
    """Build a synthetic 24-rule/one-pressure inventory, never read owner cases."""
    dates = pd.date_range("2023-03-01", periods=40)
    frames = []
    for code in ("1234", "2527", "9999"):
        raw = bars(40)
        raw["Code"], raw["Date"] = code, dates
        frames.append(raw)
    pd.concat(frames, ignore_index=True).to_parquet(directory / "prices.parquet", index=False)
    factors().to_parquet(directory / "actions.parquet", index=False)
    (directory / "calendar.json").write_text(json.dumps({"basis": "synthetic", "dates": [validator.iso_day(day) for day in dates]}), encoding="utf-8")
    cases = [{"id": f"synthetic-{i}", "code": "1234", "date": validator.iso_day(day), "kind": "rule"} for i, day in enumerate(dates[:24])]
    cases.append({"id": "synthetic-pressure", "code": "2527", "date": "2023-04-07", "kind": "old_pressure"})
    return cases


def synthetic_legacy(raw: pd.DataFrame, actions: pd.DataFrame, code: str, cutoff: str, *, adjprice_text: str) -> pd.DataFrame:
    """Only adapt synthetic prices; expectations are separately forced to pass."""
    result = raw.copy().rename(columns={"Date": "asof_date", "Volume": "VolumeLots"})
    result["RawClose"] = result["Close"]
    result["atr14_pct"] = 0.02
    return result


@pytest.mark.parametrize("changed_field", ["id", "date", "code", "kind"])
def test_alternative_25_case_inventory_cannot_claim_original_even_when_all_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_field: str) -> None:
    cases = synthetic_inventory_inputs(tmp_path)
    original_bytes = json.dumps(cases).encode()
    # A synthetic registered identity exercises success and rejection without
    # loading, reconstructing or weakening the production original inventory.
    monkeypatch.setattr(validator, "ORIGINAL_CASES_SHA256", hashlib.sha256(original_bytes).hexdigest())
    monkeypatch.setattr(validator, "_legacy_prices_from_source", synthetic_legacy)
    monkeypatch.setattr(validator, "expectation", lambda case, event: True)
    cases_path = tmp_path / "cases.json"
    cases_path.write_bytes(original_bytes)
    original_report = validator._validate_in_process(inputs=tmp_path, cutoff="2023-04-09")
    assert original_report["checks"]["original_25_case_inventory"]
    assert original_report["legacy_passed"] and original_report["new_all_expected"]
    if changed_field == "kind":
        cases[0]["kind"], cases[-1]["kind"] = "old_pressure", "rule"
    else:
        cases[0][changed_field] = {"id": "replacement-id", "date": "2023-03-25", "code": "9999"}[changed_field]
    cases_path.write_bytes(json.dumps(cases).encode())
    report = validator._validate_in_process(inputs=tmp_path, cutoff="2023-04-09")
    assert report["checks"]["legacy_all_expected"]
    assert all(row["legacy_pass"] and row["new_pass"] for row in report["cases"])
    assert not report["checks"]["original_25_case_inventory"]
    assert not report["legacy_passed"] and not report["new_all_expected"]
    assert report["input_sha256"]["cases.json"] == hashlib.sha256(cases_path.read_bytes()).hexdigest()


def test_cases_bytes_changed_after_capture_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = synthetic_inventory_inputs(tmp_path)
    cases_path = tmp_path / "cases.json"
    cases_path.write_bytes(json.dumps(cases).encode())
    monkeypatch.setattr(validator, "_legacy_prices_from_source", synthetic_legacy)
    original_expectation = validator.expectation
    changed = False

    def mutate_cases(case: dict[str, Any], event: dict[str, Any] | None) -> bool:
        nonlocal changed
        if not changed:
            changed = True
            cases[0]["id"] = "changed-after-capture"
            cases_path.write_bytes(json.dumps(cases).encode())
        return original_expectation(case, event)

    monkeypatch.setattr(validator, "expectation", mutate_cases)
    with pytest.raises(ValueError, match="compatibility inputs changed"):
        validator._validate_in_process(inputs=tmp_path, cutoff="2023-04-09")
    assert changed


def test_validation_executes_one_captured_source_mapping_for_all_symbols(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synthetic_inventory_inputs(tmp_path)
    cases = [{"id": f"captured-{code}", "code": code, "date": "2023-04-09", "kind": "rule"} for code in ("1234", "2527")]
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    texts = {
        "detect.py": "def pivots_atr(frame):\n    return []\n",
        "hhhl_rule_v4.py": (
            "def detect(frame):\n"
            "    return [{'t': len(frame)-1, 'pattern': True, 'scale': 'big_range', 'cat': 'range', "
            "'blocking': [], 'bonus_levels': [], 'hz_top': 111.0, 'restart': 0}]\n"
        ),
        "adjprice.py": (
            "def load(code):\n"
            "    frame = pd.read_parquet(TABLES / f'{code}.parquet', "
            "columns=['asof_date', 'RawOpen', 'RawHigh', 'RawLow', 'RawClose', 'VolumeLots'])\n"
            "    frame = frame.rename(columns={'RawOpen': 'Open', 'RawHigh': 'High', 'RawLow': 'Low'})\n"
            "    frame['Close'] = frame['RawClose'] + 1.0\n"
            "    frame['atr14_pct'] = 0.02\n"
            "    return frame\n"
        ),
    }
    changed_texts = {name: text.replace("111.0", "222.0").replace("+ 1.0", "+ 9.0") for name, text in texts.items()}
    reads = 0

    def changing_verified_sources(version: str) -> dict[str, str]:
        nonlocal reads
        reads += 1
        assert version == "v4"
        return texts.copy() if reads == 1 else changed_texts.copy()

    monkeypatch.setattr(validator.source, "verify_sources", changing_verified_sources)
    report = validator._validate_in_process(inputs=tmp_path, cutoff="2023-04-09")

    assert reads == 1
    assert len(report["symbols"]) == 2
    assert report["source_sha256"] == {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in texts.items()}
    for symbol in report["symbols"]:
        assert symbol["price_differences"]["Close"]["max_absolute_difference"] == 1.0
    for case in report["cases"]:
        for event in (case["legacy_event"], case["new_event"]):
            assert event is not None
            assert event["hz_top"] == 111.0


def test_scratch_registry_and_archive_changes_cannot_mix_captured_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    cases = synthetic_inventory_inputs(inputs)
    (inputs / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    expected_texts = validator.source.verify_sources("v4")
    scratch_sources = tmp_path / "sources"
    (scratch_sources / "v4").mkdir(parents=True)
    shutil.copyfile(validator.source.ROOT / "sources.json", scratch_sources / "sources.json")
    shutil.copyfile(validator.source.ROOT / "v4/sources.zip", scratch_sources / "v4/sources.zip")
    monkeypatch.setattr(validator.source, "ROOT", scratch_sources)
    original_legacy = validator._legacy_prices_from_source
    captured_adapters: list[str] = []

    def mutate_source_on_first_symbol(
        raw: pd.DataFrame,
        actions: pd.DataFrame,
        code: str,
        cutoff: str,
        *,
        adjprice_text: str,
    ) -> pd.DataFrame:
        captured_adapters.append(adjprice_text)
        if len(captured_adapters) == 1:
            (scratch_sources / "sources.json").write_bytes(b"replaced registry")
            (scratch_sources / "v4/sources.zip").write_bytes(b"replaced archive")
        return original_legacy(raw, actions, code, cutoff, adjprice_text=adjprice_text)

    monkeypatch.setattr(validator, "_legacy_prices_from_source", mutate_source_on_first_symbol)
    report = validator._validate_in_process(inputs=inputs, cutoff="2023-04-09")

    assert len(report["symbols"]) == 2
    assert captured_adapters == [expected_texts["adjprice.py"]] * 2
    assert report["source_sha256"] == {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in expected_texts.items()}
    assert (scratch_sources / "sources.json").read_bytes() == b"replaced registry"
    assert (scratch_sources / "v4/sources.zip").read_bytes() == b"replaced archive"
