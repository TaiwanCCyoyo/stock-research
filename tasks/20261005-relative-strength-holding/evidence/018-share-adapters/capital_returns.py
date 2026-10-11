"""Per-qualified-share principal refund adapter, not dividend income.

Reuse 018's qualification, cent rounding, prefix and timing algorithm. Only its
private calculation stream uses the dividend vocabulary. Published events and
the final shared ledger keep principal returns separate. No source/time is inferred.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
# Public local source digest from 018's receipt, not a credential.
QUALIFICATION_SHA256 = "3f0a739de1bb4bf217ce0db9d78ea7e23c4c938e161dcb0f378ab00db6e1d098"  # pragma: allowlist secret
if hashlib.sha256((BASE / "cash_dividends.py").read_bytes()).hexdigest() != QUALIFICATION_SHA256:
    raise RuntimeError("018 qualification algorithm identity changed")
sys.path.insert(0, str(BASE))
import cash_dividends as qualification  # noqa: E402
from cash_dividends import CashCoverage, CashDividend, CashDividendError, build_cash_provider  # noqa: E402

if Path(qualification.__file__).resolve() != (BASE / "cash_dividends.py").resolve():
    raise RuntimeError("cash qualification import resolves to a different packet")

from research_core.chronology import CorporateEvidence  # noqa: E402


@dataclass(frozen=True)
class CapitalReturn(CashDividend):
    """Explicit net refund per share held strictly before entitlement_at.

    The caller must supply a justified qualification instant before any relevant
    share reduction. This adapter does not itself transform shares or infer dates.
    """


def build_capital_return_provider(
    terms: Sequence[CapitalReturn],
    coverage: Sequence[CashCoverage],
    *,
    initial_cash_cents: int,
    max_positions: int,
    rounding_policy: str,
):
    frozen = tuple(terms)
    if any(not isinstance(term, CapitalReturn) for term in frozen):
        raise CashDividendError("principal returns require explicit CapitalReturn terms")
    ids = {term.event_id for term in frozen}
    inner = build_cash_provider(
        frozen,
        coverage,
        initial_cash_cents=initial_cash_cents,
        max_positions=max_positions,
        rounding_policy=rounding_policy,
    )
    to_internal = {"CAPITAL_RETURN_ENTITLEMENT": "DIVIDEND_ENTITLEMENT", "CAPITAL_RETURN": "DIVIDEND"}
    to_public = {value: key for key, value in to_internal.items()}

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        # Exact decision replay already requires linked dividends. State this
        # boundary before the internal translation can blur the reason for refusal.
        translated = []
        claim_kinds: dict[str, str] = {}
        payment_kinds: list[tuple[str, str]] = []
        for event in prefix:
            action = str(event["action"]).upper()
            identity = event.get("entitlement_id")
            if action in {"DIVIDEND", "CAPITAL_RETURN"} and (not isinstance(identity, str) or not identity):
                raise CashDividendError("capital return bridge requires linked cash payments; legacy payments are unsupported")
            if identity in ids and action in {"DIVIDEND", "DIVIDEND_ENTITLEMENT"}:
                raise CashDividendError("principal return identity conflicts with dividend evidence")
            if action in {"DIVIDEND_ENTITLEMENT", "CAPITAL_RETURN_ENTITLEMENT"}:
                if not isinstance(identity, str) or not identity or identity in claim_kinds:
                    raise CashDividendError("cash entitlement identity must be nonempty and unique")
                claim_kinds[identity] = action.removesuffix("_ENTITLEMENT")
            elif action in {"DIVIDEND", "CAPITAL_RETURN"} and isinstance(identity, str):
                payment_kinds.append((identity, action))
            translated.append({**event, "action": to_internal.get(action, action)})
        if any(identity in claim_kinds and claim_kinds[identity] != kind for identity, kind in payment_kinds):
            raise CashDividendError("payment cash kind differs from entitlement")
        result = inner(since, until, translated)
        events = []
        for item in result.events:
            record = dict(item)
            record["action"] = to_public[record["action"]]
            record["capital_return_policy_id"] = record.pop("cash_policy_id")
            events.append(record)
        return CorporateEvidence(result.evidence_id.replace("cash-dividends:", "capital-returns:", 1), tuple(events), result.complete)

    return provide
