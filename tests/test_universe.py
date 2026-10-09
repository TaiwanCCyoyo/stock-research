from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from StockProject.universe import UniverseError, resolve_codes, resolve_universe


def _write_universe(universes_dir: Path, name: str, payload: dict) -> None:
    import json

    universes_dir.mkdir(parents=True, exist_ok=True)
    (universes_dir / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def _build_symbol_meta_db(db_path: Path, rows: list[tuple[str, str]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE symbol_meta (code TEXT PRIMARY KEY, industry_category TEXT)")
        conn.executemany("INSERT INTO symbol_meta (code, industry_category) VALUES (?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def test_resolve_universe_with_explicit_codes(tmp_path: Path) -> None:
    _write_universe(tmp_path, "core", {"name": "core", "codes": ["2330", "2454"]})

    resolved = resolve_universe("core", universes_dir=tmp_path, symbol_meta_db=tmp_path / "unused.sqlite")

    assert resolved.codes == ["2330", "2454"]


def test_resolve_universe_with_rule_queries_symbol_meta(tmp_path: Path) -> None:
    _write_universe(tmp_path, "semis", {"name": "semis", "rule": {"industry": "半導體業"}})
    db_path = tmp_path / "symbol_meta.sqlite"
    _build_symbol_meta_db(
        db_path,
        [("2330", "半導體業"), ("2454", "半導體業"), ("1101", "水泥工業")],
    )

    resolved = resolve_universe("semis", universes_dir=tmp_path, symbol_meta_db=db_path)

    assert resolved.codes == ["2330", "2454"]


def test_resolve_universe_unknown_name_fails(tmp_path: Path) -> None:
    with pytest.raises(UniverseError):
        resolve_universe("does-not-exist", universes_dir=tmp_path, symbol_meta_db=tmp_path / "unused.sqlite")


def test_resolve_universe_requires_exactly_one_of_codes_or_rule(tmp_path: Path) -> None:
    _write_universe(tmp_path, "ambiguous", {"name": "ambiguous", "codes": ["2330"], "rule": {"industry": "x"}})

    with pytest.raises(UniverseError):
        resolve_universe("ambiguous", universes_dir=tmp_path, symbol_meta_db=tmp_path / "unused.sqlite")


def test_resolve_universe_rule_with_no_matches_fails(tmp_path: Path) -> None:
    _write_universe(tmp_path, "empty", {"name": "empty", "rule": {"industry": "不存在業"}})
    db_path = tmp_path / "symbol_meta.sqlite"
    _build_symbol_meta_db(db_path, [("2330", "半導體業")])

    with pytest.raises(UniverseError):
        resolve_universe("empty", universes_dir=tmp_path, symbol_meta_db=db_path)


def test_resolve_codes_with_plain_comma_list_is_unaffected(tmp_path: Path) -> None:
    codes, universe_name = resolve_codes("2330, 2454 ,0050", universes_dir=tmp_path, symbol_meta_db=tmp_path / "unused.sqlite")

    assert codes == ["2330", "2454", "0050"]
    assert universe_name is None


def test_resolve_codes_with_universe_reference(tmp_path: Path) -> None:
    _write_universe(tmp_path, "core", {"name": "core", "codes": ["2330", "2454"]})

    codes, universe_name = resolve_codes("@core", universes_dir=tmp_path, symbol_meta_db=tmp_path / "unused.sqlite")

    assert codes == ["2330", "2454"]
    assert universe_name == "core"


def test_resolve_codes_with_unknown_universe_reference_fails(tmp_path: Path) -> None:
    with pytest.raises(UniverseError):
        resolve_codes("@nope", universes_dir=tmp_path, symbol_meta_db=tmp_path / "unused.sqlite")
