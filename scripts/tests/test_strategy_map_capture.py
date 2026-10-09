"""Daily membership shares the map projection and fractional metric contract."""

from __future__ import annotations

from typing import Any

import pytest

from research_core.opportunity_history_store import LazyHistoryStore
from research_core.strategy_map_capture import HistoryCapture, appears_on_map


def row(metric: float | None = 100, basis: str = "actual", launch: str | None = "2021-04-28", end: str | None = None) -> dict[str, Any]:
    return {"growth": {"sizingGainPct": metric, "basis": basis}, "launchCandidate": {"date": launch} if launch else None, "endConfirmedAt": end}


@pytest.mark.parametrize(
    "value,expected",
    [
        (row(), True),
        (row(99), False),
        (row(100, "annualized"), True),
        (row(None), False),
        (row(float("nan")), False),
        (row(500, "unknown"), False),
        (row(500, launch=None), False),
        (row(500, launch="2021-04-30"), False),
        (row(500, end="2021-04-29"), False),
    ],
)
def test_membership_defaults_match_launched_map(value: dict[str, Any], expected: bool) -> None:
    assert appears_on_map(value, "2021-04-29") is expected


def test_optional_catalog_mode_and_tolerance():
    assert appears_on_map(row(100 - 5e-10, launch=None), "2021-04-29", mode="catalog")
    assert not appears_on_map(row(100 - 2e-9), "2021-04-29")
    with pytest.raises(ValueError):
        appears_on_map(row(), "2021-04-29", mode="invalid")


def test_capture_selects_security_but_reuses_actual_frame_function(monkeypatch: pytest.MonkeyPatch) -> None:
    import research_core.strategy_map_capture as module

    provider = LazyHistoryStore()

    class Store:
        identity = "fixed"
        dates = ["2021-04-29"]
        series: dict[str, dict[str, Any]] = {"2609": {}}
        securities = {"2609": {"name": "陽明"}, "2330": {"name": "台積電"}}
        catalog = {"securities": securities, "retained": "all other verified frame inputs"}

    monkeypatch.setattr(provider, "store", Store())

    def project(catalog: dict[str, Any], date: str) -> dict[str, Any]:
        assert list(catalog["securities"]) == ["2609"]
        assert catalog["retained"] == Store.catalog["retained"]
        return {"rows": [row(200) | {"name": "陽明", "waveId": "wave", "start": "2021-02-01"}]}

    monkeypatch.setattr(module, "build_frame", project)
    capture = HistoryCapture(provider)
    result = capture("2609", "2021-04-29")
    assert result is not None
    assert result["onMap"] is True
    assert result["metric"] == 2.0
    missing_date = capture("2609", "2020-01-01")
    missing_stock = capture("not-covered", "2021-04-29")
    assert missing_date is not None and missing_date["onMap"] is None
    assert missing_stock is not None and missing_stock["onMap"] is None
    assert len(Store.securities) == 2
