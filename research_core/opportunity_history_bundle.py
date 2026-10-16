"""Shared-root home of the frozen opportunity-history web bundle.

The bundle (`catalog-v2/` plus `runs/native/`) is registered in the shared
`research_data` catalog as `patterns/opportunity-history-web/<version>/`. Its
payload reader, `HistoryStore`, stays the authority on validity: it checks every
member's SHA-256 against the manifest on each process start. The catalog entry
only pins which manifest bytes this installation accepts.

The pinned manifest is the predecessor's original bytes. The bootstrap migration
later rewrote path text in the tracked evidence copy (SHA-256 `238e7e4a...`), but the
native receipts of the surviving data still carry the predecessor's
`producer_identity`, so only the original manifest is consistent with these bytes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_core.artifact_store import canonical, publish_noreplace, relative_name, safe_path
from research_core.producer_data import ENV_FILE_NAME, REPO_ROOT, primary_checkout, read_env_file_value
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots, _reject_alias, checked_path

LOGGER = logging.getLogger(__name__)

DATA_ID = "opportunity-history-web"
KIND = "patterns"
SUBTREES = ("catalog-v2", "runs/native")
MANIFEST = "catalog-v2/manifest.json"
RECEIPT = "copy-receipt.json"
# SHA-256 of `catalog-v2/manifest.json` exactly as the predecessor produced it. Tracked
# evidence cites the path-rewritten `238e7e4a...` form (`REGISTERED_MANIFEST_SHA256` in
# scripts/query_opportunity_history.py); that constant is unchanged and still readable.
ORIGINAL_MANIFEST_SHA256 = "c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140"  # pragma: allowlist secret (a public content digest)
# For this entry the version id is the manifest digest, so one value pins both.
BUNDLE_VERSION = ORIGINAL_MANIFEST_SHA256
BLOCK = 1024 * 1024


class BundleUnavailable(RuntimeError):
    """The pinned bundle cannot be located or verified through the shared catalog."""


@dataclass(frozen=True)
class ResolvedBundle:
    path: Path
    manifest_sha256: str


def history_data_roots(*, environ: dict[str, str] | None = None, repo_root: Path | None = None) -> DataRoots:
    """Process environment first, then the primary checkout's `.env.local`; never guessed."""
    environment = os.environ if environ is None else environ
    repo = REPO_ROOT if repo_root is None else repo_root
    configured = environment.get(DATA_ROOT_ENV)
    source = "the process environment"
    if configured is None:
        primary = primary_checkout(repo.resolve())
        env_file = primary / ENV_FILE_NAME if primary is not None else None
        configured = read_env_file_value(env_file, DATA_ROOT_ENV) if env_file is not None else None
        source = str(env_file)
        if configured is None:
            raise BundleUnavailable(f"{DATA_ROOT_ENV} is not configured in the process environment or {source}; no automatic fallback")
    try:
        return DataRoots.from_env({DATA_ROOT_ENV: configured.strip()})
    except ValueError as error:
        raise BundleUnavailable(f"{DATA_ROOT_ENV} from {source} is unusable: {error}") from error


def resolve_history_bundle(
    roots: DataRoots | None = None, *, version_id: str = BUNDLE_VERSION, manifest_sha256: str = ORIGINAL_MANIFEST_SHA256
) -> ResolvedBundle:
    """Locate the pinned bundle through the catalog; no latest lookup and no fallback."""
    try:
        roots = history_data_roots() if roots is None else roots
        entry = DataCatalog(roots).get(DATA_ID, version_id, manifest_sha256=manifest_sha256)
    except BundleUnavailable:
        raise
    except (KeyError, ValueError, OSError) as error:
        LOGGER.warning("Opportunity history bundle unavailable: %s: %s", type(error).__name__, error)
        raise BundleUnavailable(f"pinned catalog entry {DATA_ID}/{version_id} is unavailable: {error}") from error
    path = roots.artifact_path(entry["manifest"]["scope"], entry["manifest"]["path"])
    if path.relative_to(roots.data).as_posix() != f"{KIND}/{DATA_ID}/{version_id}/{MANIFEST}":
        raise BundleUnavailable("catalog entry does not point at the bundle manifest")
    bundle = path.parent.parent
    LOGGER.info("Resolved opportunity history bundle %s", bundle)
    return ResolvedBundle(bundle, manifest_sha256)


def catalog_entry(manifest: dict[str, Any], version_id: str = BUNDLE_VERSION) -> dict[str, Any]:
    """Discovery metadata for the bundle; coverage is what the manifest itself declares."""
    window = manifest["window"]
    return {
        "data_id": DATA_ID,
        "kind": KIND,
        "version_id": version_id,
        "definition_version": f"{manifest['schema_version']}/{manifest['catalog_revision']}",
        "reader": "metadata_only",
        "parameters": {
            "adapter_revision": manifest["adapter_revision"],
            "gain_policy": manifest["gain_policy"],
            "price_basis": manifest["price_basis"],
            "rule": manifest["rule"],
            "selector": manifest["selector"],
            "task": manifest["task"],
        },
        "inputs": {
            "calendar_id": manifest["calendar_id"],
            "calendar_sha256": manifest["calendar"]["sha256"],
            "source_manifest_sha256": manifest["source_manifest"]["sha256"],
            "series_manifest_sha256": manifest["series_manifest"]["sha256"],
            "input_receipt_sha256": manifest["producer_identity"]["input_receipt_sha256"],
        },
        "coverage": {
            "scope": (
                f"{manifest['analyzed_security_count']} eligible saved stocks of {manifest['security_count']} catalogued securities; "
                "not every issuer ever listed"
            ),
            "raw_input_period": {"start": window["start"], "end": window["end"], "reason": None},
            "valid_indicator_period": {"start": None, "end": None, "reason": "retrospective wave catalog, not an indicator dataset"},
            "complete_label_period": {
                "start": None,
                "end": None,
                "reason": "waves are labelled retrospectively; open waves are known only through observedThrough, no completeness is certified",
            },
        },
        "status": "legacy",
        "limitations": [
            "universe covers saved stocks only; delistings and historical membership remain incomplete",
            "2010-2012 corporate actions and missing prices need review; adjusted gains there are not certified",
            "classification is the current taxonomy, not point-in-time",
            "no reliable historical market cap; area uses the wave's own gain only",
            "rule status is preliminary (初步辨識，規則未定); retrospective labels are not real-time signals",
            "manifest bytes are the predecessor's originals; the tracked 238e7e4a form differs in provenance fields only",
        ],
        "backup": {"scope": "existing stock-research backup includes research_data; no new backup run", "status": "unknown"},
        "manifest": {"scope": "data", "path": f"{KIND}/{DATA_ID}/{version_id}/{MANIFEST}", "sha256": version_id},
    }


def _inventory(source: Path, progress: Callable[[str], None]) -> list[dict[str, Any]]:
    """Hash every member before any write; reject links, reparse points and hardlinks."""
    checked_path(source)
    files: list[dict[str, Any]] = []
    for subtree in SUBTREES:
        root = checked_path(source / subtree)
        if not root.is_dir():
            raise ValueError(f"missing producer subtree: {subtree}")
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                children = sorted(entry.name for entry in entries)
            for name in children:
                child = directory / name
                info = child.lstat()
                _reject_alias(child, info)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(child)
                elif stat.S_ISREG(info.st_mode):
                    relative = relative_name(child.relative_to(source).as_posix())
                    with child.open("rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    files.append({"path": relative, "bytes": info.st_size, "sha256": digest})
                else:
                    raise ValueError(f"unsupported entry type: {child}")
        progress(f"hashed {subtree}")
    files.sort(key=lambda item: item["path"])
    if not files:
        raise ValueError("empty producer bundle")
    return files


def _copy_member(source: Path, destination: Path, expected: dict[str, Any]) -> None:
    """Exclusive create; the bytes written must hash to the pre-copy digest."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        for block in iter(lambda: incoming.read(BLOCK), b""):
            digest.update(block)
            written += len(block)
            outgoing.write(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if digest.hexdigest() != expected["sha256"] or written != expected["bytes"]:
        raise ValueError(f"source changed during copy: {expected['path']}")


def _require_separate(source: Path, data_root: Path) -> None:
    """Refuse a source that contains, equals or sits inside the shared root, by physical identity."""
    source, data_root = source.resolve(), data_root.resolve()
    if source == data_root or source.is_relative_to(data_root) or data_root.is_relative_to(source):
        raise ValueError("source and the shared research_data root must be separate directories; nothing was written")
    for ancestor in (source, *source.parents):
        if data_root.exists() and ancestor.exists() and ancestor.samefile(data_root):
            raise ValueError("source and the shared research_data root must be separate directories; nothing was written")
    for ancestor in (data_root, *data_root.parents):
        if ancestor.exists() and source.exists() and ancestor.samefile(source):
            raise ValueError("source and the shared research_data root must be separate directories; nothing was written")


def _resume_registration(
    destination: Path,
    files: list[dict[str, Any]],
    entry: dict[str, Any],
    roots: DataRoots,
    gate: Callable[[Path, str], Any],
    report: Callable[[str], None],
) -> dict[str, Any]:
    """A previous run published the directory but did not register it.

    Existence proves nothing, so the whole destination gets the checks a fresh copy gets: no
    link, reparse point or hardlink anywhere in it, the exact source file set and bytes, and
    the full reader gate. Only then is it registered.
    """
    checked_path(destination)
    for path in destination.rglob("*"):
        _reject_alias(path, path.lstat())
    expected = {item["path"]: item for item in files}
    present = {path.relative_to(destination).as_posix(): path for path in destination.rglob("*") if path.is_file()}
    if set(present) - {RECEIPT} != set(expected):
        raise FileExistsError(f"bundle already present with different contents, existing data is not overwritten: {destination}")
    for name, item in expected.items():
        with present[name].open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise FileExistsError(f"bundle already present with different contents, existing data is not overwritten: {destination}")
    gate(destination, entry["version_id"])
    DataCatalog(roots).register([entry])
    report(f"existing verified bundle registered: {DATA_ID}/{entry['version_id']}")
    return {"destination": str(destination), "files": len(files), "bytes": sum(item["bytes"] for item in files), "resumed": True}


def restore_bundle(
    source: Path,
    roots: DataRoots,
    *,
    gate: Callable[[Path, str], Any],
    expected_manifest_sha256: str = ORIGINAL_MANIFEST_SHA256,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Copy a producer bundle into the shared root, verify it, publish it, register it.

    Nothing is overwritten. Any failure before publication leaves the sibling `.staging-*`
    directory in place for inspection and the final directory absent. If publication succeeded
    but catalog registration failed, a rerun finds the final directory, applies the same alias,
    byte and reader-gate checks as a fresh copy and only then registers it.
    """
    report = progress or (lambda message: LOGGER.info("%s", message))
    started = time.monotonic()
    source = safe_path(Path(source))
    _require_separate(source, roots.data)
    files = _inventory(source, report)
    by_path = {item["path"]: item for item in files}
    manifest_item = by_path.get(MANIFEST)
    if manifest_item is None or manifest_item["sha256"] != expected_manifest_sha256:
        raise ValueError("source manifest does not match the pinned original bytes; nothing was written")
    manifest = json.loads((source / MANIFEST).read_bytes())
    entry = catalog_entry(manifest, expected_manifest_sha256)
    destination = roots.artifact_path("data", f"{KIND}/{DATA_ID}/{expected_manifest_sha256}")
    if destination.exists():
        return _resume_registration(destination, files, entry, roots, gate, report)
    staging = roots.artifact_path("data", f"{KIND}/{DATA_ID}/.staging-{expected_manifest_sha256[:12]}-{uuid.uuid4().hex}")
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    hashed = time.monotonic()
    report(f"copying {len(files)} files, {sum(item['bytes'] for item in files)} bytes into {staging}")
    for index, item in enumerate(files, 1):
        _copy_member(source / item["path"], safe_path(staging / item["path"]), item)
        if index % 1000 == 0:
            report(f"copied {index}/{len(files)}")
    copied = time.monotonic()
    # Second, independent read of what is now on disk.
    on_disk = {path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()}
    if on_disk != set(by_path):
        raise ValueError("copied file set differs from the source inventory")
    for item in files:
        with (staging / item["path"]).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError(f"copy verification failed: {item['path']}")
    verified = time.monotonic()
    gate(staging, expected_manifest_sha256)
    gated = time.monotonic()
    receipt = {
        "schema": "opportunity-history-copy-receipt.v1",
        "source": "<legacy-checkout>/.worktrees/strategy-presentation/tasks/20261005-market-full-history-web/inputs/producer-preview",
        "manifest_sha256": expected_manifest_sha256,
        "files": files,
        "seconds": {
            "hash_source": round(hashed - started, 1),
            "copy": round(copied - hashed, 1),
            "verify_copy": round(verified - copied, 1),
            "reader_gate": round(gated - verified, 1),
        },
    }
    with (staging / RECEIPT).open("xb") as stream:
        stream.write(canonical(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    publish_noreplace(staging, destination)
    for path in destination.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    DataCatalog(roots).register([entry])
    report(f"registered {DATA_ID}/{expected_manifest_sha256}")
    return {"destination": str(destination), "files": len(files), "bytes": sum(item["bytes"] for item in files), "seconds": receipt["seconds"]}
