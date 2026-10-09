"""Compact query reconstruction stays identical to the full native adapter."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import pytest

from research_core import opportunity_history_catalog as catalog
from scripts.query_opportunity_history import GAIN_POLICY, V2_ADAPTERS, validate_manifest_identity
from scripts.tests.test_opportunity_history_catalog import fixture


def test_current_compact_producer_revision_is_registered_but_unknown_bytes_are_rejected() -> None:
    revision = hashlib.sha256(Path(catalog.__file__).read_bytes()).hexdigest()
    manifest = {
        "schema_version": "opportunity-local-history-preview.v1",
        "adapter_revision": revision,
        "gain_policy": GAIN_POLICY,
        "rule": catalog.RULE,
        "selector": catalog.SELECTOR,
    }
    assert validate_manifest_identity(manifest)["adapter_revision"] == revision
    # Registration remains a reviewed fixed list, never approval of arbitrary live code.
    assert revision in V2_ADAPTERS
    with pytest.raises(ValueError, match="adapter revision"):
        validate_manifest_identity(manifest | {"adapter_revision": "0" * 64})


@pytest.mark.parametrize(
    "case",
    ["base", "aliases", "multiscale", "tied_candidates", "boundaries", "censored", "no_candidate", "empty", "excluded", "source_break", "no_quotes"],
)
def test_query_projection_matches_full_adapter(case: str) -> None:
    series, dates, native = fixture()
    record = native["native"][0]
    if case == "aliases":
        other = copy.deepcopy(record)
        other["method"] = "filter"
        for wave in other["result"]["waves"]:
            wave["id"] = "filter-" + wave["id"]
        native["native"].insert(0, other)
    elif case == "multiscale":
        for scale in ("fine", "coarse"):
            other = copy.deepcopy(record)
            other["scale"] = scale
            native["native"].append(other)
    elif case == "tied_candidates":
        launch = record["result"]["launches"][0]
        record["result"]["launches"] = [dict(launch, id=identifier) for identifier in ("z", "a", "middle")]
    elif case == "boundaries":
        launch = record["result"]["launches"][0]
        record["result"]["launches"] = [dict(launch, id=f"at-{index}", index=index) for index in (0, 1, 4, 6, 7)]
    elif case == "censored":
        for wave in record["result"]["waves"]:
            wave["leftCensored"] = True
    elif case == "no_candidate":
        record["result"]["launches"] = []
    elif case == "empty":
        native["native"] = []
    elif case == "excluded":
        series.update(instrument_role="benchmark", cohort="unresolved")
        native["native"] = []
    elif case == "source_break":
        native["source_run_indices"] = [0, 0, None, 1, 1, 2, 2, 2]
        series["sources"] = ["official", "official", None, "supplement", "official", "official", "official", "official"]
    elif case == "no_quotes":
        series["raw"] = [None] * len(dates)
        series["adjusted"] = [None] * len(dates)
    full = catalog.adapt_security(series, dates, native)
    compact = catalog.project_query_tables(series, {"dates": dates}, native)
    assert compact == {name: full[name] for name in ("securities", "representative_intervals")}
    assert set(compact) == {"securities", "representative_intervals"}


def test_projection_candidate_ties_and_exclusive_end_use_saved_ids() -> None:
    series, dates, native = fixture()
    record = native["native"][0]
    large = record["result"]["waves"][1]
    record["result"]["waves"] = [large]
    launch = record["result"]["launches"][0]
    record["result"]["launches"] = [
        dict(launch, id="before", index=0),
        dict(launch, id="z", index=1),
        dict(launch, id="a", index=1),
        dict(launch, id="at-end", index=6),
    ]
    full = catalog.adapt_security(series, dates, native)
    interval = catalog.project_query_tables(series, dates, native)["representative_intervals"][0]
    tied = [candidate["id"] for candidate in full["candidates"] if candidate["index"] == 1]
    assert interval["earliest_candidate_id"] == min(tied)
    assert (interval["start_index"], interval["end_exclusive_index"]) == (1, 6)
    assert not full["candidates"][0]["wave_ids"]
    assert not full["candidates"][-1]["wave_ids"]
    # Open waves instead include observedThrough, including its launch.
    large.update(end=None, observedThrough=6, rightCensored=True)
    record["result"]["launches"] = [record["result"]["launches"][-1]]
    compact = catalog.project_query_tables(series, dates, native)
    assert compact["representative_intervals"][0]["end_exclusive_index"] == 7
    assert compact["representative_intervals"][0]["earliest_candidate_id"] is not None


def test_projection_does_not_build_relations_or_compute_gains(monkeypatch: pytest.MonkeyPatch) -> None:
    series, dates, native = fixture()
    full = catalog.adapt_security(series, dates, native)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Query projection must not build relations or convert gains")

    monkeypatch.setattr(catalog, "_relation", forbidden)
    monkeypatch.setattr(catalog, "gain_at", forbidden)
    # These detail-only collections are not needed even to reconstruct aliases.
    native["support_records"] = None
    native["native"][0]["result"]["segments"] = None
    assert catalog.project_query_tables(series, dates, native) == {name: full[name] for name in ("securities", "representative_intervals")}


@pytest.mark.parametrize("change", ["geometry", "gain", "parent"])
def test_projection_preserves_shared_baseline_rejection(change: str) -> None:
    series, dates, native = fixture()
    other = copy.deepcopy(native["native"][0])
    other["method"] = "filter"
    wave = other["result"]["waves"][0]
    if change == "geometry":
        wave["start"] += 1
    elif change == "gain":
        wave["gain"] += 1
    else:
        wave["parentId"] = "large"
    native["native"].append(other)
    with pytest.raises(ValueError, match="inconsistent shared wave"):
        catalog.project_query_tables(series, dates, native)


@pytest.mark.parametrize("field", ["security_id", "series_id", "calendar_id"])
def test_projection_preserves_native_identity_gate(field: str) -> None:
    series, dates, native = fixture()
    native[field] = "wrong"
    with pytest.raises(ValueError, match="native/series identity mismatch"):
        catalog.project_query_tables(series, dates, native)
