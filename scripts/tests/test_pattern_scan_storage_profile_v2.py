"""Synthetic storage profiling; real descriptors/Parquet, mocked calculations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_barrier_v1 as barrier_module
from research_core import pattern_scan_storage_profile_v2 as storage
from research_core.artifact_store import describe_file, file_digest, read_json, write_json


@pytest.fixture
def sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    source = {"source_id": "synthetic-source"}
    monkeypatch.setattr(barrier_module, "verify_source", lambda value: None)
    monkeypatch.setattr(storage, "PATTERNS", ("B4", "H1"))
    calls = {"select": 0, "summarize": 0, "followup": 0}

    def parquet(path: Path, rows: int) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"synthetic": range(rows)}).to_parquet(path, index=False)
        return path

    part = tmp_path / "stock"
    checkpoint = parquet(part / "prices.parquet", 5)
    write_json(
        part / "receipt.json",
        {
            "complete": True,
            "code": "1101",
            "output_path": str(part),
            "request_id": "stock-request",
            "source_id": source["source_id"],
            "input_id": "inputs",
            "artifacts": [describe_file(part, checkpoint)],
        },
    )
    global_directory = tmp_path / "barrier"
    global_path = parquet(global_directory / "1101.parquet", 5)
    global_files = {"1101": {"path": str(global_path), "sha256": file_digest(global_path)}}
    sidecars = {}
    for name in ("context", "close_matrix", "jump_matrix", "benchmark"):
        path = parquet(global_directory / f"{name}.parquet", 5)
        sidecars[name] = {"path": str(path), "sha256": file_digest(path)}
    barrier = {
        "schema": "pattern-scan-barrier.v1",
        "complete": True,
        "source_id": source["source_id"],
        "input_id": "inputs",
        "identity": {"stock_receipts": {"1101": file_digest(part / "receipt.json")}},
        "global_files": global_files,
        "sidecars": sidecars,
        "artifacts": [describe_file(global_directory, path) for path in sorted(global_directory.glob("*.parquet"))],
    }
    write_json(global_directory / "receipt.json", barrier)
    events = {}
    for target in storage.PATTERNS:
        directory = tmp_path / f"events-{target}"
        path = parquet(directory / "events.parquet", 9)  # Deliberately exceeds old four-event cap.
        write_json(
            directory / "receipt.json",
            {
                "schema": "pattern-scan-event-part.v1",
                "complete": True,
                "identity": {
                    "code": "1101",
                    "target": target,
                    "source_id": source["source_id"],
                    "input_id": "inputs",
                    "stock_request_id": "stock-request",
                    "global_sha256": global_files["1101"]["sha256"],
                },
                "artifacts": [describe_file(directory, path)],
            },
        )
        events[target] = {"1101": directory}

    def select(event_parts: dict[str, dict[str, Path]]) -> dict[str, Any]:
        calls["select"] += 1
        assert event_parts == events
        return {target: {"candidates": []} for target in storage.PATTERNS}

    def summarize(event_parts: dict[str, dict[str, Path]], selections: dict[str, Any], output: Path) -> dict[str, Any]:
        calls["summarize"] += 1
        assert set(event_parts) == set(storage.PATTERNS)
        return {
            "files": {
                "summary/tiny.parquet": str(parquet(output / "summary.parquet", 6)),
                "annual/tiny.parquet": str(parquet(output / "annual.parquet", 7)),
            },
            "confirmation_top_input": [],
        }

    def followup(
        parts: dict[str, Path],
        supplied_barrier: dict[str, Any],
        event_parts: dict[str, dict[str, Path]],
        selections: dict[str, Any],
        summaries: dict[str, Any],
        output: Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls["followup"] += 1
        assert supplied_barrier == barrier and event_parts == events
        episodes = {
            "files": {
                "observations.parquet": str(parquet(output / "episodes" / "observations.parquet", 4)),
                "coverage.parquet": str(parquet(output / "episodes" / "coverage.parquet", 2)),
            }
        }
        receipt = {
            "files": {
                "observations/B4/1101/paths.parquet": str(parquet(output / "observations.parquet", 9)),
                "B4/summary.parquet": str(parquet(output / "summary.parquet", 3)),
                "holding_context.parquet": str(parquet(output / "holding.parquet", 2)),
            },
            "episodes": episodes,
        }
        write_json(output / "receipt.json", receipt)
        return receipt

    monkeypatch.setattr(storage, "select_all", select)
    monkeypatch.setattr(storage, "summarize_all", summarize)
    monkeypatch.setattr(storage, "complete_followup", followup)
    return {
        "parts": {"1101": part},
        "barrier": barrier,
        "event_parts": events,
        "source": source,
        "input_id": "inputs",
        "output": tmp_path / "primary" / "tasks" / "scratch",
        "calls": calls,
    }


def run(sample: dict[str, Any]) -> dict[str, Any]:
    return storage.profile_storage(**{key: value for key, value in sample.items() if key != "calls"})


def test_full_components_metadata_and_unchanged_resume(sample: dict[str, Any]) -> None:
    receipt = run(sample)
    components = receipt["components"]
    assert receipt["scope"]["max_stocks"] == 4
    assert receipt["scope"]["catalog_publication"] is False
    assert components["events_by_stock"]["1101"]["parquet_rows"] == 18
    assert components["checkpoints_by_stock"]["1101"]["parquet_rows"] == 5
    assert components["summaries"]["parquet_rows"] == 13
    assert components["followup_observations"]["parquet_rows"] == 9
    assert components["followup_summaries"]["parquet_rows"] == 3
    assert components["holding_context"]["parquet_rows"] == 2
    assert components["episodes"]["parquet_rows"] == 6
    assert components["report_copy"]["bytes"] == sum(
        components[key]["bytes"]
        for key in (
            "summaries",
            "followup_observations",
            "followup_summaries",
            "holding_context",
        )
    )
    assert receipt["exact_quantile_memory_bytes"] is None
    assert "do not expose" in receipt["exact_quantile_memory_reason"]
    assert all("native" in phase and phase["wall_seconds"] >= 0 for phase in receipt["phases"])
    assert {record["path"] for record in receipt["artifacts"]}.issuperset({"selection.json", "summary-index.json", "followup/receipt.json"})
    assert run(sample) == receipt
    assert sample["calls"] == {"select": 1, "summarize": 1, "followup": 1}
    assert (sample["output"] / "receipt.json").is_file()


@pytest.mark.parametrize("count", [0, 5])
def test_stock_bound_before_computation(sample: dict[str, Any], count: int) -> None:
    sample["parts"] = {str(code): next(iter(sample["parts"].values())) for code in range(count)}
    with pytest.raises(ValueError, match="one to four"):
        run(sample)
    assert sample["calls"] == {"select": 0, "summarize": 0, "followup": 0}


def test_event_stock_mismatch_rejected(sample: dict[str, Any]) -> None:
    sample["event_parts"]["B4"] = {}
    with pytest.raises(ValueError, match="stock-set"):
        run(sample)


@pytest.mark.parametrize("where", ["summary", "checkpoint", "event", "barrier", "source", "input"])
def test_changed_payload_or_identity_refuses_completed_reuse(sample: dict[str, Any], where: str) -> None:
    receipt = run(sample)
    paths = {
        "summary": Path(receipt["components"]["summaries"]["files"][0]["path"]),
        "checkpoint": sample["parts"]["1101"] / "prices.parquet",
        "event": sample["event_parts"]["B4"]["1101"] / "events.parquet",
        "barrier": Path(sample["barrier"]["sidecars"]["context"]["path"]),
    }
    if where in paths:
        with paths[where].open("ab") as stream:
            stream.write(b"changed")
    elif where == "source":
        sample["source"] = {"source_id": "different-source"}
    else:
        sample["input_id"] = "different-input"
    with pytest.raises(ValueError, match="differs|mismatch|changed"):
        run(sample)
    assert sample["calls"] == {"select": 1, "summarize": 1, "followup": 1}


def test_partial_outputs_preserved_and_summary_work_reused(sample: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    followup = storage.complete_followup

    def interrupted(*args: Any, **kwargs: Any) -> dict[str, Any]:
        output = args[5]
        output.mkdir(parents=True)
        staging = output / ".staging-interrupted"
        staging.mkdir()
        (staging / "partial.bin").write_bytes(b"preserve")
        raise RuntimeError("interrupted synthetic followup")

    monkeypatch.setattr(storage, "complete_followup", interrupted)
    with pytest.raises(RuntimeError, match="interrupted synthetic"):
        run(sample)
    assert not (sample["output"] / "receipt.json").exists()
    monkeypatch.setattr(storage, "complete_followup", followup)
    receipt = run(sample)
    assert sample["calls"] == {"select": 1, "summarize": 1, "followup": 1}
    assert receipt["retained_partial_staging_bytes"] == len(b"preserve")
    assert (sample["output"] / "followup" / ".staging-interrupted" / "partial.bin").read_bytes() == b"preserve"


def test_event_receipt_identity_checked(sample: dict[str, Any]) -> None:
    path = sample["event_parts"]["B4"]["1101"] / "receipt.json"
    receipt = read_json(path)
    receipt["identity"]["global_sha256"] = "0" * 64
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="event receipt identity"):
        run(sample)
