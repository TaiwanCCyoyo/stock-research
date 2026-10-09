from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from scripts.build_opportunity_history import code_identity
from scripts.opportunity_history_native_validation import (
    PAIRS,
    expected_baseline_waves,
    expected_noise,
    validate_native_semantics,
)


@pytest.mark.parametrize(
    ("tail", "expected_ends"),
    [
        ([1.5488300560039703, 1.4992965889882885, 1.4513472624308077, 1.404931413594948, 1.36], [None, None]),
        ([1.4898398641517403, 1.3872642630097975, 1.2917510007156756, 1.202813834640073, 1.12], [8, 10]),
    ],
)
@pytest.mark.parametrize("mutation", ["scale", "drawdown"])
def test_directional_endpoints_preserve_javascript_float_boundaries(tail: list[float], expected_ends: list[int | None], mutation: str) -> None:
    # These two source goldens differed from a Python math.log/math.exp port.
    prices = [1.0, 1.0985605433061179, 1.2068352673090326, 1.3257816069359947, 1.4564513624208644, 1.6, *tail]
    series: dict[str, Any] = {
        "schema_version": "opportunity-series.v1",
        "adjusted": prices,
        "raw": prices,
        "numeric_flags": {},
        "series_id": "fixture-series",
        "security_id": "fixture-security",
        "calendar_id": "fixture-calendar",
    }
    runs: list[int | None] = [0] * len(prices)
    waves = expected_baseline_waves(series, runs, "fine")
    assert [wave["id"] for wave in waves] == ["wave-small-0", "wave-large-1"]
    assert [wave["end"] for wave in waves] == expected_ends
    assert all(wave["start"] == 0 and wave["peak"] == 5 for wave in waves)
    assert all(wave["gain"] == pytest.approx(60) for wave in waves)

    native: dict[str, Any] = {
        "code_identity": code_identity(),
        "source_run_indices": runs,
        "native": [
            {
                "method": method,
                "scale": scale,
                "status": "ok",
                "result": {
                    "waves": expected_baseline_waves(series, runs, scale),
                    "segments": [],
                    "launches": [],
                    "diagnostics": {"noise": expected_noise(series, runs)},
                },
            }
            for method, scale in sorted(PAIRS)
        ],
        "support_records": [],
    }
    calendar = {"calendar_id": "fixture-calendar", "dates": [f"2020-01-{index + 1:02}" for index in range(len(prices))]}
    validate_native_semantics(native, series, calendar)
    # A prior successful check must not authorize changed evidence in the same process.
    changed = deepcopy(native)
    record = next(record for record in changed["native"] if record["scale"] == "fine")
    field, value = ("scale", "large") if mutation == "scale" else ("maxDrawdown", 999)
    record["result"]["waves"][0][field] = value
    with pytest.raises(ValueError):
        validate_native_semantics(changed, series, calendar)
