"""Synthetic published checkpoint extensions equal full v2 recomputation."""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from research_core import derived_features_chunk_v2 as kernel
from research_core import research_data_incremental as incremental
from research_core.artifact_store import file_digest
from research_core.hhhl_variants_paths import outcomes_for_closes
from research_core.market_context import compute_context_rows
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots


def frame(n: int, code: int = 0) -> pd.DataFrame:
    close = 100 + code + 10 * np.sin(np.arange(n) / 4)
    result = pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True},
        index=pd.DatetimeIndex(pd.bdate_range("2010-01-04", periods=n).values, name="Date"),
    )
    if n > 60:
        result.iloc[58, result.columns.get_loc("Quality")] = False
    return result


@pytest.fixture
def catalog(tmp_path: Path) -> DataCatalog:
    (tmp_path / "primary/.git").mkdir(parents=True)
    return DataCatalog(DataRoots.from_env({DATA_ROOT_ENV: str(tmp_path / "primary/research_data")}))


def build(catalog: DataCatalog, data: dict[str, pd.DataFrame], names: list[str], base: dict | None = None, factors: dict[str, str] | None = None) -> dict:
    return incremental.build_incremental_features(
        catalog, data, names, factor_ids=factors or {code: "factor-v1" for code in data}, price_basis="synthetic", base=base, calculation_authorized=True
    )


def test_published_extensions_and_checkpoint_roundtrips_equal_full(catalog: DataCatalog):
    names = ["SMA20", "EMA10", "ATR14", "pivots_1p5"]
    original = build(catalog, {"INVENTED": frame(55)}, names)
    discovery = catalog.get(original["data_id"], original["version_id"], manifest_sha256=original["manifest"]["sha256"])
    assert "stocks" not in discovery and "implementation" not in discovery
    original_path = catalog.roots.data / Path(original["manifest"]["path"]).parent
    before = {path.relative_to(original_path).as_posix(): file_digest(path) for path in original_path.rglob("*") if path.is_file()}
    second = build(catalog, {"INVENTED": frame(72)}, names, original)
    third = build(catalog, {"INVENTED": frame(96)}, names, second)
    assert second["extension_receipt"]["initialized_feature_rows"] == 0
    assert second["extension_receipt"]["processed_new_rows"] == 17 * len(names)
    for feature in names:
        actual_daily, actual_pivots = incremental.load_incremental_feature(catalog, third, "INVENTED", feature)
        expected_daily, expected_pivots, _ = kernel.compute_selected_full(frame(96), [feature])
        pd.testing.assert_frame_equal(actual_daily, expected_daily, check_exact=True)
        pd.testing.assert_frame_equal(actual_pivots, expected_pivots, check_exact=True)
    assert before == {path.relative_to(original_path).as_posix(): file_digest(path) for path in original_path.rglob("*") if path.is_file()}


def test_same_request_zero_compute_and_added_feature_only_initializes_missing(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch):
    data = {"INVENTED": frame(50)}
    first = build(catalog, data, ["SMA20"])
    full = Mock(wraps=kernel.compute_selected_full)
    chunk = Mock(wraps=kernel.compute_selected_chunk)
    monkeypatch.setattr(kernel, "compute_selected_full", full)
    monkeypatch.setattr(kernel, "compute_selected_chunk", chunk)
    same = build(catalog, data, ["SMA20"], first)
    assert same == first
    full.assert_not_called()
    chunk.assert_not_called()
    extra = build(catalog, data, ["SMA20", "BB20_Upper"], first)
    assert full.call_count == 1 and full.call_args.args[1] == ["BB20_Upper"]
    assert extra["extension_receipt"]["reused_features"] == 1
    old_daily, _ = incremental.load_incremental_feature(catalog, first, "INVENTED", "SMA20")
    new_daily, _ = incremental.load_incremental_feature(catalog, extra, "INVENTED", "SMA20")
    pd.testing.assert_frame_equal(old_daily, new_daily, check_exact=True)


@pytest.mark.parametrize("correction", ["historical_price", "factor"])
def test_only_corrected_stock_rebuilds(catalog: DataCatalog, correction: str):
    data = {"A": frame(40), "B": frame(40, 1)}
    first = build(catalog, data, ["EMA10"])
    more = {"A": frame(43), "B": frame(43, 1)}
    factors = {"A": "factor-v1", "B": "factor-v1"}
    if correction == "historical_price":
        more["A"].iloc[2, more["A"].columns.get_loc("Close")] += 0.1
    else:
        factors["A"] = "factor-v2"
    result = build(catalog, more, ["EMA10"], first, factors)
    assert result["extension_receipt"]["stocks"]["A"]["full_stock_rebuild"] is True
    assert result["extension_receipt"]["stocks"]["B"]["full_stock_rebuild"] is False
    assert result["extension_receipt"]["initialized_feature_rows"] == 43
    assert result["extension_receipt"]["processed_new_rows"] == 3
    for code in more:
        actual, _ = incremental.load_incremental_feature(catalog, result, code, "EMA10")
        expected, _, _ = kernel.compute_selected_full(more[code], ["EMA10"])
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)


@pytest.mark.parametrize("horizon", [10, 126, 252])
def test_future_tail_update_equals_retained_full_label_definition(horizon: int):
    old = 10 + np.arange(280, dtype=float) / 10
    new = 10 + np.arange(300, dtype=float) / 10
    old[250] = np.nan
    new[250] = np.nan
    actual, receipt = incremental.update_outcome_tail(old, new, outcomes_for_closes(old, horizon), horizon)
    expected = outcomes_for_closes(new, horizon)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert receipt["tail_start"] == 280 - horizon
    assert receipt["recalculated_rows"] == horizon + 20


def test_no_authorization_no_write_and_missing_segment_no_recompute(catalog: DataCatalog):
    with pytest.raises(PermissionError):
        incremental.build_incremental_features(catalog, {"A": frame(20)}, ["SMA5"], factor_ids={"A": "factor-v1"}, price_basis="synthetic")
    assert not catalog.roots.data.exists()
    first = build(catalog, {"A": frame(20)}, ["SMA5"])
    path = catalog.roots.data / Path(first["manifest"]["path"]).parent / "stocks/A/SMA5/checkpoint.json"
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        build(catalog, {"A": frame(21)}, ["SMA5"], first)


@pytest.mark.parametrize("layer", ["past_only", "retrospective"])
def test_context_tail_and_event_checkpoint_equal_full(layer: str):
    dates = pd.bdate_range("2010-01-04", periods=110).strftime("%Y-%m-%d").tolist()
    closes: list[float | None] = []
    for value, count in [(100.0, 25), (110.0, 30), (120.0, 25), (90.0, 30)]:
        closes.extend([value] * count)
    old_rows = compute_context_rows(dates[:72], closes[:72], layer=layer)
    actual, receipt = incremental.update_context_tail(dates[:72], closes[:72], dates[:93], closes[:93], old_rows, layer=layer)
    assert actual == compute_context_rows(dates[:93], closes[:93], layer=layer)
    final, new_receipt = incremental.update_context_tail(
        dates[:93], closes[:93], dates, closes, actual, layer=layer, event_checkpoint=receipt["checkpoint_before_tail"]
    )
    assert final == compute_context_rows(dates, closes, layer=layer)
    assert new_receipt["recalculated_rows"] == 17 + (10 if layer == "retrospective" else 0)


@pytest.mark.parametrize("horizon", [126, 252])
def test_published_label_tails_equal_full_and_preserve_old_version(catalog: DataCatalog, horizon: int):
    dates = pd.DatetimeIndex(pd.bdate_range("2010-01-04", periods=300).values, name="Date")
    closes = 10 + np.arange(300, dtype=float) / 10
    first = incremental.publish_forward_series(
        catalog, "INVENTED", dates[:280], closes[:280], price_basis="synthetic", factor_id="factor-v1", horizon=horizon, calculation_authorized=True
    )
    manifest = catalog.roots.data / first["manifest"]["path"]
    before = file_digest(manifest)
    second = incremental.publish_forward_series(
        catalog, "INVENTED", dates[:291], closes[:291], price_basis="synthetic", factor_id="factor-v1", horizon=horizon, base=first, calculation_authorized=True
    )
    third = incremental.publish_forward_series(
        catalog, "INVENTED", dates, closes, price_basis="synthetic", factor_id="factor-v1", horizon=horizon, base=second, calculation_authorized=True
    )
    actual = incremental.load_forward_series(catalog, third)
    expected = outcomes_for_closes(closes, horizon)
    expected.index = dates
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert second["extension_receipt"]["recalculated_rows"] == horizon + 11
    assert file_digest(manifest) == before


@pytest.mark.parametrize("layer", ["past_only", "retrospective"])
def test_published_context_tail_equals_full(catalog: DataCatalog, layer: str):
    dates = pd.DatetimeIndex(pd.bdate_range("2010-01-04", periods=90).values, name="Date")
    closes = np.r_[np.full(25, 100.0), np.full(30, 110.0), np.full(20, 120.0), np.full(15, 90.0)]
    first = incremental.publish_forward_series(
        catalog, "0050", dates[:65], closes[:65], price_basis="synthetic", factor_id="factor-v1", context_layer=layer, calculation_authorized=True
    )
    second = incremental.publish_forward_series(
        catalog, "0050", dates[:76], closes[:76], price_basis="synthetic", factor_id="factor-v1", context_layer=layer, base=first, calculation_authorized=True
    )
    third = incremental.publish_forward_series(
        catalog, "0050", dates, closes, price_basis="synthetic", factor_id="factor-v1", context_layer=layer, base=second, calculation_authorized=True
    )
    actual = incremental.load_forward_series(catalog, third)
    expected = pd.DataFrame(compute_context_rows(dates.strftime("%Y-%m-%d").tolist(), closes.tolist(), layer=layer), index=dates)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_forward_basis_factor_change_rebuilds_and_same_request_reuses(catalog: DataCatalog, monkeypatch: pytest.MonkeyPatch):
    dates = pd.DatetimeIndex(pd.bdate_range("2010-01-04", periods=40).values, name="Date")
    closes = np.linspace(10, 15, 40)
    first = incremental.publish_forward_series(
        catalog, "A", dates, closes, price_basis="synthetic", factor_id="factor-v1", horizon=10, calculation_authorized=True
    )
    compute = Mock(wraps=incremental.outcomes_for_closes)
    monkeypatch.setattr(incremental, "outcomes_for_closes", compute)
    same = incremental.publish_forward_series(
        catalog, "A", dates, closes, price_basis="synthetic", factor_id="factor-v1", horizon=10, base=first, calculation_authorized=True
    )
    assert same == first
    compute.assert_not_called()
    second = incremental.publish_forward_series(
        catalog, "A", dates, closes, price_basis="synthetic", factor_id="factor-v2", horizon=10, base=first, calculation_authorized=True
    )
    assert second["extension_receipt"]["mode"] == "full_rebuild"
    assert second["version_id"] != first["version_id"]
