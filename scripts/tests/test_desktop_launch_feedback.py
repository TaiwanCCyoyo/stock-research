from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from research_core import desktop_launch_feedback as desktop
from scripts import ci_scope


@pytest.fixture
def feedback(tmp_path: Path) -> Iterator[desktop.DesktopLaunchFeedback]:
    tk = MagicMock()
    tk.ttk.Button.side_effect = lambda *args, **kwargs: MagicMock()
    with patch.dict(sys.modules, {"tkinter": tk, "tkinter.ttk": tk.ttk}):
        yield desktop.DesktopLaunchFeedback(tmp_path / "desktop.log")


def test_progress_ready_and_failure_restore_window(feedback: desktop.DesktopLaunchFeedback) -> None:
    feedback.status("正在確認資料設定")
    feedback._drain()
    cast(MagicMock, feedback._message).set.assert_called_with("正在確認資料設定")
    feedback.ready()
    feedback._drain()
    cast(MagicMock, feedback._root).withdraw.assert_called_once()
    cast(MagicMock, feedback._root).destroy.assert_not_called()
    feedback.failed("服務意外結束")
    feedback._events.put(("finished", ""))
    feedback._drain()
    cast(MagicMock, feedback._message).set.assert_called_with("服務意外結束")
    cast(MagicMock, feedback._root).deiconify.assert_called_once()
    cast(MagicMock, feedback._root).destroy.assert_not_called()
    cast(MagicMock, feedback._log_button).pack.assert_called_once()
    cast(MagicMock, feedback._cancel_button).configure.assert_called_with(text="關閉", state="normal")
    feedback.close()
    cast(MagicMock, feedback._root).destroy.assert_called_once()


def test_ready_keeps_nondaemon_monitor_alive(feedback: desktop.DesktopLaunchFeedback) -> None:
    ready = threading.Event()
    continue_monitor = threading.Event()
    monitor_done = threading.Event()
    worker_details: list[bool] = []

    def operation(events: desktop.LaunchFeedback) -> int:
        worker_details.append(threading.current_thread().daemon)
        events.ready()
        ready.set()
        assert continue_monitor.wait(5)
        monitor_done.set()
        return 0

    def mainloop() -> None:
        assert ready.wait(5)
        feedback._drain()
        assert not monitor_done.is_set()
        cast(MagicMock, feedback._root).destroy.assert_not_called()
        continue_monitor.set()
        assert monitor_done.wait(5)

    cast(MagicMock, feedback._root).mainloop.side_effect = mainloop
    assert feedback.run(operation) == 0
    assert worker_details == [False]
    feedback._drain()
    cast(MagicMock, feedback._root).destroy.assert_called_once()


def test_dismissing_error_during_cleanup_does_not_leave_hidden_process(feedback: desktop.DesktopLaunchFeedback) -> None:
    feedback.failed("啟動失敗")
    feedback._drain()
    feedback.close()
    feedback._events.put(("finished", ""))
    feedback._drain()
    cast(MagicMock, feedback._root).destroy.assert_called_once()


def test_close_cancels_and_waits_visibly_for_owned_cleanup(feedback: desktop.DesktopLaunchFeedback) -> None:
    started = threading.Event()
    cleanup_started = threading.Event()
    finish_cleanup = threading.Event()

    def operation(events: desktop.LaunchFeedback) -> int:
        started.set()
        try:
            assert events.cancellation._requested.wait(5)
            events.cancellation.check()
        finally:
            cleanup_started.set()
            assert finish_cleanup.wait(5)
        return 0

    def mainloop() -> None:
        try:
            assert started.wait(5)
            feedback.close()
            assert cleanup_started.wait(5)
            feedback.status("outdated progress")
            feedback._drain()
            cast(MagicMock, feedback._root).destroy.assert_not_called()
            cast(MagicMock, feedback._root).withdraw.assert_not_called()
            cast(MagicMock, feedback._message).set.assert_called_with("正在停止本次啟動的服務，完成後會關閉視窗…")
        finally:
            finish_cleanup.set()

    cast(MagicMock, feedback._root).mainloop.side_effect = mainloop
    assert feedback.run(operation) == desktop.CANCELLED_EXIT_CODE
    feedback._drain()
    cast(MagicMock, feedback._root).destroy.assert_called_once()
    cast(MagicMock, feedback._root).deiconify.assert_not_called()


def test_ui_initialization_failure_logs_and_uses_visible_fallback(tmp_path: Path) -> None:
    log_path = tmp_path / "desktop.log"
    operation = MagicMock()
    with patch.object(desktop, "DesktopLaunchFeedback", side_effect=RuntimeError("missing Tcl")), patch.object(desktop, "show_fallback") as fallback:
        assert desktop.run_desktop_launch(operation, log_path) == 1
    operation.assert_not_called()
    assert "missing Tcl" in log_path.read_text(encoding="utf-8")
    assert "missing Tcl" in fallback.call_args.args[0]
    assert str(log_path) in fallback.call_args.args[0]


def test_fallback_is_native_under_pythonw() -> None:
    with patch.object(desktop.sys, "platform", "win32"), patch.object(desktop.sys, "stderr", None), patch.object(desktop.ctypes, "windll", create=True) as dll:
        desktop.show_fallback("啟動失敗")
    dll.user32.MessageBoxW.assert_called_once_with(None, "啟動失敗", "股票 Dashboard", 0x10)


def test_open_log_uses_exact_persistent_log(feedback: desktop.DesktopLaunchFeedback) -> None:
    with patch.object(desktop.os, "startfile", create=True) as open_file:
        feedback.open_log()
    open_file.assert_called_once_with(feedback._log_path)


def test_unexpected_worker_error_is_logged_and_keeps_error_visible(feedback: desktop.DesktopLaunchFeedback) -> None:
    def operation(events: desktop.LaunchFeedback) -> int:
        raise ValueError("unexpected failure")

    assert feedback.run(operation) == 1
    feedback._drain()
    assert "unexpected failure" in feedback._log_path.read_text(encoding="utf-8")
    cast(MagicMock, feedback._root).deiconify.assert_called_once()
    cast(MagicMock, feedback._root).destroy.assert_not_called()


def test_ci_routes_feedback_and_launcher_together() -> None:
    plan = ci_scope.make_plan([("M", "research_core/desktop_launch_feedback.py")])
    assert not plan["full"]
    assert "opportunity" in plan["domains"]
    assert "scripts/tests/test_desktop_launch_feedback.py" in plan["python_tests"]
    assert "scripts/tests/test_start_research_web.py" in plan["python_tests"]
