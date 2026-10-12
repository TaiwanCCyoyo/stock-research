"""Exact-identity immutable feature blocks with additive recovery generations."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import (
    canonical,
    file_digest,
    object_digest,
    publish_new_directory,
    read_json,
    relative_name,
    safe_path,
    verify_files,
    write_json,
)
from research_core.feature_identity_v1 import identity_digest, validate_identity

SCHEMA = "research-feature-publication.v1"
DIGEST = re.compile(r"[0-9a-f]{64}")


def _content(entries: list[dict[str, Any]]) -> str:
    return object_digest(sorted(entries, key=lambda entry: entry["path"]))


def verify_block(version: Path, identity: dict[str, Any] | None = None) -> dict[str, Any]:
    version = safe_path(version)
    if DIGEST.fullmatch(version.name) is None or DIGEST.fullmatch(version.parent.name) is None:
        raise ValueError("explicit identity/version digest directory required")
    manifest_path = version / "manifest.json"
    external = file_digest(manifest_path)
    manifest = read_json(manifest_path)
    if manifest.get("schema") != SCHEMA or manifest.get("complete") is not True:
        raise ValueError("incomplete feature publication")
    stored = validate_identity(manifest["identity"])
    if identity_digest(stored) != version.parent.name:
        raise ValueError("feature identity directory mismatch")
    if identity is not None and stored != validate_identity(identity):
        raise ValueError("requested feature identity mismatch")
    if manifest.get("version_id") != version.name or object_digest({key: value for key, value in manifest.items() if key != "version_id"}) != version.name:
        raise ValueError("publication version mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("nonempty feature artifacts required")
    verify_files(version, artifacts)
    expected = {relative_name(entry["path"]) for entry in artifacts} | {"manifest.json"}
    observed = set()
    for path in version.rglob("*"):
        safe_path(path)
        if path.is_file():
            observed.add(path.relative_to(version).as_posix())
    if observed != expected:
        raise ValueError("feature artifact inventory mismatch")
    if file_digest(manifest_path) != external:
        raise ValueError("feature manifest changed during verification")
    return manifest


class FeatureBlockStore:
    """The caller supplies an explicit root; no mutable latest or live fallback."""

    def __init__(self, root: Path):
        if not root.is_absolute():
            raise ValueError("absolute feature store root required")
        self.root = safe_path(root)

    def inspect(self, identity: dict[str, Any]) -> dict[str, Any]:
        identity = validate_identity(identity)
        key = identity_digest(identity)
        directory = safe_path(self.root / key)
        valid: list[tuple[Path, dict[str, Any]]] = []
        invalid: list[dict[str, str]] = []
        if directory.exists():
            if not directory.is_dir():
                return {"identity_id": key, "status": "invalid", "reason": "identity path is not a directory", "invalid": [], "reference": None}
            for path in sorted(directory.iterdir()):
                if path.name.startswith(".staging-"):
                    continue
                try:
                    manifest = verify_block(path, identity)
                    valid.append((path, manifest))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    invalid.append({"path": path.name, "reason": str(error)})
        contents = {_content(manifest["artifacts"]) for _, manifest in valid}
        if len(contents) > 1:
            return {"identity_id": key, "status": "conflict", "reason": "same identity has different valid output bytes", "invalid": invalid, "reference": None}
        if valid:
            path, manifest = valid[0]
            reference = {
                "path": str(path),
                "identity_id": key,
                "version_id": path.name,
                "manifest_sha256": file_digest(path / "manifest.json"),
                "artifacts": manifest["artifacts"],
            }
            return {"identity_id": key, "status": "reusable", "invalid": invalid, "reference": reference}
        return {"identity_id": key, "status": "invalid" if invalid else "missing", "invalid": invalid, "reference": None}

    def plan(self, identities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = [identity_digest(identity) for identity in identities]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate requested feature identity")
        return [self.inspect(identity) for identity in identities]

    def publish(self, identity: dict[str, Any], payloads: dict[str, bytes]) -> dict[str, Any]:
        identity = validate_identity(identity)
        if not payloads or any(not isinstance(data, bytes) for data in payloads.values()):
            raise ValueError("nonempty byte payload mapping required")
        for name in payloads:
            relative_name(name)
            if name == "manifest.json" or name.startswith("manifest.json/"):
                raise ValueError("manifest path is reserved")
        descriptors = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(payloads.items())]
        key = identity_digest(identity)
        self.root.mkdir(parents=True, exist_ok=True)
        lock = safe_path(self.root / f".{key}.lock")
        token = {"pid": os.getpid(), "token": uuid.uuid4().hex, "identity_id": key}
        write_json(lock, token)
        succeeded = False
        try:
            existing = self.inspect(identity)
            if existing["status"] == "conflict":
                raise ValueError(existing["reason"])
            if existing["status"] == "reusable":
                if _content(existing["reference"]["artifacts"]) != _content(descriptors):
                    raise ValueError("same identity produced different bytes")
                succeeded = True
                return {**existing["reference"], "reused": True}
            directory = safe_path(self.root / key)
            directory.mkdir(exist_ok=True)
            body = {"schema": SCHEMA, "complete": True, "identity": identity, "artifacts": descriptors, "publication_nonce": uuid.uuid4().hex}
            version_id = object_digest(body)
            manifest = {**body, "version_id": version_id}
            version = safe_path(directory / version_id)
            publish_new_directory(version, {**payloads, "manifest.json": canonical(manifest)})
            verify_block(version, identity)
            succeeded = True
            return {
                "path": str(version),
                "identity_id": key,
                "version_id": version_id,
                "manifest_sha256": file_digest(version / "manifest.json"),
                "artifacts": descriptors,
                "reused": False,
            }
        finally:
            # Keep an unsuccessful lock/staging as evidence; never clear another writer.
            if succeeded and read_json(lock) == token:
                lock.unlink()

    def read(self, identity: dict[str, Any], artifact: str, *, reference: dict[str, Any] | None = None) -> bytes:
        artifact = relative_name(artifact)
        if reference is None:
            result = self.inspect(identity)
            if result["status"] != "reusable":
                raise ValueError(f"feature block is {result['status']}")
            reference = result["reference"]
        if reference is None:
            raise ValueError("feature reference is missing")
        path = Path(reference["path"])
        if not path.is_absolute():
            raise ValueError("absolute feature reference path required")
        version = safe_path(path)
        if reference["identity_id"] != identity_digest(identity) or reference["version_id"] != version.name:
            raise ValueError("external reference identity/version mismatch")
        if version.parent != self.root / identity_digest(identity):
            raise ValueError("reference lies outside the requested store identity")
        if file_digest(version / "manifest.json") != reference["manifest_sha256"]:
            raise ValueError("external manifest pin mismatch")
        manifest = verify_block(version, identity)
        if artifact not in {entry["path"] for entry in manifest["artifacts"]}:
            raise ValueError("artifact not declared")
        data = safe_path(version / artifact).read_bytes()
        entry = next(entry for entry in manifest["artifacts"] if entry["path"] == artifact)
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("returned artifact bytes mismatch")
        verify_files(version, manifest["artifacts"])
        if file_digest(version / "manifest.json") != reference["manifest_sha256"]:
            raise ValueError("manifest changed during read")
        return data
