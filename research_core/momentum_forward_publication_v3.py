"""Immutable candidate content and live observations, without acceptance authority.

No market reads, receipts, accepted reader, cohort writes or journal orchestration.
Inspection verifies candidate integrity; it cannot reconstruct a live observation.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from research_core import artifact_store as store
from research_core import momentum_forward_v1 as v1
from research_core.json_integrity import strict_json_object

LOGGER = logging.getLogger(__name__)
PROTOCOL = "candidate-content-sealing.v3"
MANIFEST_SCHEMA = "momentum-forward-publication-manifest.v3"
PROPOSAL_SCHEMA = "momentum-forward-cohort-proposal.v3"
MEMBERS = ("day.parquet", "cohort-proposal.json", "manifest.json")
PROVISIONAL = ("recorded_late", "recorded_at_utc", "first_frozen_at_utc")
FORBIDDEN = {"accepted", "on_time", "acceptance_status", "publication_observed_at_utc"}
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PROPOSAL_BYTES = 64 * 1024
MAX_DAY_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class CandidateIdentity:
    target_day: str
    attempt_id: str
    bundle_id: str
    generation: str
    generation_asof: str
    code_commit: str


@dataclass(frozen=True)
class CohortProposal:
    """An unverified proposal, never an accepted cohort or receipt-chain verdict."""

    kind: Literal["first", "continue"]
    confirmatory_start: str
    confirmatory_end: str
    anchor_receipt_sha256: str | None
    predecessor_receipt_sha256: str | None


@dataclass(frozen=True)
class SerializedCandidate:
    identity: CandidateIdentity
    day_bytes: bytes
    proposal_bytes: bytes
    manifest_bytes: bytes
    manifest_sha256: str


@dataclass(frozen=True)
class CandidateInspection:
    """Integrity/identity only; no wall time, acceptance result or effective cohort."""

    identity: CandidateIdentity
    manifest_sha256: str
    manifest_size_bytes: int
    row_count: int
    security_ids: tuple[str, ...]
    proposal: CohortProposal


@dataclass(frozen=True)
class PublishedCandidate:
    path: Path
    content: CandidateInspection


@dataclass(frozen=True)
class ClockSample:
    """Explicit provider claims; this module does not certify an OS clock/NTP source."""

    wall_time: datetime | pd.Timestamp
    monotonic_ns: int
    source: str
    trusted: bool
    healthy: bool


ContentState = Literal["observed_before_deadline", "observed_late", "unknown", "ineligible"]


@dataclass(frozen=True)
class PublicationObservation:
    """Ephemeral evidence from this call, with no API to persist an acceptance receipt."""

    candidate: PublishedCandidate
    state: ContentState
    deadline_utc: pd.Timestamp
    before: ClockSample | None
    after: ClockSample | None
    reason: str


def _date(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("canonical ISO day required")
    if datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value:
        raise ValueError("invalid day")
    return value


def _hex(value: object, length: int) -> str:
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
        raise ValueError(f"canonical {length}-character hexadecimal identity required")
    return value


def _keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError(f"missing/unknown contract fields: {sorted(set(value) ^ expected)}")


def _identity(value: dict[str, Any]) -> CandidateIdentity:
    _keys(value, {"target_day", "attempt_id", "bundle_id", "generation", "generation_asof", "code_commit"})
    identity = CandidateIdentity(**value)
    _date(identity.target_day)
    _date(identity.generation_asof)
    _hex(identity.attempt_id, 32)
    _hex(identity.bundle_id, 32)
    _hex(identity.code_commit, 40)
    if not isinstance(identity.generation, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identity.generation):
        raise ValueError("invalid generation identity")
    return identity


def _proposal(value: dict[str, Any], identity: CandidateIdentity) -> CohortProposal:
    _keys(value, {"kind", "confirmatory_start", "confirmatory_end", "anchor_receipt_sha256", "predecessor_receipt_sha256"})
    proposal = CohortProposal(**value)
    start, end = _date(proposal.confirmatory_start), _date(proposal.confirmatory_end)
    end_stamp = pd.Timestamp(start) + pd.DateOffset(months=12) - pd.Timedelta(days=1)
    if not isinstance(end_stamp, pd.Timestamp):
        raise ValueError("invalid cohort interval")
    expected_end = end_stamp.strftime("%Y-%m-%d")
    if end != expected_end or not start <= identity.target_day <= end:
        raise ValueError("proposal must preserve the existing 12-month interval and contain the target day")
    if proposal.kind == "first":
        if start != identity.target_day or proposal.anchor_receipt_sha256 is not None or proposal.predecessor_receipt_sha256 is not None:
            raise ValueError("first proposal must start at target day with no accepted-chain claim")
    elif proposal.kind == "continue":
        _hex(proposal.anchor_receipt_sha256, 64)
        _hex(proposal.predecessor_receipt_sha256, 64)
    else:
        raise ValueError("unsupported cohort proposal kind")
    return proposal


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or len(raw) > maximum:
        raise ValueError("JSON member type/size invalid")
    value = strict_json_object(raw)
    if store.canonical(value) != raw:
        raise ValueError("noncanonical candidate JSON bytes")
    return value


def _frame(frame: pd.DataFrame, identity: CandidateIdentity) -> tuple[str, ...]:
    if frame.empty or not frame.columns.is_unique or any(not isinstance(name, str) for name in frame.columns):
        raise ValueError("nonempty candidate with unique string columns required")
    if set(PROVISIONAL) & set(frame.columns) or FORBIDDEN & set(frame.columns):
        raise ValueError("candidate cannot contain provisional/acceptance evidence columns")
    if "t0" not in frame or "security_id" not in frame:
        raise ValueError("candidate needs t0 and security_id")
    if any(not isinstance(day, str) or day != identity.target_day for day in frame["t0"]):
        raise ValueError("day rows conflict with candidate identity")
    codes = tuple(frame["security_id"])
    if any(not isinstance(code, str) or not re.fullmatch(r"TW:[0-9]{4,6}", code) for code in codes) or len(set(codes)) != len(codes):
        raise ValueError("unique canonical security IDs required")
    for column, expected in (("generation", identity.generation), ("code_commit", identity.code_commit)):
        if column in frame and any(not isinstance(value, str) or value != expected for value in frame[column]):
            raise ValueError(f"{column} conflicts with candidate identity")
    if frame.attrs:
        raise ValueError("candidate dataframe attributes must be empty")
    return codes


def serialize_candidate(frame: pd.DataFrame, *, identity: CandidateIdentity, cohort_proposal: CohortProposal) -> SerializedCandidate:
    """Freeze all three covered members in memory; source frame is never modified."""
    identity = _identity(asdict(identity))
    proposal = _proposal(asdict(cohort_proposal), identity)
    copied = frame.copy(deep=True).drop(columns=list(PROVISIONAL), errors="ignore")
    copied.attrs = {}
    codes = _frame(copied, identity)
    day_bytes = copied.to_parquet(index=False, compression="zstd", engine="pyarrow")
    if type(day_bytes) is not bytes or len(day_bytes) > MAX_DAY_BYTES:
        raise ValueError("day member type/size invalid")
    proposal_bytes = store.canonical({"schema": PROPOSAL_SCHEMA, "identity": asdict(identity), "proposal": asdict(proposal)})
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "protocol": PROTOCOL,
        "identity": asdict(identity),
        "required_members": list(MEMBERS),
        "payloads": {name: {"size_bytes": len(raw), "sha256": _digest(raw)} for name, raw in zip(MEMBERS[:2], (day_bytes, proposal_bytes), strict=True)},
        "row_count": len(copied),
        "security_ids": list(codes),
    }
    manifest_bytes = store.canonical(manifest)
    candidate = SerializedCandidate(identity, day_bytes, proposal_bytes, manifest_bytes, _digest(manifest_bytes))
    _inspect_bytes(candidate.day_bytes, candidate.proposal_bytes, candidate.manifest_bytes, identity.target_day, identity.bundle_id)
    LOGGER.info("Serialized candidate day=%s bundle=%s rows=%d", identity.target_day, identity.bundle_id, len(copied))
    return candidate


def _inspect_bytes(day: bytes, proposal_raw: bytes, manifest_raw: bytes, target_day: str, bundle_id: str) -> CandidateInspection:
    manifest = _json(manifest_raw, MAX_MANIFEST_BYTES)
    _keys(manifest, {"schema", "protocol", "identity", "required_members", "payloads", "row_count", "security_ids"})
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["protocol"] != PROTOCOL or manifest["required_members"] != list(MEMBERS):
        raise ValueError("unsupported manifest schema/protocol/member set")
    if not isinstance(manifest["identity"], dict):
        raise ValueError("identity object required")
    identity = _identity(manifest["identity"])
    if (identity.target_day, identity.bundle_id) != (target_day, bundle_id):
        raise ValueError("manifest identity conflicts with bundle path")
    payloads = manifest["payloads"]
    if not isinstance(payloads, dict):
        raise ValueError("payload identities object required")
    _keys(payloads, set(MEMBERS[:2]))
    for name, raw, maximum in zip(MEMBERS[:2], (day, proposal_raw), (MAX_DAY_BYTES, MAX_PROPOSAL_BYTES), strict=True):
        info = payloads[name]
        if not isinstance(info, dict):
            raise ValueError("member identity object required")
        _keys(info, {"size_bytes", "sha256"})
        if type(raw) is not bytes or len(raw) > maximum or type(info["size_bytes"]) is not int or info["size_bytes"] != len(raw):
            raise ValueError(f"member length mismatch: {name}")
        if _hex(info["sha256"], 64) != _digest(raw):
            raise ValueError(f"member digest mismatch: {name}")
    proposal_doc = _json(proposal_raw, MAX_PROPOSAL_BYTES)
    _keys(proposal_doc, {"schema", "identity", "proposal"})
    if proposal_doc["schema"] != PROPOSAL_SCHEMA or proposal_doc["identity"] != asdict(identity) or not isinstance(proposal_doc["proposal"], dict):
        raise ValueError("proposal identity/schema mismatch")
    proposal = _proposal(proposal_doc["proposal"], identity)
    frame = pd.read_parquet(io.BytesIO(day), engine="pyarrow")
    codes = _frame(frame, identity)
    if type(manifest["row_count"]) is not int or manifest["row_count"] != len(frame) or manifest["security_ids"] != list(codes):
        raise ValueError("manifest row membership mismatch")
    return CandidateInspection(identity, _digest(manifest_raw), len(manifest_raw), len(frame), codes, proposal)


def _destination(root: Path, target_day: str, bundle_id: str) -> Path:
    _date(target_day)
    _hex(bundle_id, 32)
    return store.safe_path(root / "publication-v3" / "bundles" / target_day / bundle_id)


def publish_candidate(root: Path, candidate: SerializedCandidate) -> PublishedCandidate:
    """Return only after every member close and native directory no-replace return."""
    content = _inspect_bytes(
        candidate.day_bytes, candidate.proposal_bytes, candidate.manifest_bytes, candidate.identity.target_day, candidate.identity.bundle_id
    )
    if content.identity != candidate.identity or content.manifest_sha256 != candidate.manifest_sha256:
        raise ValueError("serialized candidate identity/manifest byte pin mismatch")
    destination = _destination(root, content.identity.target_day, content.identity.bundle_id)
    result = PublishedCandidate(destination, content)
    LOGGER.info("Publishing candidate day=%s bundle=%s", content.identity.target_day, content.identity.bundle_id)
    store.publish_new_directory(destination, dict(zip(MEMBERS, (candidate.day_bytes, candidate.proposal_bytes, candidate.manifest_bytes), strict=True)))
    return result


def _sample(clock: Callable[[], ClockSample]) -> tuple[ClockSample | None, pd.Timestamp | None, str | None]:
    try:
        sample = clock()
        if not isinstance(sample, ClockSample):
            raise ValueError("explicit ClockSample required")
        if sample.trusted is not True or sample.healthy is not True or not isinstance(sample.source, str) or not sample.source.strip():
            raise ValueError("clock trust/source/health unavailable")
        if type(sample.monotonic_ns) is not int or sample.monotonic_ns < 0:
            raise ValueError("invalid monotonic ordering sample")
        if not isinstance(sample.wall_time, (datetime, pd.Timestamp)):
            raise ValueError("aware wall time required")
        wall = pd.Timestamp(sample.wall_time)
        if not isinstance(wall, pd.Timestamp) or wall.tzinfo is None:
            raise ValueError("invalid/naive wall time")
        return sample, wall.tz_convert("UTC"), None
    except Exception as error:  # noqa: BLE001 - invalid clock is unknown, never early evidence
        return None, None, f"{type(error).__name__}: {error}"


def publish_and_observe(root: Path, candidate: SerializedCandidate, *, clock: Callable[[], ClockSample]) -> PublicationObservation:
    """Sample live wall time immediately after publication returns; persist no verdict."""
    before, before_wall, before_error = _sample(clock)
    published = publish_candidate(root, candidate)
    after, after_wall, after_error = _sample(clock)
    identity = published.content.identity
    deadline = v1.freeze_deadline(identity.target_day).tz_convert("UTC")
    state: ContentState
    reason: str
    if before is None or after is None or before_wall is None or after_wall is None:
        state, reason = "unknown", before_error or after_error or "clock unavailable"
    elif before.source != after.source or after.monotonic_ns <= before.monotonic_ns or after_wall < before_wall:
        state, reason = "unknown", "clock source changed, visible wall rollback or contradictory monotonic order"
    elif identity.generation_asof != identity.target_day or identity.target_day < v1.FIRST_CONFIRMATORY_DAY:
        state, reason = "ineligible", "v1 generation-as-of or first-confirmatory-day predicate failed"
    elif v1.is_on_time(identity.target_day, identity.generation_asof, after_wall):
        state, reason = "observed_before_deadline", "all covered publication operations returned before this trusted live sample"
    else:
        state, reason = "observed_late", "publication observation is at or after the existing v1 deadline"
    LOGGER.info("Candidate observation bundle=%s state=%s", identity.bundle_id, state)
    return PublicationObservation(published, state, deadline, before, after, reason)


def inspect_candidate(root: Path, *, target_day: str, bundle_id: str) -> CandidateInspection:
    """Inspect bytes only; never infer publication time from files, mtime or restart."""
    destination = _destination(root, target_day, bundle_id)
    if not destination.is_dir() or {path.name for path in destination.iterdir()} != set(MEMBERS):
        raise ValueError("candidate directory must contain exactly the three covered members")
    raw: dict[str, bytes] = {}
    for name, maximum in zip(MEMBERS, (MAX_DAY_BYTES, MAX_PROPOSAL_BYTES, MAX_MANIFEST_BYTES), strict=True):
        path = store.safe_path(destination / name)
        if not path.is_file() or path.stat().st_size > maximum:
            raise ValueError(f"invalid candidate member type/size: {name}")
        raw[name] = path.read_bytes()
    return _inspect_bytes(raw[MEMBERS[0]], raw[MEMBERS[1]], raw[MEMBERS[2]], target_day, bundle_id)
