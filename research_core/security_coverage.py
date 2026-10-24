"""Conservative security identity and presence projections; no acquisition or PIT claim."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from research_core.artifact_store import object_digest

SCHEMA = "security-coverage.v1"
FAMILY = "security-coverage-v1"
MARKETS = ("TWSE", "TPEx")
DATASETS = (
    ("official_daily", "每日官方股價", "daily"),
    ("price_daily", "整合每日股價", "daily"),
    ("institutional", "三大法人", "daily"),
    ("monthly_revenue", "月營收", "monthly"),
    ("corporate_actions", "公司行動", "events"),
    ("symbol_meta", "名稱與產業", "observation"),
    ("adjusted_daily", "還原股價與指標", "daily"),
)
DATASET_IDS = frozenset(item[0] for item in DATASETS)


def normalized_market(value: object) -> str:
    return {"TWSE": "TWSE", "TSE": "TWSE", "TPEx": "TPEx", "OTC": "TPEx"}.get(str(value), "unknown")


def security_key(market: str, code: str, start: str | None = None) -> str:
    """Opaque source-observed key, not a permanent issuer identifier."""
    return "s_" + object_digest([market, code, start])[:24]


def _kind(meta: dict[str, Any]) -> str:
    if meta.get("is_etf") in (1, True):
        return "etf"
    if meta.get("security_category") in ("股票", "創新板"):
        return "stock"
    return "unknown"


def _cell(
    dataset: str,
    summary: dict[str, Any] | None,
    source: dict[str, Any],
    *,
    first: str | None,
    last: str | None,
    listed: str | None,
    ambiguous: bool,
    as_of: str,
) -> dict[str, Any]:
    observation = dataset == "symbol_meta"
    period = {"from": summary.get("first") if summary else None, "to": summary.get("last") if summary else None}
    reasons: list[str] = []
    read_status = source.get("status", "unavailable")
    rows = summary.get("rows") if summary else None
    exists = "unknown"
    mark = "unknown"
    completeness = "unknown"
    if read_status == "ok":
        if summary is None:
            rows = 0
            exists = "absent"
            reasons.append("no_observations")
            # A successful scan proves absence, not applicability or an obligation to report.
        else:
            exists = "present" if rows else "absent"
            if rows:
                mark = "present"
                reasons.append("historical_completeness_unverified")
            if dataset == "institutional" and rows:
                floor = source.get("first_by_market", {}).get(summary.get("market"), source.get("first"))
                # A known global stored-history gap is only assigned to an eligible old listing.
                if floor and floor >= "2019-01-01" and listed and listed < "2019-01-01":
                    mark = "partial"
                    completeness = "partial"
                    reasons.append("stored_history_before_2019_missing")
                elif not listed:
                    reasons.append("listing_period_unverified")
            if dataset == "corporate_actions":
                reasons.append("event_absence_does_not_prove_missing")
            if dataset == "monthly_revenue":
                reasons.append("current_revision_not_point_in_time")
            if dataset == "adjusted_daily":
                reasons.append("price_basis_and_warmup_apply")
    else:
        reasons.append(source.get("reason", "source_unavailable"))
    if ambiguous:
        reasons.append("identity_unresolved")
    if first is not None or last is not None:
        reasons.append("bounded_identity_segment")
    return {
        "dataset": dataset,
        "mark": mark,
        "existence": exists,
        "applicability": "unknown",
        "completeness": completeness,
        "read_status": read_status,
        "freshness": "unknown",
        "rows": rows,
        "period": period,
        "assessment_period": {"from": first or listed, "to": last or as_of},
        "assessment_scope": "presence_and_known_gaps",
        "input_identity": source.get("input_fingerprint") or source.get("input_identifier"),
        "checked_at": source.get("checked_at"),
        "time_kind": "observed" if observation else "data",
        "reasons": reasons,
    }


def project_security_coverage(sources: dict[str, dict[str, Any]], metadata: list[dict[str, Any]], *, built_at: str, as_of: str) -> dict[str, Any]:
    """Union source-observed market/code keys without guessing historical identity.

    Per-source members use market/code and can already be split into bounded segments.
    An unresolved segment never receives the latest company's name.
    """
    meta_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    universe: set[tuple[str, str]] = set()
    for meta in metadata:
        market, code = normalized_market(meta.get("market")), str(meta["code"])
        universe.add((market, code))
        meta_by_key[(market, code)] = meta
    for source in sources.values():
        universe.update((normalized_market(row.get("market")), str(row["code"])) for row in source.get("members", []))
    source_index = {
        dataset: {(normalized_market(row.get("market")), str(row["code"])): row for row in source.get("members", [])} for dataset, source in sources.items()
    }
    securities = []
    recent_floor = (date.fromisoformat(as_of) - timedelta(days=14)).isoformat()
    for market, code in sorted(universe):
        meta = meta_by_key.get((market, code), {})
        listed = meta.get("listed_date")
        rows_by_source = {dataset: mapping.get((market, code)) for dataset, mapping in source_index.items()}
        chronological = [item for dataset, item in rows_by_source.items() if item and dataset != "symbol_meta"]
        actual_first = min((item["first"] for item in chronological if item.get("first")), default=None)
        actual_last = max((item["last"] for item in chronological if item.get("last")), default=None)
        boundary_set = {gap[1] for item in chronological for gap in item.get("gaps", [])}
        identity_first = min(
            (
                item["first"]
                for dataset, item in rows_by_source.items()
                if item and dataset in ("official_daily", "institutional", "price_daily", "adjusted_daily") and item.get("first")
            ),
            default=None,
        )
        reused = bool(listed and identity_first and identity_first < listed)
        if reused:
            boundary_set.add(listed)
        boundaries = sorted(boundary_set)
        starts: list[str | None] = [None, *boundaries]
        for position, start in enumerate(starts):
            end = (date.fromisoformat(boundaries[position]) - timedelta(days=1)).isoformat() if position < len(boundaries) else None
            ambiguous = bool(boundaries) or market == "unknown"
            old_segment = bool(end)
            cells = []
            for dataset, _, _ in DATASETS:
                source = sources.get(dataset, {"status": "unavailable"})
                item = rows_by_source.get(dataset)
                # Aggregate counts cannot be divided across identity segments without raw reads.
                # Keep availability unknown rather than attach all old rows to each segment.
                if ambiguous:
                    item = None
                    source = {**source, "status": "unavailable", "reason": "identity_segment_summary_required"}
                cells.append(_cell(dataset, item, source, first=start, last=end, listed=listed if not old_segment else None, ambiguous=ambiguous, as_of=as_of))
            explicit_status = meta.get("listing_status")
            listing_status = explicit_status if explicit_status in ("listed", "delisted") and meta.get("listing_evidence") else "unknown"
            securities.append({
                "key": security_key(market, code, start),
                "market": market,
                "code": code,
                "name": None if old_segment or market == "unknown" else meta.get("name"),
                "kind": "unknown" if old_segment else _kind(meta),
                "identity_status": "unresolved" if ambiguous else "provisional",
                "listing_status": listing_status,
                "listing_evidence": meta.get("listing_evidence"),
                "activity": "recent" if not old_segment and actual_last and actual_last >= recent_floor else "historical",
                "listed_date": listed if not old_segment else None,
                "observed_at": meta.get("fetched_at") if not old_segment else None,
                "segment": {"from": start, "to": end},
                "period": {"from": actual_first if not ambiguous else None, "to": actual_last if not ambiguous else None},
                "reasons": (["possible_code_reuse"] if reused else []) + (["long_observation_gap"] if boundaries and not reused else []),
                "can_view_prices": not ambiguous and sources.get("official_daily", {}).get("status") == "ok" and bool(rows_by_source.get("adjusted_daily")),
                "coverage": cells,
            })
    return {
        "schema": SCHEMA,
        "status": "ok" if all(sources.get(dataset, {}).get("status") == "ok" for dataset in DATASET_IDS) else "partial",
        "family": FAMILY,
        "built_at": built_at,
        "as_of": as_of,
        "universe": "source-observed securities; not a complete historical listing universe",
        "datasets": [{"id": item[0], "name": item[1], "frequency": item[2]} for item in DATASETS],
        "sources": {key: {k: v for k, v in value.items() if k != "members"} for key, value in sources.items()},
        "securities": securities,
    }
