"""Native desktop launch feedback; service ownership stays with the caller."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from typing import Protocol

LOGGER = logging.getLogger(__name__)
CANCELLED_EXIT_CODE = 130


class LaunchCancelled(Exception):
    """The user requested startup cancellation; owned resources must unwind."""


class LaunchCancellation:
    def __init__(self) -> None:
        self._requested = threading.Event()

    def request(self) -> None:
        self._requested.set()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def check(self) -> None:
        if self.requested:
            raise LaunchCancelled("已取消啟動")


class LaunchFeedback(Protocol):
    cancellation: LaunchCancellation

    def status(self, message: str) -> None: ...

    def ready(self) -> None: ...

    def failed(self, message: str) -> None: ...


def record_failure(log_path: Path, message: str) -> str:
    """Keep startup failures even when logging could not be initialized."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as output:
            output.write(message + "\n" + traceback.format_exc() + "\n")
    except OSError as exc:
        return f"{message}\n記錄檔也無法寫入：{exc}"
    return message


def show_fallback(message: str) -> None:
    """A pythonw process must never hide an unavailable GUI behind stderr."""
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "股票 Dashboard", 0x10)
    elif sys.stderr is not None:
        sys.stderr.write(message + "\n")


class DesktopLaunchFeedback:
    """All Tk access stays on the main thread; workers only enqueue events."""

    def __init__(self, log_path: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._events: Queue[tuple[str, str]] = Queue()
        self.cancellation = LaunchCancellation()
        self._failed = False
        self._finished = False
        self._dismissed_error = False
        self._log_path = log_path
        self._root = tk.Tk()
        try:
            self._root.title("股票 Dashboard")
            self._root.geometry("480x280")
            self._root.minsize(440, 260)
            self._root.protocol("WM_DELETE_WINDOW", self.close)
            frame = ttk.Frame(self._root, padding=24)
            frame.pack(fill="both", expand=True)
            self._heading = ttk.Label(frame, text="正在開啟股票 Dashboard", font=("Microsoft JhengHei UI", 15, "bold"))
            self._heading.pack(anchor="w")
            self._message = tk.StringVar(value="正在準備啟動…")
            ttk.Label(frame, textvariable=self._message, wraplength=420).pack(anchor="w", pady=(12, 12))
            self._progress = ttk.Progressbar(frame, mode="indeterminate")
            self._progress.pack(fill="x")
            self._progress.start(12)
            self._hint = ttk.Label(frame, text="完成後會自動開啟瀏覽器；關閉此視窗會取消啟動。")
            self._hint.pack(anchor="w", pady=(10, 0))
            self._log_button = ttk.Button(frame, text="開啟記錄檔", command=self.open_log)
            self._cancel_button = ttk.Button(frame, text="取消", command=self.close)
            self._cancel_button.pack(anchor="e", pady=(12, 0))
            # Paint before logging, configuration validation or service startup.
            self._root.update()
        except Exception:
            self._root.destroy()
            raise

    def status(self, message: str) -> None:
        self._events.put(("status", message))

    def ready(self) -> None:
        self._events.put(("ready", ""))

    def failed(self, message: str) -> None:
        self._events.put(("failed", message))

    def close(self) -> None:
        if self._finished:
            self._root.destroy()
        else:
            self._dismissed_error = self._failed
            self.cancellation.request()
            self._heading.configure(text="正在取消啟動")
            self._message.set("正在停止本次啟動的服務，完成後會關閉視窗…")
            self._hint.configure(text="既有服務不受影響。")
            self._cancel_button.configure(state="disabled")

    def open_log(self) -> None:
        try:
            os.startfile(self._log_path)
        except OSError as exc:
            LOGGER.exception("Unable to open desktop launcher log")
            self._message.set(f"無法開啟記錄檔：{exc}\n{self._log_path}")

    def _drain(self) -> None:
        while True:
            try:
                event, message = self._events.get_nowait()
            except Empty:
                break
            if event == "exit_error" and not self._failed:
                event, message = "failed", "啟動未完成，請開啟記錄檔查看原因。"
            if event == "status" and not self.cancellation.requested:
                self._message.set(message)
            elif event == "ready" and not self.cancellation.requested:
                self._root.withdraw()
            elif event == "failed":
                self._failed = True
                self._dismissed_error = False
                self._root.geometry("540x360")
                self._heading.configure(text="股票 Dashboard 無法繼續執行")
                self._message.set(message)
                self._progress.stop()
                self._progress.pack_forget()
                self._hint.configure(text="錯誤已保留在記錄檔，可開啟查看。")
                self._log_button.pack(anchor="w", pady=(12, 0))
                self._cancel_button.configure(text="關閉", state="normal")
                self._root.deiconify()
                self._root.lift()
            elif event == "finished":
                self._finished = True
                if not self._failed or self._dismissed_error:
                    self._root.destroy()
                    return
        self._root.after(80, self._drain)

    def run(self, operation: Callable[[LaunchFeedback], int]) -> int:
        result = [1]

        def worker() -> None:
            try:
                result[0] = operation(self)
                if result[0] not in (0, CANCELLED_EXIT_CODE):
                    # Preserve a specific error already enqueued by the caller.
                    self._events.put(("exit_error", ""))
            except LaunchCancelled:
                LOGGER.info("Desktop startup cancelled; cleanup completed")
                result[0] = CANCELLED_EXIT_CODE
            except Exception as exc:
                message = record_failure(self._log_path, f"啟動失敗：{exc}")
                LOGGER.exception("Desktop launcher worker failed")
                self.failed(message)
            finally:
                self._events.put(("finished", ""))

        thread = threading.Thread(target=worker, name="dashboard-launcher", daemon=False)
        thread.start()
        self._root.after(0, self._drain)
        self._root.mainloop()
        thread.join()
        return result[0]


def run_desktop_launch(operation: Callable[[LaunchFeedback], int], log_path: Path) -> int:
    try:
        feedback = DesktopLaunchFeedback(log_path)
    except Exception as exc:
        message = record_failure(log_path, f"無法顯示啟動視窗：{exc}")
        show_fallback(f"{message}\n請重新開啟股票 Dashboard。\n記錄檔：{log_path}")
        return 1
    return feedback.run(operation)
