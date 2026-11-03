"""Synthetic checkpoint boundary tests: no detector or market-data access."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_barrier_v1 as barrier
from research_core import pattern_scan_recovery_v1 as recovery
from research_core.artifact_store import describe_file, file_digest, object_digest, read_json
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.pattern_scan_projection_v1 import project_outcomes
from research_core.pattern_scan_stock_v1 import EVENT_COLUMNS

SOURCE_BODY: dict[str, Any] = {
    "schema": "pattern-scan-source.git.v2",
    "code": {"commit": "a" * 40, "dirty": True},
    "runtime": {"python": "3.11.9", "numpy": "1.26.4", "pandas": "2.2.3", "pyarrow": "17.0.0"},
    "platform": "win32",
    "numerical_thread_limits": {
        name: "1" for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS")
    },
}
SOURCE = {**SOURCE_BODY, "source_id": object_digest(SOURCE_BODY)}
INPUT_ID = "SYNTH-input"


def write_json(path: Path, body: dict[str, Any]) -> None:
    """Allow deliberate replacement only inside this test's owned fixture."""
    path.write_text(json.dumps(body, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        write_frame(frame, stream, index=True)


def _event(calendar: pd.DatetimeIndex, index: int, pattern: str = "L1", cohort: str = "union") -> dict[str, Any]:
    identity = EventIdentity("TW:0001", str(calendar[index].strftime("%Y-%m-%d")), pattern, "original", SOURCE["source_id"], INPUT_ID)
    row: dict[str, Any] = dict.fromkeys(EVENT_COLUMNS)
    row.update(
        security_id=identity.security_id,
        event_id=identity.event_id,
        t0=identity.t0,
        calendar_index=index,
        pattern_id=pattern,
        subtype_id="original",
        cohort_id=cohort,
        window_start=index - 2,
        details_json='{"synthetic":"preserve"}',
        base_eligible=True,
        eligibility_reason=None,
        definition_id=SOURCE["source_id"],
        input_id=INPUT_ID,
        member_subtype_ids='["original"]',
        member_event_ids='["saved-member"]',
        member_metadata='[{"source":"saved"}]',
    )
    return row


def _stock_receipts(root: Path) -> dict[str, Any]:
    directory = root / "parts" / "0001"
    row = {
        "code": "0001",
        "complete": True,
        "source_id": SOURCE["source_id"],
        "input_id": INPUT_ID,
        "request_id": "SYNTH-stock-request",
        "output_path": str(directory),
        "rows": {"cohort_events": len(read_frame(directory / "cohort_events.parquet"))},
        "artifacts": [describe_file(directory, path) for path in sorted(directory.glob("*.parquet"))],
    }
    write_json(directory / "receipt.json", row)
    write_json(root / "phase-stock-result.json", {"phase": "full_stock_checkpoints", "pool": {"complete": True, "results": [row]}})
    return row


@pytest.fixture
def checkpoint(tmp_path: Path) -> Path:
    root = tmp_path / "synthetic-retained-run"
    directory = root / "parts" / "0001"
    calendar = pd.bdate_range("2020-01-06", periods=310)
    # Adjacent union events must survive intact; the reader must not recool.
    cohort = pd.DataFrame([_event(calendar, 10), _event(calendar, 11), _event(calendar, 30, cohort="original"), _event(calendar, 40, pattern="L2")])
    _write(directory / "cohort_events.parquet", cohort)
    labels = pd.DataFrame([
        {
            "security_id": "TW:0001",
            "t0": calendar[index].strftime("%Y-%m-%d"),
            "calendar_index": index,
            "horizon": horizon,
            "label": "hit",
            "calendar_full": True,
            "main_eligible": True,
            "unknown_reason": None,
        }
        for index in (10, 11)
        for horizon in (126, 252)
    ])
    _write(directory / "base_labels.parquet", labels)
    _write(directory / "indicators.parquet", pd.DataFrame({"quality_reason": None}, index=calendar))
    _write(
        directory / "common_values.parquet",
        pd.DataFrame(
            {"security_id": "TW:0001", "t0": calendar.strftime("%Y-%m-%d"), "calendar_index": range(len(calendar)), "G": 1.5, "VOL_a": 0.7}, index=calendar
        ),
    )
    _stock_receipts(root)
    global_path = root / "global" / "0001.parquet"
    _write(
        global_path,
        pd.DataFrame({"security_id": "TW:0001", "t0": calendar.strftime("%Y-%m-%d"), "calendar_index": range(len(calendar)), "MKT": "mixed"}, index=calendar),
    )
    write_json(
        root / "global" / "receipt.json",
        {
            "complete": True,
            "source_id": SOURCE["source_id"],
            "input_id": INPUT_ID,
            "calendar": calendar.strftime("%Y-%m-%d").tolist(),
            "global_files": {"0001": {"path": str(global_path), "sha256": file_digest(global_path)}},
        },
    )
    write_json(root / "derived-preparation.json", {"source": SOURCE, "input_id": INPUT_ID, "ordinary_reference_n": 1, "calendar_n": len(calendar)})
    return root


def _load(root: Path, **kwargs: Any) -> recovery.RecoveryInventory:
    label_version = _label_version(root)
    arguments = {
        "requested_codes": ("0001",),
        "expected_input_id": INPUT_ID,
        "expected_source_id": SOURCE["source_id"],
        "expected_label_version_id": label_version,
        "expected_calendar_n": 310,
        "expected_stock_n": 1,
        "expected_retained_n": 0,
    }
    arguments.update(kwargs)
    return recovery.load_recovery_inventory(root, **arguments)


def _label_version(root: Path) -> str:
    """Independent oracle for the unchanged historical checkpoint label body."""
    rows = read_json(root / "phase-stock-result.json")["pool"]["results"]
    labels = {}
    for row in rows:
        receipt = read_json(Path(row["output_path"]) / "receipt.json")
        labels[row["code"]] = next(record for record in receipt["artifacts"] if record["path"] == "base_labels.parquet")
    body = {"schema": "pattern-scan-label-checkpoints.v3", "source_id": SOURCE["source_id"], "input_id": INPUT_ID, "labels": labels}
    return f"checkpoint-only:{object_digest(body)}"


def _add_synthetic_stock(root: Path, code: str) -> None:
    """Extend only this test's hand-built checkpoint pool; never read real inputs."""
    directory = root / "parts" / code
    for path in sorted((root / "parts" / "0001").glob("*.parquet")):
        frame = read_frame(path)
        if "security_id" in frame:
            frame["security_id"] = f"TW:{code}"
        if "event_id" in frame:
            frame["event_id"] = [
                EventIdentity(f"TW:{code}", t0, pattern_id, subtype_id, SOURCE["source_id"], INPUT_ID).event_id
                for t0, pattern_id, subtype_id in frame[["t0", "pattern_id", "subtype_id"]].itertuples(index=False, name=None)
            ]
        _write(directory / path.name, frame)
    row = {
        "code": code,
        "complete": True,
        "source_id": SOURCE["source_id"],
        "input_id": INPUT_ID,
        "request_id": f"SYNTH-stock-request-{code}",
        "output_path": str(directory),
        "rows": {"cohort_events": len(read_frame(directory / "cohort_events.parquet"))},
        "artifacts": [describe_file(directory, path) for path in sorted(directory.glob("*.parquet"))],
    }
    write_json(directory / "receipt.json", row)
    pool_path = root / "phase-stock-result.json"
    pool = read_json(pool_path)
    pool["pool"]["results"].append(row)
    write_json(pool_path, pool)
    global_path = root / "global" / f"{code}.parquet"
    global_frame = read_frame(root / "global" / "0001.parquet")
    global_frame["security_id"] = f"TW:{code}"
    _write(global_path, global_frame)
    barrier_path = root / "global" / "receipt.json"
    global_receipt = read_json(barrier_path)
    global_receipt["global_files"][code] = {"path": str(global_path), "sha256": file_digest(global_path)}
    write_json(barrier_path, global_receipt)
    preparation_path = root / "derived-preparation.json"
    preparation = read_json(preparation_path)
    preparation["ordinary_reference_n"] = len(pool["pool"]["results"])
    write_json(preparation_path, preparation)


def _retained(root: Path) -> Path:
    inventory = _load(root)
    result = recovery.recover_stock(inventory, "0001")
    directory = root / "analysis" / "event-parts" / "synthetic-stock"
    tables = {
        "events": result.events,
        "conditions": result.conditions,
        "group_memberships": result.memberships,
        "daily_groups": pd.DataFrame({"t0": inventory.calendar.strftime("%Y-%m-%d"), "pattern:union": False}),
        "formula_groups": pd.DataFrame({"group_id": ["pattern:union"]}),
    }
    for name, frame in tables.items():
        _write(directory / f"{name}.parquet", frame)
    identity = {
        "code": "0001",
        "target": "L1",
        "source_id": SOURCE["source_id"],
        "input_id": INPUT_ID,
        "stock_request_id": "SYNTH-stock-request",
        "global_sha256": inventory.barrier["global_files"]["0001"]["sha256"],
        "shared_pins": {"labels": inventory.label_pin},
    }
    write_json(
        directory / "receipt.json",
        {
            "schema": "pattern-scan-event-part.v1",
            "complete": True,
            "identity": identity,
            "artifacts": [describe_file(directory, path) for path in sorted(directory.glob("*.parquet"))],
        },
    )
    return directory


def test_saved_union_ids_metadata_boundaries_and_inputs_unchanged(checkpoint: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = {str(path): path.read_bytes() for path in checkpoint.rglob("*") if path.is_file()}
    calls = []

    def observe(events: pd.DataFrame, *args: Any, **kwargs: Any) -> pd.DataFrame:
        calls.append(events.event_id.tolist())
        return project_outcomes(events, *args, **kwargs)

    monkeypatch.setattr(recovery, "project_outcomes", observe)
    result = recovery.recover_stock(_load(checkpoint), "0001")
    original = read_frame(checkpoint / "parts" / "0001" / "cohort_events.parquet")
    expected = original.loc[original.pattern_id.eq("L1") & original.cohort_id.eq("union")]
    assert calls == [expected.event_id.tolist()]
    assert result.events.event_id.drop_duplicates().tolist() == expected.event_id.tolist()
    assert result.events.groupby("event_id").horizon.apply(list).tolist() == [[126, 252], [126, 252]]
    assert result.events.details_json.eq('{"synthetic":"preserve"}').all()
    assert result.events.member_metadata.eq('[{"source":"saved"}]').all()
    assert result.conditions.G_bin.tolist() == ["150to200", "150to200"]
    assert result.conditions.VOL_a_bin.tolist() == ["le070", "le070"]
    assert result.audit["historical_parity_verified"] is False
    assert before == {str(path): path.read_bytes() for path in checkpoint.rglob("*") if path.is_file()}


def test_recovery_uses_shared_full_result_jump_scope_and_first_decision(checkpoint: Path) -> None:
    directory = checkpoint / "parts" / "0001"
    quality = read_frame(directory / "indicators.parquet")
    quality.iloc[12, 0] = "missing_official_quote|invalid_ohlc"
    quality.iloc[137, 0] = "unexplained_adjusted_jump"
    _write(directory / "indicators.parquet", quality)
    _stock_receipts(checkpoint)
    result = recovery.recover_stock(_load(checkpoint), "0001")
    assert result.events.base_label.eq("hit").all()
    assert result.events.loc[result.events.horizon.eq(126), "effective_label"].tolist() == ["hit", "unknown"]
    assert result.events.loc[result.events.horizon.eq(252), "effective_label"].eq("unknown").all()
    assert result.events.loc[result.events.horizon.eq(126), "result_scope_json"].tolist() == ['{"start":11,"end":136}', '{"start":12,"end":137}']


@pytest.mark.parametrize("requested", [(), ("0001", "0001"), ("",), tuple(f"{i:04}" for i in range(6))])
def test_request_bound_is_enforced_before_io(tmp_path: Path, requested: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="one to five"):
        recovery.load_recovery_inventory(
            tmp_path / "absent",
            requested_codes=requested,
            expected_input_id=INPUT_ID,
            expected_source_id=SOURCE["source_id"],
            expected_label_version_id="unused",
            expected_calendar_n=310,
            expected_stock_n=1,
            expected_retained_n=0,
        )


def test_unrequested_stock_is_rejected(checkpoint: Path) -> None:
    with pytest.raises(ValueError, match="approved pilot"):
        recovery.recover_stock(_load(checkpoint), "9999")


@pytest.mark.parametrize(
    "pin", ["expected_input_id", "expected_source_id", "expected_label_version_id", "expected_calendar_n", "expected_stock_n", "expected_retained_n"]
)
def test_fixed_checkpoint_pins_fail_closed(checkpoint: Path, pin: str) -> None:
    with pytest.raises(ValueError):
        _load(checkpoint, **{pin: 2 if pin.endswith("_n") else "different"})


def test_payload_hash_is_not_replaced_by_label_manifest(checkpoint: Path) -> None:
    inventory = _load(checkpoint)
    path = checkpoint / "parts" / "0001" / "base_labels.parquet"
    with path.open("ab") as stream:
        stream.write(b"changed but receipt pin unchanged")
    with pytest.raises(ValueError):
        recovery.recover_stock(inventory, "0001")


@pytest.mark.parametrize("invalid", ["event_id", "missing_horizon", "duplicate_label", "foreign_label"])
def test_event_and_label_relations_fail_closed(checkpoint: Path, invalid: str) -> None:
    directory = checkpoint / "parts" / "0001"
    name = "cohort_events" if invalid == "event_id" else "base_labels"
    frame = read_frame(directory / f"{name}.parquet")
    if invalid == "event_id":
        frame.loc[0, "event_id"] = "not-canonical"
    elif invalid == "missing_horizon":
        frame = frame.iloc[1:]
    elif invalid == "duplicate_label":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    else:
        frame.loc[0, "security_id"] = "TW:9999"
    _write(directory / f"{name}.parquet", frame)
    _stock_receipts(checkpoint)
    with pytest.raises(ValueError):
        recovery.recover_stock(_load(checkpoint), "0001")


def test_retained_validation_projection_matches_saved_rows(checkpoint: Path) -> None:
    _retained(checkpoint)
    result = recovery.recover_stock(_load(checkpoint, expected_retained_n=1), "0001")
    assert result.audit["retained_part_present"] is True
    assert result.audit["historical_parity_verified"] is True
    assert result.audit["event_count"] == 2
    assert result.audit["projection_row_count"] == 4


@pytest.mark.parametrize("invalid", ["payload", "ancestry", "incomplete"])
def test_bad_retained_part_never_falls_back(checkpoint: Path, monkeypatch: pytest.MonkeyPatch, invalid: str) -> None:
    directory = _retained(checkpoint)
    receipt = read_json(directory / "receipt.json")
    if invalid == "payload":
        with (directory / "events.parquet").open("ab") as stream:
            stream.write(b"corrupt retained payload")
    else:
        if invalid == "ancestry":
            receipt["identity"]["stock_request_id"] = "wrong-request"
        else:
            receipt["complete"] = False
        write_json(directory / "receipt.json", receipt)
    monkeypatch.setattr(recovery, "project_outcomes", lambda *args, **kwargs: pytest.fail("invalid retained part was silently reprojected"))
    with pytest.raises(ValueError):
        _load(checkpoint, expected_retained_n=1)


def test_retained_semantic_corruption_is_not_silent_replacement(checkpoint: Path) -> None:
    directory = _retained(checkpoint)
    events = read_frame(directory / "events.parquet")
    events.loc[0, "effective_label"] = "loss"
    _write(directory / "events.parquet", events)
    receipt = read_json(directory / "receipt.json")
    receipt["artifacts"] = [describe_file(directory, directory / record["path"]) for record in receipt["artifacts"]]
    write_json(directory / "receipt.json", receipt)
    with pytest.raises(ValueError, match="parity"):
        recovery.recover_stock(_load(checkpoint, expected_retained_n=1), "0001")


def test_missing_whole_retained_receipt_cannot_silently_become_projection(checkpoint: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = _retained(checkpoint)
    # Preserve every synthetic byte: removing the discoverable receipt name is
    # sufficient to reproduce a missing historical part in the inventory.
    (directory / "receipt.json").rename(directory / "hidden-receipt.json")
    monkeypatch.setattr(recovery, "project_outcomes", lambda *args, **kwargs: pytest.fail("missing historical coverage was silently projected"))
    with pytest.raises(ValueError, match="retained|coverage"):
        _load(checkpoint, expected_retained_n=1)


def test_unexpected_retained_coverage_fails_closed(checkpoint: Path) -> None:
    _retained(checkpoint)
    with pytest.raises(ValueError, match="retained|coverage"):
        _load(checkpoint, expected_retained_n=0)


def test_input_changed_during_read_is_rejected(checkpoint: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = _load(checkpoint)
    original = recovery.read_frame

    def change_after_read(path: Path, **kwargs: Any) -> pd.DataFrame:
        result = original(path, **kwargs)
        if path.name == "indicators.parquet":
            with path.open("ab") as stream:
                stream.write(b"concurrent change")
        return result

    monkeypatch.setattr(recovery, "read_frame", change_after_read)
    with pytest.raises(ValueError, match="changed"):
        recovery.recover_stock(inventory, "0001")


@pytest.mark.parametrize("column,value", [("security_id", "TW:9999"), ("t0", "1999-01-01"), ("calendar_index", 99)])
def test_common_condition_join_identity_is_verified(checkpoint: Path, column: str, value: Any) -> None:
    directory = checkpoint / "parts" / "0001"
    common = read_frame(directory / "common_values.parquet")
    common.loc[common.index[10], column] = value
    _write(directory / "common_values.parquet", common)
    _stock_receipts(checkpoint)
    with pytest.raises(ValueError, match="common"):
        recovery.recover_stock(_load(checkpoint), "0001")


def test_condition_missing_and_not_applicable_preserve_audit(checkpoint: Path) -> None:
    directory = checkpoint / "parts" / "0001"
    common = read_frame(directory / "common_values.parquet")
    common["G_unknown_reason"] = pd.Series(None, index=common.index, dtype=object)
    common["VOL_a_applicable"] = True
    common.loc[common.index[10], ["G", "G_unknown_reason"]] = [float("nan"), "saved-missing"]
    common.loc[common.index[11], "VOL_a_applicable"] = False
    _write(directory / "common_values.parquet", common)
    _stock_receipts(checkpoint)
    result = recovery.recover_stock(_load(checkpoint), "0001")
    assert result.conditions.G_status.tolist() == ["feature_unknown", "known"]
    assert result.conditions.G_reason.tolist() == ["saved-missing", None]
    assert result.conditions.VOL_a_status.tolist() == ["known", "not_applicable"]
    assert result.conditions.VOL_a_reason.tolist() == [None, "outside_condition_cohort"]
    assert pd.isna(result.conditions.G_bin.iloc[0])
    assert pd.isna(result.conditions.VOL_a_bin.iloc[1])
    assert result.events.effective_label.eq("hit").all()


def test_selected_zero_event_stock_is_not_a_missing_stock(checkpoint: Path) -> None:
    directory = checkpoint / "parts" / "0001"
    cohort = read_frame(directory / "cohort_events.parquet")
    _write(directory / "cohort_events.parquet", cohort.loc[cohort.cohort_id.ne("union")])
    _stock_receipts(checkpoint)
    result = recovery.recover_stock(_load(checkpoint), "0001")
    assert result.events.empty and result.conditions.empty and result.memberships.empty
    assert result.audit["event_count"] == result.audit["projection_row_count"] == 0


def test_historical_runtime_differs_without_weakening_active_source_validation(checkpoint: Path) -> None:
    # Keep the active-execution barrier strict: only the historical read adapter
    # may accept a recorded runtime that differs from the current interpreter.
    with pytest.raises(ValueError, match="runtime"):
        barrier.checkpoint_label_entry({"0001": checkpoint / "parts" / "0001"}, source=SOURCE, input_id=INPUT_ID)
    pin = _label_version(checkpoint)
    before = {str(path): path.read_bytes() for path in checkpoint.rglob("*") if path.is_file()}
    inventory = _load(checkpoint, expected_label_version_id=pin)
    assert inventory.label_pin["version_id"] == pin
    assert inventory.label_pin["manifest_sha256"] == pin.removeprefix("checkpoint-only:")
    assert inventory.runtime_audit["original_runtime"] == SOURCE["runtime"]
    assert inventory.runtime_audit["runtime_differs"] is True
    assert inventory.runtime_audit["original_runtime_reexecuted"] is False
    result = recovery.recover_stock(inventory, "0001")
    assert result.events.base_label_version_id.eq(pin).all()
    assert before == {str(path): path.read_bytes() for path in checkpoint.rglob("*") if path.is_file()}


@pytest.mark.parametrize("field", ["runtime", "code", "platform"])
def test_historical_source_body_cannot_change_under_unchanged_id(checkpoint: Path, field: str) -> None:
    path = checkpoint / "derived-preparation.json"
    prepared = read_json(path)
    if field == "runtime":
        prepared["source"]["runtime"]["numpy"] = "different-runtime"
    elif field == "code":
        prepared["source"]["code"]["commit"] = "b" * 40
    else:
        prepared["source"]["platform"] = "different-platform"
    write_json(path, prepared)
    with pytest.raises(ValueError, match="source|identity"):
        _load(checkpoint)


def test_changed_label_descriptor_cannot_reuse_expected_historical_pin(checkpoint: Path) -> None:
    pinned = _label_version(checkpoint)
    receipt_path = checkpoint / "parts" / "0001" / "receipt.json"
    receipt = read_json(receipt_path)
    descriptor = next(row for row in receipt["artifacts"] if row["path"] == "base_labels.parquet")
    descriptor["sha256"] = "b" * 64
    write_json(receipt_path, receipt)
    pool_path = checkpoint / "phase-stock-result.json"
    pool = read_json(pool_path)
    pool["pool"]["results"] = [receipt]
    write_json(pool_path, pool)
    assert _label_version(checkpoint) != pinned
    with pytest.raises(ValueError, match="label.*identity|label.*pin"):
        _load(checkpoint, expected_label_version_id=pinned)


def test_unselected_observed_mutation_between_stocks_is_caught_at_global_gate(checkpoint: Path) -> None:
    _add_synthetic_stock(checkpoint, "0002")
    inventory = _load(checkpoint, requested_codes=("0001", "0002"), expected_stock_n=2)
    unselected = checkpoint / "unselected-observed.bin"
    unselected.write_bytes(b"saved unselected payload")
    inventory._reads.observe(unselected)
    first = recovery.recover_stock(inventory, "0001")
    unselected.write_bytes(b"changed unselected payload")
    second = recovery.recover_stock(inventory, "0002")
    assert first.events.security_id.eq("TW:0001").all()
    assert second.events.security_id.eq("TW:0002").all()
    assert inventory._reads.metrics["scoped_sweeps"] == 4
    assert inventory._reads.metrics["full_sweeps"] == 1
    with pytest.raises(ValueError, match="input changed"):
        inventory._reads.unchanged()


def test_scoped_schedule_preserves_events_q1_and_marginal_results(checkpoint: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_recovery_pilot_v1 as pilot
    from research_core.pattern_scan_q1_counts_v1 import Q1Counts

    _add_synthetic_stock(checkpoint, "0002")

    def run(global_schedule: bool) -> tuple[list[recovery.RecoveryStock], tuple[pd.DataFrame, pd.DataFrame], tuple[pd.DataFrame, pd.DataFrame]]:
        inventory = _load(checkpoint, requested_codes=("0001", "0002"), expected_stock_n=2)
        if global_schedule:
            original = inventory._reads.unchanged
            monkeypatch.setattr(inventory._reads, "unchanged", lambda paths=None: original())
        q1 = Q1Counts("L1", ("pattern:union",))
        marginal = pilot._marginal_cells()
        recovered = []
        for code in inventory.requested_codes:
            stock = recovery.recover_stock(inventory, code)
            recovered.append(stock)
            q1.add_stock(code, stock.events, stock.memberships, markets=stock.markets)
            pilot._marginal_add(marginal, stock.events, stock.conditions, stock.markets)
        inventory._reads.unchanged()
        inventory._reads.unchanged()
        if not global_schedule:
            assert inventory._reads.metrics["full_sweeps"] == 3
            assert inventory._reads.metrics["scoped_sweeps"] == 4
        return recovered, q1.finalize(), pilot._marginal_finalize(marginal)

    scoped, scoped_q1, scoped_marginal = run(False)
    global_result, global_q1, global_marginal = run(True)
    for actual, expected in zip(scoped, global_result, strict=True):
        pd.testing.assert_frame_equal(actual.events, expected.events, check_exact=True)
        pd.testing.assert_frame_equal(actual.conditions, expected.conditions, check_exact=True)
        pd.testing.assert_frame_equal(actual.memberships, expected.memberships, check_exact=True)
        pd.testing.assert_series_equal(actual.markets, expected.markets, check_exact=True)
    for actual, expected in zip((*scoped_q1, *scoped_marginal), (*global_q1, *global_marginal), strict=True):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
