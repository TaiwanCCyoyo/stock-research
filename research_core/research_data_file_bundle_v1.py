"""Bounded physical publication of shared bundles from already sealed files.

The catalog is the formal research_data entry. Payload blocks have one copy in
research_cache and are read there through the catalog's explicit manifest pin.
This uses the existing bundle envelope and shared artifact-store primitives.
"""

from __future__ import annotations

import logging
import stat
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import copy_verified, file_digest, object_digest, publish_noreplace, relative_name, write_json
from research_core.research_data_catalog import CATALOG_FIELDS, DataCatalog, validate_entry, verify_entry
from research_core.research_data_paths import _checked_path

LOGGER = logging.getLogger(__name__)


def publish_file_bundle(
    catalog: DataCatalog,
    metadata: dict[str, Any],
    files: dict[str, Path],
    *,
    lineage: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Publish one immutable verified version without loading all bytes in RAM.

    An exact existing identity is reused only after full verification. Concurrent
    or corrupt finals are never replaced. Inputs are caller-owned sealed files;
    no acquisition, calculation, link creation or cleanup happens here.
    """
    if not files:
        raise ValueError("nonempty sealed payload files required")
    artifacts: list[dict[str, Any]] = []
    for name, source in sorted(files.items()):
        relative_name(name)
        if name == "manifest.json" or name.startswith("manifest.json/"):
            raise ValueError("manifest path reserved")
        source = _checked_path(source)
        if not source.is_file():
            raise ValueError("sealed payload source must be a regular physical file")
        artifacts.append({"path": name, "bytes": source.stat().st_size, "sha256": file_digest(source)})
    body = {"schema": "research-data-bundle.v1", "complete": True, "metadata": metadata, "lineage": lineage, "artifacts": artifacts}
    version = object_digest(body)
    name = f"research_cache/shared-bundles-v1/{metadata['kind']}/{relative_name(metadata['data_id'])}/{version}"
    if task_id is not None:
        if not isinstance(task_id, str) or relative_name(task_id) != task_id or "/" in task_id:
            raise ValueError("one explicit task identifier required")
        name = f"tasks/{task_id}/datasets/{relative_name(metadata['data_id'])}/{version}"
    destination = catalog.roots.artifact_path("primary", name)
    entry = {
        **{key: metadata[key] for key in CATALOG_FIELDS},
        "version_id": version,
        "reader": "bundle",
        "manifest": {"scope": "primary", "path": f"{name}/manifest.json", "sha256": version},
    }
    validate_entry(entry, catalog.roots)
    for artifact in artifacts:
        catalog.roots.artifact_path("primary", f"{name}/{artifact['path']}")
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging_name = f"{name.rsplit('/', 1)[0]}/.staging-{version}-{uuid.uuid4().hex}"
        staging = catalog.roots.artifact_path("primary", staging_name)
        staging.mkdir()
        for artifact in artifacts:
            target = catalog.roots.artifact_path("primary", f"{staging_name}/{artifact['path']}")
            copy_verified(_checked_path(files[artifact["path"]]), target, artifact["sha256"])
        write_json(staging / "manifest.json", body)
        # Full inventory/byte verification before the atomic final publication.
        from research_core.artifact_store import verify_files

        verify_files(staging, artifacts)
        publish_noreplace(staging, destination)
    verify_entry(entry, catalog.roots)
    for artifact in [*artifacts, {"path": "manifest.json"}]:
        path = catalog.roots.artifact_path("primary", f"{name}/{artifact['path']}")
        path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    catalog.register([entry])
    LOGGER.info(
        "Published bounded shared bundle data=%s version=%s files=%d bytes=%d",
        metadata["data_id"],
        version,
        len(artifacts),
        sum(row["bytes"] for row in artifacts),
    )
    return entry
