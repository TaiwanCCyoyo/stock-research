"""Synthetic adapter checks; no market tables or probability outcomes are read."""

import ast
import hashlib
import sqlite3
import sys
import types
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_rule_source import SOURCE_HASHES, load_rule
from research_core.hhhl_v4_source import prepare_v4_prices

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "tasks/20261010-hhhl-v4-probability/sources"
V1_SOURCES = ROOT / "tasks/20261009-hhhl-pattern-probability/sources"
V4_FILES = ("hhhl_rule_v4.py", "bigrange_v4.py", "adjprice.py", "detect.py")


def source_bytes(name: str) -> bytes:
    with zipfile.ZipFile(SOURCES / "hhhl_rule_v4.zip") as archive:
        return archive.read(name)


def synthetic_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2026-08-01", periods=17, freq="D").strftime("%Y-%m-%d")
    close = np.arange(100.0, 117.0)
    raw = pd.DataFrame({
        "asof_date": dates,
        "RawOpen": close,
        "RawHigh": close + 1.0,
        "RawLow": close - 1.0,
        "RawClose": close,
        "VolumeLots": np.full(len(close), 100.0),
        "atr14_pct": np.full(len(close), 0.01),
    })
    raw.loc[4, "RawHigh"] = np.nan
    actions = pd.DataFrame(
        [
            {"code": "1234", "ex_date": "2026-08-06", "event_type": "cash_dividend", "price_factor": 0.9},
            {"code": "1234", "ex_date": "2026-08-15", "event_type": "cash_dividend", "price_factor": 0.8},
            {"code": "5678", "ex_date": None, "event_type": "cash_dividend", "price_factor": None},
        ],
    )
    return raw, actions


def synthetic_signal_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    t = np.arange(360, dtype=float)
    close = 100.0 + 0.1 * t + 5.0 * np.sin(2.0 * np.pi * t / 20.0)
    volume = np.full(len(t), 100.0)
    for index in range(20, len(t)):
        if close[index] > close[index - 20 : index].max():
            volume[index] = 300.0
    raw = pd.DataFrame({
        "asof_date": pd.date_range("2025-08-01", periods=len(t), freq="D").strftime("%Y-%m-%d"),
        "RawOpen": close,
        "RawHigh": close + 0.3,
        "RawLow": close - 0.3,
        "RawClose": close,
        "VolumeLots": volume,
        "atr14_pct": np.full(len(t), 0.01),
    })
    actions = pd.DataFrame({column: pd.Series(dtype="object") for column in ("code", "ex_date", "event_type", "price_factor")})
    return raw, actions


def _source_detect() -> Callable[[pd.DataFrame], list[dict[str, Any]]]:
    detect_ns: dict[str, Any] = {"np": np}
    detect_tree = ast.parse(source_bytes("detect.py").decode("utf-8"))
    pivots: list[ast.stmt] = [node for node in detect_tree.body if isinstance(node, ast.FunctionDef) and node.name == "pivots_atr"]
    assert len(pivots) == 1
    exec(compile(ast.Module(body=pivots, type_ignores=[]), "detect.py", "exec"), detect_ns)
    detect_module = types.ModuleType("detect")
    detect_module.__dict__["pivots_atr"] = detect_ns["pivots_atr"]

    bigrange_ns: dict[str, Any] = {}
    with patch.dict(sys.modules, {"detect": detect_module}):
        exec(compile(source_bytes("bigrange_v4.py"), "bigrange_v4.py", "exec"), bigrange_ns)
    bigrange_module = types.ModuleType("bigrange_v4")
    bigrange_module.__dict__.update(bigrange_ns)
    direct_ns: dict[str, Any] = {}
    with patch.dict(sys.modules, {"detect": detect_module, "bigrange_v4": bigrange_module}):
        exec(compile(source_bytes("hhhl_rule_v4.py"), "hhhl_rule_v4.py", "exec"), direct_ns)
    return cast(Callable[[pd.DataFrame], list[dict[str, Any]]], direct_ns["detect"])


def _frames_equal_ignoring_attrs(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    actual_copy = actual.copy(deep=True)
    actual_copy.attrs = expected.attrs.copy()
    pd.testing.assert_frame_equal(actual_copy, expected, check_exact=True)


def test_v4_whitelist_hashes_and_source_seams_are_exact() -> None:
    assert tuple(SOURCE_HASHES["hhhl_rule_v4"]) == V4_FILES
    with zipfile.ZipFile(SOURCES / "hhhl_rule_v4.zip") as archive:
        assert sorted(archive.namelist()) == sorted(V4_FILES)
        for name in V4_FILES:
            assert hashlib.sha256(archive.read(name)).hexdigest() == SOURCE_HASHES["hhhl_rule_v4"][name]

    frozen = load_rule(SOURCES, "hhhl_rule_v4")
    direct = _source_detect()
    raw, actions = synthetic_frames()
    prepared = prepare_v4_prices(raw, actions, "1234", sources=SOURCES)
    assert frozen.rule_id == "hhhl_rule_v4"
    assert frozen.k == 1.5
    assert frozen.source_hashes == SOURCE_HASHES["hhhl_rule_v4"]
    assert frozen.detect(prepared) == direct(prepared)


def test_v4_archive_member_and_byte_tampering_are_rejected(tmp_path: Path) -> None:
    archive_path = SOURCES / "hhhl_rule_v4.zip"
    with zipfile.ZipFile(archive_path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}

    with zipfile.ZipFile(tmp_path / "hhhl_rule_v4.zip", "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
        archive.writestr("extra.py", b"pass\n")
    with pytest.raises(ValueError, match="members mismatch"):
        load_rule(tmp_path, "hhhl_rule_v4")

    members["adjprice.py"] += b"\n# changed\n"
    with zipfile.ZipFile(tmp_path / "hhhl_rule_v4.zip", "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="hash mismatch: adjprice.py"):
        load_rule(tmp_path, "hhhl_rule_v4")


def test_v1_loader_contract_remains_unchanged() -> None:
    rule = load_rule(V1_SOURCES, "hhhl_rule_v1")
    assert rule.rule_id == "hhhl_rule_v1"
    assert rule.k == 1.5
    assert rule.source_hashes == SOURCE_HASHES["hhhl_rule_v1"]
    assert set(rule.source_hashes) == {"hhhl_rule_v1.py", "detect.py"}


def test_v4_rule_has_signal_parity_and_prefix_consistency() -> None:
    raw, empty_actions = synthetic_signal_frames()
    prepared = prepare_v4_prices(raw, empty_actions, "1234", sources=SOURCES)
    frozen = load_rule(SOURCES, "hhhl_rule_v4")
    direct = _source_detect()

    direct_events = direct(prepared)
    frozen_events = frozen.detect(prepared)
    assert direct_events
    assert any(event["pattern"] for event in direct_events)
    assert frozen_events == direct_events
    for stop in (100, 200, 300):
        expected_prefix = [event for event in direct_events if event["t"] < stop]
        assert frozen.detect(prepared.iloc[:stop]) == expected_prefix


def test_prepare_prices_preserves_dropna_factor_cutoff_and_wilder() -> None:
    raw, actions = synthetic_frames()
    raw_before, actions_before = raw.copy(deep=True), actions.copy(deep=True)
    result = prepare_v4_prices(raw, actions, "1234", sources=SOURCES)

    assert len(result) == 16
    assert "2026-08-05" not in result["asof_date"].tolist()
    assert result["asof_date"].iloc[0] == "2026-08-01"
    np.testing.assert_allclose(result["div_factor"].to_numpy()[:4], 0.9)
    np.testing.assert_allclose(result["div_factor"].to_numpy()[4:], 1.0)

    high = result["High"].to_numpy(dtype=float)
    low = result["Low"].to_numpy(dtype=float)
    close = result["Close"].to_numpy(dtype=float)
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - np.r_[np.nan, close[:-1]]), np.abs(low - np.r_[np.nan, close[:-1]])),
    )
    tr[0] = high[0] - low[0]
    expected_atr = np.full(len(result), np.nan)
    expected_atr[13] = tr[:14].mean()
    for index in range(14, len(result)):
        expected_atr[index] = (expected_atr[index - 1] * 13 + tr[index]) / 14
    np.testing.assert_allclose(result["atr14_pct"].to_numpy(), expected_atr / close, equal_nan=True)

    metadata = result.attrs["preparation_metadata"]
    assert metadata["dropped_missing_ohlc_rows"] == 1
    assert metadata["excluded_invalid_action_rows"] == 1
    assert metadata["applied_action_rows"] == 1
    assert metadata["applied_action_dates"] == ("2026-08-06",)
    pd.testing.assert_frame_equal(raw, raw_before)
    pd.testing.assert_frame_equal(actions, actions_before)


def test_prepare_prices_uses_memory_only_io_seams() -> None:
    raw, actions = synthetic_frames()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external price/action I/O was attempted")

    with (
        patch.object(pd, "read_parquet", side_effect=forbidden),
        patch.object(pd, "read_sql", side_effect=forbidden),
        patch.object(sqlite3, "connect", side_effect=forbidden),
        patch.object(urllib.request, "urlopen", side_effect=forbidden),
    ):
        prepared = prepare_v4_prices(raw, actions, "1234", sources=SOURCES)
    assert len(prepared) == 16


def test_action_date_factor_and_duplicate_guards_are_scoped_to_applied_rows() -> None:
    raw, actions = synthetic_frames()
    bad_date = actions.iloc[[0]].copy()
    bad_date.loc[:, "ex_date"] = "2026-08-0z"
    with pytest.raises(ValueError, match="valid ISO date"):
        prepare_v4_prices(raw, bad_date, "1234", sources=SOURCES)

    infinite = actions.iloc[[0]].copy()
    infinite.loc[:, "ex_date"] = "2026-08-08"
    infinite.loc[:, "price_factor"] = np.inf
    with pytest.raises(ValueError, match="must be finite"):
        prepare_v4_prices(raw, infinite, "1234", sources=SOURCES)

    duplicate = pd.concat([actions.iloc[[0]], actions.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate applied action code/ex_date"):
        prepare_v4_prices(raw, duplicate, "1234", sources=SOURCES)

    raw_duplicate = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate asof_date"):
        prepare_v4_prices(raw_duplicate, actions, "1234", sources=SOURCES)

    unrelated = pd.concat(
        [
            actions,
            pd.DataFrame([{"code": "9999", "ex_date": "not-a-date", "event_type": "cash_dividend", "price_factor": 1.1}]),
        ],
        ignore_index=True,
    )
    result = prepare_v4_prices(raw, unrelated, "1234", sources=SOURCES)
    assert result.attrs["preparation_metadata"]["applied_action_rows"] == 1


def test_empty_and_nonfinite_raw_frames_fail_clearly() -> None:
    raw, actions = synthetic_frames()
    empty = raw.iloc[0:0].copy()
    with pytest.raises(ValueError, match="cannot prepare an empty frame"):
        prepare_v4_prices(empty, actions, "1234", sources=SOURCES)

    raw.loc[0, "RawClose"] = np.inf
    with pytest.raises(ValueError, match="OHLC values must be finite"):
        prepare_v4_prices(raw, actions, "1234", sources=SOURCES)


def test_synthetic_result_matches_unmodified_adjprice_load_with_memory_io() -> None:
    raw, actions = synthetic_frames()
    actual = prepare_v4_prices(raw, actions, "1234", sources=SOURCES)
    original_ns: dict[str, Any] = {}
    exec(compile(source_bytes("adjprice.py"), "adjprice.py", "exec"), original_ns)
    original_factors = original_ns["_factors"]
    original_factors.cache_clear()

    class MemoryConnection:
        def close(self) -> None:
            return None

    def read_raw(_path: object, *, columns: list[str]) -> pd.DataFrame:
        return raw.loc[:, columns].copy()

    with (
        patch.object(sqlite3, "connect", return_value=MemoryConnection()),
        patch.object(pd, "read_sql", return_value=actions.copy(deep=True)),
        patch.object(pd, "read_parquet", side_effect=read_raw),
    ):
        expected = original_ns["load"]("1234")
    _frames_equal_ignoring_attrs(actual, expected)


def test_nondefault_cutoff_matches_original_adjprice_filter() -> None:
    raw, actions = synthetic_frames()
    cutoff = "2026-08-04"
    actual = prepare_v4_prices(raw, actions, "1234", cutoff=cutoff, sources=SOURCES)

    original_ns: dict[str, Any] = {}
    exec(compile(source_bytes("adjprice.py"), "adjprice.py", "exec"), original_ns)
    original_ns["CUTOFF"] = cutoff
    original_ns["_factors"].cache_clear()

    class MemoryConnection:
        def close(self) -> None:
            return None

    def read_raw(_path: object, *, columns: list[str]) -> pd.DataFrame:
        return raw.loc[:, columns].copy()

    with (
        patch.object(sqlite3, "connect", return_value=MemoryConnection()),
        patch.object(pd, "read_sql", return_value=actions.copy(deep=True)),
        patch.object(pd, "read_parquet", side_effect=read_raw),
    ):
        expected = original_ns["load"]("1234")
    _frames_equal_ignoring_attrs(actual, expected)
    np.testing.assert_allclose(actual["div_factor"].to_numpy(), 1.0)
