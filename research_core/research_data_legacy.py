"""Register existing immutable artifacts in place, with conservative coverage."""

from __future__ import annotations

from typing import Any

from research_core.artifact_store import file_digest, read_json
from research_core.research_data_catalog import DataCatalog


def _period(start: str | None = None, end: str | None = None, reason: str | None = None) -> dict[str, Any]:
    return {"start": start, "end": end, "reason": reason}


def existing_entries(catalog: DataCatalog) -> list[dict[str, Any]]:
    """Metadata discovery, not a market evaluation or a bulk validity claim."""
    primary = catalog.roots.primary
    candidates = [
        ("market-context", "market", "market_context", primary / "tasks/20261005-market-context-handoff/market-context-v2/manifest.json"),
        ("atlas-v2", "features", "metadata_only", primary / "tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2/manifest.json"),
        (
            "hhhl-v1-descriptive",
            "patterns",
            "metadata_only",
            primary / "tasks/20261009-hhhl-pattern-probability/datasets/hhhl-v1-descriptive-02/manifest-corrected.json",
        ),
        ("hhhl-v4-descriptive", "patterns", "metadata_only", primary / "tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-descriptive-01/manifest.json"),
        ("hhhl-v4-variants", "patterns", "metadata_only", primary / "tasks/20261012-hhhl-v4-variants/datasets/hhhl-v4-variants-01/manifest.json"),
    ]
    candidates += [("price-bases", "prices", "derived_cache", path) for path in sorted((primary / "research_cache/price-bases").glob("*/manifest.json"))]
    result = []
    for data_id, kind, reader, candidate in candidates:
        name = candidate.relative_to(primary).as_posix()
        path = catalog.roots.artifact_path("primary", name)
        if not path.exists():
            continue
        manifest = read_json(path)
        if manifest.get("complete") is False:
            continue
        identity = manifest.get("identity", {})
        version = manifest.get("version_id", manifest.get("dataset_id", path.parent.name))
        # Stable portable ID; preserve the original dataset_id in inputs metadata.
        version = str(version).removeprefix("sha256:")
        limitations = [
            "Registration preserves original bytes and location; no time concatenation or market recomputation.",
            "Backup of this exact current version is not verified; no off-machine backup evidence.",
        ]
        if reader == "market_context":
            summary = manifest["summary"]
            period = _period(summary["start"], summary["end"])
            scope = "benchmark TW:0050 only"
            status, definition = "complete", manifest["definition_version"]
            parameters = {"layers": ["past_only", "retrospective"], "calendar_slots": summary["calendar_slots"]}
            inputs = {key: manifest[key] for key in ("series_id", "calendar_id", "source_manifest_sha256")}
            indicator = _period(reason="warmup and unusable rows differ by layer; consult retained summary.layers")
            labels = _period(reason="retrospective last 10 days are future_unavailable; not H126/H252 labels")
            limitations.append("Complete means the retained benchmark dataset, not full-market coverage or historical PIT certification.")
        else:
            window = manifest.get("window", identity.get("window", {}))
            if isinstance(window, list) and len(window) == 2:
                window = {"start": window[0], "end": window[1]}
            if not isinstance(window, dict):
                raise ValueError("retained window must be an object or a two-date array")
            if reader == "derived_cache":
                calendar = read_json(path.parent / "inputs/calendar.json")
                dates = calendar.get("dates", calendar.get("calendar", []))
                if isinstance(dates, list) and dates:
                    window = {"start": dates[0], "end": dates[-1]}
                definition = identity["definitions"]["prices"]
                codes = manifest["codes"]
                scope = f"{len(codes)} demonstration stocks; not full market"
                status, parameters = "partial", identity["parameters"]
                inputs = identity["inputs"]
            else:
                if not window:
                    pins = catalog.roots.artifact_path("primary", "tasks/20261012-hhhl-v4-variants/params/input-pins-v1.json")
                    if data_id == "hhhl-v4-variants" and pins.exists():
                        if file_digest(pins) != identity["input_pins_sha256"]:
                            # Primary may still have an older text checkout. Never
                            # rewrite its bytes or assign a new pin to old results.
                            limitations.append("Primary input-pins raw bytes differ from the sealed receipt; input period is not inferred from that file.")
                        else:
                            calendar = read_json(pins)["calendar"]
                            window = {"start": calendar["first"], "end": calendar["last"]}
                definition = str(manifest.get("rule", manifest.get("feature_definition_id", manifest.get("schema_version", "retained-definition"))))
                scope = "retained study stock universe; consult original data contract"
                status = "legacy"
                parameters = {"original_schema": manifest.get("schema_version"), "original_dataset_id": manifest.get("dataset_id"), "run": path.parent.name}
                inputs = {"original_manifest_sha256": file_digest(path), "identity": identity, "source_dataset_id": manifest.get("source_dataset_id")}
                limitations.append("Metadata-only discovery: payload validity and access remain with the indexed original reader/contract.")
            period = _period(
                window.get("start"),
                window.get("end"),
                None if window.get("start") and window.get("end") else "period not directly available in retained metadata; consult original input pins",
            )
            indicator = _period(reason="feature-specific warmup and gaps; not inferred from raw input period")
            labels = _period(reason="horizon-specific incomplete windows; consult original result contract")
            limitations.append("Existing 2019-onward inputs do not meet the new 2010-onward study requirement; reuse code, not concatenated time slices.")
        result.append({
            "data_id": data_id,
            "version_id": version,
            "kind": kind,
            "definition_version": definition,
            "parameters": parameters,
            "inputs": inputs,
            "coverage": {"scope": scope, "raw_input_period": period, "valid_indicator_period": indicator, "complete_label_period": labels},
            "status": status,
            "limitations": limitations,
            "backup": {"status": "unknown_for_exact_version", "off_machine": "unverified", "same_disk_only_if_present": True},
            "reader": reader,
            "manifest": {"scope": "primary", "path": name, "sha256": file_digest(path)},
        })
    return result


def register_existing(catalog: DataCatalog) -> dict[str, Any]:
    return catalog.register(existing_entries(catalog))
