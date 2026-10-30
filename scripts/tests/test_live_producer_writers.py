from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_core import live_producer
from research_core.live_producer import ProducerBusyError, assert_producer_idle, live_lock_writers, wait_for_producer_idle

TAIPEI = timezone(timedelta(hours=8))
NIGHT = datetime(2026, 10, 29, 21, 34, tzinfo=TAIPEI)


@pytest.fixture()
def producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda **kwargs: [])
    monkeypatch.setattr(live_producer, "producer_data_root", lambda: tmp_path)
    return tmp_path


def test_live_lock_blocks_and_names_pid_and_lock(producer: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (producer / ".run_daily.lock").write_text(json.dumps({"pid": os.getpid(), "started_at": "x", "git_commit": "abc"}), encoding="utf-8")
    with pytest.raises(ProducerBusyError, match=rf"pid {os.getpid()} \(lock \.run_daily\.lock\)"):
        assert_producer_idle(NIGHT)


def test_stale_lock_warns_and_does_not_block(producer: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    (producer / ".official_backfill.lock").write_text(json.dumps({"pid": 4_000_000}), encoding="utf-8")
    (producer / ".run_daily.lock").write_text("not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert_producer_idle(NIGHT)
    assert "Stale producer lock" in caplog.text and "Unreadable producer lock" in caplog.text
    assert live_lock_writers(producer) == []


def test_live_process_blocks_when_task_is_ready(producer: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    budgets: list[Any] = []

    def processes(**kwargs: Any) -> list[tuple[int, str]]:
        budgets.append(kwargs)
        return [(1234, "python.exe")]

    monkeypatch.setattr(live_producer, "query_writer_processes", processes)
    with pytest.raises(ProducerBusyError, match="pid 1234"):
        assert_producer_idle(NIGHT, task_timeout=2.5)
    assert budgets == [{"timeout": 2.5}]


def test_unresolvable_root_still_runs_process_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda **kwargs: [])

    def broken() -> Path:
        raise ValueError("no root")

    monkeypatch.setattr(live_producer, "producer_data_root", broken)
    monkeypatch.setattr(live_producer, "query_writer_processes", lambda **kwargs: [(7, "uv.exe")])
    with pytest.raises(ProducerBusyError, match="pid 7"):
        assert_producer_idle(NIGHT)


@pytest.mark.parametrize("outcome", ["ok", "empty", "timeout", "failure"])
def test_process_query_parsing_and_fail_closed(monkeypatch: pytest.MonkeyPatch, outcome: str) -> None:
    monkeypatch.setattr(live_producer, "sys", SimpleNamespace(platform="win32"))
    seen: list[Any] = []

    def run(command: list[str], **kwargs: Any) -> Any:
        seen.append((command, kwargs["timeout"]))
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("synthetic", kwargs["timeout"])
        if outcome == "failure":
            return SimpleNamespace(returncode=1, stderr="boom", stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout="" if outcome == "empty" else "321 python.exe\nnoise\n654 uv.exe\n")

    monkeypatch.setattr(live_producer.subprocess, "run", run)
    # conftest stubs the public wrapper for every test; call the PowerShell layer it delegates to.
    if outcome in {"timeout", "failure"}:
        with pytest.raises(ProducerBusyError):
            live_producer._powershell_writer_processes(1.5)
    else:
        found = live_producer._powershell_writer_processes(1.5)
        assert found == ([] if outcome == "empty" else [(321, "python.exe"), (654, "uv.exe")])
    command, timeout = seen[0]
    assert command[0] == "powershell.exe" and "run_daily" in command[-1] and "backfill_official_history" in command[-1] and timeout == 1.5


# The root conftest stubs query_writer_processes for every test; keep the real one to test it.
_REAL_QUERY_WRITER_PROCESSES = live_producer.query_writer_processes


def test_non_windows_reports_no_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_producer, "query_writer_processes", _REAL_QUERY_WRITER_PROCESSES)
    monkeypatch.setattr(live_producer, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(live_producer, "_powershell_writer_processes", lambda timeout: pytest.fail("must not query"))
    assert live_producer.query_writer_processes() == []


def test_pid_liveness() -> None:
    assert live_producer._pid_is_running(os.getpid())
    assert not live_producer._pid_is_running(4_000_000)
    assert not live_producer._pid_is_running(0) and not live_producer._pid_is_running(True)


def test_wait_polls_until_idle_and_logs_each_wait(caplog: pytest.LogCaptureFixture) -> None:
    moment = [datetime(2026, 10, 29, 20, 30, tzinfo=TAIPEI)]
    results = [ProducerBusyError("pid 9 (lock .run_daily.lock)"), ProducerBusyError("busy again"), None]
    sleeps: list[float] = []

    def check() -> None:
        outcome = results.pop(0)
        if outcome is not None:
            raise outcome

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        moment[0] += timedelta(seconds=seconds)

    with caplog.at_level(logging.INFO):
        wait_for_producer_idle(datetime(2026, 10, 29, 23, 30, tzinfo=TAIPEI), check=check, clock=lambda: moment[0], sleep=sleep)
    assert sleeps == [300.0, 300.0]
    waits = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert waits == [
        "producer busy (pid 9 (lock .run_daily.lock)); next check in 300s, deadline 23:30",
        "producer busy (busy again); next check in 300s, deadline 23:30",
    ]


def test_wait_gives_up_at_deadline_with_error(caplog: pytest.LogCaptureFixture) -> None:
    moment = [datetime(2026, 10, 29, 23, 20, tzinfo=TAIPEI)]

    def check() -> None:
        raise ProducerBusyError("still busy")

    def sleep(seconds: float) -> None:
        moment[0] += timedelta(seconds=seconds)

    with caplog.at_level(logging.INFO), pytest.raises(ProducerBusyError, match="still busy"):
        wait_for_producer_idle(datetime(2026, 10, 29, 23, 30, tzinfo=TAIPEI), check=check, clock=lambda: moment[0], sleep=sleep)
    assert moment[0] == datetime(2026, 10, 29, 23, 30, tzinfo=TAIPEI)
    assert caplog.records[-1].levelno == logging.ERROR


def test_no_wait_checks_once(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[int] = []

    def check() -> None:
        calls.append(1)
        raise ProducerBusyError("busy")

    with pytest.raises(ProducerBusyError):
        wait_for_producer_idle(None, check=check, sleep=lambda seconds: pytest.fail("no sleeping without a deadline"))
    assert calls == [1]


def test_windows_query_runs_the_powershell_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_producer, "query_writer_processes", _REAL_QUERY_WRITER_PROCESSES)
    monkeypatch.setattr(live_producer, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(live_producer, "_powershell_writer_processes", lambda timeout: [(5, "python.exe")])
    assert live_producer.query_writer_processes(timeout=2.0) == [(5, "python.exe")]


def test_wait_checks_again_at_the_deadline_when_less_than_a_poll_remains() -> None:
    # Busy at 21:56 with a 22:00 deadline; the producer finishes at 21:57.
    deadline = datetime(2026, 10, 29, 22, 0, tzinfo=TAIPEI)
    moment = [datetime(2026, 10, 29, 21, 56, tzinfo=TAIPEI)]
    sleeps: list[float] = []

    def check() -> None:
        if moment[0] < datetime(2026, 10, 29, 21, 57, tzinfo=TAIPEI):
            raise ProducerBusyError("run_daily finishing")

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        moment[0] += timedelta(seconds=seconds)

    wait_for_producer_idle(deadline, check=check, clock=lambda: moment[0], sleep=sleep)
    assert sleeps == [240.0] and moment[0] == deadline


class _Kernel32:
    """Stand-in for kernel32 where OpenProcess succeeds and GetExitCodeProcess fails."""

    class _Function:
        def __init__(self, result: Any) -> None:
            self.result = result
            self.restype: Any = None

        def __call__(self, *args: Any) -> Any:
            return self.result

    def __init__(self) -> None:
        self.OpenProcess = self._Function(1234)
        self.GetExitCodeProcess = self._Function(0)
        self.CloseHandle = self._Function(1)


@pytest.mark.skipif(sys.platform != "win32", reason="exercises the Windows liveness branch")
def test_a_failed_exit_code_query_counts_as_running(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: _Kernel32())
    assert live_producer._pid_is_running(4321), "a process whose state cannot be read must not be treated as exited"


def test_an_empty_released_lock_is_ignored_silently(producer: Path, caplog: pytest.LogCaptureFixture) -> None:
    (producer / ".run_daily.lock").write_text("", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert live_lock_writers(producer) == []
    assert not caplog.records
