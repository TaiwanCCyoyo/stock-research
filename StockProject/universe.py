"""Named universe resolution: `@universe-name` -> expanded stock code list.

Universes are plain JSON files under `universes/` (explicit `codes` list or a
classification `rule`). Rule-based universes are resolved against
`stock-data-downloader/data/symbol_meta.sqlite`, read directly the same way
`engine/data_loader.py` reads `corporate_actions.sqlite` -- no import of the
submodule's own tooling.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_core.producer_data import producer_data_root

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSES_DIR = REPO_ROOT / "universes"
DEFAULT_SYMBOL_META_DB = producer_data_root() / "symbol_meta.sqlite"


class UniverseError(Exception):
    """Raised when a `@universe-name` reference cannot be resolved."""


@dataclass(frozen=True)
class ResolvedUniverse:
    name: str
    codes: list[str]


def is_universe_reference(value: str) -> bool:
    return value.startswith("@")


def load_universe_definition(name: str, universes_dir: Path = DEFAULT_UNIVERSES_DIR) -> dict[str, Any]:
    path = universes_dir / f"{name}.json"
    if not path.is_file():
        raise UniverseError(f"Unknown universe: {name!r} (expected {path})")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UniverseError(f"Universe file is not valid JSON: {path}") from exc


def resolve_universe(
    name: str,
    *,
    universes_dir: Path = DEFAULT_UNIVERSES_DIR,
    symbol_meta_db: Path = DEFAULT_SYMBOL_META_DB,
) -> ResolvedUniverse:
    definition = load_universe_definition(name, universes_dir)
    has_codes = "codes" in definition
    has_rule = "rule" in definition
    if has_codes == has_rule:
        raise UniverseError(f"Universe {name!r} must define exactly one of 'codes' or 'rule'")

    if has_codes:
        codes = definition["codes"]
        if not isinstance(codes, list) or not codes:
            raise UniverseError(f"Universe {name!r} 'codes' must be a non-empty list")
        return ResolvedUniverse(name=name, codes=[str(code) for code in codes])

    rule = definition["rule"]
    industry = rule.get("industry") if isinstance(rule, dict) else None
    if not industry:
        raise UniverseError(f"Universe {name!r} 'rule' must specify 'industry'")
    codes = resolve_industry_rule(industry, symbol_meta_db)
    if not codes:
        raise UniverseError(f"Universe {name!r} rule matched no symbols for industry={industry!r}")
    return ResolvedUniverse(name=name, codes=codes)


def resolve_industry_rule(industry: str, symbol_meta_db: Path = DEFAULT_SYMBOL_META_DB) -> list[str]:
    if not symbol_meta_db.is_file():
        raise UniverseError(f"symbol_meta.sqlite not found at {symbol_meta_db}; run stock-data-downloader/scripts/fetch_symbol_meta.py fetch first")
    conn = sqlite3.connect(symbol_meta_db)
    try:
        rows = conn.execute(
            "SELECT code FROM symbol_meta WHERE industry_category = ? ORDER BY code",
            (industry,),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def resolve_codes(
    value: str,
    *,
    universes_dir: Path = DEFAULT_UNIVERSES_DIR,
    symbol_meta_db: Path = DEFAULT_SYMBOL_META_DB,
) -> tuple[list[str], str | None]:
    """Resolve a `--codes` value to `(code_list, universe_name)`.

    A plain comma-separated value returns `(codes, None)`, unaffected by
    universe resolution. An `@universe-name` value resolves to that
    universe's expanded code list and its name, for reproducibility.
    """
    value = value.strip()
    if is_universe_reference(value):
        name = value[1:]
        if not name:
            raise UniverseError("Universe reference must include a name after '@', e.g. @semiconductor")
        resolved = resolve_universe(name, universes_dir=universes_dir, symbol_meta_db=symbol_meta_db)
        return resolved.codes, resolved.name
    codes = [item.strip() for item in value.split(",") if item.strip()]
    return codes, None
