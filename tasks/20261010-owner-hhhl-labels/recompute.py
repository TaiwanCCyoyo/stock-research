"""Recompute every batch 2-5 acceptance number from Git-tracked files only.

Reads data/owner_labels.json (the owner's labels), data/chart_sets.zip (what was shown, with the
rule/control `kind` of each blind item) and data/rule_hits.json (what each rule detected on each
labelled chart, captured once by capture_rule_hits.py). No market data is needed.

Scoring follows each batch's preregistration exactly as the original scorers did:
  - an owner buy-breakout is a BO point tagged one of BUY;
  - a rule day "catches" it within +-1 session of the stock's own session list;
  - precision is 算 / (算 + 不算); 看不出來 and unanswered are reported, not counted.

`python recompute.py --check` exits non-zero if any number differs from the published
batchN-result.md tables (the EXPECTED dict below).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from record_timeline import BATCHES, order_holds  # noqa: E402

BUY = {"像", "區間突破", "底部打底", "漲停急拉後整理"}
log = logging.getLogger("recompute")

# Published results (batch2..5-result.md). Recall: (caught, positives); precision: (算, 不算, 看不出來).
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


# documents per page in the archived 2026-10-08 export (all pages, including those no score uses)
EXPECTED_DOCS = {"r1": 30, "b2": 30, "b3a": 30, "b3b": 32, "b4a": 30, "b4b": 32, "b5a": 30, "b5b": 38, "reviews": 30, "lines": 24, "missed": 17}


_SNAPSHOT: dict[str, bytes] = {}


def file_bytes(rel: str) -> bytes:
    """Each archived file is read once per process; every check and every use sees those bytes."""
    if rel not in _SNAPSHOT:
        _SNAPSHOT[rel] = (HERE / rel).read_bytes()
    return _SNAPSHOT[rel]


def open_zip(name: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(file_bytes(f"data/{name}")))


def verified_zip(name: str) -> dict[str, bytes]:
    """Every member of an archive zip, after re-hashing each one against the zip's own manifest."""
    with open_zip(name) as z:
        manifest = json.loads(z.read("manifest.json"))
        members = {n: z.read(n) for n in z.namelist() if n != "manifest.json"}
    if set(members) != set(manifest):
        raise SystemExit(f"{name}: members {sorted(set(members) ^ set(manifest))} disagree with its manifest")
    bad = sorted(n for n, data in members.items() if hashlib.sha256(data).hexdigest() != manifest[n])
    if bad:
        raise SystemExit(f"{name}: members {bad} do not match their manifest SHA-256")
    return members


def pinned_zip(name: str) -> dict[str, bytes]:
    """verified_zip, plus the manifest itself must match the digest pinned in this file."""
    members = verified_zip(name)
    with open_zip(name) as z:
        if canonical(json.loads(z.read("manifest.json"))) != PINNED[name]:
            raise SystemExit(f"{name} differs from its pinned digest; nothing run or written")
    return members


def distinct_ids(items: list[dict], label: str) -> set[str]:
    """Item ids of a chart set; a repeated id would count one owner judgment twice."""
    ids = {it["id"] for it in items}
    if len(ids) != len(items):
        raise SystemExit(f"{label}: {len(items)} items but {len(ids)} distinct ids")
    return ids


# Canonical-JSON SHA-256 of every archived artifact, pinned in Git-tracked code: a zip manifest,
# the owner documents and both receipts. Rewriting an artifact consistently (members and manifest,
# or a receipt and the hits) still changes its digest here. A deliberate new capture updates them.
PINNED = {
    "chart_sets.zip": "6e2b331a15466123d520966686902c8810fd3029cc1a5975978e1f875d5f8dc6",  # pragma: allowlist secret
    "history.zip": "04984133b1031dfc5d07c7db50e95029ea0c4a1f344ef5c58421fda2596e9e8a",  # pragma: allowlist secret
    "rule_sources.zip": "16e95056493584ea95eae58d6b6c9f32ac2bcb178fa438af4e0e5ee1e2a8df29",  # pragma: allowlist secret
    "owner_labels.json": "a0b68a808ab777f0e62d2c06bc46dca27601973a330f298c9418b86cf0b36c05",  # pragma: allowlist secret
    "rule_hits_inputs.zip": "5f46c7c752d68a908df49ceb65bac67c9b46c969a3a28af47c50cd9e050887f2",  # pragma: allowlist secret
    "rule_hits.json": "2e4f22115d693f73ee6670898a65072382a3d30fb5b04711b36f514ceda100e4",  # pragma: allowlist secret
    "timeline_receipt.zip": "d1ea6f4a81c5d0dfbe82dd5f6247e09c5e726ea52b12ada85a413bfe9a128609",  # pragma: allowlist secret
}
# Raw-byte SHA-256 of the published result files, so EXPECTED below cannot drift from them unnoticed.
PINNED_RESULTS = {
    "batch2-result.md": "43635e25d2048c8b422c3202e6f639bd78e93b6debe25b2a832db65cd7014a58",  # pragma: allowlist secret
    "batch3-result.md": "da3211c7474d752733d1d3dbdd7cffe782d55c5eec4c51e5441c488d73c014e4",  # pragma: allowlist secret
    "batch4-result.md": "39d276f4e6e73e607571d002c74affbcb414442cdd4356872d5d63b9f5d5a766",  # pragma: allowlist secret
    "batch5-result.md": "888670030f3e510579bda991d496ddec65fa94b5c0b3933f19db65bf1f9072c2",  # pragma: allowlist secret
}


def canonical(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def check_pins() -> None:
    found = {}
    for name in ("chart_sets.zip", "history.zip", "rule_sources.zip"):
        with open_zip(name) as z:
            found[name] = canonical(json.loads(z.read("manifest.json")))
    found["owner_labels.json"] = canonical(json.loads(file_bytes("data/owner_labels.json").decode("utf-8")))
    found["rule_hits.json"] = canonical(json.loads(file_bytes("data/rule_hits.json").decode("utf-8")))
    for name, member in (("rule_hits_inputs.zip", "inputs.json"), ("timeline_receipt.zip", "receipt.json")):
        with open_zip(name) as z:
            found[name] = canonical(json.loads(z.read(member)))
    for name in PINNED_RESULTS:
        found[name] = hashlib.sha256(file_bytes(name)).hexdigest()
    bad = sorted(k for k in {**PINNED, **PINNED_RESULTS} if found.get(k) != {**PINNED, **PINNED_RESULTS}[k])
    if bad:
        raise SystemExit(f"archived artifacts {bad} differ from their pinned digests")


# The fresh export must equal the earlier dump of each page, except the one documented change,
# whose new values are pinned here (report.md): the owner cleared b2-14's chart verdict.
FRESH_CHANGES = {"b2-14-3015-2025-09-11": {"saved_at": "2026-10-06T16:16:37.796Z", "verdict": ""}}


def check_against_dumps(docs: dict, history: dict[str, bytes]) -> None:
    from build_label_archive import KNOWN_DUMP_DIFFS, KNOWN_DUMP_DIGESTS, PAGES, canonical_digest

    for pid, (_url, _coll, _sub, dump, _cset) in PAGES.items():
        old = {}
        for name, data in history.items():
            if name.startswith(f"earlier_dumps/{dump}/"):
                d = json.loads(data)
                d = d.get("data", d)
                old[d["id"]] = d
        if set(old) != set(docs[pid]):
            raise SystemExit(f"{pid}: archived documents and the {dump} dump cover different ids")
        for i, doc in docs[pid].items():
            changed = {k for k in set(doc) | set(old[i]) if (k in doc) != (k in old[i]) or doc.get(k) != old[i].get(k)}
            allowed = KNOWN_DUMP_DIFFS.get((dump, i), set())
            if allowed and canonical_digest(old[i]) != KNOWN_DUMP_DIGESTS[i]:
                raise SystemExit(f"{dump}/{i}: historical values differ from the pinned digest")
            if changed != allowed or any(doc.get(k) != v for k, v in FRESH_CHANGES.get(i, {}).items()):
                raise SystemExit(f"{pid}/{i}: archived document differs from the {dump} dump beyond the documented change")


def load() -> tuple[dict, dict, dict]:
    verified = {name: verified_zip(name) for name in ("chart_sets.zip", "history.zip", "rule_sources.zip")}
    history, shown = verified["history.zip"], verified["chart_sets.zip"]
    labels = json.loads(file_bytes("data/owner_labels.json").decode("utf-8"))["pages"]
    sets = {p: json.loads(shown[v["chart_set"]].decode("utf-8")) for p, v in labels.items()}
    hits = json.loads(file_bytes("data/rule_hits.json").decode("utf-8"))["batches"]
    with open_zip("rule_hits_inputs.zip") as z:
        receipt = json.loads(z.read("inputs.json"))
    pinned = receipt["rule_hits_sha256"]
    charted = {it["code"] for p in ("b2", "b3a", "b4a", "b5a") for it in sets[p]}
    adjusted = {it["code"] for p in ("b4a", "b5a") for it in sets[p]}
    tables = receipt.get("atlas_tables", {})
    if set(tables) != charted or not all(isinstance(v, str) and len(v) == 64 for v in tables.values()):
        raise SystemExit("rule_hits_inputs.zip does not pin every atlas table the labelled charts used")
    factor_rows = receipt.get("factor_rows_applied", {})
    if set(factor_rows) != adjusted or not all(isinstance(v, list) for v in factor_rows.values()):
        raise SystemExit("rule_hits_inputs.zip does not record the factor rows for every adjusted code")
    if hashlib.sha256(json.dumps(hits, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest() != pinned:
        raise SystemExit("rule_hits.json does not match the hits digest in rule_hits_inputs.zip")
    docs = {p: {d["id"]: d for d in v["documents"]} for p, v in labels.items()}
    log.info("loaded %d pages, %d documents", len(docs), sum(len(v) for v in docs.values()))
    check_against_dumps(docs, history)
    counts = {p: len(v) for p, v in docs.items()}
    if counts != EXPECTED_DOCS:
        raise SystemExit(f"archive page counts {counts} differ from {EXPECTED_DOCS}")
    for p, v in docs.items():
        stray = sorted(set(v) - distinct_ids(sets[p], f"chart set of page {p}"))
        if stray:
            raise SystemExit(f"{p}: documents not in the chart set shown: {stray}")
    with open_zip("timeline_receipt.zip") as z:
        timeline = json.loads(z.read("receipt.json"))["batches"]
    pages_of = {"2": ["b2"], "3": ["b3a", "b3b"], "4": ["b4a", "b4b"], "5": ["b5a", "b5b"]}
    with open_zip("chart_sets.zip") as z:
        set_digests = json.loads(z.read("manifest.json"))
    if set(timeline) != set(BATCHES):
        raise SystemExit(f"timeline receipt covers batches {sorted(timeline)}, expected {sorted(BATCHES)}")
    for batch, row in timeline.items():
        listed = [x["file"] for x in row["chart_sets"]]
        if sorted(listed) != sorted(f"{s}.json" for s in BATCHES[batch][0]):
            raise SystemExit(f"batch {batch}: timeline receipt lists chart sets {listed}, expected {BATCHES[batch][0]}")
        prereg = row["preregistration"]
        committed = hashlib.sha256(file_bytes(f"batch{batch}-preregistration.md")).hexdigest()
        if prereg["file"] != f"batch{batch}-preregistration.md" or prereg["sha256"] != committed or prereg["equals_committed_copy"] is not True:
            raise SystemExit(f"batch {batch}: timeline receipt is not about the committed preregistration")
        for x in row["chart_sets"]:
            if set_digests.get(f"sets/{x['file']}") != x["sha256"]:
                raise SystemExit(f"batch {batch}: timeline receipt chart set {x['file']} does not match chart_sets.zip")
        first = min(d["saved_at"] for p in pages_of[batch] for d in docs[p].values() if d.get("saved_at"))
        sets_utc = [x["modified_utc"] for x in row["chart_sets"]]
        if row["owner_first_save_utc"] != first or not order_holds(row["preregistration"]["modified_utc"], sets_utc, first):
            raise SystemExit(f"batch {batch}: timeline receipt disagrees with the archive or shows the wrong order")
    check_pins()  # last, so the specific checks above report what drifted first
    return docs, sets, hits


def near(sessions: list[str], a: str, b: str) -> bool:
    return abs(sessions.index(a) - sessions.index(b)) <= 1


def buy_points(doc: dict) -> list[str]:
    return [p["d"] for p in doc.get("points", []) if p["k"] == "BO" and p.get("cat") in BUY]


def recall(docs: dict, items: list[dict], hits: dict, variant: str, only_tagged: bool = False) -> tuple[int, int]:
    caught = pos = 0
    for it in items:
        doc = docs.get(it["id"], {})
        P = buy_points(doc)
        if only_tagged and not P and not doc.get("note"):
            continue
        h = hits[it["id"]]
        pos += len(P)
        caught += sum(any(near(h["sessions"], x, t) for t in h["events"][variant]) for x in P)
    return caught, pos


def precision(docs: dict, items: list[dict], keys: Callable[[dict], list[str | None]]) -> dict[str, tuple[int, int, int]]:
    agg: dict[str, dict[str, int]] = {}
    for it in items:
        v = docs.get(it["id"], {}).get("verdict", "")
        for k in keys(it):
            if k:
                agg.setdefault(k, {}).setdefault(v, 0)
                agg[k][v] += 1
    return {k: (m.get("yes", 0), m.get("no", 0), m.get("unsure", 0)) for k, m in agg.items()}


def batch2(docs: dict, items: list[dict], hits: dict) -> dict:
    out = {}
    for r in ("T2", "T1.5", "T3", "T2-red"):
        caught = pos = fires = good = 0
        for it in items:
            doc, h = docs.get(it["id"], {}), hits[it["id"]]
            s = h["sessions"]
            bos = [p for p in doc.get("points", []) if p["k"] == "BO"]
            P = [p["d"] for p in bos if p.get("cat") in BUY]
            neutral = [p["d"] for p in bos if p.get("cat") in ("看不出來", "", None)]
            w0, w1 = s.index(h["window"][0]), s.index(h["window"][1])
            days = [t for t in h["events"][r] if w0 <= s.index(t) <= w1]
            kept = [t for t in days if not any(near(s, t, n) for n in neutral)]
            pos += len(P)
            caught += sum(any(near(s, x, t) for t in days) for x in P)
            fires += len(kept)
            good += sum(any(near(s, t, x) for x in P) for t in kept)
        out[r] = (caught, pos, good, fires)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if any number differs from the published results")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    docs, sets, hits = load()

    got: dict[str, dict] = {"b2": batch2(docs["b2"], sets["b2"], hits["b2"])}

    b3b = precision(docs["b3b"], sets["b3b"], lambda it: [it["kind"]])
    got["b3"] = {"A v1": recall(docs["b3a"], sets["b3a"], hits["b3a"], "v1"), "B rule": b3b["rule"][:2] + (None,), "B control": b3b["control"][:2] + (None,)}

    b4b = precision(
        docs["b4b"],
        sets["b4b"],
        lambda it: [it["kind"], f"rule/{it.get('context')}" if it["kind"] == "rule" else None, f"rule/{it.get('cat')}" if it["kind"] == "rule" else None],
    )
    got["b4"] = {f"B {k}": v for k, v in b4b.items()}
    got["b4"]["A v2"] = recall(docs["b4a"], sets["b4a"], hits["b4a"], "v2")
    got["b4"]["A clears only"] = recall(docs["b4a"], sets["b4a"], hits["b4a"], "clears only")

    b5b = precision(
        docs["b5b"],
        sets["b5b"],
        lambda it: [
            it["kind"],
            f"rule/{it.get('cat')}" if it["kind"] == "rule" else None,
            "rule/big_hhhl" if it.get("big_hhhl") else None,
            "rule/limit_up" if it.get("limit_up") else None,
        ],
    )
    got["b5"] = {f"B {k}": v for k, v in b5b.items()}
    for variant in ("v3 primary", "v3 any pattern"):
        got["b5"][f"A {variant}"] = recall(docs["b5a"], sets["b5a"], hits["b5a"], variant, only_tagged=True)

    bad = 0
    for batch, rows in got.items():
        print(f"== {batch}")
        for name, value in sorted(rows.items()):
            want = EXPECTED[batch].get(name)
            mark = "" if want is None else ("ok" if tuple(want) == tuple(value) else f"MISMATCH (published {want})")
            bad += mark.startswith("MISMATCH")
            print(f"  {name:28s} {value}  {mark}")
        missing = set(EXPECTED[batch]) - set(rows)
        for name in sorted(missing):
            bad += 1
            print(f"  {name:28s} MISSING (published {EXPECTED[batch][name]})")
    print("all published numbers reproduced" if not bad else f"{bad} differences")
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
