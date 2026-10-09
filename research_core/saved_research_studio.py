"""Versioned, read-only presentation of saved account evidence; never run a strategy.

Prices and order metadata must be verified against the saved run's SHA-256 sources.
Accounting uses the original ledger marks, including claims and receivables. Missing
relationships stay unknown rather than being assigned to the most recent trade.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import logging
import math
import re
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from threading import Lock, local
from typing import Any, Callable, TypedDict

from research_core.evidence import EvidenceError, finite_json, read_json, task_catalog, validate_registry, validate_result

logger = logging.getLogger(__name__)
SCHEMA = "saved-research-studio.v1"
TRANSPORT_SCHEMA = "saved-research-studio-manifest.v1"
MAX_PART_BYTES = 450 * 1024
MAX_TRANSPORT_BYTES = 128 * 1024 * 1024
MAX_PACKAGE_JSON_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PARTS = 512
MONEY_TOLERANCE = 1e-6
RANK_MISSING = "依規則應退出，但沒有保存當日排名，無法逐筆確認。"
CAPTURE_MISSING = "尚未連接與飆股地圖相同規則的逐日判定。"
EXPOSURE_WEIGHT_KEYS = ("runawayWeight", "otherStockWeight", "unknownStockWeight", "otherAssetsWeight", "cashWeight")


class StudioError(ValueError):
    """Unavailable or inconsistent saved evidence; never a strategy verdict."""


class StudioNotFound(StudioError):
    """The verified package has no requested run, trade, or account date."""


class TransportPart(TypedDict):
    basename: str
    bytes: int
    sha256: str


def valid_day(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise StudioError("expected YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise StudioError("invalid calendar date") from error
    return value


def _day(value: str) -> str:
    return valid_day(value[:10])


def _money(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise StudioError("money must be a finite number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise StudioError("money must be finite")
    return result


def _sum_money(values: Any) -> float:
    return float(sum((_money(value) for value in values), Decimal(0)))


def _path_key(value: str | Path) -> str:
    return str(value).replace("\\", "/").casefold()


def _security_name(value: Any) -> str | None:
    """Missing source labels stay missing rather than becoming 'None' or 'nan'."""
    if not isinstance(value, str):
        return None
    result = value.strip()
    return result if result and result.casefold() not in {"none", "null", "nan", "nat", "<na>"} else None


def _capture_display_name(row: dict[str, Any], status: dict[str, Any] | None) -> None:
    """Supplement only code labels, using the verified provider's catalog identity."""
    if status is None or row["name"] != row["code"]:
        return
    name = _security_name(status.get("name"))
    catalog_id = status.get("catalogId")
    if name is None or name == row["code"] or _security_name(catalog_id) is None:
        return
    row.update({
        "name": name,
        "nameSourceId": f"security-name-catalog:{catalog_id}",
        "nameBasis": "catalog-snapshot-display-name-not-historical-classification",
    })


def _complete_exposure(row: dict[str, Any]) -> bool:
    """Same complete-date criterion as the allocation renderer; zero is evidence."""
    return row.get("known") is True and all(
        isinstance(row.get(key), (int, float)) and not isinstance(row[key], bool) and math.isfinite(row[key]) for key in EXPOSURE_WEIGHT_KEYS
    )


def _capture_coverage(run: dict[str, Any], exposure: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in run["positions"] if trade["closeDate"] is not None]
    captured = sum(trade["capture"]["days"] is not None and trade["capture"]["days"] > 0 for trade in closed)
    not_captured = sum(
        trade["capture"]["days"] == 0 and trade["capture"]["totalDays"] > 0 and trade["capture"]["knownDays"] == trade["capture"]["totalDays"]
        for trade in closed
    )
    complete = [row for row in exposure if _complete_exposure(row)]
    return {
        "closedTradeTotal": len(closed),
        "confirmedCapturedClosedTradeCount": captured,
        "confirmedNotCapturedClosedTradeCount": not_captured,
        "undeterminedClosedTradeCount": len(closed) - captured - not_captured,
        "completeExposureDays": len(complete),
        "totalExposureDays": len(exposure),
        "knownDayAverageWeight": math.fsum(row["runawayWeight"] for row in complete) / len(complete) if complete else None,
    }


def read_verified(path: Path, expected_hash: str) -> bytes:
    raw = path.read_bytes()
    measured = hashlib.sha256(raw).hexdigest()
    if measured != expected_hash:
        logger.error("saved studio source mismatch: %s", path)
        raise StudioError(f"source SHA-256 mismatch: {path}")
    logger.debug("verified saved source %s (%s)", path, measured)
    return raw


def _bounded_bytes(path: Path, maximum: int) -> bytes:
    if path.stat().st_size > maximum:
        raise StudioError("presentation transport file exceeds its bounded size")
    with path.open("rb") as source:
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        raise StudioError("presentation transport file exceeds its bounded size")
    return raw


def _part_basename(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", value):
        raise StudioError("transport part must have a safe basename")
    if value.endswith("."):
        raise StudioError("transport part must not use a Windows trailing-dot alias")
    if re.match(r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", value):
        raise StudioError("transport part uses a reserved Windows basename")
    return value


def _transport_size(value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise StudioError("invalid or oversized declared transport bytes")
    return value


def _transport_hash(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value):
        raise StudioError("invalid transport SHA-256")
    return value.casefold()


def _read_split_gzip(manifest: dict[str, Any], manifest_path: Path) -> bytes:
    if manifest.get("schema") != TRANSPORT_SCHEMA or manifest.get("contentSchema") != SCHEMA or manifest.get("compression") != "gzip":
        raise StudioError("unsupported presentation transport manifest")
    total = _transport_size(manifest.get("bytes"), MAX_TRANSPORT_BYTES)
    whole_sha = _transport_hash(manifest.get("sha256"))
    parts = manifest.get("parts")
    if not isinstance(parts, list) or not 0 < len(parts) <= MAX_PARTS:
        raise StudioError("invalid transport part count")
    declared = []
    seen = set()
    for part in parts:
        if not isinstance(part, dict):
            raise StudioError("invalid transport part record")
        basename = _part_basename(part.get("basename"))
        if basename.casefold() in seen:
            raise StudioError("duplicate transport part basename")
        seen.add(basename.casefold())
        declared.append((basename, _transport_size(part.get("bytes"), MAX_PART_BYTES), _transport_hash(part.get("sha256"))))
    if sum(size for _, size, _ in declared) != total:
        raise StudioError("transport part sizes disagree with whole gzip bytes")
    root = manifest_path.parent.resolve()
    chunks = []
    for basename, size, sha in declared:
        path = root / basename
        if path.is_symlink() or path.resolve().parent != root:
            raise StudioError("transport part escapes manifest directory")
        raw = _bounded_bytes(path, MAX_PART_BYTES)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
            raise StudioError("transport part bytes/SHA-256 mismatch")
        chunks.append(raw)
    payload = b"".join(chunks)
    if len(payload) != total or hashlib.sha256(payload).hexdigest() != whole_sha:
        raise StudioError("whole transport gzip bytes/SHA-256 mismatch")
    logger.info("verified saved studio transport: %d parts, %d gzip bytes", len(parts), total)
    return payload


def _package_field(row: dict[str, Any], key: str, label: str) -> Any:
    if key not in row:
        raise StudioError(f"missing package field: {label}.{key}")
    return row[key]


def _package_text(value: Any, label: str, *, nullable: bool = False, allow_empty: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise StudioError(f"package field must be a nonempty string: {label}")


def _package_number(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudioError(f"package field must be a finite number: {label}")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise StudioError(f"package number exceeds finite numeric range: {label}") from error
    if not finite:
        raise StudioError(f"package field must be a finite number: {label}")


def _package_bool(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, bool):
        raise StudioError(f"package field must be a boolean: {label}")


def _package_date(row: dict[str, Any], key: str, label: str, *, nullable: bool = False) -> None:
    value = _package_field(row, key, label)
    if nullable and value is None:
        return
    _package_text(value, f"{label}.{key}")
    valid_day(value)


def _package_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise StudioError(f"package field must be an array: {label}")
    return value


def _package_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StudioError(f"package field must be an object: {label}")
    return value


def _package_strings(value: Any, label: str) -> None:
    for item in _package_array(value, label):
        _package_text(item, label)


def _package_records(value: Any, label: str, identity: str | None = None) -> list[dict[str, Any]]:
    rows = []
    seen: set[str] = set()
    for index, value in enumerate(_package_array(value, label)):
        row = _package_object(value, f"{label}[{index}]")
        if identity is not None:
            key = _package_field(row, identity, label)
            _package_text(key, f"{label}.{identity}")
            if key in seen:
                raise StudioError(f"duplicate package identity: {label}.{identity}")
            seen.add(key)
        rows.append(row)
    return rows


def _validate_package_trade(trade: dict[str, Any]) -> None:
    label = "run.positions"
    for key in ("code", "name", "whySell", "formula"):
        _package_text(_package_field(trade, key, label), f"{label}.{key}")
    for key in ("cost", "inflow", "quantityEnd", "remainingCost", "days"):
        _package_number(_package_field(trade, key, label), f"{label}.{key}")
    for key in ("mark", "markPrice", "pnl", "realizedPnl", "unrealizedPnl", "return"):
        _package_number(_package_field(trade, key, label), f"{label}.{key}", nullable=True)
    for key in ("nameSourceId", "nameBasis"):
        if key in trade:
            _package_text(trade[key], f"{label}.{key}", nullable=key == "nameSourceId")
    _package_date(trade, "openDate", label)
    _package_date(trade, "closeDate", label, nullable=True)
    _package_strings(_package_field(trade, "missingReasons", label), f"{label}.missingReasons")
    capture = _package_object(_package_field(trade, "capture", label), f"{label}.capture")
    for key in ("knownDays", "totalDays"):
        _package_number(_package_field(capture, key, label), f"{label}.capture.{key}")
    for key in ("days", "bestMetric"):
        _package_number(_package_field(capture, key, label), f"{label}.capture.{key}", nullable=True)
    _package_text(_package_field(capture, "missingReason", label), f"{label}.capture.missingReason", nullable=True)
    for fill in _package_records(_package_field(trade, "fills", label), f"{label}.fills", "id"):
        _package_date(fill, "date", f"{label}.fills")
        _validate_package_fill(fill)
    for candle in _package_records(_package_field(trade, "candles", label), f"{label}.candles", "date"):
        _package_date(candle, "date", f"{label}.candles")
        for key in ("open", "high", "low", "close"):
            _package_number(_package_field(candle, key, label), f"{label}.candles.{key}", nullable=True)
        _package_text(_package_field(candle, "sourceId", label), f"{label}.candles.sourceId")
        if "name" in candle:
            _package_text(candle["name"], f"{label}.candles.name", nullable=True, allow_empty=True)
    if "pendingAssets" in trade:
        for asset in _package_records(trade["pendingAssets"], f"{label}.pendingAssets", "entitlementId"):
            _package_date(asset, "date", f"{label}.pendingAssets")
            for key in ("action", "eventId"):
                _package_text(_package_field(asset, key, label), f"{label}.pendingAssets.{key}")
            for key in ("amount", "qualifiedQuantity"):
                _package_number(_package_field(asset, key, label), f"{label}.pendingAssets.{key}", nullable=True)


def _validate_package_fill(fill: dict[str, Any]) -> None:
    label = "run.positions.fills"
    for key in ("timestamp", "action", "rankMissingReason"):
        _package_text(_package_field(fill, key, label), f"{label}.{key}")
    if _package_field(fill, "kind", label) not in ("entry", "add", "retry", "sell", "corporate-action", "unknown"):
        raise StudioError("invalid package fill kind")
    for key in ("quantity", "price", "cashFlow", "fee", "tax", "penalty", "dailyRank", "dayOpen", "dayClose"):
        _package_number(_package_field(fill, key, label), f"{label}.{key}", nullable=True)
    _package_date(fill, "decisionDate", label, nullable=True)
    _package_text(_package_field(fill, "orderId", label), f"{label}.orderId", nullable=True)
    _package_bool(_package_field(fill, "retry", label), f"{label}.retry")
    _package_object(_package_field(fill, "original", label), f"{label}.original")
    candidates = _package_field(fill, "entryCandidates", label)
    if candidates is not None:
        for candidate in _package_records(candidates, f"{label}.entryCandidates", "code"):
            _package_text(_package_field(candidate, "affordability", label), f"{label}.entryCandidates.affordability")
    if fill.get("addSignal") is not None:
        signal = _package_object(fill["addSignal"], f"{label}.addSignal")
        _package_number(_package_field(signal, "economicReturn", label), f"{label}.addSignal.economicReturn", nullable=True)
        for key in ("reason", "orderId"):
            _package_text(_package_field(signal, key, label), f"{label}.addSignal.{key}", nullable=True)
        _package_object(_package_field(signal, "original", label), f"{label}.addSignal.original")


def _validate_package_account(account: dict[str, Any]) -> None:
    label = "run.accounts"
    _package_date(account, "date", label)
    _package_text(_package_field(account, "timestamp", label), f"{label}.timestamp")
    for key in ("cash", "recordedEquity"):
        _package_number(_package_field(account, key, label), f"{label}.{key}")
    for key in ("otherAssets", "reconstructedEquity", "difference"):
        _package_number(_package_field(account, key, label), f"{label}.{key}", nullable=True)
    _package_bool(_package_field(account, "verified", label), f"{label}.verified")
    _package_strings(_package_field(account, "reasons", label), f"{label}.reasons")
    for key in ("receivables", "shareClaims"):
        _package_array(_package_field(account, key, label), f"{label}.{key}")
    for holding in _package_records(_package_field(account, "holdings", label), f"{label}.holdings", "code"):
        _package_text(_package_field(holding, "name", label), f"{label}.holdings.name")
        _package_number(_package_field(holding, "quantity", label), f"{label}.holdings.quantity")
        for key in ("price", "marketValue"):
            _package_number(_package_field(holding, key, label), f"{label}.holdings.{key}", nullable=True)
        _package_bool(_package_field(holding, "onMap", label), f"{label}.holdings.onMap", nullable=True)
        _package_bool(_package_field(holding, "modeled", label), f"{label}.holdings.modeled", nullable=True)
        for key in ("sourceId", "observedAt", "availableAt", "missingReason"):
            _package_text(_package_field(holding, key, label), f"{label}.holdings.{key}", nullable=True)
        for key in ("nameSourceId", "nameBasis"):
            if key in holding:
                _package_text(holding[key], f"{label}.holdings.{key}", nullable=key == "nameSourceId")


def _validate_package_period(period: Any, label: str, duration_key: str) -> None:
    row = _package_object(period, label)
    _package_number(_package_field(row, duration_key, label), f"{label}.{duration_key}")
    for key in ("from", "until"):
        _package_date(row, key, label, nullable=True)


def _validate_package_statistics(stats: dict[str, Any]) -> None:
    label = "run.statistics"
    _package_number(_package_field(stats, "maxDrawdown", label), f"{label}.maxDrawdown")
    _validate_package_period(_package_field(stats, "longestUnderwater", label), f"{label}.longestUnderwater", "days")
    losing = _package_field(stats, "longestLosingStreak", label)
    _validate_package_period(losing, f"{label}.longestLosingStreak", "count")
    _package_number(_package_field(losing, "pnl", label), f"{label}.longestLosingStreak.pnl")
    for key in ("winRate", "meanGain", "meanLoss", "topFiveProfitShare"):
        _package_number(_package_field(stats, key, label), f"{label}.{key}", nullable=True)
    _package_text(_package_field(stats, "topFiveShareDefinition", label), f"{label}.topFiveShareDefinition")
    for month in _package_records(_package_field(stats, "monthlyReturns", label), f"{label}.monthlyReturns", "month"):
        valid_day(f"{month['month']}-01")
        _package_number(_package_field(month, "return", label), f"{label}.monthlyReturns.return")
    for bucket in _package_records(_package_field(stats, "histogram", label), f"{label}.histogram"):
        for key in ("from", "until"):
            _package_number(_package_field(bucket, key, label), f"{label}.histogram.{key}", nullable=True)
        _package_number(_package_field(bucket, "count", label), f"{label}.histogram.count")


def _validate_package_run(run: dict[str, Any]) -> None:
    for key in ("name", "plainTitle", "plainIdea", "studyStatus"):
        _package_text(_package_field(run, key, "run"), f"run.{key}")
    for key in ("from", "through"):
        _package_date(run, key, "run")
    for key in ("initialCapital", "finalEquity", "netReturn", "costs", "maxDrawdown", "closedTradeCount"):
        _package_number(_package_field(run, key, "run"), f"run.{key}")
    for key in ("winRate", "capturedClosedTradeCount", "captureAvgWeight"):
        _package_number(_package_field(run, key, "run"), f"run.{key}", nullable=True)
    _package_bool(_package_field(run, "ownerAdopted", "run"), "run.ownerAdopted", nullable=True)
    dates = _package_array(_package_field(run, "accountDates", "run"), "run.accountDates")
    seen: set[str] = set()
    for day in dates:
        _package_text(day, "run.accountDates")
        valid_day(day)
        if day in seen:
            raise StudioError("duplicate package identity: run.accountDates")
        seen.add(day)
    _package_strings(_package_field(run, "limitations", "run"), "run.limitations")
    _package_strings(_package_field(run, "sourceIds", "run"), "run.sourceIds")
    _validate_package_period(_package_field(run, "longestUnderwater", "run"), "run.longestUnderwater", "days")
    stats = _package_object(_package_field(run, "statistics", "run"), "run.statistics")
    _validate_package_statistics(stats)
    method = _package_object(_package_field(run, "method", "run"), "run.method")
    _package_strings(_package_field(method, "rules", "run.method"), "run.method.rules")
    _package_text(_package_field(method, "conclusion", "run.method"), "run.method.conclusion", allow_empty=True)
    benchmark = _package_object(_package_field(run, "benchmark", "run"), "run.benchmark")
    for key in ("code", "label", "basis"):
        _package_text(_package_field(benchmark, key, "run.benchmark"), f"run.benchmark.{key}")
    _package_text(_package_field(benchmark, "missingReason", "run.benchmark"), "run.benchmark.missingReason", nullable=True)
    reconciliation = _package_object(_package_field(run, "reconciliation", "run"), "run.reconciliation")
    for key in ("closedPnl", "accountIncrease"):
        _package_number(_package_field(reconciliation, key, "run.reconciliation"), f"run.reconciliation.{key}")
    for key in ("openPnl", "otherAssets", "totalPnl", "difference"):
        _package_number(_package_field(reconciliation, key, "run.reconciliation"), f"run.reconciliation.{key}", nullable=True)
    _package_bool(_package_field(reconciliation, "verified", "run.reconciliation"), "run.reconciliation.verified")
    _package_strings(_package_field(reconciliation, "reasons", "run.reconciliation"), "run.reconciliation.reasons")
    for point in _package_records(_package_field(run, "nav", "run"), "run.nav", "date"):
        _package_date(point, "date", "run.nav")
        _package_number(_package_field(point, "equity", "run.nav"), "run.nav.equity")
        _package_number(_package_field(point, "benchmarkEquity", "run.nav"), "run.nav.benchmarkEquity", nullable=True)
        _package_number(_package_field(point, "drawdown", "run.nav"), "run.nav.drawdown")
    for trade in _package_records(_package_field(run, "positions", "run"), "run.positions", "id"):
        _validate_package_trade(trade)
    for account in _package_records(_package_field(run, "accounts", "run"), "run.accounts", "date"):
        _validate_package_account(account)


def _validate_studio_package(value: dict[str, Any]) -> None:
    """Check reader-required structure before caching; do not rewrite saved results."""
    for run in _package_records(_package_field(value, "runs", "package"), "package.runs", "id"):
        _validate_package_run(run)
    history = _package_object(_package_field(value, "researchHistory", "package"), "package.researchHistory")
    if history.get("schema") != "saved-research-history.v1":
        raise StudioError("unsupported saved studio history schema")
    _package_bool(_package_field(history, "historyComplete", "history"), "history.historyComplete")
    for item in _package_records(_package_field(history, "items", "history"), "history.items", "id"):
        _package_date(item, "date", "history.items")
        for key in ("title", "status", "evidenceState"):
            _package_text(_package_field(item, key, "history.items"), f"history.items.{key}")
        for key in ("conclusion", "originalSummary"):
            _package_text(_package_field(item, key, "history.items"), f"history.items.{key}", allow_empty=True)
        _package_text(_package_field(item, "reportPath", "history.items"), "history.items.reportPath", nullable=True)
        _package_bool(_package_field(item, "reviewConfirmed", "history.items"), "history.items.reviewConfirmed")
        _package_strings(_package_field(item, "registryEventIds", "history.items"), "history.items.registryEventIds")
        for key in ("outcome", "draftStatus", "sourceNote"):
            if key in item:
                _package_text(item[key], f"history.items.{key}", nullable=True, allow_empty=True)
        for key in ("dateBasis", "summarySource"):
            if key in item:
                _package_text(item[key], f"history.items.{key}")


def read_studio_package(path: Path) -> dict[str, Any]:
    """Verify parts before decompression, while preserving legacy one-file readers."""
    value: Any = None
    if path.suffix == ".gz":
        raw = _bounded_bytes(path, MAX_TRANSPORT_BYTES)
        compressed = True
    else:
        maximum = MAX_MANIFEST_BYTES if path.name.endswith(".manifest.json") else MAX_PACKAGE_JSON_BYTES
        raw = _bounded_bytes(path, maximum)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise StudioError("invalid presentation package JSON") from error
        if isinstance(value, dict) and value.get("schema") == TRANSPORT_SCHEMA:
            if len(raw) > MAX_MANIFEST_BYTES:
                raise StudioError("transport manifest exceeds its bounded size")
            raw = _read_split_gzip(value, path)
            compressed = True
        else:
            compressed = False
    if compressed:
        try:
            with gzip.GzipFile(fileobj=BytesIO(raw)) as source:
                decoded = source.read(MAX_PACKAGE_JSON_BYTES + 1)
            if len(decoded) > MAX_PACKAGE_JSON_BYTES:
                raise StudioError("decompressed presentation package exceeds its bounded size")
            value = json.loads(decoded)
        except (OSError, EOFError, ValueError, UnicodeError) as error:
            if isinstance(error, StudioError):
                raise
            raise StudioError("invalid presentation package gzip/JSON") from error
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise StudioError("unsupported saved studio schema")
    try:
        finite_json(value)
    except EvidenceError as error:
        raise StudioError("invalid presentation package values") from error
    _validate_studio_package(value)
    return value


def write_split_package(payload: bytes, manifest_path: Path) -> dict[str, Any]:
    """Split the same gzip bytes; create all parts exclusively and publish manifest last."""
    if manifest_path.suffix.casefold() != ".json":
        raise StudioError("split transport manifest output must use a .json suffix")
    _transport_size(len(payload), MAX_TRANSPORT_BYTES)
    if not payload.startswith(b"\x1f\x8b"):
        raise StudioError("split transport requires gzip bytes")
    prefix = manifest_path.stem.removesuffix(".manifest")
    parts: list[TransportPart] = []
    chunks = [payload[offset : offset + MAX_PART_BYTES] for offset in range(0, len(payload), MAX_PART_BYTES)]
    if len(chunks) > MAX_PARTS:
        raise StudioError("split transport exceeds maximum part count")
    for index, raw in enumerate(chunks):
        basename = _part_basename(f"{prefix}.part-{index:05d}.bin")
        parts.append({"basename": basename, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "schema": TRANSPORT_SCHEMA,
        "contentSchema": SCHEMA,
        "compression": "gzip",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "parts": parts,
    }
    manifest_raw = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(manifest_raw) > MAX_MANIFEST_BYTES:
        raise StudioError("split manifest exceeds maximum bytes")
    targets = [manifest_path, *(manifest_path.parent / part["basename"] for part in parts)]
    if any(path.exists() for path in targets):
        raise StudioError("split transport never overwrites existing manifests or parts")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    for part, raw in zip(parts, chunks):
        with (manifest_path.parent / part["basename"]).open("xb") as target:
            target.write(raw)
    with manifest_path.open("xb") as target:
        target.write(manifest_raw)
    return manifest


def _verified_json(path: Path, expected_hash: str) -> Any:
    value = json.loads(read_verified(path, expected_hash))
    finite_json(value)
    return value


def _fill(
    event: dict[str, Any], order: dict[str, Any] | None, traces: dict[str, dict[str, Any]], candle: dict[str, Any] | None, probe: dict[str, Any] | None = None
) -> dict[str, Any]:
    original = event["original"]
    intent = order.get("intent", {}) if order else {}
    decision = _day(intent["decision_at"]) if intent.get("decision_at") else None
    action = event["action"]
    order_id = original.get("order_id")
    retry = bool(order and order.get("lineage"))
    if action not in {"BUY", "SELL"}:
        kind = "corporate-action"
    elif action == "SELL":
        kind = "sell"
    elif not order:
        kind = "unknown"
    elif retry:
        kind = "retry"
    elif str(order_id).startswith("ADD-"):
        kind = "add"
    else:
        kind = "entry"
    decision_at = intent.get("decision_at")
    trace = traces.get(decision_at) if decision_at else None
    candidates = (
        None
        if trace is None or trace.get("unoccupied_top_five") is None
        else [{"code": row[0], "affordability": row[1]} for row in trace["unoccupied_top_five"]]
    )

    def cents(name: str) -> float | None:
        return float(_money(original[name]) / 100) if original.get(name) is not None else None

    add_signal = None
    if probe:
        ratio = probe.get("economic_return") or {}
        denominator = ratio.get("denominator")
        add_signal = {
            "economicReturn": ratio["numerator"] / denominator if denominator else None,
            "reason": probe.get("reason"),
            "orderId": probe.get("order_id"),
            "original": probe,
        }
    return {
        "id": event["id"],
        "date": _day(event["date"]),
        "timestamp": event["date"],
        "action": action,
        "quantity": event.get("quantity"),
        "price": event.get("price"),
        "cashFlow": event.get("cashFlow"),
        "fee": cents("commission_cents"),
        "tax": cents("tax_cents"),
        "penalty": cents("penalty_cents"),
        "kind": kind,
        "decisionDate": decision,
        "orderId": order_id,
        "retry": retry,
        "entryCandidates": candidates,
        "dailyRank": None,
        "rankMissingReason": RANK_MISSING,
        "dayOpen": candle.get("open") if candle else None,
        "dayClose": candle.get("close") if candle else None,
        "original": original,
        "addSignal": add_signal,
    }


def account_audit(state: dict[str, Any], recorded_equity: float) -> dict[str, Any]:
    """Verify the original ledger valuation; do not replace missing marks with zero."""
    holdings = []
    reasons: list[str] = []
    if state.get("nav_twd") is not None and abs(state["nav_twd"] - recorded_equity) > MONEY_TOLERANCE:
        reasons.append("保存帳本淨值與原回測紀錄不一致。")
    for position in state.get("tradable_positions", []):
        quality = position.get("mark_quality") or {}
        price = position.get("raw_mark_twd")
        quantity = position["quantity"]
        value = None if price is None else float(_money(price) * quantity)
        missing = None if value is not None else "原帳本沒有保存這筆持股的估值價格。"
        if missing:
            reasons.append(missing)
        declared = position.get("market_value_twd")
        if value is not None and declared is not None and abs(value - declared) > MONEY_TOLERANCE:
            reasons.append(f"{position['security_id']} 股數乘價格與保存市值不一致。")
        holdings.append({
            "code": str(position["security_id"]).removeprefix("TW:"),
            "name": str(position["security_id"]).removeprefix("TW:"),
            "quantity": quantity,
            "price": price,
            "marketValue": value,
            "sourceId": quality.get("source_id"),
            "observedAt": quality.get("observed_at"),
            "availableAt": quality.get("available_at"),
            "modeled": quality.get("modeled_mark"),
            "missingReason": missing,
            "onMap": None,
        })
    asset_fields = ("dividend_receivable_twd", "capital_return_receivable_twd", "share_claims_value_twd")
    other = None if any(state.get(key) is None for key in asset_fields) else _sum_money(state[key] for key in asset_fields)
    if other is None:
        reasons.append("應收款或未交付股權估值未完整保存。")
    total = (
        None
        if other is None or any(h["marketValue"] is None for h in holdings)
        else _sum_money([state["cash_twd"], other, *(h["marketValue"] for h in holdings)])
    )
    difference = None if total is None else float(_money(total) - _money(recorded_equity))
    if difference is not None and abs(difference) > MONEY_TOLERANCE:
        reasons.append("持股、現金與其他資產加總和原帳戶紀錄有差額。")
    return {
        "date": _day(state["date"]),
        "timestamp": state["date"],
        "cash": state["cash_twd"],
        "holdings": holdings,
        "otherAssets": other,
        "receivables": state.get("receivables", []),
        "shareClaims": state.get("share_claims", []),
        "reconstructedEquity": total,
        "recordedEquity": recorded_equity,
        "difference": difference,
        "verified": difference is not None and abs(difference) <= MONEY_TOLERANCE and not reasons,
        "reasons": reasons,
    }


def _cycles(
    run: dict[str, Any],
    orders: list[dict[str, Any]],
    entry_traces: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    candles: dict[str, list[dict[str, Any]]],
    probe_traces: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    order_by_id: dict[str, dict[str, Any]] = {}
    for source_order in orders:
        intent = source_order["intent"]
        if intent["order_id"] in order_by_id:
            raise StudioError("duplicate source order id")
        order_by_id[intent["order_id"]] = source_order
    traces = {}
    for trace in entry_traces:
        _day(trace["as_of"])
        if trace["as_of"] in traces:
            raise StudioError("duplicate saved entry trace identity")
        traces[trace["as_of"]] = trace
    probes = {}
    for trace in probe_traces:
        for probe in trace.get("adds", []):
            order_id = probe.get("order_id")
            if order_id:
                if order_id in probes:
                    raise StudioError("duplicate saved add probe order id")
                probes[order_id] = {**probe, "decision_at": trace["as_of"]}
    candle_by_code = {code: {row["date"]: row for row in rows} for code, rows in candles.items()}
    active: dict[str, dict[str, Any]] = {}
    entitlement_cycle: dict[str, dict[str, Any]] = {}
    cycles: list[dict[str, Any]] = []
    unassigned: list[str] = []
    unsupported_by_code: dict[str, list[str]] = {}
    for sequence, event in enumerate(sorted(run["events"], key=lambda event: event["date"])):
        code, action, original = event["code"], event["action"], event["original"]
        order = order_by_id.get(original.get("order_id"))
        if order and (order["intent"]["code"] != code or order["intent"]["side"] != action):
            raise StudioError("event and matched order disagree")
        if action in {"BUY", "SELL"} and order is None:
            raise StudioError(f"saved fill lacks its source order: {event['id']}")
        probe = probes.get(original.get("order_id"))
        if probe and (probe.get("code") != code or (order and probe["decision_at"] != order["intent"]["decision_at"])):
            raise StudioError("add probe and matched order disagree")
        fill = _fill(event, order, traces, candle_by_code.get(code, {}).get(_day(event["date"])), probe)
        cycle = active.get(code)
        if action == "BUY":
            if cycle is None:
                cycle = {
                    "id": f"{run['id']}:cycle:{len(cycles)}",
                    "code": code,
                    "name": code,
                    "openDate": fill["date"],
                    "closeDate": None,
                    "cost": 0,
                    "inflow": 0,
                    "remainingCost": 0,
                    "quantityEnd": 0,
                    "fills": [],
                    "missingReasons": [],
                    "pendingAssets": [],
                }
                cycles.append(cycle)
                active[code] = cycle
            cycle["quantityEnd"] += event["quantity"]
            cycle["cost"] = _sum_money([cycle["cost"], -event["cashFlow"]])
            cycle["remainingCost"] = _sum_money([cycle["remainingCost"], -event["cashFlow"]])
        elif action == "SELL":
            if cycle is None or event["quantity"] > cycle["quantityEnd"]:
                raise StudioError("sell has no sufficient saved holding")
            cycle["remainingCost"] = float(_money(cycle["remainingCost"]) * (cycle["quantityEnd"] - event["quantity"]) / cycle["quantityEnd"])
            cycle["quantityEnd"] -= event["quantity"]
            cycle["inflow"] = _sum_money([cycle["inflow"], event["cashFlow"]])
            if cycle["quantityEnd"] == 0:
                cycle["closeDate"] = fill["date"]
                cycle["closeSequence"] = sequence
                active.pop(code)
        elif action == "SPLIT":
            if cycle is None:
                unassigned.append(f"{event['id']}: 分割沒有可核對的持股關係。")
                continue
            cycle["quantityEnd"] += event["quantity"]
        elif action in {"DIVIDEND_ENTITLEMENT", "CAPITAL_RETURN_ENTITLEMENT"}:
            entitlement = original.get("entitlement_id")
            if cycle is None or not entitlement or original.get("qualified_qty") != cycle["quantityEnd"]:
                reason = f"{event['id']}: 權益資格與當時持股無法核對。"
                unassigned.append(reason)
                if cycle is not None:
                    cycle["missingReasons"].append(reason)
                continue
            entitlement_cycle[entitlement] = cycle
            cycle["pendingAssets"].append({
                "entitlementId": entitlement,
                "date": fill["date"],
                "action": action,
                "amount": original.get("amount"),
                "qualifiedQuantity": original.get("qualified_qty"),
                "eventId": event["id"],
            })
        elif action in {"DIVIDEND", "CAPITAL_RETURN"}:
            cycle = entitlement_cycle.get(original.get("entitlement_id"))
            if cycle is None or cycle["code"] != code:
                unassigned.append(f"{event['id']}: 現金權益沒有已核對的資格事件。")
                continue
            cycle["inflow"] = _sum_money([cycle["inflow"], event["cashFlow"]])
            cycle["pendingAssets"] = [asset for asset in cycle["pendingAssets"] if asset["entitlementId"] != original["entitlement_id"]]
        else:
            reason = f"{event['id']}: 此公司行動尚無交易關聯轉換規則。"
            unassigned.append(reason)
            if cycle is not None:
                cycle["missingReasons"].append(reason)
                cycle["fills"].append(fill)
            else:
                unsupported_by_code.setdefault(code, []).append(reason)
            continue
        cycle["fills"].append(fill)
    end = run["through"]
    end_holdings = {h["code"]: h for h in accounts[-1]["holdings"]} if accounts else {}
    for cycle in cycles:
        for reason in unsupported_by_code.get(cycle["code"], []):
            cycle["missingReasons"].append(f"此股另有關聯未確認的原始事件，尚未分配至本筆：{reason}")
        for asset in cycle["pendingAssets"]:
            cycle["missingReasons"].append(f"權益 {asset['entitlementId']} 尚未入帳，未計入已入帳交易損益。")
        closed = cycle["closeDate"] is not None
        mark = end_holdings.get(cycle["code"]) if not closed else None
        mark_value = 0.0 if closed else mark["marketValue"] if mark else None
        if not closed and (mark is None or mark["quantity"] != cycle["quantityEnd"]):
            cycle["missingReasons"].append("期末持股股數無法與保存帳本核對。")
            mark_value = None
        cycle["mark"] = None if closed else mark_value
        cycle["markPrice"] = mark["price"] if mark else None
        pnl = None if mark_value is None else _sum_money([cycle["inflow"], mark_value, -cycle["cost"]])
        realized = _sum_money([cycle["inflow"], -cycle["cost"], cycle["remainingCost"]])
        unrealized = None if mark_value is None else _sum_money([mark_value, -cycle["remainingCost"]])
        cycle.update({
            "pnl": pnl,
            "realizedPnl": realized,
            "unrealizedPnl": unrealized if not closed else None,
            "return": pnl / cycle["cost"] if pnl is not None and cycle["cost"] > 0 else None,
            "days": (date.fromisoformat(cycle["closeDate"] or end) - date.fromisoformat(cycle["openDate"])).days,
            "capture": {"days": None, "knownDays": 0, "totalDays": 0, "bestMetric": None, "missingReason": CAPTURE_MISSING},
            "whySell": RANK_MISSING,
            "formula": "（賣出收入＋已領股息／退還股款＋剩餘持股估值−買進成本）÷買進成本；已實現與未實現損益另列，剩餘成本採平均成本分攤。",
        })
        lower = date.fromisoformat(cycle["openDate"]) - timedelta(days=35)
        upper = date.fromisoformat(cycle["closeDate"] or end) + timedelta(days=20)
        cycle["candles"] = [row for row in candles.get(cycle["code"], []) if lower <= date.fromisoformat(row["date"]) <= upper]
        named_candles = [row for row in cycle["candles"] if _security_name(row.get("name"))]
        if named_candles:
            cycle["name"] = _security_name(named_candles[-1]["name"])
            cycle["nameSourceId"] = named_candles[-1]["sourceId"]
            cycle["nameBasis"] = "frozen-source-display-name-not-certified-historical-name"
        else:
            cycle["nameSourceId"] = None
            cycle["nameBasis"] = "code-only-name-unavailable"
        if not cycle["candles"]:
            cycle["missingReasons"].append("原價格快照的日 K 線不可取得。")
    return cycles, unassigned


def _statistics(nav: list[dict[str, Any]], cycles: list[dict[str, Any]], initial: float) -> dict[str, Any]:
    peak = initial
    peak_date = nav[0]["date"]
    start = None
    longest: dict[str, Any] = {"days": 0, "from": None, "until": None}
    for point in nav:
        if point["equity"] >= peak:
            if start:
                days = (date.fromisoformat(point["date"]) - date.fromisoformat(start)).days
                if days > longest["days"]:
                    longest = {"days": days, "from": start, "until": point["date"]}
            peak, peak_date, start = point["equity"], point["date"], None
        elif start is None:
            start = peak_date
        point["drawdown"] = point["equity"] / peak - 1
    if start:
        days = (date.fromisoformat(nav[-1]["date"]) - date.fromisoformat(start)).days
        if days > longest["days"]:
            longest = {"days": days, "from": start, "until": None}
    months: dict[str, float] = {}
    for point in nav:
        months[point["date"][:7]] = point["equity"]
    monthly = []
    previous = initial
    for month, equity in months.items():
        monthly.append({"month": month, "return": equity / previous - 1})
        previous = equity
    closed = sorted((c for c in cycles if c["closeDate"] and c["pnl"] is not None), key=lambda c: (c["closeDate"], c["closeSequence"]))
    wins, losses = [c for c in closed if c["pnl"] > 0], [c for c in closed if c["pnl"] < 0]
    streak: list[dict[str, Any]] = []
    worst: dict[str, Any] = {"count": 0, "pnl": 0, "from": None, "until": None}
    for cycle in closed:
        streak = [*streak, cycle] if cycle["pnl"] < 0 else []
        if len(streak) > worst["count"]:
            worst = {"count": len(streak), "pnl": _sum_money(c["pnl"] for c in streak), "from": streak[0]["closeDate"], "until": cycle["closeDate"]}
    gains = _sum_money(c["pnl"] for c in wins)
    top = _sum_money(c["pnl"] for c in sorted(wins, key=lambda c: c["pnl"], reverse=True)[:5])
    edges = [None, -0.5, -0.2, 0, 0.2, 0.5, 1, 2, None]
    histogram = [
        {
            "from": left,
            "until": right,
            "count": sum((left is None or c["return"] >= left) and (right is None or c["return"] < right) for c in closed if c["return"] is not None),
        }
        for left, right in zip(edges, edges[1:])
    ]
    return {
        "maxDrawdown": min(point["drawdown"] for point in nav),
        "longestUnderwater": longest,
        "longestLosingStreak": worst,
        "monthlyReturns": monthly,
        "winRate": len(wins) / len(closed) if closed else None,
        "meanGain": gains / len(wins) if wins else None,
        "meanLoss": _sum_money(c["pnl"] for c in losses) / len(losses) if losses else None,
        "topFiveProfitShare": top / gains if gains > 0 else None,
        "topFiveShareDefinition": "最賺五筆已平倉交易的獲利／全部獲利已平倉交易的獲利；不含未實現損益。",
        "histogram": histogram,
    }


def _validate_normalized_run(run: dict[str, Any], ledger: dict[str, Any]) -> None:
    """Reject adapter-field tampering even if original payloads and total NAV agree."""
    keys = {"date": "date", "action": "action", "code": "code", "quantity": "qty", "price": "price", "cashFlow": "total"}
    seen = set()
    for index, event in enumerate(run["events"]):
        original = event["original"]
        for key, native_key in keys.items():
            if key not in event or event[key] != original.get(native_key):
                raise StudioError(f"normalized event {key} disagrees with original source")
            if key in {"quantity", "price", "cashFlow"} and isinstance(event[key], bool):
                raise StudioError(f"normalized event {key} must not be a boolean")
        if event["id"] in seen:
            raise StudioError("duplicate saved event id")
        seen.add(event["id"])
        native = ledger.get("events", [])[index] if ledger.get("events") is not None else {}
        if "presentation_event_id" in native and event["id"] != native["presentation_event_id"]:
            raise StudioError("saved event presentation identity disagrees with verified ledger")
        if "source_event_index" in native and native["source_event_index"] != index:
            raise StudioError("verified ledger source event order mismatch")
    initial = _money(run["initialCapital"])
    final = _money(run["finalEquity"])
    if initial <= 0:
        raise StudioError("initial capital must be positive")
    if not run.get("nav"):
        raise StudioError("saved run has no NAV")
    if abs(final - _money(run["nav"][-1]["equity"])) > Decimal(str(MONEY_TOLERANCE)):
        raise StudioError("final equity disagrees with last saved NAV")
    if abs(_money(run["netReturn"]) - (final / initial - 1)) > Decimal("1e-9"):
        raise StudioError("net return disagrees with initial capital and final NAV")
    if ledger.get("recorded_nav") is not None:
        native_nav = [{"date": _day(point["date"]), "equity": point["equity"]} for point in ledger["recorded_nav"]]
        if native_nav != run["nav"]:
            raise StudioError("saved NAV disagrees with verified ledger")
    measurement = ledger.get("recorded_measurement")
    if measurement is not None:
        mapping = {"initialCapital": "initial_capital_twd", "finalEquity": "endpoint_equity_twd", "costs": "costs_total_twd"}
        for key, native_key in mapping.items():
            if abs(_money(run[key]) - _money(measurement[native_key])) > Decimal(str(MONEY_TOLERANCE)):
                raise StudioError(f"saved {key} disagrees with verified measurement")
        if abs(_money(run["netReturn"]) - _money(measurement["endpoint_net_return_fraction"])) > Decimal("1e-9"):
            raise StudioError("saved net return disagrees with verified measurement")


def build_run(
    run: dict[str, Any],
    ledger: dict[str, Any],
    orders: list[dict[str, Any]],
    entry_traces: list[dict[str, Any]],
    candles: dict[str, list[dict[str, Any]]],
    source_ids: list[str],
    probe_traces: list[dict[str, Any]] | None = None,
    display_names: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Pure adapter for already-saved evidence, usable with small regression fixtures."""
    if ledger.get("portfolio_id") != run["id"]:
        raise StudioError("ledger and run identities disagree")
    native_events = ledger.get("events")
    if native_events is not None and ([event["original"] for event in run["events"]] != [event["source_event"] for event in native_events]):
        raise StudioError("saved events disagree with verified ledger")
    _validate_normalized_run(run, ledger)
    if not run.get("nav"):
        raise StudioError("saved run has no NAV")
    nav_by_date = {valid_day(p["date"]): p["equity"] for p in run["nav"]}
    if len(nav_by_date) != len(run["nav"]) or list(nav_by_date) != sorted(nav_by_date):
        raise StudioError("NAV dates must be unique and sorted")
    if run["from"] != next(iter(nav_by_date)) or run["through"] != list(nav_by_date)[-1]:
        raise StudioError("run window does not match saved NAV")
    accounts = []
    for state in ledger["daily_states"]:
        day = _day(state["date"])
        if day not in nav_by_date:
            raise StudioError("account state has no recorded NAV")
        accounts.append(account_audit(state, nav_by_date[day]))
    if [a["date"] for a in accounts] != list(nav_by_date):
        raise StudioError("daily account dates do not match saved NAV")
    benchmark = {row["date"]: row["close"] for row in candles.get("0050", [])}
    base = benchmark.get(run["from"])
    nav = [
        {
            "date": day,
            "equity": equity,
            "benchmarkEquity": run["initialCapital"] * benchmark[day] / base if base and benchmark.get(day) else None,
            "drawdown": 0,
        }
        for day, equity in nav_by_date.items()
    ]
    cycles, reasons = _cycles(run, orders, entry_traces, accounts, candles, probe_traces or [])
    names = display_names or {}
    for cycle in cycles:
        metadata = names.get(cycle["code"])
        if metadata and _security_name(metadata.get("name")) and cycle["name"] == cycle["code"]:
            cycle["name"] = metadata["name"]
            cycle["nameSourceId"] = metadata["sourceId"]
            cycle["nameBasis"] = "catalog-snapshot-display-name-not-historical-classification"
    cycle_names = {cycle["code"]: cycle for cycle in cycles if cycle["name"] != cycle["code"]}
    for account in accounts:
        for holding in account["holdings"]:
            metadata = names.get(holding["code"])
            holding_cycle = cycle_names.get(holding["code"])
            if metadata and _security_name(metadata.get("name")):
                holding.update({
                    "name": metadata["name"],
                    "nameSourceId": metadata["sourceId"],
                    "nameBasis": "catalog-snapshot-display-name-not-historical-classification",
                })
            elif holding_cycle:
                holding.update({"name": holding_cycle["name"], "nameSourceId": holding_cycle["nameSourceId"], "nameBasis": holding_cycle["nameBasis"]})
    stats = _statistics(nav, cycles, run["initialCapital"])
    closed_pnl = _sum_money(c["pnl"] for c in cycles if c["closeDate"] and c["pnl"] is not None)
    open_cycles = [c for c in cycles if not c["closeDate"]]
    open_pnl = None if any(c["pnl"] is None for c in open_cycles) else _sum_money(c["pnl"] for c in open_cycles)
    other = accounts[-1]["otherAssets"]
    total = None if open_pnl is None or other is None else _sum_money([closed_pnl, open_pnl, other])
    increase = _sum_money([run["finalEquity"], -run["initialCapital"]])
    difference = None if total is None else _sum_money([total, -increase])
    if difference is None or abs(difference) > MONEY_TOLERANCE:
        reasons.append("交易損益、期末持股與其他資產尚未和帳戶增減完全核對。")
    if any(not a["verified"] for a in accounts):
        reasons.append("部分日期的帳戶估值無法核對。")
    result = {
        "id": run["id"],
        "name": run["name"],
        "plainTitle": run["name"],
        "plainIdea": run["method"]["rules"][0] if run["method"].get("rules") else "請展開原研究規則。",
        "ownerAdopted": False if run["method"].get("parameters", {}).get("final_strategy_approved") is False else None,
        "studyStatus": run["method"]["status"],
        "initialCapital": run["initialCapital"],
        "finalEquity": run["finalEquity"],
        "from": run["from"],
        "through": run["through"],
        "netReturn": run["netReturn"],
        "costs": run["costs"],
        "nav": nav,
        "maxDrawdown": stats["maxDrawdown"],
        "longestUnderwater": stats["longestUnderwater"],
        "winRate": stats["winRate"],
        "closedTradeCount": sum(bool(c["closeDate"]) for c in cycles),
        "capturedClosedTradeCount": None,
        "captureAvgWeight": None,
        "positions": cycles,
        "statistics": stats,
        "method": run["method"],
        "benchmark": {
            "code": "0050",
            "label": "0050 股價，不含配息",
            "basis": "original-frozen-raw-close-price-only",
            "missingReason": None if all(p["benchmarkEquity"] is not None for p in nav) else "部分日期缺少同一原始快照的 0050 收盤價。",
        },
        "sourceIds": source_ids,
        "accountDates": list(nav_by_date),
        "accounts": accounts,
        "limitations": [
            *run.get("limitations", []),
            RANK_MISSING,
            "持有期間與事後飆股重疊不表示事前可發現。",
            "加碼以原研究的經濟報酬判定，可能包含股息等權益；未還原 K 線漲幅不是同一數字。",
            "交易損益及交易統計只計已入帳股息／退還股款；未入帳權益列在 pendingAssets 與帳戶其他資產。",
        ],
        "reconciliation": {
            "closedPnl": closed_pnl,
            "openPnl": open_pnl,
            "otherAssets": other,
            "totalPnl": total,
            "accountIncrease": increase,
            "difference": difference,
            "verified": difference is not None and abs(difference) <= MONEY_TOLERANCE and not reasons,
            "reasons": reasons,
        },
    }
    finite_json(result)
    return result


def _frozen_candles(packet: dict[str, Any], codes: set[str], first: str, last: str) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Read only exact sealed parquet bytes; raw bars cannot be invented from Close."""
    import pandas as pd

    inputs = packet.get("inputs", {})
    found = [
        (Path(path), sha)
        for path, sha in inputs.items()
        if re.search(r"/price-readset/(twse-official|twse-recovered|tpex-official)/prices\.parquet$", _path_key(path))
    ]
    if not found:
        logger.warning("saved packet has no frozen OHLC readset")
        return {}, []
    candles: dict[str, dict[str, dict[str, Any]]] = {}
    sources = []
    lower, upper = str(date.fromisoformat(first) - timedelta(days=40)), str(date.fromisoformat(last) + timedelta(days=25))
    for path, sha in found:
        frame = pd.read_parquet(
            BytesIO(read_verified(path, sha)),
            columns=["code", "date", "open", "high", "low", "close", "name"],
            filters=[("code", "in", sorted(codes)), ("date", ">=", lower), ("date", "<=", upper)],
        )
        source_id = f"{path.parent.name}:{sha}"
        sources.append({"id": source_id, "path": str(path), "hash": sha})
        for row in frame.to_dict("records"):
            code, day = str(row["code"]), valid_day(str(row["date"]))
            candle: dict[str, Any] = {"date": day, "sourceId": source_id, "name": _security_name(row["name"])}
            for key in ("open", "high", "low", "close"):
                value = row[key]
                candle[key] = float(value) if value is not None and math.isfinite(value) else None
            code_rows = candles.setdefault(code, {})
            if day in code_rows and any(code_rows[day][key] != candle[key] for key in ("open", "high", "low", "close")):
                raise StudioError(f"conflicting frozen OHLC sources: {code}/{day}")
            code_rows[day] = candle
    return {code: [rows[day] for day in sorted(rows)] for code, rows in candles.items()}, sources


def _catalog_benchmark(manifest_path: Path, expected_sha: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    manifest = _verified_json(manifest_path, expected_sha)
    root = manifest_path.parent.resolve()
    references = [manifest["calendar"], manifest["series"]["0050"]]
    values = []
    sources = [{"id": f"benchmark-catalog:{expected_sha}", "path": str(manifest_path), "hash": expected_sha}]
    for ref in references:
        path = (root / ref["path"]).resolve()
        if not path.is_relative_to(root):
            raise StudioError("benchmark reference escapes catalog root")
        raw = read_verified(path, ref["sha256"])
        values.append(json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw))
        sources.append({"id": f"benchmark-source:{ref['sha256']}", "path": str(path), "hash": ref["sha256"]})
    calendar, series = values
    if series["code"] != "0050" or series["calendar_id"] != calendar["calendar_id"] or len(series["raw"]) != len(calendar["dates"]):
        raise StudioError("benchmark calendar/security identity mismatch")
    rows = [
        {"date": valid_day(day), "open": None, "high": None, "low": None, "close": close, "sourceId": f"benchmark-catalog:{expected_sha}"}
        for day, close in zip(calendar["dates"], series["raw"])
    ]
    return rows, sources


def _catalog_display_names(manifest_path: Path, expected_sha: str) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """Use only pinned catalog security labels; never assign its current classifications."""
    manifest = _verified_json(manifest_path, expected_sha)
    root = manifest_path.parent.resolve()
    sources = [{"id": f"security-name-catalog:{expected_sha}", "path": str(manifest_path), "hash": expected_sha}]
    names: dict[str, dict[str, str]] = {}
    for ref in manifest.get("tables", {}).get("securities", []):
        path = (root / ref["path"]).resolve()
        if not path.is_relative_to(root):
            raise StudioError("security name reference escapes catalog root")
        raw = read_verified(path, ref["sha256"])
        payload = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) != ref["count"]:
            raise StudioError("security name table has invalid rows/count")
        source_id = f"security-name-source:{ref['sha256']}"
        sources.append({"id": source_id, "path": str(path), "hash": ref["sha256"]})
        for row in rows:
            code = row["code"]
            if not isinstance(code, str) or row["security_id"] != f"TW:{code}":
                raise StudioError("security name table identity mismatch")
            name = _security_name(row.get("name"))
            if name is None:
                continue
            previous = names.get(code)
            if previous and previous["name"] != name:
                raise StudioError("conflicting security display names")
            names[code] = {"name": name, "sourceId": source_id}
    return names, sources


def export_bundle(
    saved_runs_path: Path,
    tasks_root: Path,
    registry_path: Path,
    benchmark_manifest: Path | None = None,
    benchmark_manifest_sha: str | None = None,
    presentation_path: Path | None = None,
) -> dict[str, Any]:
    """Enrich the existing reviewed runs using their own declared source identities."""
    raw = saved_runs_path.read_bytes()
    saved = json.loads(gzip.decompress(raw) if saved_runs_path.suffix == ".gz" else raw)
    if saved.get("schema") != "saved-research-runs.v1":
        raise StudioError("unsupported saved research bundle")
    sources = {source["id"]: source for source in saved["sources"]}
    results = []
    extra_sources: list[dict[str, str]] = []
    catalog_benchmark: list[dict[str, Any]] | None = None
    benchmark_sources: list[dict[str, str]] = []
    display_names: dict[str, dict[str, str]] = {}
    name_sources: list[dict[str, str]] = []
    if benchmark_manifest is not None:
        if benchmark_manifest_sha is None:
            raise StudioError("benchmark catalog requires an external SHA-256 pin")
        catalog_benchmark, benchmark_sources = _catalog_benchmark(benchmark_manifest, benchmark_manifest_sha)
        extra_sources.extend(benchmark_sources)
        display_names, name_sources = _catalog_display_names(benchmark_manifest, benchmark_manifest_sha)
        extra_sources.extend(name_sources)
    for run in saved["runs"]:
        declared = [sources[source_id] for source_id in run["sourceIds"]]
        ledger_source = next((s for s in declared if s["id"] == f"ledger:{run['id']}"), None)
        if ledger_source is None:
            raise StudioError("saved run lacks declared ledger")
        ledger = _verified_json(Path(ledger_source["path"]), ledger_source["hash"])
        source_by_path = {_path_key(path): sha for path, sha in ledger["source_hashes"].items()}
        order_paths = [Path(path) for path in ledger["source_hashes"] if _path_key(path).endswith("/orders.json")]
        if len(order_paths) != 1:
            raise StudioError("ledger must declare exactly one native orders source")
        order_path = order_paths[0]
        receipt_path = order_path.with_name("receipt.json")
        receipt = _verified_json(receipt_path, source_by_path[_path_key(receipt_path)])
        if receipt.get("status") != "complete" or receipt.get("inputs_unchanged") is not True:
            raise StudioError("native receipt is not a completed unchanged-input run")
        orders = _verified_json(order_path, source_by_path[_path_key(order_path)])
        traces_path = order_path.with_name("entry-traces.json")
        traces = _verified_json(traces_path, receipt["outputs"]["entry-traces.json"])
        extra_sources.append({"id": f"entry-traces:{run['id']}", "path": str(traces_path), "hash": receipt["outputs"]["entry-traces.json"]})
        probe_path = order_path.with_name("probe-traces.json")
        probes = _verified_json(probe_path, receipt["outputs"]["probe-traces.json"])
        extra_sources.append({"id": f"probe-traces:{run['id']}", "path": str(probe_path), "hash": receipt["outputs"]["probe-traces.json"]})
        packet_candidates = [Path(path) for path, sha in ledger["source_hashes"].items() if sha == receipt["approved_packet_sha256"]]
        if len(packet_candidates) != 1:
            raise StudioError("receipt packet identity not uniquely declared")
        packet = _verified_json(packet_candidates[0], receipt["approved_packet_sha256"])
        codes = {e["code"] for e in run["events"]} | {"0050"}
        candles, price_sources = _frozen_candles(packet, codes, run["from"], run["through"])
        alternate_benchmark = not candles.get("0050") and catalog_benchmark is not None
        if alternate_benchmark:
            assert catalog_benchmark is not None
            candles["0050"] = catalog_benchmark
        extra_sources.extend(price_sources)
        results.append(
            build_run(
                run,
                ledger,
                orders,
                traces,
                candles,
                [
                    *run["sourceIds"],
                    f"entry-traces:{run['id']}",
                    f"probe-traces:{run['id']}",
                    *(s["id"] for s in price_sources),
                    *(s["id"] for s in name_sources),
                ],
                probes,
                display_names,
            )
        )
        if display_names:
            results[-1]["limitations"].append("部分股票名稱使用已核對的目錄快照作顯示標籤，不代表當年公司名稱或歷史產業分類。")
        if alternate_benchmark:
            results[-1]["benchmark"]["basis"] = "fixed-history-catalog-raw-close-price-only; separate-from-strategy-seal"
            results[-1]["benchmark"]["sourceIds"] = [source["id"] for source in benchmark_sources]
            results[-1]["limitations"].append("0050 比較線使用另行核對的歷史目錄固定快照；它不是原策略封存輸入，不含配息。")
            results[-1]["sourceIds"].extend(source["id"] for source in benchmark_sources)
        logger.info(
            "saved studio: %s, %d cycles, %d account dates, reconciliation=%s",
            run["id"],
            len(results[-1]["positions"]),
            len(results[-1]["accounts"]),
            results[-1]["reconciliation"]["verified"],
        )
    if presentation_path is not None and presentation_path.is_file():
        presentation_raw = presentation_path.read_bytes()
        extra_sources.append({"id": "research-presentation-metadata", "path": str(presentation_path), "hash": hashlib.sha256(presentation_raw).hexdigest()})
    all_sources: dict[str, dict[str, Any]] = {}
    for source in [*saved["sources"], *extra_sources]:
        previous = all_sources.get(source["id"])
        if previous is not None and previous != source:
            raise StudioError("conflicting source identity in saved studio bundle")
        all_sources[source["id"]] = source
    result = {
        "schema": SCHEMA,
        "asOf": saved["asOf"],
        "savedRunsHash": hashlib.sha256(raw).hexdigest(),
        "sources": list(all_sources.values()),
        "runs": results,
        "researchHistory": research_history(tasks_root, registry_path, presentation_path),
    }
    finite_json(result)
    return result


def _presentation_metadata(path: Path | None, *, required: bool = False) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"research presentation metadata unavailable: {path}")
        return {}
    try:
        value = read_json(path)
    except EvidenceError as error:
        raise StudioError("invalid research presentation metadata JSON") from error
    if not isinstance(value, dict) or value.get("schema") != "research-presentation.v1":
        raise StudioError("unsupported research presentation metadata schema")
    studies = value.get("studies")
    if studies is None and isinstance(value.get("items"), list):
        studies = {}
        for row in value["items"]:
            if not isinstance(row, dict):
                raise StudioError("invalid research presentation study")
            task_id = row.get("taskId", row.get("id"))
            if not isinstance(task_id, str) or task_id in studies:
                raise StudioError("invalid or duplicate research presentation study identity")
            studies[task_id] = row
    if not isinstance(studies, dict):
        raise StudioError("research presentation studies must be a mapping")
    allowed_statuses = {"行不通", "結果不一", "已結案", "研究中", "已保存報告", "資料不足", "量測待修正", "尚未評估"}
    for task_id, item in studies.items():
        if not isinstance(task_id, str) or not isinstance(item, dict):
            raise StudioError("invalid research presentation study")
        if item.get("status") is not None and (not isinstance(item["status"], str) or item["status"] not in allowed_statuses):
            raise StudioError("presentation metadata cannot declare owner adoption or an unknown verdict")
        if "category" in item and (not isinstance(item["category"], str) or item["category"] not in {"research", "infrastructure"}):
            raise StudioError("presentation category must be research or infrastructure")
        if "section" in item and (not isinstance(item["section"], str) or item["section"] not in {"method", "market", "design"}):
            raise StudioError("presentation section must be method, market or design")
        if "reviewConfirmed" in item and not isinstance(item["reviewConfirmed"], bool):
            raise StudioError("presentation reviewConfirmed must be a boolean")
        for key in ("plainTitle", "plainConclusion", "sourceNote"):
            if key in item and (not isinstance(item[key], str) or not item[key].strip()):
                raise StudioError(f"presentation {key} must be nonempty text")
    return studies


def _apply_history_presentation(item: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Overlay display copy on a projection; formal outcome and saved evidence stay intact."""
    if "section" in metadata:
        item["section"] = metadata["section"]
    if "plainTitle" in metadata:
        if item["title"] != metadata["plainTitle"]:
            item.setdefault("savedTitle", item["title"])
        item["title"] = metadata["plainTitle"]
    if "plainConclusion" in metadata:
        item["conclusion"] = metadata["plainConclusion"]
    if "plainTitle" in metadata or "plainConclusion" in metadata:
        item["summarySource"] = "presentation-metadata"
        item["reviewConfirmed"] = metadata.get("reviewConfirmed", False)
        item["sourceNote"] = metadata.get("sourceNote", "呈現摘要尚未由研究端核對。")
    # A display suggestion cannot replace a recorded outcome or declare adoption.
    if item.get("outcome") is None and metadata.get("status"):
        item["draftStatus"] = metadata["status"]


def _history_title_origins(path: Path | None, history: dict[str, Any]) -> tuple[dict[str, dict[str, str]], str | None]:
    """A pinned report-title snapshot supplements titles lost by legacy overlays."""
    if path is None:
        return {}, None
    try:
        raw = _bounded_bytes(path, MAX_PART_BYTES)
        value = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise StudioError("invalid history title origins JSON") from error
    if not isinstance(value, dict) or value.get("schema") != "research-history-title-origins.v1":
        raise StudioError("unsupported history title origins schema")
    fingerprint = hashlib.sha256(json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if value.get("historySha256") != fingerprint:
        raise StudioError("history title origins do not match saved history")
    revision, titles = value.get("sourceRevision"), value.get("titles")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision) or not isinstance(titles, dict):
        raise StudioError("invalid history title origins provenance")
    expected = {item["id"]: item["reportPath"] for item in history["items"] if item["reportPath"] is not None}
    if set(titles) != set(expected):
        raise StudioError("history title origins have missing or extra identities")
    for task_id, row in titles.items():
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("title"), str)
            or not row["title"].strip()
            or row.get("sourcePath") != expected[task_id]
            or not isinstance(row.get("sourceSha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["sourceSha256"])
        ):
            raise StudioError("invalid history title source")
    return titles, revision


def _restore_history_presentation(item: dict[str, Any], origin: dict[str, str] | None, revision: str | None) -> None:
    """Restore display inputs first; never change formal outcomes or saved summaries."""
    legacy = item.get("summarySource") == "presentation-metadata"
    if legacy:
        item["legacyPresentationTitle"] = item["title"]
    original_title = item.get("originalTitle")
    if original_title is not None and (not isinstance(original_title, str) or not original_title.strip()):
        raise StudioError("invalid original history title")
    if original_title is not None:
        item["title"] = original_title
    elif origin is not None:
        item["title"] = origin["title"]
        item["titleSourceRevision"] = revision
        item["titleSourceSha256"] = origin["sourceSha256"]
        item["titleBasis"] = "versioned-report-heading-not-legacy-export-title"
    elif legacy:
        saved_title = item.get("savedTitle")
        if saved_title is not None and (not isinstance(saved_title, str) or not saved_title.strip()):
            raise StudioError("invalid saved history title")
        item["title"] = saved_title or item["id"]
        if not saved_title:
            item["originalTitleUnavailable"] = True
    if legacy:
        published = (item.get("reportPath") or "").endswith("/report.md")
        item["conclusion"] = item["originalSummary"] if published else "目前只有保存的研究規劃，尚無結果報告。"
        item["summarySource"] = "formal-report" if published else "mission"
        item["sourceNote"] = None
        item["reviewConfirmed"] = False
    for field in ("draftStatus", "section", "savedTitle"):
        item.pop(field, None)


def research_history(tasks_root: Path, registry_path: Path, presentation_path: Path | None = None) -> dict[str, Any]:
    """Index published reports dynamically; avoid opening sealed runs or summaries."""
    registry = validate_registry(read_json(registry_path))
    presentation = _presentation_metadata(presentation_path)
    events = registry["events"]
    items = []
    for task in task_catalog(tasks_root):
        root = tasks_root / task["task"]
        report = root / "report.md"
        mission = root / "mission.md"
        if not report.is_file() and not mission.is_file():
            continue
        published = report.is_file()
        content = (report if published else mission).read_text(encoding="utf-8")
        lines = content.splitlines()
        title = next((line.lstrip("# ").strip() for line in lines if line.startswith("# ")), task["task"])
        paragraphs = re.split(r"\n\s*\n", content)
        summary = next((p.strip() for p in paragraphs if p.strip() and not p.lstrip().startswith(("#", "|", "-", "```"))), "")
        event_ids = [e["id"] for e in events if e["source"].split("#")[0].replace("\\", "/").startswith(f"tasks/{task['task']}/")]
        inferred_date = task["task"][:8]
        if not re.fullmatch(r"\d{8}", inferred_date):
            continue
        day = f"{inferred_date[:4]}-{inferred_date[4:6]}-{inferred_date[6:]}"
        valid_day(day)
        status = "已保存報告" if published else "研究中"
        outcome = None
        if published and (root / "research_result.json").is_file():
            result = validate_result(read_json(root / "research_result.json"))
            outcome = result["outcome"]
            status = {
                "candidate_failed": "行不通",
                "candidate_passed": "通過研究門檻，尚未採用",
                "invalid_measurement": "量測待修正",
                "data_blocked": "資料不足",
                "incomplete": "研究中",
                "not_evaluated": "尚未評估",
            }[outcome]
        conclusion = summary if published else "目前只有保存的研究規劃，尚無結果報告。"
        item = {
            "id": task["task"],
            "date": day,
            "title": title,
            "originalTitle": title,
            "dateBasis": "task-identifier-date-not-certified-completion-date",
            "status": status,
            "conclusion": conclusion,
            "originalSummary": summary,
            "reportPath": f"tasks/{task['task']}/report.md" if published else f"tasks/{task['task']}/mission.md",
            "reviewConfirmed": False,
            "outcome": outcome,
            "draftStatus": None,
            "summarySource": "formal-report" if published else "mission",
            "sourceNote": None,
            "evidenceState": "published_report_not_owner_adoption" if published else "mission_only_not_evaluated",
            "registryEventIds": event_ids,
        }
        metadata = presentation.get(task["task"])
        if metadata:
            _apply_history_presentation(item, metadata)
        items.append(item)
    return {"schema": "saved-research-history.v1", "historyComplete": False, "items": sorted(items, key=lambda row: (row["date"], row["id"]), reverse=True)}


def synthetic_studio_package() -> dict[str, Any]:
    """Build an independent fictional ledger, never adapt a private saved package.

    The demo identity follows the opportunity fixture's fictional demo-0-0 control.
    This is deterministic presentation data, not an evaluated market strategy.
    """
    run_id, code = "synthetic:studio:v1", "demo-0-0"
    dates = ["2020-01-02", "2020-01-03"]
    originals = [
        {"action": "BUY", "code": code, "date": f"{dates[0]}T09:00:00+08:00", "qty": 10, "price": 10, "total": -100, "order_id": "demo-buy"},
        {"action": "SELL", "code": code, "date": f"{dates[1]}T09:00:00+08:00", "qty": 10, "price": 11, "total": 110, "order_id": "demo-sell"},
    ]
    source_raw = json.dumps(originals, sort_keys=True, separators=(",", ":")).encode()
    source_id = f"synthetic-ledger:{hashlib.sha256(source_raw).hexdigest()}"
    run = {
        "id": run_id,
        "name": "Fictional saved account demo",
        "from": dates[0],
        "through": dates[1],
        "initialCapital": 1000,
        "finalEquity": 1010,
        "netReturn": 0.01,
        "costs": 0,
        "method": {
            "status": "synthetic-demo",
            "rules": ["Fictional buy and sell; not market research or a strategy recommendation."],
            "conclusion": "Demonstrates saved evidence presentation only.",
            "parameters": {"final_strategy_approved": False},
        },
        "limitations": ["All identities, prices, holdings and returns are fictional deterministic controls."],
        "nav": [{"date": day, "equity": equity} for day, equity in zip(dates, [1000, 1010])],
        "events": [
            {
                "id": f"demo-event-{i}",
                "date": event["date"],
                "action": event["action"],
                "code": code,
                "quantity": event["qty"],
                "price": event["price"],
                "cashFlow": event["total"],
                "original": event,
            }
            for i, event in enumerate(originals)
        ],
    }
    states = []
    for day, cash, quantity, price in zip(dates, [900, 1010], [10, 0], [10, 11]):
        states.append({
            "date": f"{day}T20:00:00+08:00",
            "cash_twd": cash,
            "tradable_positions": [
                {
                    "security_id": code,
                    "quantity": quantity,
                    "raw_mark_twd": price,
                    "market_value_twd": quantity * price,
                    "mark_quality": {"source_id": source_id, "modeled_mark": False, "observed_at": f"{day}T13:30:00+08:00"},
                }
            ]
            if quantity
            else [],
            "dividend_receivable_twd": 0,
            "capital_return_receivable_twd": 0,
            "share_claims_value_twd": 0,
            "receivables": [],
            "share_claims": [],
        })
    ledger = {"portfolio_id": run_id, "daily_states": states, "events": [{"source_event": event} for event in originals]}
    orders = [
        {"intent": {"order_id": event["order_id"], "code": code, "side": event["action"], "decision_at": "2020-01-01T20:00:00+08:00"}, "lineage": None}
        for event in originals
    ]
    candles = {
        code: [
            {"date": day, "open": price, "high": price + 1, "low": price - 1, "close": price, "name": "Fictional demo company", "sourceId": source_id}
            for day, price in zip(dates, [10, 11])
        ]
    }
    built_run = build_run(run, ledger, orders, [], candles, [source_id])
    built_run["benchmark"] = {
        "code": "demo-benchmark",
        "label": "Fictional demo; no market benchmark",
        "basis": "synthetic-demo-no-market-data",
        "missingReason": "No market benchmark is supplied in synthetic mode.",
    }
    built_run["synthetic"] = True
    value = {
        "schema": SCHEMA,
        "dataMode": "public-synthetic",
        "synthetic": True,
        "sources": [{"id": source_id, "hash": hashlib.sha256(source_raw).hexdigest(), "basis": "generated-fictional-ledger-v1"}],
        "runs": [built_run],
        "researchHistory": {"schema": "saved-research-history.v1", "historyComplete": False, "items": []},
    }
    finite_json(value)
    _validate_studio_package(value)
    return value


class SavedResearchStudio:
    """In-memory reader of the additive package; optional map callback stays external."""

    def __init__(
        self,
        package_path: Path | None,
        capture_provider: Callable[[str, str], dict[str, Any] | None] | None = None,
        history_presentation_path: Path | None = None,
        history_title_origins_path: Path | None = None,
    ):
        self.package_path = package_path
        self.capture_provider = capture_provider
        self.history_presentation_path = history_presentation_path
        self.history_title_origins_path = history_title_origins_path
        self._package: dict[str, Any] | None = None
        self._enriched: dict[str, dict[str, Any]] = {}
        self._capture_locks_guard = Lock()
        self._capture_locks: dict[str, Any] = {}
        self._capture_context = local()

    def capture_state(self) -> str:
        if self.capture_provider is None:
            return "failed"
        state = getattr(self.capture_provider, "state", None)
        value = state() if callable(state) else "ready"
        if isinstance(value, dict):
            value = value.get("state", value.get("status"))
        return value if isinstance(value, str) and value in {"loading", "ready", "failed"} else "failed"

    def _load(self) -> dict[str, Any]:
        if self._package is None:
            value = synthetic_studio_package() if self.package_path is None else read_studio_package(self.package_path)
            self._package = value
            logger.info("loaded saved studio package %s (%d runs)", self.package_path, len(value["runs"]))
        return self._package

    def _find(self, run_id: str) -> dict[str, Any]:
        for run in self._load()["runs"]:
            if run["id"] == run_id:
                return run
        raise StudioNotFound("saved run not found")

    def _with_capture(self, run_id: str) -> dict[str, Any]:
        # A provider can consult saved evidence during projection. Such nested
        # reads get the un-enriched view instead of acquiring another run lock.
        if getattr(self._capture_context, "active", False):
            return self._enriched.get(run_id) or {**self._find(run_id), "captureState": "loading"}
        state = self.capture_state()
        if state != "ready":
            return {**self._find(run_id), "captureState": state}
        if run_id in self._enriched:
            return self._enriched[run_id]
        with self._capture_locks_guard:
            run_lock = self._capture_locks.setdefault(run_id, Lock())
        with run_lock:
            if run_id in self._enriched:
                return self._enriched[run_id]
            self._capture_context.active = True
            try:
                state = self.capture_state()
                if state != "ready":
                    return {**self._find(run_id), "captureState": state}
                return self._enrich_ready_run(run_id, state)
            finally:
                self._capture_context.active = False

    def _enrich_ready_run(self, run_id: str, state: str) -> dict[str, Any]:
        original = self._find(run_id)
        provider = self.capture_provider
        if provider is None:
            return original
        run = copy.deepcopy(original)
        run["captureState"] = state
        capture_cache: dict[tuple[str, str], dict[str, Any] | None] = {}

        def capture(code: str, day: str) -> dict[str, Any] | None:
            key = (code, day)
            if key not in capture_cache:
                capture_cache[key] = provider(code, day)
            return capture_cache[key]

        for account in run["accounts"]:
            for holding in account["holdings"]:
                status = capture(holding["code"], account["date"])
                holding["onMap"] = status.get("onMap") if status else None
                _capture_display_name(holding, status)
        for trade in run["positions"]:
            days = [day for day in run["accountDates"] if trade["openDate"] <= day <= (trade["closeDate"] or run["through"])]
            known, hits, metrics = 0, 0, []
            for day in days:
                status = capture(trade["code"], day)
                if status and status.get("onMap") is not None:
                    known += 1
                    if status["onMap"]:
                        hits += 1
                        if status.get("metric") is not None:
                            metrics.append(status["metric"])
                _capture_display_name(trade, status)
            trade["capture"] = {
                "days": hits if known else None,
                "knownDays": known,
                "totalDays": len(days),
                "bestMetric": max(metrics) if metrics else None,
                "missingReason": None if known == len(days) else "部分持有日期的飆股狀態未知。",
            }
        closed = [trade for trade in run["positions"] if trade["closeDate"]]
        run["capturedClosedTradeCount"] = (
            sum(bool(trade["capture"]["days"]) for trade in closed) if all(trade["capture"]["missingReason"] is None for trade in closed) else None
        )
        exposure = self._exposure_rows(run)
        run["captureAvgWeight"] = (
            sum(row["runawayWeight"] for row in exposure) / len(exposure) if exposure and all(row["runawayWeight"] is not None for row in exposure) else None
        )
        run["captureCoverage"] = _capture_coverage(run, exposure)
        logger.debug("saved capture coverage %s: %s", run_id, run["captureCoverage"])
        run["limitations"].append("交易重疊逐個保存交易日判定，包含開倉與平倉日；資金比例採當晚保存持股，不沿用每週樣本。")
        self._enriched[run_id] = run
        return run

    @staticmethod
    def _exposure_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for account in run["accounts"]:
            equity = account["recordedEquity"]
            usable_equity = equity > 0
            known_values = all(h["marketValue"] is not None for h in account["holdings"])
            known_status = all(h["onMap"] is not None for h in account["holdings"])
            stock_value = _sum_money(h["marketValue"] for h in account["holdings"]) if known_values else None
            runaway_value = _sum_money(h["marketValue"] for h in account["holdings"] if h["onMap"]) if known_values and known_status else None
            unknown_value = _sum_money(h["marketValue"] for h in account["holdings"] if h["onMap"] is None) if known_values else None
            rows.append({
                "date": account["date"],
                "runawayWeight": runaway_value / equity if usable_equity and runaway_value is not None else None,
                "otherStockWeight": (stock_value - runaway_value) / equity if usable_equity and stock_value is not None and runaway_value is not None else None,
                "cashWeight": account["cash"] / equity if usable_equity else None,
                "otherAssetsWeight": account["otherAssets"] / equity if usable_equity and account["otherAssets"] is not None else None,
                "unknownStockWeight": unknown_value / equity if usable_equity and unknown_value is not None else None,
                "known": usable_equity and known_values and known_status,
                "verifiedAccount": account["verified"],
            })
        return rows

    def index(self) -> dict[str, Any]:
        excluded = {"positions", "statistics", "reconciliation", "method", "benchmark", "sourceIds", "accountDates", "accounts"}
        return {
            "schema": SCHEMA,
            "captureState": self.capture_state(),
            "runs": [{k: v for k, v in self._with_capture(run["id"]).items() if k not in excluded} for run in self._load()["runs"]],
        }

    def run(self, run_id: str) -> dict[str, Any]:
        return {key: value for key, value in self._with_capture(run_id).items() if key != "accounts"}

    def trade(self, run_id: str, trade_id: str) -> dict[str, Any]:
        for trade in self._with_capture(run_id)["positions"]:
            if trade["id"] == trade_id:
                return copy.deepcopy(trade)
        raise StudioNotFound("saved trade not found")

    def account(self, run_id: str, day: str) -> dict[str, Any]:
        valid_day(day)
        for account in self._with_capture(run_id)["accounts"]:
            if account["date"] == day:
                result = copy.deepcopy(account)
                return result
        raise StudioNotFound("no saved account state on this date")

    def history(self) -> dict[str, Any]:
        history = copy.deepcopy(self._load()["researchHistory"])
        titles, revision = _history_title_origins(self.history_title_origins_path, history)
        for item in history["items"]:
            _restore_history_presentation(item, titles.get(item["id"]), revision)
        presentation = _presentation_metadata(self.history_presentation_path, required=True)
        original_items = history["items"]
        history["items"] = [item for item in original_items if presentation.get(item["id"], {}).get("category", "research") != "infrastructure"]
        for item in history["items"]:
            _apply_history_presentation(item, presentation.get(item["id"], {}))
        history["excludedInfrastructureCount"] = len(original_items) - len(history["items"])
        return history

    def exposure(self, run_id: str) -> dict[str, Any]:
        return {
            "runId": run_id,
            "captureState": self.capture_state(),
            "basis": "daily-saved-evening-holdings; same-map-rule; no-weekly-sampling",
            "rows": self._exposure_rows(self._with_capture(run_id)),
        }
