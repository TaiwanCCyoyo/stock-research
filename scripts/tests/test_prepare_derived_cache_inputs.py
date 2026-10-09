"""Small functional raw-input snapshot regression; no market outcomes."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts import prepare_derived_cache_inputs as input_module
from scripts.prepare_derived_cache_inputs import prepare_inputs


def test_snapshot_reads_only_raw_columns_and_preserves_sources(tmp_path: Path):
    tables = tmp_path / "tables"
    tables.mkdir()
    frame = pd.DataFrame({
        "asof_date": pd.date_range("2020-01-01", periods=3),
        "RawOpen": [10.0, 11.0, 12.0],
        "RawHigh": [11.0, 12.0, 13.0],
        "RawLow": [9.0, 10.0, 11.0],
        "RawClose": [10.0, 11.0, 12.0],
        "VolumeLots": 100,
        "label_126": "must_not_be_read",
    })
    frame.to_parquet(tables / "2330.parquet", index=False)
    actions = tmp_path / "actions.parquet"
    pd.DataFrame(columns=pd.Index(["code", "ex_date", "event_type", "price_factor"])).to_parquet(actions)
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"code": "2330"}]), encoding="utf-8")
    original_cases = cases.read_bytes()
    original_actions = actions.read_bytes()
    expected_cases_hash = hashlib.sha256(original_cases).hexdigest()
    result = prepare_inputs(tables=tables, actions=actions, cases=cases, output=tmp_path / "output")
    assert result["complete"] is True and result["rows"] == 3
    prices = pd.read_parquet(tmp_path / "output/prices.parquet")
    assert prices.Code.tolist() == ["2330"] * 3
    assert set(prices.Code) == set(result["codes"]) == {case["code"] for case in json.loads(original_cases)}
    assert result["source_cases_sha256"] == expected_cases_hash
    assert (tmp_path / "output/cases.json").read_bytes() == original_cases
    receipt = json.loads((tmp_path / "output/input-receipt.json").read_bytes())
    assert receipt["source_cases_sha256"] == expected_cases_hash
    assert next(entry["sha256"] for entry in receipt["artifacts"] if entry["path"] == "cases.json") == expected_cases_hash
    assert cases.read_bytes() == original_cases and actions.read_bytes() == original_actions
    assert "label_126" not in prices
    assert pd.read_parquet(tables / "2330.parquet").label_126.eq("must_not_be_read").all()
    with pytest.raises(FileExistsError):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=tmp_path / "output")


@pytest.fixture
def race_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    tables = tmp_path / "tables"
    tables.mkdir()
    frame = pd.DataFrame({
        "asof_date": pd.date_range("2020-01-01", periods=2),
        **{column: [10.0, 11.0] for column in ("RawOpen", "RawHigh", "RawLow", "RawClose")},
        "VolumeLots": [100, 100],
        "label_126": "never_read",
    })
    for code in ("2330", "2317"):
        frame.to_parquet(tables / f"{code}.parquet", index=False)
    actions = tmp_path / "actions.parquet"
    pd.DataFrame(columns=pd.Index(["code", "ex_date", "event_type", "price_factor"])).to_parquet(actions)
    cases = tmp_path / "cases.json"
    cases.write_bytes(b'[{"code":"2330"}]')
    return tables, actions, cases, tmp_path / "output"


def test_cases_change_after_parse_cannot_complete(race_inputs: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch):
    tables, actions, cases, output = race_inputs
    original_loads = input_module.json.loads
    parsed = False

    def mutate_after_parse(document: str | bytes | bytearray, *args: Any, **kwargs: Any) -> Any:
        nonlocal parsed
        result = original_loads(document, *args, **kwargs)
        if not parsed:
            parsed = True
            cases.write_bytes(b'[{"code":"2317"}]')
        return result

    monkeypatch.setattr(input_module.json, "loads", mutate_after_parse)
    with pytest.raises(ValueError, match="source changed before copy"):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert parsed and not output.exists()
    staging = next(output.parent.glob(".staging-prepare-*"))
    assert not (staging / "input-receipt.json").exists()
    assert set(pd.read_parquet(staging / "prices.parquet").Code) == {"2330"}
    assert not (staging / "cases.json").exists()
    receipt = prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert receipt["codes"] == ["2317"] and output.exists() and staging.exists()


@pytest.mark.parametrize("changed_source", ["cases", "actions"])
def test_source_change_after_cases_copy_cannot_complete(race_inputs: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch, changed_source: str):
    tables, actions, cases, output = race_inputs
    original_copy = input_module.copy_verified
    original_cases = cases.read_bytes()
    original_actions = actions.read_bytes()

    def mutate_after_copy(source: Path, destination: Path, expected: str) -> None:
        original_copy(source, destination, expected)
        if source == cases:
            if changed_source == "cases":
                cases.write_bytes(b'[{"code":"2317"}]')
            else:
                actions.write_bytes(original_actions + b"changed after verified copy")

    monkeypatch.setattr(input_module, "copy_verified", mutate_after_copy)
    with pytest.raises(ValueError, match="cases or actions source moved"):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert not output.exists()
    staging = next(output.parent.glob(".staging-prepare-*"))
    assert not (staging / "input-receipt.json").exists()
    assert (staging / "cases.json").read_bytes() == original_cases
    assert (staging / "actions.parquet").read_bytes() == original_actions
    assert set(pd.read_parquet(staging / "prices.parquet").Code) == {"2330"}
    monkeypatch.setattr(input_module, "copy_verified", original_copy)
    actions.write_bytes(original_actions)
    prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert output.exists() and staging.exists()


@pytest.mark.parametrize("failure", ["receipt_write", "source_change", "stage_corrupt", "receipt_corrupt"])
def test_failed_staging_never_publishes_and_same_output_can_retry(
    race_inputs: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    tables, actions, cases, output = race_inputs
    writer = input_module.write_json

    def fail_after_inputs(path: Path, value: dict[str, Any]) -> None:
        if path.name != "input-receipt.json":
            writer(path, value)
            return
        if failure == "receipt_write":
            path.write_bytes(b"interrupted receipt")
            raise OSError("injected receipt interruption")
        writer(path, value)
        if failure == "source_change":
            cases.write_bytes(b'[{"code":"2317"}]')
        elif failure == "stage_corrupt":
            (path.parent / "prices.parquet").write_bytes(b"corrupted staged prices")
        else:
            path.write_bytes(json.dumps({**value, "complete": False}).encode())

    monkeypatch.setattr(input_module, "write_json", fail_after_inputs)
    with pytest.raises((OSError, ValueError)):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert not output.exists() and not (output.parent / f".{output.name}.prepare.lock").exists()
    staging = next(output.parent.glob(".staging-prepare-*"))
    failed_bytes = {path.name: path.read_bytes() for path in staging.iterdir()}
    monkeypatch.setattr(input_module, "write_json", writer)
    receipt = prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert output.exists() and receipt["complete"] is True
    assert {path.name: path.read_bytes() for path in staging.iterdir()} == failed_bytes
    assert set(path.name for path in output.iterdir()) == {"prices.parquet", "actions.parquet", "calendar.json", "cases.json", "input-receipt.json"}
    assert all(not Path(entry["path"]).is_absolute() for entry in receipt["artifacts"])
    assert receipt["source_table_paths"] == {code: str(tables / f"{code}.parquet") for code in receipt["codes"]}
    input_module.verify_files(output, receipt["artifacts"])


def test_competing_final_is_preserved(race_inputs: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    tables, actions, cases, output = race_inputs
    writer = input_module.write_json

    def competing_publish(path: Path, value: dict[str, Any]) -> None:
        writer(path, value)
        if path.name == "input-receipt.json":
            output.mkdir()
            (output / "foreign.txt").write_bytes(b"competing writer")

    monkeypatch.setattr(input_module, "write_json", competing_publish)
    with pytest.raises(FileExistsError):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert (output / "foreign.txt").read_bytes() == b"competing writer"
    assert set(path.name for path in output.iterdir()) == {"foreign.txt"}
    assert len(list(output.parent.glob(".staging-prepare-*"))) == 1
    assert not (output.parent / f".{output.name}.prepare.lock").exists()


def test_empty_competing_final_at_publication_boundary_is_never_replaced(race_inputs: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    tables, actions, cases, output = race_inputs
    publisher = input_module.publish_noreplace
    publications = 0

    def competing_publish(staging: Path, destination: Path) -> None:
        nonlocal publications
        assert destination == output and not destination.exists()
        assert (staging / "input-receipt.json").is_file()
        destination.mkdir()
        publications += 1
        publisher(staging, destination)

    monkeypatch.setattr(input_module, "publish_noreplace", competing_publish)
    with pytest.raises(FileExistsError):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert publications == 1
    assert output.is_dir() and list(output.iterdir()) == []
    assert not (output.parent / f".{output.name}.prepare.lock").exists()
    stages = list(output.parent.glob(".staging-prepare-*"))
    assert len(stages) == 1
    retained_bytes = {path.name: path.read_bytes() for path in stages[0].iterdir()}
    receipt = input_module.read_json(stages[0] / "input-receipt.json")
    assert receipt["complete"] is True
    input_module.verify_files(stages[0], receipt["artifacts"])

    monkeypatch.setattr(input_module, "publish_noreplace", publisher)
    with pytest.raises(FileExistsError):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert output.is_dir() and list(output.iterdir()) == []
    assert {path.name: path.read_bytes() for path in stages[0].iterdir()} == retained_bytes
    assert list(output.parent.glob(".staging-prepare-*")) == stages
    assert not (output.parent / f".{output.name}.prepare.lock").exists()


def test_foreign_lock_is_never_removed(race_inputs: tuple[Path, Path, Path, Path]) -> None:
    tables, actions, cases, output = race_inputs
    lock = output.parent / f".{output.name}.prepare.lock"
    lock.write_bytes(b"foreign writer lock")
    with pytest.raises(FileExistsError):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert lock.read_bytes() == b"foreign writer lock" and not output.exists()
    assert list(output.parent.glob(".staging-prepare-*")) == []


def test_receipt_hash_gate_rejects_late_byte_change(race_inputs: tuple[Path, Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    tables, actions, cases, output = race_inputs
    verifier = input_module.verify_files
    calls = 0

    def mutate_receipt_after_final_artifact_check(root: Path, entries: list[dict[str, Any]]) -> None:
        nonlocal calls
        verifier(root, entries)
        calls += 1
        if calls == 3:
            receipt_path = root / "input-receipt.json"
            receipt_path.write_bytes(receipt_path.read_bytes() + b" ")  # JSON unchanged, bytes changed.

    monkeypatch.setattr(input_module, "verify_files", mutate_receipt_after_final_artifact_check)
    with pytest.raises(ValueError, match="receipt changed before publication"):
        prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert not output.exists() and len(list(output.parent.glob(".staging-prepare-*"))) == 1
    monkeypatch.setattr(input_module, "verify_files", verifier)
    prepare_inputs(tables=tables, actions=actions, cases=cases, output=output)
    assert output.exists()
