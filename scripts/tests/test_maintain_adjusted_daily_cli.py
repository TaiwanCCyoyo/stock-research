from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from research_core.live_producer import ProducerBusyError
from scripts import maintain_adjusted_daily as cli

TAIPEI = timezone(timedelta(hours=8))
NOON = datetime(2026, 10, 29, 12, 0, tzinfo=TAIPEI)


def test_wait_deadline_options() -> None:
    assert cli._wait_deadline(None, False, NOON) == datetime(2026, 10, 29, 23, 30, tzinfo=TAIPEI)
    assert cli._wait_deadline("22:15", False, NOON) == datetime(2026, 10, 29, 22, 15, tzinfo=TAIPEI)
    assert cli._wait_deadline("22:15", True, NOON) is None


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str], waits: list[Any], updates: list[Any]) -> int:
    monkeypatch.setattr(sys, "argv", ["maintain_adjusted_daily", *argv])
    monkeypatch.setattr(cli, "wait_for_producer_idle", lambda deadline: waits.append(deadline))
    monkeypatch.setattr(cli, "producer_data_root", lambda: "root")

    def update(**kwargs: Any) -> dict[str, str]:
        updates.append(kwargs)
        return {"generation": "g"}

    monkeypatch.setattr(cli.family, "update", update)
    monkeypatch.setattr(cli, "_startup_commit", lambda: "abc123")
    return cli.main()


def test_update_logs_startup_waits_then_updates(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    waits: list[Any] = []
    updates: list[Any] = []
    with caplog.at_level(logging.INFO):
        assert _run(monkeypatch, ["update", "--wait-until", "22:00"], waits, updates) == 0
    assert any(r.getMessage().startswith("starting update pid=") and "code_commit=abc123" in r.getMessage() for r in caplog.records)
    assert waits[0].strftime("%H:%M") == "22:00"
    assert updates == [{"producer_root": "root", "skip_unchanged": True}]


def test_update_force_and_no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[Any] = []
    updates: list[Any] = []
    _run(monkeypatch, ["update", "--no-wait", "--force"], waits, updates)
    assert waits == [None] and updates[0]["skip_unchanged"] is False


def test_update_exits_nonzero_without_updating_when_producer_stays_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    updates: list[Any] = []
    monkeypatch.setattr(sys, "argv", ["maintain_adjusted_daily", "update"])
    monkeypatch.setattr(cli, "_startup_commit", lambda: "abc123")

    def busy(deadline: Any) -> None:
        raise ProducerBusyError("busy")

    monkeypatch.setattr(cli, "wait_for_producer_idle", busy)
    monkeypatch.setattr(cli.family, "update", lambda **kwargs: updates.append(kwargs))
    assert cli.main() == 1
    assert updates == []
