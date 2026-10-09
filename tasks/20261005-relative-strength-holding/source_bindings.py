"""Bind retained economic/quote evidence without reading prices or running H05.

Physical capture locations are explicit; historical raw_path values inside the
evidence are never rewritten when an artifact has moved between worktrees.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from economics import BoundCapital, BoundPaid, BoundShare, EconomicBindings, prepare_economics  # noqa: E402
from source_modules import ACTIVE_ROOT, EVIDENCE_ROOT, load_adapters, local_source_paths  # noqa: E402

LOGGER = logging.getLogger(__name__)
BEGINNING = datetime.fromisoformat("2019-01-02T06:00:00+08:00")
ENDING = datetime.fromisoformat("2023-12-29T20:00:00+08:00")
CAPITAL_FACTOR_ID = "annual:twtauu:2316:2019-10-07:12"
CAPITAL_ANNUAL_HASH = "ef33ba24aae08df2d71eab09da9cc6fea3534fff00e53488717b987271e078e0"  # pragma: allowlist secret


@dataclass(frozen=True)
class BoundSources:
    economics: Any
    bindings: EconomicBindings
    adjustments: tuple[Any, ...]
    halt_cases: tuple[Any, ...]
    no_trade: Any
    input_sha256: Mapping[str, str]
    cash_payment_delay_days: int = 45


def bind_existing_sources(modules: Mapping[str, Any], *, cash_payment_delay_days: int = 45) -> BoundSources:
    """Validate only previously selected named sources and return native leaves."""
    if type(cash_payment_delay_days) is not int or cash_payment_delay_days not in (45, 90):
        raise ValueError("cash payment delay must be 45 or 90 calendar days")
    timing_policy_id = f"ex-date-plus{cash_payment_delay_days}-calendar-days-v1"
    LOGGER.info("Binding modeled cash timing: %s", timing_policy_id)
    inputs: dict[str, str] = {}

    def read(path: Path, expected: str | None = None) -> bytes:
        path = path.resolve(strict=True)
        if not path.is_relative_to(EVIDENCE_ROOT.resolve()):
            raise ValueError(f"source outside declared evidence root: {path}")
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if expected is not None and digest != expected:
            raise ValueError(f"source identity changed: {path}")
        inputs[path.relative_to(EVIDENCE_ROOT).as_posix()] = digest
        return body

    scratch = EVIDENCE_ROOT / ".tmp/claude-kline"
    raw = EVIDENCE_ROOT / "shioaji_stock_prices/data/raw"
    captures = EVIDENCE_ROOT / ".worktrees/codex-workspace/.tmp"
    pilot = ACTIVE_ROOT / "tasks/20260921-evening-pilot"
    factor_payload = json.loads(read(scratch / "025-signal-factor-inputs/signal-factor-readset-v1.json", modules["readset"].FACTOR_HASH))
    records = factor_payload["records"]
    modeled = modules["model"].model_adjustments(records, policy_id=modules["model"].POLICY_ID)
    adjustments = tuple(item.adjustment for item in modeled)
    cash = modules["cash_terms"]
    cash_payload = json.loads(read(cash.SOURCE, cash.SOURCE_HASH))
    package = cash.bind_cash_terms(
        cash_payload["events"],
        source_snapshot_id=f"015:{cash.SOURCE_HASH}",
        timing_policy_id=timing_policy_id,
        amount_policy_id=cash.AMOUNT_POLICY,
    )
    cash_keys = {(term.code, term.entitlement_at.date()) for term in package.terms}
    rights_keys = {(code, date.fromisoformat(day)) for _market, code, day in package.noncash_keys}
    limits_module = modules["event_limits"]
    initial_limits = limits_module.bind_cash_event_limits(records, cash_keys, rights_keys)
    named_limits = limits_module.bind_named_rights_execution_limits(records, {(date(2022, 10, 27), "9945"): "annual:twt49u:9945:2022-10-27:968"})
    if initial_limits.keys() & named_limits.keys():
        raise ValueError("named rights quote limits overlap cash-only quote limits")
    initial_limits.update(named_limits)

    capital = modules["capital_event"].bind_capital_event(
        json.loads(read(pilot / "capital-2316-source.json")),
        json.loads(read(raw / "twse/twtauu/20190101_20191231.json", CAPITAL_ANNUAL_HASH)),
    )
    stock = modules["stock_rights"]
    share_specs = (
        ("rights-2915-source.json", "annual:twt49u:2915:2021-10-04:883"),
        ("rights-2823-source.json", "annual:twt49u:2823:2021-10-25:916"),
    )
    shares = [BoundShare(stock.bind_share_event(json.loads(read(pilot / name)), records), identity) for name, identity in share_specs]
    shares.append(
        BoundShare(
            stock.bind_tpex_share_event(read(captures / "pilot-v6-6472-detail/response-002.json"), records),
            "annual:exdailyq:6472:2022-08-30:797",
        )
    )
    mixed_root = EVIDENCE_ROOT / ".tmp/claude-download/005-artifacts-46d07a89845348c0b1757f988d53dfce/captures"
    mixed_specs = (
        ("3588-110", "annual:twt49u:3588:2021-09-02:734"),
        ("3617-112", "annual:twt49u:3617:2023-08-16:823"),
    )
    mixed = tuple(
        BoundShare(modules["mixed_rights"].bind_mixed_share_event(read(mixed_root / directory / "response-002.json"), records), identity)
        for directory, identity in mixed_specs
    )
    paid: list[BoundPaid] = []
    native_paid = modules["paid_rights"]
    for code in ("3363", "4768"):
        offer = native_paid.bind_declined_offer(records, code=code)
        key = (offer.at.date(), offer.code)
        limits = limits_module.bind_named_rights_execution_limits(records, {key: offer.event_id})[key]
        paid.append(BoundPaid(offer, native_paid.build_declining_provider, limits))
    for code, annual in (("6438", "20190101_20191231.json"), ("2641", "20210101_20211231.json"), ("3680", "20190101_20191231.json")):
        binder = modules[f"declined_{code}"]
        offer = binder.bind_offer(read(raw / "tpex/exdailyq" / annual), records)
        paid.append(BoundPaid(offer, binder.build_declining_provider, offer.limits))
    binder = modules["declined_6443"]
    offer = binder.bind_offer(
        read(raw / "twse/twt49u/20200101_20201231.json"),
        read(captures / "6443-detail-capture-20261002/raw-001.json"),
        read(captures / "6443-detail-capture-20261002/events.jsonl"),
        records,
    )
    paid.append(BoundPaid(offer, binder.build_declining_provider, offer.limits))
    bindings = EconomicBindings(package, (BoundCapital(capital, CAPITAL_FACTOR_ID),), tuple(shares), mixed, tuple(paid))
    plan = prepare_economics(
        modules,
        bindings,
        factors=[(event.effective_on, event.code, event.event_id) for event in adjustments],
        beginning=BEGINNING,
        ending=ENDING,
        initial_limits=initial_limits,
        payment_delay_days=cash_payment_delay_days,
    )
    for path in modules["source_binding"].source_paths():
        read(path)
    halt_cases = modules["source_binding"].named_cases()
    no_trade_path = EVIDENCE_ROOT / ".worktrees/codex-workspace/tasks/20261002-momentum-probe/no-trade-4192-source.json"
    no_trade = modules["no_trade_execution"].bind_no_trade_source(json.loads(read(no_trade_path)), modules["readset"].PRICE_HASHES["tpex-official"])
    # A synthetic empty prefix exercises native constructors and the real core
    # seam, not a historical portfolio or a claim about held-event completeness.
    provider = plan.new_factory([], [])()
    evidence = provider(BEGINNING, BEGINNING + timedelta(minutes=1), ())
    if evidence.complete is not True or evidence.events:
        raise ValueError("source-bound empty-prefix provider smoke failed")
    # Include lazy source imports made by constructors. Registered execution will
    # additionally reject unlisted imports at both ends of every actual run.
    for path in local_source_paths():
        read(path)
    LOGGER.info("Bound %d cash terms, %d supported noncash events; no H05 prices or results read", len(package.terms), 1 + len(shares) + len(mixed) + len(paid))
    return BoundSources(plan, bindings, adjustments, halt_cases, no_trade, inputs, cash_payment_delay_days)


def preflight_summary(sources: BoundSources) -> dict[str, Any]:
    """Scope-labelled source inventory, not an account or coverage certification."""
    bindings = sources.bindings
    return {
        "status": "named_sources_bound_not_market_execution",
        "scope": "retained source records; not H05 held events or complete corporate-domain certification",
        "cash_terms": len(bindings.cash_package.terms),
        "modeled_cash_timing": {
            "payment_delay_calendar_days": sources.cash_payment_delay_days,
            "policy_id": f"ex-date-plus{sources.cash_payment_delay_days}-calendar-days-v1",
            "basis": "modeled assumption, not observed payment timing",
        },
        "capital_events": len(bindings.capital),
        "free_share_events": len(bindings.shares),
        "mixed_events": len(bindings.mixed),
        "declined_paid_offers": len(bindings.paid),
        "named_halt_cases": len(sources.halt_cases),
        "named_regular_no_trade": {"code": sources.no_trade.code, "day": sources.no_trade.day.isoformat()},
        "input_files": len(sources.input_sha256),
        "native_empty_prefix_smoke": "passed; not a historical account",
        "market_execution": False,
        "historical_availability": "unknown; declared economic timing assumptions remain",
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(preflight_summary(bind_existing_sources(load_adapters())), ensure_ascii=False))
