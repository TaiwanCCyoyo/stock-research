"""Regression coverage for the source-bound market presentation export."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pytest

from scripts.export_market_atlas import AtlasExportError, build_market_atlas


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(catalog: Path, manifest: dict[str, object]) -> None:
    (catalog / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    canonical = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (catalog / "completion-receipt.json").write_text(json.dumps({"manifest_canonical_sha256": canonical}), encoding="utf-8")


def _catalog(
    root: Path,
    source: Path,
    findings: list[dict[str, object]] | None = None,
    *,
    name_fields: dict[str, object] | None = None,
    code_fields: dict[str, object] | None = None,
    security_id_fields: dict[str, object] | None = None,
    group_ids_fields: dict[str, object] | None = None,
    group_rows: list[dict[str, object]] | None = None,
) -> Path:
    catalog = root / "catalog"
    chunks = catalog / "chunks"
    chunks.mkdir(parents=True)
    groups = list(group_rows) if group_rows is not None else [{"group_id": "research", "label": "Research", "parent_id": None}]
    if not any(group.get("group_id") == "official:1000" for group in groups):
        groups.append({"group_id": "official:1000", "label": "Official", "parent_id": None})
    securities: list[dict[str, object]] = [
        {
            "security_id": "TW:1111",
            "code": "1111",
            "name": "One",
            "group_ids": ["research"],
            "coverage_status": "official_only",
            "price_coverage_status": "observed",
        },
        {
            "security_id": "TW:2222",
            "code": "2222",
            "name": "Two",
            "group_ids": ["official:1000"],
            "official_industry": "Official",
            "coverage_status": "official_only",
            "price_coverage_status": "observed",
        },
    ]
    if name_fields is not None:
        securities[0].pop("name")
        securities[0].update(name_fields)
    if code_fields is not None:
        securities[0].pop("code")
        securities[0].update(code_fields)
    if security_id_fields is not None:
        securities[0].pop("security_id")
        securities[0].update(security_id_fields)
    if group_ids_fields is not None:
        securities[0].pop("group_ids")
        securities[0].update(group_ids_fields)
    if findings is None:
        findings = [{"code": "1111", "date": "2019-01-03", "reason": "duplicate_date"}]
    chunk_entries = []
    for table, rows in (("groups", groups), ("securities", securities), ("quality_findings", findings)):
        path = chunks / f"{table}-0001.json.gz"
        with path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                zipped.write(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode())
        chunk_entries.append({
            "table": table,
            "path": str(path.relative_to(catalog)).replace("\\", "/"),
            "rows": len(rows),
            "sha256": _sha(path),
            "compression": "gzip",
        })
    manifest: dict[str, object] = {
        "schema_version": "sector-wave-catalog.v1",
        "classification_fetched_at": "2026-10-01T00:00:00Z",
        "counts": {"groups": len(groups), "securities": len(securities), "quality_findings": len(findings)},
        "chunks": chunk_entries,
        "input_identities_sha256": {"price": _sha(source / "price_daily.parquet"), "actions": _sha(source / "corporate_actions.sqlite")},
    }
    _write_manifest(catalog, manifest)
    return catalog


def _source(
    root: Path,
    prices: list[dict[str, object]] | None = None,
    actions: list[tuple[str, str, str, float]] | None = None,
) -> Path:
    source = root / "source"
    source.mkdir()
    frame = pd.DataFrame(
        prices
        or [
            {"Code": "1111", "Date": "2019-01-02", "Close": 100.0, "Source": "official"},
            {"Code": "1111", "Date": "2019-01-03", "Close": 50.0, "Source": "official"},
            {"Code": "2222", "Date": "2019-01-04", "Close": 20.0, "Source": "official"},
            {"Code": "3333", "Date": "2019-01-05", "Close": 10.0, "Source": "shioaji"},
        ]
    )
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame.to_parquet(source / "price_daily.parquet")
    with sqlite3.connect(source / "corporate_actions.sqlite") as connection:
        connection.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
        connection.executemany("INSERT INTO corporate_actions VALUES (?, ?, ?, ?)", actions or [("1111", "2019-01-03", "ETF_SPLIT", 0.5)])
    connection.close()
    return source


def _test_tempdir() -> TemporaryDirectory[str]:
    scratch = Path(__file__).resolve().parents[2] / ".tmp"
    scratch.mkdir(exist_ok=True)
    return TemporaryDirectory(prefix="test-export-market-atlas-", dir=scratch)


def test_export_aligns_official_calendar_missing_prices_and_split_adjustment() -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source)
        output = root / "market-atlas.json"

        payload = build_market_atlas(catalog, source, output)

        assert payload["schema"] == "market-atlas.v1"
        assert payload["dates"] == ["2019-01-02", "2019-01-03", "2019-01-04"]
        assert payload["groups"] == [{"id": "research", "label": "Research"}, {"id": "official-industry:Official", "label": "Official"}]
        one, two = payload["stocks"]
        assert one["raw"] == [100.0, 50.0, None]
        assert one["adjusted"] == [50.0, 50.0, None]
        assert one["quality"] == []
        assert one["qualityFindings"] == [{"date": "2019-01-03", "kind": "duplicate_date"}]
        assert one["coverage"] == {"catalogStatus": "official_only", "priceStatus": "observed", "reason": None}
        assert two["raw"] == [None, None, 20.0]
        assert two["adjusted"] == [None, None, 20.0]
        assert all(len(stock["raw"]) == len(payload["dates"]) == len(stock["adjusted"]) for stock in payload["stocks"])
        assert payload["provenance"]["sourceQuotePolicy"] == "official daily quotes only; calendar is their date union"
        assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_export_uses_only_permanent_factors_and_keeps_first_duplicate_and_invalid_close_null() -> None:
    prices = [
        {"Code": "1111", "Date": "2019-01-02", "Close": 100.0, "Source": "official"},
        {"Code": "1111", "Date": "2019-01-03", "Close": 50.0, "Source": "official"},
        {"Code": "1111", "Date": "2019-01-04", "Close": 0.0, "Source": "official"},
        {"Code": "1111", "Date": "2019-01-04", "Close": 40.0, "Source": "official"},
        {"Code": "2222", "Date": "2019-01-02", "Close": 100.0, "Source": "official"},
        {"Code": "2222", "Date": "2019-01-03", "Close": 95.0, "Source": "official"},
    ]
    actions = [
        ("1111", "2019-01-03", "ETF_SPLIT", 0.5),
        ("1111", "2019-01-04", "CAPITAL_REDUCTION", 0.8),
        ("2222", "2019-01-03", "CASH_DIVIDEND", 0.95),
    ]
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root, prices, actions)
        payload = build_market_atlas(_catalog(root, source), source, root / "market-atlas.json")

        one, two = payload["stocks"]
        assert one["raw"] == [100.0, 50.0, None]
        assert one["adjusted"] == [40.0, 40.0, None]
        assert two["raw"] == [100.0, 95.0, None]
        assert two["adjusted"] == [100.0, 95.0, None]


def test_export_rejects_source_drift_before_writing() -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source)
        (source / "price_daily.parquet").write_bytes(b"changed")

        with pytest.raises(AtlasExportError, match="price source hash differs"):
            build_market_atlas(catalog, source, root / "market-atlas.json")


@pytest.mark.parametrize("code_fields", [{}, {"code": None}, {"code": 1111}, {"code": False}, {"code": ""}, {"code": " \t"}, {"code": "\ufeff"}])
def test_export_rejects_invalid_security_code_before_loading_source(code_fields: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, code_fields=code_fields)
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._source_identities", lambda *args: pytest.fail("source loaded before code validation"))

        with pytest.raises(AtlasExportError, match="security code must be a nonempty string"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


def test_export_rejects_duplicate_security_codes_before_loading_source(monkeypatch: pytest.MonkeyPatch) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, code_fields={"code": "2222"})
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._source_identities", lambda *args: pytest.fail("source loaded before code validation"))

        with pytest.raises(AtlasExportError, match="duplicate security code: 2222"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize(
    ("security_id_fields", "message"),
    [
        ({}, "security_id must be a nonempty string"),
        ({"security_id": None}, "security_id must be a nonempty string"),
        ({"security_id": 1111}, "security_id must be a nonempty string"),
        ({"security_id": False}, "security_id must be a nonempty string"),
        ({"security_id": ""}, "security_id must be a nonempty string"),
        ({"security_id": " \t"}, "security_id must be a nonempty string"),
        ({"security_id": "\ufeff"}, "security_id must be a nonempty string"),
        ({"security_id": "\u00a0\ufeff\u2028\u2029"}, "security_id must be a nonempty string"),
        ({"security_id": "TW:2222"}, "duplicate security_id: TW:2222"),
    ],
)
def test_export_rejects_invalid_or_shared_security_ids_before_mapping_or_source_loading(
    security_id_fields: dict[str, object], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        # The fixture keeps distinct codes and distinct group memberships, even for a shared ID.
        catalog = _catalog(root, source, security_id_fields=security_id_fields)
        output = root / "export" / "market-atlas.json"
        for function in ("_quality_findings_by_security", "_group_projection", "_source_identities"):
            monkeypatch.setattr(f"scripts.export_market_atlas.{function}", lambda *args: pytest.fail("mapping or source loaded before security_id validation"))

        with pytest.raises(AtlasExportError, match=message):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("code", ["0011", "\ufeff1111\ufeff", " 1111 ", "\u001c"])
def test_export_preserves_nonblank_security_codes(code: str) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, findings=[{"security_id": "TW:1111", "date": "2019-01-03", "reason": "duplicate_date"}], code_fields={"code": code})
        output = root / "market-atlas.json"

        payload = build_market_atlas(catalog, source, output)

        assert payload["stocks"][0]["code"] == code
        assert json.loads(output.read_text(encoding="utf-8"))["stocks"][0]["code"] == code


@pytest.mark.parametrize(
    ("day", "quote_source"),
    [("2019-01-02", "shioaji"), ("2019-01-01", "official"), ("2026-08-15", "official")],
)
def test_export_rejects_empty_official_calendar_in_fixed_window(day: str, quote_source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root, prices=[{"Code": "1111", "Date": day, "Close": 100.0, "Source": quote_source}])
        catalog = _catalog(root, source)
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._load_actions", lambda *args: pytest.fail("actions loaded after empty calendar"))

        with pytest.raises(AtlasExportError, match="official price calendar is empty in 2019-01-02 through 2026-08-14"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("day", ["2019-02-29", "20190103", "2019-W01-4", "unknown", "", 20190103])
def test_export_rejects_invalid_dated_findings_before_loading_source(day: object, monkeypatch: pytest.MonkeyPatch) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, [{"code": "1111", "date": day, "reason": "duplicate_date"}])
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._source_identities", lambda *args: pytest.fail("source loaded before validation"))

        with pytest.raises(AtlasExportError, match="canonical Gregorian YYYY-MM-DD"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("reason", ["", " \t", "\ufeff", "\u00a0\ufeff\u2028\u2029", None, 123])
def test_export_rejects_empty_or_invalid_dated_reason(reason: object) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, [{"code": "1111", "date": "2019-01-03", "reason": reason}])
        output = root / "market-atlas.json"

        with pytest.raises(AtlasExportError, match="nonempty reason"):
            build_market_atlas(catalog, source, output)

        assert not output.exists()


@pytest.mark.parametrize("reason", ["duplicate_date", "\u001c", "\ufeffreason\ufeff"])
def test_export_preserves_canonical_quality_and_ignores_undated_coverage_findings(reason: str) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        findings: list[dict[str, object]] = [
            {"code": "1111", "date": "2019-01-03", "reason": reason},
            {"security_id": "TW:1111", "date": "2024-02-29", "reason": "outside_calendar_warning"},
            {"code": "2222", "reason": "coverage_missing"},
            {"code": "2222", "date": None, "reason": "coverage_missing"},
        ]
        catalog = _catalog(root, source, findings)

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["stocks"][0]["qualityFindings"] == [
            {"date": "2019-01-03", "kind": reason},
            {"date": "2024-02-29", "kind": "outside_calendar_warning"},
        ]
        assert payload["stocks"][1]["qualityFindings"] == []


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"security_id": None, "code": None},
        {"security_id": "TW:unknown"},
        {"code": "unknown"},
        {"security_id": "TW:1111", "code": "2222"},
        {"security_id": "TW:unknown", "code": "1111"},
        {"security_id": "TW:1111", "code": "unknown"},
        {"security_id": 1111, "code": "1111"},
        {"security_id": False, "code": "1111"},
        {"security_id": "", "code": "1111"},
        {"security_id": "\ufeff", "code": "1111"},
        {"code": 1111, "security_id": "TW:1111"},
        {"code": False, "security_id": "TW:1111"},
        {"code": "", "security_id": "TW:1111"},
        {"code": " \t", "security_id": "TW:1111"},
        {"code": "\ufeff", "security_id": "TW:1111"},
    ],
)
def test_export_rejects_unresolved_or_conflicting_dated_finding_identity_before_source_loading(
    identity: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        finding = {**identity, "date": "2019-01-03", "reason": "duplicate_date"}
        catalog = _catalog(root, source, findings=[finding])
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._source_identities", lambda *args: pytest.fail("source loaded before finding identity validation"))

        with pytest.raises(AtlasExportError, match="dated quality finding"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize(
    "identity",
    [
        {"security_id": "TW:1111"},
        {"code": "1111"},
        {"security_id": "TW:1111", "code": "1111"},
        {"security_id": None, "code": "1111"},
        {"security_id": "TW:1111", "code": None},
    ],
)
def test_export_preserves_sorted_evidence_for_valid_dated_finding_identity(identity: dict[str, object]) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        findings = [
            {**identity, "date": "2019-01-03", "reason": "z_reason"},
            {**identity, "date": "2019-01-02", "reason": "earlier"},
            {**identity, "date": "2019-01-03", "reason": "a_reason"},
            {"code": "unknown", "security_id": 123, "reason": "undated_coverage"},
        ]
        catalog = _catalog(root, source, findings=findings)

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["stocks"][0]["qualityFindings"] == [
            {"date": "2019-01-02", "kind": "earlier"},
            {"date": "2019-01-03", "kind": "a_reason"},
            {"date": "2019-01-03", "kind": "z_reason"},
        ]
        assert payload["stocks"][1]["qualityFindings"] == []


@pytest.mark.parametrize("industry", [None, "", " \t", "\ufeff", "\u00a0\ufeff\u2028\u2029"])
def test_export_uses_unclassified_fallback_for_browser_blank_official_industry(industry: object) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, group_ids_fields={"group_ids": [], "official_industry": industry})

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["stocks"][0]["groupIds"] == ["official-industry:unknown"]
        assert {"id": "official-industry:unknown", "label": "分類待補"} in payload["groups"]


@pytest.mark.parametrize(
    "timestamp",
    [
        "missing",
        None,
        "unknown",
        "",
        "2026-10-01",
        "2026-10-01Tgarbage",
        "2026-10-01T25:00:00Z",
        "2026-02-30T00:00:00Z",
        "20261001T00:00:00Z",
        "2026-W40-4T00:00:00Z",
        "2026-10-01T00:00:00",
        "2026-10-01T00:00:00+08:99",
        "2026-10-01T00:00:00-08:60",
        123,
    ],
)
def test_export_rejects_invalid_classification_before_loading_source(timestamp: object, monkeypatch: pytest.MonkeyPatch) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source)
        manifest = json.loads((catalog / "manifest.json").read_text(encoding="utf-8"))
        if timestamp == "missing":
            manifest.pop("classification_fetched_at")
        else:
            manifest["classification_fetched_at"] = timestamp
        _write_manifest(catalog, manifest)
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._source_identities", lambda *args: pytest.fail("source loaded before validation"))

        with pytest.raises(AtlasExportError, match="classification_fetched_at requires a complete ISO timestamp"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("timestamp", ["2026-10-01T00:00:00Z", "2026-10-01T00:30:00.123456+08:00", "2026-10-01T23:30:00.5-07:00"])
def test_export_preserves_classification_local_date(timestamp: str) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source)
        manifest = json.loads((catalog / "manifest.json").read_text(encoding="utf-8"))
        manifest["classification_fetched_at"] = timestamp
        _write_manifest(catalog, manifest)

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["classificationAsOf"] == "2026-10-01"


@pytest.mark.parametrize(
    ("name_fields", "expected_name"),
    [
        ({}, "1111"),
        ({"name": None}, "1111"),
        ({"name": ""}, "1111"),
        ({"name": " \t\n"}, "1111"),
        ({"name": "\ufeff"}, "1111"),
        (
            {
                "name": "\u0009\u000b\u000c\u0020\u00a0\u1680"
                "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
                "\u202f\u205f\u3000\ufeff\u000a\u000d\u2028\u2029"
            },
            "1111",
        ),
        ({"name": "One"}, "One"),
        ({"name": "  One  "}, "  One  "),
        ({"name": "\ufeffOne\ufeff"}, "\ufeffOne\ufeff"),
        ({"name": "\u001c"}, "\u001c"),
    ],
)
def test_export_uses_code_for_missing_or_blank_name_and_preserves_nonempty_name(name_fields: dict[str, object], expected_name: str) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, name_fields=name_fields)
        output = root / "market-atlas.json"

        payload = build_market_atlas(catalog, source, output)

        assert payload["stocks"][0]["name"] == expected_name
        assert json.loads(output.read_text(encoding="utf-8")) == payload


@pytest.mark.parametrize("name", [123, False, ["One"], {"label": "One"}])
def test_export_rejects_invalid_name_type_without_coercion(name: object) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, name_fields={"name": name})
        output = root / "market-atlas.json"

        with pytest.raises(AtlasExportError, match="security name must be a string or null"):
            build_market_atlas(catalog, source, output)

        assert not output.exists()


@pytest.mark.parametrize("field", ["group_id", "label"])
@pytest.mark.parametrize("value", ["", " \t", "\ufeff", "\u00a0\ufeff\u2028\u2029", 123, False, None])
def test_export_rejects_invalid_root_group_strings(field: str, value: object) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        group: dict[str, object] = {"group_id": "research", "label": "Research", "parent_id": None}
        group[field] = value
        catalog = _catalog(root, source, group_rows=[group])
        output = root / "export" / "market-atlas.json"

        message = "catalog group_id must be a nonempty string" if field == "group_id" else "root group label must be a nonempty string"
        with pytest.raises(AtlasExportError, match=message):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("value", ["\ufeffResearch\ufeff", "\u001c", "  Research  "])
def test_export_preserves_nonblank_root_group_strings(value: str) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, group_rows=[{"group_id": value, "label": value, "parent_id": None}], group_ids_fields={"group_ids": [value]})

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["groups"][0] == {"id": value, "label": value}


@pytest.mark.parametrize("duplicate_id", ["research", "official-industry:Official"])
def test_export_rejects_duplicate_root_or_fallback_group_ids(duplicate_id: str) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        groups: list[dict[str, object]] = [
            {"group_id": "research", "label": "Research", "parent_id": None},
            {"group_id": duplicate_id, "label": "Duplicate", "parent_id": None},
        ]
        catalog = _catalog(root, source, group_rows=groups)
        output = root / "export" / "market-atlas.json"

        message = "duplicate catalog group_id" if duplicate_id == "research" else "duplicate display group id"
        with pytest.raises(AtlasExportError, match=message):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("collision", ["root-child", "child-child"])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_export_rejects_source_group_id_collisions_before_parent_mapping(collision: str, reverse_order: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        groups: list[dict[str, object]] = [
            {"group_id": "research", "label": "Research", "parent_id": None},
            {"group_id": "other", "label": "Other", "parent_id": None},
        ]
        if collision == "root-child":
            groups.append({"group_id": "research", "label": "Child", "parent_id": "other"})
        else:
            groups.extend([
                {"group_id": "shared-child", "label": "First child", "parent_id": "research"},
                {"group_id": "shared-child", "label": "Second child", "parent_id": "other"},
            ])
        if reverse_order:
            groups.reverse()
        catalog = _catalog(root, source, group_rows=groups)
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._load_prices", lambda *args: pytest.fail("prices loaded before group validation"))

        with pytest.raises(AtlasExportError, match="duplicate catalog group_id"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize(
    "id_fields", [{}, {"group_id": None}, {"group_id": 123}, {"group_id": False}, {"group_id": ""}, {"group_id": " \t"}, {"group_id": "\ufeff"}]
)
def test_export_rejects_invalid_child_group_ids_before_parent_mapping(id_fields: dict[str, object]) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        child: dict[str, object] = {"label": "Child", "parent_id": "research"}
        child.update(id_fields)
        groups: list[dict[str, object]] = [{"group_id": "research", "label": "Research", "parent_id": None}, child]
        catalog = _catalog(root, source, group_rows=groups)
        output = root / "export" / "market-atlas.json"

        with pytest.raises(AtlasExportError, match="catalog group_id must be a nonempty string"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("reference", ["parent_id", "group_ids"])
def test_export_rejects_numeric_group_references_matching_string_ids(reference: str) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        groups: list[dict[str, object]] = [
            {"group_id": "123", "label": "Numeric-looking root", "parent_id": None},
            {"group_id": "child", "label": "Child", "parent_id": 123 if reference == "parent_id" else "123"},
        ]
        group_ids = ["child"] if reference == "parent_id" else [123]
        catalog = _catalog(root, source, group_rows=groups, group_ids_fields={"group_ids": group_ids})
        output = root / "export" / "market-atlas.json"
        message = (
            "catalog parent_id must be a nonempty string or null" if reference == "parent_id" else "security group_ids must be an array of nonempty strings"
        )

        with pytest.raises(AtlasExportError, match=message):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("parent_id", [False, "", " \t", "\ufeff", ["research"]])
def test_export_rejects_invalid_group_parent_reference(parent_id: object) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        groups = [{"group_id": "research", "label": "Research", "parent_id": parent_id}]
        catalog = _catalog(root, source, group_rows=groups)
        output = root / "export" / "market-atlas.json"

        with pytest.raises(AtlasExportError, match="catalog parent_id must be a nonempty string or null"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("group_ids", [None, False, "research", {"id": "research"}, [None], [False], [""], [" \t"], ["\ufeff"]])
def test_export_rejects_invalid_security_group_references(group_ids: object) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, group_ids_fields={"group_ids": group_ids})
        output = root / "export" / "market-atlas.json"

        with pytest.raises(AtlasExportError, match="security group_ids must be an array of nonempty strings"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("group_ids_fields", [{}, {"group_ids": []}])
def test_export_preserves_missing_and_empty_group_fallback(group_ids_fields: dict[str, object]) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        groups: list[dict[str, object]] = [
            {"group_id": "research", "label": "Research", "parent_id": None},
        ]
        catalog = _catalog(root, source, group_rows=groups, group_ids_fields=group_ids_fields)

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["stocks"][0]["groupIds"] == ["official-industry:unknown"]
        assert {"id": "official-industry:unknown", "label": "分類待補"} in payload["groups"]


@pytest.mark.parametrize("referenced", [False, True])
def test_export_rejects_missing_parent_even_for_unreferenced_child(referenced: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        groups: list[dict[str, object]] = [
            {"group_id": "research", "label": "Research", "parent_id": None},
            {"group_id": "child", "label": "Child", "parent_id": "missing-parent"},
        ]
        catalog = _catalog(root, source, group_rows=groups, group_ids_fields={"group_ids": ["child"] if referenced else ["research"]})
        output = root / "export" / "market-atlas.json"
        monkeypatch.setattr("scripts.export_market_atlas._load_prices", lambda *args: pytest.fail("prices loaded before parent validation"))

        with pytest.raises(AtlasExportError, match="unresolved catalog parent_id: missing-parent"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


@pytest.mark.parametrize("group_ids", [["unknown"], ["research", "unknown"]])
def test_export_rejects_unresolved_security_group_reference(group_ids: list[str]) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source, group_ids_fields={"group_ids": group_ids})
        output = root / "export" / "market-atlas.json"

        with pytest.raises(AtlasExportError, match="unresolved security group_id: unknown"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()


def test_export_resolves_valid_child_to_root_and_preserves_official_fallback() -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        groups: list[dict[str, object]] = [
            {"group_id": "child", "label": "Child", "parent_id": "research"},
            {"group_id": "research", "label": "Research", "parent_id": None},
        ]
        catalog = _catalog(root, source, group_rows=groups, group_ids_fields={"group_ids": ["child"]})

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["stocks"][0]["groupIds"] == ["research"]
        assert payload["stocks"][1]["groupIds"] == ["official-industry:Official"]


@pytest.mark.parametrize("parent_fields", [{}, {"parent_id": None}])
def test_export_preserves_missing_or_null_parent_as_root(parent_fields: dict[str, object]) -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        group: dict[str, object] = {"group_id": "research", "label": "Research"}
        group.update(parent_fields)
        catalog = _catalog(root, source, group_rows=[group])

        payload = build_market_atlas(catalog, source, root / "market-atlas.json")

        assert payload["stocks"][0]["groupIds"] == ["research"]


def test_export_rejects_committed_wal_change_even_when_main_file_hash_matches() -> None:
    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        actions_path = source / "corporate_actions.sqlite"
        connection = sqlite3.connect(actions_path)
        try:
            assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            catalog = _catalog(root, source)
            pinned_hash = _sha(actions_path)
            connection.execute("UPDATE corporate_actions SET price_factor = 0.25 WHERE code = '1111'")
            connection.commit()
            wal_path = source / "corporate_actions.sqlite-wal"
            wal_before = wal_path.read_bytes()
            assert wal_before
            assert _sha(actions_path) == pinned_hash
            output = root / "export" / "market-atlas.json"

            with pytest.raises(AtlasExportError, match="WAL sidecar.*cannot checkpoint or modify source data"):
                build_market_atlas(catalog, source, output)

            assert not output.parent.exists()
            assert _sha(actions_path) == pinned_hash
            assert wal_path.read_bytes() == wal_before
        finally:
            connection.close()


@pytest.mark.parametrize("boundary", ["hash", "read"])
def test_export_rejects_wal_created_during_source_hash_or_read(boundary: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import export_market_atlas

    with _test_tempdir() as temporary:
        root = Path(temporary)
        source = _source(root)
        catalog = _catalog(root, source)
        wal_path = source / "corporate_actions.sqlite-wal"
        output = root / "export" / "market-atlas.json"
        if boundary == "hash":
            original_sha256 = export_market_atlas._sha256

            def create_wal_after_hash(path: Path) -> str:
                digest = original_sha256(path)
                if path == source / "corporate_actions.sqlite":
                    wal_path.touch()
                return digest

            monkeypatch.setattr(export_market_atlas, "_sha256", create_wal_after_hash)
        else:
            original_read_sql = pd.read_sql_query

            def create_wal_after_read(sql: str, connection: sqlite3.Connection, *, params: list[str]) -> pd.DataFrame:
                frame = original_read_sql(sql, connection, params=params)
                wal_path.touch()
                return frame

            monkeypatch.setattr(pd, "read_sql_query", create_wal_after_read)

        with pytest.raises(AtlasExportError, match="WAL sidecar"):
            build_market_atlas(catalog, source, output)

        assert not output.parent.exists()
