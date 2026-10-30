"""Lightweight identity of the dashboard configuration selected at startup."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping


def dashboard_identity(environment: Mapping[str, str]) -> dict[str, str]:
    """Fingerprint configuration paths without reading private files or evidence."""
    mode = environment.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    configuration = {"mode": mode}
    if mode == "local-private":
        for key in ("STOCK_PRIVATE_ARTIFACT_ROOT", "STOCK_SAVED_STUDIO_PACKAGE"):
            value = environment.get(key, "")
            configuration[key] = os.path.normcase(os.path.abspath(value)) if value else ""
    raw = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    identity = {"dataMode": mode, "configId": hashlib.sha256(raw).hexdigest(), "webUrl": environment.get("RESEARCH_WEB_URL", "")}
    if environment.get("RESEARCH_PREVIEW_CONFIG_ID"):
        identity["previewConfigId"] = environment["RESEARCH_PREVIEW_CONFIG_ID"]
    return identity
