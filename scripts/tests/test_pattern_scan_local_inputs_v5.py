"""Synthetic continuity, complete-peer and unhashed progress contracts."""

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_local_inputs_v5 as module
from research_core.pattern_scan_event_tables_v1 import EventTables
from research_core.pattern_scan_holding_v1 import holding_values


def _holding_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str], pd.DataFrame, pd.DataFrame]:
    calendar = pd.bdate_range("2010-01-04", periods=300)
    positions = np.arange(len(calendar), dtype=float)
    # Interleave industries so partitioning must preserve the original peer
    # order rather than relying on adjacency or lexicographic stock ordering.
    close = pd.DataFrame(
        {
            "TW:0003": 101.37 + positions * 0.113,
            "TW:0008": 23.91 + positions * 0.071,
            "TW:0001": 50.13 + positions * 0.317,
            "TW:0009": 83.17 + positions * 0.191,
            "TW:0005": 12.37 + positions * 0.053,
            "TW:0002": np.nan,
            "TW:0004": 77.23 + positions * 0.223,
        },
        index=calendar,
    )
    industries = {"TW:0003": "tech", "TW:0008": "", "TW:0001": "tech", "TW:0009": "chem", "TW:0005": "tech", "TW:0002": "tech", "TW:0004": ""}
    close.loc[calendar[30], "TW:0003"] = np.nan  # ordinary interior gap
    close.loc[calendar[126], "TW:0001"] = np.nan  # missing endpoint
    jumps = pd.DataFrame(False, index=calendar, columns=close.columns).astype("boolean")
    jumps.loc[calendar[50], "TW:0005"] = True
    jumps.loc[calendar[270], "TW:0001"] = pd.NA
    benchmark = pd.DataFrame({"Close": 100.17 + positions * 0.173, "quality_reason": None}, index=calendar)
    benchmark.loc[calendar[100], "quality_reason"] = "unexplained_adjusted_jump"
    benchmark.loc[calendar[252], "Close"] = np.nan
    states = pd.Series(np.resize(np.array(["up", "down", "mixed", "consolidation", None], dtype=object), len(calendar)), index=calendar)
    context = pd.DataFrame({"Date": calendar, "retrospective_state": states.to_numpy()})
    return close, jumps, industries, benchmark, context


@pytest.mark.parametrize("industry", ("tech", "", "chem"))
def test_industry_partition_is_bitwise_equal_to_full_grid_including_unknown_peers(industry: str) -> None:
    close, jumps, industries, benchmark, context = _holding_inputs()
    codes = tuple(code for code in close if industries[code] == industry)
    # Only some peers have requested outputs. Every peer must nevertheless
    # remain in the reduction, including the entirely missing TW:0002.
    anchors = {code: [0, 20, 130, 299] for code in codes if code != "TW:0002"}
    full = holding_values(
        close,
        industries,
        benchmark.Close,
        context.set_index("Date").retrospective_state,
        jump_matrix=jumps,
        benchmark_jump=benchmark.quality_reason.fillna("").str.contains("unexplained.*jump", regex=True),
        anchors=anchors,
    )
    actual = module.industry_holding(close, jumps, industries, benchmark, context, codes, anchors)
    expected = full.loc[full.security_id.isin(codes)].reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual.censored.any()
    assert actual.own_return_reason.eq("window_end").any()
    assert actual.benchmark_return_reason.eq("unexplained_jump").any()
    if industry == "tech":
        first = actual.loc[actual.security_id.eq("TW:0003") & actual.calendar_index.eq(0) & actual.horizon.eq(126)].iloc[0]
        assert first.potential_peer_n == first.unknown_peer_n == 3
        assert first.known_peer_n == 0
        assert pd.notna(first.own_return)  # interior gaps do not erase endpoints
        assert actual.own_return_reason.eq("invalid_endpoint").any()
        assert actual.own_return_reason.eq("unexplained_jump").any()
        assert actual.own_return_reason.eq("quality_unknown").any()
    elif industry == "":
        assert actual.peer_return_reason.eq("unknown_industry").all()
        assert actual.potential_peer_n.eq(0).all()
    else:
        assert actual.peer_return_reason.eq("no_peers").all()


@pytest.mark.parametrize("damage", ("omit_missing_peer", "reorder", "mixed", "empty"))
def test_industry_partition_rejects_incomplete_or_reordered_peer_inventory(damage: str) -> None:
    close, jumps, industries, benchmark, context = _holding_inputs()
    codes = tuple(code for code in close if industries[code] == "tech")
    if damage == "omit_missing_peer":
        codes = tuple(code for code in codes if code != "TW:0002")
    elif damage == "reorder":
        codes = codes[::-1]
    elif damage == "mixed":
        codes = (*codes, "TW:0009")
    else:
        codes = ()
    with pytest.raises(ValueError, match="industry block|reference-industry block"):
        module.industry_holding(close, jumps, industries, benchmark, context, codes, {})


def _forbid_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("mutable progress and intermediate cache must not hash payloads")

    for name in ("file_digest", "object_digest", "describe_file", "verify_files"):
        monkeypatch.setattr(f"research_core.artifact_store.{name}", forbidden)


def test_progress_replaces_one_mutable_json_atomically_without_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_hashes(monkeypatch)
    path = tmp_path / "progress.json"
    first = {"target": "B1", "completed": ["0050"], "complete": False}
    second = {"target": "B1", "completed": ["0050", "2330"], "complete": True}
    module.write_progress(path, first)
    replace = module.os.replace
    calls: list[tuple[Path, Path]] = []

    def checked_replace(source: Path, destination: Path) -> None:
        assert destination == path
        assert source.parent == destination.parent
        assert json.loads(destination.read_text(encoding="utf-8")) == first
        assert json.loads(source.read_text(encoding="utf-8")) == second
        calls.append((source, destination))
        replace(source, destination)

    monkeypatch.setattr(module.os, "replace", checked_replace)
    module.write_progress(path, second)
    assert json.loads(path.read_text(encoding="utf-8")) == second
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == [path]


def _bound(calendar: pd.DatetimeIndex) -> EventTables:
    events = pd.DataFrame({
        "event_id": ["first", "first", "second", "second", "other"],
        "horizon": [126, 252, 126, 252, 126],
        "effective_label": ["hit", "unknown", "unknown", "loss", "flat-win"],
        "calendar_full": [True, False, True, True, True],
        "censored": [False, True, False, False, False],
        "calendar_index": [0, 0, 1, 1, 2],
    })
    conditions = pd.DataFrame({"event_id": ["first", "second", "other"], "MKT": [None, "up", "down"], "F10": [1, -1, 0]})
    members = pd.DataFrame({"event_id": ["first", "second", "other"], "group_id": ["pattern:union", "pattern:union", "C-52w"]})
    states = {"pattern:union": pd.Series(np.array([1, 1, 0], dtype=np.int8), index=calendar)}
    return EventTables(events, conditions, members, states, states)


def test_group_frame_keeps_canonical_outcomes_unknown_and_market_without_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_hashes(monkeypatch)
    bound = _bound(pd.bdate_range("2010-01-04", periods=3))
    before = bound.events.copy(deep=True)
    h126 = module.group_frame(bound, "pattern:union", 126)
    assert h126.event_id.tolist() == ["first", "second"]
    assert h126.effective_label.tolist() == ["hit", "unknown"]
    assert h126.mkt.tolist() == ["unknown", "up"]
    assert h126.F10.tolist() == [1, -1]
    assert pd.isna(h126.iloc[0].MKT)
    h252 = module.group_frame(bound, "pattern:union", 252)
    assert h252.effective_label.tolist() == ["unknown", "loss"]
    assert h252.censored.tolist() == [True, False]
    pd.testing.assert_frame_equal(bound.events, before)
    assert module.group_frame(bound, "missing", 126).empty


def test_group_frame_rejects_duplicate_members_instead_of_multiplying_outcomes() -> None:
    original = _bound(pd.bdate_range("2010-01-04", periods=3))
    bound = EventTables(
        original.events,
        original.conditions,
        pd.concat([original.group_memberships, original.group_memberships.iloc[:1]]),
        original.daily_groups,
        original.formula_groups,
    )
    with pytest.raises(pd.errors.MergeError):
        module.group_frame(bound, "pattern:union", 126)


def _stub_inputs(temporary: Path, calendar: pd.DatetimeIndex, bound: EventTables, builds: list[str]) -> module.LocalInputs:
    # Exercise the real public cache/restart path without touching constructor
    # discovery of retained research files or the maintained shared root.
    inputs = object.__new__(module.LocalInputs)
    inputs.temporary = temporary
    inputs.codes = ("0050", "2330")
    inputs.source_id, inputs.input_id = "synthetic-source", "synthetic-input"
    inputs.calendar = calendar
    inputs.existing = {}
    inputs._target_roots, inputs._cached_codes = {}, {}
    inputs.label_pin = {"version_id": "synthetic-labels", "manifest_sha256": "historical-description-only"}

    def stock(code: str) -> dict[str, pd.DataFrame]:
        builds.append(code)
        return {}

    inputs.stock = stock  # type: ignore[method-assign]
    inputs.global_values = lambda code: pd.DataFrame(index=calendar)  # type: ignore[method-assign]
    return inputs


def test_complete_projection_cache_reuses_after_restart_without_building_or_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_hashes(monkeypatch)
    calendar = pd.bdate_range("2010-01-04", periods=3)
    expected = _bound(calendar)
    builds: list[str] = []
    temporary = tmp_path / "continuation"
    temporary.mkdir()

    def build(*args: Any, **kwargs: Any) -> EventTables:
        return expected

    monkeypatch.setattr(module, "build_event_tables", build)
    first = _stub_inputs(temporary, calendar, expected, builds)
    output = temporary / "B1"
    assert first.cache_target("B1", output) == output
    assert builds == ["0050", "2330"]

    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("completed stock projections must be reused after a restart")

    monkeypatch.setattr(module, "build_event_tables", forbidden)
    second = _stub_inputs(temporary, calendar, expected, builds)
    assert second.cache_target("B1", output) == output
    restored = second.bound("B1", "0050")
    pd.testing.assert_frame_equal(restored.events, expected.events)
    pd.testing.assert_frame_equal(restored.conditions, expected.conditions)
    pd.testing.assert_frame_equal(pd.DataFrame(restored.daily_groups), pd.DataFrame(expected.daily_groups))
    assert builds == ["0050", "2330"]
    assert json.loads((output / "progress.json").read_text(encoding="utf-8"))["completed"] == ["0050", "2330"]
    assert not list(output.rglob("*receipt*")) and not list(output.rglob("*manifest*"))


def _holding_cache_inputs(temporary: Path) -> tuple[module.LocalInputs, dict[str, list[int]]]:
    close, jumps, industries, benchmark, context = _holding_inputs()
    temporary.mkdir()
    inputs = object.__new__(module.LocalInputs)
    inputs.temporary = temporary
    inputs.calendar = cast(pd.DatetimeIndex, close.index)
    inputs.codes = tuple(str(security).removeprefix("TW:") for security in close)
    inputs._sidecars = {"close_matrix": close, "jump_matrix": jumps, "benchmark": benchmark, "context": context}
    inputs._industries = industries
    inputs.parts = {}
    anchors = {str(security): [] if security == "TW:0002" else [0, 20, 130, 299] for security in close}
    for code in inputs.codes:
        part = temporary / f"original-{code}"
        part.mkdir()
        inputs.parts[code] = part
        module.write_frame(pd.DataFrame({"calendar_index": pd.Series(anchors[f"TW:{code}"], dtype="int64")}), part / "cohort_events.parquet", index=False)
    return inputs, anchors


def test_holding_partial_peer_retry_preserves_valid_peers_and_recomputes_only_complete_affected_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_hashes(monkeypatch)
    inputs, anchors = _holding_cache_inputs(tmp_path / "holding-inputs")
    inputs.holding("0009", anchors["TW:0009"])
    output = inputs.temporary / "holding"
    unrelated = output / "0009.parquet"
    unrelated_before = unrelated.read_bytes(), unrelated.stat().st_mtime_ns
    write, replace, kernel = module.write_frame, module.os.replace, module.industry_holding
    reductions: list[tuple[str, ...]] = []
    publications: list[str] = []

    def observed_kernel(*args: Any, **kwargs: Any) -> pd.DataFrame:
        reductions.append(args[5])
        return kernel(*args, **kwargs)

    def checked_replace(staged: Path, destination: Path) -> None:
        assert staged.parent == destination.parent and staged != destination
        security = f"TW:{destination.stem}"
        assert module._cached_holding(staged, security, inputs.calendar, anchors[security], full=True, exact_anchors=True) is not None
        publications.append(destination.stem)
        replace(staged, destination)

    def interrupted_write(frame: pd.DataFrame, path: Path, *, index: bool) -> None:
        if path.name.startswith(".0001.parquet-"):
            path.write_bytes(b"PAR1synthetic interrupted staged peer")
            raise RuntimeError("interrupted staged holding peer")
        write(frame, path, index=index)

    monkeypatch.setattr(module, "industry_holding", observed_kernel)
    monkeypatch.setattr(module.os, "replace", checked_replace)
    monkeypatch.setattr(module, "write_frame", interrupted_write)
    with pytest.raises(RuntimeError, match="staged holding peer"):
        inputs.holding("0003", anchors["TW:0003"])
    valid_peer = output / "0003.parquet"
    valid_before = valid_peer.read_bytes(), valid_peer.stat().st_mtime_ns
    assert not (output / "0001.parquet").exists()  # A new staged half-write never becomes canonical.
    # An old direct-write implementation may already have left this canonical
    # half-file; the new restart path must repair it rather than trust exists().
    (output / "0001.parquet").write_bytes(b"PAR1old half-written canonical peer")
    monkeypatch.setattr(module, "write_frame", write)
    recovered = inputs.holding("0001", anchors["TW:0001"])
    peers = ("TW:0003", "TW:0001", "TW:0005", "TW:0002")
    assert reductions == [peers, peers]
    assert publications == ["0003", "0001", "0005", "0002"]
    assert valid_before == (valid_peer.read_bytes(), valid_peer.stat().st_mtime_ns)
    assert unrelated_before == (unrelated.read_bytes(), unrelated.stat().st_mtime_ns)
    close, jumps, industries, benchmark, context = _holding_inputs()
    expected = holding_values(
        close,
        industries,
        benchmark.Close,
        context.set_index("Date").retrospective_state,
        jump_matrix=jumps,
        benchmark_jump=benchmark.quality_reason.fillna("").str.contains("unexplained.*jump", regex=True),
        anchors=anchors,
    )
    pd.testing.assert_frame_equal(recovered.reset_index(drop=True), expected.loc[expected.security_id.eq("TW:0001")].reset_index(drop=True), check_exact=True)
    for security in peers:
        actual = inputs.holding(security.removeprefix("TW:"), anchors[security])
        pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.loc[expected.security_id.eq(security)].reset_index(drop=True), check_exact=True)
    assert reductions == [peers, peers]  # Valid reads never rerun any partition.
    assert not list(output.glob("*receipt*")) and not list(output.glob("*manifest*"))


@pytest.mark.parametrize("damage", ("schema", "missing_horizon", "wrong_security", "wrong_clock"))
def test_holding_cache_rejects_readable_but_incomplete_fixed_clock(tmp_path: Path, damage: str) -> None:
    close, jumps, industries, benchmark, context = _holding_inputs()
    security, anchors = "TW:0003", [0, 20]
    frame = holding_values(
        close,
        industries,
        benchmark.Close,
        context.set_index("Date").retrospective_state,
        jump_matrix=jumps,
        benchmark_jump=benchmark.quality_reason.fillna("").str.contains("unexplained.*jump", regex=True),
        anchors={security: anchors},
    )
    if damage == "schema":
        frame = frame.drop(columns="own_return")
    elif damage == "missing_horizon":
        frame = frame.iloc[:-1].copy()
    elif damage == "wrong_security":
        frame["security_id"] = "TW:9999"
    else:
        frame.loc[frame.index[0], "t0"] = "2010-01-05"
    path = tmp_path / "readable.parquet"
    module.write_frame(frame, path, index=False)
    assert module._cached_holding(path, security, cast(pd.DatetimeIndex, close.index), anchors, full=True, exact_anchors=True) is None


def test_holding_cache_permission_error_propagates_without_kernel_or_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs, anchors = _holding_cache_inputs(tmp_path / "permission-inputs")
    denied = PermissionError("synthetic holding footer denied")

    def denied_footer(*args: Any, **kwargs: Any) -> Any:
        raise denied

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("permission errors must not trigger kernel recomputation or repair")

    monkeypatch.setattr(module.pq, "read_metadata", denied_footer)
    monkeypatch.setattr(module, "industry_holding", forbidden)
    monkeypatch.setattr(module.os, "replace", forbidden)
    with pytest.raises(PermissionError) as error:
        inputs.holding("0003", anchors["TW:0003"])
    assert error.value is denied
