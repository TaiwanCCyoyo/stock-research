"""Make a fresh, bounded raw-input snapshot from already-exposed atlas tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from research_core.artifact_store import copy_verified, describe_file, file_digest, publish_noreplace, read_json, safe_path, verify_files, write_json

RAW_COLUMNS = ["asof_date", "RawOpen", "RawHigh", "RawLow", "RawClose", "VolumeLots"]


def prepare_inputs(*, tables: Path, actions: Path, cases: Path, output: Path) -> dict[str, Any]:
    """Never read labels or overwrite an existing input snapshot."""
    tables, actions, cases, output = map(safe_path, (tables, actions, cases, output))
    if output.exists():
        raise FileExistsError(output)
    cases_bytes = cases.read_bytes()
    cases_hash = hashlib.sha256(cases_bytes).hexdigest()
    selected_cases = json.loads(cases_bytes)
    if not isinstance(selected_cases, list) or not selected_cases:
        raise ValueError("explicit nonempty cases list required")
    codes = sorted({str(case["code"]) for case in selected_cases})
    if any(not code.isdigit() for code in codes):
        raise ValueError("numeric security codes required")
    sources = {code: safe_path(tables / f"{code}.parquet") for code in codes}
    before = {code: file_digest(path) for code, path in sources.items()}
    actions_hash = file_digest(actions)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = safe_path(output.parent / f".{output.name}.prepare.lock")
    with lock.open("x"):
        pass  # Acquisition precedes finally; a competing writer's lock is never ours.
    try:
        if safe_path(output).exists():
            raise FileExistsError(output)
        staging = safe_path(output.parent / f".staging-prepare-{uuid.uuid4().hex}")
        staging.mkdir()
        frames: list[pd.DataFrame] = []
        for code, path in sources.items():
            frame = pd.read_parquet(path, columns=RAW_COLUMNS).rename(
                columns={"asof_date": "Date", "VolumeLots": "Volume", **{f"Raw{name}": name for name in ("Open", "High", "Low", "Close")}}
            )
            frame["Date"] = pd.to_datetime(frame["Date"])
            frame.insert(0, "Code", code)
            frames.append(frame)
        if any(not frame["Date"].equals(frames[0]["Date"]) for frame in frames):
            raise ValueError("source tables must share the explicit original atlas calendar")
        prices_path, calendar_path = staging / "prices.parquet", staging / "calendar.json"
        pd.concat(frames, ignore_index=True).to_parquet(prices_path, index=False)
        dates = frames[0]["Date"]
        write_json(
            calendar_path, {"basis": "original_atlas_explicit_calendar_not_reconstructed_exchange_calendar", "dates": [day.date().isoformat() for day in dates]}
        )
        copy_verified(actions, staging / "actions.parquet", actions_hash)
        copy_verified(cases, staging / "cases.json", cases_hash)

        def verify_sources() -> None:
            if {code: file_digest(path) for code, path in sources.items()} != before:
                raise ValueError("atlas source moved; incomplete staging retained")
            if file_digest(cases) != cases_hash or file_digest(actions) != actions_hash:
                raise ValueError("cases or actions source moved; incomplete staging retained")

        verify_sources()
        receipt: dict[str, Any] = {
            "schema": "derived-cache-inputs.v1",
            "complete": True,
            "codes": codes,
            "source_table_hashes": before,
            "source_table_paths": {code: str(path) for code, path in sources.items()},
            "source_actions_sha256": actions_hash,
            "source_cases_sha256": cases_hash,
            "read_columns": RAW_COLUMNS,
            "rows": sum(len(frame) for frame in frames),
            "artifacts": [describe_file(staging, path) for path in (prices_path, calendar_path, staging / "actions.parquet", staging / "cases.json")],
        }
        verify_files(staging, receipt["artifacts"])
        receipt_path = staging / "input-receipt.json"
        write_json(receipt_path, receipt)
        receipt_hash = file_digest(receipt_path)
        if read_json(receipt_path) != receipt:
            raise ValueError("prepared input receipt differs from computed evidence")
        verify_files(staging, receipt["artifacts"])
        expected_names = {row["path"] for row in receipt["artifacts"]} | {"input-receipt.json"}
        if {safe_path(path).name for path in staging.iterdir()} != expected_names:
            raise ValueError("prepared staging contains unexpected artifacts")
        verify_sources()
        verify_files(staging, receipt["artifacts"])
        if file_digest(receipt_path) != receipt_hash:
            raise ValueError("prepared input receipt changed before publication")
        if safe_path(output).exists():
            raise FileExistsError(output)
        publish_noreplace(staging, output)
        return receipt
    finally:
        lock.unlink()  # Remove only this invocation's exclusively acquired lock.
        # Keep failed staging untouched for diagnosis and a fresh same-output retry.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tables", "actions", "cases", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_inputs(tables=args.tables, actions=args.actions, cases=args.cases, output=args.output), ensure_ascii=False))  # noqa: T201 - CLI receipt on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
