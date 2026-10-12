"""Small phase receipts; native counters describe this process only."""

from __future__ import annotations

import os
import platform
import sys
import time
from typing import Any


def resource_sample() -> dict[str, Any]:
    result: dict[str, Any] = {"wall": time.perf_counter(), "cpu": time.process_time(), "native": None}
    if sys.platform == "win32":
        import win32api
        import win32process

        handle = win32api.GetCurrentProcess()
        memory = win32process.GetProcessMemoryInfo(handle)
        result["native"] = {
            "working_set_bytes": memory["WorkingSetSize"],
            "peak_working_set_lifetime_bytes": memory["PeakWorkingSetSize"],
            "io": win32process.GetProcessIoCounters(handle),
        }
    return result


def phase_receipt(name: str, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"phase": name, "wall_seconds": after["wall"] - before["wall"], "cpu_seconds": after["cpu"] - before["cpu"], "native": None}
    if before["native"] is not None and after["native"] is not None:
        result["native"] = {
            "working_set_after_bytes": after["native"]["working_set_bytes"],
            "peak_working_set_process_lifetime_bytes": after["native"]["peak_working_set_lifetime_bytes"],
            "io_delta": {name: value - before["native"]["io"][name] for name, value in after["native"]["io"].items()},
            "io_scope": "Windows process transfer counters, including cached I/O; not physical disk throughput",
            "memory_scope": "Process lifetime peak observed at phase end; not an isolated phase peak",
        }
    return result


def host_resources() -> dict[str, Any]:
    result: dict[str, Any] = {
        "logical_processors": os.cpu_count(),
        "python": platform.python_version(),
        "platform": sys.platform,
        "physical_total_bytes": None,
        "physical_available_bytes": None,
    }
    if sys.platform == "win32":
        import win32api

        memory = win32api.GlobalMemoryStatus()
        result.update(physical_total_bytes=memory["TotalPhys"], physical_available_bytes=memory["AvailPhys"])
    return result
