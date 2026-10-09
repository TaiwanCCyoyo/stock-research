"""One fixed descriptive v4 batch; never mutate atlas, factors, or prior attempts."""

from __future__ import annotations

import argparse
import json
import logging
import math
import multiprocessing
import os
import platform
import random
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Generator, Sequence
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.feature_atlas_dataset import verify_dataset
from research_core.hhhl_probability import OUTCOME_COLUMNS
from research_core.hhhl_rule_source import load_source_texts
from research_core.hhhl_v4_landmark_view import AUDIT_LANDMARK_COLUMNS, attach_l20_audit
from research_core.hhhl_v4_outcomes import first_decision_outcomes, landmark_record
from research_core.hhhl_v4_source import DATASET_ID, FIXED_INPUT_SHA256, OHLC_COLUMNS, RAW_COLUMNS, RULE_ID, load_v4_components
from research_core.hhhl_v4_summary import landmark_census, summarize_v4
from research_core.jobs import confined, file_digest
from scripts.validate_hhhl_v4_source import read_inputs, write_json

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
WINDOW = ("2019-01-02", "2026-08-14")
SEED = 20261010
MAX_RUNTIME_SECONDS = 3600
PENDING_MANIFEST = "manifest.pending.json"
ATTEMPT_START = "attempt-start.json"
MAX_ATTEMPT_BYTES = 65_536
KEYS = ["security_id", "asof_date", "year", "base_eligible", "eligibility_reason", "regime", "industry_ref"]
OUTCOMES = [f"{basis}_{column}" for basis in ("adjusted", "atlas") for column in OUTCOME_COLUMNS]
INPUT_COLUMNS = list(dict.fromkeys([*KEYS, *RAW_COLUMNS, "Close", *OUTCOME_COLUMNS]))
BASE_COLUMNS = [*KEYS, "anchor_date", "breakout_date", "adjusted_close", "atlas_close", *OUTCOMES]
EVENT_COLUMNS = [
    *BASE_COLUMNS,
    "event_id",
    "rule_id",
    "code",
    "calendar_index",
    "detector_index",
    "cat",
    "scale",
    "pattern",
    "limit_up",
    "big_hhhl",
    "liquid",
    "vx",
    "hz_top",
    "Z2",
    "restart_date",
    "leg_start_date",
    "has_old",
    "has_recent_far",
    "bonus_levels",
    "blocking",
    "pivot_sequence",
    "structure_missing_ohlc",
]
LANDMARK_COLUMNS = list(AUDIT_LANDMARK_COLUMNS)


def _verify_fixed_input_identity(inputs: Path) -> None:
    for relative, expected in FIXED_INPUT_SHA256.items():
        path = confined(inputs, relative)
        if not path.is_file() or file_digest(path) != expected:
            raise ValueError(f"unauthorized fixed input SHA-256: {relative}")


def read_fixed_inputs(inputs: Path) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Bind this experiment to the original preparation, not a self-signed receipt."""
    _verify_fixed_input_identity(inputs)
    result = read_inputs(inputs)
    _verify_fixed_input_identity(inputs)
    return result


@lru_cache(maxsize=1)
def worker_inputs(sources: str, inputs: str) -> tuple[Any, Any, pd.DataFrame]:
    """Immutable source and factor snapshot, loaded once per bounded worker."""
    detect, _, _, prepare = load_v4_components(load_source_texts(Path(sources), RULE_ID))
    factors, _, _ = read_fixed_inputs(Path(inputs))
    return detect, prepare, factors


def scan_frame(frame: pd.DataFrame, factors: pd.DataFrame, detect: Any, prepare: Any) -> dict[str, Any]:
    """Map the original valid-row detector to the unfilled common calendar."""
    if frame.empty or frame["security_id"].nunique() != 1:
        raise ValueError("one nonempty security table required")
    dates = pd.to_datetime(frame["asof_date"])
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("invalid shared calendar")
    date_strings = dates.dt.strftime("%Y-%m-%d")
    if date_strings.iloc[0] != WINDOW[0] or date_strings.iloc[-1] != WINDOW[1]:
        raise ValueError("unauthorized date range")
    security = str(frame["security_id"].iloc[0])
    code = security.split(":", 1)[1]
    missing_ohlc = cast(pd.Series, frame.loc[:, list(OHLC_COLUMNS)].isna().any(axis=1))
    if missing_ohlc.all():
        if cast(pd.Series, frame["base_eligible"]).eq(True).any():
            raise ValueError("eligible anchors without any usable OHLC")
        bars = pd.DataFrame()
        events: list[dict[str, Any]] = []
        adjusted = np.full(len(frame), np.nan)
        preparation = {"used_rows": 0, "dropped_missing_ohlc_rows": len(frame), "status": "no_usable_ohlc"}
        indices = np.array([], dtype=int)
    else:
        bars = prepare(frame, factors, code, WINDOW[1])
        preparation = bars.attrs["preparation_metadata"]
        indices = pd.DatetimeIndex(dates).get_indexer(pd.to_datetime(bars["asof_date"]))
        if (indices < 0).any() or len(np.unique(indices)) != len(indices):
            raise ValueError("detector dates not mapped one-to-one to shared calendar")
        events = detect(bars)
        adjusted = np.full(len(frame), np.nan)
        adjusted[indices] = bars["Close"].to_numpy(float)
    outcomes = first_decision_outcomes(adjusted)
    base = frame.loc[:, KEYS].copy()
    base["anchor_date"] = date_strings
    base["breakout_date"] = date_strings
    base["adjusted_close"] = adjusted
    base["atlas_close"] = frame["Close"].to_numpy(float)
    for column in OUTCOME_COLUMNS:
        base[f"adjusted_{column}"] = outcomes[column].to_numpy()
        base[f"atlas_{column}"] = frame[column].to_numpy()
    event_positions = {int(event["t"]) for event in events}
    pattern_positions = {int(event["t"]) for event in events if event["pattern"]}
    controls = []
    if len(bars):
        closes = bars["Close"].to_numpy(float)
        volumes = bars["VolumeLots"].to_numpy(float)
        prior_high = bars["Close"].shift(1).rolling(20, min_periods=20).max().to_numpy(float)
        prior_volume = cast(pd.Series, bars["VolumeLots"].shift(1).rolling(20, min_periods=1).mean()).to_numpy(float)
        high_volume = (closes > prior_high) & (prior_volume > 0) & (volumes >= 1.5 * prior_volume)
        for t in np.flatnonzero(high_volume):
            if int(t) not in pattern_positions:
                controls.append({**base.iloc[int(indices[t])].to_dict(), "control_no_event": int(t) not in event_positions, "control_no_pattern": True})
    records = []
    landmarks = []
    for event in events:
        t = int(event["t"])
        calendar_t = int(indices[t])
        row = base.iloc[calendar_t].to_dict()
        z2 = float(next(p for p in reversed(event["seq"]) if p["k"] == "L")["p"])
        bonus = event["bonus_levels"]
        if any(level["age"] not in ("old", "recent_far") for level in bonus):
            raise ValueError("unexpected frozen bonus age")
        event_id = f"{RULE_ID}:{security}:{date_strings.iloc[calendar_t]}"
        rs = int(indices[int(event["restart"])])
        record = {
            **row,
            "event_id": event_id,
            "rule_id": RULE_ID,
            "code": code,
            "calendar_index": calendar_t,
            "detector_index": t,
            **{key: event[key] for key in ("cat", "scale", "pattern", "limit_up", "big_hhhl", "liquid", "vx", "hz_top")},
            "Z2": z2,
            "restart_date": date_strings.iloc[rs],
            "leg_start_date": date_strings.iloc[int(indices[int(event["leg_start"])])],
            "has_old": any(level["age"] == "old" for level in bonus),
            "has_recent_far": any(level["age"] == "recent_far" for level in bonus),
            "bonus_levels": json.dumps(bonus),
            "blocking": json.dumps(event["blocking"]),
            "pivot_sequence": json.dumps([{**p, "date": date_strings.iloc[int(indices[p["i"]])]} for p in event["seq"]]),
            "structure_missing_ohlc": int(missing_ohlc.iloc[rs : calendar_t + 1].sum()),
        }
        records.append(record)
        if event["pattern"]:
            for landmark in (10, 20, 40):
                state = landmark_record(adjusted, calendar_t, landmark, z2, bonus)
                landmark_index = state["landmark_index"]
                landmark_date = date_strings.iloc[int(landmark_index)] if landmark_index is not None else None
                lm = {
                    **{key: record[key] for key in ("event_id", "security_id", "base_eligible", "breakout_date", "year")},
                    **state,
                    "anchor_date": landmark_date,
                    "landmark_date": landmark_date,
                    "Z2": z2,
                    "target_close": 2 * adjusted[calendar_t],
                    "deadline_index": calendar_t + 126,
                }
                for age in ("old", "recent_far"):
                    index = lm.get(f"first_cross_{age}_index")
                    lm[f"first_cross_{age}_date"] = date_strings.iloc[int(index)] if index is not None else None
                landmarks.append(lm)
    return {
        "base": base,
        "events": records,
        "controls": controls,
        "landmarks": landmarks,
        "coverage": {
            "security_id": security,
            "rows": len(frame),
            "first_date": date_strings.iloc[0],
            "last_date": date_strings.iloc[-1],
            "missing_adjusted_close": int(np.isnan(adjusted).sum()),
            "raw_close_present_dropped_ohlc": int((missing_ohlc & frame["RawClose"].notna()).sum()),
            "events": len(records),
            "preparation": preparation,
        },
    }


def scan_file(args: tuple[Path, str, str, str, int]) -> dict[str, Any]:
    path, sources, inputs, expected_digest, rows = args
    if file_digest(path) != expected_digest:
        raise ValueError(f"source table changed: {path}")
    frame = pd.read_parquet(path, columns=INPUT_COLUMNS).reset_index(drop=True)
    if len(frame) != rows:
        raise ValueError("source row count mismatch")
    detect, prepare, factors = worker_inputs(sources, inputs)
    result = scan_frame(frame, factors, detect, prepare)
    result["coverage"]["source_sha256"] = expected_digest
    return result


def batches(
    args: Sequence[tuple[Any, ...]],
    workers: int,
    *,
    deadline: float | None = None,
    worker: Callable[[tuple[Any, ...]], dict[str, Any]] | None = None,
    clock: Callable[[], float] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Yield ordered worker results and terminate this pool at the fixed deadline."""
    if workers not in (1, 4):
        raise ValueError("one or four fixed workers required")
    if not args:
        return

    monotonic = clock or time.monotonic
    fixed_deadline = deadline if deadline is not None else monotonic() + MAX_RUNTIME_SECONDS
    worker_fn = worker if worker is not None else cast(Callable[[tuple[Any, ...]], dict[str, Any]], scan_file)
    pool = multiprocessing.get_context("spawn").Pool(processes=workers)
    completed = False
    LOGGER.info("Starting fixed worker pool workers=%d tasks=%d", workers, len(args))
    try:
        for start in range(0, len(args), workers):
            pending = [pool.apply_async(worker_fn, (item,)) for item in args[start : start + workers]]
            for result in pending:
                remaining = fixed_deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("fixed worker phase exceeded its monotonic deadline")
                try:
                    yield result.get(timeout=remaining)
                except multiprocessing.TimeoutError as exc:
                    raise TimeoutError("fixed worker phase exceeded its monotonic deadline") from exc
        if monotonic() > fixed_deadline:
            raise TimeoutError("fixed worker phase exceeded its monotonic deadline")
        completed = True
    except GeneratorExit:
        raise
    except BaseException:
        LOGGER.exception("Worker phase aborted; terminating owned pool")
        raise
    finally:
        if completed:
            pool.close()
        else:
            LOGGER.warning("Terminating incomplete owned worker pool")
            pool.terminate()
        pool.join()


def noise_record(base: pd.DataFrame, event: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Original event order is fixed by the parent, independently of worker timing."""
    anchor = event["calendar_index"]
    candidates = [j for j in range(max(0, anchor - 60), min(len(base), anchor + 61)) if j != anchor and bool(base.iloc[j]["base_eligible"])]
    if candidates:
        chosen = rng.choice(candidates)
        return {**base.iloc[chosen].to_dict(), "event_id": event["event_id"], "breakout_date": event["breakout_date"], "calendar_offset": chosen - anchor}
    row = {**base.iloc[anchor].to_dict(), "event_id": event["event_id"], "calendar_offset": None}
    for column in OUTCOMES:
        row[column] = "no_shift_candidate" if "unknown_reason" in column else None
    return row


def _initial_attempt_record(token: str, started_at_utc: str) -> dict[str, Any]:
    return {
        "complete": False,
        "identity_complete": False,
        "code_commit": None,
        "identity": None,
        "attempt_token": token,
        "started_at_utc": started_at_utc,
    }


def _initialize_attempt(output: Path, *, token: str | None = None, started_at_utc: str | None = None) -> dict[str, Any]:
    """Create a new output and durable incomplete evidence before validation."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    token = token or uuid.uuid4().hex
    started_at_utc = started_at_utc or pd.Timestamp.now(tz="UTC").isoformat()
    initial = _initial_attempt_record(token, started_at_utc)
    for name in (ATTEMPT_START, "attempt.json"):
        temporary = output / f".{name}.{token}.tmp"
        destination = output / name
        write_json(temporary, initial)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"refusing to overwrite initial attempt evidence: {destination}")
        temporary.rename(destination)
    LOGGER.info("Initialized incomplete attempt evidence before preflight")
    return initial


def _read_attempt_record(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ATTEMPT_BYTES:
        raise ValueError(f"attempt evidence is missing or exceeds the bounded read size: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"attempt evidence must be an object: {path.name}")
    return value


def _validate_parent_attempt(output: Path, token: str, started_at_utc: str) -> dict[str, Any]:
    """Accept only the exact incomplete output initialized by the public parent."""
    if not output.is_dir() or output.is_symlink():
        raise ValueError("private child output must be the existing parent-owned directory")
    if len(token) != 32 or any(character not in "0123456789abcdef" for character in token):
        raise ValueError("private child requires a valid parent attempt token")
    expected = _initial_attempt_record(token, started_at_utc)
    start = _read_attempt_record(output / ATTEMPT_START)
    current = _read_attempt_record(output / "attempt.json")
    if start != expected or current != expected:
        raise ValueError("output does not contain the matching fresh parent-owned incomplete attempt")
    return expected


def _enrich_attempt(output: Path, initial: dict[str, Any], code_commit: str, identity: dict[str, str]) -> None:
    """Atomically add sealed preflight identity while preserving initial bytes."""
    _validate_parent_attempt(output, initial["attempt_token"], initial["started_at_utc"])
    enriched = {**initial, "code_commit": code_commit, "identity": identity, "identity_complete": True}
    payload = json.dumps(enriched, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(payload.encode("utf-8")) > MAX_ATTEMPT_BYTES:
        raise ValueError("enriched attempt evidence exceeds the bounded write size")
    temporary = output / f".attempt.{initial['attempt_token']}.tmp"
    write_json(temporary, enriched)
    if temporary.stat().st_size > MAX_ATTEMPT_BYTES:
        raise ValueError("temporary enriched attempt evidence exceeds the bounded write size")
    os.replace(temporary, output / "attempt.json")
    LOGGER.info("Sealed preflight identity into incomplete attempt evidence")


def _build(
    dataset: Path,
    task_root: Path,
    inputs: Path,
    output: Path,
    workers: int = 4,
    *,
    started: float | None = None,
    deadline: float | None = None,
    pending_manifest: Path | None = None,
    attempt_token: str | None = None,
    attempt_started_at_utc: str | None = None,
) -> dict[str, Any]:
    if workers not in (1, 4):
        raise ValueError("one or four fixed workers required")
    started = time.monotonic() if started is None else started
    run_deadline = deadline if deadline is not None else started + MAX_RUNTIME_SECONDS
    if attempt_token is not None and (output.is_symlink() or not output.is_dir()):
        raise ValueError("private child requires the existing parent-owned output directory")
    output = output.resolve()
    if attempt_token is None:
        if attempt_started_at_utc is not None:
            raise ValueError("attempt start timestamp requires the private parent token")
        initial_attempt = _initialize_attempt(output)
    else:
        if attempt_started_at_utc is None:
            raise ValueError("private child requires the parent's attempt start timestamp")
        initial_attempt = _validate_parent_attempt(output, attempt_token, attempt_started_at_utc)
    pending = (pending_manifest or output / PENDING_MANIFEST).resolve()
    if pending.parent != output:
        raise ValueError("pending completion receipt must be inside the new output directory")
    if time.monotonic() >= run_deadline:
        raise TimeoutError("fixed budget expired before preflight validation; preserve incomplete attempt")
    verified = verify_dataset(dataset)
    if verified["dataset_id"] != DATASET_ID:
        raise ValueError("unauthorized dataset")
    _, _, receipt = read_fixed_inputs(inputs)
    load_source_texts(task_root / "sources", RULE_ID)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    identity_paths = [
        task_root / "mission.md",
        task_root / "data-contract.md",
        task_root / "sources/hhhl_rule_v4.zip",
        task_root / "sources/definition-response.zip",
        ROOT / "uv.lock",
        ROOT / "pyproject.toml",
        Path(__file__),
        ROOT / "research_core/hhhl_v4_outcomes.py",
        ROOT / "research_core/hhhl_v4_summary.py",
        ROOT / "research_core/hhhl_v4_landmark_view.py",
        ROOT / "research_core/hhhl_v4_source.py",
        ROOT / "research_core/hhhl_rule_source.py",
        ROOT / "research_core/hhhl_probability.py",
        ROOT / "research_core/feature_atlas_dataset.py",
        ROOT / "research_core/jobs.py",
        ROOT / "research_core/windows_process_job.py",
        ROOT / "scripts/validate_hhhl_v4_source.py",
        inputs / "input-receipt.json",
        inputs / receipt["factor_snapshot"]["path"],
        inputs / receipt["validation_cases"]["path"],
        dataset / "manifest.json",
    ]
    before = {str(p): file_digest(p) for p in identity_paths}
    code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--ignore-submodules=all"], cwd=ROOT, text=True).strip():
        raise ValueError("commit sealed code/definitions before reading outcomes")
    _enrich_attempt(output, initial_attempt, code_commit, before)
    (output / "baseline").mkdir()
    entries = sorted(manifest["tables"], key=lambda entry: entry["security_id"])
    args = [(confined(dataset, e["path"]), str(task_root / "sources"), str(inputs), e["sha256"], e["rows"]) for e in entries]
    events, controls, noises, landmarks, coverage, base_parts = [], [], [], [], [], []
    rng = random.Random(SEED)
    expected_dates: list[str] | None = None
    worker_results = batches(args, workers, deadline=run_deadline)
    try:
        for n, (entry, result) in enumerate(zip(entries, worker_results, strict=True), 1):
            base = result["base"]
            current_dates = base["anchor_date"].tolist()
            if expected_dates is None:
                expected_dates = current_dates
            elif current_dates != expected_dates:
                raise ValueError("security calendars differ")
            if not base["security_id"].eq(entry["security_id"]).all():
                raise ValueError("security identity mismatch")
            base.to_parquet(output / "baseline" / f"{n:04}.parquet", index=False)
            base_parts.append(base.loc[base["base_eligible"].eq(True), ["security_id", "year", "base_eligible", "anchor_date", "breakout_date", *OUTCOMES]])
            events.extend(result["events"])
            controls.extend(result["controls"])
            landmarks.extend(result["landmarks"])
            coverage.append(result["coverage"])
            for event in sorted(result["events"], key=lambda e: e["breakout_date"]):
                if event["pattern"] and event["base_eligible"]:
                    noises.append(noise_record(base, event, rng))
            if n % 100 == 0 or n == len(entries):
                LOGGER.info("Progress stocks=%d/%d events=%d elapsed=%.1fs", n, len(entries), len(events), time.monotonic() - started)
            if time.monotonic() >= run_deadline:
                raise TimeoutError("fixed budget exceeded; preserve incomplete attempt")
    finally:
        worker_results.close()
    if time.monotonic() >= run_deadline:
        raise TimeoutError("fixed budget exceeded after worker phase; preserve incomplete attempt")
    event_frame = pd.DataFrame(events, columns=pd.Index(EVENT_COLUMNS))
    control_frame = pd.DataFrame(controls, columns=pd.Index([*BASE_COLUMNS, "control_no_event", "control_no_pattern"]))
    noise_frame = pd.DataFrame(noises, columns=pd.Index([*BASE_COLUMNS, "event_id", "calendar_offset"]))
    landmark_frame = pd.DataFrame(landmarks, columns=pd.Index(LANDMARK_COLUMNS))
    baseline = pd.concat(base_parts, ignore_index=True)
    if len(events) != event_frame["event_id"].nunique():
        raise ValueError("duplicate event key")
    summaries = summarize_v4(event_frame, baseline, control_frame, noise_frame, landmark_frame)
    if len(summaries) != 1080:
        raise ValueError("fixed comparison inventory mismatch")
    if time.monotonic() >= run_deadline:
        raise TimeoutError("fixed budget exceeded before output serialization; preserve incomplete attempt")
    for name, frame in (("events", event_frame), ("controls", control_frame), ("noise", noise_frame), ("landmarks", landmark_frame)):
        frame.to_parquet(output / f"{name}.parquet", index=False)
    audit = event_frame.sort_values(["security_id", "breakout_date"]).loc[lambda f: f["pattern"] & f["base_eligible"]].head(10)
    attach_l20_audit(audit, landmark_frame).to_parquet(output / "audit-sample.parquet", index=False)
    write_json(output / "summaries.json", summaries)
    write_json(output / "coverage.json", coverage)
    census = [
        {"landmark": landmark, "status": status, "eligible": eligible, "events": len(group), "securities": int(group["security_id"].nunique())}
        for landmark in (10, 20, 40)
        for status in ("active", "early_hit", "early_failed", "unknown")
        for eligible in (True, False)
        for group in [
            landmark_frame.loc[(landmark_frame["landmark"] == landmark) & (landmark_frame["status"] == status) & (landmark_frame["base_eligible"] == eligible)]
        ]
    ]
    discordance = []
    for horizon in (63, 126):
        a, b = event_frame[f"adjusted_label_{horizon}"], event_frame[f"atlas_label_{horizon}"]
        same = a.eq(b) | (a.isna() & b.isna())
        subset = event_frame.loc[
            ~same,
            [
                "event_id",
                "base_eligible",
                f"adjusted_label_{horizon}",
                f"atlas_label_{horizon}",
                f"adjusted_unknown_reason_{horizon}",
                f"atlas_unknown_reason_{horizon}",
            ],
        ].copy()
        subset["difference_reason"] = np.where(
            subset[f"adjusted_label_{horizon}"].notna() & subset[f"atlas_label_{horizon}"].isna(),
            "adjusted_first_decision_known_atlas_unknown",
            np.where(subset[f"adjusted_label_{horizon}"].isna(), "adjusted_unknown_atlas_known", "different_price_basis_threshold"),
        )
        subset.to_parquet(output / f"label-discordance-{horizon}.parquet", index=False)
        discordance.append({
            "horizon": horizon,
            "different_events": len(subset),
            "eligible_different_events": int(subset["base_eligible"].eq(True).sum()),
            "reasons": subset["difference_reason"].value_counts().to_dict(),
        })
    write_json(
        output / "diagnostics.json",
        {
            "landmark_census": census,
            "label_discordance": discordance,
            "landmark_reason_census": landmark_census(landmark_frame),
        },
    )
    if {str(p): file_digest(p) for p in identity_paths} != before:
        raise ValueError("declared inputs/code changed during execution; not complete")
    for entry in entries:
        if file_digest(confined(dataset, entry["path"])) != entry["sha256"]:
            raise ValueError("source table changed during execution; not complete")
    artifacts = {
        str(p.relative_to(output)).replace("\\", "/"): {"sha256": file_digest(p), "bytes": p.stat().st_size} for p in sorted(output.rglob("*")) if p.is_file()
    }
    result = {
        "schema_version": "hhhl-probability.v4",
        "phase": "descriptive_provisional",
        "rule": RULE_ID,
        "complete": True,
        "code_commit": code_commit,
        "completed_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_dataset_id": DATASET_ID,
        "source": str(dataset),
        "verified_input": verified,
        "window": WINDOW,
        "identity": before,
        "factor_input": receipt,
        "runtime": {"python": platform.python_version(), "platform": platform.platform(), "pandas": pd.__version__, "numpy": np.__version__},
        "workers": workers,
        "noise_seed": SEED,
        "counts": {
            "securities": len(entries),
            "calendar_sessions": len(expected_dates or []),
            "rows": sum(e["rows"] for e in entries),
            "events": len(events),
            "true_patterns": int(event_frame["pattern"].eq(True).sum()),
            "baseline_eligible": len(baseline),
            "controls_no_event": int(control_frame["control_no_event"].eq(True).sum()),
            "controls_no_pattern": len(controls),
            "noise": len(noises),
            "landmarks": len(landmarks),
            "comparisons": len(summaries),
        },
        "elapsed_seconds": time.monotonic() - started,
        "artifacts": artifacts,
        "limitations": [
            "current-reference universe, not PIT",
            "exposed development period, not confirmation",
            "reference-factor prices, not cash total return",
            "repeated events and market correlation, not IID",
            "fixed coarse landmark bins, not causal effect",
            "no account strategy or stops evaluated",
        ],
    }
    if time.monotonic() >= run_deadline:
        raise TimeoutError("fixed budget exceeded before completion; preserve incomplete attempt")
    if pending.exists():
        raise FileExistsError(f"pending completion receipt already exists: {pending}")
    write_json(pending, result)
    return result


def _interrupt_owned_tree(process: subprocess.Popen[Any]) -> None:
    """Stop only the child process tree created by _supervise_child()."""
    if sys.platform == "win32":
        raise RuntimeError("Windows tree teardown requires the owned Job Object, never a leader PID")

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        LOGGER.error("owned process did not exit after process-group kill pid=%d", process.pid)
        raise


def _supervise_child(
    command: list[str],
    deadline: float,
    *,
    clock: Callable[[], float] | None = None,
    waiter: Callable[[subprocess.Popen[Any], float], int] | None = None,
) -> int:
    """Run one isolated child and enforce the caller's absolute monotonic deadline."""
    monotonic = clock or time.monotonic
    from research_core.windows_process_job import WindowsProcessJob

    job = WindowsProcessJob() if sys.platform == "win32" else None
    process: subprocess.Popen[Any] | None = None
    try:
        process = job.start(command, ROOT) if job is not None else subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, start_new_session=True)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("fixed budget expired while starting the supervised build")
        status = waiter(process, remaining) if waiter is not None else process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        LOGGER.error("Supervised build exceeded its absolute deadline; stopping owned process tree")
        if process is not None and job is None:
            _interrupt_owned_tree(process)
        raise TimeoutError("supervised child exceeded the absolute deadline; preserve incomplete attempt") from exc
    except BaseException:
        if process is not None and job is None:
            _interrupt_owned_tree(process)
        raise
    else:
        if status != 0 and job is None:
            _interrupt_owned_tree(process)
        return status
    finally:
        if job is not None:
            try:
                job.terminate_and_confirm()
                if process is not None:
                    process.wait(timeout=5)
            finally:
                job.close()


def _finalize_pending_receipt(
    output: Path,
    deadline: float,
    *,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Validate the child receipt and atomically publish it as the canonical manifest."""
    monotonic = clock or time.monotonic
    pending = output / PENDING_MANIFEST
    manifest_path = output / "manifest.json"
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired before checking the canonical manifest path")
    if manifest_path.exists() or manifest_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite completed manifest: {manifest_path}")
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired before checking the pending receipt path")
    if not pending.is_file() or pending.is_symlink():
        raise ValueError("supervised child did not leave a regular pending completion receipt")
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired before reading the pending receipt")
    pending_bytes = pending.stat().st_size
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired while checking the pending receipt size")
    if pending_bytes > 1_000_000:
        raise ValueError("pending completion receipt exceeds the bounded read size")
    receipt = json.loads(pending.read_text(encoding="utf-8"))
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired while reading the pending receipt")
    required = {
        "schema_version",
        "phase",
        "rule",
        "complete",
        "code_commit",
        "completed_at_utc",
        "source_dataset_id",
        "source",
        "verified_input",
        "window",
        "identity",
        "factor_input",
        "runtime",
        "workers",
        "noise_seed",
        "counts",
        "elapsed_seconds",
        "artifacts",
        "limitations",
    }
    if not isinstance(receipt, dict) or not required.issubset(receipt):
        raise ValueError("pending completion receipt is missing required manifest fields")
    if receipt["schema_version"] != "hhhl-probability.v4" or receipt["phase"] != "descriptive_provisional" or receipt["complete"] is not True:
        raise ValueError("pending completion receipt is not a complete v4 manifest")
    if not isinstance(receipt["identity"], dict) or not isinstance(receipt["runtime"], dict):
        raise ValueError("pending completion receipt has invalid identity/runtime metadata")
    counts = receipt["counts"]
    if not isinstance(counts, dict) or counts.get("comparisons") != 1080:
        raise ValueError("pending completion receipt has an invalid fixed comparison count")
    elapsed = receipt["elapsed_seconds"]
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0 or elapsed > MAX_RUNTIME_SECONDS or not math.isfinite(elapsed):
        raise ValueError("pending completion receipt has invalid elapsed time")
    artifacts = receipt["artifacts"]
    if not isinstance(artifacts, dict) or not {"attempt.json", ATTEMPT_START}.issubset(artifacts):
        raise ValueError("pending completion receipt has no attempt artifact inventory")
    if {"manifest.json", PENDING_MANIFEST} & artifacts.keys():
        raise ValueError("pending completion receipt inventories a manifest as its own artifact")
    for relative, descriptor in artifacts.items():
        if monotonic() >= deadline:
            raise TimeoutError("fixed budget expired while validating pending artifact metadata")
        if not isinstance(relative, str) or not isinstance(descriptor, dict):
            raise ValueError("pending completion receipt has an invalid artifact descriptor")
        normalized_parts = relative.replace("\\", "/").split("/")
        windows_path = PureWindowsPath(relative)
        byte_count = descriptor.get("bytes")
        digest = descriptor.get("sha256")
        if (
            not relative
            or Path(relative).is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or any(part in ("", ".", "..") for part in normalized_parts)
            or isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
        ):
            raise ValueError(f"pending completion receipt artifact is invalid: {relative}")
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired before reading the incomplete attempt")
    attempt_path = output / "attempt.json"
    attempt = _read_attempt_record(attempt_path)
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired while reading the incomplete attempt")
    initial_path = output / ATTEMPT_START
    initial = _read_attempt_record(initial_path)
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired while reading the initial attempt snapshot")
    token = attempt.get("attempt_token")
    started_at_utc = attempt.get("started_at_utc")
    if not isinstance(token, str) or not isinstance(started_at_utc, str):
        raise ValueError("pending completion receipt attempt has invalid start identity")
    if (
        initial != _initial_attempt_record(token, started_at_utc)
        or attempt.get("complete") is not False
        or attempt.get("identity_complete") is not True
        or attempt.get("identity") != receipt["identity"]
        or attempt.get("code_commit") != receipt["code_commit"]
    ):
        raise ValueError("pending completion receipt does not match the incomplete attempt identity")
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired before publishing the canonical manifest")
    pending.rename(manifest_path)
    return receipt


def _supervise_build(
    command: list[str],
    output: Path,
    deadline: float,
    *,
    clock: Callable[[], float] | None = None,
    waiter: Callable[[subprocess.Popen[Any], float], int] | None = None,
) -> dict[str, Any]:
    """Finalize only after a successful child exit and valid pending receipt."""
    monotonic = clock or time.monotonic
    status = _supervise_child(command, deadline, clock=monotonic, waiter=waiter)
    if status != 0:
        raise RuntimeError(f"supervised build child exited with status {status}; preserve incomplete attempt")
    if monotonic() >= deadline:
        raise TimeoutError("fixed budget expired after child exit; preserve pending receipt")
    return _finalize_pending_receipt(output, deadline, clock=monotonic)


def build(dataset: Path, task_root: Path, inputs: Path, output: Path, workers: int = 4) -> dict[str, Any]:
    """Supervise all verification, computation, serialization, and hashing in one child."""
    if workers not in (1, 4):
        raise ValueError("one or four fixed workers required")
    started = time.monotonic()
    deadline = started + MAX_RUNTIME_SECONDS
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output already exists; preserving prior attempt: {output}")
    output = output.resolve()
    attempt_token = uuid.uuid4().hex
    attempt_started_at_utc = pd.Timestamp.now(tz="UTC").isoformat()
    _initialize_attempt(output, token=attempt_token, started_at_utc=attempt_started_at_utc)
    if time.monotonic() >= deadline:
        raise TimeoutError("fixed budget expired before supervised child startup")
    command = [
        sys.executable,
        "-m",
        "scripts.build_hhhl_v4_probability",
        "--dataset",
        str(dataset.resolve()),
        "--task-root",
        str(task_root.resolve()),
        "--inputs",
        str(inputs.resolve()),
        "--output",
        str(output),
        "--workers",
        str(workers),
        "--_child",
        "--_started",
        repr(started),
        "--_deadline",
        repr(deadline),
        "--_attempt-token",
        attempt_token,
        "--_attempt-started-at-utc",
        attempt_started_at_utc,
    ]
    LOGGER.info("Launching supervised v4 child workers=%d deadline_seconds=%d", workers, MAX_RUNTIME_SECONDS)
    return _supervise_build(command, output, deadline)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("dataset", "task-root", "inputs", "output"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 4), default=4)
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_started", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--_deadline", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--_attempt-token", help=argparse.SUPPRESS)
    parser.add_argument("--_attempt-started-at-utc", help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args._child:
            if args._started is None or args._deadline is None or args._attempt_token is None or args._attempt_started_at_utc is None:
                parser.error("internal child mode requires parent start, deadline, and attempt identity")
            _build(
                args.dataset,
                args.task_root,
                args.inputs,
                args.output,
                args.workers,
                started=args._started,
                deadline=args._deadline,
                pending_manifest=args.output / PENDING_MANIFEST,
                attempt_token=args._attempt_token,
                attempt_started_at_utc=args._attempt_started_at_utc,
            )
            LOGGER.info("Child finished; pending receipt awaits parent finalization")
            return 0
        if any(value is not None for value in (args._started, args._deadline, args._attempt_token, args._attempt_started_at_utc)):
            parser.error("internal start/deadline/attempt identity are only valid in child mode")
        result = build(args.dataset, args.task_root, args.inputs, args.output, args.workers)
    except (ValueError, OSError, TimeoutError, KeyError, RuntimeError, subprocess.SubprocessError):
        LOGGER.exception("V4 execution incomplete; preserve evidence, inputs untouched")
        return 1
    print(json.dumps({"complete": result["complete"], "counts": result["counts"], "elapsed_seconds": result["elapsed_seconds"]}))  # noqa: T201 - CLI evidence
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
