from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

import pytest

from research_core.opportunity_history_catalog import RULE, SELECTOR, adapt_security, query_security, source_run_indices
from scripts.build_opportunity_history import code_identity
from scripts.query_opportunity_history import GAIN_POLICY, V2_ADAPTERS, calendar_content_id, main, series_content_id
from scripts.tests.opportunity_trusted_fixture_calls import fixture_manifest_sha256, query_manifest


def fixture() -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    dates = [f"2020-01-{i:02}" for i in range(1, 9)]
    series = {
        "security_id": "sec",
        "series_id": "series",
        "calendar_id": "calendar",
        "code": "A",
        "cohort": "metadata_stock",
        "instrument_role": "stock",
        "raw": [100, 101, 102, 103, 104, 105, 106, 107],
        "adjusted": [100, 101, 102, 103, 104, 105, 106, 107],
        "numeric_flags": {},
        "action_barriers": [],
        "coverage_caveats": ["early_action_coverage"],
    }
    small = {
        "id": "small",
        "start": 0,
        "peak": 3,
        "end": 4,
        "observedThrough": 7,
        "gain": 0.3,
        "maxDrawdown": 0.1,
        "scale": "small",
        "leftCensored": False,
        "rightCensored": False,
    }
    large = {**small, "id": "large", "start": 1, "end": 6, "scale": "large"}
    later = {**large, "id": "later", "start": 2, "end": None, "rightCensored": True}
    launch = {"id": "launch", "index": 3, "rangeStart": 3, "rangeEnd": 5, "kind": "breakout", "outcome": "failed", "forwardEnd": 5}
    native = {
        "security_id": "sec",
        "series_id": "series",
        "calendar_id": "calendar",
        "input_identity": "input",
        "native": [
            {
                "method": "segments",
                "scale": "balanced",
                "status": "ok",
                "result": {
                    "waves": [small, large, later],
                    "launches": [launch, {**launch, "id": "unlinked", "index": 7, "rangeStart": 7, "rangeEnd": 7}],
                    "segments": [{"start": 0, "end": 3, "slope": 0.01, "phase": "advance"}, {"start": 3, "end": 7, "slope": -0.01, "phase": "decline"}],
                },
                "error": None,
            }
        ],
        "support_records": [{"method": "segments", "scale": "balanced", "target_id": "launch", "min_index": 1, "max_index": 7, "matches": []}],
    }
    return series, dates, native


def test_native_percent_units_preserved_and_query_gain_is_fraction() -> None:
    series, dates, native = fixture()
    native["native"][0]["result"]["waves"][0].update(gain=60, maxDrawdown=-25)
    native["native"][0]["result"]["launches"][0].update(forwardGain=5, drawdown=-3)
    tables = adapt_security(series, dates, native)
    wave = tables["baseline_waves"][0]
    candidate = tables["candidates"][0]
    assert (wave["gain"], wave["gain_unit"], wave["maxDrawdown"], wave["maxDrawdown_unit"]) == (60, "percent", -25, "percent")
    assert (candidate["forwardGain"], candidate["forwardGain_unit"], candidate["drawdown"], candidate["drawdown_unit"]) == (5, "percent", -3, "percent")
    result = query_security(tables, series, dates, dates[2])
    assert result["gain_unit"] == "fraction"
    assert result["gain"] == pytest.approx(102 / 101 - 1)


def test_saved_js_runs_control_boundary_and_gain() -> None:
    series, dates, native = fixture()
    series["raw"] = series["adjusted"] = [4, 5.4, 5.4, 5.4, 5.4, 5.4, 5.4, 5.4]
    native["source_run_indices"] = [0, 1, 1, 1, 1, 1, 1, 1]
    tables = adapt_security(series, dates, native)
    assert tables["securities"][0]["run_boundary_precision"] == "exact_pinned_js"
    assert tables["source_phases"][0]["run_boundary_crossing"]
    from research_core.opportunity_history_catalog import gain_at

    assert gain_at({**series, "source_run_indices": native["source_run_indices"]}, dates, 0, 1) == (None, "continuity_jump")


def test_ratio_warning_does_not_override_saved_js_continuity() -> None:
    from research_core.opportunity_history_catalog import gain_at

    series = {"raw": [6.02, 8.127], "adjusted": [6.02, 8.127], "numeric_flags": {}, "action_barriers": [], "source_run_indices": [0, 0]}
    gain, reason = gain_at(series, ["2020-01-01", "2020-01-02"], 0, 1)
    assert gain == pytest.approx(0.35)
    assert reason is None


def test_fixed_selector_start_large_ascending_exclusive_end_cutoff() -> None:
    series, dates, native = fixture()
    tables = adapt_security(series, dates, native)
    intervals = tables["representative_intervals"]
    assert [(r["start_index"], r["end_exclusive_index"], r["gain_base_index"]) for r in intervals] == [(0, 1, 0), (1, 6, 1), (6, 8, 2)]
    assert query_security(tables, series, dates, dates[0])["member"]
    assert intervals[-1]["end_exclusive_date"] is None
    assert intervals[-1]["cutoff_date"] == dates[-1]
    assert query_security(tables, series, dates, dates[6])["gain_base_index"] == 2
    switch = tables["transitions"][-1]
    assert switch["old_gain_base_index"] == 1
    assert switch["new_gain_base_index"] == 2
    assert switch["gain_jump"] == pytest.approx(106 / 102 - 106 / 101)
    assert intervals[1]["earliest_candidate_id"] is not None
    assert all(r["manual_selection"] is None for r in intervals)


@pytest.mark.parametrize(
    "change,reason", [("missing", "missing_or_invalid_endpoint"), ("flag", "numeric_blocker"), ("action", "action_barrier"), ("jump", "continuity_jump")]
)
def test_unknown_return_preserves_raw_and_membership(change: str, reason: str) -> None:
    series, dates, native = fixture()
    if change == "missing":
        series["adjusted"][4] = None
    elif change == "flag":
        series["numeric_flags"] = {"4": ["blocked"]}
    elif change == "action":
        series["action_barriers"] = [{"index": 3}]
    else:
        series["adjusted"][3] = 200
    tables = adapt_security(series, dates, native)
    result = query_security(tables, series, dates, dates[4])
    assert result["member"] and result["raw_quote"] == 104
    assert result["gain"] is None and result["gain_reason"] == reason


def test_native_preservation_shared_baseline_support_and_failures() -> None:
    series, dates, native = fixture()
    second = copy.deepcopy(native["native"][0])
    second["method"] = "filter"
    second["result"]["diagnostics"] = {"converged": False}
    native["native"].extend([second, {"method": "filter", "scale": "fine", "status": "error", "result": None, "error": "runtime failure"}])
    tables = adapt_security(series, dates, native)
    assert len(tables["baseline_waves"]) == 3
    assert all(len(w["aliases"]) == 2 for w in tables["baseline_waves"])
    assert len(tables["candidates"]) == 4
    assert len(tables["source_phases"]) == 4
    assert tables["methods"][1]["diagnostics"] == {"converged": False}
    assert tables["methods"][-1]["error"] == "runtime failure"
    assert tables["support_records"][0]["min_index"] == 1
    assert tables["candidates"][0]["rangeStart"] == 3
    assert tables["candidates"][0]["outcome"] == "failed"
    assert tables["candidates"][0]["first_knowable_at"] is None
    assert tables["source_phases"][1]["start"] == 3
    assert any(r["shared_endpoints"] for r in tables["relations"] if "shared_endpoints" in r)
    second["result"]["waves"][0]["gain"] = 0.4
    with pytest.raises(ValueError, match="inconsistent shared wave"):
        adapt_security(series, dates, native)


def test_distinct_scales_empty_unresolved_and_identity() -> None:
    series, dates, native = fixture()
    fine = copy.deepcopy(native["native"][0])
    fine["scale"] = "fine"
    native["native"].append(fine)
    assert len(adapt_security(series, dates, native)["baseline_waves"]) == 6
    series["instrument_role"] = "benchmark"
    tables = adapt_security(series, dates, native)
    assert query_security(tables, series, dates, dates[2])["stock_opportunity_count"] == 0
    native["native"][0]["result"] = {"launches": [{"id": "orphan", "index": 1, "rangeStart": 1, "rangeEnd": 2, "outcome": "unresolved"}]}
    native["native"] = native["native"][:1]
    series["raw"] = [None] * 8
    series["adjusted"] = [None] * 8
    tables = adapt_security(series, dates, native)
    assert tables["representative_intervals"] == []
    assert tables["candidates"][0]["wave_ids"] == []
    assert tables["securities"][0]["status"] == "no_usable_quotes"
    native["series_id"] = "other"
    with pytest.raises(ValueError, match="identity"):
        adapt_security(series, dates, native)


def test_primary_candidate_reference_and_true_support_shape() -> None:
    series, dates, native = fixture()
    filter_record = copy.deepcopy(native["native"][0])
    filter_record["method"] = "filter"
    filter_record["result"]["launches"][0]["index"] = 1
    native["native"].append(filter_record)
    native["support_records"] = [
        {
            "method": "segments",
            "scale": "balanced",
            "candidate_id": "launch",
            "index": 3,
            "kind": "breakout",
            "matched_ids": [{"method": "filter", "scale": "balanced", "candidate_id": "launch", "index": 1}],
            "support": 1,
            "rangeStart": 1,
            "rangeEnd": 3,
        }
    ]
    tables = adapt_security(series, dates, native)
    primary = next(c for c in tables["candidates"] if c["method"] == "segments" and c["native_id"] == "launch")
    secondary = next(c for c in tables["candidates"] if c["method"] == "filter" and c["native_id"] == "launch")
    assert tables["representative_intervals"][1]["earliest_candidate_id"] == primary["id"]
    support = tables["support_records"][0]
    assert support["target_catalog_id"] == primary["id"]
    assert support["matched_catalog_ids"] == [secondary["id"]]
    assert (support["rangeStart"], support["rangeEnd"]) == (1, 3)
    assert (primary["rangeStart"], primary["rangeEnd"]) == (3, 5)


def test_run_boundary_single_point_phase_is_flagged_without_repair() -> None:
    series, dates, native = fixture()
    series["adjusted"] = [100, 101, 200, None, 202, 203, 204, 205]
    series["numeric_flags"] = {"5": ["unresolved_action"]}
    assert source_run_indices(series) == [0, 0, 1, None, 2, None, 3, 3]
    inherited = {"start": 0, "end": 2, "slope": 0.01, "phase": "advance"}
    native["native"][0]["result"]["segments"] = [inherited, {"start": 2, "end": 2, "slope": 0, "phase": "advance"}]
    tables = adapt_security(series, dates, native)
    phase, point = tables["source_phases"]
    assert phase["run_boundary_crossing"]
    assert phase["source_run_ids"] == [0, 1]
    assert all(phase[field] == inherited[field] for field in inherited)
    assert not point["run_boundary_crossing"]
    assert point["source_run_ids"] == [1]


@pytest.mark.parametrize("mutation", ["start", "missing", "parent"])
def test_successful_method_baseline_disagreement_rejected(mutation: str) -> None:
    series, dates, native = fixture()
    other = copy.deepcopy(native["native"][0])
    other["method"] = "filter"
    if mutation == "start":
        other["result"]["waves"][0]["start"] = 1
    elif mutation == "missing":
        other["result"]["waves"].pop()
    else:
        other["result"]["waves"][0]["parentId"] = "large"
    native["native"].append(other)
    with pytest.raises(ValueError, match="inconsistent shared wave"):
        adapt_security(series, dates, native)
    other.update(status="error", result=None, error="method_failed")
    assert len(adapt_security(series, dates, native)["baseline_waves"]) == 3


def test_candidate_date_links_not_ensuing_range_and_confirmed_end_excluded() -> None:
    series, dates, native = fixture()
    wave = native["native"][0]["result"]["waves"][1]
    native["native"][0]["result"]["waves"] = [wave]
    template = native["native"][0]["result"]["launches"][0]
    native["native"][0]["result"]["launches"] = [
        {**template, "id": "before", "index": 0, "rangeStart": 0, "rangeEnd": 4},
        {**template, "id": "inside", "index": 2, "rangeStart": 2, "rangeEnd": 7},
        {**template, "id": "end", "index": 6, "rangeStart": 5, "rangeEnd": 7},
    ]
    tables = adapt_security(series, dates, native)
    candidates = {row["native_id"]: row for row in tables["candidates"]}
    assert candidates["before"]["wave_ids"] == []
    assert candidates["end"]["wave_ids"] == []
    assert candidates["inside"]["wave_ids"]
    assert tables["representative_intervals"][0]["earliest_candidate_id"] == candidates["inside"]["id"]
    assert candidates["inside"]["rangeEnd"] == 7
    assert sum(row["kind"] == "candidate_index_in_wave" for row in tables["relations"]) == 1
    assert any(row["right_id"] == candidates["before"]["id"] and row["span_domain"] == "native_candidate_ensuing_inclusive" for row in tables["relations"])


def test_cli_reads_same_intervals_and_checks_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series, dates, native = fixture()
    series["schema_version"] = "opportunity-series.v1"
    calendar_payload: dict[str, Any] = {"dates": dates}
    calendar_id = calendar_content_id(calendar_payload)
    calendar_payload["calendar_id"] = calendar_id
    series["calendar_id"] = calendar_id
    native["calendar_id"] = calendar_id
    series["series_id"] = series_content_id(series)
    native["series_id"] = series["series_id"]

    def write(name: str, payload: Any) -> dict[str, str]:
        data = json.dumps(payload).encode()
        if name.endswith(".gz"):
            data = gzip.compress(data)
        (tmp_path / name).write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    calendar_ref = write("calendar.json", calendar_payload) | {"count": len(dates)}
    series_ref = write("A.json.gz", series) | {"series_id": series["series_id"], "security_id": series["security_id"]}
    identity = code_identity()
    context = {"code_identity": identity, "fixture": "controlled-six-records"}
    expected_runs = [0] * len(dates)
    native["schema"] = "opportunity-native-results.v1"
    native["code_identity"] = identity
    native["input_identity"] = {"series_sha256": series_ref["sha256"], "calendar_sha256": calendar_ref["sha256"]}
    native["source_run_indices"] = expected_runs.copy()
    template = native["native"][0]
    log_returns = [math.log(series["adjusted"][i]) - math.log(series["adjusted"][i - 1]) for i in range(1, len(dates))]
    centre = median(log_returns)
    noise = max(1e-4, 1.4826 * median(abs(value - centre) for value in log_returns))
    template["result"] = {
        "waves": [],  # This observed 7% rise is below the pinned 60% retention floor at every scale.
        "segments": [{"start": 0, "end": 3, "slope": 0, "phase": "flat"}, {"start": 3, "end": 7, "slope": 0.01, "phase": "fast"}],
        "launches": [
            {
                "id": "launch-3-breakout",
                "index": 3,
                "rangeStart": 3,
                "rangeEnd": 7,
                "kind": "breakout",
                "preSlope": 0,
                "postSlope": 0.01,
                "sustainSessions": 4,
                "relativeStrength": 0.01 / noise,
                "forwardGain": (107 / 103 - 1) * 100,
                "forwardEnd": 7,
                "drawdown": 0,
                "outcome": "unresolved",
                "support": 1,
            }
        ],
        "fit": series["adjusted"].copy(),
        "diagnostics": {"noise": noise},
    }
    native["native"] = [
        copy.deepcopy(template) | {"method": method, "scale": scale} for method in ("segments", "filter") for scale in ("fine", "balanced", "coarse")
    ]
    native["support_records"] = []
    for record in native["native"]:
        for target in record["result"]["launches"]:
            matches = []
            for scale in ("fine", "balanced", "coarse"):
                available = [
                    candidate
                    for other in native["native"]
                    if other["method"] == record["method"] and other["scale"] == scale
                    for candidate in other["result"]["launches"]
                    if candidate["kind"] == target["kind"] and abs(candidate["index"] - target["index"]) <= 20
                ]
                if available:
                    nearest = min(available, key=lambda candidate: abs(candidate["index"] - target["index"]))
                    matches.append({"method": record["method"], "scale": scale, "candidate_id": nearest["id"], "index": nearest["index"]})
            native["support_records"].append({
                "method": record["method"],
                "scale": record["scale"],
                "candidate_id": target["id"],
                "index": target["index"],
                "kind": target["kind"],
                "matched_ids": matches,
                "support": len(matches),
                "rangeStart": min(match["index"] for match in matches),
                "rangeEnd": max(match["index"] for match in matches),
            })
    native_ref: dict[str, Any] = write("A.native.json.gz", native) | {"count": 6}
    native_ref["receipt"] = write(
        "A.receipt.json",
        {
            "schema_version": "opportunity-native-receipt.v1",
            "context": context,
            "sha256": native_ref["sha256"],
            "security_id": series["security_id"],
            "series_id": series["series_id"],
        },
    )
    monkeypatch.setattr("scripts.query_opportunity_history.expected_source_runs", lambda _path, _codes: {"A": expected_runs.copy()})
    tables = adapt_security(series, calendar_payload, native)
    eligible = series["instrument_role"] == "stock" and series["cohort"] in ("metadata_stock", "innovation_board")
    tables["securities"][0].update({
        "stock_opportunity_eligible": eligible,
        "method_eligibility_reason": "stock_cohort" if eligible else "excluded_role_or_identity",
        "coverage": series.get("coverage", {}),
    })
    manifest = {
        "schema_version": "opportunity-local-history-preview.v1",
        "rule": RULE,
        "selector": SELECTOR,
        "adapter_revision": sorted(V2_ADAPTERS)[0],
        "gain_policy": GAIN_POLICY,
        "code_identity": identity,
        "producer_identity": context,
        "native": {"A": native_ref},
        "calendar_id": series["calendar_id"],
        "calendar": calendar_ref,
        "series": {"A": series_ref},
        "tables": {name: [write(f"{name}.json", {"rows": tables[name]})] for name in ("securities", "representative_intervals")},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert main(["--manifest", str(path), "--code", "A", "--date", dates[0], "--expected-manifest-sha256", fixture_manifest_sha256(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    evidence = result.pop("evidence")
    assert result == query_security(tables, series, dates, dates[0])
    assert evidence["effective_gain_policy"] == "exact_pinned_js_run.preview.v2"
    assert evidence["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert evidence["native_sha256"] == native_ref["sha256"]
    assert evidence["native_receipt_sha256"] == native_ref["receipt"]["sha256"]
    (tmp_path / "A.json.gz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        query_manifest(path, "A", dates[0])
