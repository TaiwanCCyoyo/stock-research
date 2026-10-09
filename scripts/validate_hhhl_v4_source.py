"""Freeze explicit v4 inputs and verify owner examples without forward labels."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from research_core.feature_atlas_dataset import verify_dataset
from research_core.hhhl_rule_source import load_rule
from research_core.hhhl_v4_source import DATASET_ID, FIXED_INPUT_SHA256
from research_core.jobs import confined, file_digest

LOGGER = logging.getLogger(__name__)
RULE_ID = "hhhl_rule_v4"
RAW_COLUMNS = ["asof_date", "RawOpen", "RawHigh", "RawLow", "RawClose", "VolumeLots", "atr14_pct"]
CASE_SOURCE_HASH = "4cd3eab10b14ee8063b62e3a7e520f5bcbb922f16293896199613876700efc2d"  # pragma: allowlist secret - frozen source SHA-256


def write_json(path: Path, value: Any) -> None:
    """Create new evidence only; do not replace a previous attempt."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def freeze_inputs(actions: Path, examples: Path, output: Path) -> dict[str, Any]:
    """Capture one read-only SQLite statement, not a file copy of a live DB."""
    if file_digest(examples) != CASE_SOURCE_HASH:
        raise ValueError("example source SHA256 mismatch")
    source_cases = json.loads(examples.read_text(encoding="utf-8"))
    cases = [{"id": row["id"], "code": str(row["code"]), "date": row["date"], "kind": "rule"} for row in source_cases if row["kind"] == "rule"]
    if len(cases) != 24 or len({(row["code"], row["date"]) for row in cases}) != 24:
        raise ValueError("expected exactly 24 distinct owner rule examples")
    cases.append({"id": "old-pressure-2527", "code": "2527", "date": "2023-04-07", "kind": "old_pressure"})
    if output.exists():
        raise FileExistsError(f"input attempt already exists: {output}")
    query = "SELECT code, ex_date, event_type, price_factor FROM corporate_actions ORDER BY code, ex_date, source, market"
    with sqlite3.connect(f"{actions.resolve().as_uri()}?mode=ro", uri=True) as connection:
        factors = pd.read_sql_query(query, connection)
    # The SELECT is one consistent SQLite read transaction. The parquet is the
    # executable input identity; the live main DB hash would omit possible WAL.
    output.mkdir(parents=True, exist_ok=False)
    factor_path = output / "corporate_action_factors.parquet"
    cases_path = output / "validation-cases.json"
    factors.to_parquet(factor_path, index=False)
    write_json(cases_path, cases)
    receipt = {
        "schema_version": "hhhl-v4-validation-inputs.v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_database": str(actions.resolve()),
        "read_mode": "SQLite mode=ro, one consistent SELECT; no primary writes",
        "query": query,
        "factor_rows": len(factors),
        "factor_snapshot": {"path": factor_path.name, "sha256": file_digest(factor_path)},
        "validation_cases": {"path": cases_path.name, "sha256": file_digest(cases_path), "count": len(cases)},
        "example_source": {"path": str(examples.resolve()), "sha256": CASE_SOURCE_HASH},
        "outcomes_read": False,
        "scope": "source parity only; no probability execution authority",
    }
    write_json(output / "input-receipt.json", receipt)
    LOGGER.info("Captured factor rows=%d validation cases=%d", len(factors), len(cases))
    return receipt


def read_inputs(inputs: Path) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Read only the named, hashed input snapshot."""
    receipt = json.loads((inputs / "input-receipt.json").read_text(encoding="utf-8"))
    paths = {}
    for name in ("factor_snapshot", "validation_cases"):
        entry = receipt[name]
        path = confined(inputs, entry["path"])
        if file_digest(path) != entry["sha256"]:
            raise ValueError(f"input SHA256 mismatch: {name}")
        paths[name] = path
    factors = pd.read_parquet(paths["factor_snapshot"])
    if len(factors) != receipt["factor_rows"]:
        raise ValueError("factor snapshot row count mismatch")
    cases = json.loads(paths["validation_cases"].read_text(encoding="utf-8"))
    return factors, cases, receipt


def _verify_fixed_input_identity(inputs: Path) -> None:
    for relative, expected in FIXED_INPUT_SHA256.items():
        path = confined(inputs, relative)
        if not path.is_file() or file_digest(path) != expected:
            raise ValueError(f"unauthorized fixed input SHA-256: {relative}")


def validate(dataset: Path, sources: Path, inputs: Path) -> dict[str, Any]:
    """Verify exact rule parity using projected price columns, never labels."""
    from research_core.hhhl_v4_source import prepare_v4_prices

    manifest_path = dataset / "manifest.json"
    manifest_digest = file_digest(manifest_path)
    verified = verify_dataset(dataset)
    if verified["dataset_id"] != DATASET_ID:
        raise ValueError("source validation requires the mission fixed atlas dataset_id")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["dataset_id"] != DATASET_ID or file_digest(manifest_path) != manifest_digest:
        raise ValueError("atlas manifest changed during dataset verification")
    _verify_fixed_input_identity(inputs)
    factors, cases, receipt = read_inputs(inputs)
    _verify_fixed_input_identity(inputs)
    rule = load_rule(sources, RULE_ID)
    LOGGER.info("Verified fixed atlas identity=%s and original preparation inputs", DATASET_ID)
    entries = {entry["security_id"].split(":")[-1]: entry for entry in manifest["tables"]}
    results = []
    consumed = []
    for code in sorted({row["code"] for row in cases}):
        entry = entries[code]
        table = confined(dataset, entry["path"])
        if file_digest(table) != entry["sha256"]:
            raise ValueError(f"atlas table SHA256 mismatch: {entry['path']}")
        raw = pd.read_parquet(table, columns=RAW_COLUMNS)
        if len(raw) != entry["rows"]:
            raise ValueError(f"atlas table row count mismatch: {entry['path']}")
        dates = pd.to_datetime(raw["asof_date"])
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise ValueError(f"invalid atlas calendar: {code}")
        frame = prepare_v4_prices(raw, factors, code, sources=sources)
        event_dates = pd.to_datetime(frame["asof_date"]).dt.strftime("%Y-%m-%d")
        events = {event_dates.iloc[event["t"]]: event for event in rule.detect(frame)}
        consumed.append({
            "code": code,
            "path": entry["path"],
            "sha256": entry["sha256"],
            "rows": len(raw),
            "detector_rows": len(frame),
            "preparation": frame.attrs.get("preparation_metadata", {}),
        })
        for case in (row for row in cases if row["code"] == code):
            event = events.get(case["date"])
            bonus = event["bonus_levels"] if event else []
            if case["kind"] == "rule":
                passed = event is not None and bool(event["pattern"]) and not bonus
            else:
                passed = (
                    event is not None
                    and bool(event["pattern"])
                    and event["scale"] == "small_range"
                    and any(level["age"] == "old" and math.isclose(level["level"], 20.48, abs_tol=0.05) for level in bonus)
                )
            results.append({
                **case,
                "passed": passed,
                "found": event is not None,
                "pattern": bool(event["pattern"]) if event else None,
                "scale": event["scale"] if event else None,
                "bonus_levels": bonus,
                "restart": int(event["restart"]) if event else None,
                "leg_start": int(event["leg_start"]) if event else None,
            })
        LOGGER.info("Verified case security=%s rows=%d", code, len(raw))
    rule_cases = [row for row in results if row["kind"] == "rule"]
    old_cases = [row for row in results if row["kind"] == "old_pressure"]
    checks = {
        "rule_exact24": len(rule_cases) == 24 and all(row["passed"] for row in rule_cases),
        "old_pressure_example": len(old_cases) == 1 and old_cases[0]["passed"],
        "atlas_manifest_unchanged": file_digest(manifest_path) == manifest_digest,
    }
    # Revalidate all consumed identities after execution, including the factors.
    _verify_fixed_input_identity(inputs)
    read_inputs(inputs)
    _verify_fixed_input_identity(inputs)
    checks["consumed_tables_unchanged"] = all(file_digest(confined(dataset, row["path"])) == row["sha256"] for row in consumed)
    return {
        "schema_version": "hhhl-v4-source-validation.v1",
        "passed": all(checks.values()),
        "dataset_id": manifest["dataset_id"],
        "rule_id": RULE_ID,
        "source_hashes": rule.source_hashes,
        "factor_input": receipt,
        "checks": checks,
        "cases": results,
        "consumed_tables": consumed,
        "outcomes_read": False,
        "price_basis": "corporate-action reference-factor adjusted OHLC, not executable cash total return",
        "old_level_validation_tolerance": 0.05,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--freeze-actions", type=Path)
    parser.add_argument("--examples", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        if args.freeze_actions:
            if not args.examples:
                parser.error("--freeze-actions requires --examples")
            report = freeze_inputs(args.freeze_actions, args.examples, args.inputs)
        else:
            if not args.dataset or not args.sources or not args.report:
                parser.error("validation requires --dataset, --sources and --report")
            if args.report.exists():
                raise FileExistsError(f"validation report already exists: {args.report}")
            report = validate(args.dataset, args.sources, args.inputs)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))  # noqa: T201 - CLI evidence
        return 0 if report.get("passed", True) else 1
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        LOGGER.error("V4 source validation failed: %s", exc)
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))  # noqa: T201 - CLI evidence
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
