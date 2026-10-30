from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from research_core import momentum_forward_attempts_v2 as journal
from research_core import momentum_forward_run_v2 as runner
from research_core import momentum_forward_v1 as v1


class Clock:
    def __init__(self, value: str = "2026-10-22 21:00") -> None:
        self.value = cast(pd.Timestamp, pd.Timestamp(value, tz=v1.TAIPEI))

    def __call__(self) -> pd.Timestamp:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value = cast(pd.Timestamp, self.value + pd.Timedelta(seconds=seconds))


def fixture_frame(codes: Sequence[str], *, generation: str, day: str, late: bool, workers: int = 1) -> pd.DataFrame:
    return pd.DataFrame({"t0": day, "security_id": [f"TW:{code}" for code in codes], "generation": generation, "recorded_late": late})


@pytest.fixture()
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    generation = tmp_path / "fixture-generation"
    generation.mkdir()
    pd.DataFrame({"Date": pd.to_datetime(["2026-10-21", "2026-10-22"])}).to_parquet(generation / "calendar.parquet")
    status = {"generation": "fixture-g22", "asof": "2026-10-22", "path": str(generation)}
    monkeypatch.setattr(v1, "current_generation", lambda: status)
    monkeypatch.setattr(v1, "day_frame", fixture_frame)
    # Fail immediately if any real market path is accidentally reached.
    monkeypatch.setattr(v1, "read_adjusted_daily", lambda *args, **kwargs: pytest.fail("real market reader called"))
    return status


def invoke(root: Path, **kwargs: Any) -> Path | None:
    return runner.run(root, lambda: ["1101", "2330"], identity=lambda: ("fixture-commit", None), clock=kwargs.pop("clock", Clock()), **kwargs)


def test_start_precedes_identity_generation_producer_and_codes(tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def accepted() -> None:
        assert len(list((tmp_path / journal.JOURNAL).glob("*/started.json"))) == 1

    def identity() -> tuple[str, None]:
        accepted()
        return "fixture-commit", None

    def generation() -> dict[str, Any]:
        accepted()
        return source

    def codes() -> list[str]:
        accepted()
        return ["1101"]

    monkeypatch.setattr(v1, "current_generation", generation)
    assert runner.run(tmp_path, codes, identity=identity, clock=Clock(), producer_idle=accepted)
    rows = journal.read_attempts(tmp_path)
    assert len(rows) == 1 and rows[0]["outcome"] == "on_time" and rows[0]["code_commit"] == "fixture-commit"
    assert json.loads(next((tmp_path / journal.JOURNAL).glob("*/started.json")).read_bytes())["code_commit"] == "unknown"


@pytest.mark.parametrize("case", ["on_time", "late", "refused", "generation_failure", "producer_busy", "already_frozen"])
def test_outcomes_and_existing_artifacts_stay_byte_identical(tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    root = tmp_path / "log"
    root.mkdir()
    (root / "attempts.jsonl").write_bytes(b'{"outcome":"legacy"}\n')
    (root / "days").mkdir()
    (root / "days" / "2026-10-20.parquet").write_bytes(b"legacy untouched day")
    (root / "cohort.json").write_text(json.dumps({"confirmatory_start": "2026-10-22", "confirmatory_end": "2027-10-21"}), encoding="utf-8")
    if case == "already_frozen":
        v1.record_day(root, ["1101"], day=None, code_commit="old", now=Clock())
    protected = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    kwargs: dict[str, Any] = {}
    if case == "late":
        kwargs["day"] = "2026-10-21"
    elif case == "refused":
        monkeypatch.setattr(runner, "code_identity", lambda repo: ("c", "uncommitted"))
        runner.run(root, lambda: pytest.fail("codes requested on refusal"), identity=lambda: runner.code_identity(tmp_path), clock=Clock())
    elif case == "generation_failure":

        def broken() -> dict[str, Any]:
            raise FileNotFoundError("fixture generation unavailable")

        monkeypatch.setattr(v1, "current_generation", broken)
        with pytest.raises(FileNotFoundError):
            invoke(root)
    elif case == "producer_busy":

        def busy() -> None:
            raise RuntimeError("fixture writer")

        kwargs["producer_idle"] = busy
    if case not in {"refused", "generation_failure"}:
        if case == "already_frozen":
            with pytest.raises(FileExistsError):
                invoke(root)
        else:
            invoke(root, **kwargs)
    rows = journal.read_attempts(root, include_legacy=False)
    expected = {"generation_failure": "failed", "producer_busy": "refused"}.get(case, case)
    assert len(rows) == 1 and rows[0]["outcome"] == expected
    for path, raw in protected.items():
        assert path.read_bytes() == raw
    before = (root / journal.LEDGER).read_bytes()
    journal.recover(root)
    assert (root / journal.LEDGER).read_bytes() == before


def test_computation_failure_records_one_terminal(tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise OSError("fixture disk full")

    monkeypatch.setattr(v1, "day_frame", failed)
    with pytest.raises(OSError, match="disk full"):
        invoke(tmp_path)
    assert [entry["outcome"] for entry in journal.read_attempts(tmp_path)] == ["failed"]


def test_waits_for_today_and_busy_producer_then_already_frozen(tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()

    def generation() -> dict[str, Any]:
        return source if clock.value.hour >= 22 else {**source, "asof": "2026-10-21"}

    def idle() -> None:
        if clock.value < pd.Timestamp("2026-10-22 22:30", tz=v1.TAIPEI):
            raise RuntimeError("fixture writer")

    monkeypatch.setattr(v1, "current_generation", generation)
    first = invoke(tmp_path, scheduled=True, clock=clock, sleep=clock.sleep, producer_idle=idle)
    again = invoke(tmp_path, scheduled=True, clock=clock, sleep=clock.sleep, producer_idle=idle)
    assert first == again and first is not None
    assert [entry["outcome"] for entry in journal.read_attempts(tmp_path)] == ["on_time", "already_frozen"]


def test_scheduled_stale_generation_stops_without_holiday_inference(tmp_path: Path, source: dict[str, Any]) -> None:
    source["asof"] = "2026-10-21"
    clock = Clock()
    assert invoke(tmp_path, scheduled=True, clock=clock, sleep=clock.sleep) is None
    row = journal.read_attempts(tmp_path)[0]
    assert row["outcome"] == "not_recorded" and row["target_day"] == "2026-10-22"
    assert "not refreshed" in row["reason"] and not (tmp_path / "days").exists()


def test_crossing_0900_stays_late(tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()

    def slow(*args: Any, **kwargs: Any) -> pd.DataFrame:
        clock.sleep(12 * 3600 + 60)
        return fixture_frame(*args, **kwargs)

    monkeypatch.setattr(v1, "day_frame", slow)
    path = invoke(tmp_path, scheduled=True, clock=clock, sleep=clock.sleep)
    assert path and bool(pd.read_parquet(path)["recorded_late"].all())
    assert journal.read_attempts(tmp_path)[0]["outcome"] == "late" and v1.read_cohort(tmp_path) is None


def day_crash_child(root: Path, late: bool = False) -> None:
    """Synthetic sources only; terminate this test child after day publication."""

    def generation_status(root: Path | None = None, *, generation: str | None = None) -> dict[str, Any]:
        return {"generation": "fixture", "asof": "2026-10-22"}

    v1.current_generation = generation_status
    v1.day_frame = fixture_frame
    v1._write_cohort = lambda *args, **kwargs: os._exit(74)
    invoke(root, clock=Clock("2026-10-26 21:00") if late else Clock())


@pytest.mark.parametrize("late", [False, True])
def test_published_day_survives_death_and_only_v1_recovers_cohort(tmp_path: Path, source: dict[str, Any], late: bool) -> None:
    root = tmp_path / "crash"
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "from scripts.tests.test_momentum_forward_run_v2 import day_crash_child; "
            "day_crash_child(Path(sys.argv[1]), sys.argv[2] == 'late')",
            str(root),
            "late" if late else "on_time",
        ],
        timeout=30,
        capture_output=True,
        check=False,
    )
    assert child.returncode == 74, child.stderr.decode(errors="replace")
    day = root / "days" / "2026-10-22.parquet"
    original = day.read_bytes()
    assert v1.read_cohort(root) is None
    journal.recover(root)
    assert v1.read_cohort(root) is None and day.read_bytes() == original
    row = journal.read_attempts(root)[0]
    assert row["outcome"] == "interrupted" and row["completion"] == "unknown"
    # Re-enter only the public v1 route, preserving its frozen timing evidence.
    if late:
        with pytest.raises(FileExistsError):
            invoke(root, clock=Clock("2026-10-26 21:00"))
        assert day.read_bytes() == original and v1.read_cohort(root) is None
        assert journal.read_attempts(root)[-1]["outcome"] == "already_frozen"
        return
    invoke(root, clock=Clock("2026-10-26 21:00"))
    assert day.read_bytes() == original
    assert journal.read_attempts(root)[-1]["outcome"] == "cohort_recovered"
    cohort = v1.read_cohort(root)
    assert cohort and cohort["first_frozen_at_utc"] == pd.read_parquet(day)["recorded_at_utc"].iloc[0]


def test_two_invocations_do_not_write_days_concurrently(tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    child = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            "from pathlib import Path; import sys; "
            "from research_core.momentum_forward_attempts_v2 import Attempt, root_lock, utc_now; "
            "root=Path(sys.argv[1]); a=Attempt(root, requested_day=None, mode='scheduled'); "
            "lock=root_lock(root, '.attempts-v2-writer.lock'); assert lock.__enter__(); "
            "print(a.attempt_id, flush=True); sys.stdin.readline(); "
            "a.finish({'outcome':'not_recorded','reason':'fixture','finished_at_utc':utc_now()}); "
            "a.close(); lock.__exit__(None,None,None)",
            str(tmp_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        active = child.stdout.readline().strip()
        assert len(active) == 32
        monkeypatch.setattr(v1, "current_generation", lambda: pytest.fail("busy recorder read market"))
        assert invoke(tmp_path) is None
        assert not (tmp_path / "days").exists()
        assert not (tmp_path / journal.JOURNAL / active / "terminal.json").exists()
        assert [entry["outcome"] for entry in journal.read_attempts(tmp_path)] == ["refused"]
    finally:
        child.communicate("release\n", timeout=30)
    assert child.returncode == 0
    journal.recover(tmp_path)
    assert len(journal.read_attempts(tmp_path)) == 2


def test_wait_interrupt_has_one_failed_terminal(tmp_path: Path, source: dict[str, Any]) -> None:
    source["asof"] = "2026-10-21"

    def interrupted(seconds: float) -> None:
        raise KeyboardInterrupt("fixture")

    with pytest.raises(KeyboardInterrupt):
        invoke(tmp_path, scheduled=True, sleep=interrupted)
    assert [entry["outcome"] for entry in journal.read_attempts(tmp_path)] == ["failed"]


def test_corrupt_ledger_blocks_before_market_reads(tmp_path: Path, source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    old = journal.Attempt(tmp_path, requested_day=None, mode="manual")
    old.close()
    ledger = tmp_path / journal.LEDGER
    ledger.write_bytes(b'{"partial":')
    monkeypatch.setattr(v1, "current_generation", lambda: pytest.fail("corrupt ledger read market"))
    with pytest.raises(journal.JournalError, match="partial JSONL"):
        invoke(tmp_path)
    assert ledger.read_bytes() == b'{"partial":'


@pytest.mark.parametrize(
    "path",
    [
        "research_core/momentum_forward_attempts_v2.py",
        "research_core/momentum_forward_run_v2.py",
        "scripts/record_momentum_forward_day_v2.py",
    ],
)
def test_ci_domain_selects_new_suites_and_v1_regression(path: str) -> None:
    from scripts import ci_scope

    plan = ci_scope.make_plan([("A", path)])
    assert not plan["full"] and "momentum_forward_v2" in plan["domains"]
    assert {
        "scripts/tests/test_momentum_forward_attempts_v2.py",
        "scripts/tests/test_momentum_forward_run_v2.py",
        "scripts/tests/test_momentum_forward_v1.py",
    } <= set(plan["python_tests"])


@pytest.mark.parametrize(
    "path",
    [
        "scripts/tests/test_momentum_forward_attempts_v2.py",
        "scripts/tests/test_momentum_forward_run_v2.py",
    ],
)
def test_ci_changed_suite_runs_itself_without_selecting_its_domain(path: str) -> None:
    from scripts import ci_scope

    # A changed test is a consumer, not a source change to the domain it verifies.
    plan = ci_scope.make_plan([("A", path)])
    assert not plan["full"] and plan["domains"] == []
    assert path in plan["python_tests"]


def test_identity_failure_is_journaled_before_market_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def identity() -> tuple[str, str | None]:
        assert next((tmp_path / journal.JOURNAL).glob("*/started.json")).exists()
        raise OSError("fixture identity unavailable")

    monkeypatch.setattr(v1, "current_generation", lambda: pytest.fail("identity failure read market"))
    with pytest.raises(OSError, match="identity unavailable"):
        runner.run(tmp_path, lambda: pytest.fail("identity failure requested universe"), identity=identity)
    row = journal.read_attempts(tmp_path)[0]
    assert row["outcome"] == "failed" and row["code_commit"] == "unknown"
