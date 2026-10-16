import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import annual_completion_evidence as adapter
from research_core.annual_rotation_v2 import economic_path_v2


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def identity(raw: bytes) -> dict[str, Any]:
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def publication(tmp_path: Path, *, body_path: str = "facts.json", bound_digest: str | None = None) -> dict[str, bytes]:
    body = encoded({"amount": "100", "unit": "shares_per_1000"})
    body_identity = identity(body)
    candidate = {
        "sources": [{"evidence_id": "official-1", "raw_body": {"path": body_path, **body_identity, **({"sha256": bound_digest} if bound_digest else {})}}],
        "events": [],
        "daily_gap_observations": [],
    }
    members = {adapter.CANDIDATE: encoded(candidate), "captured/facts.json": body, "captured/rows.jsonl": b'{"row":1}\n{"row":2}\n'}
    for name, raw in members.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (tmp_path / "publication.json").write_bytes(
        encoded({"schema": "annual-source-evidence.v1", "members": {name: identity(raw) for name, raw in members.items()}})
    )
    return members


def test_loader_hashes_each_consumed_member_once_and_keeps_the_same_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    members = publication(tmp_path)
    original_hash = hashlib.sha256
    original_open = Path.open
    hashed = []
    opened: dict[str, int] = {}

    def sha256(raw: bytes = b"") -> Any:
        hashed.append(raw)
        return original_hash(raw)

    def opened_once(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "rb" and path.is_relative_to(tmp_path) and path.relative_to(tmp_path).as_posix() in members:
            name = path.relative_to(tmp_path).as_posix()
            opened[name] = opened.get(name, 0) + 1
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(adapter.hashlib, "sha256", sha256)
    monkeypatch.setattr(Path, "open", opened_once)
    evidence = adapter.load_verified_evidence(tmp_path)
    assert len(hashed) == len(members)
    assert opened == dict.fromkeys(members, 1)
    assert evidence.retained_bytes == sum(map(len, members.values()))
    assert evidence.verification_seconds >= 0
    (tmp_path / "captured/facts.json").write_bytes(b"changed after verification")
    assert evidence.json("captured/facts.json") == {"amount": "100", "unit": "shares_per_1000"}
    assert evidence.jsonl("captured/rows.jsonl") == [{"row": 1}, {"row": 2}]
    assert len(hashed) == len(members)
    assert opened == dict.fromkeys(members, 1)


def test_loader_rejects_member_tampering_and_unbound_source_facts(tmp_path: Path):
    publication(tmp_path)
    (tmp_path / "captured/facts.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="identity mismatch"):
        adapter.load_verified_evidence(tmp_path)
    publication(tmp_path, bound_digest="0" * 64)
    with pytest.raises(ValueError, match="unbound source fact"):
        adapter.load_verified_evidence(tmp_path)


@pytest.mark.parametrize("name", ["../outside.json", "/outside.json", "C:/outside.json", "captured\\outside.json"])
def test_loader_rejects_unsafe_member_paths(tmp_path: Path, name: str):
    publication(tmp_path)
    manifest = json.loads((tmp_path / "publication.json").read_bytes())
    manifest["members"] = {name: {"bytes": 0, "sha256": "0" * 64}}
    (tmp_path / "publication.json").write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match="unsafe artifact name"):
        adapter.load_verified_evidence(tmp_path)


def test_loader_rejects_unsafe_fact_locator_and_oversized_member(tmp_path: Path):
    publication(tmp_path, body_path="../facts.json")
    with pytest.raises(ValueError, match="unsafe artifact name"):
        adapter.load_verified_evidence(tmp_path)
    publication(tmp_path)
    manifest = json.loads((tmp_path / "publication.json").read_bytes())
    manifest["members"][adapter.CANDIDATE]["bytes"] = 32_000_001
    (tmp_path / "publication.json").write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match="size limit"):
        adapter.load_verified_evidence(tmp_path)


@pytest.mark.parametrize(
    "left,right,expected", [("100.00000041", "100.00000049", "100.000000"), ("1.2345665", "1.2345664", "1.234566"), ("1.2345675", "1.2345676", "1.234568")]
)
def test_r8_agreement_uses_six_decimals_in_source_units(left: str, right: str, expected: str):
    assert adapter.agreed(Decimal(left), Decimal(right)) == Decimal(expected)


def test_r8_conflict_is_not_averaged():
    with pytest.raises(ValueError, match="source term conflict"):
        adapter.agreed(Decimal("100.0000001"), Decimal("100.0000009"))


def prices_for(code: str) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    dates = pd.DatetimeIndex(["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"])
    return pd.DataFrame({"Code": code, "Date": dates, "Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0, "Volume": 1.0}), dates


def source_fact(attribute: str, value: str, unit: str) -> dict[str, Any]:
    return {"attribute": attribute, "raw_value": value, "unit": unit, "fact_status": "source_explicit", "evidence_ids": ["official-1"]}


def base_event(code: str, kind: str = "EX_RIGHT_AND_DIVIDEND") -> dict[str, Any]:
    return {
        "event_id": "event-1",
        "code": code,
        "event_type": kind,
        "source_evidence_ids": ["official-1"],
        "date_roles": [{"role": "study_input_ex_date", "date": "2020-01-07"}],
        "source_facts": [],
        "market_intervals": [],
    }


def evidence_for(candidate: dict[str, Any], members: dict[str, bytes] | None = None) -> adapter.Evidence:
    payloads = {
        adapter.CANDIDATE: encoded({"sources": [{"evidence_id": "official-1"}], "events": [], "daily_gap_observations": [], **candidate}),
        **(members or {}),
    }
    return adapter.Evidence({"members": {name: identity(raw) for name, raw in payloads.items()}}, payloads, sum(map(len, payloads.values())), 0.0)


def stated(value: Any) -> dict[str, Any]:
    return {"status": "stated", "value": value}


def rights_evidence(code: str = "3205", *, cash: Any = "2", exchange_bonus: str = "100") -> adapter.Evidence:
    body = b"captured issuer page"
    date = "2020-01-07"
    record = {
        "company_id": code,
        "capture_relative_path": f"issuer-{code}.html",
        "body_sha256": identity(body)["sha256"],
        "fields": {"stated_ex_date": stated(date), "cash_per_share": stated(cash)},
        "rights_fields": {
            key: stated(value)
            for key, value in {
                "subscription_class": "普通股",
                "earnings_free_per_thousand": "100",
                "reserves_free_per_thousand": "0",
                "subscription_per_thousand": "50",
                "subscription_price": "30",
            }.items()
        },
    }
    exchange = {
        "tables": [
            {
                "fields": ["代號", "除權息日期", "每仟股無償配股", "現金股利", "按持股比例仟股認購", "現金增資認購價"],
                "data": [[code, "109/01/07", exchange_bonus, "2", "50", "30"]],
            }
        ]
    }
    return evidence_for(
        {"events": [base_event(code)]},
        {
            "rights-projections-v2.json": encoded({"records": [record]}),
            f"captured/issuer-{code}.html": body,
            f"captured/tpex-current/exdailyq-{code}-{date}.json": encoded(exchange),
        },
    )


def admit(evidence: adapter.Evidence, code: str, prices: pd.DataFrame | None = None) -> adapter.Admission:
    frame, dates = prices_for(code)
    return adapter.build_admission(evidence, frame if prices is None else prices, pd.DataFrame(), dates)


def test_rights_terms_are_linked_without_factor_to_share_inference():
    result = admit(rights_evidence(), "3205")
    assert not result.unresolved
    assert len(result.entitlements) == 1
    term = result.entitlements[0]
    assert term.share_multiplier == 1.1
    assert term.cash_per_old_share == 2
    assert term.rights_per_old_share == 0.05
    assert term.subscription_price == 30
    assert term.announced_date == term.effective_date == "2020-01-07"
    assert term.source_event_type == "EX_RIGHT_AND_DIVIDEND"


@pytest.mark.parametrize("failure", ["missing_cash", "r8_conflict", "unbound_projection", "wrong_projection_date", "wrong_exchange_code"])
def test_term_failure_blocks_holding_instead_of_defaulting_cash_or_rights_to_zero(failure: str):
    evidence = rights_evidence(cash=None if failure == "missing_cash" else "2", exchange_bonus="100.000002" if failure == "r8_conflict" else "100")
    if failure in {"unbound_projection", "wrong_projection_date"}:
        projection = evidence.json("rights-projections-v2.json")
        if failure == "unbound_projection":
            projection["records"][0]["body_sha256"] = "0" * 64
        else:
            projection["records"][0]["fields"]["stated_ex_date"] = stated("2020-01-08")
        evidence.members["rights-projections-v2.json"] = encoded(projection)
    if failure == "wrong_exchange_code":
        name = "captured/tpex-current/exdailyq-3205-2020-01-07.json"
        exchange = evidence.json(name)
        exchange["tables"][0]["data"][0][0] = "9999"
        evidence.members[name] = encoded(exchange)
    result = admit(evidence, "3205")
    assert result.entitlements == ()
    assert result.unresolved[0]["code"] == "3205"
    assert result.unresolved[0]["year"] == 2020
    assert result.unresolved[0]["reasons"]
    assert result.audit[0]["status"] == "unresolved"


def literal_evidence() -> adapter.Evidence:
    evidence = rights_evidence("3406", cash=None)
    literal = {
        "effective_date_from_annual_row": "2020-01-07",
        "literal_fields": {
            "股票代號": "3406",
            "A. 按普通股股東持股比例每千股無償配股": "100 股",
            "(每股配發現金股利)除息": "0 元／股",
            "按股東持股比例每千股認購": "20 股",
            "每股認購金額": "50 元／股",
        },
    }
    evidence.members["captured/capture-3406/events.jsonl"] = encoded(literal) + b"\n"
    return evidence


def test_twse_literal_uses_explicit_units_when_older_issuer_projection_is_unsupported():
    result = admit(literal_evidence(), "3406")
    assert not result.unresolved
    assert result.entitlements[0].share_multiplier == 1.1
    assert result.entitlements[0].cash_per_old_share == 0
    assert result.entitlements[0].rights_per_old_share == 0.02
    assert result.entitlements[0].subscription_price == 50


@pytest.mark.parametrize("failure", ["unit", "date", "code", "duplicate"])
def test_twse_literal_requires_exact_units_code_and_date(failure: str):
    evidence = literal_evidence()
    name = "captured/capture-3406/events.jsonl"
    row = evidence.jsonl(name)[0]
    if failure == "unit":
        row["literal_fields"]["按股東持股比例每千股認購"] = "20 %"
    elif failure == "date":
        row["effective_date_from_annual_row"] = "2020-01-08"
    elif failure == "code":
        row["literal_fields"]["股票代號"] = "9999"
    evidence.members[name] = encoded(row) + b"\n" + (encoded(row) + b"\n" if failure == "duplicate" else b"")
    result = admit(evidence, "3406")
    assert not result.entitlements
    assert result.unresolved[0]["reasons"]


@pytest.mark.parametrize("failure", ["missing", "duplicate", "zero", "nan", "bad_geometry"])
def test_cash_and_rights_require_an_actual_valid_same_day_ohlc(failure: str):
    prices, _ = prices_for("3205")
    if failure == "missing":
        prices = prices.drop(index=1)
    elif failure == "duplicate":
        prices = pd.concat([prices, prices.iloc[[1]]], ignore_index=True)
    elif failure == "zero":
        prices.loc[1, "Close"] = 0
    elif failure == "nan":
        prices.loc[1, "Close"] = np.nan
    else:
        prices.loc[1, "Low"] = 101
    result = admit(rights_evidence(), "3205", prices)
    assert result.entitlements == ()
    assert result.unresolved[0]["reasons"]


def test_share_change_uses_first_actual_resumption_quote_and_preserves_original_date():
    event = base_event("6276", "LOSS_OFFSET_CAPITAL_REDUCTION")
    event["date_roles"] = [{"role": "resumption_date", "date": "2020-01-07"}]
    event["source_facts"] = [source_fact("shares_reduced_per_1000_existing", "600", "shares_per_1000_existing_shares")]
    prices, _ = prices_for("6276")
    result = admit(evidence_for({"events": [event]}), "6276", prices.drop(index=1))
    assert not result.unresolved
    assert result.entitlements[0].announced_date == "2020-01-07"
    assert result.entitlements[0].effective_date == "2020-01-08"
    assert result.entitlements[0].share_multiplier == 0.4


def gap(day: str = "2020-01-07", *, evidence_ids: list[str] | None = None, event_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "gap_id": "gap-" + day,
        "code": "1234",
        "date": day,
        "evidence_ids": ["official-1"] if evidence_ids is None else evidence_ids,
        "event_ids": event_ids or [],
        "observation_kind": "missing_close",
        "source_observation": {"open": None, "high": None, "low": None, "close": None},
        "cause_status": "cause_unknown",
    }


def test_source_bound_all_null_ohlc_can_be_n_without_inventing_a_halt_cause():
    observation = gap()
    result = admit(evidence_for({"daily_gap_observations": [observation]}), "1234")
    assert result.unavailable_by_code == {"1234": {"2020-01-07": "N"}}
    assert result.audit[-1]["cause_status"] == "cause_unknown"
    assert result.audit[-1]["source_observation"] == observation["source_observation"]


@pytest.mark.parametrize("evidence_ids", [[], ["unregistered-source"]])
def test_missing_or_unregistered_source_cannot_admit_h_or_n(evidence_ids: list[str]):
    result = admit(evidence_for({"daily_gap_observations": [gap(evidence_ids=evidence_ids)]}), "1234")
    assert not result.unavailable_by_code


def test_partial_ohlc_or_missing_null_fields_cannot_be_n():
    observations = [gap("2020-01-07"), gap("2020-01-08")]
    observations[0]["source_observation"]["open"] = 100
    observations[1]["source_observation"].pop("high")
    result = admit(evidence_for({"daily_gap_observations": observations}), "1234")
    assert not result.unavailable_by_code
    assert [row["class"] for row in result.audit] == ["U", "U"]


def test_open_ended_halt_proves_only_its_documented_start_day():
    event = base_event("1234", "TRADING_SUSPENSION")
    event["market_intervals"] = [
        {
            "type": "trading_suspension",
            "evidence_ids": ["official-1"],
            "start_date": "2020-01-07",
            "end_date": None,
            "start_inclusive": True,
            "end_inclusive": False,
        }
    ]
    observations = [gap("2020-01-07", event_ids=["event-1"]), gap("2020-01-08", event_ids=["event-1"])]
    for observation in observations:
        observation["observation_kind"] = "halt_announcement"
    result = admit(evidence_for({"events": [event], "daily_gap_observations": observations}), "1234")
    assert result.unavailable_by_code == {"1234": {"2020-01-07": "H"}}
    assert [row["class"] for row in result.audit] == ["H", "U"]


def test_trade_conflict_observation_is_preserved_and_does_not_replace_valid_quote():
    event = base_event("1234", "TRADING_SUSPENSION")
    event["market_intervals"] = [
        {
            "type": "trading_suspension",
            "evidence_ids": ["official-1"],
            "start_date": "2020-01-07",
            "end_date": None,
            "start_inclusive": True,
            "end_inclusive": False,
        }
    ]
    observation = gap(event_ids=["event-1"])
    observation.update(
        observation_kind="observed_trade_conflict",
        cause_status="official_halt_but_quote_observed",
        source_observation={"open": 100, "high": 100, "low": 100, "close": 100, "volume": 10},
    )
    original = deepcopy(observation)
    prices, calendar = prices_for("1234")
    result = admit(evidence_for({"events": [event], "daily_gap_observations": [observation]}), "1234", prices)
    audit = result.audit[-1]
    assert audit["source_observation"] == original["source_observation"]
    assert audit["cause_status"] == original["cause_status"]
    assert audit["evidence_ids"] == ["official-1"]
    actions = pd.DataFrame(columns=pd.Index(["code", "ex_date", "event_type", "price_factor", "cash_dividend_estimate"]))
    start, end = calendar[0], calendar[-1]
    assert isinstance(start, pd.Timestamp) and isinstance(end, pd.Timestamp)
    path = economic_path_v2(prices, actions, calendar, start=start, end=end, unavailable_days=result.unavailable_by_code.get("1234", {}))
    assert path["status"] == "modeled"
    assert path["complete_equity"] is True
    assert path["carried_days"] == 0


def test_unsupported_supplement_economic_event_is_unresolved_not_silently_ignored():
    event = base_event("1234", "MERGER")
    result = admit(evidence_for({"events": [event]}), "1234")
    assert result.entitlements == ()
    assert result.unresolved == [{"code": "1234", "year": 2020, "event_dates": ["2020-01-07"], "reasons": ["unsupported supplement economic event: MERGER"]}]
    assert result.audit[0]["status"] == "unresolved"


@pytest.mark.parametrize("conflict", ["different_code", "exclusive_end", "wrong_interval_type"])
def test_halt_interval_must_match_issuer_and_include_the_observed_day(conflict: str):
    event = base_event("9999" if conflict == "different_code" else "1234", "TRADING_SUSPENSION")
    event["market_intervals"] = [
        {
            "type": "trading_method_change" if conflict == "wrong_interval_type" else "trading_suspension",
            "evidence_ids": ["official-1"],
            "start_date": "2020-01-06",
            "end_date": "2020-01-07",
            "start_inclusive": True,
            "end_inclusive": conflict != "exclusive_end",
        }
    ]
    observation = gap(event_ids=["event-1"])
    observation["observation_kind"] = "halt_announcement"
    result = admit(evidence_for({"events": [event], "daily_gap_observations": [observation]}), "1234")
    assert not result.unavailable_by_code
    assert result.audit[-1]["class"] == "U"


@pytest.mark.parametrize("failure", ["later_session", "derivation_date", "announced_is_session"])
def test_r6_rejects_a_later_session_or_inconsistent_date_derivation(failure: str):
    event = base_event("1519")
    event["date_roles"] = [
        {"role": "announced_ex_date", "date": "2020-01-07"},
        {"role": "price_adjustment_trading_date", "date": "2020-01-09" if failure == "later_session" else "2020-01-08"},
    ]
    event["source_facts"] = [
        source_fact("new_shares_per_1000_old_shares", "100", "new_shares_per_1000_old_shares"),
        source_fact("cash_dividend_per_share", "2", "NTD_per_share"),
    ]
    event["date_derivations"] = [
        {
            "status": "inferred_official_rule",
            "date": "2020-01-09" if failure == "derivation_date" else event["date_roles"][1]["date"],
            "evidence_ids": ["ev-twse-close-0723", "ev-twse-close-0724", "ev-twse-disaster-faq", "ev-twse-report-0726"],
        }
    ]
    prices, calendar = prices_for("1519")
    if failure != "announced_is_session":
        calendar = calendar.delete(1)
        prices = prices.loc[prices.Date.isin(calendar)]
    registered = [{"evidence_id": item} for item in ["official-1", "ev-twse-close-0723", "ev-twse-close-0724", "ev-twse-disaster-faq", "ev-twse-report-0726"]]
    result = adapter.build_admission(evidence_for({"events": [event], "sources": registered}), prices, pd.DataFrame(), calendar)
    assert result.entitlements == ()
    assert "official closure/date rule evidence required" in result.unresolved[0]["reasons"][0]


def test_unresolved_event_exports_only_economic_role_dates_for_holding_matching():
    event = base_event("1234", "MERGER")
    event["date_roles"] = [
        {"role": "notice_publication_date", "date": "2019-12-01"},
        {"role": "study_input_ex_date", "date": "2019-12-31"},
        {"role": "announced_ex_date", "date": "2019-12-31"},
        {"role": "price_adjustment_trading_date", "date": "2020-01-06"},
        {"role": "effective_date", "date": "2020-01-07"},
        {"role": "resumption_date", "date": "2020-01-08"},
        {"role": "new_shares_start_trading", "date": "2020-01-09"},
    ]
    result = admit(evidence_for({"events": [event]}), "1234")
    assert result.unresolved[0]["event_dates"] == ["2019-12-31", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"]
    assert result.unresolved[0]["year"] == 2019


@pytest.mark.parametrize("date_roles", [[], [{"role": "notice_publication_date", "date": "2020-01-07"}], [{"role": "effective_date", "date": "invalid"}]])
def test_undated_economic_uncertainty_retains_empty_dates_instead_of_guessing_a_year(date_roles: list[dict[str, str]]):
    event = base_event("1234", "MERGER")
    event["date_roles"] = date_roles
    result = admit(evidence_for({"events": [event]}), "1234")
    assert result.unresolved[0]["event_dates"] == []
    assert result.unresolved[0]["year"] is None


def test_supported_term_failure_also_keeps_all_economic_dates():
    evidence = rights_evidence(cash=None)
    candidate = evidence.json(adapter.CANDIDATE)
    candidate["events"][0]["date_roles"].append({"role": "effective_date", "date": "2020-01-08"})
    evidence.members[adapter.CANDIDATE] = encoded(candidate)
    result = admit(evidence, "3205")
    assert result.entitlements == ()
    assert result.unresolved[0]["event_dates"] == ["2020-01-07", "2020-01-08"]


def share_event(kind: str = "LOSS_OFFSET_CAPITAL_REDUCTION") -> dict[str, Any]:
    event = base_event("1234", kind)
    if kind == "PAR_VALUE_CHANGE":
        event["date_roles"] = [{"role": "new_shares_start_trading", "date": "2020-01-07"}]
        event["source_facts"] = [
            source_fact("new_shares_per_old_share", "20", "new_shares_per_old_share"),
            source_fact("old_par_value", "10", "NTD_per_share"),
            source_fact("new_par_value", "0.5", "NTD_per_share"),
        ]
    else:
        event["date_roles"] = [{"role": "resumption_date", "date": "2020-01-07"}]
        event["source_facts"] = [source_fact("shares_reduced_per_1000_existing", "600", "shares_per_1000_existing_shares")]
    return event


@pytest.mark.parametrize("invalid_ids", [[], None, "official-1", [""], [1], ["unregistered-source"]])
def test_recognized_event_requires_nonempty_registered_top_level_ids(invalid_ids: Any):
    event = share_event()
    event["source_evidence_ids"] = invalid_ids
    result = admit(evidence_for({"events": [event]}), "1234")
    assert result.entitlements == ()
    assert result.unresolved[0]["event_dates"] == ["2020-01-07"]
    assert "source_evidence_ids" in result.unresolved[0]["reasons"][0]


@pytest.mark.parametrize("kind", ["LOSS_OFFSET_CAPITAL_REDUCTION", "PAR_VALUE_CHANGE"])
def test_share_quantity_fact_cannot_reference_an_unregistered_source(kind: str):
    event = share_event(kind)
    event["source_facts"][0]["evidence_ids"] = ["unregistered-source"]
    result = admit(evidence_for({"events": [event]}), "1234")
    assert result.entitlements == ()
    assert result.unresolved[0]["event_dates"] == ["2020-01-07"]
    assert "source_facts" in result.unresolved[0]["reasons"][0]


@pytest.mark.parametrize("field", ["source_facts", "derivations", "date_derivations", "market_intervals"])
@pytest.mark.parametrize("invalid_ids", [[], ["unregistered-source"]])
def test_all_present_nested_metadata_require_registered_evidence(field: str, invalid_ids: list[str]):
    event = share_event()
    if field == "source_facts":
        event[field][0]["evidence_ids"] = invalid_ids
    else:
        event[field] = [{"evidence_ids": invalid_ids}]
    result = admit(evidence_for({"events": [event]}), "1234")
    assert result.entitlements == ()
    assert field in result.unresolved[0]["reasons"][0]


@pytest.mark.parametrize("kind,expected_multiplier", [("LOSS_OFFSET_CAPITAL_REDUCTION", 0.4), ("PAR_VALUE_CHANGE", 20.0)])
def test_nested_sources_can_be_registered_cross_sources_not_listed_at_event_top(kind: str, expected_multiplier: float):
    event = share_event(kind)
    for fact in event["source_facts"]:
        fact["evidence_ids"] = ["official-2"]
    for field in ("derivations", "date_derivations", "market_intervals"):
        event[field] = [{"evidence_ids": ["official-2"]}]
    registered = [{"evidence_id": "official-1"}, {"evidence_id": "official-2"}]
    result = admit(evidence_for({"events": [event], "sources": registered}), "1234")
    assert not result.unresolved
    assert len(result.entitlements) == 1
    assert result.entitlements[0].share_multiplier == expected_multiplier


@pytest.mark.parametrize("kind", ["EX_RIGHT_AND_DIVIDEND", "LOSS_OFFSET_CAPITAL_REDUCTION", "PAR_VALUE_CHANGE", "MERGER"])
@pytest.mark.parametrize("invalid_code", [None, "", " ", " 1234", "1234 ", 1234, False, "unknown", "１２３４"])
def test_unassignable_economic_event_raises_globally_before_supported_type_admission(kind: str, invalid_code: Any):
    event = base_event("1234", kind)
    event["code"] = invalid_code
    with pytest.raises(ValueError, match="valid four-digit issuer code"):
        admit(evidence_for({"events": [event]}), "1234")


def test_market_wide_noneconomic_event_can_have_no_issuer():
    event = base_event("1234", "MARKET_CLOSURE")
    event["code"] = None
    result = admit(evidence_for({"events": [event]}), "1234")
    assert result.entitlements == ()
    assert result.unresolved == []


def test_missing_economic_issuer_is_not_hidden_by_a_previously_valid_event():
    valid = share_event()
    unassignable = base_event("1234", "EX_RIGHT")
    unassignable["event_id"] = "unassignable-event"
    unassignable.pop("code")
    with pytest.raises(ValueError, match="issuer code"):
        admit(evidence_for({"events": [valid, unassignable]}), "1234")


@pytest.mark.parametrize("invalid_id", [None, "", " ", 1234, False, []])
def test_event_ids_must_be_nonempty_strings_before_building_the_index(invalid_id: Any):
    event = share_event()
    event["event_id"] = invalid_id
    with pytest.raises(ValueError, match="event_id must be a nonempty string"):
        admit(evidence_for({"events": [event]}), "1234")


@pytest.mark.parametrize("hidden_event", ["economic", "no_issuer", "noneconomic"])
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_event_id_cannot_overwrite_economic_or_invalid_issuer_events(hidden_event: str, reverse: bool):
    earlier = share_event()
    if hidden_event == "no_issuer":
        earlier["code"] = None
    elif hidden_event == "noneconomic":
        earlier["event_type"] = "TRADING_SUSPENSION"
    later = base_event("1234", "TRADING_METHOD_CHANGE")
    records = [later, earlier] if reverse else [earlier, later]
    with pytest.raises(ValueError, match="duplicate supplement event_id"):
        admit(evidence_for({"events": records}), "1234")


def test_distinct_event_ids_keep_each_unresolved_economic_event():
    first = base_event("1234", "MERGER")
    second = base_event("5678", "MERGER")
    second["event_id"] = "event-2"
    result = admit(evidence_for({"events": [first, second]}), "1234")
    assert [row["code"] for row in result.unresolved] == ["1234", "5678"]
    assert [row["event_id"] for row in result.audit] == ["event-1", "event-2"]


def rewrite_candidate(tmp_path: Path, members: dict[str, bytes], raw: bytes) -> None:
    members[adapter.CANDIDATE] = raw
    (tmp_path / adapter.CANDIDATE).write_bytes(raw)
    (tmp_path / "publication.json").write_bytes(
        encoded({"schema": "annual-source-evidence.v1", "members": {name: identity(value) for name, value in members.items()}})
    )


@pytest.mark.parametrize("sources", [None, {}, [None], [{"evidence_id": None}], [{"evidence_id": ""}], [{"evidence_id": " "}], [{"evidence_id": 1}]])
def test_source_registry_shape_and_identifiers_fail_globally_in_loader_and_admission(tmp_path: Path, sources: Any):
    members = publication(tmp_path)
    candidate = json.loads(members[adapter.CANDIDATE])
    candidate["sources"] = sources
    rewrite_candidate(tmp_path, members, encoded(candidate))
    with pytest.raises(ValueError, match="source"):
        adapter.load_verified_evidence(tmp_path)
    with pytest.raises(ValueError, match="source"):
        admit(evidence_for(candidate), "1234")


def test_duplicate_source_id_cannot_fold_distinct_captured_bodies_into_one_identity(tmp_path: Path):
    members = publication(tmp_path)
    candidate = json.loads(members[adapter.CANDIDATE])
    other_body = b"a distinct verified source"
    members["captured/other.json"] = other_body
    (tmp_path / "captured/other.json").write_bytes(other_body)
    candidate["sources"].append({"evidence_id": "official-1", "raw_body": {"path": "other.json", **identity(other_body)}})
    rewrite_candidate(tmp_path, members, encoded(candidate))
    with pytest.raises(ValueError, match="duplicate source evidence_id"):
        adapter.load_verified_evidence(tmp_path)
    with pytest.raises(ValueError, match="duplicate source evidence_id"):
        admit(evidence_for(candidate), "1234")


def test_distinct_verified_sources_remain_available_under_distinct_ids(tmp_path: Path):
    members = publication(tmp_path)
    candidate = json.loads(members[adapter.CANDIDATE])
    second = deepcopy(candidate["sources"][0])
    second["evidence_id"] = "official-2"
    candidate["sources"].append(second)
    rewrite_candidate(tmp_path, members, encoded(candidate))
    evidence = adapter.load_verified_evidence(tmp_path)
    result = admit(evidence, "1234")
    assert not result.unresolved
    assert len(evidence.json(adapter.CANDIDATE)["sources"]) == 2


@pytest.mark.parametrize("raw", [b'{"value":1,"value":2}', b'{"nested":{"value":1,"value":2}}', b'{"value":NaN}', b'{"value":Infinity}', b"[]", b"null"])
@pytest.mark.parametrize("format", ["json", "jsonl"])
def test_evidence_json_and_jsonl_reject_ambiguous_nonfinite_or_nonobject_records(raw: bytes, format: str):
    name = "member." + format
    evidence = adapter.Evidence({}, {name: raw}, len(raw), 0)
    with pytest.raises(ValueError):
        evidence.json(name) if format == "json" else evidence.jsonl(name)


def test_candidate_duplicate_event_key_is_rejected_before_identity_validation(tmp_path: Path):
    members = publication(tmp_path)
    rewrite_candidate(tmp_path, members, b'{"sources":[],"events":[{"event_id":"one","code":null,"code":"1234"}],"daily_gap_observations":[]}')
    with pytest.raises(ValueError, match="duplicate"):
        adapter.load_verified_evidence(tmp_path)
    evidence = adapter.Evidence({}, members, 0, 0)
    with pytest.raises(ValueError, match="duplicate"):
        admit(evidence, "1234")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema":"other","schema":"annual-source-evidence.v1","members":{}}',
        b'{"schema":"annual-source-evidence.v1","members":{},"members":{}}',
        b"[]",
        b"null",
        b'{"value":Infinity}',
    ],
)
def test_manifest_is_strictly_parsed_before_any_duplicate_key_can_be_lost(tmp_path: Path, raw: bytes):
    (tmp_path / "publication.json").write_bytes(raw)
    with pytest.raises(ValueError):
        adapter.load_verified_evidence(tmp_path)


def test_manifest_read_retains_eight_megabyte_bound(tmp_path: Path):
    (tmp_path / "publication.json").write_bytes(b" " * 8_000_001)
    with pytest.raises(ValueError, match="manifest exceeds size limit"):
        adapter.load_verified_evidence(tmp_path)
