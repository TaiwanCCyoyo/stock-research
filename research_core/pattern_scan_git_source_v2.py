"""Git and runtime provenance for normally imported live-input scan workers.

Historical identity validation deliberately does not inspect the current checkout.
Active process entries separately require the recorded checkout identity.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

from research_core.artifact_store import object_digest
from research_core.pattern_scan_execution_v1 import NUMERICAL_THREADS
from research_core.run_receipt import code_identity
from research_core.stock_feature_pool_v1 import runtime_identity

LOGGER = logging.getLogger(__name__)
SCHEMA = "pattern-scan-source.git.v2"


def git_source_identity(repo_root: Path) -> dict[str, Any]:
    """Record code provenance without reading producer data or sealing source bytes."""
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "code": code_identity(repo_root),
        "runtime": runtime_identity(),
        "platform": sys.platform,
        "numerical_thread_limits": dict(NUMERICAL_THREADS),
    }
    identity = {**body, "source_id": object_digest(body)}
    verify_git_source(identity)
    LOGGER.info("Recorded Git scan source commit=%s dirty=%s", body["code"]["commit"], body["code"]["dirty"])
    return identity


def verify_git_source(identity: dict[str, Any]) -> None:
    """Validate receipt structure and runtime, independent of current Git HEAD."""
    required = {"schema", "code", "runtime", "platform", "numerical_thread_limits", "source_id"}
    body = {key: value for key, value in identity.items() if key != "source_id"}
    if set(identity) != required or identity.get("schema") != SCHEMA or object_digest(body) != identity.get("source_id"):
        raise ValueError("invalid Git source identity")
    code = identity["code"]
    if (
        not isinstance(code, dict)
        or set(code) != {"commit", "dirty"}
        or not isinstance(code["commit"], str)
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", code["commit"]) is None
        or type(code["dirty"]) is not bool
    ):
        raise ValueError("invalid Git code identity")
    if identity["runtime"] != runtime_identity() or identity["platform"] != sys.platform:
        raise ValueError("Git source runtime differs")
    if identity["numerical_thread_limits"] != NUMERICAL_THREADS:
        raise ValueError("Git numerical thread limits differ")


def assert_current_code(identity: dict[str, Any], repo_root: Path) -> None:
    """Require the exact recorded commit and dirty flag once at an active entry."""
    verify_git_source(identity)
    if code_identity(repo_root) != identity["code"]:
        raise ValueError("active Git source checkout differs from recorded code identity")
    LOGGER.info("Verified active Git scan source commit=%s dirty=%s", identity["code"]["commit"], identity["code"]["dirty"])
