"""Durable invocation orchestration over the frozen v1 public day API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core import momentum_forward_v1 as v1
from research_core.momentum_forward_attempts_v2 import Attempt, Checkpoint, read_attempts, recover, root_lock, utc_now

LOGGER = logging.getLogger(__name__)


def run(
    root: Path,
    codes: Callable[[], Sequence[str]],
    *,
    day: str | None = None,
    scheduled: bool = False,
    identity: Callable[[], tuple[str, str | None]],
    workers: int = 1,
    producer_idle: Callable[[], None] | None = None,
    clock: Callable[[], pd.Timestamp] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = 900.0,
    max_wait_seconds: float = 12 * 3600.0,
    checkpoint: Checkpoint | None = None,
) -> Path | None:
    """Start before lazy dependencies; exactly one durable terminal if execution returns.

    Market/day APIs remain v1's public functions. Tests replace those functions with
    synthetic sources. A crash can leave a terminal awaiting safe ledger projection.
    """
    attempt = Attempt(root, requested_day=day, mode="scheduled" if scheduled else "manual", checkpoint=checkpoint)
    entry: dict[str, Any] = {}
    status: dict[str, Any] | None = None
    now = clock or (lambda: cast(pd.Timestamp, pd.Timestamp.now(tz=v1.TAIPEI)))
    try:
        try:
            recover(root)
            read_attempts(root, include_legacy=False)  # fail closed even when no old attempt needs projection
            with root_lock(root, ".attempts-v2-writer.lock") as locked:
                if not locked:
                    entry.update(outcome="refused", reason="recorder busy/unknown: v2 writer lock unavailable")
                    return None
                commit, refusal = identity()
                entry["code_commit"] = commit
                start = now()
                if start.tzinfo is None:
                    raise ValueError("clock must be timezone aware")
                today = str(start.tz_convert(v1.TAIPEI).strftime("%Y-%m-%d"))
                if scheduled and day is not None:
                    raise ValueError("scheduled mode does not accept an explicit date")
                if poll_seconds <= 0 or max_wait_seconds < 0 or workers < 1:
                    raise ValueError("invalid worker/wait bounds")
                if scheduled:
                    entry["target_day"] = today
                # Refusals still observe generation/missing-day metadata, as in v1.
                while True:
                    status = v1.current_generation()
                    entry.update(generation=status["generation"], generation_asof=status["asof"])
                    entry["target_day"] = day or status["asof"] if not scheduled else today
                    busy = None
                    if refusal is None and producer_idle is not None:
                        try:
                            producer_idle()
                        except RuntimeError as error:
                            busy = f"producer busy: {error}"
                    if refusal is not None or (not scheduled and busy is not None):
                        entry.update(outcome="refused", reason=refusal or busy)
                        return None
                    if not scheduled or (status["asof"] >= today and busy is None):
                        break
                    reason = busy or f"generation not refreshed: current {status['generation']} as-of {status['asof']} built {status.get('built_at_utc')}"
                    if now() >= v1.freeze_deadline(today) or (now() - start).total_seconds() + poll_seconds > max_wait_seconds:
                        entry.update(outcome="not_recorded", reason=reason)
                        return None
                    LOGGER.info("Waiting for forward generation: %s", reason)
                    sleep(poll_seconds)
                target = day or status["asof"]
                entry["target_day"] = target
                if day is None and now() >= v1.freeze_deadline(status["asof"]):
                    entry["stale_generation"] = f"current generation as-of {status['asof']} was not refreshed before {v1.freeze_deadline(status['asof'])}"
                destination = root / "days" / f"{target}.parquet"
                existed, had_cohort = destination.exists(), (root / "cohort.json").exists()
                try:
                    path = v1.record_day(root, codes(), day=day, code_commit=commit, workers=workers, now=now)
                except FileExistsError as error:
                    entry.update(outcome="already_frozen", reason=str(error))
                    if scheduled:
                        return destination
                    raise
                if existed:
                    entry["outcome"] = "cohort_recovered" if not had_cohort else "already_frozen"
                else:
                    frozen = pd.read_parquet(path, columns=["recorded_late"])
                    entry.update(outcome="late" if bool(frozen["recorded_late"].any()) else "on_time", rows=len(frozen))
                return path
        except BaseException as error:
            entry.setdefault("outcome", "failed")
            entry.setdefault("reason", f"{type(error).__name__}: {error}")
            raise
        finally:
            entry["finished_at_utc"] = utc_now()
            # Recovery must never invent missing days by consulting a later generation.
            # Only this live invocation's own generation is eligible for v1 metadata.
            if status is not None:
                try:
                    entry.update(v1.missing_entry(root, status))
                except Exception as error:  # noqa: BLE001 - preserve a terminal even if metadata is unavailable
                    entry["missing_days_error"] = f"{type(error).__name__}: {error}"
            else:
                entry.update(generation=None, generation_asof=None, missing_days_error="unavailable: no generation was read")
            attempt.finish(entry)
    finally:
        attempt.close()


def code_identity(repo: Path) -> tuple[str, str | None]:
    """Lazy CLI identity, after durable start; ignore the producer gitlink."""
    import subprocess

    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True).stdout.strip()

    commit = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all", "--", ".")
    return commit, "uncommitted code: record from a clean commit" if dirty else None
