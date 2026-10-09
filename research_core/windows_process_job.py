"""An owned Windows Job Object with a pre-execution assignment gate."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
_GATE = "import sys,subprocess; ok=sys.stdin.buffer.readline(4)==b'run\\n'; sys.exit(subprocess.call(sys.argv[1:],stdin=subprocess.DEVNULL) if ok else 125)"


class WindowsProcessJob:
    """Retain process ownership independently of the leader's PID or lifetime."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows Job Objects require Windows")
        import win32job

        self._api: Any = win32job
        self._handle: Any = win32job.CreateJobObject(None, "")
        try:
            info = win32job.QueryInformationJobObject(self._handle, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self._handle, win32job.JobObjectExtendedLimitInformation, info)
        except BaseException:
            self.close()
            raise

    def start(self, command: list[str], cwd: Path) -> subprocess.Popen[Any]:
        """Do not allow the gate to spawn the command before job assignment."""
        if sys.platform != "win32":
            raise RuntimeError("Windows Job Objects require Windows")
        process = subprocess.Popen(
            [sys.executable, "-c", _GATE, *command],
            cwd=cwd,
            stdin=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )
        try:
            # CPython's Windows Popen retains this original kernel process handle.
            # Unlike OpenProcess(pid), this cannot target a reused unrelated PID.
            handle = getattr(process, "_handle", None)
            if handle is None:
                raise RuntimeError("owned Windows process handle is unavailable")
            self._api.AssignProcessToJobObject(self._handle, int(handle))
            if process.stdin is None:
                raise RuntimeError("owned Windows startup gate is unavailable")
            process.stdin.write(b"run\n")
            process.stdin.close()
            LOGGER.info("Assigned startup-gated Windows process to owned job pid=%d", process.pid)
            return process
        except BaseException:
            # The gate has not been released on assignment failure: no descendants.
            process.kill()
            process.wait(timeout=5)
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            raise

    def terminate_and_confirm(self, timeout: float = 5.0) -> None:
        self._api.TerminateJobObject(self._handle, 1)
        deadline = time.monotonic() + timeout
        while True:
            info = self._api.QueryInformationJobObject(self._handle, self._api.JobObjectBasicAccountingInformation)
            if info["ActiveProcesses"] == 0:
                LOGGER.info("Owned Windows job is empty after teardown")
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("owned Windows job teardown could not be confirmed")
            time.sleep(0.01)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.Close()
            self._handle = None
