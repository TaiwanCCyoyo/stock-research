"""Stop on an encountered unsupported right, rather than preselecting issuers."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from research_core.chronology import CorporateEvidence
from research_core.ledger import replay_ledger


def event_domains(
    factors: Sequence[tuple[date, str, str]],
    cash_keys: set[tuple[str, date]],
    rights_keys: set[tuple[str, date]],
) -> tuple[list[tuple[date, str, str]], frozenset[tuple[date, str]]]:
    """Union independent rights evidence; a price-factor subset is not authority."""
    factor_keys = {(code, day) for day, code, _identity in factors}
    unsupported = [(day, code, identity) for day, code, identity in factors if (code, day) not in cash_keys or (code, day) in rights_keys]
    unsupported += [(day, code, f"rights:{code}:{day.isoformat()}") for code, day in rights_keys - factor_keys]
    boundaries = frozenset((day, code) for code, day in factor_keys | cash_keys | rights_keys)
    return unsupported, boundaries


def guarded_cash_provider(
    cash_provider: Callable[..., CorporateEvidence],
    unsupported: Sequence[tuple[datetime, str, str]],
    diagnostics: list[dict[str, Any]],
) -> Callable[..., CorporateEvidence]:
    """Unknown noncash economics stop only if the account owns that issuer.

    The caller names unsupported events explicitly and separately binds the
    supported principal/share events. This guard replays the real prefix
    and does not certify other corporate domains. Execution separately stops
    unsupported event-day requests.
    """
    ordered = sorted(unsupported)
    moments = [row[0] for row in ordered]

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        within = ordered[bisect_right(moments, since) : bisect_right(moments, until)]
        if within:
            ledger = replay_ledger(2_000_000, prefix, max_positions=5)
            for at, code, event_id in within:
                if code in ledger["positions"] or code in ledger["outstanding_share_codes"]:
                    diagnostics.append({"reason": "held_noncash_event_not_bound", "at": at.isoformat(), "code": code, "event_id": event_id})
                    return CorporateEvidence(f"unsupported-held-event:{event_id}", (), False)
        result = cash_provider(since, until, prefix)
        if not result.complete:
            diagnostics.append({"reason": "cash_terms_incomplete", "since": since.isoformat(), "until": until.isoformat(), "evidence_id": result.evidence_id})
        return result

    return provide
