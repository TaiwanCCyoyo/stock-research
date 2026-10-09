"""Exercise the pinned JS semantic gate without private catalog artifacts."""

from __future__ import annotations

import json
import math
import subprocess
from collections import OrderedDict
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import pytest

from scripts import opportunity_history_native_validation as gate
from scripts.opportunity_native_receipt_cache import semantic_receipt_cache


@pytest.fixture(scope="module")
def original_native() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    values = [math.exp(-0.01 * min(index, 19) + 0.03 * max(0, min(index - 19, 40)) - 0.02 * max(0, index - 59)) for index in range(90)]
    calendar = {
        "calendar_id": "semantic-test-calendar",
        "dates": [(date(2020, 1, 1) + timedelta(days=index)).isoformat() for index in range(len(values))],
    }
    series = {
        "schema": "opportunity-series.v1",
        "code": "TEST",
        "security_id": "semantic-test-stock",
        "series_id": "semantic-test-series",
        "calendar_id": calendar["calendar_id"],
        "raw": values,
        "adjusted": values,
        "numeric_flags": {},
    }
    methods_uri = gate.SOURCE_GATE.with_name("opportunity_history_methods.mjs").as_uri()
    javascript = f"""
        import {{ analyzeSeries, codeIdentity, sha256 }} from {json.dumps(methods_uri)};
        let text = "";
        for await (const chunk of process.stdin) text += chunk;
        const {{ series, calendar }} = JSON.parse(text);
        const native = analyzeSeries(series, calendar, {{
            identity: await codeIdentity(),
            inputIdentity: {{
                series_sha256: sha256(Buffer.from(JSON.stringify(series))),
                calendar_sha256: sha256(Buffer.from(JSON.stringify(calendar))),
            }},
        }});
        process.stdout.write(JSON.stringify(native));
    """
    completed = subprocess.run(
        [str(gate.NODE), "--input-type=module", "-e", javascript],
        input=json.dumps({"series": series, "calendar": calendar}, allow_nan=False),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    native = json.loads(completed.stdout)
    assert len(native["native"]) == 6
    assert all(record["status"] == "ok" for record in native["native"])
    assert any(record["result"]["waves"] for record in native["native"])
    assert any(record["result"]["launches"] for record in native["native"])
    assert any(record["result"]["segments"] for record in native["native"])
    return native, series, calendar


def test_original_six_method_results_pass(
    original_native: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    gate.validate_native_semantics(*original_native)


def test_disk_receipt_reuses_exact_inputs_and_invalidates_changed_price_or_source(
    original_native: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    native, series, calendar = original_native
    calls: list[str] = []
    original_call = gate._call_source

    def tracked_call(encoded: str, mode: str) -> str:
        calls.append(mode)
        return original_call(encoded, mode)

    monkeypatch.setattr(gate, "_call_source", tracked_call)
    monkeypatch.setattr(gate, "_VERIFIED", OrderedDict())
    with semantic_receipt_cache(tmp_path):
        gate.validate_native_semantics(native, series, calendar)
        assert calls == ["--verify"]
        gate._VERIFIED.clear()  # A fresh server process has no memory receipt.
        gate.validate_native_semantics(native, series, calendar)
        assert calls == ["--verify"]
        changed = deepcopy(series)
        changed["raw"][0] *= 1.001
        gate._VERIFIED.clear()
        gate.validate_native_semantics(native, changed, calendar)
        assert calls == ["--verify", "--verify"]
        fingerprint = gate._source_fingerprint()
        monkeypatch.setattr(gate, "_source_fingerprint", lambda: fingerprint + "changed")
        gate._VERIFIED.clear()
        gate.validate_native_semantics(native, series, calendar)
        assert calls == ["--verify", "--verify", "--verify"]

    gate._VERIFIED.clear()
    gate.validate_native_semantics(native, series, calendar)
    assert len(calls) == 4  # CLI defaults do not reuse the website's disk cache.


def test_claimed_method_failure_cannot_hide_saved_success(
    original_native: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    native, series, calendar = original_native
    changed = deepcopy(native)
    changed["native"][0].update({"status": "error", "result": None, "error": "claimed failure"})
    changed["support_records"] = gate.expected_support_records(changed)

    with pytest.raises(ValueError):
        gate.validate_native_semantics(changed, series, calendar)


@pytest.mark.parametrize(
    ("mutation", "mismatch"),
    [
        ("wave-scale", "Original source wave mismatch"),
        ("launch-outcome", "Original source launch mismatch"),
        ("phase-label", "Original source phase mismatch"),
    ],
)
def test_success_cache_reuses_exact_payload_but_rejects_semantic_tampering(
    original_native: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: Literal["wave-scale", "launch-outcome", "phase-label"],
    mismatch: str,
) -> None:
    native, series, calendar = original_native
    monkeypatch.setattr(gate, "_VERIFIED", OrderedDict())
    original_call = gate._call_source
    calls: list[str] = []

    def tracked_call(encoded: str, mode: str) -> str:
        calls.append(mode)
        return original_call(encoded, mode)

    monkeypatch.setattr(gate, "_call_source", tracked_call)
    gate.validate_native_semantics(native, series, calendar)
    gate.validate_native_semantics(deepcopy(native), deepcopy(series), deepcopy(calendar))
    assert calls == ["--verify"]

    changed = deepcopy(native)
    if mutation == "wave-scale":
        wave = next(record["result"]["waves"][0] for record in changed["native"] if record["result"]["waves"])
        wave["scale"] = "large" if wave["scale"] == "small" else "small"
    elif mutation == "launch-outcome":
        launch = next(record["result"]["launches"][0] for record in changed["native"] if record["result"]["launches"])
        launch["outcome"] = "failed" if launch["outcome"] != "failed" else "continued"
    else:
        segment = next(record["result"]["segments"][0] for record in changed["native"] if record["result"]["segments"])
        segment["phase"] = "flat" if segment["phase"] != "flat" else "fast"

    # Bounds, gain and support identities still pass; only the original JS
    # semantic comparison can detect these plausible field substitutions.
    with pytest.raises(ValueError, match=mismatch):
        gate.validate_native_semantics(changed, series, calendar)
    assert calls == ["--verify", "--verify"]
