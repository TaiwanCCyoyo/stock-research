"""Real bounded synthetic reuse through the shared builder adapter."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core.research_data_builder import build_feature_blocks
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots
from research_core.stock_feature_pool_v2 import make_stock_request

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="actual Windows owned processes")


def test_second_consumer_zero_compute_and_added_column_only_fills_gap(tmp_path: Path):
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    catalog = DataCatalog(DataRoots.from_env({DATA_ROOT_ENV: str(primary / "research_data")}))
    close = 50 + np.sin(np.arange(130) / 4) * 8
    prepared = pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True}, index=pd.bdate_range("2010-01-04", periods=130, name="Date")
    )
    path = primary / "invented.parquet"
    prepared.to_parquet(path)
    request = make_stock_request(path, "INVENTED", ["SMA20"], price_basis="synthetic")
    with pytest.raises(PermissionError):
        build_feature_blocks(catalog, [request], primary / "unauthorized")
    first = build_feature_blocks(catalog, [request], primary / ".tmp/first", calculation_authorized=True)
    second = build_feature_blocks(catalog, [request], primary / ".tmp/second", calculation_authorized=True)
    more = make_stock_request(path, "INVENTED", ["SMA20", "BB20_Upper"], price_basis="synthetic")
    third = build_feature_blocks(catalog, [more], primary / ".tmp/third", calculation_authorized=True)
    assert (first["computed_n"], first["reused_n"]) == (1, 0)
    assert (second["computed_n"], second["reused_n"], second["effective_workers"]) == (0, 1, 0)
    assert (third["computed_n"], third["reused_n"]) == (1, 1)
    assert first["references"][0] == second["references"][0]
