"""Source-bound dividend terms for 018; not an all-corporate-event provider."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TASKS = HERE.parent
ROOT = HERE.parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from selection import CashSelection, select_cash  # noqa: E402

SOURCE = TASKS / "015-cash-source-readset" / "cash-readset-v2.json"
SOURCE_HASH = "cbb817c112f0c4eacb4d7492fe30718dc256f3a5efaf5f6450b0e498e39767db"  # pragma: allowlist secret - artifact checksum
ADAPTER_PATH = TASKS / "018-share-adapters" / "cash_dividends.py"
ADAPTER_HASH = "3f0a739de1bb4bf217ce0db9d78ea7e23c4c938e161dcb0f378ab00db6e1d098"  # pragma: allowlist secret - artifact checksum
TAIPEI = timezone(timedelta(hours=8))
TIMING_POLICIES = {"ex-date-plus45-calendar-days-v1": 45, "ex-date-plus90-calendar-days-v1": 90}
AMOUNT_POLICY = "stated-gross-before-investor-specific-income-tax-v1"


class CashBindingError(ValueError):
    """Evidence identity or an explicitly chosen modeling scope is inconsistent."""


def checked(path: Path, digest: str) -> bytes:
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != digest:
        raise CashBindingError(f"evidence identity drift: {path}")
    return body


checked(ADAPTER_PATH, ADAPTER_HASH)
_spec = importlib.util.spec_from_file_location("cash_runtime_018", ADAPTER_PATH)
if _spec is None or _spec.loader is None:
    raise CashBindingError("cannot load verified cash adapter")
cash = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cash
_spec.loader.exec_module(cash)


@dataclass(frozen=True)
class CashPackage:
    selections: tuple[CashSelection, ...]
    terms: tuple[Any, ...]
    noncash_keys: tuple[tuple[str, str, str], ...]
    source_snapshot_id: str
    timing_policy_id: str
    amount_policy_id: str


def bind_cash_terms(events: Sequence[Mapping[str, Any]], *, source_snapshot_id: str, timing_policy_id: str, amount_policy_id: str) -> CashPackage:
    """Bind source statements, without assigning coverage or changing missing values.

    The supplied timing is modeled for economic accounting only. Original historical
    availability and actual payment dates are not thereby established.
    """
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id.strip():
        raise CashBindingError("source snapshot identity required")
    if timing_policy_id not in TIMING_POLICIES or amount_policy_id != AMOUNT_POLICY:
        raise CashBindingError("explicit supported timing and amount policies required")
    selections: list[CashSelection] = []
    terms: list[Any] = []
    noncash: list[tuple[str, str, str]] = []
    seen: set[tuple[str, Any]] = set()
    for event in events:
        selected = select_cash(event)
        key = (selected.code, selected.effective_date)
        if key in seen:
            raise CashBindingError("duplicate code/date dividend source event")
        seen.add(key)
        selections.append(selected)
        # Rights-plus-cash still requires independent share/subscription handling.
        if "權" in selected.kind:
            noncash.append((selected.market, selected.code, selected.effective_date.isoformat()))
        if selected.status == "noncash_domain":
            continue
        entitlement = datetime.combine(selected.effective_date, time(7), tzinfo=TAIPEI)
        terms.append(
            cash.CashDividend(
                event_id=f"cash:{selected.market}:{selected.code}:{selected.effective_date.isoformat()}",
                code=selected.code,
                credited_per_share=selected.amount,
                entitlement_at=entitlement,
                payment_at=entitlement + timedelta(days=TIMING_POLICIES[timing_policy_id]),
                source_available_at=entitlement,
                source_id=f"{source_snapshot_id}|{selected.market}/{selected.code}/{selected.effective_date.isoformat()}|accounting-time-assumed",
                policy_id=f"{selected.policy_id}|{timing_policy_id}|{amount_policy_id}",
                time_basis="assumed",
            )
        )
    return CashPackage(tuple(selections), tuple(terms), tuple(noncash), source_snapshot_id, timing_policy_id, amount_policy_id)


def build_cash_domain_provider(package: CashPackage, *, coverage: Sequence[Any]):
    """Caller's explicit cash-domain coverage only; compose other domains separately."""
    return cash.build_cash_provider(package.terms, coverage, initial_cash_cents=200_000_000, max_positions=5, rounding_policy="account-cent-half-up")


def package_records(package: CashPackage) -> list[dict[str, Any]]:
    by_key = {(term.code, term.entitlement_at.date()): term for term in package.terms}
    records = []
    for selection in package.selections:
        term = by_key.get((selection.code, selection.effective_date))
        records.append({
            "market": selection.market,
            "code": selection.code,
            "effective_date": selection.effective_date.isoformat(),
            "kind": selection.kind,
            "selection_status": selection.status,
            "unresolved_reason": selection.unresolved_reason,
            "selected_per_share": str(selection.amount) if selection.amount is not None else None,
            "selected_sources": list(selection.selected_sources),
            "all_candidates": list(selection.all_candidates),
            "selection_policy": selection.policy_id,
            "event_id": term.event_id if term else None,
            "modeled_entitlement_at": term.entitlement_at.isoformat() if term else None,
            "modeled_payment_at": term.payment_at.isoformat() if term else None,
            "modeled_source_available_at": term.source_available_at.isoformat() if term else None,
            "historical_available_at": None,
            "observed_payment_at": None,
            "time_basis": "assumed" if term else None,
            "amount_policy": package.amount_policy_id,
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent != HERE or output.exists():
        raise CashBindingError("output must be a fresh file directly inside this batch")
    payload = json.loads(checked(SOURCE, SOURCE_HASH))
    packages = [
        bind_cash_terms(payload["events"], source_snapshot_id=f"015:{SOURCE_HASH}", timing_policy_id=policy, amount_policy_id=AMOUNT_POLICY)
        for policy in TIMING_POLICIES
    ]
    first = packages[0]
    report = {
        "status": "cash_terms_bound_not_strategy_execution_or_corporate_coverage",
        "source_path": str(SOURCE),
        "source_sha256": SOURCE_HASH,
        "adapter_sha256": ADAPTER_HASH,
        "binder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "selection_sha256": hashlib.sha256((HERE / "selection.py").read_bytes()).hexdigest(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "selection_counts": dict(Counter(item.status for item in first.selections)),
        "term_count_per_scenario": len(first.terms),
        "noncash_domain_keys": first.noncash_keys,
        "coverage_created": False,
        "amount_policy": AMOUNT_POLICY,
        "scenarios": {
            package.timing_policy_id: {"records": package_records(package), "payment_delay_calendar_days": TIMING_POLICIES[package.timing_policy_id]}
            for package in packages
        },
    }
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
