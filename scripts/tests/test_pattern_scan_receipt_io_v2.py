"""Finite scan receipt budgets and atomic, no-replace publication behavior."""

from pathlib import Path
from typing import Any

import pytest

from research_core import pattern_scan_receipt_io_v2 as receipt_io
from research_core.artifact_store import canonical, read_json


def test_interrupted_writer_retains_only_staging_and_retry_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    final = tmp_path / "receipt.json"
    original = receipt_io.write_json

    def interrupted(path: Path, value: dict[str, Any]) -> None:
        path.write_bytes(b'{"interrupted":')
        raise RuntimeError("synthetic writer interruption")

    monkeypatch.setattr(receipt_io, "write_json", interrupted)
    with pytest.raises(RuntimeError, match="synthetic writer interruption"):
        receipt_io.publish_scan_receipt(final, {"complete": True})
    partials = list(tmp_path.glob(".staging-receipt.json-*"))
    assert len(partials) == 1 and partials[0].read_bytes() == b'{"interrupted":'
    assert not final.exists()
    monkeypatch.setattr(receipt_io, "write_json", original)
    receipt_io.publish_scan_receipt(final, {"complete": True})
    assert receipt_io.read_scan_receipt(final) == {"complete": True}
    assert partials[0].read_bytes() == b'{"interrupted":'
    before = final.read_bytes()
    with pytest.raises(OSError):
        receipt_io.publish_scan_receipt(final, {"complete": False})
    assert final.read_bytes() == before
    assert any(path.read_bytes() == canonical({"complete": False}) for path in tmp_path.glob(".staging-receipt.json-*"))


def test_small_budget_rejects_oversized_writer_and_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receipt_io, "MAX_SCAN_RECEIPT_BYTES", 96)
    final = tmp_path / "receipt.json"
    receipt_io.publish_scan_receipt(final, {"value": "small"})
    assert receipt_io.read_scan_receipt(final) == {"value": "small"}
    oversized = tmp_path / "oversized.json"
    with pytest.raises(ValueError, match="metadata budget"):
        receipt_io.publish_scan_receipt(oversized, {"value": "x" * 100})
    assert not oversized.exists()
    staging = next(tmp_path.glob(".staging-oversized.json-*"))
    assert staging.stat().st_size > 96
    with pytest.raises(ValueError, match="size limit"):
        receipt_io.read_scan_receipt(staging)


def test_publisher_checks_actual_staged_bytes_not_value_estimate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = {"complete": True}
    budget = len(canonical(value))
    monkeypatch.setattr(receipt_io, "MAX_SCAN_RECEIPT_BYTES", budget)
    at_limit = tmp_path / "at-limit.json"
    receipt_io.publish_scan_receipt(at_limit, value)
    assert receipt_io.read_scan_receipt(at_limit) == value

    def padded_writer(path: Path, payload: dict[str, Any]) -> None:
        path.write_bytes(canonical(payload) + b" ")

    monkeypatch.setattr(receipt_io, "write_json", padded_writer)
    final = tmp_path / "padded.json"
    with pytest.raises(ValueError, match="metadata budget"):
        receipt_io.publish_scan_receipt(final, value)
    assert not final.exists()
    staging = next(tmp_path.glob(".staging-padded.json-*"))
    assert read_json(staging) == value  # Legal JSON exceeds the budget only in actual bytes.
    with pytest.raises(ValueError, match="size limit"):
        receipt_io.read_scan_receipt(staging)
