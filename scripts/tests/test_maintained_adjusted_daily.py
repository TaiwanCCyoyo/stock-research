from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from research_core import live_producer, maintained_adjusted_daily, run_receipt
from research_core.artifact_store import read_json
from research_core.shared_data import ENV_KEY, SharedRootError, shared_data_root


def _git(*args: str, cwd: Path) -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args], cwd=cwd, env=environment, check=True, capture_output=True)


@pytest.fixture()
def checkouts(tmp_path: Path) -> tuple[Path, Path]:
    primary = tmp_path / "primary checkout"
    primary.mkdir()
    _git("init", "-q", "-b", "main", cwd=primary)
    (primary / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=primary)
    _git("commit", "-q", "-m", "init", cwd=primary)
    worktree = primary / ".worktrees" / "linked worktree"
    _git("worktree", "add", "-q", "-b", "task", str(worktree), cwd=primary)
    return primary, worktree


def test_shared_root_resolves_from_the_primary_env_file_for_a_worktree(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    shared = tmp_path / "Stock Data" / "stock-research"
    shared.mkdir(parents=True)
    (primary / ".env.local").write_text(f"STOCK_PRODUCER_DATA_ROOT=D:/x\n{ENV_KEY}={shared}\n", encoding="utf-8")

    assert shared_data_root(environ={}, repo_root=worktree) == shared.resolve()
    other = tmp_path / "env wins"
    other.mkdir()
    assert shared_data_root(environ={ENV_KEY: str(other)}, repo_root=worktree) == other.resolve()


@pytest.mark.parametrize("inside", ["research_cache", ".worktrees/linked worktree/research_data"])
def test_shared_root_inside_the_checkout_or_a_worktree_is_refused(checkouts: tuple[Path, Path], inside: str) -> None:
    primary, worktree = checkouts
    candidate = primary / inside
    candidate.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SharedRootError, match="outside every checkout and worktree"):
        shared_data_root(environ={ENV_KEY: str(candidate)}, repo_root=worktree)


def test_shared_root_inside_a_sibling_worktree_is_refused(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    sibling = tmp_path / "sibling worktree"
    _git("worktree", "add", "-q", "-b", "sibling", str(sibling), cwd=primary)
    candidate = sibling / "shared"
    candidate.mkdir()

    with pytest.raises(SharedRootError, match="outside every checkout and worktree"):
        shared_data_root(environ={ENV_KEY: str(candidate)}, repo_root=worktree)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction")
def test_shared_root_through_a_junction_is_refused(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    outside = tmp_path / "real outside"
    outside.mkdir()
    junction = primary / "linked shared"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], check=True, capture_output=True)
    try:
        with pytest.raises(SharedRootError, match="link, junction or hardlink"):
            shared_data_root(environ={ENV_KEY: str(junction)}, repo_root=worktree)
    finally:
        os.rmdir(junction)
    assert outside.is_dir()


def test_shared_root_has_no_fallback(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = checkouts
    with pytest.raises(SharedRootError, match="not configured"):
        shared_data_root(environ={}, repo_root=worktree)
    with pytest.raises(SharedRootError, match="unavailable"):
        shared_data_root(environ={ENV_KEY: str(tmp_path / "missing")}, repo_root=worktree)
    with pytest.raises(SharedRootError, match="absolute"):
        shared_data_root(environ={ENV_KEY: "relative/dir"}, repo_root=worktree)


def _producer(root: Path, *, closes_2330: list[float]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"])
    rows = []
    for day, close in zip(dates, closes_2330, strict=True):
        rows.append({"Code": "2330", "Date": day, "Open": close, "High": close, "Low": close, "Close": close, "Volume": 1000.0, "Source": "official"})
    for day in dates[1:]:
        source = "shioaji" if day == dates[-1] else "official"
        rows.append({"Code": "6488", "Date": day, "Open": 50.0, "High": 51.0, "Low": 49.0, "Close": 50.0, "Volume": 10.0, "Source": source})
    pd.DataFrame(rows).to_parquet(root / "price_daily.parquet", index=False)
    database = root / "corporate_actions.sqlite"
    database.unlink(missing_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
        connection.executemany(
            "INSERT INTO corporate_actions VALUES (?, ?, ?, ?)",
            [("2330", "2026-10-14", "CASH_DIVIDEND", 0.95), ("2330", "2026-12-01", "CASH_DIVIDEND", 0.9)],
        )
    connection.close()
    return root


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    producer = _producer(tmp_path / "producer data", closes_2330=[100.0, 100.0, 95.0, 96.0])
    shared = tmp_path / "shared root"
    shared.mkdir()
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(producer))
    monkeypatch.setenv(ENV_KEY, str(shared))
    monkeypatch.setattr(run_receipt, "assert_producer_idle", lambda now=None: None)
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: [])
    return producer, shared


def test_update_publishes_a_readable_generation_and_flips_current(environment: tuple[Path, Path]) -> None:
    producer, shared = environment

    first = maintained_adjusted_daily.update(producer_root=producer)
    frame, record = maintained_adjusted_daily.read_adjusted_daily("reference_factor_adjusted", codes=["2330"])

    assert record["generation"] == first["generation"] and record["asof"] == "2026-10-15"
    assert frame["Code"].unique().tolist() == ["2330"]
    assert frame["Close"].round(4).tolist() == [95.0, 95.0, 95.0, 96.0]
    assert frame["RawClose"].tolist() == [100.0, 100.0, 95.0, 96.0]
    raw, _ = maintained_adjusted_daily.read_adjusted_daily("raw", codes=["6488"])
    assert raw["Date"].min() == pd.Timestamp("2026-10-13"), "rows start at the symbol's first quote"
    assert raw["Date"].max() == pd.Timestamp("2026-10-14"), "the shioaji row is excluded before calculation"
    status = maintained_adjusted_daily.current_generation()
    assert status["actions"]["after_asof_excluded"] == 1
    assert status["input_fingerprint"]["inputs"]["price_daily"]["live_producer"] is True
    assert status["previous_generation"] is None
    assert status["source_policy"] == {"kept": "official", "excluded_rows": 1, "excluded_codes": 1, "codes_without_official_rows": []}


def test_failed_update_leaves_current_untouched_and_retention_keeps_two(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = environment
    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    generations = []
    for _ in range(3):
        generations.append(maintained_adjusted_daily.update(producer_root=producer)["generation"])
        monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(len(generations)))
    assert sorted(path.name for path in (family / "generations").iterdir()) == sorted(generations[1:])
    assert read_json(family / "current.json")["generation"] == generations[2]

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("compute failed")

    monkeypatch.setattr(maintained_adjusted_daily, "compute", boom)
    with pytest.raises(RuntimeError, match="compute failed"):
        maintained_adjusted_daily.update(producer_root=producer)

    assert read_json(family / "current.json")["generation"] == generations[2]
    assert sorted(path.name for path in (family / "generations").iterdir()) == sorted(generations[1:])
    assert not (family / ".writer.lock").exists()
    frame, record = maintained_adjusted_daily.read_adjusted_daily("raw")
    assert record["generation"] == generations[2] and len(frame) == 6


def test_a_prune_failure_does_not_fail_a_published_update(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = environment
    first = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(1))
    second = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(2))

    def locked(path: Path) -> None:
        raise PermissionError(f"in use: {path}")

    monkeypatch.setattr(maintained_adjusted_daily.shutil, "rmtree", locked)
    third = maintained_adjusted_daily.update(producer_root=producer)

    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    assert third["pruned"] == [] and read_json(family / "current.json")["generation"] == third["generation"]
    assert {first, second} <= {path.name for path in (family / "generations").iterdir()}


def test_a_replaced_parquet_is_refused_before_it_is_read(environment: tuple[Path, Path]) -> None:
    producer, _ = environment
    maintained_adjusted_daily.update(producer_root=producer)
    status = maintained_adjusted_daily.current_generation()
    raw_path = Path(status["path"]) / "raw.parquet"
    adjusted_path = Path(status["path"]) / "reference_factor_adjusted.parquet"
    raw_path.write_bytes(adjusted_path.read_bytes())
    maintained_adjusted_daily._VERIFIED.clear()

    with pytest.raises(ValueError, match="does not match the bytes/SHA-256"):
        maintained_adjusted_daily.read_adjusted_daily("raw")


def test_a_pinned_generation_survives_an_update_until_pruned(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, _ = environment
    maintained_adjusted_daily.update(producer_root=producer)
    _, pinned = maintained_adjusted_daily.read_adjusted_daily("raw")
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(1))
    maintained_adjusted_daily.update(producer_root=producer)

    frame, record = maintained_adjusted_daily.read_adjusted_daily("raw", generation=pinned["generation"])
    assert record["generation"] == pinned["generation"] and record["sha256"] == pinned["sha256"] and len(frame) == 6

    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(2))
    maintained_adjusted_daily.update(producer_root=producer)
    with pytest.raises(FileNotFoundError, match="may have been pruned"):
        maintained_adjusted_daily.read_adjusted_daily("raw", generation=pinned["generation"])
    with pytest.raises(FileNotFoundError):
        maintained_adjusted_daily.read_adjusted_daily("raw", generation="../escape")


def test_a_shioaji_row_cannot_mark_neighbouring_official_rows(environment: tuple[Path, Path]) -> None:
    producer, _ = environment
    rows = [
        {"Code": "2330", "Date": pd.Timestamp(day), "Open": close, "High": close, "Low": close, "Close": close, "Volume": 1.0, "Source": source}
        for day, close, source in (("2026-10-12", 100.0, "official"), ("2026-10-13", 10.0, "shioaji"), ("2026-10-14", 101.0, "official"))
    ]
    pd.DataFrame(rows).to_parquet(producer / "price_daily.parquet", index=False)
    maintained_adjusted_daily.update(producer_root=producer)

    frame, _ = maintained_adjusted_daily.read_adjusted_daily("raw")
    assert frame["Date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-10-12", "2026-10-14"]
    assert frame["Quality"].tolist() == [True, True]


def test_concurrent_writer_is_refused(environment: tuple[Path, Path]) -> None:
    producer, shared = environment
    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    family.mkdir(parents=True)
    (family / ".writer.lock").write_text("pid=1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="another update holds"):
        maintained_adjusted_daily.update(producer_root=producer)
    assert not (family / "current.json").exists()


def test_cli_update_then_status(environment: tuple[Path, Path]) -> None:
    producer, shared = environment
    environment_variables = {**os.environ, "STOCK_PRODUCER_DATA_ROOT": str(producer), ENV_KEY: str(shared)}
    repo = Path(__file__).resolve().parents[2]
    script = (
        "import sys; from research_core import run_receipt; run_receipt.assert_producer_idle = lambda now=None: None; "
        "from scripts.maintain_adjusted_daily import main; sys.argv = ['x', sys.argv[1]]; raise SystemExit(main())"
    )
    for command in ("update", "status"):
        result = subprocess.run(
            [sys.executable, "-c", script, command], cwd=repo, env=environment_variables, capture_output=True, text=True, encoding="utf-8", check=False
        )
        assert result.returncode == 0, result.stderr
    assert '"asof": "2026-10-15"' in result.stdout


class _Later:
    """A datetime stand-in whose now() moves forward, so generation ids differ."""

    def __init__(self, offset: int) -> None:
        self.offset = offset

    def now(self, tz: object = None) -> object:
        from datetime import datetime, timedelta

        return datetime.now(tz) + timedelta(seconds=self.offset)  # type: ignore[arg-type]
