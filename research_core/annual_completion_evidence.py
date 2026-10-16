"""Admit captured source facts for the fixed annual-winner completion.

This adapter reads a canonical producer supplement, never a task-local input
copy. Its versioned, study-specific mappings turn explicit source terms into
research entitlements; unsupported or conflicting terms block that holding.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.annual_rotation_v2 import Entitlement
from research_core.artifact_store import read_json, relative_name, safe_path

CANDIDATE = "captured/annual-winner-supplement-candidate.v1.json"
PRECISION = Decimal("0.000001")


@dataclass
class Evidence:
    manifest: dict[str, Any]
    members: dict[str, bytes]
    retained_bytes: int
    verification_seconds: float

    def json(self, name: str) -> dict[str, Any]:
        value = json.loads(self.members[relative_name(name)])
        if not isinstance(value, dict):
            raise ValueError(f"object required: {name}")
        return value

    def jsonl(self, name: str) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.members[relative_name(name)].splitlines() if line.strip()]


@dataclass
class Admission:
    entitlements: tuple[Entitlement, ...]
    unavailable_by_code: dict[str, dict[str, str]]
    audit: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]


def load_verified_evidence(root: Path) -> Evidence:
    """Read/hash each bounded member once, then consume those same bytes."""
    started = time.perf_counter()
    root = safe_path(root)
    manifest = read_json(root / "publication.json")
    if manifest.get("schema") != "annual-source-evidence.v1":
        raise ValueError("unsupported source publication")
    members: dict[str, bytes] = {}
    total = 0
    for name, identity in manifest["members"].items():
        path = safe_path(root / relative_name(name))
        size = identity["bytes"]
        if not isinstance(size, int) or not 0 <= size <= 32_000_000:
            raise ValueError(f"source member exceeds size limit: {name}")
        with path.open("rb") as stream:
            raw = stream.read(size + 1)
        total += len(raw)
        if total > 128_000_000 or len(raw) != size or hashlib.sha256(raw).hexdigest() != identity["sha256"]:
            raise ValueError(f"source member identity mismatch: {name}")
        members[name] = raw
    evidence = Evidence(manifest, members, total, time.perf_counter() - started)
    for source in evidence.json(CANDIDATE)["sources"]:
        body = source["raw_body"]
        identity = manifest["members"].get("captured/" + relative_name(body["path"]))
        if identity is None or any(identity[key] != body[key] for key in ("bytes", "sha256")):
            raise ValueError(f"unbound source fact: {source['evidence_id']}")
    return evidence


def agreed(issuer: Decimal, exchange: Decimal) -> Decimal:
    """R8: six decimals in the source units, never an average."""
    left = issuer.quantize(PRECISION, rounding=ROUND_HALF_EVEN)
    right = exchange.quantize(PRECISION, rounding=ROUND_HALF_EVEN)
    if left != right:
        raise ValueError(f"source term conflict: {issuer} versus {exchange}")
    return left


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation as error:
        raise ValueError("missing/non-numeric source term") from error
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("source term must be finite and nonnegative")
    return parsed


def _date(event: dict[str, Any], role: str) -> str:
    matches = [item["date"] for item in event["date_roles"] if item["role"] == role]
    if len(matches) != 1:
        raise ValueError(f"unique date role required: {role}")
    return str(matches[0])


def _fact(event: dict[str, Any], attribute: str, unit: str) -> Decimal:
    matches = [item for item in event["source_facts"] if item["attribute"] == attribute]
    if len(matches) != 1 or matches[0]["unit"] != unit or matches[0]["fact_status"] != "source_explicit" or not matches[0]["evidence_ids"]:
        raise ValueError(f"explicit source units required: {attribute}")
    return _decimal(matches[0]["raw_value"])


def _stated(fields: dict[str, Any], name: str) -> Any:
    field = fields[name]
    if field["status"] != "stated" or field["value"] is None:
        raise ValueError(f"stated projection required: {name}")
    return field["value"]


def _exchange(evidence: Evidence, code: str, date: str) -> dict[str, Any]:
    table = evidence.json(f"captured/tpex-current/exdailyq-{code}-{date}.json")["tables"][0]
    records = [dict(zip(table["fields"], row, strict=True)) for row in table["data"]]
    roc_date = f"{int(date[:4]) - 1911}/{date[5:7]}/{date[8:10]}"
    matches = [row for row in records if str(row["代號"]).strip() == code and row["除權息日期"] == roc_date]
    if len(matches) != 1:
        raise ValueError("unique exchange code/date record required")
    return matches[0]


def _literal_number(fields: dict[str, Any], label: str, unit: str) -> Decimal:
    match = re.fullmatch(r"\s*([\d.,]+)\s*" + re.escape(unit) + r"\s*", fields[label])
    if match is None:
        raise ValueError(f"explicit literal unit required: {label}")
    return _decimal(match[1])


def _twse_literal(evidence: Evidence, code: str, date: str) -> dict[str, Any]:
    matches = [
        row
        for row in evidence.jsonl(f"captured/capture-{code}/events.jsonl")
        if row["effective_date_from_annual_row"] == date and str(row["literal_fields"]["股票代號"]).strip() == code
    ]
    if len(matches) != 1:
        raise ValueError("unique TWSE literal code/date required")
    return matches[0]["literal_fields"]


def _valid_day(prices: pd.DataFrame, code: str, date: str, *, first_after: bool = False) -> str:
    rows = prices.loc[prices.Code.astype(str).eq(code) & prices.Date.ge(pd.Timestamp(date))]
    if not first_after:
        rows = rows.loc[rows.Date.eq(pd.Timestamp(date))]
    rows = rows.sort_values("Date")
    if rows.Date.duplicated().any():
        raise ValueError("duplicate quote at entitlement application")
    values = rows[["Open", "High", "Low", "Close"]].to_numpy(dtype=float)
    valid = np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
    valid &= (values[:, 1] >= values.max(axis=1)) & (values[:, 2] <= values.min(axis=1))
    if not valid.any():
        raise ValueError("observed event quote required")
    return str(rows.loc[valid, "Date"].iloc[0].date())


def _rights_terms(evidence: Evidence, event: dict[str, Any]) -> tuple[str, Decimal, Decimal, Decimal, Decimal]:
    code = event["code"]
    records = [item for item in evidence.json("rights-projections-v2.json")["records"] if item["company_id"] == code]
    if len(records) != 1:
        raise ValueError("unique rights projection required")
    record = records[0]
    identity = evidence.manifest["members"]["captured/" + record["capture_relative_path"]]
    if identity["sha256"] != record["body_sha256"]:
        raise ValueError("unbound rights projection")
    date = _stated(record["fields"], "stated_ex_date")
    if date != _date(event, "study_input_ex_date"):
        raise ValueError("rights ex-date linkage conflict")
    if code == "3406":
        # The producer projection explicitly reports this older template as
        # unsupported. Reuse its captured TWSE literal projection; blank MOPS
        # cash is never interpreted as zero.
        fields = _twse_literal(evidence, code, date)
        bonus = _literal_number(fields, "A. 按普通股股東持股比例每千股無償配股", "股")
        cash = _literal_number(fields, "(每股配發現金股利)除息", "元／股")
        rights = _literal_number(fields, "按股東持股比例每千股認購", "股")
        price = _literal_number(fields, "每股認購金額", "元／股")
    else:
        fields = record["rights_fields"]
        if _stated(fields, "subscription_class") != "普通股":
            raise ValueError("ordinary-share terms required")
        exchange = _exchange(evidence, code, date)
        bonus = agreed(
            _decimal(_stated(fields, "earnings_free_per_thousand")) + _decimal(_stated(fields, "reserves_free_per_thousand")),
            _decimal(exchange["每仟股無償配股"]),
        )
        cash = agreed(_decimal(_stated(record["fields"], "cash_per_share")), _decimal(exchange["現金股利"]))
        rights = agreed(_decimal(_stated(fields, "subscription_per_thousand")), _decimal(exchange["按持股比例仟股認購"]))
        price = agreed(_decimal(_stated(fields, "subscription_price")), _decimal(exchange["現金增資認購價"]))
    return date, bonus, cash, rights, price


def _entitlement(evidence: Evidence, event: dict[str, Any], prices: pd.DataFrame, calendar: pd.DatetimeIndex) -> Entitlement:
    code, kind = event["code"], event["event_type"]
    multiplier, cash, rights, price = Decimal(1), Decimal(0), Decimal(0), None
    if code in {"3406", "3205"}:
        announced, bonus, cash, rights, price = _rights_terms(evidence, event)
        multiplier += bonus / 1000
        effective = _valid_day(prices, code, announced)
    elif kind == "LOSS_OFFSET_CAPITAL_REDUCTION":
        announced = _date(event, "resumption_date")
        multiplier = (1000 - _fact(event, "shares_reduced_per_1000_existing", "shares_per_1000_existing_shares")) / 1000
        effective = _valid_day(prices, code, announced, first_after=True)
    elif kind == "PAR_VALUE_CHANGE":
        announced = _date(event, "new_shares_start_trading")
        multiplier = _fact(event, "new_shares_per_old_share", "new_shares_per_old_share")
        if multiplier != _fact(event, "old_par_value", "NTD_per_share") / _fact(event, "new_par_value", "NTD_per_share"):
            raise ValueError("par-value/share ratio conflict")
        effective = _valid_day(prices, code, announced, first_after=True)
    else:
        bonus = _fact(event, "new_shares_per_1000_old_shares", "new_shares_per_1000_old_shares")
        cash = _fact(event, "cash_dividend_per_share", "NTD_per_share")
        if code == "6538":
            announced = _date(event, "study_input_ex_date")
            exchange = _exchange(evidence, code, announced)
            bonus = agreed(bonus, _decimal(exchange["每仟股無償配股"]))
            cash = agreed(cash, _decimal(exchange["現金股利"]))
            effective = _valid_day(prices, code, announced)
        else:
            announced = _date(event, "announced_ex_date")
            effective = _date(event, "price_adjustment_trading_date")
            # R6 permits only a documented closure plus exchange carry rule.
            derivations = event["date_derivations"]
            required = {"ev-twse-close-0723", "ev-twse-close-0724", "ev-twse-disaster-faq", "ev-twse-report-0726"}
            following = calendar[calendar > pd.Timestamp(announced)]
            if (
                len(derivations) != 1
                or derivations[0]["status"] != "inferred_official_rule"
                or derivations[0]["date"] != effective
                or not required.issubset(derivations[0]["evidence_ids"])
                or pd.Timestamp(announced) in calendar
                or following.empty
                or following[0] != pd.Timestamp(effective)
            ):
                raise ValueError("official closure/date rule evidence required")
            fields = _twse_literal(evidence, code, announced)
            bonus = agreed(bonus, _literal_number(fields, "A. 按普通股股東持股比例每千股無償配股", "股"))
            cash = agreed(cash, _literal_number(fields, "(每股配發現金股利)除息", "元／股"))
            if _valid_day(prices, code, effective) != effective:
                raise ValueError("observed resumption quote required")
        multiplier += bonus / 1000
    return Entitlement(
        code=code,
        effective_date=effective,
        announced_date=announced,
        share_multiplier=float(multiplier),
        cash_per_old_share=float(cash),
        rights_per_old_share=float(rights / 1000),
        subscription_price=None if price is None else float(price),
        evidence_ids=tuple(event["source_evidence_ids"]),
        kind=kind,
        source_event_type=kind if kind != "PAR_VALUE_CHANGE" else None,
    )


def _unresolved_event(event: dict[str, Any], reason: str) -> dict[str, Any]:
    economic_roles = {
        "study_input_ex_date",
        "announced_ex_date",
        "price_adjustment_trading_date",
        "effective_date",
        "resumption_date",
        "new_shares_start_trading",
    }
    dates: list[str] = []
    for role in event.get("date_roles", []):
        value = role.get("date")
        if role.get("role") not in economic_roles or not isinstance(value, str):
            continue
        try:
            parsed = dt.date.fromisoformat(value)
        except ValueError:
            continue
        if parsed.isoformat() == value and value not in dates:
            dates.append(value)
    dates.sort()
    return {"code": event["code"], "year": int(dates[0][:4]) if dates else None, "event_dates": dates, "reasons": [reason]}


def _validate_entitlement_sources(event: dict[str, Any], source_ids: set[str]) -> None:
    """Require every supplied economic fact/derivation to cite captured sources."""

    def require_ids(value: object, label: str) -> None:
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or not set(value).issubset(source_ids)
        ):
            raise ValueError(f"nonempty registered evidence identifiers required: {label}")

    require_ids(event.get("source_evidence_ids"), "source_evidence_ids")
    for field in ("source_facts", "derivations", "date_derivations", "market_intervals"):
        records = event.get(field, [])
        if not isinstance(records, list):
            raise ValueError(f"source metadata records must be a list: {field}")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"source metadata record required: {field}")
            require_ids(record.get("evidence_ids"), field)


def build_admission(evidence: Evidence, prices: pd.DataFrame, actions: pd.DataFrame, calendar: pd.DatetimeIndex) -> Admission:
    """Fail affected holdings closed when a term gate fails; never default it."""
    del actions  # The economic kernel binds exact source types/dates itself.
    candidate = evidence.json(CANDIDATE)
    source_ids = {item["evidence_id"] for item in candidate["sources"]}
    audit: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    terms: list[Entitlement] = []
    availability: dict[str, dict[str, str]] = {}
    events = {item["event_id"]: item for item in candidate["events"]}
    types = {"EX_RIGHT", "EX_RIGHT_AND_DIVIDEND", "LOSS_OFFSET_CAPITAL_REDUCTION", "PAR_VALUE_CHANGE"}
    noneconomic_types = {"TRADING_METHOD_CHANGE", "MARKET_CLOSURE", "TRADING_SUSPENSION"}
    for event in events.values():
        if event["event_type"] not in noneconomic_types:
            # These fixed Taiwan ordinary-share/0050 studies use four-digit
            # issuer identifiers. An unassignable economic event cannot become
            # a per-issuer unresolved row that every holding then ignores.
            code = event.get("code")
            if not isinstance(code, str) or re.fullmatch(r"[0-9]{4}", code) is None:
                raise ValueError("economic event requires a valid four-digit issuer code")
        if event["event_type"] not in types:
            if event["event_type"] not in noneconomic_types:
                reason = f"unsupported supplement economic event: {event['event_type']}"
                unresolved.append(_unresolved_event(event, reason))
                audit.append({"event_id": event["event_id"], "status": "unresolved", "reason": reason})
            continue
        try:
            _validate_entitlement_sources(event, source_ids)
            entitlement = _entitlement(evidence, event, prices, calendar)
            terms.append(entitlement)
            audit.append({"event_id": event["event_id"], "status": "admitted", "entitlement": entitlement.__dict__})
        except (KeyError, ValueError, ZeroDivisionError) as error:
            reason = str(error)
            unresolved.append(_unresolved_event(event, reason))
            audit.append({"event_id": event["event_id"], "status": "unresolved", "reason": reason})
    for gap in candidate["daily_gap_observations"]:
        if gap["code"] is None or not gap["evidence_ids"] or not set(gap["evidence_ids"]).issubset(source_ids):
            continue
        code, day = gap["code"], gap["date"]
        classification = None
        for event_id in gap["event_ids"]:
            event = events[event_id]
            if event["code"] not in {code, None}:
                continue
            for interval in event["market_intervals"]:
                # An open-ended halt proves only its documented start day.
                end = interval["end_date"] or interval["start_date"]
                if (
                    interval["type"] in {"trading_suspension", "market_wide_closure"}
                    and interval["evidence_ids"]
                    and set(interval["evidence_ids"]).issubset(source_ids)
                    and interval["start_inclusive"]
                    and interval["start_date"] <= day <= end
                    and (interval["end_date"] is None or interval["end_inclusive"] or day < end)
                ):
                    classification = "H"
        observation = gap["source_observation"]
        if (
            classification is None
            and gap["observation_kind"] == "missing_close"
            and all(key in observation and observation[key] is None for key in ("open", "high", "low", "close"))
        ):
            classification = "N"
        if classification and pd.Timestamp(day) in calendar:
            availability.setdefault(code, {})[day] = classification
        audit.append({
            "gap_id": gap["gap_id"],
            "code": code,
            "date": day,
            "class": classification or "U",
            "cause_status": gap["cause_status"],
            "source_observation": observation,
            "evidence_ids": gap["evidence_ids"],
        })
    return Admission(tuple(terms), availability, audit, unresolved)
