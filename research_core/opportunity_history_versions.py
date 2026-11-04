"""Bounded, catalog-registered immutable history snapshots, never a latest fallback.

Registration and manifest bytes are checked before a pin gets a lazy reader.
The reader verifies its dependencies before publishing an in-memory snapshot;
detail reads continue to verify newly read bytes. This is not a filesystem watcher.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from research_core.artifact_store import relative_name
from research_core.opportunity_history_bundle import BundleUnavailable, resolve_history_bundle
from research_core.opportunity_history_store import HistoryStore, LazyHistoryStore
from research_core.research_data_paths import DataRoots
from research_core.strategy_map_capture import HistoryCapture


@dataclass(frozen=True)
class HistorySelection:
    provider: LazyHistoryStore
    capture: HistoryCapture


def history_pin(version_id: str | None, manifest_sha256: str | None) -> tuple[str, str] | None:
    """Validate the complete HTTP identity without treating it as a trust anchor."""
    if version_id is None and manifest_sha256 is None:
        return None
    if version_id is None or manifest_sha256 is None:
        raise ValueError("Both version_id and manifest_sha256 are required")
    if not version_id.strip() or len(version_id) > 1024 or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in version_id):
        raise ValueError("Invalid history version_id")
    relative_name(version_id)
    if re.fullmatch(r"[0-9a-fA-F]{64}", manifest_sha256) is None:
        raise ValueError("Invalid history manifest_sha256")
    return version_id, manifest_sha256.lower()


class HistoryVersions:
    """At most four explicit versions plus the legacy default per HTTP router.

    Loading and failed readers retain their slots, so arbitrary requests cannot start
    unbounded workers or retry expensive failures. A full registry refuses another
    version rather than evicting an in-flight snapshot. The process owns its lifetime.
    """

    def __init__(self, default: LazyHistoryStore | None = None, *, roots: DataRoots | None = None, capacity: int = 4) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Positive history version capacity required")
        default = default or LazyHistoryStore()
        self.default = HistorySelection(default, HistoryCapture(default))
        self.roots = roots
        self.capacity = capacity
        self._lock = threading.Lock()
        self._versions: dict[tuple[str, str], HistorySelection] = {}

    def select(self, version_id: str | None = None, manifest_sha256: str | None = None) -> HistorySelection:
        pin = history_pin(version_id, manifest_sha256)
        if pin is None:
            return self.default
        with self._lock:
            existing = self._versions.get(pin)
            if existing is not None:
                return existing
            if len(self._versions) >= self.capacity:
                raise BundleUnavailable("History version reader capacity reached; no fallback")
            version, digest = pin
            # DataCatalog, not the caller's digest alone, authorizes this location.
            resolved = resolve_history_bundle(self.roots, version_id=version, manifest_sha256=digest)
            if resolved.manifest_sha256 != digest:
                raise BundleUnavailable("Resolved history manifest differs from requested pin")
            default = self.default.provider
            snapshot = default.store if type(default) is LazyHistoryStore else None
            if (
                type(snapshot) is HistoryStore
                and default.error is None
                and default.bundle is not None
                and Path(os.path.abspath(default.bundle)) == resolved.path
                and snapshot.bundle == resolved.path
                and default.version_id == snapshot.version_id == version
                and default.expected_sha == snapshot.identity == digest
            ):
                # Reuse only a verified concrete reader after catalog authorization.
                # In particular, injected legacy providers and digest aliases do not qualify.
                selected = self.default
            else:
                provider = LazyHistoryStore(resolved.path, digest, version_id=version)
                selected = HistorySelection(provider, HistoryCapture(provider))
            self._versions[pin] = selected
            return selected
