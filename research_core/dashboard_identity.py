"""Lightweight identity of the dashboard configuration selected at startup."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from research_core.producer_data import primary_checkout, read_env_file_value

CONFIG_VERSION = "dashboard-config.v2"
ROOT_KEYS = ("STOCK_PRODUCER_DATA_ROOT", "STOCK_RESEARCH_SHARED_ROOT", "STOCK_RESEARCH_DATA_ROOT")
PRIVATE_PATH_KEYS = ("STOCK_PRIVATE_ARTIFACT_ROOT", "STOCK_SAVED_STUDIO_PACKAGE")


def dashboard_identity(environment: Mapping[str, str], *, repo_root: Path | None = None) -> dict[str, str]:
    """Fingerprint effective configuration, never data bytes or root availability.

    Explicit mappings remain deterministic when repo_root is omitted. Production
    API startup supplies its checkout to resolve missing paths from primary's
    configuration, using the same process-over-file precedence as data readers.
    """
    mode = environment.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    primary = primary_checkout(repo_root) if repo_root is not None else None
    configuration: dict[str, str | None] = {"version": CONFIG_VERSION, "mode": mode}
    for key in (*ROOT_KEYS, *PRIVATE_PATH_KEYS):
        value = environment.get(key)
        if value is None and primary is not None:
            value = read_env_file_value(primary / ".env.local", key)
        # Missing/blank means no usable root; it must differ from every path.
        configuration[key] = os.path.normcase(os.path.abspath(value)) if value else None
    raw = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    identity = {
        "dataMode": mode,
        "configVersion": CONFIG_VERSION,
        "configId": hashlib.sha256(raw).hexdigest(),
        "webUrl": environment.get("RESEARCH_WEB_URL", ""),
    }
    if environment.get("RESEARCH_PREVIEW_CONFIG_ID"):
        identity["previewConfigId"] = environment["RESEARCH_PREVIEW_CONFIG_ID"]
    return identity
