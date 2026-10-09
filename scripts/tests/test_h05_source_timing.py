"""Source timing wiring with synthetic dependencies and no retained-file reads."""

import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

LOCATION = Path(__file__).resolve().parents[2] / "tasks" / "20261005-relative-strength-holding" / "source_bindings.py"
SPEC = importlib.util.spec_from_file_location("h05_source_timing_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
binding_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = binding_module
SPEC.loader.exec_module(binding_module)


@pytest.mark.parametrize("delay", [True, False, 45.0, 90.0, "45", 0, 46, None])
def test_invalid_delay_rejected_before_dependencies_or_source_reads(monkeypatch: pytest.MonkeyPatch, delay: object) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid timing must not read any source")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    with pytest.raises(ValueError, match="45 or 90 calendar days"):
        binding_module.bind_existing_sources({}, cash_payment_delay_days=delay)


@pytest.mark.parametrize("delay", [None, 45, 90])
def test_real_binding_passes_matching_cash_and_composition_timing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    delay: int | None,
) -> None:
    selected = 45 if delay is None else delay
    body = json.dumps({"records": [], "events": []}).encode()
    digest = hashlib.sha256(body).hexdigest()
    reads = []
    calls: dict[str, Any] = {}
    factories = []
    monkeypatch.setattr(binding_module, "EVIDENCE_ROOT", tmp_path)
    monkeypatch.setattr(binding_module, "ACTIVE_ROOT", tmp_path)
    monkeypatch.setattr(binding_module, "CAPITAL_ANNUAL_HASH", digest)
    monkeypatch.setattr(binding_module, "local_source_paths", lambda: ())
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: self)

    def read(self: Path) -> bytes:
        reads.append(self)
        return body

    monkeypatch.setattr(Path, "read_bytes", read)
    package = SimpleNamespace(terms=(), noncash_keys=())

    def cash_bind(events: object, **kwargs: object) -> object:
        calls["cash"] = kwargs
        return package

    def fresh_factory(*args: object) -> object:
        def construct() -> object:
            def provider(*args: object) -> SimpleNamespace:
                return SimpleNamespace(complete=True, events=())

            factories.append(provider)
            return provider

        return construct

    plan = SimpleNamespace(new_factory=fresh_factory)

    def prepare(modules: object, bindings: object, **kwargs: object) -> object:
        calls["prepare"] = kwargs
        calls["bindings"] = bindings
        return plan

    monkeypatch.setattr(binding_module, "prepare_economics", prepare)

    def offer(code: str) -> SimpleNamespace:
        return SimpleNamespace(code=code, at=binding_module.BEGINNING, event_id=f"synthetic:{code}", limits=object())

    modules = {
        "readset": SimpleNamespace(FACTOR_HASH=digest, PRICE_HASHES={"tpex-official": "synthetic-price-hash"}),
        "model": SimpleNamespace(POLICY_ID="synthetic-model", model_adjustments=lambda *args, **kwargs: ()),
        "cash_terms": SimpleNamespace(SOURCE=tmp_path / "cash.json", SOURCE_HASH=digest, AMOUNT_POLICY="synthetic-amount", bind_cash_terms=cash_bind),
        "event_limits": SimpleNamespace(
            bind_cash_event_limits=lambda *args: {},
            bind_named_rights_execution_limits=lambda records, identities: {key: object() for key in identities},
        ),
        "capital_event": SimpleNamespace(bind_capital_event=lambda *args: "unchanged-capital"),
        "stock_rights": SimpleNamespace(bind_share_event=lambda *args: "unchanged-share", bind_tpex_share_event=lambda *args: "unchanged-tpex-share"),
        "mixed_rights": SimpleNamespace(bind_mixed_share_event=lambda *args: "unchanged-mixed-share"),
        "paid_rights": SimpleNamespace(bind_declined_offer=lambda records, code: offer(code), build_declining_provider=lambda *args: None),
        "source_binding": SimpleNamespace(source_paths=lambda: (), named_cases=lambda: ()),
        "no_trade_execution": SimpleNamespace(bind_no_trade_source=lambda *args: SimpleNamespace(code="4192", day=date(2020, 1, 2))),
    }
    for code in ("6438", "2641", "3680", "6443"):
        modules[f"declined_{code}"] = SimpleNamespace(bind_offer=lambda *args, code=code: offer(code), build_declining_provider=lambda *args: None)
    kwargs = {} if delay is None else {"cash_payment_delay_days": delay}
    sources = binding_module.bind_existing_sources(modules, **kwargs)
    assert calls["cash"]["timing_policy_id"] == f"ex-date-plus{selected}-calendar-days-v1"
    assert calls["prepare"]["payment_delay_days"] == selected
    assert calls["bindings"].cash_package is package
    assert calls["bindings"].capital[0].event == "unchanged-capital"
    assert calls["bindings"].shares[0].event == "unchanged-share"
    assert calls["bindings"].mixed[0].event == "unchanged-mixed-share"
    assert sources.economics is plan
    assert sources.cash_payment_delay_days == selected
    assert reads and set(sources.input_sha256.values()) == {digest}
    timing = binding_module.preflight_summary(sources)["modeled_cash_timing"]
    assert timing["payment_delay_calendar_days"] == selected
    assert timing["policy_id"] == calls["cash"]["timing_policy_id"]
    first = sources.economics.new_factory([], [])()
    second = sources.economics.new_factory([], [])()
    assert first is not second
    assert len(factories) == 3  # Native binding smoke plus two independent constructions.
