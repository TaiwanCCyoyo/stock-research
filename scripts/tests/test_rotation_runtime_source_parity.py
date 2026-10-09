"""Synthetic parity against preserved historical bytes; never loads market artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
import types
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
TASK = REPO / "tasks/20260823-rotation-universe"
MEMBERS = {
    "eligibility": "eligibility.py",
    "features": "features.py",
    "builder": "build_rotation_universe.py",
    "ranker": "candidates/rotation_ranker.py",
}


@pytest.fixture
def implementations() -> Iterator[dict[str, dict[str, types.ModuleType]]]:
    """Restore import aliases and path even when source import or a test fails."""
    aliases = ("eligibility", "features", "engine", "engine.strategy_base")
    saved = {name: sys.modules.get(name) for name in aliases}
    old_path = sys.path.copy()
    try:
        engine = types.ModuleType("engine")
        engine.__path__ = [str(REPO / "StockProject/engine")]
        base_path = REPO / "StockProject/engine/strategy_base.py"
        base = types.ModuleType("engine.strategy_base")
        base.__file__ = str(base_path)
        sys.modules["engine"] = engine
        sys.modules["engine.strategy_base"] = base
        exec(compile(base_path.read_bytes(), str(base_path), "exec"), base.__dict__)

        result: dict[str, dict[str, types.ModuleType]] = {}
        with zipfile.ZipFile(TASK / "original-source.zip") as archive:
            for variant in ("original", "current"):
                modules: dict[str, types.ModuleType] = {}
                for key, relative in MEMBERS.items():
                    path = TASK / relative
                    source = archive.read(relative) if variant == "original" else path.read_bytes()
                    module = types.ModuleType(f"_rotation_{variant}_{key}")
                    module.__file__ = str(path)
                    exec(compile(source, str(path), "exec"), module.__dict__)
                    modules[key] = module
                    if key in ("eligibility", "features"):
                        sys.modules[key] = module
                result[variant] = modules
        yield result
    finally:
        sys.path[:] = old_path
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture
def synthetic() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2019-01-02", periods=180)
    rows = []
    codes = [f"SYN_{letter}" for letter in "ABCDEF"]
    for ordinal, code in enumerate(codes):
        for day, date in enumerate(dates):
            if (code == "SYN_A" and day == 40) or (code == "SYN_F" and day < 90):
                continue
            close = 100.0 + ordinal * 3 + day * (ordinal + 1) / 50
            rows.append({
                "Code": code,
                "Date": date,
                "Open": close - 0.2,
                "High": close + 1,
                "Low": close - 1,
                "Close": close,
                "Volume": 1.0 if code == "SYN_E" else 2000.0,
            })
    frame = pd.DataFrame(rows).sort_values(["Code", "Date"]).reset_index(drop=True)
    frame.loc[(frame["Code"] == "SYN_C") & (frame["Date"] == dates[70]), "Close"] = float("nan")
    frame.loc[(frame["Code"] == "SYN_B") & (frame["Date"] == dates[75]), "Volume"] = 0.0
    meta = pd.DataFrame({"Code": codes, "industry_category": ["SYNTHETIC"] * len(codes)})
    return frame, meta


def test_feature_and_eligibility_parity(implementations: Any, synthetic: Any) -> None:
    prices, meta = synthetic
    before = prices.copy(deep=True)
    meta_before = meta.copy(deep=True)
    outputs = {}
    for name, modules in implementations.items():
        eligibility = modules["eligibility"]
        columns = eligibility.add_eligibility_columns(prices)
        matrix = eligibility.eligible_matrix(prices, "2019-01-02", "2020-01-01")
        features = modules["features"].compute(prices, meta)
        outputs[name] = (columns, matrix, features)
        assert matrix.loc[matrix["Code"].isin(["SYN_E", "SYN_F"]), "eligible"].eq(False).all()
        assert matrix["eligible"].any()  # Ensure meaningful ranks, not only all-NaN parity.
        assert features["cohort_ret_20"].notna().any()
        for _, group in prices.groupby("Code", sort=False):
            turnovers = (group["Close"] * group["Volume"]).tolist()
            vector = matrix.loc[matrix["Code"] == group.iloc[0]["Code"], "eligible"].tolist()
            # The historical scalar rule does not define NaN turnover handling;
            # compare its vector/scalar contract only on fully known windows.
            # NaN rows remain in the strict original/current frame comparison.
            for i, expected in enumerate(vector):
                if all(pd.notna(value) for value in turnovers[max(0, i - eligibility.LIQ_WINDOW) : i]):
                    assert expected == eligibility.is_eligible(i, turnovers[:i])
        pd.testing.assert_frame_equal(prices, before, check_exact=True)
        pd.testing.assert_frame_equal(meta, meta_before, check_exact=True)
    for original, current in zip(outputs["original"], outputs["current"], strict=True):
        pd.testing.assert_frame_equal(original, current, check_exact=True)


@pytest.mark.parametrize("variant", ["original", "current"])
def test_each_implementation_reads_only_past(implementations: Any, synthetic: Any, variant: str) -> None:
    prices, meta = synthetic
    modules = implementations[variant]
    cut = sorted(prices["Date"].unique())[-21]
    truncated = prices.loc[prices["Date"] <= cut].copy()
    before = truncated.copy(deep=True)
    full = modules["features"].compute(prices, meta)
    short = modules["features"].compute(truncated, meta)
    pd.testing.assert_frame_equal(full.loc[full["Date"] <= cut].reset_index(drop=True), short.reset_index(drop=True), check_exact=True)
    full_eligible = modules["eligibility"].eligible_matrix(prices, "2019-01-02", str(pd.Timestamp(cut).date()))
    short_eligible = modules["eligibility"].eligible_matrix(truncated, "2019-01-02", str(pd.Timestamp(cut).date()))
    pd.testing.assert_frame_equal(full_eligible, short_eligible, check_exact=True)
    pd.testing.assert_frame_equal(truncated, before, check_exact=True)


@pytest.mark.parametrize("floor", [50000.0, 100000.0, 200000.0])
def test_builder_parity(implementations: Any, synthetic: Any, floor: float) -> None:
    prices, _ = synthetic
    before = prices.copy(deep=True)
    original = implementations["original"]["builder"].build(prices, floor)
    current = implementations["current"]["builder"].build(prices, floor)
    assert original[0] == current[0]
    pd.testing.assert_series_equal(original[1], current[1], check_exact=True)
    assert "SYN_E" not in current[0] and "SYN_F" not in current[0]
    pd.testing.assert_frame_equal(prices, before, check_exact=True)


class RecordingBroker:
    initial_cash = 100000.0
    fee_rate = 0.001

    def __init__(self) -> None:
        self.positions = {"SYN_D": 10}
        self.calls: list[tuple[Any, ...]] = []

    def get_position(self, code: str) -> int:
        return self.positions.get(code, 0)

    def execution_price(self, code: str, price: float) -> float:
        return price

    def sell(self, code: str, price: float, quantity: int, date: Any) -> None:
        self.calls.append(("sell", code, price, quantity, date))
        self.positions[code] = 0

    def buy(self, code: str, price: float, quantity: int, date: Any) -> bool:
        self.calls.append(("buy", code, price, quantity, date))
        self.positions[code] = quantity
        return True


def test_ranker_parity_with_ties_nan_and_ineligible(implementations: Any, monkeypatch: Any) -> None:
    table = pd.DataFrame({
        "Code": [f"SYN_{c}" for c in "ABCDE"],
        "Date": [pd.Timestamp("2019-09-02")] * 5,
        "eligible": [True, True, True, True, False],
        "r_ret_20": [0.8, 0.8, float("nan"), 0.1, 1.0],
        "r_ret_60": [0.4] * 5,
    })
    before = table.copy(deep=True)

    def fake_parquet(path: Any, *args: Any, **kwargs: Any) -> pd.DataFrame:
        assert Path(path) == TASK / "features.parquet"
        return table.copy(deep=True)

    monkeypatch.setattr(pd, "read_parquet", fake_parquet)
    outputs = []
    for variant in ("original", "current"):
        broker = RecordingBroker()
        ranker = implementations[variant]["ranker"].RotationRanker(broker, context={"top_k": 2, "exit_rank": 2, "weights": {"r_ret_20": 1.0, "r_ret_60": 0.0}})
        ranker.on_bar(pd.Timestamp("2019-09-02"), {f"SYN_{c}": {"Close": 100.0} for c in "ABCDE"})
        assert broker.calls[0][0:2] == ("sell", "SYN_D")
        assert len(broker.calls) == 3
        assert "SYN_E" not in ranker.ranking["2019-09-02"]
        outputs.append((ranker.ranking, ranker.rank_of, broker.calls))
        with pytest.raises(ValueError, match="every weight is zero"):
            implementations[variant]["ranker"].RotationRanker(broker, context={"weights": {"r_ret_20": 0.0}})
    assert outputs[0] == outputs[1]
    pd.testing.assert_frame_equal(table, before, check_exact=True)


def test_preserved_archive_and_runtime_identities_match() -> None:
    """Reject drift before comparing current formulas with frozen originals."""
    manifest = json.loads((TASK / "typed-source-provenance.json").read_text(encoding="utf-8"))
    archive = TASK / manifest["originalArchive"]
    assert "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["archiveDigest"]
    with zipfile.ZipFile(archive) as original:
        assert set(original.namelist()) == {entry["path"] for entry in manifest["files"]}
        for entry in manifest["files"]:
            frozen = original.read(entry["path"])
            runtime = (TASK / entry["path"]).read_bytes()
            assert len(frozen) == entry["originalBytes"]
            assert "sha256:" + hashlib.sha256(frozen).hexdigest() == entry["originalDigest"]
            assert len(runtime) == entry["typedBytes"]
            assert "sha256:" + hashlib.sha256(runtime).hexdigest() == entry["typedDigest"]
