"""Synthetic producer mapping and control/noise regression tests."""

from __future__ import annotations

import json
import multiprocessing
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_probability import OUTCOME_COLUMNS
from research_core.hhhl_v4_summary import landmark_census as summarize_landmark_census
from research_core.jobs import file_digest
from scripts import build_hhhl_v4_probability as producer
from scripts.build_hhhl_v4_probability import WINDOW, noise_record, scan_frame


def frame() -> pd.DataFrame:
    dates = pd.date_range(WINDOW[0], periods=160).to_list()
    dates[-1] = pd.Timestamp(WINDOW[1])
    data: dict[str, Any] = {
        "security_id": ["TWSE:1234"] * 160,
        "asof_date": dates,
        "year": [2019] * 160,
        "base_eligible": [True] * 160,
        "eligibility_reason": [""] * 160,
        "regime": ["range"] * 160,
        "industry_ref": ["test"] * 160,
        "RawOpen": [10.0] * 160,
        "RawHigh": [10.0] * 160,
        "RawLow": [10.0] * 160,
        "RawClose": [10.0] * 160,
        "Close": [10.0] * 160,
        "VolumeLots": [10.0] * 160,
        "atr14_pct": [0.01] * 160,
    }
    for column in OUTCOME_COLUMNS:
        data[column] = [None if "unknown_reason" in column or "wait" in column else False if "complete" in column else 0.0] * 160
    result = pd.DataFrame(data)
    result.loc[25, ["RawClose", "RawHigh", "Close"]] = 10.5
    result.loc[25, "VolumeLots"] = 30.0
    result.loc[28:, ["RawClose", "RawHigh", "Close"]] = 12.0
    result.loc[120:, ["RawClose", "RawHigh", "Close"]] = 21.0
    return result


def prepare(raw: pd.DataFrame, _factors: pd.DataFrame, _code: str, _cutoff: str) -> pd.DataFrame:
    bars = raw.dropna(subset=["RawOpen", "RawHigh", "RawLow", "RawClose"]).copy().reset_index(drop=True)
    for name in ("Open", "High", "Low", "Close"):
        bars[name] = bars[f"Raw{name}"]
    bars.attrs["preparation_metadata"] = {"used_rows": len(bars)}
    return bars


def event(pattern: bool = True, t: int = 25) -> dict[str, Any]:
    return {
        "t": t,
        "restart": 5,
        "leg_start": 5,
        "seq": [{"i": 18, "k": "L", "p": 9.0, "rel": "same"}],
        "bonus_levels": [{"level": 11.0, "touches": 2, "age": "old"}],
        "blocking": [],
        "cat": "hhhl",
        "scale": "small_range" if pattern else "inside_big_range",
        "pattern": pattern,
        "limit_up": False,
        "big_hhhl": False,
        "liquid": True,
        "vx": 3.0,
        "hz_top": 10.0,
    }


def _synthetic_batch_worker(task: tuple[str, str, float]) -> dict[str, Any]:
    action, value, delay = task
    if action == "block":
        Path(value).write_text("started", encoding="utf-8")
        time.sleep(60)
    elif action == "sleep":
        time.sleep(delay)
    elif action == "raise":
        raise ValueError("synthetic worker failure")
    return {"value": value}


def _receipt_child_command(output: Path, *, status: int = 0, ready: Path | None = None) -> list[str]:
    child_code = "\n".join([
        "import hashlib, json, os, pathlib, subprocess, sys, time",
        "out = pathlib.Path(sys.argv[1])",
        "out.mkdir(parents=True, exist_ok=True)",
        "identity = {'synthetic': 'receipt-test'}",
        "token = 'a' * 32",
        "started_at_utc = 'synthetic'",
        (
            "initial = {'complete': False, 'identity_complete': False, 'code_commit': None, 'identity': None, "
            "'attempt_token': token, 'started_at_utc': started_at_utc}"
        ),
        "initial_path = out / 'attempt-start.json'",
        "initial_path.write_text(json.dumps(initial), encoding='utf-8')",
        "attempt = out / 'attempt.json'",
        "enriched = {**initial, 'identity_complete': True, 'code_commit': 'synthetic', 'identity': identity}",
        "attempt.write_text(json.dumps(enriched), encoding='utf-8')",
        "initial_artifact = {'sha256': hashlib.sha256(initial_path.read_bytes()).hexdigest(), 'bytes': initial_path.stat().st_size}",
        "artifact = {'sha256': hashlib.sha256(attempt.read_bytes()).hexdigest(), 'bytes': attempt.stat().st_size}",
        "receipt = {",
        "    'schema_version': 'hhhl-probability.v4',",
        "    'phase': 'descriptive_provisional',",
        "    'rule': 'synthetic',",
        "    'complete': True,",
        "    'code_commit': 'synthetic',",
        "    'completed_at_utc': 'synthetic',",
        "    'source_dataset_id': 'synthetic',",
        "    'source': 'synthetic',",
        "    'verified_input': {},",
        "    'window': ['2019-01-02', '2026-08-14'],",
        "    'identity': identity,",
        "    'factor_input': {},",
        "    'runtime': {'python': 'synthetic'},",
        "    'workers': 1,",
        "    'noise_seed': 1,",
        "    'counts': {'comparisons': 1080},",
        "    'elapsed_seconds': 0.25,",
        "    'artifacts': {'attempt.json': artifact, 'attempt-start.json': initial_artifact},",
        "    'limitations': [],",
        "}",
        "(out / 'manifest.pending.json').write_text(json.dumps(receipt), encoding='utf-8')",
        "if sys.argv[3]:",
        "    nested = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
        "    pathlib.Path(sys.argv[3]).write_text(f'{os.getpid()} {nested.pid}', encoding='utf-8')",
        "    time.sleep(60)",
        "sys.exit(int(sys.argv[2]))",
    ])
    return [sys.executable, "-c", child_code, str(output), str(status), str(ready or "")]


def _write_synthetic_pending_receipt(output: Path) -> Path:
    output.mkdir(parents=True)
    identity = {"synthetic": "receipt-test"}
    token = "b" * 32
    started_at_utc = "synthetic"
    initial = {
        "complete": False,
        "identity_complete": False,
        "code_commit": None,
        "identity": None,
        "attempt_token": token,
        "started_at_utc": started_at_utc,
    }
    initial_path = output / producer.ATTEMPT_START
    initial_path.write_text(json.dumps(initial), encoding="utf-8")
    attempt = output / "attempt.json"
    attempt.write_text(
        json.dumps({**initial, "identity_complete": True, "code_commit": "synthetic", "identity": identity}),
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "hhhl-probability.v4",
        "phase": "descriptive_provisional",
        "rule": "synthetic",
        "complete": True,
        "code_commit": "synthetic",
        "completed_at_utc": "synthetic",
        "source_dataset_id": "synthetic",
        "source": "synthetic",
        "verified_input": {},
        "window": ["2019-01-02", "2026-08-14"],
        "identity": identity,
        "factor_input": {},
        "runtime": {"python": "synthetic"},
        "workers": 1,
        "noise_seed": 1,
        "counts": {"comparisons": 1080},
        "elapsed_seconds": 0.25,
        "artifacts": {
            "attempt.json": {"sha256": file_digest(attempt), "bytes": attempt.stat().st_size},
            producer.ATTEMPT_START: {"sha256": file_digest(initial_path), "bytes": initial_path.stat().st_size},
        },
        "limitations": [],
    }
    pending = output / producer.PENDING_MANIFEST
    pending.write_text(json.dumps(receipt), encoding="utf-8")
    return pending


def _synthetic_fixed_inputs(inputs: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    inputs.mkdir()
    factor_path = inputs / "corporate_action_factors.parquet"
    factors = pd.DataFrame({
        "code": ["1234"],
        "ex_date": ["2020-01-02"],
        "event_type": ["cash"],
        "price_factor": [0.95],
    })
    factors.to_parquet(factor_path, index=False)
    cases_path = inputs / "validation-cases.json"
    cases_path.write_text(json.dumps([{"id": "case-1", "code": "1234", "date": "2020-01-03", "kind": "rule"}]), encoding="utf-8")
    receipt = {
        "factor_rows": len(factors),
        "factor_snapshot": {"path": factor_path.name, "sha256": file_digest(factor_path)},
        "validation_cases": {"path": cases_path.name, "sha256": file_digest(cases_path), "count": 1},
    }
    receipt_path = inputs / "input-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(
        producer,
        "FIXED_INPUT_SHA256",
        {path.name: file_digest(path) for path in (factor_path, cases_path, receipt_path)},
    )
    return inputs


def _pid_is_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
            text=True,
        )
        return f'"{pid}"' in result.stdout
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            state = proc_stat.read_text(encoding="utf-8").split(")", 1)[1].strip().split()[0]
        except FileNotFoundError:
            return False
        if state == "Z":
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_until_pids_exit(pids: list[int]) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and any(_pid_is_alive(pid) for pid in pids):
        time.sleep(0.05)
    assert not any(_pid_is_alive(pid) for pid in pids)


def test_mapping_fixed_clock_and_primary_atlas_separation() -> None:
    raw = frame()
    raw.loc[130, "RawOpen"] = np.nan
    result = scan_frame(raw, pd.DataFrame(), lambda _: [event()], prepare)
    row = result["events"][0]
    assert row["adjusted_label_126"] == 1
    assert row["atlas_label_126"] == 0
    assert not row["adjusted_complete_126"]
    assert pd.isna(row["adjusted_min_return_126"])
    assert pd.isna(result["base"].iloc[130]["adjusted_close"])
    assert result["coverage"]["raw_close_present_dropped_ohlc"] == 1
    landmark = next(r for r in result["landmarks"] if r["landmark"] == 20)
    assert landmark["group"] == "cross_old_only"
    assert landmark["label_126"] == 1
    assert landmark["deadline_index"] == 151
    assert landmark["first_cross_old_date"] == "2019-01-30"
    assert not any(row["anchor_date"] == "2019-01-27" for row in result["controls"])


@pytest.mark.parametrize(
    ("tail_state", "expected_status", "expected_reason"),
    [
        ("window_end", "unknown", "window_end"),
        ("early_hit", "early_hit", None),
        ("early_failed", "early_failed", None),
    ],
)
def test_unobserved_landmark_keeps_null_index_and_date(tail_state: str, expected_status: str, expected_reason: str | None) -> None:
    raw = frame()
    if tail_state == "early_hit":
        raw.loc[151, ["RawOpen", "RawHigh", "RawLow", "RawClose", "Close"]] = 42.0
    elif tail_state == "early_failed":
        raw.loc[151, ["RawOpen", "RawHigh", "RawLow", "RawClose", "Close"]] = 8.0

    result = scan_frame(raw, pd.DataFrame(), lambda _: [event(t=150)], prepare)
    landmarks = result["landmarks"]
    assert {row["landmark"] for row in landmarks} == {10, 20, 40}
    for row in landmarks:
        assert row["status"] == expected_status
        assert row["reason"] == expected_reason
        assert row["landmark_index"] is None
        assert row["landmark_date"] is None
        assert row["anchor_date"] is None


def test_observed_landmark_index_and_date_remain_unchanged() -> None:
    raw = frame()
    date_strings = pd.to_datetime(raw["asof_date"]).dt.strftime("%Y-%m-%d")

    result = scan_frame(raw, pd.DataFrame(), lambda _: [event(t=25)], prepare)
    by_landmark = {row["landmark"]: row for row in result["landmarks"]}
    for landmark in (10, 20, 40):
        expected_index = 25 + landmark
        expected_date = date_strings.iloc[expected_index]
        assert by_landmark[landmark]["landmark_index"] == expected_index
        assert by_landmark[landmark]["landmark_date"] == expected_date
        assert by_landmark[landmark]["anchor_date"] == expected_date


def test_false_event_is_secondary_but_not_main_control() -> None:
    result = scan_frame(frame(), pd.DataFrame(), lambda _: [event(False)], prepare)
    control = next(row for row in result["controls"] if row["anchor_date"] == "2019-01-27")
    assert control["control_no_pattern"]
    assert not control["control_no_event"]
    assert result["landmarks"] == []


def test_noise_deterministic_and_unavailable_stays_unknown() -> None:
    result = scan_frame(frame(), pd.DataFrame(), lambda _: [event()], prepare)
    first = noise_record(result["base"], result["events"][0], random.Random(20261010))
    second = noise_record(result["base"], result["events"][0], random.Random(20261010))
    assert first["calendar_offset"] == second["calendar_offset"] != 0
    base = result["base"].copy()
    base["base_eligible"] = False
    base.loc[25, "base_eligible"] = True
    unavailable = noise_record(base, result["events"][0], random.Random(20261010))
    assert unavailable["base_eligible"]
    assert unavailable["adjusted_label_126"] is None
    assert unavailable["atlas_unknown_reason_63"] == "no_shift_candidate"


def test_empty_ohlc_retained_unless_eligible() -> None:
    raw = frame()
    raw["RawOpen"] = np.nan
    with pytest.raises(ValueError, match="eligible anchors"):
        scan_frame(raw, pd.DataFrame(), lambda _: [], prepare)
    raw["base_eligible"] = False
    result = scan_frame(raw, pd.DataFrame(), lambda _: [], prepare)
    assert result["coverage"]["preparation"]["status"] == "no_usable_ohlc"
    assert len(result["base"]) == 160
    assert result["events"] == []


def test_computational_build_writes_pending_receipt_without_self_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset, task, inputs, output = (tmp_path / name for name in ("dataset", "task", "inputs", "output"))
    for directory in (dataset, task / "sources", inputs):
        directory.mkdir(parents=True)
    for relative in ("mission.md", "data-contract.md", "sources/hhhl_rule_v4.zip", "sources/definition-response.zip"):
        (task / relative).write_text("synthetic fixture", encoding="utf-8")
    for name in ("input-receipt.json", "factors.parquet", "cases.json"):
        (inputs / name).write_text("synthetic fixture", encoding="utf-8")
    table = dataset / "stock.parquet"
    frame().to_parquet(table, index=False)
    (dataset / "manifest.json").write_text(
        json.dumps({"tables": [{"security_id": "TWSE:1234", "path": table.name, "rows": 160, "sha256": file_digest(table)}]}), encoding="utf-8"
    )
    monkeypatch.setattr(producer, "verify_dataset", lambda _: {"dataset_id": producer.DATASET_ID})
    monkeypatch.setattr(
        producer,
        "read_fixed_inputs",
        lambda _: (pd.DataFrame(), [], {"factor_snapshot": {"path": "factors.parquet"}, "validation_cases": {"path": "cases.json"}}),
    )
    monkeypatch.setattr(producer, "load_source_texts", lambda *_: {})
    monkeypatch.setattr(producer.subprocess, "check_output", lambda command, **_: "" if command[1] == "status" else "synthetic-commit")

    def scan_with_unknown_reasons(_: Path) -> dict[str, Any]:
        raw = frame()
        raw.loc[30, "RawOpen"] = np.nan
        raw.loc[151, "base_eligible"] = False
        return scan_frame(raw, pd.DataFrame(), lambda _: [event(t=25), event(t=150)], prepare)

    def synthetic_batches(args: list[tuple[Any, ...]], _workers: int, **_kwargs: Any) -> Any:
        yield scan_with_unknown_reasons(args[0][0])

    monkeypatch.setattr(producer, "batches", synthetic_batches)
    result = producer._build(dataset, task, inputs, output, workers=1)
    assert result["complete"]
    assert (output / producer.PENDING_MANIFEST).is_file()
    assert not (output / "manifest.json").exists()
    assert result["counts"]["comparisons"] == 1080
    assert result["counts"]["landmarks"] == 6
    assert "manifest.json" not in result["artifacts"]
    assert result["artifacts"]["attempt.json"]["sha256"] == file_digest(output / "attempt.json")
    assert result["artifacts"][producer.ATTEMPT_START]["sha256"] == file_digest(output / producer.ATTEMPT_START)
    initial_attempt = json.loads((output / producer.ATTEMPT_START).read_text(encoding="utf-8"))
    assert initial_attempt["complete"] is False
    assert initial_attempt["identity_complete"] is False
    assert initial_attempt["code_commit"] is None
    assert initial_attempt["identity"] is None
    enriched_attempt = json.loads((output / "attempt.json").read_text(encoding="utf-8"))
    assert enriched_attempt["complete"] is False
    assert enriched_attempt["identity_complete"] is True
    assert enriched_attempt["identity"] == result["identity"]
    for name, evidence in result["artifacts"].items():
        assert evidence["sha256"] == file_digest(output / name)
        assert evidence["bytes"] == (output / name).stat().st_size

    diagnostics = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
    assert set(diagnostics) == {"landmark_census", "label_discordance", "landmark_reason_census"}
    legacy = diagnostics["landmark_census"]
    assert len(legacy) == 24
    assert all(set(row) == {"landmark", "status", "eligible", "events", "securities"} for row in legacy)
    landmark_frame = pd.read_parquet(output / "landmarks.parquet", columns=["security_id", "landmark", "base_eligible", "status", "reason"])
    assert diagnostics["landmark_reason_census"] == summarize_landmark_census(landmark_frame)
    unknown = [row for row in diagnostics["landmark_reason_census"] if row["status"] == "unknown"]
    assert {row["reason"] for row in unknown} == {"missing_before_landmark", "window_end"}
    assert {row["eligibility"] for row in unknown} == {"eligible", "ineligible"}

    expected_legacy = []
    for landmark in (10, 20, 40):
        for status in ("active", "early_hit", "early_failed", "unknown"):
            for eligible in (True, False):
                group = landmark_frame.loc[
                    landmark_frame["landmark"].eq(landmark) & landmark_frame["status"].eq(status) & landmark_frame["base_eligible"].eq(eligible)
                ]
                expected_legacy.append({
                    "landmark": landmark,
                    "status": status,
                    "eligible": eligible,
                    "events": len(group),
                    "securities": int(group["security_id"].nunique()),
                })
    assert legacy == expected_legacy
    with pytest.raises(FileExistsError):
        producer._build(dataset, task, inputs, output, workers=1)


def test_fixed_synthetic_factor_snapshot_is_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _synthetic_fixed_inputs(tmp_path / "inputs", monkeypatch)

    factors, cases, receipt = producer.read_fixed_inputs(inputs)

    assert factors["code"].tolist() == ["1234"]
    assert cases == [{"id": "case-1", "code": "1234", "date": "2020-01-03", "kind": "rule"}]
    assert receipt["factor_snapshot"]["path"] == "corporate_action_factors.parquet"


def test_fixed_hash_rejects_factor_and_receipt_rewritten_consistently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _synthetic_fixed_inputs(tmp_path / "inputs", monkeypatch)
    factor_path = inputs / "corporate_action_factors.parquet"
    receipt_path = inputs / "input-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    pd.DataFrame({
        "code": ["1234", "5678"],
        "ex_date": ["2020-01-02", "2021-01-02"],
        "event_type": ["cash", "cash"],
        "price_factor": [0.95, 0.9],
    }).to_parquet(factor_path, index=False)
    receipt["factor_rows"] = 2
    receipt["factor_snapshot"]["sha256"] = file_digest(factor_path)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    # The mutable receipt remains algebraically self-consistent; the frozen SHA map rejects it.
    generic_factors, _, generic_receipt = producer.read_inputs(inputs)
    assert len(generic_factors) == generic_receipt["factor_rows"] == 2
    with pytest.raises(ValueError, match="unauthorized fixed input SHA-256"):
        producer.read_fixed_inputs(inputs)


def test_fixed_hash_rechecks_inputs_after_generic_reader_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = _synthetic_fixed_inputs(tmp_path / "inputs", monkeypatch)
    generic_reader = producer.read_inputs

    def mutate_after_read(root: Path) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
        loaded = generic_reader(root)
        (root / "validation-cases.json").write_text('[{"id":"mutated"}]', encoding="utf-8")
        return loaded

    monkeypatch.setattr(producer, "read_inputs", mutate_after_read)
    with pytest.raises(ValueError, match="unauthorized fixed input SHA-256"):
        producer.read_fixed_inputs(inputs)


def test_direct_build_records_unknown_attempt_before_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "preflight-failure"

    def fail_verification(_dataset: Path) -> dict[str, Any]:
        raise RuntimeError("synthetic verification failure")

    monkeypatch.setattr(producer, "verify_dataset", fail_verification)
    with pytest.raises(RuntimeError, match="synthetic verification failure"):
        producer._build(tmp_path / "dataset", tmp_path / "task", tmp_path / "inputs", output, workers=1)

    initial = json.loads((output / producer.ATTEMPT_START).read_text(encoding="utf-8"))
    attempt = json.loads((output / "attempt.json").read_text(encoding="utf-8"))
    assert attempt == initial
    assert initial["complete"] is False
    assert initial["identity_complete"] is False
    assert initial["code_commit"] is None
    assert initial["identity"] is None
    assert not (output / "manifest.json").exists()


def test_private_build_rejects_output_with_different_parent_attempt_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "parent-owned"
    started_at_utc = "synthetic-start"
    producer._initialize_attempt(output, token="c" * 32, started_at_utc=started_at_utc)

    def unexpected_verification(_dataset: Path) -> dict[str, Any]:
        raise AssertionError("mismatched private child must stop before dataset validation")

    monkeypatch.setattr(producer, "verify_dataset", unexpected_verification)
    with pytest.raises(ValueError, match="fresh parent-owned incomplete attempt"):
        producer._build(
            tmp_path / "dataset",
            tmp_path / "task",
            tmp_path / "inputs",
            output,
            workers=1,
            attempt_token="d" * 32,
            attempt_started_at_utc=started_at_utc,
        )

    assert json.loads((output / producer.ATTEMPT_START).read_text(encoding="utf-8"))["attempt_token"] == "c" * 32
    assert json.loads((output / "attempt.json").read_text(encoding="utf-8"))["identity"] is None


def test_public_build_preserves_initial_attempt_when_child_startup_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "startup-failure"

    def fail_launch(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("synthetic child startup failure")

    monkeypatch.setattr(producer.subprocess, "Popen", fail_launch)
    with pytest.raises(OSError, match="synthetic child startup failure"):
        producer.build(tmp_path / "dataset", tmp_path / "task", tmp_path / "inputs", output, workers=1)

    initial = json.loads((output / producer.ATTEMPT_START).read_text(encoding="utf-8"))
    assert json.loads((output / "attempt.json").read_text(encoding="utf-8")) == initial
    assert initial["identity"] is None
    assert initial["code_commit"] is None
    assert not (output / "manifest.json").exists()


def test_public_build_preserves_initial_attempt_when_supervisor_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "supervisor-timeout"

    def time_out(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise TimeoutError("synthetic parent deadline")

    monkeypatch.setattr(producer, "_supervise_build", time_out)
    with pytest.raises(TimeoutError, match="synthetic parent deadline"):
        producer.build(tmp_path / "dataset", tmp_path / "task", tmp_path / "inputs", output, workers=1)

    initial = json.loads((output / producer.ATTEMPT_START).read_text(encoding="utf-8"))
    assert json.loads((output / "attempt.json").read_text(encoding="utf-8")) == initial
    assert initial["complete"] is False
    assert initial["identity_complete"] is False
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("workers", [1, 4])
def test_blocked_owned_pool_is_terminated_at_deadline(workers: int, tmp_path: Path) -> None:
    before = {child.pid for child in multiprocessing.active_children()}
    markers = [tmp_path / f"worker-{index}.started" for index in range(workers)]
    tasks = [("block", str(marker), 0.0) for marker in markers]
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="monotonic deadline"):
        list(producer.batches(tasks, workers, deadline=started + 10.0, worker=_synthetic_batch_worker))
    elapsed = time.monotonic() - started
    assert elapsed < 17.0
    assert any(marker.exists() for marker in markers)
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_batches_preserves_input_order_when_workers_finish_out_of_order() -> None:
    tasks = [("sleep", label, delay) for label, delay in (("slow", 0.4), ("fast", 0.01), ("mid", 0.1), ("quick", 0.02))]
    results = list(producer.batches(tasks, 4, deadline=time.monotonic() + 15.0, worker=_synthetic_batch_worker))
    assert results == [{"value": label} for label, _ in (("slow", 0.4), ("fast", 0.01), ("mid", 0.1), ("quick", 0.02))]


def test_batches_does_not_reset_one_deadline_between_batches() -> None:
    class SteppingClock:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> float:
            self.calls += 1
            return 0.0 if self.calls == 1 else 3601.0

    clock = SteppingClock()
    before = {child.pid for child in multiprocessing.active_children()}
    results = producer.batches(
        [("sleep", "first", 0.01), ("sleep", "second", 0.01)],
        1,
        deadline=3600.0,
        worker=_synthetic_batch_worker,
        clock=clock,
    )
    assert next(results) == {"value": "first"}
    with pytest.raises(TimeoutError, match="monotonic deadline"):
        next(results)
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_worker_exception_and_explicit_close_clean_up_owned_pool(tmp_path: Path) -> None:
    before = {child.pid for child in multiprocessing.active_children()}
    failing = producer.batches([("raise", "broken", 0.0)], 1, deadline=time.monotonic() + 15.0, worker=_synthetic_batch_worker)
    with pytest.raises(ValueError, match="synthetic worker failure"):
        list(failing)
    assert {child.pid for child in multiprocessing.active_children()} <= before

    marker = tmp_path / "blocked.started"
    partially_consumed = producer.batches(
        [("sleep", "first", 0.05), ("block", str(marker), 0.0)],
        4,
        deadline=time.monotonic() + 15.0,
        worker=_synthetic_batch_worker,
    )
    assert next(partially_consumed) == {"value": "first"}
    ready_deadline = time.monotonic() + 5.0
    while not marker.exists() and time.monotonic() < ready_deadline:
        time.sleep(0.01)
    partially_consumed.close()
    assert marker.exists()
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_supervisor_uses_remaining_deadline_and_finalizes_after_child_exit(tmp_path: Path) -> None:
    output = tmp_path / "successful"

    class Clock:
        def __init__(self) -> None:
            self.values = iter((10.0, *([20.0] * 32)))

        def __call__(self) -> float:
            return next(self.values)

    observed_timeouts: list[float] = []

    def wait_for_child(process: subprocess.Popen[Any], timeout: float) -> int:
        assert not (output / "manifest.json").exists()
        observed_timeouts.append(timeout)
        return process.wait(timeout=timeout)

    receipt = producer._supervise_build(
        _receipt_child_command(output),
        output,
        deadline=100.0,
        clock=Clock(),
        waiter=wait_for_child,
    )
    assert observed_timeouts == [90.0]
    assert receipt["complete"] is True
    assert (output / "manifest.json").is_file()
    assert not (output / producer.PENDING_MANIFEST).exists()
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == receipt


def test_finalizer_rejects_expired_deadline_and_preserves_pending_receipt(tmp_path: Path) -> None:
    output = tmp_path / "expired-finalization"
    pending = _write_synthetic_pending_receipt(output)

    with pytest.raises(TimeoutError, match="fixed budget expired"):
        producer._finalize_pending_receipt(output, deadline=10.0, clock=lambda: 10.0)

    assert pending.is_file()
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("elapsed", [float("nan"), float("inf"), float("-inf")])
def test_finalizer_rejects_nonfinite_pending_elapsed(tmp_path: Path, elapsed: float) -> None:
    output = tmp_path / "invalid-elapsed"
    pending = _write_synthetic_pending_receipt(output)
    receipt = json.loads(pending.read_text(encoding="utf-8"))
    receipt["elapsed_seconds"] = elapsed
    pending.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid elapsed time"):
        producer._finalize_pending_receipt(output, deadline=time.monotonic() + 30.0)

    assert pending.is_file()
    assert not (output / "manifest.json").exists()


def test_finalizer_rejects_unsafe_pending_artifact_path(tmp_path: Path) -> None:
    output = tmp_path / "invalid-artifact-path"
    pending = _write_synthetic_pending_receipt(output)
    receipt = json.loads(pending.read_text(encoding="utf-8"))
    receipt["artifacts"]["../escape.json"] = {"sha256": "0" * 64, "bytes": 0}
    pending.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact is invalid"):
        producer._finalize_pending_receipt(output, deadline=time.monotonic() + 30.0)

    assert pending.is_file()
    assert not (output / "manifest.json").exists()


def test_failed_child_keeps_pending_receipt_without_completed_manifest(tmp_path: Path) -> None:
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="exited with status 7"):
        producer._supervise_build(
            _receipt_child_command(output, status=7),
            output,
            deadline=time.monotonic() + 30.0,
        )
    assert (output / producer.PENDING_MANIFEST).is_file()
    assert not (output / "manifest.json").exists()


def test_timed_out_child_tree_is_terminated_without_touching_unrelated_process(tmp_path: Path) -> None:
    output = tmp_path / "timed-out"
    ready = tmp_path / "tree.started"
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

    def wait_until_tree_ready_then_timeout(process: subprocess.Popen[Any], timeout: float) -> int:
        deadline = time.monotonic() + 20.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.is_file(), "synthetic child did not reach its blocked finalization point"
        raise subprocess.TimeoutExpired(process.args, timeout)

    try:
        with pytest.raises(TimeoutError, match="absolute deadline"):
            producer._supervise_build(
                _receipt_child_command(output, ready=ready),
                output,
                deadline=time.monotonic() + 30.0,
                waiter=wait_until_tree_ready_then_timeout,
            )
        assert (output / producer.PENDING_MANIFEST).is_file()
        assert not (output / "manifest.json").exists()
        process_ids = [int(value) for value in ready.read_text(encoding="utf-8").split()]
        _wait_until_pids_exit(process_ids)
        assert unrelated.poll() is None
    finally:
        if unrelated.poll() is None:
            unrelated.terminate()
            unrelated.wait(timeout=5)


def test_native_crash_cleans_descendants_after_leader_exit(tmp_path: Path) -> None:
    output = tmp_path / "native-crash"
    producer._initialize_attempt(output)
    ready = tmp_path / "native-tree.started"
    script = (
        "import os,subprocess,sys; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"Path({str(ready)!r}).write_text(str(os.getpid())+' '+str(child.pid),encoding='utf-8'); "
        "os._exit(7)"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        with pytest.raises(RuntimeError, match="exited with status 7"):
            producer._supervise_build([sys.executable, "-c", script], output, deadline=time.monotonic() + 30.0)
        _wait_until_pids_exit([int(value) for value in ready.read_text(encoding="utf-8").split()])
        assert unrelated.poll() is None
        assert (output / "attempt.json").is_file()
        assert not (output / "manifest.json").exists()
    finally:
        if unrelated.poll() is None:
            unrelated.terminate()
            unrelated.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 Job Object regression")
def test_windows_assignment_failure_does_not_release_startup_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core.windows_process_job import WindowsProcessJob

    marker = tmp_path / "must-not-start"
    job = WindowsProcessJob()

    def fail_assignment(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic assignment failure")

    monkeypatch.setattr(job._api, "AssignProcessToJobObject", fail_assignment)
    try:
        with pytest.raises(RuntimeError, match="synthetic assignment failure"):
            job.start([sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"], tmp_path)
        job.terminate_and_confirm()
        assert not marker.exists()
    finally:
        job.close()


@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 Job Object regression")
def test_windows_cleanup_reports_unconfirmed_membership() -> None:
    from research_core.windows_process_job import WindowsProcessJob

    job = WindowsProcessJob()
    original_api = job._api

    class Unconfirmed:
        JobObjectBasicAccountingInformation = original_api.JobObjectBasicAccountingInformation

        @staticmethod
        def TerminateJobObject(*_args: Any) -> None:
            pass

        @staticmethod
        def QueryInformationJobObject(*_args: Any) -> dict[str, int]:
            return {"ActiveProcesses": 1}

    job._api = Unconfirmed
    try:
        with pytest.raises(RuntimeError, match="could not be confirmed"):
            job.terminate_and_confirm(timeout=0)
    finally:
        job.close()


def test_public_build_does_not_launch_or_overwrite_existing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "preserve.txt"
    marker.write_text("prior attempt", encoding="utf-8")

    def unexpected_launch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("existing output must be rejected before child launch")

    monkeypatch.setattr(producer.subprocess, "Popen", unexpected_launch)
    with pytest.raises(FileExistsError, match="preserving prior attempt"):
        producer.build(tmp_path / "dataset", tmp_path / "task", tmp_path / "inputs", output, workers=1)
    assert marker.read_text(encoding="utf-8") == "prior attempt"
    assert not (output / "attempt.json").exists()
