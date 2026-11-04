"""Synthetic declaration parsing and CLI protocol; no market-source reads."""

from __future__ import annotations

import copy
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_core import order_card_freshness_json_v1 as adapter
from scripts.check_order_card_freshness import main


def _packet() -> dict[str, Any]:
    return {
        "schema": "order-card-freshness.v1",
        "request": {
            "expected_session": "2026-10-30",
            "universe_id": "synthetic-universe.v1",
            "requirements": [{"dataset_id": "synthetic-daily", "definition": "synthetic-daily.v1", "generation": "generation-a"}],
        },
        "calendar": {
            "calendar_id": "synthetic-calendar.v1",
            "decision_at": "2026-10-30T15:00:00+08:00",
            "availability_note": "Artificial calendar facts, not an official-source certification",
            "facts": [
                {
                    "date": "2026-10-30",
                    "session_state": 1,
                    "known_at": "2026-10-29T00:00:00Z",
                    "close_at": "2026-10-30T13:30:00+08:00",
                    "source_ref": "synthetic:session",
                }
            ],
        },
        "observations": [
            {
                "dataset_id": "synthetic-daily",
                "definition": "synthetic-daily.v1",
                "generation": "generation-a",
                "calendar_id": "synthetic-calendar.v1",
                "universe_id": "synthetic-universe.v1",
                "as_of_session": "2026-10-30",
                "available_at": "2026-10-30T15:00:00+08:00",
                "status": "complete",
                "source_ref": "synthetic:daily",
            }
        ],
    }


def _write_packet(tmp_path: Path, packet: object) -> Path:
    target = tmp_path / "manual packet.json"
    target.write_text(json.dumps(packet), encoding="utf-8")
    return target


def _set_path(packet: dict[str, Any], path: tuple[str | int, ...], value: object) -> None:
    cursor: Any = packet
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value


def test_current_cli_preserves_evidence_and_only_reads_explicit_packet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    packet = _packet()
    target = _write_packet(tmp_path, packet)
    before = target.read_bytes()
    assert main(["--input", str(target)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result["freshness_ready"] is True
    assert result["expected_session"] == "2026-10-30"
    assert result["decision_at"] == "2026-10-30T15:00:00+08:00"
    assert result["calendar_days"][0]["source_ref"] == "synthetic:session"
    assert result["datasets"][0]["requirement"] == packet["request"]["requirements"][0]
    assert result["datasets"][0]["observation"] == packet["observations"][0]
    assert "source_authenticity" in result["validation_scope"]
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_explicit_closure_can_pass_without_closure_quotes() -> None:
    packet = _packet()
    packet["calendar"]["decision_at"] = "2026-11-01T15:00:00+08:00"
    for day in ("2026-10-31", "2026-11-01"):
        packet["calendar"]["facts"].append({
            "date": day,
            "session_state": 0,
            "known_at": "2026-10-29T00:00:00Z",
            "close_at": None,
            "source_ref": "synthetic:closure",
        })
    result: Any = adapter.assess_packet(packet)
    assert result["freshness_ready"] is True
    assert [day["session_state"] for day in result["calendar_days"]] == [1, 0, 0]


@pytest.mark.parametrize("status", ["missing", "unknown", "updating"])
def test_valid_noncomplete_declaration_is_withheld(status: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    packet = _packet()
    packet["observations"][0].update(status=status, as_of_session=None, available_at=None)
    assert main(["--input", str(_write_packet(tmp_path, packet))]) == 2
    result = json.loads(capsys.readouterr().out)
    observation = result["datasets"][0]["observation"]
    assert observation["as_of_session"] is None and observation["available_at"] is None
    assert f"status_{status}" in result["datasets"][0]["reasons"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema",), "future.schema"),
        (("request", "expected_session"), "2026-1-30"),
        (("request", "expected_session"), "2026-02-30"),
        (("request", "expected_session"), "2026-10-30T00:00:00"),
        (("observations", 0, "as_of_session"), "20261030"),
        (("calendar", "facts", 0, "date"), 20261030),
        (("calendar", "decision_at"), "2026-10-30T15:00:00"),
        (("calendar", "decision_at"), "2026-10-30"),
        (("calendar", "decision_at"), "2026-10-30T15:00:00+25:00"),
        (("calendar", "facts", 0, "known_at"), "NaT"),
        (("calendar", "facts", 0, "close_at"), "2026-10-30T13:30:00"),
        (("observations", 0, "available_at"), "2026-10-30T15:00:00"),
        (("request", "requirements", 0, "generation"), None),
        (("request", "universe_id"), None),
        (("calendar", "decision_at"), None),
        (("calendar", "facts", 0, "source_ref"), None),
        (("calendar", "facts", 0, "session_state"), True),
        (("observations", 0, "definition"), None),
        (("observations", 0, "source_ref"), None),
        (("observations", 0, "status"), "fresh"),
        (("observations",), {}),
        (("request", "requirements"), []),
    ],
)
def test_invalid_declaration_is_input_error(path: tuple[str | int, ...], value: object) -> None:
    packet = _packet()
    _set_path(packet, path, value)
    with pytest.raises(ValueError):
        adapter.assess_packet(packet)


@pytest.mark.parametrize("path", [(), ("request",), ("request", "requirements", 0), ("calendar",), ("calendar", "facts", 0), ("observations", 0)])
def test_unknown_keys_are_rejected_at_every_object(path: tuple[str | int, ...]) -> None:
    packet = _packet()
    cursor: Any = packet
    for key in path:
        cursor = cursor[key]
    cursor["typo"] = "must not disappear"
    with pytest.raises(ValueError, match="unknown=.*typo"):
        adapter.assess_packet(packet)


def test_missing_field_is_rejected_instead_of_defaulted() -> None:
    packet = _packet()
    del packet["observations"][0]["available_at"]
    with pytest.raises(ValueError, match="missing=.*available_at"):
        adapter.assess_packet(packet)


@pytest.mark.parametrize("kind", ["duplicate_requirement", "duplicate_observation", "extra_observation"])
def test_invalid_dataset_inventory_is_rejected(kind: str) -> None:
    packet = _packet()
    if kind == "duplicate_requirement":
        packet["request"]["requirements"] *= 2
    else:
        extra = copy.deepcopy(packet["observations"][0])
        if kind == "extra_observation":
            extra["dataset_id"] = "unexpected-source"
        packet["observations"].append(extra)
    with pytest.raises(ValueError, match="duplicate|unexpected"):
        adapter.assess_packet(packet)


@pytest.mark.parametrize("kind", ["missing", "stale", "future_availability", "generation_mismatch", "missing_closure"])
def test_valid_unready_packet_exits_two(kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    packet = _packet()
    if kind == "missing":
        packet["observations"] = []
    elif kind == "stale":
        packet["observations"][0]["as_of_session"] = "2026-10-29"
    elif kind == "future_availability":
        packet["observations"][0]["available_at"] = "2026-10-30T15:00:00.000000001+08:00"
    elif kind == "generation_mismatch":
        packet["observations"][0]["generation"] = "new-mtime-but-wrong-generation"
    else:
        packet["calendar"]["decision_at"] = "2026-10-31T15:00:00+08:00"
    assert main(["--input", str(_write_packet(tmp_path, packet))]) == 2
    assert json.loads(capsys.readouterr().out)["freshness_ready"] is False


def test_unknown_calendar_fields_remain_null_and_withhold() -> None:
    packet = _packet()
    packet["calendar"]["facts"][0].update(session_state=-1, known_at=None, close_at=None, source_ref=None)
    result: Any = adapter.assess_packet(packet)
    assert result["freshness_ready"] is False
    day = result["calendar_days"][0]
    assert day["declared_state"] == -1
    assert day["source_ref"] is None and day["close_at"] is None and day["known_at"] is None


def test_timezone_equivalence_input_immutability_and_deterministic_json() -> None:
    packet = _packet()
    packet["calendar"]["decision_at"] = "2026-10-30T07:00:00Z"
    packet["observations"][0]["available_at"] = "2026-10-30T07:00:00Z"
    requirement = {"dataset_id": "a-source", "definition": "a.v1", "generation": "a-generation"}
    packet["request"]["requirements"].append(requirement)
    packet["observations"].append({**packet["observations"][0], **requirement})
    before = copy.deepcopy(packet)
    first: Any = adapter.assess_packet(packet)
    assert packet == before
    packet["observations"].reverse()
    assert adapter.assess_packet(packet) == first
    assert first["freshness_ready"] is True
    assert [row["requirement"]["dataset_id"] for row in first["datasets"]] == ["a-source", "synthetic-daily"]
    assert json.loads(json.dumps(first, allow_nan=False)) == first


@pytest.mark.parametrize("raw", ["{broken", "[]", "null", '{"schema": NaN}'])
def test_malformed_json_has_no_stdout_and_logs_diagnostic(
    raw: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "bad.json"
    target.write_text(raw, encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert main(["--input", str(target)]) == 1
    assert capsys.readouterr().out == ""
    assert "Invalid freshness input" in caplog.text


def test_bounded_read_and_missing_file_are_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "oversize.json"
    target.write_text(" " * (adapter.MAX_PACKET_BYTES + 1), encoding="utf-8")
    assert main(["--input", str(target)]) == 1
    assert main(["--input", str(tmp_path / "absent.json")]) == 1
    assert capsys.readouterr().out == ""


def test_duplicate_json_keys_cannot_overwrite_withheld_status(tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
    raw = json.dumps(_packet()).replace('"status": "complete"', '"status": "missing", "status": "complete"')
    target = tmp_path / "duplicate.json"
    target.write_text(raw, encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert main(["--input", str(target)]) == 1
    assert capsys.readouterr().out == ""
    assert "duplicate JSON key: status" in caplog.text


def test_module_command_stdout_and_argument_error_protocol(tmp_path: Path) -> None:
    target = _write_packet(tmp_path, _packet())
    command = [sys.executable, "-m", "scripts.check_order_card_freshness"]
    root = Path(__file__).resolve().parents[2]
    valid = subprocess.run([*command, "--input", str(target)], cwd=root, capture_output=True, text=True, check=False)
    assert valid.returncode == 0 and valid.stderr == ""
    assert json.loads(valid.stdout)["freshness_ready"] is True
    invalid = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    assert invalid.returncode == 1 and invalid.stdout == ""
    assert "--input" in invalid.stderr
