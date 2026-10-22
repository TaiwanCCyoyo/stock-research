from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import momentum_forward_v1 as forward
from research_core import momentum_only_v1 as study


@pytest.fixture()
def fake_generation(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    status = {"generation": "2026-10-22-20261022T123008Z", "asof": "2026-10-22"}
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
