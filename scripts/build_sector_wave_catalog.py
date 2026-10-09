"""Build the descriptive sector-wave bundle from its pinned local inputs."""

from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import logging
import math
import os
import sqlite3
import sys
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

from research_core.evidence import finite_json, read_json
from research_core.sector_groups import build_groups
from research_core.sector_waves import DEFINITION_ID, CatalogBar, cluster_waves, compare_peer, detect_episodes, select_wave_winner
from StockProject.engine.data_loader import CASH_WINDOW_EVENTS, PERMANENT_FACTOR_EVENTS, DataLoader

WINDOW_START = "2019-01-02"
WINDOW_END = "2026-08-14"
TASK_NAME = "20261002-sector-wave-catalog"
CHUNK_ROWS = 256
LOGGER = logging.getLogger(__name__)
TEXT_INPUT_KEYS = (
    "config",
    "mission",
    "owner_contract",
    "registry",
    "loader",
    "waves",
    "groups",
    "entrypoint",
    "evidence",
    "foundation",
    "lock",
)


def _iso_day(value: Any) -> str:
    text = str(pd.Timestamp(value))[:10]
    date.fromisoformat(text)
    return text


def _usable_factor(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


class CatalogIOError(ValueError):
    """Pinned catalog input or output contract is invalid."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_sha(name: str, path: Path) -> str:
    """Hash pinned source text consistently across CRLF and LF worktrees."""
    content = path.read_bytes()
    if name in TEXT_INPUT_KEYS:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:16]}"


def _readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise CatalogIOError(f"required input missing: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogIOError(f"invalid JSON input: {path}") from error
    if not isinstance(value, dict):
        raise CatalogIOError(f"JSON input must be an object: {path}")
    return value


def _paths(repo_root: Path) -> dict[str, Path]:
    data = repo_root / "shioaji_stock_prices" / "data"
    task = repo_root / "tasks" / TASK_NAME
    return {
        "price": data / "price_daily.parquet",
        "meta": data / "symbol_meta.sqlite",
        "actions": data / "corporate_actions.sqlite",
        "taxonomy": data / "value_chain_classification.json",
        "config": repo_root / "research_core" / "sector_groups.v1.json",
        "mission": task / "mission.md",
        "owner_contract": repo_root / "docs" / "en" / "research-owner-contract.md",
        "registry": repo_root / "docs" / "en" / "research-registry.json",
        "loader": repo_root / "StockProject" / "engine" / "data_loader.py",
        "waves": repo_root / "research_core" / "sector_waves.py",
        "groups": repo_root / "research_core" / "sector_groups.py",
        "entrypoint": Path(__file__).resolve(),
        "evidence": repo_root / "research_core" / "evidence.py",
        "foundation": repo_root / "docs" / "en" / "research-foundation.md",
        "lock": repo_root / "uv.lock",
    }


def _finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    return value


def _write_chunks(output: Path, table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks = output / "chunks"
    chunks.mkdir(exist_ok=True)
    output_rows = rows or []
    result = []
    for offset in range(0, len(output_rows), CHUNK_ROWS):
        payload = json.dumps(
            _finite(output_rows[offset : offset + CHUNK_ROWS]), ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        relative = f"chunks/{table}-{offset // CHUNK_ROWS + 1:04d}.json.gz"
        target = output / relative
        with target.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                zipped.write(payload)
        result.append({"table": table, "path": relative, "rows": min(CHUNK_ROWS, len(output_rows) - offset), "sha256": _sha(target), "compression": "gzip"})
    return result


def _meta_securities(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    connection = _readonly(path)
    try:
        frame = pd.read_sql_query("SELECT code, name, market, industry_category, is_etf, security_category, fetched_at FROM symbol_meta", connection)
    finally:
        connection.close()
    included, excluded = [], []
    for row in frame.to_dict("records"):
        code = str(row["code"])
        market = str(row.get("market") or "")
        ordinary = row.get("is_etf") in (0, False) and row.get("security_category") == "股票" and market in {"TWSE", "TPEX", "上市", "上櫃"}
        if ordinary:
            included.append({
                "security_id": f"TW:{code}",
                "code": code,
                "name": str(row.get("name") or code),
                "market": {"上市": "TWSE", "上櫃": "TPEX"}.get(market, market),
                "source_market": market,
                "metadata_fetched_at": row.get("fetched_at"),
                "official_industry": row.get("industry_category"),
            })
        else:
            excluded.append({"code": code, "reason": "not_twse_tpex_ordinary_stock", "market": market})
    return sorted(included, key=lambda item: item["security_id"]), sorted(excluded, key=lambda item: item["code"])


def _actions(path: Path, code: str) -> pd.DataFrame:
    connection = _readonly(path)
    try:
        frame = pd.read_sql_query(
            "SELECT * FROM corporate_actions WHERE code = ? AND ex_date >= ? AND ex_date <= ?", connection, params=[code, WINDOW_START, WINDOW_END]
        )
    finally:
        connection.close()
    if frame.empty:
        return pd.DataFrame({
            "Code": pd.Series(dtype="object"),
            "Date": pd.Series(dtype="datetime64[ns]"),
            "event_type": pd.Series(dtype="object"),
            "price_factor": pd.Series(dtype="float64"),
            "previous_close": pd.Series(dtype="float64"),
        })
    rename = {"code": "Code", "ex_date": "Date"}
    frame = frame.rename(columns=rename)
    frame["Date"] = pd.to_datetime(frame["Date"])
    for column in ("event_type", "price_factor", "previous_close"):
        if column not in frame:
            frame[column] = None
    return frame


def _load_prices(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise CatalogIOError(f"required input missing: {path}")
    return pd.read_parquet(
        path,
        columns=["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Source"],
        filters=[("Date", ">=", pd.Timestamp(WINDOW_START)), ("Date", "<=", pd.Timestamp(WINDOW_END)), ("Source", "==", "official")],
    )


QUALITY_FLAG_BY_REASON = {
    "invalid_price_or_volume": "invalid_price_removed",
    "duplicate_date": "duplicate_date",
    "unsupported_action_factor": "unsupported_action_factor",
    "unexplained_extreme_jump": "unexplained_extreme_jump",
    "missing_or_invalid_volume": "missing_or_invalid_volume",
}


def _path_quality_flags(findings: list[dict[str, Any]], start_date: str, end_date: str) -> tuple[str, ...]:
    """Return adapter findings dated inside one requested comparison interval."""
    return tuple(
        sorted({
            QUALITY_FLAG_BY_REASON[finding["reason"]]
            for finding in findings
            if finding.get("reason") in QUALITY_FLAG_BY_REASON and isinstance(finding.get("date"), str) and start_date <= finding["date"] <= end_date
        })
    )


def _bars_for_code(frame: pd.DataFrame, actions: pd.DataFrame, loader: DataLoader) -> tuple[tuple[CatalogBar, ...], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    clean = frame.copy()
    clean["Date"] = pd.to_datetime(clean["Date"])
    clean = clean.sort_values("Date", kind="stable")
    duplicate_dates = clean.loc[clean.duplicated("Date", keep="first"), "Date"]
    clean = clean.drop_duplicates("Date", keep="first")
    bad = ~clean["Close"].map(lambda value: pd.notna(value) and math.isfinite(float(value)) and float(value) > 0)
    for code, timestamp in clean.loc[bad, ["Code", "Date"]].itertuples(index=False, name=None):
        records.append({"code": str(code), "date": _iso_day(timestamp), "reason": "invalid_price_or_volume"})
    clean = clean.loc[~bad].copy()
    if clean.empty:
        return (), records
    adapter_actions = actions.copy()
    adapter_actions["price_factor"] = pd.to_numeric(adapter_actions["price_factor"], errors="coerce")
    adapter_actions["previous_close"] = pd.to_numeric(adapter_actions["previous_close"], errors="coerce")
    known_action_types = PERMANENT_FACTOR_EVENTS | CASH_WINDOW_EVENTS
    adapter_actions = adapter_actions.loc[
        adapter_actions["event_type"].isin(sorted(known_action_types)) & adapter_actions["price_factor"].map(_usable_factor)
    ].copy()
    clean = loader._apply_corporate_action_policy(clean, adapter_actions)
    day_list = clean["Date"].dt.strftime("%Y-%m-%d").tolist()
    inherited: dict[str, set[str]] = {}

    def flag_at_or_after(day: str, flag: str) -> None:
        index = bisect.bisect_left(day_list, day)
        if index < len(day_list):
            inherited.setdefault(day_list[index], set()).add(flag)

    def flag_at_or_after_or_last(day: str, flag: str) -> None:
        index = bisect.bisect_left(day_list, day)
        target = day_list[index] if index < len(day_list) else day_list[-1]
        inherited.setdefault(target, set()).add(flag)

    for day in duplicate_dates:
        flag_at_or_after(_iso_day(day), "duplicate_date")
        records.append({"code": str(clean.iloc[0]["Code"]), "date": _iso_day(day), "reason": "duplicate_date"})
    for finding in records:
        if finding["reason"] == "invalid_price_or_volume":
            flag_at_or_after_or_last(finding["date"], "invalid_price_removed")
    action_rows: list[dict[str, Any]] = [dict(item) for item in actions.to_dict("records")]
    for action in action_rows:
        kind = action["event_type"]
        factor = action.get("price_factor")
        unusable = not _usable_factor(factor)
        if (kind in PERMANENT_FACTOR_EVENTS and unusable) or kind not in PERMANENT_FACTOR_EVENTS | CASH_WINDOW_EVENTS:
            day = _iso_day(action["Date"])
            flag_at_or_after(day, "unsupported_action_factor")
            records.append({"code": str(clean.iloc[0]["Code"]), "date": day, "reason": "unsupported_action_factor", "event_type": kind})
    bars: list[CatalogBar] = []
    previous: float | None = None
    selected_columns = clean[["Code", "Date", "SplitAdjustedClose", "RawClose", "Volume"]]
    for code, timestamp, split_adjusted_close, raw_close, volume in selected_columns.itertuples(index=False, name=None):
        day = _iso_day(timestamp)
        flags = set(inherited.get(day, set()))
        close = float(split_adjusted_close)
        if previous is not None and abs(close / previous - 1) >= 0.40:
            flags.add("unexplained_extreme_jump")
            records.append({"code": str(code), "date": day, "reason": "unexplained_extreme_jump"})
        previous = close
        valid_volume = pd.notna(volume) and math.isfinite(float(volume)) and float(volume) >= 0
        turnover = float(raw_close * volume) if valid_volume else None
        if not valid_volume:
            flags.add("missing_or_invalid_volume")
            records.append({"code": str(code), "date": day, "reason": "missing_or_invalid_volume"})
        bars.append(CatalogBar(day, close, float(raw_close), turnover, tuple(sorted(flags))))
    return tuple(bars), records


def build_bundle(repo_root: Path, output_dir: Path, run_id: str) -> dict[str, Any]:
    """Build one immutable descriptive bundle.  The caller supplies no market paths."""
    repo_root, output_dir = repo_root.resolve(), output_dir.resolve()
    task_root = (repo_root / "tasks" / TASK_NAME).resolve()
    if not output_dir.is_relative_to(task_root) or not isinstance(run_id, str) or not run_id:
        raise CatalogIOError("output must be below this task and run_id must be nonempty")
    paths = _paths(repo_root)
    identities = {name: _input_sha(name, path) for name, path in paths.items()}
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise CatalogIOError("output directory already exists") from error
    prices = _load_prices(paths["price"])
    price_by_code: dict[str, pd.DataFrame] = {str(code): frame for code, frame in prices.groupby("Code", sort=False)}
    securities, exclusions = _meta_securities(paths["meta"])
    groups, securities, taxonomy_nodes = build_groups(_json(paths["taxonomy"]), _json(paths["config"]), securities)
    loader = DataLoader(paths["price"].parent)
    bars_by_id: dict[str, tuple[CatalogBar, ...]] = {}
    dates_by_id: dict[str, list[str]] = {}
    episodes: list[dict[str, Any]] = []
    quality = exclusions[:]
    metadata_codes = {item["code"] for item in securities}
    quality.extend({"code": code, "reason": "price_code_without_ordinary_stock_metadata"} for code in sorted(price_by_code.keys() - metadata_codes))
    episodes_by_security: dict[str, list[dict[str, Any]]] = {}
    findings_by_security: dict[str, list[dict[str, Any]]] = {}
    for security_index, security in enumerate(securities):
        code = security["code"]
        rows = price_by_code.get(code)
        if rows is None:
            rows = prices.iloc[0:0]
        actions = _actions(paths["actions"], code)
        bars, findings = _bars_for_code(rows, actions, loader)
        findings_by_security[security["security_id"]] = findings
        bars_by_id[security["security_id"]] = bars
        dates_by_id[security["security_id"]] = [bar.date for bar in bars]
        quality.extend(findings)
        security["price_coverage_status"] = "observed" if bars else "no_bars"
        security["price_bar_count"] = len(bars)
        security["observed_start_date"] = bars[0].date if bars else None
        security["observed_end_date"] = bars[-1].date if bars else None
        security["zero_volume_count"] = sum(bar.turnover_k_twd == 0 for bar in bars)
        own_episodes = detect_episodes(code, bars)
        episodes_by_security[security["security_id"]] = own_episodes
        for episode in own_episodes:
            episode["observed_end_date"] = episode["confirmation_date"] or bars[-1].date
            episode["corporate_actions"] = _finite([
                {**action, "Date": _iso_day(action["Date"])}
                for action in [dict(item) for item in actions.to_dict("records")]
                if episode["start_date"] <= _iso_day(action["Date"]) <= episode["observed_end_date"]
            ])
            if episode["right_censored"]:
                episode["observed_end_date"] = bars[-1].date
                episode["censor_reason"] = "window_end" if bars[-1].date == WINDOW_END else "security_data_ended_early"
            episodes.append(episode)
        if security_index % 200 == 0:
            LOGGER.info("Processed %d/%d securities", security_index + 1, len(securities))
    waves, peers = [], []
    by_security = {security["security_id"]: security for security in securities}
    for group_index, group in enumerate(groups):
        members = set(group["member_security_ids"])
        seeds = [episode for episode in episodes if episode["security_id"] in members and not episode["quality_flags"]]
        if group["kind"] == "official_chain":
            seeds = [episode for episode in seeds if not any(not item.startswith("official:") for item in by_security[episode["security_id"]]["group_ids"])]
        for wave in cluster_waves(group["group_id"], seeds):
            wave_peers = []
            for security_id in sorted(members):
                dates = dates_by_id[security_id]
                own_bars = bars_by_id[security_id]
                window_bars = own_bars[bisect.bisect_left(dates, wave["start_date"]) : bisect.bisect_right(dates, wave["end_date"])]
                peer = compare_peer(
                    wave["wave_id"],
                    security_id,
                    window_bars if window_bars else own_bars,
                    wave["start_date"],
                    wave["end_date"],
                    path_quality_flags=_path_quality_flags(findings_by_security[security_id], wave["start_date"], wave["end_date"]),
                )
                peer["peer_id"] = _stable_id("peer", wave["wave_id"], security_id)
                peer["episode_ids"] = [
                    episode["episode_id"]
                    for episode in episodes_by_security[security_id]
                    if episode["start_date"] <= wave["end_date"] and episode["peak_date"] >= wave["start_date"]
                ]
                peers.append(peer)
                wave_peers.append(peer)
            wave["peer_ids"] = [peer["peer_id"] for peer in wave_peers]
            wave["winner_security_id"] = select_wave_winner(wave_peers)
            waves.append(wave)
        if group_index % 10 == 0:
            LOGGER.info("Compared %d/%d groups", group_index + 1, len(groups))
    tables = {
        "securities": securities,
        "groups": groups,
        "taxonomy_nodes": taxonomy_nodes,
        "episodes": episodes,
        "waves": waves,
        "peers": peers,
        "quality_findings": quality,
    }
    chunks = [chunk for table, rows in tables.items() for chunk in _write_chunks(output_dir, table, rows)]
    if identities != {name: _input_sha(name, path) for name, path in paths.items()}:
        raise CatalogIOError("input changed while building catalog")
    manifest = {
        "schema_version": "sector-wave-catalog.v1",
        "run_id": run_id,
        "definition_id": DEFINITION_ID,
        "classification_snapshot_id": _json(paths["taxonomy"])["snapshot_id"],
        "classification_fetched_at": _json(paths["taxonomy"]).get("fetched_at"),
        "classification_mode": "retrospective",
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "units": {"appreciation_fraction": "fraction", "price": "TWD", "turnover_k_twd": "thousand_TWD"},
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "runtime": {"python": sys.version.split()[0], "pandas": pd.__version__, "pyarrow": version("pyarrow"), "numpy": version("numpy")},
        "counts": {table: len(rows) for table, rows in tables.items()},
        "coverage": {
            "excluded": len(exclusions),
            "quarantined_episodes": sum(bool(item["quality_flags"]) for item in episodes),
            "securities_without_price": sum(item["price_coverage_status"] == "no_bars" for item in securities),
            "securities_without_classification": sum(item["coverage_status"] == "source_missing" for item in securities),
            "price_codes_without_ordinary_metadata": len(price_by_code.keys() - metadata_codes),
        },
        "limitations": [
            "Retrospective descriptive catalog, not a predictive or executable strategy.",
            "Cash dividends excluded; rights/capital-reduction factors are price bridges, not execution PnL.",
            "Current business labels and company names do not establish historical business membership.",
            "Current metadata and incomplete TWSE delisted coverage can omit historical stocks; missing identity is reported.",
            "2019 opening and 2026 ending boundaries are partial; unconfirmed episodes are censored.",
            "Family/subgroup and overlapping wave views are dependent and must not be summed as independent events.",
        ],
        "input_identities_sha256": identities,
        "input_identity_policy": {
            "text": "sha256-universal-newlines.v1",
            "text_keys": list(TEXT_INPUT_KEYS),
            "raw_bytes_keys": [name for name in paths if name not in TEXT_INPUT_KEYS],
        },
        "input_paths": {
            name: str(path.relative_to(repo_root)).replace(os.sep, "/") if path.is_relative_to(repo_root) else str(path) for name, path in paths.items()
        },
        "chunks": chunks,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    validate_bundle(output_dir)
    canonical_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    (output_dir / "completion-receipt.json").write_text(
        json.dumps({"run_id": run_id, "manifest_canonical_sha256": canonical_hash, "counts": manifest["counts"]}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_bundle(output_dir: Path) -> None:
    manifest = _json(output_dir / "manifest.json")
    if manifest.get("schema_version") != "sector-wave-catalog.v1":
        raise CatalogIOError("invalid manifest schema")
    loaded: dict[str, list[dict[str, Any]]] = {}
    for chunk in manifest.get("chunks", []):
        path = (output_dir / chunk["path"]).resolve()
        if not path.is_relative_to(output_dir.resolve()):
            raise CatalogIOError("chunk path leaves bundle")
        if _sha(path) != chunk["sha256"]:
            raise CatalogIOError("chunk hash mismatch")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = json.load(handle)
        if not isinstance(rows, list) or len(rows) != chunk["rows"] or any(not isinstance(row, dict) for row in rows):
            raise CatalogIOError("invalid chunk rows")
        finite_json(rows)
        loaded.setdefault(chunk["table"], []).extend(rows)
    if {key: len(value) for key, value in loaded.items()} != {key: value for key, value in manifest["counts"].items() if value}:
        raise CatalogIOError("manifest counts mismatch")
    for table, identity in (("securities", "security_id"), ("groups", "group_id"), ("episodes", "episode_id"), ("waves", "wave_id"), ("peers", "peer_id")):
        values = [row[identity] for row in loaded.get(table, [])]
        if len(values) != len(set(values)):
            raise CatalogIOError(f"duplicate {identity}")
    security_rows = {row["security_id"]: row for row in loaded.get("securities", [])}
    securities = set(security_rows)
    groups = {row["group_id"]: row for row in loaded.get("groups", [])}
    episodes = {row["episode_id"] for row in loaded.get("episodes", [])}
    waves = {row["wave_id"] for row in loaded.get("waves", [])}
    peers = {row["peer_id"]: row for row in loaded.get("peers", [])}
    findings_by_code: dict[str, list[dict[str, Any]]] = {}
    for finding in loaded.get("quality_findings", []):
        findings_by_code.setdefault(finding["code"], []).append(finding)
    for security in loaded.get("securities", []):
        if not set(security["group_ids"]) <= groups.keys():
            raise CatalogIOError("unresolved security group")
    for group in groups.values():
        if not set(group["member_security_ids"]) <= securities:
            raise CatalogIOError("unresolved group security")
    for episode in loaded.get("episodes", []):
        if episode["security_id"] not in securities:
            raise CatalogIOError("unresolved episode security")
    for peer in peers.values():
        if peer["wave_id"] not in waves or peer["security_id"] not in securities or not set(peer["episode_ids"]) <= episodes:
            raise CatalogIOError("unresolved peer reference")
        expected_flags = _path_quality_flags(
            findings_by_code.get(security_rows[peer["security_id"]]["code"], []),
            peer["requested_start_date"],
            peer["requested_end_date"],
        )
        if not set(expected_flags) <= set(peer["quality_flags"]):
            raise CatalogIOError("peer missing quality flags")
        has_returns = peer.get("common_window_endpoint_appreciation_fraction") is not None
        if peer["quality_flags"] and has_returns and peer["comparability_status"] == "comparable":
            raise CatalogIOError("quality peer marked comparable")
    for wave in loaded.get("waves", []):
        if wave["group_id"] not in groups or not set(wave["episode_ids"]) <= episodes or not set(wave["peer_ids"]) <= peers.keys():
            raise CatalogIOError("unresolved wave reference")
        winner = wave.get("winner_security_id")
        own_peers = [peers[peer_id] for peer_id in wave["peer_ids"]]
        if any(peer["wave_id"] != wave["wave_id"] for peer in own_peers) or {peer["security_id"] for peer in own_peers} != set(
            groups[wave["group_id"]]["member_security_ids"]
        ):
            raise CatalogIOError("invalid wave peer membership")
        if winner != select_wave_winner(own_peers):
            raise CatalogIOError("invalid wave winner")
    receipt_path = output_dir / "completion-receipt.json"
    if receipt_path.is_file():
        receipt = _json(receipt_path)
        canonical_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        if receipt.get("manifest_canonical_sha256") != canonical_hash or receipt.get("counts") != manifest["counts"]:
            raise CatalogIOError("receipt mismatch")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    build_bundle(Path(__file__).resolve().parents[1], args.output_dir, args.run_id)


if __name__ == "__main__":
    main()
