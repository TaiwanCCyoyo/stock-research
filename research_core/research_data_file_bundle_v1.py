"""Bounded physical publication of shared bundles from already sealed files.

The catalog is the formal research_data entry. Payload blocks have one copy in
research_cache and are read there through the catalog's explicit manifest pin.
This uses the existing bundle envelope and shared artifact-store primitives.
"""

from __future__ import annotations

import logging
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from research_core.artifact_store import copy_verified, describe_file, file_digest, object_digest, publish_noreplace, read_json, relative_name, write_json
from research_core.research_data_catalog import CATALOG_FIELDS, DataCatalog, read_detached, validate_entry, verify_entry
from research_core.research_data_paths import _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)


def _staged_inventory(catalog: DataCatalog, directory: Path) -> list[dict[str, Any]]:
    """Inventory physical payloads, excluding only the root bundle manifest."""
    pending = [directory]
    artifacts = []
    while pending:
        for member in sorted(pending.pop().iterdir()):
            name = member.relative_to(directory).as_posix()
            catalog.roots.artifact_path("data", member.relative_to(catalog.roots.data).as_posix())
            if name == "manifest.json":
                if not member.is_file():
                    raise ValueError("manifest path reserved for a regular bundle manifest")
                continue
            info = member.lstat()
            if stat.S_ISDIR(info.st_mode):
                pending.append(member)
            elif stat.S_ISREG(info.st_mode):
                artifacts.append(describe_file(directory, member))
            else:
                raise ValueError("bundle payload must contain only regular physical files and directories")
    return sorted(artifacts, key=lambda record: record["path"])


def prepare_staged_bundle(
    catalog: DataCatalog,
    metadata: dict[str, Any],
    staging: Path,
    *,
    managed_parent: str,
    lineage: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Seal and verify a staged bundle without publishing or registering it.

    New staging directories must be named ``.staging-*``. After a registration
    failure, retry with the digest-named final directory as ``staging``; its
    manifest and complete physical inventory are verified again. The returned
    entry can be journaled before publication. No payload is copied or moved.
    """
    parent = catalog.roots.artifact_path("data", managed_parent)
    if not staging.is_absolute():
        raise ValueError("explicit absolute staging directory required")
    staging = _checked_path(staging)
    if staging.parent != parent or not staging.is_dir():
        raise ValueError("populated staging must be a sibling under the explicit managed parent")
    if staging.stat().st_dev != parent.stat().st_dev:
        raise ValueError("staging and final parent must be on the same filesystem")
    artifacts = _staged_inventory(catalog, staging)
    if not artifacts:
        raise ValueError("nonempty staged payload required")
    body = {"schema": "research-data-bundle.v1", "complete": True, "metadata": metadata, "lineage": lineage, "artifacts": artifacts}
    version = object_digest(body)
    if not staging.name.startswith(".staging-") and staging.name != version:
        raise ValueError("staging name must be .staging-* or its verified final digest")
    name = f"{relative_name(managed_parent)}/{version}"
    destination = catalog.roots.artifact_path("data", name)
    entry = {
        **{key: metadata[key] for key in CATALOG_FIELDS},
        "version_id": version,
        "reader": "bundle",
        "manifest": {"scope": "data", "path": f"{name}/manifest.json", "sha256": version},
    }
    validate_entry(entry, catalog.roots)
    manifest = staging / "manifest.json"
    if manifest.exists():
        if read_json(manifest) != body:
            raise ValueError("reserved manifest differs from the staged bundle identity")
    elif staging == destination:
        raise ValueError("existing final bundle lacks its manifest")
    else:
        write_json(manifest, body)
    if file_digest(manifest) != version:
        raise ValueError("staged manifest hash differs from the bundle identity")
    LOGGER.info("Prepared staged bundle data=%s version=%s files=%d", metadata["data_id"], version, len(artifacts))
    return entry, body


def publish_staged_bundle(
    catalog: DataCatalog,
    metadata: dict[str, Any],
    staging: Path,
    *,
    managed_parent: str,
    lineage: dict[str, Any] | None = None,
    before_publish: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Publish a verified sibling by one no-replace rename, then register it.

    An identical existing final is fully verified; separately supplied staging
    remains untouched. Registration failure retains the final for a retry using
    that digest-named directory. No payload is copied or individually moved.
    The optional callback receives a detached planned entry before any rename
    or registration, allowing an atomic handoff journal without a second seal.
    It must only journal metadata, leaving the owned payload unchanged. Catalog
    registration retains its independent full verification trust boundary.
    """
    before = resource_sample()
    entry, body = prepare_staged_bundle(catalog, metadata, staging, managed_parent=managed_parent, lineage=lineage)
    staging = _checked_path(staging)
    destination = catalog.roots.artifact_path("data", entry["manifest"]["path"]).parent
    existing = destination.exists()
    if existing and destination != staging:
        final_entry, final_body = prepare_staged_bundle(catalog, metadata, destination, managed_parent=managed_parent, lineage=lineage)
        if final_entry != entry or final_body != body:
            raise ValueError("existing final bundle identity/inventory mismatch")
    LOGGER.info("Staged publisher verification measurement=%s", phase_receipt("staged_bundle_inventory", before, resource_sample()))
    if before_publish is not None:
        before_publish(read_detached(entry))
    if not existing:
        publish_noreplace(staging, destination)
    before = resource_sample()
    try:
        catalog.register([entry])
    finally:
        LOGGER.info("Catalog registration including independent verification measurement=%s", phase_receipt("catalog_registration", before, resource_sample()))
    LOGGER.info("Published staged bundle data=%s version=%s files=%d", metadata["data_id"], entry["version_id"], len(body["artifacts"]))
    return entry


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
