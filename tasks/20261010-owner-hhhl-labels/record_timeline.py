"""Record, once, the filesystem evidence for the preregistration order of batches 2-5.

The batch files' headers carry handoff labels instead of real dates (see report.md). The order that
matters, preregistration before the owner saw a batch, rests on three timestamps per batch:

  1. when the preregistration file was last modified in the .tmp working directory;
  2. when the batch's chart sets were written there;
  3. when the owner first saved a judgment (`saved_at` in data/owner_labels.json).

Git does not keep (1) and (2), so this script stores them in data/timeline_receipt.zip together with
each file's size and SHA-256, and whether the bytes equal the copy committed in this task. They are
filesystem metadata captured on 2026-10-08: a retrospective record, not cryptographic proof.
(3) can be checked from the archive itself.

  uv run python tasks/20261010-owner-hhhl-labels/record_timeline.py --source <.tmp working directory>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from archive_io import swap_in  # noqa: E402

log = logging.getLogger("record_timeline")
BATCHES = {
    "2": (["label_set_b2"], ["b2"]),
    "3": (["label_set_b3a", "set_b3b"], ["b3a", "b3b"]),
    "4": (["label_set_b4a", "set_b4b"], ["b4a", "b4b"]),
    "5": (["label_set_b5a", "set_b5b"], ["b5a", "b5b"]),
}


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def order_holds(prereg_utc: str, chart_set_utcs: list[str], first_save_utc: str) -> bool:
    """Preregistration before every chart set, and every chart set before the owner's first save."""
    sets = [_utc(x) for x in chart_set_utcs]
    return bool(sets) and _utc(prereg_utc) < min(sets) and max(sets) < _utc(first_save_utc)


def _read(path: Path) -> bytes:
    return path.read_bytes()


def stamp(path: Path) -> tuple[dict, bytes]:
    """Content and time of one file version: refuse if the file changed while it was being read."""
    before = path.stat()
    data = _read(path)
    after = path.stat()
    same = (before.st_ino, before.st_mtime_ns, before.st_size) == (after.st_ino, after.st_mtime_ns, after.st_size)
    if not same or len(data) != after.st_size:
        raise SystemExit(f"{path.name} changed while it was being recorded; nothing written")
    row = {
        "file": path.name,
        "modified_utc": datetime.fromtimestamp(after.st_mtime, UTC).isoformat(timespec="milliseconds"),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    return row, data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    labels = json.loads((HERE / "data" / "owner_labels.json").read_text(encoding="utf-8"))["pages"]
    rows = {}
    for batch, (sets, pages) in BATCHES.items():
        prereg, prereg_bytes = stamp(a.source / f"batch{batch}-preregistration.md")
        prereg["equals_committed_copy"] = (HERE / f"batch{batch}-preregistration.md").read_bytes() == prereg_bytes
        first = min(d["saved_at"] for p in pages for d in labels[p]["documents"] if d.get("saved_at"))
        rows[batch] = {
            "preregistration": prereg,
            "chart_sets": [stamp(a.source / f"{s}.json")[0] for s in sets],
            "owner_first_save_utc": first,
        }
        order_ok = order_holds(prereg["modified_utc"], [x["modified_utc"] for x in rows[batch]["chart_sets"]], first)
        rows[batch]["order_holds"] = order_ok
        log.info("batch %s: prereg %s, first save %s, order holds %s", batch, prereg["modified_utc"], first, order_ok)
    from recompute import pinned_zip

    shown = pinned_zip("chart_sets.zip")
    problems = []
    for batch, row in rows.items():
        if not row["preregistration"]["equals_committed_copy"]:
            problems.append(f"batch {batch}: preregistration differs from the committed copy")
        if not row["order_holds"]:
            problems.append(f"batch {batch}: order does not hold")
        for x in row["chart_sets"]:
            if hashlib.sha256(shown[f"sets/{x['file']}"]).hexdigest() != x["sha256"]:
                problems.append(f"batch {batch}: {x['file']} differs from chart_sets.zip")
    if problems:
        raise SystemExit("timeline receipt not written: " + "; ".join(problems))
    receipt = {
        "schema": "owner-hhhl-timeline-receipt.v1",
        "recorded_on": "2026-10-08",
        "source_dir": a.source.as_posix(),
        "nature": "filesystem modification times; retrospective evidence, not cryptographic proof",
        "batches": rows,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("receipt.json", json.dumps(receipt, ensure_ascii=False, indent=1))
    swap_in({HERE / "data" / "timeline_receipt.zip": buf.getvalue()})


if __name__ == "__main__":
    main()
