"""Export a read-only price atlas for the sector-wave catalog presentation."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import math
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

WINDOW_START = "2019-01-02"
WINDOW_END = "2026-08-14"
SCHEMA = "market-atlas.v1"
LOGGER = logging.getLogger(__name__)
# ECMAScript String.trim whitespace and line terminators used by the browser reader.
ECMASCRIPT_TRIM_CHARACTERS = (
    "\u0009\u000b\u000c\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000\ufeff\u000a\u000d\u2028\u2029"
)
PERMANENT_FACTOR_EVENTS = {
    "ETF_SPLIT",
    "ETF_REVERSE_SPLIT",
    "EX_RIGHT",
    "EX_RIGHT_AND_DIVIDEND",
    "CASH_CAPITAL_REDUCTION",
    "LOSS_OFFSET_CAPITAL_REDUCTION",
    "CAPITAL_REDUCTION",
}


class AtlasExportError(ValueError):
    """The immutable catalog or its pinned read-only source is invalid."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AtlasExportError(f"invalid JSON input: {path}") from error
    if not isinstance(value, dict):
        raise AtlasExportError(f"JSON input must be an object: {path}")
    return value


def _load_catalog(catalog: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    manifest = _read_json(catalog / "manifest.json")
    receipt = _read_json(catalog / "completion-receipt.json")
    catalog_hash = _canonical_json_sha256(manifest)
    if receipt.get("manifest_canonical_sha256") != catalog_hash:
        raise AtlasExportError("catalog manifest hash does not match completion receipt")

    tables: dict[str, list[dict[str, Any]]] = {"groups": [], "securities": [], "quality_findings": []}
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        raise AtlasExportError("catalog manifest chunks must be a list")
    for chunk in chunks:
        if not isinstance(chunk, dict) or chunk.get("table") not in tables:
            continue
        relative = chunk.get("path")
        if not isinstance(relative, str):
            raise AtlasExportError("catalog chunk path must be a string")
        path = (catalog / relative).resolve()
        if not path.is_relative_to(catalog.resolve()):
            raise AtlasExportError("catalog chunk escapes catalog directory")
        if _sha256(path) != chunk.get("sha256"):
            raise AtlasExportError(f"catalog chunk hash mismatch: {relative}")
        try:
            rows = json.loads(gzip.decompress(path.read_bytes()))
        except (OSError, gzip.BadGzipFile, json.JSONDecodeError) as error:
            raise AtlasExportError(f"invalid catalog chunk: {relative}") from error
        if not isinstance(rows, list) or len(rows) != chunk.get("rows"):
            raise AtlasExportError(f"catalog chunk row count mismatch: {relative}")
        if not all(isinstance(row, dict) for row in rows):
            raise AtlasExportError(f"catalog chunk rows must be objects: {relative}")
        tables[chunk["table"]].extend(rows)

    expected = manifest.get("counts", {})
    for table, rows in tables.items():
        if expected.get(table) != len(rows):
            raise AtlasExportError(f"catalog {table} count does not match manifest")
    return manifest, tables["groups"], tables["securities"], tables["quality_findings"], catalog_hash


def _group_projection(groups: list[dict[str, Any]], securities: list[dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    source_group_ids: set[str] = set()
    for group in groups:
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or _is_browser_blank(group_id):
            raise AtlasExportError("catalog group_id must be a nonempty string")
        if group_id in source_group_ids:
            raise AtlasExportError(f"duplicate catalog group_id: {group_id}")
        source_group_ids.add(group_id)
        parent_id = group.get("parent_id")
        if parent_id is not None and (not isinstance(parent_id, str) or _is_browser_blank(parent_id)):
            raise AtlasExportError("catalog parent_id must be a nonempty string or null")
    groups_by_id = {group["group_id"]: group for group in groups}
    for group in groups:
        parent_id = group.get("parent_id")
        if parent_id is not None and parent_id not in groups_by_id:
            raise AtlasExportError(f"unresolved catalog parent_id: {parent_id}")
    roots = [group for group in groups if not group["group_id"].startswith("official:") and not group.get("parent_id")]
    result = []
    for group in roots:
        for field in ("group_id", "label"):
            value = group.get(field)
            if not isinstance(value, str) or _is_browser_blank(value):
                raise AtlasExportError(f"catalog root group {field} must be a nonempty string")
        result.append({"id": group["group_id"], "label": group["label"]})
    root_ids = {group["id"] for group in result}
    fallback_ids: dict[str, str] = {}
    memberships: dict[str, list[str]] = {}

    for security in securities:
        resolved: list[str] = []
        group_ids = security.get("group_ids", [])
        if not isinstance(group_ids, list) or any(not isinstance(group_id, str) or _is_browser_blank(group_id) for group_id in group_ids):
            raise AtlasExportError("security group_ids must be an array of nonempty strings")
        for group_id in group_ids:
            if group_id not in groups_by_id:
                raise AtlasExportError(f"unresolved security group_id: {group_id}")
            current = group_id
            seen: set[str] = set()
            while current in groups_by_id and groups_by_id[current].get("parent_id"):
                if current in seen:
                    raise AtlasExportError(f"catalog group parent cycle at {current}")
                seen.add(current)
                current = groups_by_id[current]["parent_id"]
            if current in root_ids and current not in resolved:
                resolved.append(current)
        if not resolved:
            industry = security.get("official_industry")
            industry = industry if isinstance(industry, str) and not _is_browser_blank(industry) else None
            label = industry if industry is not None else "分類待補"
            group_id = fallback_ids.get(label)
            if group_id is None:
                group_id = "official-industry:" + (industry if industry is not None else "unknown")
                fallback_ids[label] = group_id
                result.append({"id": group_id, "label": label})
            resolved.append(group_id)
        memberships[str(security["security_id"])] = resolved
    display_ids: set[str] = set()
    for group in result:
        if _is_browser_blank(group["id"]) or _is_browser_blank(group["label"]):
            raise AtlasExportError("display group id and label must be nonempty strings")
        if group["id"] in display_ids:
            raise AtlasExportError(f"duplicate display group id: {group['id']}")
        display_ids.add(group["id"])
    return result, memberships


def _load_prices(source_root: Path) -> pd.DataFrame:
    price_path = source_root / "price_daily.parquet"
    if not price_path.is_file():
        raise AtlasExportError(f"required price source missing: {price_path}")
    frame = pd.read_parquet(
        price_path,
        columns=["Code", "Date", "Close", "Source"],
        filters=[("Date", ">=", pd.Timestamp(WINDOW_START)), ("Date", "<=", pd.Timestamp(WINDOW_END)), ("Source", "==", "official")],
    )
    frame["Code"] = frame["Code"].astype(str)
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.normalize()
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    return frame


def _reject_actions_wal(source_root: Path) -> None:
    wal_path = source_root / "corporate_actions.sqlite-wal"
    if wal_path.exists():
        LOGGER.warning("Rejecting corporate-actions source with WAL sidecar: %s", wal_path)
        raise AtlasExportError(
            f"corporate-actions WAL sidecar prevents a main-file-bound export: {wal_path}; "
            "the exporter cannot checkpoint or modify source data; provide a stable checkpointed source"
        )


def _load_actions(source_root: Path, codes: set[str]) -> pd.DataFrame:
    actions_path = source_root / "corporate_actions.sqlite"
    if not actions_path.is_file():
        raise AtlasExportError(f"required corporate-actions source missing: {actions_path}")
    _reject_actions_wal(source_root)
    # Bind reads to the hashed main database even if a sidecar appears between
    # the guards. Immutable mode never incorporates unbound WAL transactions.
    connection = sqlite3.connect(f"{actions_path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        frame = pd.read_sql_query(
            "SELECT code, ex_date, event_type, price_factor FROM corporate_actions WHERE ex_date >= ? AND ex_date <= ?",
            connection,
            params=[WINDOW_START, WINDOW_END],
        )
    finally:
        connection.close()
    _reject_actions_wal(source_root)
    frame["code"] = frame["code"].astype(str)
    frame = frame.loc[frame["code"].isin(sorted(codes))].copy()
    frame["ex_date"] = pd.to_datetime(frame["ex_date"]).dt.normalize()
    frame["price_factor"] = pd.to_numeric(frame["price_factor"], errors="coerce")
    return frame


def _adjusted_values(rows: pd.DataFrame, actions: pd.DataFrame) -> dict[str, tuple[float, float]]:
    values: dict[str, tuple[float, float]] = {}
    clean = rows.sort_values("Date", kind="stable").drop_duplicates("Date", keep="first")
    usable = actions.loc[
        actions["event_type"].isin(sorted(PERMANENT_FACTOR_EVENTS))
        & actions["price_factor"].map(lambda item: pd.notna(item) and math.isfinite(float(item)) and float(item) > 0)
    ].sort_values("ex_date", ascending=False, kind="stable")
    action_rows = list(usable[["ex_date", "price_factor"]].itertuples(index=False, name=None))
    action_index = 0
    factor = 1.0
    ordered_rows = list(clean[["Date", "Close"]].itertuples(index=False, name=None))
    for timestamp, close in reversed(ordered_rows):
        while action_index < len(action_rows) and action_rows[action_index][0] > timestamp:
            factor *= float(action_rows[action_index][1])
            action_index += 1
        if pd.notna(close) and math.isfinite(float(close)) and float(close) > 0:
            values[timestamp.strftime("%Y-%m-%d")] = (float(close), round(float(close) * factor, 4))
    return values


def _source_identities(manifest: dict[str, Any], source_root: Path) -> dict[str, str]:
    identities = manifest.get("input_identities_sha256")
    if not isinstance(identities, dict):
        raise AtlasExportError("catalog lacks input source identities")
    _reject_actions_wal(source_root)
    actual = {"price": _sha256(source_root / "price_daily.parquet"), "actions": _sha256(source_root / "corporate_actions.sqlite")}
    _reject_actions_wal(source_root)
    for name, value in actual.items():
        if identities.get(name) != value:
            raise AtlasExportError(f"{name} source hash differs from catalog manifest")
    return actual


def _is_browser_blank(value: str) -> bool:
    return not value.strip(ECMASCRIPT_TRIM_CHARACTERS)


def _quality_findings_by_security(findings: list[dict[str, Any]], securities: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    security_id_by_code = {security["code"]: security["security_id"] for security in securities}
    result: dict[str, list[dict[str, str]]] = {security["security_id"]: [] for security in securities}
    for finding in findings:
        day, kind = finding.get("date"), finding.get("reason")
        if day is None:
            continue
        try:
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                raise ValueError("noncanonical date")
        except ValueError as error:
            raise AtlasExportError("dated quality finding requires a canonical Gregorian YYYY-MM-DD date") from error
        if not isinstance(kind, str) or _is_browser_blank(kind):
            raise AtlasExportError("dated quality finding requires a nonempty reason")
        security_id = finding.get("security_id")
        if security_id is not None:
            if not isinstance(security_id, str) or _is_browser_blank(security_id):
                raise AtlasExportError("dated quality finding security_id must be a nonempty string")
            if security_id not in result:
                raise AtlasExportError(f"dated quality finding references unknown security_id: {security_id}")
        code = finding.get("code")
        if code is not None:
            if not isinstance(code, str) or _is_browser_blank(code):
                raise AtlasExportError("dated quality finding code must be a nonempty string")
            if code not in security_id_by_code:
                raise AtlasExportError(f"dated quality finding references unknown code: {code}")
            code_security_id = security_id_by_code[code]
            if security_id is not None and security_id != code_security_id:
                raise AtlasExportError("dated quality finding identities refer to different securities")
            security_id = code_security_id
        if security_id is None:
            raise AtlasExportError("dated quality finding requires a security identity")
        result[security_id].append({"date": day, "kind": kind})
    for values in result.values():
        values.sort(key=lambda item: (item["date"], item["kind"]))
    return result


def _classification_as_of(manifest: dict[str, Any]) -> str:
    value = manifest.get("classification_fetched_at")
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value):
            raise ValueError("missing or malformed timestamp")
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None or date.fromisoformat(value[:10]).isoformat() != value[:10]:
            raise ValueError("noncanonical date or missing timezone")
    except ValueError as error:
        raise AtlasExportError("classification_fetched_at requires a complete ISO timestamp with timezone and canonical Gregorian date") from error
    return value[:10]


def build_market_atlas(catalog: Path, source_root: Path, output: Path) -> dict[str, Any]:
    """Build the immutable presentation projection without changing source inputs."""
    catalog, source_root, output = catalog.resolve(), source_root.resolve(), output.resolve()
    if output.is_relative_to(source_root) or output.is_relative_to(catalog):
        raise AtlasExportError("output must not be written inside the catalog or read-only source root")

    manifest, groups, securities, findings, catalog_hash = _load_catalog(catalog)
    code_set: set[str] = set()
    security_ids: set[str] = set()
    for security in securities:
        security_id = security.get("security_id")
        if not isinstance(security_id, str) or _is_browser_blank(security_id):
            raise AtlasExportError("security_id must be a nonempty string")
        if security_id in security_ids:
            raise AtlasExportError(f"duplicate security_id: {security_id}")
        security_ids.add(security_id)
        code = security.get("code")
        if not isinstance(code, str) or _is_browser_blank(code):
            raise AtlasExportError("security code must be a nonempty string")
        if code in code_set:
            raise AtlasExportError(f"duplicate security code: {code}")
        code_set.add(code)
    classification_as_of = _classification_as_of(manifest)
    findings_by_security = _quality_findings_by_security(findings, securities)
    LOGGER.debug("Validated atlas metadata: classification date %s, %d quality findings", classification_as_of, len(findings))
    identities = _source_identities(manifest, source_root)
    display_groups, memberships = _group_projection(groups, securities)
    prices = _load_prices(source_root)
    dates = sorted(prices["Date"].dt.strftime("%Y-%m-%d").unique().tolist())
    if not dates:
        raise AtlasExportError(f"official price calendar is empty in {WINDOW_START} through {WINDOW_END}")
    actions = _load_actions(source_root, code_set)
    by_code = {str(code): frame for code, frame in prices.loc[prices["Code"].isin(sorted(code_set))].groupby("Code", sort=False)}
    actions_by_code: dict[str, pd.DataFrame] = {str(code): frame for code, frame in actions.groupby("code", sort=False)}
    stocks = []
    for security in securities:
        code = security["code"]
        name = security.get("name")
        if name is not None and not isinstance(name, str):
            raise AtlasExportError(f"security name must be a string or null: {code}")
        display_name = name if isinstance(name, str) and not _is_browser_blank(name) else code
        security_actions = actions_by_code.get(code)
        if security_actions is None:
            security_actions = pd.DataFrame(columns=actions.columns)
        values = _adjusted_values(by_code.get(code, prices.iloc[0:0]), security_actions)
        raw = [values.get(day, (None, None))[0] for day in dates]
        adjusted = [values.get(day, (None, None))[1] for day in dates]
        stocks.append({
            "code": code,
            "name": display_name,
            "groupIds": memberships[str(security["security_id"])],
            "quality": [],
            "qualityFindings": findings_by_security[str(security["security_id"])],
            "coverage": {
                "catalogStatus": security.get("coverage_status"),
                "priceStatus": security.get("price_coverage_status"),
                "reason": security.get("coverage_reason"),
            },
            "raw": raw,
            "adjusted": adjusted,
        })

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "catalogHash": catalog_hash,
        "classificationAsOf": classification_as_of,
        "dates": dates,
        "groups": display_groups,
        "stocks": stocks,
        "provenance": {
            "catalogManifestSchema": manifest.get("schema_version"),
            "catalogManifestCanonicalSha256": catalog_hash,
            "catalogCompletionReceipt": "completion-receipt.json",
            "sourceRoot": str(source_root),
            "sourceIdentitiesSha256": identities,
            "sourceIdentityReference": {name: manifest["input_identities_sha256"][name] for name in identities},
            "sourceQuotePolicy": "official daily quotes only; calendar is their date union",
            "rawDefinition": "official price_daily.parquet Close, unadjusted",
            "splitAdjustedDefinition": "Raw Close multiplied by subsequent valid permanent corporate-action price factors; cash dividends are not reinvested",
        },
        "limitations": [
            "No historical market capitalization is included because this projection has no trustworthy source for it.",
            "The 2019-01-02 window start does not provide a common prior 252-trading-day price history for every security.",
            "Missing official quotes remain null and are never forward-filled.",
            "Classification is retrospective as recorded by the catalog, not a historical point-in-time membership claim.",
        ],
    }
    identities = _source_identities(manifest, source_root)
    payload["provenance"]["sourceIdentitiesSha256"] = identities
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(encoded)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = build_market_atlas(args.catalog, args.source_root, args.output)
    sys.stdout.write(
        json.dumps(
            {"schema": payload["schema"], "dates": len(payload["dates"]), "stocks": len(payload["stocks"]), "output": str(args.output)}, ensure_ascii=False
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
