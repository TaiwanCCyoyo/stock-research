"""Verify the `owner-hhhl-labels.v1` archive and recompute every published batch 2-5 number from it.

Reads only Git-tracked files (no market data). Scoring follows each batch's preregistration exactly
as the original scorers did:
  - an owner buy-breakout is a BO point tagged one of BUY;
  - a rule day "catches" it within +-1 session of the stock's own session list;
  - precision is 算 / (算 + 不算); 看不出來 and unanswered are reported, not counted.

`--check` exits non-zero if the archive fails verification or any number differs from the
published batchN-result.md tables (EXPECTED below, whose source files are pinned by digest).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.owner_hhhl_labels import BUY, TASK_DIR, ArchiveError, OwnerLabels, load, near, precision, recall

log = logging.getLogger("verify_owner_hhhl_labels")

# Published results (batch2..5-result.md). Recall: (caught, positives); precision: (算, 不算, 看不出來);
# batch 2: (caught, positives, good fires, fires).
EXPECTED: dict[str, dict[str, tuple[int | None, ...]]] = {
    "b2": {"T2": (8, 9, 13, 134), "T1.5": (9, 9, 16, 178), "T3": (6, 9, 9, 75), "T2-red": (6, 9, 9, 91)},
    "b3": {"A v1": (4, 10), "B rule": (11, 10, None), "B control": (2, 5, None)},
    "b4": {
        "B rule": (9, 13, 2),
        "B control": (2, 6, 0),
        "B rule/clears": (7, 3, 0),
        "B rule/inside_big_range": (2, 6, 1),
        "B rule/after_decline": (0, 4, 1),
        "B rule/hhhl": (6, 3, 0),
        "B rule/bottom": (2, 5, 1),
        "B rule/range": (1, 5, 1),
        "A v2": (5, 7),
        "A clears only": (4, 7),
    },
    "b5": {
        "B rule": (15, 7, 2),
        "B small_range": (1, 5, 0),
        "B control": (2, 4, 2),
        "B rule/hhhl": (8, 1, 1),
        "B rule/bottom": (4, 3, 1),
        "B rule/range": (3, 3, 0),
        "B rule/limit_up": (8, 1, 1),
        "A v3 primary": (0, 4),
        "A v3 any pattern": (1, 4),
    },
}
BREAKOUT_RULES = ("T2", "T1.5", "T3", "T2-red")


def batch2(docs: dict[str, dict[str, Any]], items: list[dict[str, Any]], hits: dict[str, Any]) -> dict[str, tuple[int, ...]]:
    """Batch 2 breakout rules inside the labelled window; fires next to an owner 看不出來 point are dropped."""
    out: dict[str, tuple[int, ...]] = {}
    for rule in BREAKOUT_RULES:
        caught = pos = fires = good = 0
        for it in items:
            doc, h = docs.get(it["id"], {}), hits[it["id"]]
            s = h["sessions"]
            bos = [p for p in doc.get("points", []) if p["k"] == "BO"]
            positives = [p["d"] for p in bos if p.get("cat") in BUY]
            neutral = [p["d"] for p in bos if p.get("cat") in ("看不出來", "", None)]
            w0, w1 = s.index(h["window"][0]), s.index(h["window"][1])
            days = [t for t in h["events"][rule] if w0 <= s.index(t) <= w1]
            kept = [t for t in days if not any(near(s, t, n) for n in neutral)]
            pos += len(positives)
            caught += sum(any(near(s, x, t) for t in days) for x in positives)
            fires += len(kept)
            good += sum(any(near(s, t, x) for x in positives) for t in kept)
        out[rule] = (caught, pos, good, fires)
    return out


def score(labels: OwnerLabels) -> dict[str, dict[str, tuple[int | None, ...]]]:
    docs, sets, hits = labels.documents, labels.chart_sets, labels.rule_hits
    got: dict[str, dict[str, tuple[int | None, ...]]] = {"b2": dict(batch2(docs["b2"], sets["b2"], hits["b2"]))}

    b3b = precision(docs["b3b"], sets["b3b"], lambda it: [it["kind"]])
    got["b3"] = {"A v1": recall(docs["b3a"], sets["b3a"], hits["b3a"], "v1"), "B rule": (*b3b["rule"][:2], None), "B control": (*b3b["control"][:2], None)}

    def b4_keys(it: dict[str, Any]) -> list[str | None]:
        rule = it["kind"] == "rule"
        return [it["kind"], f"rule/{it.get('context')}" if rule else None, f"rule/{it.get('cat')}" if rule else None]

    got["b4"] = {f"B {k}": v for k, v in precision(docs["b4b"], sets["b4b"], b4_keys).items()}
    got["b4"]["A v2"] = recall(docs["b4a"], sets["b4a"], hits["b4a"], "v2")
    got["b4"]["A clears only"] = recall(docs["b4a"], sets["b4a"], hits["b4a"], "clears only")

    def b5_keys(it: dict[str, Any]) -> list[str | None]:
        rule = it["kind"] == "rule"
        return [
            it["kind"],
            f"rule/{it.get('cat')}" if rule else None,
            "rule/big_hhhl" if it.get("big_hhhl") else None,
            "rule/limit_up" if it.get("limit_up") else None,
        ]

    got["b5"] = {f"B {k}": v for k, v in precision(docs["b5b"], sets["b5b"], b5_keys).items()}
    for variant in ("v3 primary", "v3 any pattern"):
        got["b5"][f"A {variant}"] = recall(docs["b5a"], sets["b5a"], hits["b5a"], variant, only_tagged=True)
    return got


def compare(got: dict[str, dict[str, tuple[int | None, ...]]]) -> tuple[list[str], int]:
    """Report lines and the number of published rows that are missing or differ."""
    lines, bad = [], 0
    for batch, rows in got.items():
        lines.append(f"== {batch}")
        for name, value in sorted(rows.items()):
            want = EXPECTED[batch].get(name)
            mark = "" if want is None else ("ok" if tuple(want) == tuple(value) else f"MISMATCH (published {want})")
            bad += mark.startswith("MISMATCH")
            lines.append(f"  {name:28s} {value}  {mark}")
        for name in sorted(set(EXPECTED[batch]) - set(rows)):
            bad += 1
            lines.append(f"  {name:28s} MISSING (published {EXPECTED[batch][name]})")
    lines.append("all published numbers reproduced" if not bad else f"{bad} differences")
    return lines, bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify owner-hhhl-labels.v1 and recompute the published batch 2-5 numbers.")
    ap.add_argument("--task-dir", type=Path, default=TASK_DIR, help="archive task directory (default: the tracked one)")
    ap.add_argument("--check", action="store_true", help="fail if the archive or any published number differs")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        labels = load(args.task_dir)
    except ArchiveError as error:
        log.error("archive verification failed: %s", error)
        return 1
    lines, bad = compare(score(labels))
    sys.stdout.write("\n".join(lines) + "\n")
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
