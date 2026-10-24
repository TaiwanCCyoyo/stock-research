"""The application exposes both direct and frontend-proxy data routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from research_api.main import create_app


@pytest.mark.parametrize("prefix", ["", "/api"])
@pytest.mark.parametrize(
    ("path", "schema"),
    [
        ("/data-status", "research-data-status.v1"),
        ("/data-series/v1/institutional/DEMO", "research-data-series.v1"),
        ("/data-series/v1/monthly-revenue/DEMO", "research-data-series.v1"),
    ],
)
def test_application_mounts_data_routes_in_synthetic_mode(monkeypatch: pytest.MonkeyPatch, prefix: str, path: str, schema: str) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    response = TestClient(create_app()).get(prefix + path)
    assert response.status_code == 200
    assert response.json()["schema"] == schema
    assert "虛構" in str(response.json())
