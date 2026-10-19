from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from research_core import live_producer, maintained_adjusted_daily, price_basis, run_receipt
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


def test_a_same_size_replacement_after_a_cached_read_is_refused(environment: tuple[Path, Path]) -> None:
    producer, _ = environment
    maintained_adjusted_daily.update(producer_root=producer)
    maintained_adjusted_daily.read_adjusted_daily("raw")
    path = Path(maintained_adjusted_daily.current_generation()["path"]) / "raw.parquet"
    original = path.stat()
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    replacement = path.with_name("replacement.tmp")
    replacement.write_bytes(bytes(data))
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, path)
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (original.st_size, original.st_mtime_ns)

    with pytest.raises(ValueError, match="does not match the bytes/SHA-256"):
        maintained_adjusted_daily.read_adjusted_daily("raw")


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


SESSIONS = pd.bdate_range("2026-09-01", periods=12)
CUTOFF = cast(pd.Timestamp, SESSIONS[6])
AFTER_ASOF = cast(pd.Timestamp, SESSIONS[-1] + pd.Timedelta(days=1))


def _tricky_producer(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Quotes and actions that make truncating the latest generation wrong at CUTOFF."""
    rows = []
    for position, day in enumerate(SESSIONS):
        close = 100.0 if position < 3 else 50.0  # an unexplained 50% drop
        volume = -5.0 if position == 5 else 1000.0
        rows.append({"Code": "2330", "Date": day, "Open": close, "High": close, "Low": close, "Close": close, "Volume": volume, "Source": "official"})
    for position in range(2, 11):
        if position == 6:
            continue  # a missing session inside the symbol's span
        high = 9.0 if position == 4 else 21.0  # invalid OHLC on one day
        rows.append({"Code": "1101", "Date": SESSIONS[position], "Open": 20.0, "High": high, "Low": 19.0, "Close": 20.0, "Volume": 7.0, "Source": "official"})
    rows.append({"Code": "1101", "Date": SESSIONS[3], "Open": 30.0, "High": 30.0, "Low": 30.0, "Close": 30.0, "Volume": 1.0, "Source": "official"})
    rows.append({"Code": "1101", "Date": SESSIONS[8], "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0, "Source": "shioaji"})
    rows.append({"Code": "6488", "Date": SESSIONS[9], "Open": 5.0, "High": 5.0, "Low": 5.0, "Close": 5.0, "Volume": 1.0, "Source": "official"})
    bars = pd.DataFrame(rows)
    actions = pd.DataFrame(
        [
            ("1101", SESSIONS[5], "EX_RIGHT", 0.9),
            ("1101", SESSIONS[9], "EX_RIGHT", 0.8),  # same-day conflict after the cutoff masks all history
            ("1101", SESSIONS[9], "CASH_DIVIDEND", 0.95),
            ("2330", pd.Timestamp("2026-09-05"), "EX_RIGHT", 0.9),  # a Saturday ex-date before the cutoff
            ("2330", CUTOFF, "CASH_DIVIDEND", 1.2),  # unusable on the cutoff itself: no factor exists at the cutoff
            ("2330", SESSIONS[8], "MYSTERY_EVENT", 0.5),  # unknown kind after the cutoff
            ("2330", SESSIONS[10], "CASH_DIVIDEND", None),  # missing factor after the cutoff
            ("2330", SESSIONS[11] + pd.Timedelta(days=30), "CASH_DIVIDEND", 0.9),  # after asof
            ("6488", SESSIONS[2], "CASH_DIVIDEND", 0.9),
        ],
        columns=pd.Index(["code", "ex_date", "event_type", "price_factor"]),
    )
    actions["ex_date"] = actions["ex_date"].dt.strftime("%Y-%m-%d")
    bars.to_parquet(root / "price_daily.parquet", index=False)
    database = root / "corporate_actions.sqlite"
    database.unlink(missing_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
        connection.executemany("INSERT INTO corporate_actions VALUES (?, ?, ?, ?)", actions.itertuples(index=False, name=None))
    connection.close()
    return bars, actions


def _oracle(bars: pd.DataFrame, actions: pd.DataFrame, code: str, calendar: pd.DatetimeIndex, basis: str) -> pd.DataFrame:
    """The contract: official quotes <= cutoff and actions <= cutoff on a fixed calendar."""
    official = bars.loc[bars["Source"].eq("official") & bars["Code"].eq(code) & bars["Date"].le(CUTOFF)].drop(columns="Source")
    events = actions.loc[actions["code"].eq(code) & pd.to_datetime(actions["ex_date"]).le(CUTOFF)]
    prepared = price_basis.prepare_prices(official, events, calendar, basis=basis, cutoff=CUTOFF)  # type: ignore[arg-type]
    frame = prepared.rename_axis("Date").reset_index()
    frame.insert(0, "Code", code)
    return frame


@pytest.mark.parametrize("basis", maintained_adjusted_daily.BASES)
@pytest.mark.parametrize("calendar_kind", ["generation", "fixed"])
def test_as_of_read_equals_prepare_prices_at_the_cutoff(environment: tuple[Path, Path], basis: str, calendar_kind: str) -> None:
    producer, _ = environment
    bars, actions = _tricky_producer(producer)
    maintained_adjusted_daily.update(producer_root=producer)
    if calendar_kind == "fixed":
        # Drop one generation session and add a Sunday no symbol traded on.
        calendar = cast(pd.DatetimeIndex, SESSIONS[SESSIONS <= CUTOFF].drop(SESSIONS[4]).append(pd.DatetimeIndex(["2026-09-06"])).sort_values())
    else:
        calendar = cast(pd.DatetimeIndex, SESSIONS[SESSIONS <= CUTOFF])

    frame, record = maintained_adjusted_daily.read_adjusted_daily(
        basis, as_of=CUTOFF.date().isoformat(), calendar=calendar if calendar_kind == "fixed" else None
    )

    assert record["as_of"] == CUTOFF.date().isoformat() and record["calendar"]["source"] == ("caller" if calendar_kind == "fixed" else "generation")
    assert sorted(frame["Code"].unique()) == ["1101", "2330"], "6488 first quoted after the cutoff"
    for code in ("1101", "2330"):
        got = frame.loc[frame["Code"].eq(code)].reset_index(drop=True)
        pd.testing.assert_frame_equal(got, _oracle(bars, actions, code, calendar, basis), check_exact=True)
    if basis == "reference_factor_adjusted":
        assert bool(frame.loc[frame["Code"].eq("2330"), "restatement_factor"].isna().all()), "no usable factor at the cutoff is reported, not guessed"
    first_1101 = frame.loc[frame["Code"].eq("1101")].iloc[0]
    assert bool(first_1101["Date"] == calendar[0]) and first_1101["quality_reason"] == "missing_official_quote", "rows before the first quote are kept"


def test_truncating_the_latest_generation_is_not_the_cutoff_state(environment: tuple[Path, Path]) -> None:
    producer, _ = environment
    _tricky_producer(producer)
    maintained_adjusted_daily.update(producer_root=producer)

    latest, _ = maintained_adjusted_daily.read_adjusted_daily("reference_factor_adjusted", codes=["1101"])
    at_cutoff, _ = maintained_adjusted_daily.read_adjusted_daily("reference_factor_adjusted", codes=["1101"], as_of=CUTOFF)

    truncated = latest.loc[latest["Date"].le(CUTOFF)]
    assert truncated["restatement_factor"].isna().all(), "the later same-day conflict masks the whole history"
    assert bool(at_cutoff["restatement_factor"].notna().all())
    assert bool(at_cutoff.loc[at_cutoff["Date"].lt(SESSIONS[5]), "restatement_factor"].eq(0.9).all())


def test_as_of_read_refuses_what_it_cannot_know(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, _ = environment
    _tricky_producer(producer)
    maintained_adjusted_daily.update(producer_root=producer)

    with pytest.raises(ValueError, match="after generation"):
        maintained_adjusted_daily.read_adjusted_daily("raw", as_of=AFTER_ASOF)
    with pytest.raises(ValueError, match="no official quote on or before"):
        maintained_adjusted_daily.read_adjusted_daily("raw", codes=["2330", "6488"], as_of=CUTOFF)
    with pytest.raises(ValueError, match="pass as_of"):
        maintained_adjusted_daily.read_adjusted_daily("raw", calendar=SESSIONS)
    with pytest.raises(ValueError, match="Calendar contains dates after cutoff"):
        maintained_adjusted_daily.read_adjusted_daily("raw", as_of=CUTOFF, calendar=SESSIONS)

    status = maintained_adjusted_daily.current_generation()
    actions_path = Path(status["path"]) / status["as_of_inputs"]["actions"]["file"]
    actions_path.write_bytes(actions_path.read_bytes()[:-1] + b"\0")
    maintained_adjusted_daily._VERIFIED.clear()
    with pytest.raises(ValueError, match="does not match the bytes/SHA-256"):
        maintained_adjusted_daily.read_adjusted_daily("raw", as_of=CUTOFF)

    older = {key: value for key, value in status.items() if key != "as_of_inputs"}
    monkeypatch.setattr(maintained_adjusted_daily, "current_generation", lambda root=None, generation=None: older)
    with pytest.raises(ValueError, match="no actions snapshot"):
        maintained_adjusted_daily.read_adjusted_daily("raw", as_of=CUTOFF)


def test_real_data_check_script_reports_equality_and_truncation_damage(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scripts import check_adjusted_daily_asof

    producer, shared = environment
    _tricky_producer(producer)
    out = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["x", "--root", str(shared), "--build", "--cutoff", CUTOFF.date().isoformat(), "--out", str(out)])

    assert check_adjusted_daily_asof.main() == 0
    entry = json.loads(out.read_text(encoding="utf-8"))["cutoffs"][0]
    assert entry["codes"] == 2 and all(entry[basis]["equal"] for basis in maintained_adjusted_daily.BASES)
    assert entry["reference_factor_adjusted"]["truncation_codes_masked_in_latest_known_at_cutoff"] == 1
    assert entry["situations"]["post_cutoff_multi_kind_days"] == 1 and entry["situations"]["post_cutoff_unknown_kind"] == 1


def test_official_quotes_are_the_source_rows_the_generation_saw_and_feed_a_receipt(environment: tuple[Path, Path]) -> None:
    producer, _ = environment
    bars, _ = _tricky_producer(producer)
    maintained_adjusted_daily.update(producer_root=producer)

    quotes, calendar, record = maintained_adjusted_daily.read_official_quotes(codes=["1101", "2330", "6488", "9999"], as_of=CUTOFF)

    assert calendar.equals(SESSIONS[SESSIONS <= CUTOFF]), "the generation's official session union, cut at as_of"
    assert record["absent_codes"] == ["6488", "9999"], "no quote on or before the cutoff is reported, not refused"
    assert record["calendar"]["sessions"] == len(calendar) and record["rows"] == len(quotes)
    expected = bars.loc[bars["Source"].eq("official") & bars["Date"].le(CUTOFF) & bars["Code"].isin(["1101", "2330"])].drop(columns="Source")
    assert list(quotes.columns) == ["Code", "Date", "Open", "High", "Low", "Close", "Volume"]
    counts = quotes.groupby(["Code", "Date"]).size()
    assert counts.equals(expected.groupby(["Code", "Date"]).size()), "gaps stay absent; a duplicated date keeps both rows"
    single = expected.loc[~expected.duplicated(["Code", "Date"], keep=False)].sort_values(["Code", "Date"]).reset_index(drop=True)
    single["Volume"] = single["Volume"].where(single["Volume"].ge(0))  # prepare_prices stores an invalid volume as NaN
    got = quotes.loc[~quotes.duplicated(["Code", "Date"], keep=False)].reset_index(drop=True)
    pd.testing.assert_frame_equal(got, single, check_dtype=False)

    assert record["generation"] == maintained_adjusted_daily.current_generation()["generation"]


def test_a_held_generation_survives_updates_until_released(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = environment
    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    held = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    record = maintained_adjusted_daily.hold_generation(held, holder="pr17-pattern-scan", reason="Q2-Q6 read this generation")
    assert record["generation"] == held
    for offset in (1, 2, 3):
        monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(offset))
        result = maintained_adjusted_daily.update(producer_root=producer)
        assert held in result["held"]
    assert held in {path.name for path in (family / "generations").iterdir()}, "updates keep a held generation"
    frame, read = maintained_adjusted_daily.read_adjusted_daily("raw", generation=held)
    assert read["generation"] == held and len(frame) == 6
    assert len(list((family / "generations").iterdir())) == 3, "current + previous + the held one, nothing else"

    released = maintained_adjusted_daily.release_generation("pr17-pattern-scan")
    assert released is not None and released["generation"] == held
    assert maintained_adjusted_daily.release_generation("pr17-pattern-scan") is None
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(4))
    maintained_adjusted_daily.update(producer_root=producer)
    assert held not in {path.name for path in (family / "generations").iterdir()}, "released generations are pruned again"

    with pytest.raises(FileNotFoundError, match="may have been pruned"):
        maintained_adjusted_daily.hold_generation(held, holder="late", reason="too late")
    with pytest.raises(ValueError, match="holder must match"):
        maintained_adjusted_daily.hold_generation(result["generation"], holder="../escape", reason="x")
    with pytest.raises(ValueError, match="reason"):
        maintained_adjusted_daily.hold_generation(result["generation"], holder="ok", reason=" ")


def test_a_hold_racing_a_prune_is_refused_not_silently_lost(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = environment
    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    first = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(1))
    maintained_adjusted_daily.update(producer_root=producer)
    monkeypatch.setattr(maintained_adjusted_daily, "HOLDS_LOCK_WAIT_SECONDS", 0.2)
    original = maintained_adjusted_daily.held_generations
    attempts: list[BaseException] = []

    def hold_during_prune(root: Path | None = None) -> dict[str, list[dict[str, object]]]:
        # The first call is the prune, holding the lock: a hold now must wait, then be refused.
        if not attempts:
            try:
                maintained_adjusted_daily.hold_generation(first, holder="late-study", reason="started mid-prune")
            except RuntimeError as error:
                attempts.append(error)
        return original(root)

    monkeypatch.setattr(maintained_adjusted_daily, "held_generations", hold_during_prune)
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(2))
    result = maintained_adjusted_daily.update(producer_root=producer)

    assert len(attempts) == 1 and "holds.lock" in str(attempts[0]), "the racing hold is refused, not reported as successful"
    assert first in result["pruned"] and not (family / "holds" / "late-study.json").exists()

    monkeypatch.setattr(maintained_adjusted_daily, "held_generations", original)
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(3))
    with maintained_adjusted_daily._holds_lock(family):  # another process mid-prune or mid-hold
        blocked = maintained_adjusted_daily.update(producer_root=producer)
    assert blocked["pruned"] == [], "a held lock skips pruning instead of failing a published update"
    assert read_json(family / "current.json")["generation"] == blocked["generation"]


def test_release_waits_for_the_holds_lock(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = environment
    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    generation = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    maintained_adjusted_daily.hold_generation(generation, holder="study", reason="reads it")
    monkeypatch.setattr(maintained_adjusted_daily, "HOLDS_LOCK_WAIT_SECONDS", 0.2)

    with maintained_adjusted_daily._holds_lock(family), pytest.raises(RuntimeError, match="holds.lock"):
        maintained_adjusted_daily.release_generation("study")
    assert (family / "holds" / "study.json").exists(), "a release never races a prune scan or a new hold"

    released = maintained_adjusted_daily.release_generation("study")
    assert released is not None and released["generation"] == generation


def test_a_lock_left_by_a_killed_process_does_not_stop_pruning(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, shared = environment
    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    first = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(1))
    maintained_adjusted_daily.update(producer_root=producer)
    # A killed holder leaves the file but the OS drops its lock: closing a locked handle
    # without unlocking is what process exit does.
    handle = (family / ".holds.lock").open("a+b")
    assert maintained_adjusted_daily._try_os_lock(handle)
    handle.close()

    monkeypatch.setattr(maintained_adjusted_daily, "datetime", _Later(2))
    result = maintained_adjusted_daily.update(producer_root=producer)

    assert first in result["pruned"], "a lock file without a live holder does not stop pruning"


def test_a_live_lock_is_never_taken_over(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _, shared = environment
    family = shared / "derived" / maintained_adjusted_daily.FAMILY
    monkeypatch.setattr(maintained_adjusted_daily, "HOLDS_LOCK_WAIT_SECONDS", 0.2)
    old = family / ".holds.lock"
    family.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"")
    os.utime(old, (0, 0))  # however old the file looks, a live lock holds
    with maintained_adjusted_daily._holds_lock(family):
        with pytest.raises(RuntimeError, match="holds.lock"), maintained_adjusted_daily._holds_lock(family):
            pass
    with maintained_adjusted_daily._holds_lock(family):
        pass  # released by its owner, then free again


def test_holds_listing_skips_a_hold_released_while_listing(environment: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    producer, _ = environment
    generation = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    maintained_adjusted_daily.hold_generation(generation, holder="study", reason="reads it")
    original = maintained_adjusted_daily.read_json

    def released_meanwhile(path: Path) -> object:
        if path.name == "study.json":
            raise FileNotFoundError(path)
        return original(path)

    monkeypatch.setattr(maintained_adjusted_daily, "read_json", released_meanwhile)
    assert maintained_adjusted_daily.held_generations() == {}


def test_holds_listing_reads_only_formal_holder_files(environment: tuple[Path, Path]) -> None:
    producer, shared = environment
    holds = shared / "derived" / maintained_adjusted_daily.FAMILY / "holds"
    generation = maintained_adjusted_daily.update(producer_root=producer)["generation"]
    maintained_adjusted_daily.hold_generation(generation, holder="study", reason="reads it")
    (holds / ".other-123.json").write_text("{", encoding="utf-8")  # a writer killed mid-write
    (holds / ".other-124.tmp").write_text("{", encoding="utf-8")
    assert [record["holder"] for record in maintained_adjusted_daily.held_generations()[generation]] == ["study"]
    assert sorted(path.name for path in holds.glob("*.tmp")) == [".other-124.tmp"], "a completed hold write leaves no temporary file"
