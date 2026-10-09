from __future__ import annotations

import sqlite3
from pathlib import Path

from research_lab.dashboard_core import rankings_with_classification, symbol_classification


def _build_symbol_meta_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE symbol_meta (code TEXT PRIMARY KEY, industry_category TEXT)")
        conn.executemany(
            "INSERT INTO symbol_meta (code, industry_category) VALUES (?, ?)",
            [("2330", "半導體業"), ("0050", None)],
        )
        conn.commit()
    finally:
        conn.close()


def test_symbol_classification_returns_known_and_skips_unknown(tmp_path: Path) -> None:
    db_path = tmp_path / "symbol_meta.sqlite"
    _build_symbol_meta_db(db_path)

    classification = symbol_classification(["2330", "0050", "9999"], db_path=db_path)

    assert classification["2330"] == "半導體業"
    assert classification["0050"] is None
    assert "9999" not in classification


def test_symbol_classification_returns_empty_when_db_missing(tmp_path: Path) -> None:
    classification = symbol_classification(["2330"], db_path=tmp_path / "does-not-exist.sqlite")

    assert classification == {}


def test_rankings_with_classification_attaches_industry_category(tmp_path: Path) -> None:
    db_path = tmp_path / "symbol_meta.sqlite"
    _build_symbol_meta_db(db_path)
    rankings = {"stocks": [{"code": "2330", "total_pnl": 100.0}, {"code": "9999", "total_pnl": -50.0}]}

    enriched = rankings_with_classification(rankings, db_path=db_path)

    assert enriched["stocks"][0]["industry_category"] == "半導體業"
    assert enriched["stocks"][1]["industry_category"] is None
    assert enriched["stocks"][0]["total_pnl"] == 100.0
