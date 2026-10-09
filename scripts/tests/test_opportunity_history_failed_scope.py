from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from typing import Any

import pytest

from scripts import opportunity_history_native_validation as validation
from scripts.build_opportunity_history import code_identity


def native_payload() -> dict[str, Any]:
    prices = [100, 120, 150, 180, 134, 100]
    series = {
        "schema": "opportunity-series.v1",
        "raw": prices,
        "adjusted": prices,
        "numeric_flags": {},
        "series_id": "fixture-series",
        "security_id": "fixture-security",
        "calendar_id": "fixture-calendar",
    }
    runs: list[int | None] = [0] * len(prices)
    native = {
        "code_identity": code_identity(),
        "source_run_indices": runs,
        "native": [
            {
                "method": method,
                "scale": scale,
                "status": "ok",
                "result": {
                    "waves": validation.expected_baseline_waves(series, runs, scale),
                    "segments": [],
                    "launches": [],
                    "diagnostics": {"noise": validation.expected_noise(series, runs)},
                },
            }
            for method, scale in sorted(validation.PAIRS)
        ],
        "support_records": [],
    }
    calendar = {"calendar_id": "fixture-calendar", "dates": [f"2020-01-{index + 1:02}" for index in range(len(prices))]}
    return {"series": series, "calendar": calendar, "native": native}


def direct_verify(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(validation.NODE), str(validation.SOURCE_GATE), "--verify"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize("failed_count", [1, 6])
def test_failed_scopes_remain_partial_and_never_enter_success_cache(failed_count: int) -> None:
    payload = native_payload()
    validation.validate_native_semantics(payload["native"], payload["series"], payload["calendar"])
    before = list(validation._VERIFIED)
    changed = deepcopy(payload)
    for record in changed["native"]["native"][:failed_count]:
        record.update({"status": "error", "result": None, "error": {"message": "saved failure"}})
    changed["native"]["support_records"] = validation.expected_support_records(changed["native"])
    completed = direct_verify(changed)
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "partial"
    assert receipt["failed_method_count"] == len(receipt["failed_scopes"]) == failed_count
    assert receipt["method_count"] == 6 - failed_count
    for _ in range(2):
        with pytest.raises(ValueError, match="Partial native source semantics.*cannot verify"):
            validation.validate_native_semantics(changed["native"], changed["series"], changed["calendar"])
        assert list(validation._VERIFIED) == before


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "status"])
def test_direct_source_gate_rejects_invalid_scope_set(mutation: str) -> None:
    payload = native_payload()
    records = payload["native"]["native"]
    if mutation == "missing":
        records.pop()
    elif mutation == "duplicate":
        records[0] = deepcopy(records[1])
    elif mutation == "unknown":
        records[0]["method"] = "fabricated"
    else:
        records[0]["status"] = "fabricated"
    completed = direct_verify(payload)
    assert completed.returncode != 0
    assert "six unique known" in completed.stderr or "Invalid native method status" in completed.stderr
