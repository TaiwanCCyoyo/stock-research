"""Portable validation for additive sector-role evidence packets."""

from __future__ import annotations

import gzip
import hashlib
import ipaddress
import json
import logging
import math
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import unquote, urlparse

PACKET_SCHEMA = "sector-classification-evidence.v1"
CATALOG_SCHEMA = "sector-wave-catalog.v1"
SCOPE_REGISTRY_PATH = Path(__file__).with_name("sector_role_review_scopes.v1.json")
ROLE_TAXONOMY_PATH = Path(__file__).with_name("sector_roles.v1.json")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
LOGGER = logging.getLogger(__name__)


class SectorRoleEvidenceError(ValueError):
    """A packet or its immutable base catalog violates the evidence contract."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SectorRoleEvidenceError(f"{name} must be a nonempty string")
    return value


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError as error:
        LOGGER.warning("Rejected invalid canonical JSON: %s", error)
        raise SectorRoleEvidenceError(f"invalid canonical JSON: {error}") from error
    return _sha_bytes(payload.encode("utf-8"))


def _reject_nonfinite_constant(value: str) -> NoReturn:
    raise SectorRoleEvidenceError(f"non-finite JSON constant: {value}")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise SectorRoleEvidenceError("non-finite JSON number after float conversion")
    return parsed


def _utc(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, name).replace("Z", "+00:00"))
    except ValueError as error:
        raise SectorRoleEvidenceError(f"{name} must be UTC ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SectorRoleEvidenceError(f"{name} must be UTC ISO timestamp")
    return parsed


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _source_url(value: Any) -> None:
    raw_url = _text(value, "source url")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw_url):
        raise SectorRoleEvidenceError("invalid source URL authority")
    try:
        parsed = urlparse(raw_url)
        hostname = parsed.hostname
        parsed.port
    except ValueError as error:
        raise SectorRoleEvidenceError("invalid source URL authority") from error
    if parsed.scheme != "https" or not hostname:
        raise SectorRoleEvidenceError("source URL must be HTTPS")
    if _INVALID_PERCENT_ESCAPE.search(hostname):
        raise SectorRoleEvidenceError("invalid source URL hostname")
    try:
        decoded_hostname = unquote(hostname, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SectorRoleEvidenceError("invalid source URL hostname") from error
    if not decoded_hostname or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in decoded_hostname):
        raise SectorRoleEvidenceError("invalid source URL hostname")
    try:
        address = ipaddress.ip_address(decoded_hostname)
    except ValueError:
        authority = parsed.netloc.rsplit("@", 1)[-1]
        if authority.startswith("["):
            raise SectorRoleEvidenceError("invalid source URL hostname")
        core = decoded_hostname[:-1] if decoded_hostname.endswith(".") else decoded_hostname
        try:
            ascii_core = core.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise SectorRoleEvidenceError("invalid source URL hostname") from error
        labels = ascii_core.split(".")
        if not core or len(ascii_core) > 253 or any(len(label) > 63 or not _DNS_LABEL.fullmatch(label) for label in labels):
            raise SectorRoleEvidenceError("invalid source URL hostname")
    else:
        authority = parsed.netloc.rsplit("@", 1)[-1]
        if address.version == 6 and not authority.startswith("["):
            raise SectorRoleEvidenceError("invalid source URL hostname")


def _day(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(_text(value, name))
    except ValueError as error:
        raise SectorRoleEvidenceError(f"{name} must be ISO day") from error


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SectorRoleEvidenceError(f"{name} must be a list")
    return value


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite_constant, parse_float=_finite_json_float)
    except (OSError, ValueError) as error:
        LOGGER.warning("Rejected JSON input %s: %s", path, error)
        raise SectorRoleEvidenceError(f"cannot read JSON: {path}: {error}") from error


def _catalog(catalog_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str], int]:
    catalog_dir = catalog_dir.resolve()
    manifest = _read_json(catalog_dir / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != CATALOG_SCHEMA:
        raise SectorRoleEvidenceError("invalid base catalog manifest")
    receipt = _read_json(catalog_dir / "completion-receipt.json")
    if not isinstance(receipt, dict) or receipt.get("manifest_canonical_sha256") != _canonical(manifest) or receipt.get("counts") != manifest.get("counts"):
        raise SectorRoleEvidenceError("base catalog receipt mismatch")
    tables: dict[str, list[dict[str, Any]]] = {"securities": [], "groups": [], "episodes": []}
    chunks = _list(manifest.get("chunks"), "catalog chunks")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise SectorRoleEvidenceError("catalog chunk must be an object")
        relative = _text(chunk.get("path"), "catalog chunk path")
        target = (catalog_dir / relative).resolve()
        if not target.is_relative_to(catalog_dir) or _sha_bytes(target.read_bytes()) != _text(chunk.get("sha256"), "catalog chunk sha256"):
            raise SectorRoleEvidenceError("base catalog chunk integrity failure")
        if chunk.get("table") in tables:
            try:
                with gzip.open(target, "rt", encoding="utf-8") as handle:
                    rows = json.load(handle, parse_constant=_reject_nonfinite_constant, parse_float=_finite_json_float)
            except (OSError, ValueError) as error:
                LOGGER.warning("Rejected catalog metadata chunk %s: %s", target, error)
                raise SectorRoleEvidenceError(f"cannot read base catalog metadata chunk: {error}") from error
            if not isinstance(rows, list) or len(rows) != chunk.get("rows") or any(not isinstance(row, dict) for row in rows):
                raise SectorRoleEvidenceError("invalid base catalog metadata rows")
            tables[chunk["table"]].extend(rows)
    securities: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}
    for row in tables["securities"]:
        identity = _text(row.get("security_id"), "catalog security_id")
        if identity in securities:
            raise SectorRoleEvidenceError("duplicate catalog security_id")
        securities[identity] = row
    for row in tables["groups"]:
        identity = _text(row.get("group_id"), "catalog group_id")
        if identity in groups:
            raise SectorRoleEvidenceError("duplicate catalog group_id")
        groups[identity] = row
    episode_security_ids = {_text(row.get("security_id"), "catalog episode security_id") for row in tables["episodes"]}
    return manifest, securities, groups, episode_security_ids, len(chunks)


def _scope_profile(profile_id: str) -> dict[str, Any]:
    registry = _read_json(SCOPE_REGISTRY_PATH)
    if not isinstance(registry, dict) or registry.get("schema_version") != "sector-role-review-scopes.v1":
        raise SectorRoleEvidenceError("invalid sector role scope registry")
    profiles = _list(registry.get("profiles"), "scope registry profiles")
    matches = [profile for profile in profiles if isinstance(profile, dict) and profile.get("profile_id") == profile_id]
    if len(matches) != 1:
        raise SectorRoleEvidenceError("unknown scope_profile_id")
    profile = matches[0]
    group_ids = _list(profile.get("included_group_ids"), "profile included_group_ids")
    seed_ids = _list(profile.get("seed_security_ids"), "profile seed_security_ids")
    _text(profile.get("base_manifest_canonical_sha256"), "profile base_manifest_canonical_sha256")
    group_reason = _text(profile.get("included_group_reason"), "profile included_group_reason")
    if group_reason in {"source_missing_with_episode", "registered_issuer_seed"}:
        raise SectorRoleEvidenceError("included_group_reason collides with another selection rule")
    if any(not isinstance(item, str) or not item for item in [*group_ids, *seed_ids]) or not isinstance(
        profile.get("include_source_missing_with_episode"), bool
    ):
        raise SectorRoleEvidenceError("invalid scope profile")
    return profile


def _ids(rows: list[Any], field: str, name: str) -> set[str]:
    result: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SectorRoleEvidenceError(f"{name} rows must be objects")
        identity = _text(row.get(field), f"{name}.{field}")
        if identity in result:
            raise SectorRoleEvidenceError(f"duplicate {name} {field}")
        result.add(identity)
    return result


def _known_string_list(value: Any, name: str, known: set[str]) -> set[str]:
    values = _list(value, name)
    if any(not isinstance(item, str) or item not in known for item in values):
        raise SectorRoleEvidenceError(f"{name} contains unknown identifier")
    return set(values)


def _nullable_with_reason(row: dict[str, Any], field: str, *, time: bool = False) -> None:
    value = row.get(field)
    reasons = row.get("unknown_reasons")
    if not isinstance(reasons, dict):
        raise SectorRoleEvidenceError("unknown_reasons must be an object")
    if value is None:
        _text(reasons.get(field), f"unknown_reasons.{field}")
    elif time:
        _utc(value, field)
    elif field in {"effective_from", "effective_to"}:
        _day(value, field)


def validate_packet(packet_path: Path, catalog_dir: Path, receipt_path: Path | None = None) -> dict[str, Any]:
    """Validate an additive packet without reading prices or mutating either artifact."""
    validation_now = _utc_now()
    future_cutoff = validation_now + timedelta(minutes=5)
    packet = _read_json(packet_path)
    if not isinstance(packet, dict) or packet.get("schema_version") != PACKET_SCHEMA:
        raise SectorRoleEvidenceError("invalid packet schema")
    _text(packet.get("packet_id"), "packet_id")
    created_at = _utc(packet.get("created_at"), "created_at")
    if created_at > future_cutoff:
        raise SectorRoleEvidenceError("packet created_at exceeds clock-skew cutoff")
    limitations = _list(packet.get("limitations"), "limitations")
    if not limitations:
        raise SectorRoleEvidenceError("limitations must be nonempty")
    for limitation in limitations:
        _text(limitation, "limitation")
    manifest, catalog_securities, catalog_groups, episode_security_ids, chunk_count = _catalog(catalog_dir)
    base = packet.get("base_catalog")
    if not isinstance(base, dict) or base.get("schema_version") != manifest["schema_version"] or base.get("manifest_canonical_sha256") != _canonical(manifest):
        raise SectorRoleEvidenceError("packet base_catalog does not match catalog")

    taxonomy = packet.get("role_taxonomy")
    if not isinstance(taxonomy, dict) or taxonomy.get("schema_version") != "sector-roles.v1":
        raise SectorRoleEvidenceError("invalid role taxonomy")
    canonical_taxonomy = _read_json(ROLE_TAXONOMY_PATH)
    if taxonomy != canonical_taxonomy:
        raise SectorRoleEvidenceError("packet role taxonomy differs from canonical taxonomy")
    role_rows = _list(taxonomy.get("roles"), "roles")
    tag_rows = _list(taxonomy.get("product_tags"), "product_tags")
    roles = _ids(role_rows, "role_id", "roles")
    tags = _ids(tag_rows, "tag_id", "product_tags")
    for row in [*role_rows, *tag_rows]:
        _text(row.get("label"), "taxonomy label")

    profile = _scope_profile(_text(packet.get("scope_profile_id"), "scope_profile_id"))
    if profile["base_manifest_canonical_sha256"] != _canonical(manifest):
        raise SectorRoleEvidenceError("scope profile base catalog does not match catalog")
    included_groups = set(profile["included_group_ids"])
    seed_ids = set(profile["seed_security_ids"])
    if not included_groups <= set(catalog_groups):
        raise SectorRoleEvidenceError("unknown profile group")
    if not seed_ids <= set(catalog_securities):
        raise SectorRoleEvidenceError("unknown profile seed")
    expected_scope_reasons: dict[str, list[str]] = {}
    for security_id, security in catalog_securities.items():
        reasons: set[str] = set()
        if included_groups.intersection(security.get("group_ids", [])):
            reasons.add(profile["included_group_reason"])
        if profile["include_source_missing_with_episode"] and security.get("coverage_status") == "source_missing" and security_id in episode_security_ids:
            reasons.add("source_missing_with_episode")
        if security_id in seed_ids:
            reasons.add("registered_issuer_seed")
        if reasons:
            expected_scope_reasons[security_id] = sorted(reasons)
    scope_rows = _list(packet.get("scope"), "scope")
    scope_ids = _ids(scope_rows, "security_id", "scope")
    if scope_ids != set(expected_scope_reasons):
        raise SectorRoleEvidenceError("scope does not match registered profile queue")
    scope_by_id = {row["security_id"]: row for row in scope_rows}
    for security_id, row in scope_by_id.items():
        source = catalog_securities.get(security_id)
        if source is None or row.get("official_industry") != source.get("official_industry") or row.get("group_ids") != source.get("group_ids"):
            raise SectorRoleEvidenceError("scope differs from original catalog membership")
        status = row.get("review_status")
        if status not in {"source_verified", "pending"}:
            raise SectorRoleEvidenceError("invalid scope review_status")
        if status == "pending":
            _text(row.get("unknown_reason"), "scope unknown_reason")
        elif row.get("unknown_reason") is not None:
            raise SectorRoleEvidenceError("verified scope may not have unknown_reason")
        scope_reasons = row.get("scope_reasons")
        if not isinstance(scope_reasons, list) or not scope_reasons or any(not isinstance(item, str) or not item for item in scope_reasons):
            raise SectorRoleEvidenceError("scope_reasons must be nonempty strings")
        if scope_reasons != expected_scope_reasons[security_id]:
            raise SectorRoleEvidenceError("scope_reasons do not match registered profile")

    sources = _list(packet.get("sources"), "sources")
    source_ids = _ids(sources, "evidence_id", "sources")
    source_by_id = {row["evidence_id"]: row for row in sources}
    consumed_sources: set[str] = set()
    for source in sources:
        security_id = _text(source.get("security_id"), "source security_id")
        if security_id not in scope_ids:
            raise SectorRoleEvidenceError("source outside scope")
        _source_url(source.get("url"))
        if source.get("source_kind") not in {"issuer_page", "issuer_report"} or source.get("verification_status") != "manually_verified":
            raise SectorRoleEvidenceError("invalid source kind or verification")
        excerpt = _text(source.get("retained_excerpt"), "retained_excerpt")
        if _sha_bytes(excerpt.encode("utf-8")) != _text(source.get("retained_excerpt_sha256"), "retained_excerpt_sha256"):
            raise SectorRoleEvidenceError("retained excerpt hash mismatch")
        _text(source.get("title"), "source title")
        _text(source.get("locator"), "source locator")
        _text(source.get("inspection_method"), "inspection_method")
        retrieved_at = _utc(source.get("retrieved_at"), "retrieved_at")
        if retrieved_at > future_cutoff:
            raise SectorRoleEvidenceError("source retrieved_at exceeds clock-skew cutoff")
        if created_at < retrieved_at:
            raise SectorRoleEvidenceError("packet created_at precedes source retrieval")
        for field in ("published_at", "available_at", "covered_period"):
            _nullable_with_reason(source, field, time=field != "covered_period")
        if source.get("covered_period") is not None:
            period = source["covered_period"]
            if not isinstance(period, dict) or _day(period.get("start"), "covered_period.start") > _day(period.get("end"), "covered_period.end"):
                raise SectorRoleEvidenceError("invalid covered_period")
            _text(period.get("basis"), "covered_period.basis")
        if source.get("published_at") is not None and _utc(source["published_at"], "published_at") > retrieved_at:
            raise SectorRoleEvidenceError("published_at follows retrieval")
        if source.get("available_at") is not None and _utc(source["available_at"], "available_at") > retrieved_at:
            raise SectorRoleEvidenceError("available_at follows retrieval")
        if source.get("published_on") is not None:
            # A printed day has no timezone. Reject only if even its UTC+14
            # earliest possible instant follows inspection; retain unknown availability.
            earliest_possible_utc = datetime.combine(_day(source["published_on"], "published_on"), time.min, tzinfo=UTC) - timedelta(hours=14)
            if earliest_possible_utc > retrieved_at:
                raise SectorRoleEvidenceError("published_on follows retrieval")
        supported_roles = _known_string_list(source.get("supported_role_ids"), "supported_role_ids", roles)
        source_tags = _known_string_list(source.get("supported_tag_ids"), "supported_tag_ids", tags)
        products_by_role = source.get("supported_products_by_role")
        if not isinstance(products_by_role, dict) or any(role not in roles for role in products_by_role) or not supported_roles <= set(products_by_role):
            raise SectorRoleEvidenceError("invalid source role/product associations")
        linked_tags: set[str] = set()
        for supported_tags in products_by_role.values():
            linked_tags.update(_known_string_list(supported_tags, "supported_products_by_role", tags))
        if source_tags != linked_tags:
            raise SectorRoleEvidenceError("source role/product associations differ from supported tags")

    assertions = _list(packet.get("assertions"), "assertions")
    _ids(assertions, "assertion_id", "assertions")
    assertion_pairs: set[tuple[str, str]] = set()
    assertion_counts: dict[str, int] = {security_id: 0 for security_id in scope_ids}
    for assertion in assertions:
        security_id = _text(assertion.get("security_id"), "assertion security_id")
        if (
            security_id not in scope_ids
            or assertion.get("assertion_status") != "source_verified"
            or assertion.get("label_kind") != "retrospective_annotation"
            or assertion.get("role_taxonomy_version") != "sector-roles.v1"
        ):
            raise SectorRoleEvidenceError("invalid assertion identity or status")
        role_id = _text(assertion.get("role_id"), "assertion role_id")
        pair = (security_id, role_id)
        if pair in assertion_pairs:
            raise SectorRoleEvidenceError("duplicate assertion security/role pair")
        assertion_pairs.add(pair)
        tag_ids = _known_string_list(assertion.get("product_tag_ids"), "product_tag_ids", tags)
        if role_id not in roles:
            raise SectorRoleEvidenceError("assertion references unknown role or tag")
        refs = _list(assertion.get("evidence_refs"), "assertion evidence_refs")
        if not refs or any(ref not in source_ids or source_by_id[ref]["security_id"] != security_id for ref in refs):
            raise SectorRoleEvidenceError("assertion evidence refs invalid")
        supported_roles = set().union(*(_known_string_list(source_by_id[ref].get("supported_role_ids"), "supported_role_ids", roles) for ref in refs))
        supported_tags = set().union(
            *(_known_string_list(source_by_id[ref]["supported_products_by_role"].get(role_id, []), "supported_products_by_role", tags) for ref in refs)
        )
        if role_id not in supported_roles or not tag_ids <= supported_tags:
            raise SectorRoleEvidenceError("assertion not supported by evidence")
        for ref in refs:
            source_roles = _known_string_list(source_by_id[ref].get("supported_role_ids"), "supported_role_ids", roles)
            source_tags = _known_string_list(source_by_id[ref]["supported_products_by_role"].get(role_id, []), "supported_products_by_role", tags)
            if role_id not in source_roles and not tag_ids.intersection(source_tags):
                raise SectorRoleEvidenceError("assertion includes irrelevant evidence source")
        consumed_sources.update(refs)
        assertion_counts[security_id] += 1
        for field in ("effective_from", "effective_to"):
            _nullable_with_reason(assertion, field)
            if assertion.get(field) is not None:
                raise SectorRoleEvidenceError("v1 packet requires unknown effective dates")
        for field, values, basis in (
            ("business_relevance", {"core", "secondary"}, "business_relevance_basis"),
            ("exposure_path", {"direct", "indirect"}, "exposure_path_basis"),
        ):
            value = assertion.get(field)
            evidence_field = f"{field}_evidence_refs"
            cited = _known_string_list(assertion.get(evidence_field), evidence_field, set(refs))
            if value is None:
                _text(assertion.get("unknown_reasons", {}).get(field), f"unknown_reasons.{field}")
                if cited or assertion.get(basis) is not None:
                    raise SectorRoleEvidenceError(f"unknown {field} may not cite evidence or basis")
            elif value not in values or not _text(assertion.get(basis), basis):
                raise SectorRoleEvidenceError(f"invalid {field}")
            if value is not None and not cited:
                raise SectorRoleEvidenceError(f"{field} lacks cited evidence")
    for security_id, scope in scope_by_id.items():
        if scope["review_status"] == "source_verified" and assertion_counts[security_id] < 1:
            raise SectorRoleEvidenceError("verified scope needs assertion")
        if scope["review_status"] == "pending" and assertion_counts[security_id]:
            raise SectorRoleEvidenceError("pending scope may not have verified assertion")
    reviews = _list(packet.get("membership_reviews"), "membership_reviews")
    review_pairs: set[tuple[str, str]] = set()
    for review in reviews:
        security_id = _text(review.get("security_id"), "review security_id")
        group_id = _text(review.get("group_id"), "review group_id")
        pair = (security_id, group_id)
        if pair in review_pairs:
            raise SectorRoleEvidenceError("duplicate membership review security/group pair")
        review_pairs.add(pair)
        refs = _list(review.get("evidence_refs"), "review evidence_refs")
        if (
            security_id not in scope_ids
            or review.get("review_status") != "needs_role_review"
            or group_id not in catalog_groups
            or group_id not in catalog_securities[security_id].get("group_ids", [])
            or not refs
            or any(ref not in source_ids or source_by_id[ref]["security_id"] != security_id for ref in refs)
        ):
            raise SectorRoleEvidenceError("invalid membership review")
        _text(review.get("reason"), "membership review reason")
        consumed_sources.update(refs)
    if consumed_sources != set(source_by_id):
        raise SectorRoleEvidenceError("dangling source evidence")
    summary = {
        "packet_id": packet["packet_id"],
        "scope_securities": len(scope_ids),
        "verified_securities": sum(row["review_status"] == "source_verified" for row in scope_rows),
        "sources": len(sources),
        "assertions": len(assertions),
        "unknown_effective_dates": sum(item.get("effective_from") is None or item.get("effective_to") is None for item in assertions),
        "membership_reviews": len(reviews),
        "original_validated_chunk_count": chunk_count,
        "packet_canonical_sha256": _canonical(packet),
    }
    if receipt_path is not None:
        receipt = _read_json(receipt_path)
        if receipt != summary:
            raise SectorRoleEvidenceError("published packet receipt mismatch")
    return summary
