from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_core import momentum_forward_attempts_v2 as journal


def crash_child(root: Path, stage: str) -> None:
    """Only called in the child created by the synthetic crash test below."""

    def checkpoint(point: str) -> None:
        if point == stage:
            os._exit(73)

    attempt = journal.Attempt(root, requested_day=None, mode="manual", checkpoint=checkpoint)
    attempt.finish({"outcome": "refused", "reason": "fixture", "finished_at_utc": journal.utc_now()})
    attempt.close()


@pytest.mark.parametrize("stage", ["started", "terminal", "appended"])
def test_real_child_crashes_and_restarts_once(tmp_path: Path, stage: str) -> None:
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "from scripts.tests.test_momentum_forward_attempts_v2 import crash_child; "
            "crash_child(Path(sys.argv[1]), sys.argv[2])",
            str(tmp_path),
            stage,
        ],
        check=False,
        timeout=30,
        capture_output=True,
    )
    assert child.returncode == 73, child.stderr.decode(errors="replace")
    started = next((tmp_path / journal.JOURNAL).glob("*/started.json"))
    original = started.read_bytes()
    assert journal.recover(tmp_path) == []
    rows = journal.read_attempts(tmp_path)
    assert len(rows) == 1
    terminal = started.with_name("terminal.json").read_bytes()
    ledger = (tmp_path / journal.LEDGER).read_bytes()
    assert journal.recover(tmp_path) == []
    assert (tmp_path / journal.LEDGER).read_bytes() == ledger
    assert started.read_bytes() == original and started.with_name("terminal.json").read_bytes() == terminal
    assert rows[0]["attempt_id"] == json.loads(original)["attempt_id"]
    if stage == "started":
        assert rows[0]["outcome"] == "interrupted" and rows[0]["completion"] == "unknown"
        assert rows[0]["finished_at_utc"] is None and "recovered_at_utc" in rows[0]
    else:
        assert rows[0]["outcome"] == "refused"


def test_live_os_owner_is_pending_even_with_ancient_timestamp(tmp_path: Path) -> None:
    child = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            "from pathlib import Path; import sys; "
            "from research_core.momentum_forward_attempts_v2 import Attempt; "
            "a=Attempt(Path(sys.argv[1]), requested_day=None, mode='manual'); "
            "print(a.attempt_id, flush=True); sys.stdin.readline(); a.close()",
            str(tmp_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        attempt_id = child.stdout.readline().strip()
        assert len(attempt_id) == 32
        path = tmp_path / journal.JOURNAL / attempt_id / "started.json"
        value = json.loads(path.read_bytes())
        value["attempted_at_utc"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(value), encoding="utf-8")
        before = path.read_bytes()
        assert journal.recover(tmp_path) == [attempt_id]
        assert path.read_bytes() == before and not path.with_name("terminal.json").exists()
    finally:
        child.communicate("release\n", timeout=30)
    assert child.returncode == 0
    journal.recover(tmp_path)
    assert journal.read_attempts(tmp_path)[0]["outcome"] == "interrupted"


@pytest.mark.parametrize("unknown", ["host", "protocol", "missing_lock", "lock_failure"])
def test_unknown_ownership_stays_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unknown: str) -> None:
    attempt = journal.Attempt(tmp_path, requested_day=None, mode="manual")
    attempt.close()
    start = attempt.path / "started.json"
    value = json.loads(start.read_bytes())
    if unknown in {"host", "protocol"}:
        value[f"owner_{unknown}"] = "unknown"
        start.write_text(json.dumps(value), encoding="utf-8")
    elif unknown == "missing_lock":
        (attempt.path / "owner.lock").unlink()
    else:
        monkeypatch.setattr(journal, "try_os_lock", lambda handle: False)
    assert journal.recover(tmp_path) == [attempt.attempt_id]
    assert not (attempt.path / "terminal.json").exists()


@pytest.mark.parametrize("raw", [b'{"attempt_id":', b"{}\n", b"\xff\n", b"\n", b'{"schema":1,"schema":2}\n'])
def test_corrupt_jsonl_preserves_all_bytes_and_stops(tmp_path: Path, raw: bytes) -> None:
    attempt = journal.Attempt(tmp_path, requested_day=None, mode="manual")
    attempt.close()
    path = tmp_path / journal.LEDGER
    path.write_bytes(raw)
    with pytest.raises(journal.JournalError, match="preserved"):
        journal.recover(tmp_path)
    assert path.read_bytes() == raw
    terminal = (attempt.path / "terminal.json").read_bytes()
    with pytest.raises(journal.JournalError):
        journal.recover(tmp_path)
    assert path.read_bytes() == raw and (attempt.path / "terminal.json").read_bytes() == terminal


@pytest.mark.parametrize("file", ["started.json", "terminal.json"])
def test_corrupt_intent_or_terminal_is_never_replaced(tmp_path: Path, file: str) -> None:
    attempt = journal.Attempt(tmp_path, requested_day=None, mode="manual")
    attempt.close()
    path = attempt.path / file
    path.write_bytes(b'{"broken":')
    with pytest.raises(journal.JournalError, match="corrupt"):
        journal.recover(tmp_path)
    assert path.read_bytes() == b'{"broken":'
    assert not (tmp_path / journal.LEDGER).exists()


def test_terminal_no_replace_and_legacy_rows_are_not_deduplicated(tmp_path: Path) -> None:
    legacy = tmp_path / "attempts.jsonl"
    legacy.write_bytes(b'{"outcome":"failed","attempted_at_utc":"same"}\n' * 2)
    old = legacy.read_bytes()
    attempt = journal.Attempt(tmp_path, requested_day="2026-10-22", mode="manual")
    fields: dict[str, Any] = {"outcome": "late", "finished_at_utc": journal.utc_now()}
    try:
        attempt.finish(fields)
        before = (attempt.path / "terminal.json").read_bytes()
        attempt.finish(fields)
        with pytest.raises(journal.JournalError, match="different terminal"):
            attempt.finish({**fields, "outcome": "on_time"})
        assert (attempt.path / "terminal.json").read_bytes() == before
    finally:
        attempt.close()
    journal.recover(tmp_path)
    rows = journal.read_attempts(tmp_path)
    assert len(rows) == 3 and rows[0] == rows[1]
    assert [row["physical_ledger"] for row in rows] == ["attempts.jsonl", "attempts.jsonl", journal.LEDGER]
    assert legacy.read_bytes() == old


def test_complete_ledger_conflict_stops_instead_of_appending(tmp_path: Path) -> None:
    attempt = journal.Attempt(tmp_path, requested_day=None, mode="manual")
    try:
        attempt.finish({"outcome": "failed", "finished_at_utc": journal.utc_now()})
    finally:
        attempt.close()
    ledger = tmp_path / journal.LEDGER
    row = json.loads(ledger.read_bytes())
    row["outcome"] = "refused"
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    before = ledger.read_bytes()
    with pytest.raises(journal.JournalError, match="conflicts"):
        journal.recover(tmp_path)
    assert ledger.read_bytes() == before
