"""Explicit shared publication and adapters over existing research engines."""

from __future__ import annotations

import logging
import stat
from pathlib import Path
from typing import Any

from research_core.artifact_store import canonical, object_digest, publish_new_directory, relative_name, safe_path
from research_core.research_data_catalog import CATALOG_FIELDS, DataCatalog, validate_entry, verify_entry

LOGGER = logging.getLogger(__name__)


def publish_bundle(catalog: DataCatalog, metadata: dict[str, Any], payloads: dict[str, bytes], *, lineage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish already authorized, validated data under an immutable new ID.

    This API does no market calculation. Existing specialized readers/builders
    remain authoritative for prices, features and stored legacy artifacts.
    """
    import hashlib

    if not payloads or any(not isinstance(value, bytes) for value in payloads.values()):
        raise ValueError("nonempty byte payloads required")
    for name in payloads:
        relative_name(name)
        if name == "manifest.json" or name.startswith("manifest.json/"):
            raise ValueError("manifest path reserved")
    artifacts = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(payloads.items())]
    body = {"schema": "research-data-bundle.v1", "complete": True, "metadata": metadata, "lineage": lineage, "artifacts": artifacts}
    version = object_digest(body)
    path = catalog.roots.artifact_path("data", f"{metadata['kind']}/{relative_name(metadata['data_id'])}/{version}")
    entry = {
        **{key: metadata[key] for key in CATALOG_FIELDS},
        "version_id": version,
        "reader": "bundle",
        "manifest": {"scope": "data", "path": f"{metadata['kind']}/{metadata['data_id']}/{version}/manifest.json", "sha256": object_digest(body)},
    }
    validate_entry(entry, catalog.roots)
    for name in payloads:
        catalog.roots.artifact_path("data", f"{metadata['kind']}/{metadata['data_id']}/{version}/{name}")
    # object_digest hashes canonical bytes, exactly the manifest being written.
    if not path.exists():
        publish_new_directory(path, {**payloads, "manifest.json": canonical(body)})
    verify_entry(entry, catalog.roots)
    # Read-only is supplementary. Root/path/link checks establish isolation.
    for name in [*payloads, "manifest.json"]:
        file = catalog.roots.artifact_path("data", f"{metadata['kind']}/{metadata['data_id']}/{version}/{name}")
        file.chmod(file.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    catalog.register([entry])
    LOGGER.info("Published shared data=%s version=%s", metadata["data_id"], version)
    return entry


def build_feature_blocks(catalog: DataCatalog, requests: list[dict[str, Any]], staging: Path, *, calculation_authorized: bool = False) -> dict[str, Any]:
    """Use the current bounded v2 engine; reuse starts zero workers.

    Explicit authorization is required even when the planner predicts reuse.
    A caller separately registers the returned pinned block metadata, including
    its observed coverage. This adapter never upgrades partial data to complete.
    """
    from research_core.feature_block_store_v1 import FeatureBlockStore
    from research_core.stock_feature_pool_v2 import run_stock_requests

    if not calculation_authorized:
        raise PermissionError("explicit calculation authorization required")
    staging = safe_path(staging)
    if ".tmp" not in staging.parts or staging.is_relative_to(catalog.roots.data) or staging.is_relative_to(catalog.roots.primary / "research_cache"):
        raise ValueError("builder staging must be disposable .tmp outside shared versions")
    root = catalog.roots.artifact_path("primary", "research_cache/feature-blocks-v1")
    return run_stock_requests(requests, FeatureBlockStore(root), staging)
