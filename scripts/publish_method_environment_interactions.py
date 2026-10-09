"""Publish and read the two approved research batches without restoring or executing them."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import logging
import lzma
import stat
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_core.evidence import EvidenceError, finite_json, read_json  # noqa: E402
from research_core.jobs import confined, digest, job_directory, validate_packet, validate_summary, verify_reuse  # noqa: E402

TASK = "20261005-method-environment-interactions"
SCHEMA = "method-environment-publication.v1"
OUTPUTS = {"summary.json", "results.json", "input-audit.json"}
FILES = {*(name + ".gz" for name in OUTPUTS), "packet.json.gz", "receipt.json.gz", "source-inputs.zip"}
INDUSTRY_TASK = "20261005-industry-role-comparison"
INDUSTRY_SCHEMA = "industry-role-publication.v1"
INDUSTRY_FILES = {*(name + ".xz" for name in OUTPUTS), "packet.json.xz", "receipt.json.xz", "source-inputs.zip"}
TRANSPORT_SCHEMA = "industry-role-transport.v2"
MAX_PART_BYTES = 350000
PART_BYTES = MAX_PART_BYTES
TRANSPORT_COPIES = INDUSTRY_FILES - {"results.json.xz"}
LIMITATION = "Bulk source data remains local at the recorded source paths; this package permits compact evidence reading, not full recomputation."
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Profile:
    task: str
    schema: str
    suffix: str
    files: frozenset[str]


_PROFILES = (
    _Profile(TASK, SCHEMA, ".gz", frozenset(FILES)),
    _Profile(INDUSTRY_TASK, INDUSTRY_SCHEMA, ".xz", frozenset(INDUSTRY_FILES)),
)


def _schema_profile(schema: Any) -> _Profile:
    for profile in _PROFILES:
        if schema == profile.schema:
            return profile
    raise EvidenceError("publication schema or required file set mismatch")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(root: Path, path: Path) -> Path:
    root = root.absolute()
    for ancestor in (root, *root.parents):
        if ancestor.exists() or ancestor.is_symlink():
            attributes = getattr(ancestor.lstat(), "st_file_attributes", 0)
            if ancestor.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                raise EvidenceError(f"linked/reparse path forbidden: {ancestor}")
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.absolute().relative_to(root).as_posix()
    except ValueError as error:
        raise EvidenceError("path escaped root") from error
    return confined(root, relative)


def _json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    finite_json(value)
    return value


def _packet(packet: dict[str, Any]) -> _Profile:
    validate_packet(packet)
    for profile in _PROFILES:
        if packet["task_id"] == profile.task and set(packet["outputs"]) == OUTPUTS and packet["summary"] == "summary.json":
            return profile
    raise EvidenceError("publication requires an approved task and exact expected outputs")


def _identity(manifest: dict[str, Any]) -> str:
    schema = manifest.get("schema_version")
    schema = TRANSPORT_SCHEMA if schema == TRANSPORT_SCHEMA else _schema_profile(schema).schema
    return schema + "-" + digest({key: value for key, value in manifest.items() if key != "artifact_id"})


def publish(root: Path, packet_path: Path, approved_sha256: str, destination: Path) -> dict[str, Any]:
    """Verify before writes; retain any partial fresh publication on failure."""
    packet_path, destination = _path(root, packet_path), _path(root, destination)
    packet_bytes = packet_path.read_bytes()
    packet = _json(packet_bytes)
    profile = _packet(packet)
    if digest(packet) != approved_sha256:
        raise EvidenceError("packet differs from approved digest")
    source = job_directory(root, packet)
    inputs = packet["inputs"]
    for group in inputs.values():
        for name in group:
            _path(root, Path(name))
    forbidden = [source, *(confined(root, name).parent for name in inputs["data"])]
    if any(destination.is_relative_to(path) for path in forbidden):
        raise EvidenceError("destination lies inside source job or input tree")
    if destination.exists():
        raise EvidenceError("publication destination exists; no overwrite")
    receipt = verify_reuse(root, packet)
    LOGGER.info("Verified reuse job=%s; publishing compact evidence", packet["job_id"])
    destination.mkdir(parents=True, exist_ok=False)
    saved = {"packet.json": packet_bytes, "receipt.json": confined(source, "receipt.json").read_bytes()}
    saved.update({name: confined(source, name).read_bytes() for name in sorted(OUTPUTS)})
    for name, raw in saved.items():
        with confined(destination, name + profile.suffix).open("xb") as stream:
            stream.write(gzip.compress(raw, mtime=0) if profile.suffix == ".gz" else lzma.compress(raw, format=lzma.FORMAT_XZ))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, expected in sorted({**inputs["code"], **inputs["contracts"]}.items()):
            raw = confined(root, name).read_bytes()
            if _sha(raw) != expected:
                raise EvidenceError(f"input identity mismatch: {name}")
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, raw)
    with confined(destination, "source-inputs.zip").open("xb") as stream:
        stream.write(archive.getvalue())
    if packet_path.read_bytes() != packet_bytes or verify_reuse(root, packet) != receipt:
        raise EvidenceError("source packet or receipt changed during publication")
    manifest: dict[str, Any] = {
        "schema_version": profile.schema,
        "packet_sha256": approved_sha256,
        "files": {name: _sha(confined(destination, name).read_bytes()) for name in sorted(profile.files)},
        "source_datasets": _json(saved["input-audit.json"])["source_datasets"],
        "bulk_limitation": LIMITATION,
    }
    manifest["artifact_id"] = _identity(manifest)
    # Validate copied bytes before the completion manifest becomes visible.
    _read_payload(destination, manifest)
    with confined(destination, "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return manifest


def _read_payload(path: Path, manifest: dict[str, Any], raw_files: dict[str, bytes] | None = None) -> dict[str, Any]:
    profile = _schema_profile(manifest.get("schema_version"))
    if set(manifest.get("files", {})) != profile.files:
        raise EvidenceError("publication schema or required file set mismatch")
    if manifest.get("artifact_id") != _identity(manifest) or manifest.get("bulk_limitation") != LIMITATION:
        raise EvidenceError("publication identity or limitation mismatch")
    if raw_files is None:
        raw_files = {name: confined(path, name).read_bytes() for name in profile.files}
    if set(raw_files) != profile.files:
        raise EvidenceError("publication schema or required file set mismatch")
    if any(_sha(raw) != manifest["files"][name] for name, raw in raw_files.items()):
        raise EvidenceError("stored file hash mismatch")
    plain = {
        name.removesuffix(profile.suffix): gzip.decompress(raw) if profile.suffix == ".gz" else lzma.decompress(raw, format=lzma.FORMAT_XZ)
        for name, raw in raw_files.items()
        if name.endswith(profile.suffix)
    }
    packet, receipt = _json(plain["packet.json"]), _json(plain["receipt.json"])
    if _packet(packet) != profile:
        raise EvidenceError("publication task and schema mismatch")
    packet_hash = digest(packet)
    if manifest["packet_sha256"] != packet_hash or receipt.get("packet_sha256") != packet_hash:
        raise EvidenceError("saved packet digest mismatch")
    if (
        receipt.get("schema_version") != "research-receipt.v1"
        or receipt.get("status") != "completed"
        or receipt.get("outputs") != {name: _sha(plain[name]) for name in OUTPUTS}
    ):
        raise EvidenceError("saved receipt output binding mismatch")
    expected = {**packet["inputs"]["code"], **packet["inputs"]["contracts"]}
    with zipfile.ZipFile(io.BytesIO(raw_files["source-inputs.zip"])) as bundle:
        if len(bundle.namelist()) != len(expected) or set(bundle.namelist()) != set(expected):
            raise EvidenceError("archived input set mismatch")
        for name, sha in expected.items():
            confined(path, name)  # Validate archive member syntax; never extract.
            if _sha(bundle.read(name)) != sha:
                raise EvidenceError("archived input hash mismatch")
    outputs = {name.removesuffix(".json"): _json(plain[name]) for name in OUTPUTS}
    validate_summary(outputs["summary"])
    if manifest["source_datasets"] != outputs["input-audit"]["source_datasets"]:
        raise EvidenceError("source dataset references mismatch")
    return {"manifest": manifest, "packet": packet, "receipt": receipt, **outputs}


def _read_transport(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    keys = {"schema_version", "artifact_id", "source_artifact_id", "result_parts", "files", "bulk_limitation"}
    parts = manifest.get("result_parts")
    if (
        set(manifest) != keys
        or manifest.get("schema_version") != TRANSPORT_SCHEMA
        or not isinstance(parts, list)
        or not 1 <= len(parts) <= 1000
        or parts != [f"results.json.xz.part{index:03d}" for index in range(len(parts))]
    ):
        raise EvidenceError("transport schema or result parts mismatch")
    files = TRANSPORT_COPIES | {"source-manifest.json", *parts}
    if not isinstance(manifest["files"], dict) or set(manifest["files"]) != files:
        raise EvidenceError("transport required file set mismatch")
    if {item.name for item in path.iterdir()} - {"manifest.json"} != files:
        raise EvidenceError("publication requires exact file set")
    if manifest["artifact_id"] != _identity(manifest) or manifest["bulk_limitation"] != LIMITATION:
        raise EvidenceError("transport identity or limitation mismatch")
    raw = {name: confined(path, name).read_bytes() for name in files}
    if any(_sha(value) != manifest["files"][name] for name, value in raw.items()):
        raise EvidenceError("stored file hash mismatch")
    if any(not 1 <= len(raw[name]) <= MAX_PART_BYTES for name in parts):
        raise EvidenceError("transport result part size mismatch")
    source_manifest = _json(raw["source-manifest.json"])
    if (
        not isinstance(source_manifest, dict)
        or source_manifest.get("schema_version") != INDUSTRY_SCHEMA
        or source_manifest.get("artifact_id") != manifest["source_artifact_id"]
    ):
        raise EvidenceError("transport source identity or schema mismatch")
    originals = {name: raw[name] for name in TRANSPORT_COPIES}
    originals["results.json.xz"] = b"".join(raw[name] for name in parts)
    data = _read_payload(path, source_manifest, originals)
    return {**data, "manifest": manifest, "source_manifest": source_manifest}


def repack_industry(source: Path, destination: Path) -> dict[str, Any]:
    """Split saved XZ bytes for transport, without touching the source or running research."""
    source = _path(source.absolute().parent, Path(source.absolute().name))
    destination = _path(destination.absolute().parent, Path(destination.absolute().name))
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise EvidenceError("transport source and destination overlap")
    if destination.exists():
        raise EvidenceError("publication destination exists; no overwrite")
    source_manifest = read_publication(source)["manifest"]
    if source_manifest["schema_version"] != INDUSTRY_SCHEMA:
        raise EvidenceError("transport requires industry publication v1")
    saved = {name: confined(source, name).read_bytes() for name in INDUSTRY_FILES | {"manifest.json"}}
    if _json(saved["manifest.json"]) != source_manifest:
        raise EvidenceError("source changed during transport")
    _read_payload(source, source_manifest, {name: saved[name] for name in INDUSTRY_FILES})
    result = saved["results.json.xz"]
    if not 1 <= PART_BYTES <= MAX_PART_BYTES or (len(result) + PART_BYTES - 1) // PART_BYTES > 1000:
        raise EvidenceError("transport result part size or count mismatch")
    parts = {f"results.json.xz.part{index:03d}": result[start : start + PART_BYTES] for index, start in enumerate(range(0, len(result), PART_BYTES))}
    copied = {name: saved[name] for name in TRANSPORT_COPIES}
    copied.update({"source-manifest.json": saved["manifest.json"], **parts})
    LOGGER.info("Repacking saved artifact=%s into %s parts", source_manifest["artifact_id"], len(parts))
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in copied.items():
        with confined(destination, name).open("xb") as stream:
            stream.write(raw)
    manifest: dict[str, Any] = {
        "schema_version": TRANSPORT_SCHEMA,
        "source_artifact_id": source_manifest["artifact_id"],
        "result_parts": list(parts),
        "files": {name: _sha(raw) for name, raw in sorted(copied.items())},
        "bulk_limitation": LIMITATION,
    }
    manifest["artifact_id"] = _identity(manifest)
    if read_publication(source)["manifest"]["artifact_id"] != source_manifest["artifact_id"] or any(
        confined(source, name).read_bytes() != raw for name, raw in saved.items()
    ):
        raise EvidenceError("source changed during transport")
    _read_transport(destination, manifest)
    with confined(destination, "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return manifest


def read_publication(path: Path) -> dict[str, Any]:
    """Read saved evidence without the source worktree, runtime or bulk files."""
    path = _path(path.absolute().parent, Path(path.absolute().name))
    names = {item.name for item in path.iterdir()}
    if "manifest.json" not in names:
        raise EvidenceError("publication requires exact file set")
    manifest = read_json(confined(path, "manifest.json"))
    if manifest.get("schema_version") == TRANSPORT_SCHEMA:
        return _read_transport(path, manifest)
    profile = _schema_profile(manifest.get("schema_version"))
    if names != profile.files | {"manifest.json"}:
        raise EvidenceError("publication requires exact file set")
    return _read_payload(path, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read", type=Path)
    parser.add_argument("--repack", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--approved-sha256")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.read:
        if args.repack or args.packet or args.approved_sha256 or args.destination:
            parser.error("--read cannot be combined with publication arguments")
        data = read_publication(args.read)
        result: dict[str, Any] = {
            "artifact_id": data["manifest"]["artifact_id"],
            "comparison_rows": len(data["results"]["comparisons"]),
            "triage": data["results"]["triage"],
        }
    elif args.repack:
        if not args.destination or args.packet or args.approved_sha256:
            parser.error("--repack requires --destination and cannot be combined with publication arguments")
        result = repack_industry(args.repack, args.destination)
    elif args.packet and args.approved_sha256 and args.destination:
        result = publish(ROOT, args.packet, args.approved_sha256, args.destination)
    else:
        parser.error("publish requires --packet, --approved-sha256 and --destination")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
