"""Synthetic exact shared-price transfer and narrowly owned retirement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_price_references_v4 as prices
from research_core import pattern_scan_shared_prices_v4 as shared
from research_core import price_basis
from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, read_json, write_json
from research_core.pattern_scan_parquet_v1 import write_frame


def _pin(path: Path) -> dict[str, Any]:
    return {**describe_file(path.parent, path), "path": str(path)}


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    run = primary / ".tmp/pattern-scan-execution/synthetic-price-transfer"
    (run / "prepared").mkdir(parents=True)
    external = tmp_path / "shared"
    external.mkdir()
    (external / "keep.bin").write_bytes(b"shared generation owned elsewhere")
    generation = external / "derived/adjusted-daily-v1/generations/synthetic-generation"
    generation.mkdir(parents=True)
    write_json(generation / "status.json", {"generation": "synthetic-generation", "synthetic": True})
    dependencies = {}
    for role in ("raw", "actions", "calendar"):
        path = generation / f"{role}.parquet"
        path.write_bytes(f"synthetic {role} dependency".encode("utf-8"))
        dependencies[role] = _pin(path)
    calendar = pd.DatetimeIndex(pd.to_datetime(["2010-01-04", "2026-10-12"]), name="Date")
    reference = {
        "root": str(external),
        "generation": "synthetic-generation",
        "calendar": {"dates": calendar.strftime("%Y-%m-%d").tolist(), "name": calendar.name},
        "inputs": dependencies,
    }
    frame = pd.DataFrame(index=calendar)
    for name in shared.maintained.ARROW_SCHEMA.names[2:]:
        if name == "Quality":
            frame[name] = [True, False]
        elif name in {"quality_reason", "volume_status", "corporate_action_types"}:
            frame[name] = ["observed", "missing"]
        else:
            frame[name] = [12.5, float("nan")]
    source = {"source_id": "original-source", "code": {"commit": "a" * 40, "dirty": False}}
    input_id = "original-input"
    fingerprint = {"inputs": {"price_daily": {"sha256": "b" * 64}, "corporate_actions": {"sha256": "c" * 64}}}
    reference["input_fingerprint"] = fingerprint["inputs"]
    monkeypatch.setattr(prices, "EXPECTED_STOCKS", 1)
    monkeypatch.setattr(prices, "EXPECTED_SESSIONS", 2)
    monkeypatch.setattr(shared, "SESSIONS", 2)
    prices._CACHE.clear()

    def make_reference(root: Path, generation: str, dates: pd.DatetimeIndex, *, expected_fingerprint: dict[str, Any]) -> dict[str, Any]:
        assert root == external and generation == reference["generation"]
        pd.testing.assert_index_equal(dates, calendar)
        assert expected_fingerprint == fingerprint
        return reference

    def read_reference(packet: dict[str, Any], code: str, *, stock_part: bool = False, columns: list[str] | None = None) -> pd.DataFrame:
        assert packet == reference and code in {"1101", "0050"}
        result = shared.as_stock_prices(frame, code) if stock_part else frame.copy()
        return result if columns is None else result.loc[:, columns]

    monkeypatch.setattr(prices, "make_price_reference", make_reference)
    monkeypatch.setattr(prices, "read_reference_frame", read_reference)
    prepared_path = run / "prepared/1101.parquet"
    benchmark = run / "prepared/0050.parquet"
    for path in (prepared_path, benchmark):
        write_frame(frame, path, index=True)
    write_json(prepared_path.with_suffix(".json"), {"sha256": file_digest(prepared_path), "identity": {"input_id": input_id}})
    directory = run / "parts/1101"
    directory.mkdir(parents=True)
    write_frame(shared.as_stock_prices(frame, "1101"), directory / "prices.parquet", index=True)
    (directory / "events.bin").write_bytes(b"retain completed event calculations")
    part = {
        "code": "1101",
        "complete": True,
        "source_id": source["source_id"],
        "input_id": input_id,
        "output_path": str(directory),
        "artifacts": [describe_file(directory, directory / name) for name in ("prices.parquet", "events.bin")],
    }
    write_json(directory / "receipt.json", part)
    prepared = {
        "schema": "pattern-scan-derived-preparation.v2",
        "scope": "full_ordinary_reference",
        "calendar_n": 2,
        "ordinary_reference_n": 1,
        "source": source,
        "input_id": input_id,
        "producer_fingerprint": fingerprint,
        "benchmark_path": str(benchmark),
        "requests": [{"code": "1101", "prepared_path": str(prepared_path)}],
        "artifacts": [describe_file(run, path) for path in (prepared_path, benchmark)],
    }
    write_json(run / "derived-preparation.json", prepared)
    write_json(run / "producer-read-receipt.json", {"complete": True})
    phase = {"phase": "full_stock_checkpoints", "global_analysis_admitted": False, "pool": {"results": [part]}}
    write_json(run / "phase-stock-result.json", phase)
    request = {"source": source, "phase": "stock"}
    write_json(run / "request-stock.json", request)
    receipt = {
        "code": source["code"],
        "parameters": {"source_id": source["source_id"], "input_id": input_id},
        "results": {"derived_preparation": _pin(run / "derived-preparation.json"), "phase_result": _pin(run / "phase-stock-result.json")},
    }
    write_json(run / "run-stock-receipt.json", receipt)
    response = {
        "complete": True,
        "result": phase,
        "request_id": object_digest(request),
        "source_id": source["source_id"],
        "input_id": input_id,
        "run_receipt_path": str(run / "run-stock-receipt.json"),
        "run_receipt_sha256": file_digest(run / "run-stock-receipt.json"),
    }
    write_json(run / "response-stock.json", response)
    write_json(
        run / "response-stock.job-memory.json",
        {"complete": True, "request_id": response["request_id"], "response_sha256": file_digest(run / "response-stock.json")},
    )
    return {
        "run": run,
        "reference": reference,
        "external": external,
        "frame": frame,
        "directory": directory,
        "part": part,
        "prepared": prepared_path,
        "benchmark": benchmark,
        "executor": {"commit": "d" * 40, "dirty": False},
        "original": {path: path.read_bytes() for path in run.rglob("*") if path.is_file()},
        "external_original": {path: path.read_bytes() for path in external.rglob("*") if path.is_file()},
    }


def _create(case: dict[str, Any]) -> dict[str, Any]:
    return prices.create_price_handoff(case["run"], case["reference"], executor=case["executor"], calculation_authorized=True)


def _retire(case: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    return prices.retire_own_prices(case["run"], handoff, retirement_authorized=True)


def _replace_case_prepared_prices(case: dict[str, Any], expected: dict[str, pd.DataFrame]) -> None:
    """Rebuild the synthetic original preparation and its dependent receipt pins."""
    run, directory = case["run"], case["directory"]
    for code, path in (("1101", case["prepared"]), ("0050", case["benchmark"])):
        write_frame(expected[code], path, index=True)
    own = read_json(case["prepared"].with_suffix(".json"))
    own["sha256"] = file_digest(case["prepared"])
    case["prepared"].with_suffix(".json").write_bytes(canonical(own))
    write_frame(shared.as_stock_prices(expected["1101"], "1101"), directory / "prices.parquet", index=True)
    part = read_json(directory / "receipt.json")
    part["artifacts"] = [describe_file(directory, directory / name) for name in ("prices.parquet", "events.bin")]
    (directory / "receipt.json").write_bytes(canonical(part))
    prepared = read_json(run / "derived-preparation.json")
    prepared["artifacts"] = [describe_file(run, path) for path in (case["prepared"], case["benchmark"])]
    (run / "derived-preparation.json").write_bytes(canonical(prepared))
    phase = read_json(run / "phase-stock-result.json")
    phase["pool"]["results"] = [part]
    (run / "phase-stock-result.json").write_bytes(canonical(phase))
    receipt = read_json(run / "run-stock-receipt.json")
    receipt["results"] = {"derived_preparation": _pin(run / "derived-preparation.json"), "phase_result": _pin(run / "phase-stock-result.json")}
    (run / "run-stock-receipt.json").write_bytes(canonical(receipt))
    response = read_json(run / "response-stock.json")
    response.update(result=phase, run_receipt_sha256=file_digest(run / "run-stock-receipt.json"))
    (run / "response-stock.json").write_bytes(canonical(response))
    memory = read_json(run / "response-stock.job-memory.json")
    memory["response_sha256"] = file_digest(run / "response-stock.json")
    (run / "response-stock.job-memory.json").write_bytes(canonical(memory))
    case["part"] = part


def test_real_maintained_generation_adapter_handoff_retirement_exact(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise real persisted as-of inputs through the reader and both consumers."""
    maintained = shared.maintained

    def forbidden_producer(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("synthetic generation integration must never load producer inputs")

    monkeypatch.setattr(maintained, "load_inputs", forbidden_producer)
    calendar = pd.DatetimeIndex(pd.to_datetime(["2010-01-04", "2026-10-12"]), name="Date")
    after_cutoff = pd.Timestamp("2026-10-13")
    rows = []
    for code, close in (("1101", 100.0), ("0050", 200.0)):
        for day in (calendar[0], calendar[1], after_cutoff):
            if code == "1101" and day == calendar[1]:
                continue  # The requested calendar must preserve this missing quote.
            value = close / 2 if day == after_cutoff else close
            rows.append({"Code": code, "Date": day, "Open": value, "High": value, "Low": value, "Close": value, "Volume": 1000.0, "Source": "official"})
    bars = pd.DataFrame(rows)
    actions = pd.DataFrame([{"code": code, "ex_date": "2026-10-13", "event_type": "ETF_SPLIT", "price_factor": 0.5} for code in ("1101", "0050")])
    generation = "real-synthetic-generation"
    directory = case["external"] / "derived" / maintained.FAMILY / "generations" / generation
    directory.mkdir()
    # Use the real generation writer primitives, without any producer/update entry.
    writers: dict[str, Any] = {
        basis: pq.ParquetWriter(directory / f"{basis}.parquet", maintained.ARROW_SCHEMA, compression="zstd") for basis in maintained.BASES
    }
    try:
        summary = maintained.compute(bars, actions, writers)
    finally:
        for writer in writers.values():
            writer.close()
    for basis in maintained.BASES:
        path = directory / f"{basis}.parquet"
        summary["bases"][basis].update({"file": path.name, "bytes": path.stat().st_size, "sha256": file_digest(path)})
    prepared = read_json(case["run"] / "derived-preparation.json")
    write_json(
        directory / "status.json",
        {
            "schema": maintained.SCHEMA,
            "family": maintained.FAMILY,
            "generation": generation,
            "definition": {"prices": price_basis.DEFINITION_VERSION},
            "source_policy": {"kept": "official"},
            **summary,
            "as_of_inputs": maintained._write_as_of_inputs(directory, bars, actions),
            "input_fingerprint": prepared["producer_fingerprint"],
        },
    )
    # Undo only the two adapter stubs installed by case. The maintained reader,
    # compute, Parquet I/O and price_basis implementation are all real functions.
    monkeypatch.setattr(prices, "make_price_reference", shared.make_price_reference)
    monkeypatch.setattr(prices, "read_reference_frame", shared.read_reference_frame)
    expected = {
        code: price_basis.prepare_prices(
            bars.loc[bars.Code.eq(code) & bars.Date.le(calendar[-1])],
            actions,
            calendar,
            basis="reference_factor_adjusted",
            cutoff=shared.CUTOFF,
        )
        for code in ("1101", "0050")
    }
    _replace_case_prepared_prices(case, expected)
    reference = shared.make_price_reference(case["external"], generation, calendar, expected_fingerprint=prepared["producer_fingerprint"])
    case["reference"] = reference
    # A truncate-only reader would retain the later split's factor of 0.5.
    current, _ = maintained.read_adjusted_daily("reference_factor_adjusted", root=case["external"], generation=generation, codes=["0050"])
    assert current.loc[current.Date.eq(calendar[0]), "Close"].item() == 100.0
    for code in ("1101", "0050"):
        actual = shared.read_reference_frame(reference, code)
        pd.testing.assert_frame_equal(actual, expected[code], check_exact=True, check_dtype=True, check_freq=True)
        pd.testing.assert_frame_equal(
            shared.read_reference_frame(reference, code, stock_part=True),
            shared.as_stock_prices(expected[code], code),
            check_exact=True,
            check_dtype=True,
            check_freq=True,
        )
    assert expected["0050"].loc[calendar[0], "Close"] == 200.0
    assert pd.isna(expected["1101"].loc[calendar[-1], "Close"])
    assert not bool(expected["1101"].loc[calendar[-1], "Quality"])
    assert "missing_official_quote" in expected["1101"].loc[calendar[-1], "quality_reason"]
    price_paths = {case["prepared"], case["prepared"].with_suffix(".json"), case["benchmark"], case["directory"] / "prices.parquet"}
    nonprice = {path: path.read_bytes() for path in case["run"].rglob("*") if path.is_file() and path not in price_paths}
    shared_files = {path: (path.stat().st_ino, path.read_bytes()) for path in case["external"].rglob("*") if path.is_file()}
    handoff = _create(case)
    result = _retire(case, handoff)
    assert result["removed_files"] == len(price_paths)
    assert all(not path.exists() for path in price_paths)
    prices.verify_stock_artifacts(case["directory"], case["part"])
    pd.testing.assert_frame_equal(prices.read_benchmark(case["run"]), expected["0050"], check_exact=True, check_dtype=True, check_freq=True)
    pd.testing.assert_frame_equal(
        prices.read_stock_prices(case["directory"]),
        shared.as_stock_prices(expected["1101"], "1101"),
        check_exact=True,
        check_dtype=True,
        check_freq=True,
    )
    assert all(path.read_bytes() == content for path, content in nonprice.items())
    assert {path: (path.stat().st_ino, path.read_bytes()) for path in case["external"].rglob("*") if path.is_file()} == shared_files


@pytest.fixture
def worker_case(case: dict[str, Any]) -> dict[str, Any]:
    run = case["run"]
    directory = run / "workers" / ("a" * 32) / "000000"
    directory.mkdir(parents=True)
    prepared = read_json(run / "derived-preparation.json")
    write_json(
        directory / "request.json",
        {
            "source": prepared["source"],
            "response_path": str(directory / "response.json"),
            "stocks": prepared["requests"],
        },
    )
    worker_response = {"complete": True, "results": [case["part"]]}
    write_json(directory / "response.json", worker_response)
    phase = read_json(run / "phase-stock-result.json")
    phase["pool"]["workers_receipts"] = [{**worker_response, "job_memory": {"complete": True}, "process_wall_seconds": 0.1}]
    (run / "phase-stock-result.json").write_bytes(canonical(phase))
    receipt = read_json(run / "run-stock-receipt.json")
    receipt["results"]["phase_result"] = _pin(run / "phase-stock-result.json")
    (run / "run-stock-receipt.json").write_bytes(canonical(receipt))
    response = read_json(run / "response-stock.json")
    response.update(result=phase, run_receipt_sha256=file_digest(run / "run-stock-receipt.json"))
    (run / "response-stock.json").write_bytes(canonical(response))
    memory = read_json(run / "response-stock.job-memory.json")
    memory["response_sha256"] = file_digest(run / "response-stock.json")
    (run / "response-stock.job-memory.json").write_bytes(canonical(memory))
    case["worker_directory"] = directory
    case["original"] = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
    return case


def test_original_worker_envelopes_retained_through_price_retirement(worker_case: dict[str, Any]) -> None:
    handoff = _create(worker_case)
    body = read_json(worker_case["run"] / prices.HANDOFF)
    worker_files = list(worker_case["worker_directory"].iterdir())
    assert all(path.relative_to(worker_case["run"]).as_posix() in body["owned_nonprice"] for path in worker_files)
    _retire(worker_case, handoff)
    for path in worker_files:
        assert path.read_bytes() == worker_case["original"][path]


@pytest.mark.parametrize("mutation", ["request", "response", "unknown", "additional_packet"])
@pytest.mark.parametrize("after_handoff", [False, True])
def test_unrecognized_worker_metadata_never_deletes_prices(
    worker_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    after_handoff: bool,
) -> None:
    handoff = _create(worker_case) if after_handoff else None
    directory = worker_case["worker_directory"]
    if mutation in {"request", "response"}:
        (directory / f"{mutation}.json").write_bytes(canonical({"changed": True}))
    elif mutation == "unknown":
        (directory / "foreign.bin").write_bytes(b"unrecognized metadata")
    else:
        extra = directory.parent / "000001"
        extra.mkdir()
        for name in ("request.json", "response.json"):
            (extra / name).write_bytes((directory / name).read_bytes())
    calls: list[Path] = []

    def forbidden_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        calls.append(path)
        raise AssertionError("worker validation must finish before deletion")

    monkeypatch.setattr(Path, "unlink", forbidden_unlink)
    with pytest.raises(ValueError):
        if handoff is None:
            _create(worker_case)
        else:
            _retire(worker_case, handoff)
    assert calls == []
    assert worker_case["prepared"].is_file() and worker_case["benchmark"].is_file()
    assert (worker_case["directory"] / "prices.parquet").is_file()


def test_exact_transfer_replaces_prices_and_preserves_original_receipts(case: dict[str, Any]) -> None:
    handoff = _create(case)
    assert handoff == {"path": str(case["run"] / prices.HANDOFF), "sha256": file_digest(case["run"] / prices.HANDOFF)}
    assert all(path.read_bytes() == content for path, content in case["original"].items())
    audit = read_json(case["run"] / prices.EQUALITY)
    assert audit["mismatch_n"] == 0 and set(audit["securities"]) == {"0050", "1101"}
    assert audit["securities"]["1101"]["rows"] == 2
    prices.verify_stock_artifacts(case["directory"], case["part"])
    expected = shared.as_stock_prices(case["frame"], "1101")
    pd.testing.assert_frame_equal(prices.read_stock_prices(case["directory"]), expected, check_exact=True)
    pd.testing.assert_frame_equal(
        prices.read_stock_prices(case["directory"], columns=["Close", "security_id", "calendar_index", "asof_date"]),
        expected.loc[:, ["Close", "security_id", "calendar_index", "asof_date"]],
    )
    pd.testing.assert_frame_equal(prices.read_benchmark(case["run"]), case["frame"])
    assert _create(case) == handoff
    result = _retire(case, handoff)
    assert result["removed_files"] == 4 and result["other_stock_artifacts_retained"] is True
    assert not case["prepared"].exists() and not case["prepared"].with_suffix(".json").exists()
    assert not case["benchmark"].exists() and not (case["directory"] / "prices.parquet").exists()
    for path, content in case["original"].items():
        if path.exists():
            assert path.read_bytes() == content
    assert (case["directory"] / "events.bin").read_bytes() == b"retain completed event calculations"
    assert all(path.read_bytes() == content for path, content in case["external_original"].items())
    prices.verify_stock_artifacts(case["directory"], case["part"])
    pd.testing.assert_frame_equal(prices.read_stock_prices(case["directory"]), expected)
    assert _retire(case, handoff) == result


def test_creation_and_retirement_require_explicit_authorization(case: dict[str, Any]) -> None:
    with pytest.raises(PermissionError):
        prices.create_price_handoff(case["run"], case["reference"], executor=case["executor"])
    handoff = _create(case)
    with pytest.raises(PermissionError):
        prices.retire_own_prices(case["run"], handoff)
    assert all(path.exists() for path in case["original"])


def test_actual_frame_mismatch_never_publishes_certificate(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    wrong = case["frame"].copy()
    wrong.iloc[0, 0] += 1
    monkeypatch.setattr(prices, "read_reference_frame", lambda *_args, **_kwargs: wrong)
    with pytest.raises(AssertionError):
        _create(case)
    assert not (case["run"] / prices.HANDOFF).exists()
    assert not (case["run"] / prices.EQUALITY).exists()
    assert all(path.read_bytes() == content for path, content in case["original"].items())


def test_stock_metadata_must_also_match_exactly(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    original = prices.as_stock_prices

    def changed_metadata(frame: pd.DataFrame, code: str) -> pd.DataFrame:
        result = original(frame, code)
        result["calendar_index"] += 1
        return result

    monkeypatch.setattr(prices, "as_stock_prices", changed_metadata)
    with pytest.raises(AssertionError):
        _create(case)
    assert not (case["run"] / prices.HANDOFF).exists()
    assert all(path.read_bytes() == content for path, content in case["original"].items())


def test_active_calculation_blocks_even_creating_handoff(case: dict[str, Any]) -> None:
    write_json(case["run"] / prices.ACTIVE, {"active": True})
    with pytest.raises(ValueError, match="actively executing"):
        _create(case)
    assert not (case["run"] / prices.HANDOFF).exists()


@pytest.mark.parametrize("active_owner", [None, "different-owner"])
def test_active_token_requires_exact_owner_for_both_operations(case: dict[str, Any], active_owner: str | None) -> None:
    handoff = _create(case)
    active = case["run"] / prices.ACTIVE
    write_json(active, {"owner": "actual-owner"})
    token = active.read_bytes()
    with pytest.raises(ValueError, match="actively executing"):
        prices.create_price_handoff(
            case["run"],
            case["reference"],
            executor=case["executor"],
            calculation_authorized=True,
            active_owner=active_owner,
        )
    with pytest.raises(ValueError, match="actively executing"):
        prices.retire_own_prices(case["run"], handoff, retirement_authorized=True, active_owner=active_owner)
    assert all(path.exists() for path in case["original"])
    assert active.read_bytes() == token


def test_exact_active_owner_can_transfer_and_retire_without_removing_token(case: dict[str, Any]) -> None:
    active = case["run"] / prices.ACTIVE
    write_json(active, {"owner": "actual-owner"})
    token = active.read_bytes()
    handoff = prices.create_price_handoff(
        case["run"],
        case["reference"],
        executor=case["executor"],
        calculation_authorized=True,
        active_owner="actual-owner",
    )
    assert all(path.exists() for path in case["original"])
    result = prices.retire_own_prices(case["run"], handoff, retirement_authorized=True, active_owner="actual-owner")
    assert result["removed_files"] == 4
    assert active.read_bytes() == token
    assert (case["directory"] / "events.bin").is_file()


def test_completed_equivalence_reused_after_handoff_publication_failure(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    publish = prices._publish

    def fail_handoff(run: Path, name: str, body: dict[str, Any]) -> None:
        if name == prices.HANDOFF:
            raise OSError("synthetic handoff publication interrupted")
        publish(run, name, body)

    monkeypatch.setattr(prices, "_publish", fail_handoff)
    with pytest.raises(OSError, match="synthetic handoff publication interrupted"):
        _create(case)
    audit = case["run"] / prices.EQUALITY
    assert audit.is_file() and not (case["run"] / prices.HANDOFF).exists()
    retained_audit = audit.read_bytes()
    assert all(path.read_bytes() == content for path, content in case["original"].items())

    def forbidden_read(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise AssertionError("completed equivalence must not repeat shared price reads")

    monkeypatch.setattr(prices, "_publish", publish)
    monkeypatch.setattr(prices, "read_reference_frame", forbidden_read)
    handoff = _create(case)
    assert handoff["sha256"] == file_digest(case["run"] / prices.HANDOFF)
    assert audit.read_bytes() == retained_audit
    assert all(path.read_bytes() == content for path, content in case["original"].items())


@pytest.mark.parametrize("mutation", ["active", "unknown", "price", "receipt", "nonprice", "handoff_pin", "hardlink"])
def test_preflight_blocks_before_first_unlink(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    handoff = _create(case)
    if mutation == "active":
        write_json(case["run"] / prices.ACTIVE, {"active": True})
    elif mutation == "unknown":
        (case["run"] / "foreign.bin").write_bytes(b"unregistered")
    elif mutation == "price":
        case["prepared"].write_bytes(b"changed original prices")
    elif mutation == "receipt":
        (case["directory"] / "receipt.json").write_bytes(canonical({"changed": True}))
    elif mutation == "nonprice":
        (case["directory"] / "events.bin").write_bytes(b"changed events")
    elif mutation == "handoff_pin":
        handoff = {**handoff, "sha256": "0" * 64}
    else:
        try:
            os.link(case["prepared"], case["external"] / "price-alias.parquet")
        except OSError as error:
            pytest.skip(f"hardlink unavailable: {error}")
    calls: list[Path] = []

    def forbidden_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        calls.append(path)
        raise AssertionError("preflight must finish before unlink")

    monkeypatch.setattr(Path, "unlink", forbidden_unlink)
    with pytest.raises((ValueError, FileNotFoundError)):
        _retire(case, handoff)
    assert calls == []
    assert case["benchmark"].is_file() and (case["directory"] / "prices.parquet").is_file()


def test_missing_generation_has_no_local_fallback(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = _create(case)

    def missing(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise FileNotFoundError("pinned shared generation retired")

    monkeypatch.setattr(prices, "read_reference_frame", missing)
    for call in (lambda: prices.read_stock_prices(case["directory"]), lambda: prices.read_benchmark(case["run"]), lambda: _retire(case, handoff)):
        with pytest.raises(FileNotFoundError, match="pinned shared generation retired"):
            call()
    assert all(path.exists() for path in case["original"])


def test_missing_local_price_without_certificate_rejected(case: dict[str, Any]) -> None:
    (case["directory"] / "prices.parquet").unlink()
    with pytest.raises(FileNotFoundError):
        prices.verify_stock_artifacts(case["directory"], case["part"])
    with pytest.raises(FileNotFoundError):
        prices.read_stock_prices(case["directory"])


def test_journaled_partial_unlink_retries_without_recomputing(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = _create(case)
    original_unlink = Path.unlink
    removed: list[Path] = []

    def fail_second(path: Path, *args: Any, **kwargs: Any) -> None:
        if len(removed) == 1:
            raise OSError("synthetic second unlink failure")
        original_unlink(path, *args, **kwargs)
        removed.append(path)

    monkeypatch.setattr(Path, "unlink", fail_second)
    with pytest.raises(OSError, match="synthetic second unlink failure"):
        _retire(case, handoff)
    assert len(removed) == 1 and not removed[0].exists()
    assert (case["run"] / prices.PLAN).is_file()
    assert not (case["run"] / prices.RETIRED).exists()
    monkeypatch.setattr(Path, "unlink", original_unlink)
    result = _retire(case, handoff)
    assert result["removed_files"] == 4
    assert (case["directory"] / "events.bin").is_file()
    assert _retire(case, handoff) == result


@pytest.mark.parametrize("field", ["price_files", "stock_parts", "owned_nonprice", "ancestors"])
def test_handoff_inventory_cannot_be_rewritten_without_audit(case: dict[str, Any], field: str) -> None:
    _create(case)
    path = case["run"] / prices.HANDOFF
    body = read_json(path)
    body[field] = {}
    path.write_bytes(canonical(body))
    prices._CACHE.clear()
    with pytest.raises(ValueError):
        prices.read_benchmark(case["run"])
    assert all(path.exists() for path in case["original"])


def test_formal_publication_cleanup_after_early_shared_price_retirement(case: dict[str, Any]) -> None:
    """Early v4 price transfer must compose with the later v3 result lifecycle."""
    from research_core import pattern_scan_result_lifecycle_v3 as lifecycle
    from research_core.research_data_catalog import DataCatalog, verify_entry
    from research_core.research_data_paths import DataRoots

    run = case["run"]
    handoff = _create(case)
    _retire(case, handoff)
    assert not (run / "prepared").exists()
    assert not (case["directory"] / "prices.parquet").exists()
    retained_prices_evidence = {name: (run / name).read_bytes() for name in (prices.EQUALITY, prices.RETIRED)}
    source = read_json(run / "derived-preparation.json")["source"]
    input_id = case["part"]["input_id"]
    analysis = run / "analysis"
    analysis.mkdir()
    aggregate = analysis / "aggregate.parquet"
    write_frame(pd.DataFrame({"cell_id": ["synthetic"], "known_n": [3], "unknown_n": [1]}), aggregate, index=False)
    aggregate_bytes = aggregate.read_bytes()
    report = analysis / "report.md"
    report.write_text("# Synthetic retained result\n\nInvented values for lifecycle verification.\n", encoding="utf-8")
    verification = run / "delivery-verification.json"
    write_json(
        verification,
        {
            "schema": "pattern-scan-delivery-verification.v3",
            "complete": True,
            "source_id": source["source_id"],
            "input_id": input_id,
            "event_audit_n": 10,
            "candidate_audit_n": 5,
            "candidate_comparison_rows": 54_720,
            "mismatch_n": 0,
        },
    )
    descriptor = lifecycle.record_computed_results(
        run,
        {
            "aggregates/aggregate.parquet": aggregate,
            "execution/shared-price-equivalence.json": run / prices.EQUALITY,
            "execution/own-price-retirement-receipt.json": run / prices.RETIRED,
        },
        source=source,
        input_id=input_id,
        provenance={"synthetic": True, "early_shared_price_handoff": handoff},
        transient_files=[path for path in run.rglob("*") if path.is_file()],
    )
    primary = run.parent.parent.parent
    roots = DataRoots(primary, primary / "research_data")
    catalog = DataCatalog(roots)
    unavailable = {"start": None, "end": None, "reason": "synthetic only"}
    metadata = {
        "data_id": "synthetic-early-price-retirement-results",
        "kind": "patterns",
        "definition_version": "fixture.v1",
        "parameters": {"fixture": True},
        "inputs": {"source_id": source["source_id"], "input_id": input_id},
        "coverage": {"scope": "invented", "raw_input_period": unavailable, "valid_indicator_period": unavailable, "complete_label_period": unavailable},
        "status": "complete",
        "limitations": ["synthetic fixture"],
        "backup": {"status": "not_backed_up", "off_machine": False},
    }
    proof = lifecycle.handoff_results(
        descriptor,
        catalog,
        metadata,
        managed_parent="bundles/synthetic-early-price-retirement-results",
        verification=verification,
        report=report,
    )
    entry = proof["entry"]
    final = roots.artifact_path(entry["manifest"]["scope"], entry["manifest"]["path"]).parent
    verify_entry(entry, roots)
    final_hashes = {path.relative_to(final).as_posix(): file_digest(path) for path in final.rglob("*") if path.is_file()}
    assert (final / "aggregates/aggregate.parquet").read_bytes() == aggregate_bytes
    for original_name, retained_name in (
        (prices.EQUALITY, "execution/shared-price-equivalence.json"),
        (prices.RETIRED, "execution/own-price-retirement-receipt.json"),
    ):
        assert (final / retained_name).read_bytes() == retained_prices_evidence[original_name]
    cleanup = lifecycle.cleanup_run(run, catalog)
    assert cleanup["complete"] is True and cleanup["prices_retained"] is False
    assert lifecycle.verify_retained_status(run, catalog) == {"entry": entry, "prices_retained": False}
    assert not (case["directory"] / "events.bin").exists()
    assert not (run / "prepared").exists()
    assert {path.relative_to(final).as_posix(): file_digest(path) for path in final.rglob("*") if path.is_file()} == final_hashes
    verify_entry(entry, roots)
    assert all(path.read_bytes() == content for path, content in case["external_original"].items())
