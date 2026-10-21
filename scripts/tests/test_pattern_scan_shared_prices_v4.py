"""Synthetic metadata and mocked as-of reads; never opens actual price datasets."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import maintained_adjusted_daily as maintained
from research_core import pattern_scan_shared_prices_v4 as shared
from research_core.artifact_store import canonical, file_digest, object_digest, write_json


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = tmp_path / "shared"
    generation = "synthetic-fixed-generation"
    directory = root / "derived" / maintained.FAMILY / "generations" / generation
    directory.mkdir(parents=True)
    # Exact approved geometry, deliberately synthetic session dates (no input
    # pins or real published data are read). Missing business days are harmless
    # here because neither the adapter nor this mocked reader calculates prices.
    days = [*pd.bdate_range(shared.START, periods=shared.SESSIONS - 1), pd.Timestamp(shared.CUTOFF)]
    calendar = pd.DatetimeIndex(days, name="approved_calendar")
    descriptors = {}
    for role in ("raw", "actions", "calendar"):
        path = directory / f"{role}.parquet"
        path.write_bytes(f"synthetic {role} descriptor payload; not Parquet".encode())
        descriptors[role] = {"file": path.name, "bytes": path.stat().st_size, "sha256": file_digest(path)}
    fingerprint = {
        "captured_at_utc": "historical-capture",
        "inputs": {
            "price_daily": {"path": "synthetic-price-source", "bytes": 10, "sha256": "a" * 64, "rows": 20},
            "corporate_actions": {"path": "synthetic-actions-source", "bytes": 12, "wal": None, "tables": {"corporate_actions": {"rows": 3}}},
        },
    }
    status: dict[str, Any] = {
        "schema": maintained.SCHEMA,
        "family": maintained.FAMILY,
        "generation": generation,
        "asof": "2026-10-15",
        "definition": {"prices": "price-basis.v2"},
        "source_policy": {"kept": "official"},
        "input_fingerprint": fingerprint,
        "bases": {"raw": descriptors["raw"]},
        "as_of_inputs": {role: descriptors[role] for role in ("actions", "calendar")},
    }
    status_path = directory / "status.json"
    write_json(status_path, status)
    # There is no current.json. Every access must pass the fixed generation.
    numeric = ("Open", "High", "Low", "Close", "RawOpen", "RawHigh", "RawLow", "RawClose", "VolumeLots", "Turnover", "restatement_factor")
    values: dict[str, Any] = {name: np.arange(len(calendar), dtype=np.float64) for name in numeric}
    values.update(
        Quality=np.ones(len(calendar), dtype=bool),
        quality_reason=pd.Series([None] * len(calendar), dtype=object),
        volume_status=pd.Series(["observed"] * len(calendar), dtype=object),
        corporate_action_types=pd.Series([""] * len(calendar), dtype=object),
    )
    prices = pd.DataFrame(values).loc[:, maintained.ARROW_SCHEMA.names[2:]]
    prices["Open"] = prices["Open"].astype("float32")  # Detect any adapter value/dtype coercion.
    prices.loc[1, "Close"] = np.nan
    prices.loc[1, "Quality"] = False
    prices.loc[1, "quality_reason"] = "missing_official_quote"
    frame = prices.copy()
    frame.insert(0, "Date", pd.Series(calendar, index=frame.index))
    frame.insert(0, "Code", "0001")
    calls = []

    def reader(basis: str, **kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
        assert basis == shared.BASIS and kwargs["root"] == root and kwargs["generation"] == generation
        assert kwargs["as_of"] == shared.CUTOFF and kwargs["codes"] == ["0001"]
        assert "columns" not in kwargs  # Validate full rows before projection.
        pd.testing.assert_index_equal(kwargs["calendar"], calendar)
        calls.append(kwargs)
        record = {
            "family": maintained.FAMILY,
            "generation": generation,
            "status_sha256": file_digest(status_path),
            "basis": basis,
            "definition": shared.DEFINITION,
            "as_of": shared.CUTOFF,
            "actions_sha256": descriptors["actions"]["sha256"],
            "codes": 1,
            "calendar": {
                "source": "caller",
                "sessions": shared.SESSIONS,
                "first": shared.START,
                "last": shared.CUTOFF,
                "sha256": object_digest(calendar.strftime("%Y-%m-%d").tolist()),
            },
            # The maintained API's requested-basis locator is not the actual
            # as-of raw input; the adapter must use status raw/actions instead.
            "file": "unused-requested-basis.parquet",
            "sha256": "f" * 64,
        }
        return frame.copy(deep=True), record

    monkeypatch.setattr(maintained, "read_adjusted_daily", reader)
    for name in ("update", "load_inputs", "compute"):
        monkeypatch.setattr(maintained, name, lambda *args, **kwargs: pytest.fail("no source read/build/calculation permitted"))
    return {
        "root": root,
        "generation": generation,
        "calendar": calendar,
        "directory": directory,
        "status": status,
        "status_path": status_path,
        "fingerprint": fingerprint,
        "frame": frame,
        "prices": prices,
        "reader": reader,
        "calls": calls,
    }


def _reference(case: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return shared.make_price_reference(case["root"], case["generation"], case["calendar"], **kwargs)


def test_reference_pins_actual_inputs_and_ignores_unconsumed_fingerprint_roles(case: dict[str, Any]) -> None:
    expected = deepcopy(case["fingerprint"])
    expected["captured_at_utc"] = "different-capture"
    expected["inputs"]["symbol_meta"] = {"unconsumed_metadata": True}
    reference = _reference(case, expected_fingerprint=expected)
    assert reference["schema"] == shared.SCHEMA and reference["definition"] == "price-basis.v2"
    assert reference["status_sha256"] == file_digest(case["status_path"])
    assert reference["basis"] == shared.BASIS and reference["cutoff"] == "2026-10-12"
    assert reference["calendar"]["sha256"] == object_digest(reference["calendar"]["dates"])
    assert set(reference["input_fingerprint"]) == {"price_daily", "corporate_actions"}
    for role in ("raw", "actions", "calendar"):
        path = case["directory"] / f"{role}.parquet"
        assert reference["inputs"][role] == {"path": str(path), "bytes": path.stat().st_size, "sha256": file_digest(path)}
    assert case["calls"] == []
    canonical(reference)  # The reference is an ordinary serializable JSON record.


def test_frames_preserve_full_values_dtypes_index_and_stock_metadata_without_second_read(case: dict[str, Any]) -> None:
    reference = _reference(case)
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in case["root"].rglob("*") if path.is_file()}
    actual = shared.read_reference_frame(reference, "0001")
    expected = case["prices"].copy()
    expected.index = case["calendar"]
    pd.testing.assert_frame_equal(actual, expected, check_exact=True, check_dtype=True)
    stock = shared.as_stock_prices(actual, "0001")
    expected_stock = expected.copy()
    expected_stock["security_id"] = "TW:0001"
    expected_stock["calendar_index"] = np.arange(len(expected), dtype=np.int64)
    expected_stock["asof_date"] = np.asarray(case["calendar"].strftime("%Y-%m-%d"), dtype=object)
    pd.testing.assert_frame_equal(stock, expected_stock, check_exact=True, check_dtype=True)
    assert len(case["calls"]) == 1
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)  # Pure helper never modifies its input.
    subset = shared.read_reference_frame(reference, "0001", stock_part=True, columns=["Close", "security_id", "calendar_index", "asof_date"])
    pd.testing.assert_frame_equal(subset, expected_stock.loc[:, subset.columns], check_exact=True, check_dtype=True)
    assert len(case["calls"]) == 2
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in case["root"].rglob("*") if path.is_file()}


@pytest.mark.parametrize("role", ["price_daily", "corporate_actions"])
def test_conflicting_consumed_fingerprint_refuses_binding(case: dict[str, Any], role: str) -> None:
    expected = deepcopy(case["fingerprint"])
    expected["inputs"][role]["bytes"] += 1
    with pytest.raises(ValueError, match="fingerprints differ"):
        _reference(case, expected_fingerprint=expected)
    assert not case["calls"]


@pytest.mark.parametrize("damage", ["source", "definition", "asof", "missing_actions", "raw_size", "raw_path", "status_generation"])
def test_incompatible_generation_metadata_refuses_binding(case: dict[str, Any], damage: str) -> None:
    status = case["status"]
    if damage == "source":
        status["source_policy"]["kept"] = "other"
    elif damage == "definition":
        status["definition"]["prices"] = "price-basis.v999"
    elif damage == "asof":
        status["asof"] = "2026-10-09"
    elif damage == "missing_actions":
        status["as_of_inputs"].pop("actions")
    elif damage == "raw_size":
        status["bases"]["raw"]["bytes"] += 1
    elif damage == "raw_path":
        status["bases"]["raw"]["file"] = "../raw.parquet"
    else:
        status["generation"] = "another-generation"
    case["status_path"].write_bytes(canonical(status))
    with pytest.raises(ValueError):
        _reference(case)
    assert not case["calls"]


@pytest.mark.parametrize("damage", ["short", "duplicate", "reverse", "timezone", "intraday", "start", "end", "unit"])
def test_invalid_calendar_geometry_refused_before_any_read(case: dict[str, Any], damage: str) -> None:
    calendar = case["calendar"]
    if damage == "short":
        calendar = calendar[:-1]
    elif damage == "duplicate":
        calendar = pd.DatetimeIndex([calendar[0], *calendar[:-1]])
    elif damage == "reverse":
        calendar = calendar[::-1]
    elif damage == "timezone":
        calendar = calendar.tz_localize("UTC")
    elif damage == "intraday":
        calendar = calendar + pd.Timedelta(hours=1)
    elif damage == "start":
        calendar = pd.DatetimeIndex([pd.Timestamp("2010-01-03"), *calendar[1:]])
    elif damage == "end":
        calendar = pd.DatetimeIndex([*calendar[:-1], pd.Timestamp("2026-10-13")])
    else:
        calendar = calendar.as_unit("us")
    with pytest.raises(ValueError, match="calendar"):
        shared.make_price_reference(case["root"], case["generation"], calendar)
    assert not case["calls"]


def test_root_must_be_physical_external_and_generation_never_falls_back(case: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        shared.make_price_reference(Path("relative"), case["generation"], case["calendar"])
    checkout = tmp_path / "other-checkout"
    (checkout / ".git").mkdir(parents=True)
    inside = checkout / "shared"
    inside.mkdir()
    with pytest.raises(ValueError, match="outside"):
        shared.make_price_reference(inside, case["generation"], case["calendar"])
    # Even an available current pointer must never substitute for a pruned pin.
    write_json(case["root"] / "derived" / maintained.FAMILY / "current.json", {"generation": case["generation"]})
    with pytest.raises(FileNotFoundError, match="not available"):
        shared.make_price_reference(case["root"], "pruned-generation", case["calendar"])
    for generation in ("", "../escape", ".staging", "wrong\\path"):
        with pytest.raises(ValueError):
            shared.make_price_reference(case["root"], generation, case["calendar"])
    assert not case["calls"]


@pytest.mark.parametrize("damage", ["status", "reference_sha", "calendar_sha", "input_path", "basis", "schema"])
def test_changed_status_or_reference_pin_rejected_before_reader(case: dict[str, Any], damage: str) -> None:
    reference = _reference(case)
    if damage == "status":
        case["status"]["changed_after_binding"] = True
        case["status_path"].write_bytes(canonical(case["status"]))
    elif damage == "reference_sha":
        reference["status_sha256"] = "0" * 64
    elif damage == "calendar_sha":
        reference["calendar"]["sha256"] = "0" * 64
    elif damage == "input_path":
        reference["inputs"]["raw"]["path"] = str(case["root"] / "elsewhere.parquet")
    else:
        reference[damage] = "different"
    with pytest.raises(ValueError):
        shared.read_reference_frame(reference, "0001")
    assert not case["calls"]


@pytest.mark.parametrize("damage", ["code", "date_order", "date_dtype", "missing_column", "column_order", "record_sha", "record_calendar"])
def test_bad_reader_rows_or_returned_pins_fail_even_for_narrow_projection(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, damage: str) -> None:
    reference = _reference(case)

    def bad_reader(*args: Any, **kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
        frame, record = case["reader"](*args, **kwargs)
        if damage == "code":
            frame.loc[0, "Code"] = "another"
        elif damage == "date_order":
            frame = frame.iloc[::-1]
        elif damage == "date_dtype":
            frame["Date"] = frame["Date"].astype("datetime64[us]")
        elif damage == "missing_column":
            frame = frame.drop(columns="quality_reason")
        elif damage == "column_order":
            frame = frame.loc[:, list(reversed(frame.columns))]
        elif damage == "record_sha":
            record["status_sha256"] = "0" * 64
        else:
            record["calendar"]["sha256"] = "0" * 64
        return frame, record

    monkeypatch.setattr(maintained, "read_adjusted_daily", bad_reader)
    with pytest.raises(ValueError):
        shared.read_reference_frame(reference, "0001", columns=["Close"])


@pytest.mark.parametrize("code", ["", " 0001", "0001 ", 1, None])
def test_original_code_identity_is_never_coerced(case: dict[str, Any], code: Any) -> None:
    with pytest.raises(ValueError, match="code string"):
        shared.read_reference_frame(_reference(case), code)
    assert not case["calls"]


@pytest.mark.parametrize("filename", ["status.json", "raw.parquet"])
def test_shared_status_and_payload_hardlink_aliases_refused(case: dict[str, Any], tmp_path: Path, filename: str) -> None:
    os.link(case["directory"] / filename, tmp_path / f"alias-{filename}")
    with pytest.raises(ValueError, match="hardlink"):
        _reference(case)
    assert not case["calls"]


@pytest.mark.parametrize("columns", [["unknown"], ["Close", "Close"], "Close"])
def test_invalid_column_projection_rejected(case: dict[str, Any], columns: Any) -> None:
    with pytest.raises(ValueError, match="columns"):
        shared.read_reference_frame(_reference(case), "0001", columns=columns)
