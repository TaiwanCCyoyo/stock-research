from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from research_core import momentum_forward_v1 as forward
from research_core import momentum_only_v1 as study


def taipei(text: str) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(text, tz="Asia/Taipei"))


@pytest.fixture()
def fake_generation(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    status = {"generation": "2026-10-22-20261022T123008Z", "asof": "2026-10-22"}
    original = forward.record_day

    def evening(*args: Any, **kwargs: Any) -> Path:
        kwargs.setdefault("now", taipei("2026-10-22 21:00"))
        return original(*args, **kwargs)

    monkeypatch.setattr(forward, "record_day", evening)
    monkeypatch.setattr(forward, "current_generation", lambda generation=None: status)

    def frame(codes: list[str], *, generation: str, day: str, late: bool, workers: int = 1) -> pd.DataFrame:
        return pd.DataFrame({"t0": day, "security_id": [f"TW:{code}" for code in codes], "generation": generation, "recorded_late": late})

    monkeypatch.setattr(forward, "day_frame", frame)
    return status


def test_on_time_day_starts_the_confirmatory_cohort_once(tmp_path: Path, fake_generation: dict[str, Any]) -> None:
    path = forward.record_day(tmp_path, ["1101", "2330"], day=None, code_commit="c" * 40)
    assert path == tmp_path / "days" / "2026-10-22.parquet"
    stored = pd.read_parquet(path)
    assert len(stored) == 2 and not bool(stored["recorded_late"].any()) and bool(stored["code_commit"].eq("c" * 40).all())
    cohort = json.loads((tmp_path / "cohort.json").read_text(encoding="utf-8"))
    assert cohort["confirmatory_start"] == "2026-10-22" and cohort["confirmatory_end"] == "2027-10-21"
    with pytest.raises(FileExistsError):
        forward.record_day(tmp_path, ["1101"], day=None, code_commit="c" * 40)


def test_late_days_never_start_the_cohort(tmp_path: Path, fake_generation: dict[str, Any]) -> None:
    forward.record_day(tmp_path, ["1101"], day="2026-10-13", code_commit="c" * 40)
    assert bool(pd.read_parquet(tmp_path / "days" / "2026-10-13.parquet")["recorded_late"].all())
    assert forward.read_cohort(tmp_path) is None
    forward.record_day(tmp_path, ["1101"], day=None, code_commit="c" * 40)
    first = forward.read_cohort(tmp_path)
    assert first is not None and first["confirmatory_start"] == "2026-10-22"


def test_an_on_time_record_requires_the_generation_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forward, "current_generation", lambda generation=None: {"generation": "g", "asof": "2026-10-21"})
    with pytest.raises(ValueError, match="needs the generation as-of"):
        forward.day_frame(["1101"], generation="g", day="2026-10-22", late=False)


def test_frozen_universe_matches_the_pr17_count_and_calendar() -> None:
    codes = study.pr17_codes()
    assert len(codes) == 1942 and codes == sorted(set(codes))
    calendar = study.pr17_calendar()
    assert calendar[0] == pd.Timestamp("2010-01-04") and calendar[-1] == pd.Timestamp("2026-10-12")


def test_days_before_the_merge_date_stay_prereg_even_when_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_generation: dict[str, Any]) -> None:
    fake_generation.update({"asof": "2026-10-21"})
    forward.record_day(tmp_path, ["1101"], day=None, code_commit="c" * 40)
    assert bool(pd.read_parquet(tmp_path / "days" / "2026-10-21.parquet")["recorded_late"].all())
    assert forward.read_cohort(tmp_path) is None


def test_a_crash_between_day_and_cohort_is_recoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_generation: dict[str, Any]) -> None:
    original = forward._write_cohort
    monkeypatch.setattr(forward, "_write_cohort", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        forward.record_day(tmp_path, ["1101"], day=None, code_commit="c" * 40)
    assert (tmp_path / "days" / "2026-10-22.parquet").exists() and forward.read_cohort(tmp_path) is None
    monkeypatch.setattr(forward, "_write_cohort", original)
    forward.record_day(tmp_path, ["1101"], day=None, code_commit="c" * 40)
    cohort = forward.read_cohort(tmp_path)
    assert cohort is not None and cohort["confirmatory_start"] == "2026-10-22"
    with pytest.raises(FileExistsError):
        forward.record_day(tmp_path, ["1101"], day=None, code_commit="c" * 40)


@pytest.mark.parametrize(
    ("now", "on_time"),
    [
        ("2026-10-22 20:50", True),
        ("2026-10-23 08:59", True),
        ("2026-10-23 09:00", False),
        ("2026-10-26 21:00", False),
    ],
)
def test_on_time_needs_the_next_session_not_yet_open(now: str, on_time: bool) -> None:
    assert forward.is_on_time("2026-10-22", "2026-10-22", taipei(now)) is on_time


def test_a_friday_is_on_time_until_monday_open() -> None:
    assert forward.freeze_deadline("2026-10-23") == taipei("2026-10-26 09:00")


def test_a_stale_generation_records_late_and_never_starts_the_cohort(tmp_path: Path, fake_generation: dict[str, Any]) -> None:
    forward.record_day(tmp_path, ["1101"], day=None, code_commit="c" * 40, now=taipei("2026-10-26 21:00"))
    assert bool(pd.read_parquet(tmp_path / "days" / "2026-10-22.parquet")["recorded_late"].all())
    assert forward.read_cohort(tmp_path) is None


def test_every_attempt_leaves_one_ledger_line(tmp_path: Path, fake_generation: dict[str, Any]) -> None:
    evening = taipei("2026-10-22 21:00")
    forward.record_with_ledger(tmp_path, ["1101"], day=None, code_commit="c" * 40, now=evening)
    with pytest.raises(FileExistsError):
        forward.record_with_ledger(tmp_path, ["1101"], day=None, code_commit="c" * 40, now=evening)
    forward.record_with_ledger(tmp_path, ["1101"], day="2026-10-21", code_commit="c" * 40, now=evening)
    assert forward.record_with_ledger(tmp_path, ["1101"], day=None, code_commit="c" * 40, refusal="producer busy: test") is None
    outcomes = [line["outcome"] for line in forward.read_attempts(tmp_path)]
    assert outcomes == ["on_time", "already_frozen", "late", "refused"]
    first = forward.read_attempts(tmp_path)[0]
    assert first["generation_asof"] == "2026-10-22" and first["rows"] == 1 and "finished_at_utc" in first


def test_a_failure_is_logged_and_reraised(tmp_path: Path, fake_generation: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forward, "day_frame", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        forward.record_with_ledger(tmp_path, ["1101"], day=None, code_commit="c" * 40, now=taipei("2026-10-22 21:00"))
    line = forward.read_attempts(tmp_path)[0]
    assert line["outcome"] == "failed" and "disk full" in line["reason"]
    assert not (tmp_path / "days" / "2026-10-22.parquet").exists()


class _Clock:
    def __init__(self, start: str) -> None:
        self.now = taipei(start)

    def __call__(self) -> pd.Timestamp:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now = cast(pd.Timestamp, self.now + pd.Timedelta(seconds=seconds))


def test_scheduled_mode_waits_for_today_then_records_on_time(tmp_path: Path, fake_generation: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock("2026-10-22 21:00")
    stale = {"generation": "g21", "asof": "2026-10-21", "built_at_utc": "2026-10-21T12:30:00+00:00"}
    fresh = {"generation": "g22", "asof": "2026-10-22", "built_at_utc": "2026-10-22T13:40:00+00:00"}
    monkeypatch.setattr(forward, "current_generation", lambda generation=None: fresh if clock.now >= taipei("2026-10-22 21:40") else stale)
    path = forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep, poll_seconds=900)
    assert path == tmp_path / "days" / "2026-10-22.parquet"
    assert forward.read_attempts(tmp_path)[-1]["outcome"] == "on_time"
    assert forward.read_cohort(tmp_path) is not None


def test_scheduled_mode_logs_a_generation_that_never_arrives(tmp_path: Path, fake_generation: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock("2026-10-22 21:00")
    stale = {"generation": "g21", "asof": "2026-10-21", "built_at_utc": "2026-10-21T12:30:00+00:00"}
    monkeypatch.setattr(forward, "current_generation", lambda generation=None: stale)
    assert forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep) is None
    line = forward.read_attempts(tmp_path)[-1]
    assert line["outcome"] == "not_recorded" and "not refreshed" in line["reason"] and line["target_day"] == "2026-10-22"
    assert line["generation"] == "g21" and line["generation_asof"] == "2026-10-21"
    assert "missing_confirmatory_days" in line or "missing_confirmatory_days_error" in line
    assert clock.now <= taipei("2026-10-23 09:00") and not (tmp_path / "days").exists()


def test_scheduled_mode_never_reads_a_stale_rebuild_as_a_holiday(tmp_path: Path, fake_generation: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock("2026-10-22 21:00")
    rebuilt = {"generation": "g21b", "asof": "2026-10-21", "built_at_utc": "2026-10-22T12:45:00+00:00"}
    fresh = {"generation": "g22", "asof": "2026-10-22", "built_at_utc": "2026-10-22T16:10:00+00:00"}
    monkeypatch.setattr(forward, "current_generation", lambda generation=None: fresh if clock.now >= taipei("2026-10-23 00:10") else rebuilt)
    path = forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep)
    assert path == tmp_path / "days" / "2026-10-22.parquet"
    assert [line["outcome"] for line in forward.read_attempts(tmp_path)] == ["on_time"]


def test_scheduled_mode_waits_out_a_busy_producer(tmp_path: Path, fake_generation: dict[str, Any]) -> None:
    clock = _Clock("2026-10-22 21:00")

    def idle() -> None:
        if clock.now < taipei("2026-10-22 22:00"):
            raise RuntimeError("producer writers are running")

    path = forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep, producer_idle=idle)
    assert path is not None and clock.now >= taipei("2026-10-22 22:00")
    assert forward.read_attempts(tmp_path)[-1]["outcome"] == "on_time"


def test_scheduled_mode_logs_an_already_frozen_day(tmp_path: Path, fake_generation: dict[str, Any]) -> None:
    clock = _Clock("2026-10-22 21:00")
    first = forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep)
    again = forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep)
    assert first == again == tmp_path / "days" / "2026-10-22.parquet"
    assert [line["outcome"] for line in forward.read_attempts(tmp_path)] == ["on_time", "already_frozen"]


def test_scheduled_mode_logs_uncommitted_code_as_refused(tmp_path: Path, fake_generation: dict[str, Any]) -> None:
    clock = _Clock("2026-10-22 21:00")
    assert forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep, refusal="uncommitted code") is None
    line = forward.read_attempts(tmp_path)[-1]
    assert line["outcome"] == "refused" and line["reason"] == "uncommitted code" and not (tmp_path / "days").exists()


def test_scheduled_mode_is_late_when_the_run_crosses_the_deadline(tmp_path: Path, fake_generation: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock("2026-10-22 21:00")
    original = forward.day_frame

    def slow(*args: Any, **kwargs: Any) -> pd.DataFrame:
        clock.sleep(12 * 3600 + 60)  # started on time, finished after 09:00
        return original(*args, **kwargs)

    monkeypatch.setattr(forward, "day_frame", slow)
    path = forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep)
    assert path is not None and bool(pd.read_parquet(path)["recorded_late"].all())
    assert forward.read_cohort(tmp_path) is None
    assert [line["outcome"] for line in forward.read_attempts(tmp_path)] == ["late"]


def test_scheduled_mode_logs_an_unreadable_generation_once(tmp_path: Path, fake_generation: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock("2026-10-22 21:00")
    monkeypatch.setattr(forward, "current_generation", lambda generation=None: (_ for _ in ()).throw(FileNotFoundError("no current pointer")))
    with pytest.raises(FileNotFoundError):
        forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep)
    lines = forward.read_attempts(tmp_path)
    assert len(lines) == 1 and lines[0]["outcome"] == "failed" and lines[0]["generation"] is None
    assert lines[0]["missing_confirmatory_days_error"].startswith("unavailable")


def test_a_failed_record_leaves_one_line_not_two(tmp_path: Path, fake_generation: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock("2026-10-22 21:00")
    monkeypatch.setattr(forward, "day_frame", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        forward.scheduled_record(tmp_path, ["1101"], code_commit="c" * 40, clock=clock, sleep=clock.sleep)
    assert [line["outcome"] for line in forward.read_attempts(tmp_path)] == ["failed"]


def test_a_tracked_ledger_may_grow_but_code_changes_stay_dirty(tmp_path: Path) -> None:
    import subprocess

    from scripts.record_momentum_forward_day import OUTPUT_PATHSPEC, _code_identity

    def git(*arguments: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True, capture_output=True)

    ledger = tmp_path / OUTPUT_PATHSPEC / "attempts.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{}\n", encoding="utf-8")
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    assert _code_identity(tmp_path)["dirty"] is False
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write("{}\n")
    assert _code_identity(tmp_path)["dirty"] is False
    (tmp_path / "code.py").write_text("x = 2\n", encoding="utf-8")
    assert _code_identity(tmp_path)["dirty"] is True
