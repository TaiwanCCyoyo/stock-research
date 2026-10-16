from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_feature_preview_v1 as preview
from research_core.artifact_store import describe_file, write_json
from research_core.pattern_scan_feature_preview_v1 import (
    COMMON_COLUMNS,
    INDICATOR_COLUMNS,
    INDICATOR_INPUT_COLUMNS,
    PIVOT_COLUMNS,
    project_frames,
)
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from scripts import preview_pattern_scan_features as preview_cli

DATES = pd.bdate_range("2020-01-02", periods=4, name="date")


class Prepared(TypedDict):
    source: dict[str, object]
    input_id: str
    producer_fingerprint: dict[str, object]
    ordinary_reference_n: int
    calendar_n: int


class CompletedSource(TypedDict):
    repo: Path
    source: Path
    stock: Path
    result: Path
    tables: dict[str, pd.DataFrame]
    prepared: Prepared


def _value(column: str, row: int) -> object:
    if column in {"security_id", "code"}:
        return "TW:2330"
    if column == "t0":
        return 0
    if column in {"calendar_index", "extreme_index", "confirmation_index"}:
        return row
    if column in {"asof_date", "date", "extreme_date", "confirmed_at", "t0"}:
        return DATES[row]
    if column.endswith("_json"):
        return "{}"
    if column.startswith("is_") or column.endswith("_eligible") or column.endswith("_valid"):
        return True
    return 100.0 + row


def _indicators() -> pd.DataFrame:
    frame = pd.DataFrame(
        {column: [_value(column, i) for i in range(len(DATES))] for column in INDICATOR_INPUT_COLUMNS},
        index=DATES,
    )
    frame["asof_date"] = [date.strftime("%Y-%m-%d") for date in DATES]
    frame["BBUpper"] = frame["BB20_Upper"] = 110.0
    frame["BBLower"] = frame["BB20_Lower"] = 90.0
    return frame


def _common() -> pd.DataFrame:
    frame = pd.DataFrame(
        {column: [_value(column, i) for i in range(len(DATES))] for column in COMMON_COLUMNS},
        index=DATES,
    )
    frame["t0"] = DATES
    return frame


def _pivots() -> pd.DataFrame:
    row = {column: _value(column, 1) for column in PIVOT_COLUMNS}
    row.update(
        k=1.5,
        kind="high",
        extreme_index=0,
        confirmation_index=1,
        extreme_date=DATES[0],
        confirmed_at=DATES[1],
        price=120.0,
        asof_date=DATES[1],
        security_id="TW:2330",
    )
    return pd.DataFrame([row])


def test_projection_preserves_values_and_removes_raw_prices_and_aliases() -> None:
    indicators, pivots, common = _indicators(), _pivots(), _common()
    originals = (indicators.copy(deep=True), pivots.copy(deep=True), common.copy(deep=True))

    result = project_frames(indicators, pivots, common, code="2330")

    assert set(result) == {"daily_indicators", "confirmed_pivots", "daily_conditions"}
    daily = result["daily_indicators"]
    assert tuple(daily.columns) == INDICATOR_COLUMNS
    forbidden = {
        "Open",
        "High",
        "Low",
        "Close",
        "RawOpen",
        "RawHigh",
        "RawLow",
        "RawClose",
        "Volume",
        "VolumeLots",
        "Turnover",
        "restatement_factor",
        "corporate_action_types",
        "BBUpper",
        "BBLower",
    }
    assert forbidden.isdisjoint(daily.columns)
    for column in daily.columns:
        pd.testing.assert_series_equal(daily[column], indicators[column], check_names=True)
    pd.testing.assert_frame_equal(result["confirmed_pivots"], pivots)
    pd.testing.assert_frame_equal(result["daily_conditions"], common)
    for actual, original in zip((indicators, pivots, common), originals, strict=True):
        pd.testing.assert_frame_equal(actual, original)


@pytest.mark.parametrize("which", ["indicators", "pivots", "common"])
@pytest.mark.parametrize("damage", ["missing", "extra", "duplicate"])
def test_exact_schema_is_required(which: str, damage: str) -> None:
    frames = {"indicators": _indicators(), "pivots": _pivots(), "common": _common()}
    frame = frames[which]
    if damage == "missing":
        frames[which] = frame.drop(columns=[str(frame.columns[0])])
    elif damage == "extra":
        frame = frame.copy()
        frame["unexpected"] = 1
        frames[which] = frame
    else:
        frame = frame.copy()
        frame.columns = list(frame.columns[:-1]) + [frame.columns[0]]
        frames[which] = frame
    with pytest.raises(ValueError):
        project_frames(frames["indicators"], frames["pivots"], frames["common"], code="2330")


@pytest.mark.parametrize("field", ["security_id", "calendar_index", "t0", "asof_date"])
def test_inconsistent_daily_identity_is_rejected(field: str) -> None:
    indicators, pivots, common = _indicators(), _pivots(), _common()
    if field in indicators:
        indicators.loc[DATES[2], field] = "9999" if field == "security_id" else 999
    elif field in common:
        common.loc[DATES[2], field] = "9999" if field == "security_id" else pd.Timestamp("1999-01-01") if field == "t0" else 999
    with pytest.raises(ValueError):
        project_frames(indicators, pivots, common, code="2330")


@pytest.mark.parametrize(
    "field,value",
    [
        ("extreme_date", pd.Timestamp("1999-01-01")),
        ("confirmed_at", pd.Timestamp("1999-01-01")),
        ("extreme_index", 2),
        ("confirmation_index", 4),
        ("kind", "sideways"),
        ("k", 9),
        ("price", 0.0),
    ],
)
def test_invalid_confirmed_pivots_are_rejected(field: str, value: object) -> None:
    pivots = _pivots()
    pivots.loc[0, field] = value
    with pytest.raises(ValueError):
        project_frames(_indicators(), pivots, _common(), code="2330")


def test_divergent_bollinger_aliases_are_rejected() -> None:
    indicators = _indicators()
    assert "BBUpper" in indicators and "BB20_Upper" in indicators
    indicators.loc[DATES[1], "BBUpper"] += 1
    with pytest.raises(ValueError):
        project_frames(indicators, _pivots(), _common(), code="2330")


@pytest.fixture
def completed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CompletedSource:
    repo = tmp_path / "repo"
    source_root = repo / "source"
    stock = source_root / "stock"
    stock.mkdir(parents=True)
    source_identity: dict[str, object] = {"schema": "synthetic-source.v1", "source_id": "original-source", "code": {"commit": "a" * 40}}
    input_id = "original-input"
    tables = {
        "indicators.parquet": _indicators(),
        "pivots.parquet": _pivots(),
        "common_values.parquet": _common(),
    }
    descriptors = []
    for name, frame in tables.items():
        path = stock / name
        with path.open("xb") as stream:
            write_frame(frame, stream, index=True)
        descriptors.append(describe_file(stock, path))
        tables[name] = read_frame(path)
    row = {
        "code": "2330",
        "complete": True,
        "source_id": source_identity["source_id"],
        "input_id": input_id,
        "output_path": str(stock),
        "artifacts": descriptors,
    }
    write_json(stock / "receipt.json", row)
    prepared: Prepared = {
        "source": source_identity,
        "input_id": input_id,
        "producer_fingerprint": {"inputs": {"synthetic": "fingerprint"}},
        "ordinary_reference_n": 1,
        "calendar_n": len(DATES),
    }
    write_json(source_root / "derived-preparation.json", prepared)
    stock_result = {
        "phase": "full_stock_checkpoints",
        "pool": {"complete": True, "results": [row]},
    }
    stock_result_path = source_root / "phase-stock-result.json"
    write_json(stock_result_path, stock_result)

    def write_fake_receipt(path: Path, **kwargs: object) -> None:
        write_json(path, {"synthetic": True, "run_id": kwargs["run_id"], "definition": kwargs["definition"]})

    monkeypatch.setattr(preview, "write_run_receipt", write_fake_receipt)
    return {"repo": repo, "source": source_root, "stock": stock, "result": stock_result_path, "tables": tables, "prepared": prepared}


def test_build_preview_writes_verified_zstd_projection_and_preserves_lineage(completed_source: CompletedSource) -> None:
    repo = completed_source["repo"]
    destination = repo / ".tmp" / "candidate"
    manifest = preview.build_preview(completed_source["result"], destination, repo_root=repo)

    assert manifest["numerical_source"] == completed_source["prepared"]["source"]
    assert manifest["input_id"] == completed_source["prepared"]["input_id"]
    for table_name, expected in zip(
        ("daily_indicators", "confirmed_pivots", "daily_conditions"),
        (completed_source["tables"]["indicators.parquet"], completed_source["tables"]["pivots.parquet"], completed_source["tables"]["common_values.parquet"]),
        strict=True,
    ):
        path = destination / "2330" / f"{table_name}.parquet"
        pd.testing.assert_frame_equal(
            read_frame(path), expected.loc[:, list(INDICATOR_COLUMNS)] if table_name == "daily_indicators" else expected, check_exact=True
        )
        assert pq.ParquetFile(path).metadata.row_group(0).column(0).compression == "ZSTD"


def test_build_preview_rejects_selected_source_hash_pollution_without_final(completed_source: CompletedSource) -> None:
    stock = completed_source["stock"]
    with (stock / "indicators.parquet").open("ab") as stream:
        stream.write(b"pollution")
    destination = completed_source["repo"] / ".tmp" / "candidate"
    with pytest.raises(ValueError, match="hash|size"):
        preview.build_preview(completed_source["result"], destination, repo_root=completed_source["repo"])
    assert not destination.exists()


def test_build_preview_requires_destination_under_repo_tmp(completed_source: CompletedSource) -> None:
    destination = completed_source["repo"] / "outside" / "candidate"
    with pytest.raises(ValueError, match=r"\.tmp"):
        preview.build_preview(completed_source["result"], destination, repo_root=completed_source["repo"])
    assert not destination.exists()


def test_build_preview_refuses_existing_destination_without_changing_bytes(completed_source: CompletedSource) -> None:
    destination = completed_source["repo"] / ".tmp" / "candidate"
    preview.build_preview(completed_source["result"], destination, repo_root=completed_source["repo"])
    original_manifest = (destination / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        preview.build_preview(completed_source["result"], destination, repo_root=completed_source["repo"])
    assert (destination / "manifest.json").read_bytes() == original_manifest


def test_preview_cli_passes_paths_and_repeated_code_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stock_result = tmp_path / "phase-stock-result.json"
    destination = tmp_path / ".tmp" / "preview"
    calls: list[tuple[Path, Path, Path, tuple[str, ...] | None]] = []

    def capture_build(stock_path: Path, destination_path: Path, *, repo_root: Path, codes: tuple[str, ...] | None = None) -> dict[str, object]:
        calls.append((stock_path, destination_path, repo_root, codes))
        return {}

    monkeypatch.setattr(preview_cli, "build_preview", capture_build)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preview_pattern_scan_features.py",
            "--stock-result",
            str(stock_result),
            "--destination",
            str(destination),
            "--code",
            "2330",
            "--code",
            "2317",
        ],
    )
    preview_cli.main()

    assert calls == [(stock_result, destination, Path(preview_cli.__file__).resolve().parents[1], ("2330", "2317"))]
