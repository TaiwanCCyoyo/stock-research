"""Serialize and publish fixed HHHL variants results without calculation authority."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import pyarrow.parquet as pq

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, safe_path, write_json
from research_core.hhhl_variants_query import summary_transport

LOGGER = logging.getLogger(__name__)


class PublicationInputs(Protocol):
    tables: list[dict[str, Any]]
    pins: dict[str, Any]


def publish_result(
    inputs: PublicationInputs,
    pins_path: Path,
    staging: Path,
    final: Path,
    publication: Path,
    summary: pd.DataFrame,
    selection: dict[str, Any],
    execution: dict[str, Any],
    mission_path: Path,
) -> dict[str, Any]:
    """Publish already verified calculations additively; never replace an existing version.

    The caller owns input/code verification and execution locks. Failure preserves staged
    evidence; publication failure after dataset publication retains the completed dataset.
    """
    staging, final, publication = map(safe_path, (staging, final, publication))
    if staging.parent != final.parent or staging == final:
        raise ValueError("dataset staging and final require distinct sibling paths")
    if publication.is_relative_to(final) or publication.is_relative_to(staging) or final.is_relative_to(publication) or staging.is_relative_to(publication):
        raise ValueError("dataset and portable publication paths must not overlap")
    if final.exists() or publication.exists():
        raise FileExistsError("fixed dataset/publication already exists; do not replace it")
    if not staging.is_dir():
        raise FileNotFoundError(f"dataset staging directory missing: {staging}")
    prepared = summary.copy()
    prepared["input_dataset_id"] = "hhhl-v4-descriptive-01"
    prepared["input_manifest_sha256"] = inputs.pins["v4_bulk"]["manifest_sha256"]
    with safe_path(staging / "summary.parquet").open("xb") as stream:
        prepared.to_parquet(stream, index=False, compression="zstd", compression_level=19)
    artifacts = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        descriptor = describe_file(staging, path)
        if path.suffix == ".parquet":
            metadata = pq.ParquetFile(safe_path(path)).metadata
            if metadata is None:
                raise ValueError(f"parquet metadata missing: {path}")
            descriptor["rows"] = metadata.num_rows
        if path.parent.name in {"features", "observations", "flags", "daily", "pivots"}:
            ordinal = int(path.stem)
            if not 1 <= ordinal <= len(inputs.tables):
                raise ValueError(f"shard ordinal outside input table inventory: {path}")
            descriptor["code"] = inputs.tables[ordinal - 1]["security_id"].split(":", 1)[1]
        artifacts.append(descriptor)
    identity = {
        "input_pins_sha256": file_digest(pins_path),
        "execution": execution,
        "mission_sha256": file_digest(mission_path),
        "definition_id": "hhhl-variants-features.v1",
    }
    dataset_id = "hhhl-variants-" + object_digest(identity)
    manifest = {
        "schema_version": "hhhl-variants-dataset.v1",
        "dataset_id": dataset_id,
        "identity": identity,
        "artifacts": artifacts,
        "summary_rows": len(prepared),
        "candidate_n": len(selection["candidates"]),
    }
    write_json(staging / "manifest.json", manifest)
    publish_noreplace(staging, final)
    publication.parent.mkdir(parents=True, exist_ok=True)
    pub_stage = safe_path(publication.parent / f".staging-{publication.name}-{uuid.uuid4().hex}")
    pub_stage.mkdir()
    contents, descriptor = summary_transport((final / "summary.parquet").read_bytes(), len(prepared))
    for name, data in contents.items():
        with safe_path(pub_stage / name).open("xb") as stream:
            stream.write(data)
    receipt = {
        "schema_version": "hhhl-variants-publication.v1",
        "dataset_id": dataset_id,
        "summary": descriptor,
        "local_dataset": {"path": str(final), "manifest_sha256": file_digest(final / "manifest.json")},
        "execution": execution,
        "summary_row_kind_counts": {str(kind): int(count) for kind, count in prepared.groupby("row_kind").size().items()},
        "summary_base_row_kind_counts": {str(kind): int(count) for kind, count in prepared.groupby("base_row_kind").size().items()},
    }
    write_json(pub_stage / "receipt.json", receipt)
    publish_noreplace(pub_stage, publication)
    LOGGER.info("Published fixed HHHL variants result: dataset=%s summary_rows=%d", dataset_id, len(prepared))
    return receipt
