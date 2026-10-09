"""Source-parity input and CLI tests, using synthetic tables only."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from research_core.jobs import file_digest
from scripts import validate_hhhl_v4_source as validator

SOURCES = Path(__file__).resolve().parents[2] / "tasks/20261010-hhhl-v4-probability/sources"


def synthetic_inputs(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database = root / "actions.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE corporate_actions(code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL, source TEXT, market TEXT)")
        connection.executemany(
            "INSERT INTO corporate_actions VALUES (?, ?, ?, ?, ?, ?)",
            [("1234", "2023-04-10", "cash_dividend", 0.9, "synthetic", "test"), ("5678", None, "unknown", None, "synthetic", "test")],
        )
    cases = [{"id": f"synthetic-{day}", "code": "1234", "date": f"2023-04-{day:02d}", "kind": "rule"} for day in range(1, 25)]
    examples = root / "examples.json"
    examples.write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setattr(validator, "CASE_SOURCE_HASH", file_digest(examples))
    inputs = root / "inputs"
    validator.freeze_inputs(database, examples, inputs)
    return inputs


def test_freeze_readonly_preserves_unknown_and_refuses_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = synthetic_inputs(tmp_path, monkeypatch)
    factors, cases, receipt = validator.read_inputs(inputs)
    assert len(factors) == 2
    assert factors.iloc[1].price_factor is None or pd.isna(factors.iloc[1].price_factor)
    assert len(cases) == 25 and cases[-1]["kind"] == "old_pressure"
    assert receipt["outcomes_read"] is False
    assert "mode=ro" in receipt["read_mode"]
    with sqlite3.connect(tmp_path / "actions.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM corporate_actions").fetchone()[0] == 2
    with pytest.raises(FileExistsError, match="already exists"):
        validator.freeze_inputs(tmp_path / "actions.sqlite", tmp_path / "examples.json", inputs)
    (inputs / "validation-cases.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        validator.read_inputs(inputs)


@pytest.fixture
def validation_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    inputs = synthetic_inputs(tmp_path, monkeypatch)
    dataset = tmp_path / "atlas"
    dataset.mkdir()
    tables = []
    for code in ("1234", "2527"):
        frame = pd.DataFrame({
            "asof_date": pd.date_range("2023-04-01", periods=30),
            "RawOpen": 100.0,
            "RawHigh": 101.0,
            "RawLow": 99.0,
            "RawClose": 100.0,
            "VolumeLots": 100.0,
            "atr14_pct": 0.01,
            "label_126": 1,
        })
        path = dataset / f"{code}.parquet"
        frame.to_parquet(path, index=False)
        tables.append({"security_id": f"TW:{code}", "path": path.name, "sha256": file_digest(path), "rows": len(frame)})
    (dataset / "manifest.json").write_text(json.dumps({"dataset_id": validator.DATASET_ID, "tables": tables}), encoding="utf-8")

    def verify_synthetic(root: Path) -> dict[str, str]:
        # Explicit test seam checks the actual fixture bytes and fixed ID;
        # production retains the full atlas manifest/identity verifier.
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["dataset_id"] == validator.DATASET_ID
        assert all(file_digest(root / entry["path"]) == entry["sha256"] for entry in manifest["tables"])
        return {"dataset_id": manifest["dataset_id"]}

    monkeypatch.setattr(validator, "verify_dataset", verify_synthetic)
    monkeypatch.setattr(validator, "FIXED_INPUT_SHA256", {name: file_digest(inputs / name) for name in validator.FIXED_INPUT_SHA256})

    def detect(frame: pd.DataFrame) -> list[dict[str, object]]:
        old = bool(frame.div_factor.eq(1).all())
        return [
            {
                "t": index,
                "pattern": True,
                "scale": "small_range" if old else "big_range",
                "bonus_levels": [{"age": "old", "level": 20.48}] if old else [],
                "restart": 0,
                "leg_start": 0,
            }
            for index in range(len(frame))
        ]

    monkeypatch.setattr(validator, "load_rule", lambda *_args: SimpleNamespace(detect=detect, source_hashes={"synthetic": "not-a-market-rule"}))
    return dataset, inputs


def test_validate_projects_only_inputs_and_tracks_both_case_types(validation_fixture: tuple[Path, Path]) -> None:
    dataset, inputs = validation_fixture
    read = pd.read_parquet
    with patch.object(validator.pd, "read_parquet", wraps=read) as spy:
        report = validator.validate(dataset, SOURCES, inputs)
    table_reads = [call for call in spy.call_args_list if Path(call.args[0]).parent == dataset]
    assert len(table_reads) == 2
    assert all(call.kwargs["columns"] == validator.RAW_COLUMNS for call in table_reads)
    assert report["passed"] and report["outcomes_read"] is False
    assert len(report["cases"]) == 25
    assert all(report["checks"].values())
    assert len(report["consumed_tables"]) == 2


@pytest.mark.parametrize("wrong_id", [False, True])
def test_dataset_rejected_before_rule_or_input_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong_id: bool) -> None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    def reject(_root: Path) -> dict[str, str]:
        if wrong_id:
            return {"dataset_id": "self-consistent-other-atlas"}
        raise ValueError("dataset_id identity mismatch")

    monkeypatch.setattr(validator, "verify_dataset", reject)
    with patch.object(validator, "load_rule") as rule, patch.object(validator, "read_inputs") as inputs, patch.object(validator.pd, "read_parquet") as prices:
        with pytest.raises(ValueError, match="fixed atlas|identity mismatch"):
            validator.validate(tmp_path, SOURCES, tmp_path)
    rule.assert_not_called()
    inputs.assert_not_called()
    prices.assert_not_called()


@pytest.mark.parametrize("member", ["validation-cases.json", "corporate_action_factors.parquet", "input-receipt.json"])
def test_self_signed_input_substitution_rejected(validation_fixture: tuple[Path, Path], member: str) -> None:
    dataset, inputs = validation_fixture
    receipt_path = inputs / "input-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    path = inputs / member
    if member == "corporate_action_factors.parquet":
        factors = pd.read_parquet(path)
        factors.loc[0, "price_factor"] = 0.8
        factors.to_parquet(path, index=False)
        receipt["factor_snapshot"]["sha256"] = file_digest(path)
    elif member == "validation-cases.json":
        cases = json.loads(path.read_text(encoding="utf-8"))
        cases[0]["id"] = "substituted"
        path.write_text(json.dumps(cases), encoding="utf-8")
        receipt["validation_cases"]["sha256"] = file_digest(path)
    else:
        receipt["scope"] = "substituted"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="unauthorized fixed input"):
        validator.validate(dataset, SOURCES, inputs)


@pytest.mark.parametrize("mutation", ["manifest", "table", "receipt"])
def test_mutation_during_case_evaluation_rejected(validation_fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    dataset, inputs = validation_fixture
    original_rule = validator.load_rule(SOURCES, validator.RULE_ID)

    def detect(frame: pd.DataFrame) -> list[dict[str, Any]]:
        result = original_rule.detect(frame)
        if mutation == "manifest":
            with (dataset / "manifest.json").open("a", encoding="utf-8") as stream:
                stream.write("\n")
        elif mutation == "receipt":
            with (inputs / "input-receipt.json").open("a", encoding="utf-8") as stream:
                stream.write("\n")
        else:
            path = dataset / "1234.parquet"
            table = pd.read_parquet(path)
            table["RawClose"] += 1
            table.to_parquet(path, index=False)
        return result

    monkeypatch.setattr(validator, "load_rule", lambda *_args: SimpleNamespace(detect=detect, source_hashes={}))
    if mutation == "receipt":
        with pytest.raises(ValueError, match="unauthorized fixed input"):
            validator.validate(dataset, SOURCES, inputs)
    else:
        report = validator.validate(dataset, SOURCES, inputs)
        assert not report["passed"]
        check = "atlas_manifest_unchanged" if mutation == "manifest" else "consumed_tables_unchanged"
        assert not report["checks"][check]


def test_cli_missing_source_is_execution_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        validator.main([
            "--inputs",
            str(tmp_path / "new-inputs"),
            "--freeze-actions",
            str(tmp_path / "missing.sqlite"),
            "--examples",
            str(tmp_path / "missing.json"),
        ])
        == 1
    )
    assert json.loads(capsys.readouterr().out)["passed"] is False
