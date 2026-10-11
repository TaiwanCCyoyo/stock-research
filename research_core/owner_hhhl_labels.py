"""Verified read access to the `owner-hhhl-labels.v1` archive and its scoring conventions.

The archive itself is Git-tracked data under `tasks/20261010-owner-hhhl-labels/data/`; its data
contract lives next to it. This module is the one place that knows how to read it safely:
`load()` re-hashes every zip member, checks every artifact against the digests pinned below,
compares the fresh export with the earlier dumps the batches were scored from, and checks the
preregistration timeline, before returning anything. Studies that score a rule against the
owner's labels should read through `load()` and reuse `buy_points`/`recall`/`precision`.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from research_core.artifact_store import safe_path

log = logging.getLogger(__name__)

DATASET_ID = "owner-hhhl-labels.v1"
TASK_DIR = Path(__file__).resolve().parents[1] / "tasks" / "20261010-owner-hhhl-labels"

# Owner breakout tags that count as a buy-breakout positive (data-contract.md).
BUY = frozenset({"像", "區間突破", "底部打底", "漲停急拉後整理"})

# page id -> (artifact url, collection, export sub-dir, earlier local dump dir, chart set file)
PAGES = {
    "r1": ("https://claude.ai/artifact/7Wo4zazNYKGek6d7NLUvaw", "labels", "labels_r1", "labels_dump2", "label_set"),
    "b2": ("https://claude.ai/artifact/SQFR98Cz4pzdJpQsux7HXy", "labels", "labels_b2", "labels_b2_dump", "label_set_b2"),
    "b3a": ("https://claude.ai/artifact/K2seibqRVVbqVFxfeVF1ui", "labels", "b3a", "b3a_dump", "label_set_b3a"),
    "b3b": ("https://claude.ai/artifact/XviNwgA4LAHk8YtKMwBTJQ", "judgments", "b3b", "b3b_dump", "set_b3b"),
    "b4a": ("https://claude.ai/artifact/Te15c5tArp5gasUy2pXRpq", "labels", "b4a", "b4a_dump", "label_set_b4a"),
    "b4b": ("https://claude.ai/artifact/PBBUPYvbLKQbpgTPk3tUVw", "judgments", "b4b", "b4b_dump", "set_b4b"),
    "b5a": ("https://claude.ai/artifact/8JHTEezx6LqcroDVFsHkKF", "labels", "b5a", "b5a_dump", "label_set_b5a"),
    "b5b": ("https://claude.ai/artifact/FeBnWGeda7HtMwr8u3v4v5", "judgments", "b5b", "b5b_dump", "set_b5b"),
    "reviews": ("https://claude.ai/artifact/TiPjf6faV2wXgVug9PsQ91", "reviews", "reviews", "reviews_dump", "review_set"),
    "lines": ("https://claude.ai/artifact/RdoGwrzpo9rDe5UAJJdMc6", "lines", "lines", "lines_dump", "lines_set"),
    "missed": ("https://claude.ai/artifact/SfGLfXf8xSNUMm4H7KJw2t", "missed", "missed", "missed_dump", "missed_set"),
}
# documents per page in the 2026-10-08 export; a different count means a missing or wrong export
EXPECTED_DOCS = {"r1": 30, "b2": 30, "b3a": 30, "b3b": 32, "b4a": 30, "b4b": 32, "b5a": 30, "b5b": 38, "reviews": 30, "lines": 24, "missed": 17}
# batch -> (chart sets shown, pages that recorded the owner's answers)
BATCHES = {
    "2": (["label_set_b2"], ["b2"]),
    "3": (["label_set_b3a", "set_b3b"], ["b3a", "b3b"]),
    "4": (["label_set_b4a", "set_b4b"], ["b4a", "b4b"]),
    "5": (["label_set_b5a", "set_b5b"], ["b5a", "b5b"]),
}

# The only documented differences between an earlier dump and the fresh export: (dump, id) -> the
# differing fields, and the digest of the dump document, so the historical values themselves are
# pinned. b2-14: the owner cleared the chart verdict after the dump (report.md).
# labels_dump: the first 10-chart snapshot of page r1; seven charts were re-labelled later.
_R1_RELABELLED = (
    "c02-6591-2019-09-27",
    "c03-5215-2019-09-23",
    "c04-6152-2023-03-06",
    "c06-1459-2023-09-19",
    "c07-6275-2021-03-15",
    "c08-6185-2025-03-27",
    "c09-2114-2020-11-25",
)
KNOWN_DUMP_DIFFS: dict[tuple[str, str], set[str]] = {("labels_b2_dump", "b2-14-3015-2025-09-11"): {"saved_at", "verdict"}} | {
    ("labels_dump", i): {"points", "saved_at", "schema"} for i in _R1_RELABELLED
}
KNOWN_DUMP_DIGESTS = {
    "b2-14-3015-2025-09-11": "a8565a83ef87e5b8c4aee87225ec0d06303259bf5447e1a745f618bd3fb7787f",  # pragma: allowlist secret
    "c02-6591-2019-09-27": "1000395df08053240d206dd49d291f03d4a15291382bcaa118a8a9e5a1990ccf",  # pragma: allowlist secret
    "c03-5215-2019-09-23": "b2a585ce6af9ae00ab80d5586c61f10375af10f878e4dddb4559891dc220be9e",  # pragma: allowlist secret
    "c04-6152-2023-03-06": "999b9f5b5bcb7188e5a20feab3a056d9e01a0dac100111da979e1dbc7ff1f0d8",  # pragma: allowlist secret
    "c06-1459-2023-09-19": "3468bc51ff3ac232407349522b058d3631d30e0c978925048e36ab3907e9bde7",  # pragma: allowlist secret
    "c07-6275-2021-03-15": "c40f3e7bd50c28275b381780939ddb8171061ac2c1986bbecd9ee466402590cc",  # pragma: allowlist secret
    "c08-6185-2025-03-27": "469d0111860de5fc9f89f05098f2a2a4257597e8c4cd42c0d53c70b1a2162755",  # pragma: allowlist secret
    "c09-2114-2020-11-25": "46c2f11ebf71e334ae124b9dd3e2f86fe90af01f71694d9a42c278534bc112d3",  # pragma: allowlist secret
}
# The fresh export must equal the earlier dump of each page except the documented change above,
# whose new values are pinned here: the owner cleared b2-14's chart verdict.
FRESH_CHANGES = {"b2-14-3015-2025-09-11": {"saved_at": "2026-10-06T16:16:37.796Z", "verdict": ""}}

# contract_digest of every archived artifact: a zip manifest, the owner documents and both receipts.
# Rewriting an artifact consistently (members and manifest, or a receipt and the hits) still changes
# its digest here. A deliberate new capture is a new dataset version with its own pins.
PINNED = {
    "chart_sets.zip": "6e2b331a15466123d520966686902c8810fd3029cc1a5975978e1f875d5f8dc6",  # pragma: allowlist secret
    "history.zip": "04984133b1031dfc5d07c7db50e95029ea0c4a1f344ef5c58421fda2596e9e8a",  # pragma: allowlist secret
    "rule_sources.zip": "b5fd17a44724ae59370c7d77c1f4e2150c17c008584d4fae65721174fac9db17",  # pragma: allowlist secret
    "owner_labels.json": "a0b68a808ab777f0e62d2c06bc46dca27601973a330f298c9418b86cf0b36c05",  # pragma: allowlist secret
    "rule_hits_inputs.zip": "14e0f9f181589c7eb412b1805b196a438d49ad0a9a1268f132e92a4eea842579",  # pragma: allowlist secret
    "rule_hits.json": "6d04e9155319382ae72e6511984aaa43c509a2c018e431ccb9c9b4ddb7175cd8",  # pragma: allowlist secret
    "timeline_receipt.zip": "437fb998161b9bad818bd4e74d007113d02be96f7931fc6dd8540e844f27cf83",  # pragma: allowlist secret
}
# Raw-byte SHA-256 of the published result files, so the expected numbers cannot drift from them unnoticed.
PINNED_RESULTS = {
    "batch2-result.md": "43635e25d2048c8b422c3202e6f639bd78e93b6debe25b2a832db65cd7014a58",  # pragma: allowlist secret
    "batch3-result.md": "da3211c7474d752733d1d3dbdd7cffe782d55c5eec4c51e5441c488d73c014e4",  # pragma: allowlist secret
    "batch4-result.md": "39d276f4e6e73e607571d002c74affbcb414442cdd4356872d5d63b9f5d5a766",  # pragma: allowlist secret
    "batch5-result.md": "888670030f3e510579bda991d496ddec65fa94b5c0b3933f19db65bf1f9072c2",  # pragma: allowlist secret
}
RULE_SOURCES = ("detect.py", "hhhl_rule_v1.py", "hhhl_rule_v2.py", "hhhl_rule_v3.py", "bigrange.py", "adjprice.py")


class ArchiveError(ValueError):
    """The archive differs from what the v1 contract pins; nothing derived from it is trustworthy."""


def contract_digest(value: object) -> str:
    """The v1 contract's digest: SHA-256 of `json.dumps(sort_keys=True, ensure_ascii=False)`.

    It predates `artifact_store.object_digest` (compact separators) and is stored inside the
    archive itself (`rule_hits_inputs.zip` -> `rule_hits_sha256`), so v1 keeps this exact form.
    """
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def order_holds(prereg_utc: str, chart_set_utcs: list[str], first_save_utc: str) -> bool:
    """Preregistration before every chart set, and every chart set before the owner's first save."""
    sets = [_utc(x) for x in chart_set_utcs]
    return bool(sets) and _utc(prereg_utc) < min(sets) and max(sets) < _utc(first_save_utc)


class Archive:
    """A read-once snapshot of the task directory: every check and every use sees the same bytes."""

    def __init__(self, task_dir: Path = TASK_DIR) -> None:
        self.task_dir = task_dir
        self._bytes: dict[str, bytes] = {}

    def file(self, rel: str) -> bytes:
        if rel not in self._bytes:
            self._bytes[rel] = safe_path(self.task_dir / rel).read_bytes()
        return self._bytes[rel]

    def json(self, rel: str) -> Any:
        return json.loads(self.file(rel).decode("utf-8"))

    def zip_json(self, name: str, member: str) -> Any:
        with zipfile.ZipFile(io.BytesIO(self.file(f"data/{name}"))) as z:
            return json.loads(z.read(member))

    def zip_members(self, name: str) -> dict[str, bytes]:
        """Every member of an archive zip, re-hashed against the zip's manifest, whose own digest is pinned."""
        with zipfile.ZipFile(io.BytesIO(self.file(f"data/{name}"))) as z:
            manifest = json.loads(z.read("manifest.json"))
            members = {n: z.read(n) for n in z.namelist() if n != "manifest.json"}
        if set(members) != set(manifest):
            raise ArchiveError(f"{name}: members {sorted(set(members) ^ set(manifest))} disagree with its manifest")
        bad = sorted(n for n, data in members.items() if hashlib.sha256(data).hexdigest() != manifest[n])
        if bad:
            raise ArchiveError(f"{name}: members {bad} do not match their manifest SHA-256")
        if contract_digest(manifest) != PINNED[name]:
            raise ArchiveError(f"{name} differs from its pinned digest")
        return members


@dataclass(frozen=True)
class OwnerLabels:
    """documents[page][id] -> owner document; chart_sets[page] -> items shown; rule_hits[page][id] -> rule days."""

    documents: dict[str, dict[str, dict[str, Any]]]
    chart_sets: dict[str, list[dict[str, Any]]]
    rule_hits: dict[str, dict[str, Any]]


def _distinct_ids(items: list[dict[str, Any]], label: str) -> set[str]:
    ids = {it["id"] for it in items}
    if len(ids) != len(items):
        raise ArchiveError(f"{label}: {len(items)} items but {len(ids)} distinct ids")
    return ids


def _check_pins(archive: Archive) -> None:
    found = {name: contract_digest(archive.zip_json(name, "manifest.json")) for name in ("chart_sets.zip", "history.zip", "rule_sources.zip")}
    found["owner_labels.json"] = contract_digest(archive.json("data/owner_labels.json"))
    found["rule_hits.json"] = contract_digest(archive.json("data/rule_hits.json"))
    found["rule_hits_inputs.zip"] = contract_digest(archive.zip_json("rule_hits_inputs.zip", "inputs.json"))
    found["timeline_receipt.zip"] = contract_digest(archive.zip_json("timeline_receipt.zip", "receipt.json"))
    found |= {name: hashlib.sha256(archive.file(name)).hexdigest() for name in PINNED_RESULTS}
    pins = PINNED | PINNED_RESULTS
    bad = sorted(k for k in pins if found.get(k) != pins[k])
    if bad:
        raise ArchiveError(f"archived artifacts {bad} differ from their pinned digests")


def _check_against_dumps(docs: dict[str, dict[str, dict[str, Any]]], history: dict[str, bytes]) -> None:
    for pid, page in PAGES.items():
        dump = page[3]
        old = {}
        for name, data in history.items():
            if name.startswith(f"earlier_dumps/{dump}/"):
                d = json.loads(data)
                d = d.get("data", d)
                old[d["id"]] = d
        if set(old) != set(docs[pid]):
            raise ArchiveError(f"{pid}: archived documents and the {dump} dump cover different ids")
        for i, doc in docs[pid].items():
            changed = {k for k in set(doc) | set(old[i]) if (k in doc) != (k in old[i]) or doc.get(k) != old[i].get(k)}
            allowed = KNOWN_DUMP_DIFFS.get((dump, i), set())
            if allowed and contract_digest(old[i]) != KNOWN_DUMP_DIGESTS[i]:
                raise ArchiveError(f"{dump}/{i}: historical values differ from the pinned digest")
            if changed != allowed or any(doc.get(k) != v for k, v in FRESH_CHANGES.get(i, {}).items()):
                raise ArchiveError(f"{pid}/{i}: archived document differs from the {dump} dump beyond the documented change")


def _check_rule_hits_receipt(archive: Archive, sets: dict[str, list[dict[str, Any]]], hits: dict[str, Any]) -> None:
    receipt = archive.zip_json("rule_hits_inputs.zip", "inputs.json")
    charted = {it["code"] for p in ("b2", "b3a", "b4a", "b5a") for it in sets[p]}
    adjusted = {it["code"] for p in ("b4a", "b5a") for it in sets[p]}
    tables = receipt.get("atlas_tables", {})
    if set(tables) != charted or not all(isinstance(v, str) and len(v) == 64 for v in tables.values()):
        raise ArchiveError("rule_hits_inputs.zip does not pin every atlas table the labelled charts used")
    factor_rows = receipt.get("factor_rows_applied", {})
    if set(factor_rows) != adjusted or not all(isinstance(v, list) for v in factor_rows.values()):
        raise ArchiveError("rule_hits_inputs.zip does not record the factor rows for every adjusted code")
    if contract_digest(hits) != receipt["rule_hits_sha256"]:
        raise ArchiveError("rule_hits.json does not match the hits digest in rule_hits_inputs.zip")


def _check_timeline(archive: Archive, docs: dict[str, dict[str, dict[str, Any]]]) -> None:
    timeline = archive.zip_json("timeline_receipt.zip", "receipt.json")["batches"]
    set_digests = archive.zip_json("chart_sets.zip", "manifest.json")
    if set(timeline) != set(BATCHES):
        raise ArchiveError(f"timeline receipt covers batches {sorted(timeline)}, expected {sorted(BATCHES)}")
    for batch, row in timeline.items():
        set_names, pages = BATCHES[batch]
        listed = [x["file"] for x in row["chart_sets"]]
        if sorted(listed) != sorted(f"{s}.json" for s in set_names):
            raise ArchiveError(f"batch {batch}: timeline receipt lists chart sets {listed}, expected {set_names}")
        prereg = row["preregistration"]
        committed = hashlib.sha256(archive.file(f"batch{batch}-preregistration.md")).hexdigest()
        if prereg["file"] != f"batch{batch}-preregistration.md" or prereg["sha256"] != committed or prereg["equals_committed_copy"] is not True:
            raise ArchiveError(f"batch {batch}: timeline receipt is not about the committed preregistration")
        for x in row["chart_sets"]:
            if set_digests.get(f"sets/{x['file']}") != x["sha256"]:
                raise ArchiveError(f"batch {batch}: timeline receipt chart set {x['file']} does not match chart_sets.zip")
        first = min(d["saved_at"] for p in pages for d in docs[p].values() if d.get("saved_at"))
        if row["owner_first_save_utc"] != first or not order_holds(prereg["modified_utc"], [x["modified_utc"] for x in row["chart_sets"]], first):
            raise ArchiveError(f"batch {batch}: timeline receipt disagrees with the archive or shows the wrong order")


def load(task_dir: Path = TASK_DIR) -> OwnerLabels:
    """Read the archive, refusing it unless every v1 check passes."""
    archive = Archive(task_dir)
    shown = archive.zip_members("chart_sets.zip")
    history = archive.zip_members("history.zip")
    archive.zip_members("rule_sources.zip")
    labels = archive.json("data/owner_labels.json")["pages"]
    sets = {p: json.loads(shown[v["chart_set"]].decode("utf-8")) for p, v in labels.items()}
    hits = archive.json("data/rule_hits.json")["batches"]
    docs = {p: {d["id"]: d for d in v["documents"]} for p, v in labels.items()}
    log.info("%s: %d pages, %d documents", DATASET_ID, len(docs), sum(len(v) for v in docs.values()))
    _check_rule_hits_receipt(archive, sets, hits)
    _check_against_dumps(docs, history)
    counts = {p: len(v) for p, v in docs.items()}
    if counts != EXPECTED_DOCS:
        raise ArchiveError(f"archive page counts {counts} differ from {EXPECTED_DOCS}")
    for p, v in docs.items():
        stray = sorted(set(v) - _distinct_ids(sets[p], f"chart set of page {p}"))
        if stray:
            raise ArchiveError(f"{p}: documents not in the chart set shown: {stray}")
    _check_timeline(archive, docs)
    _check_pins(archive)  # last, so the specific checks above report what drifted first
    return OwnerLabels(documents=docs, chart_sets=sets, rule_hits=hits)


def near(sessions: list[str], a: str, b: str) -> bool:
    """Within one session of each other on the stock's own session list."""
    return abs(sessions.index(a) - sessions.index(b)) <= 1


def buy_points(doc: dict[str, Any]) -> list[str]:
    """Dates of the owner's buy-breakouts: BO points tagged one of BUY."""
    return [p["d"] for p in doc.get("points", []) if p["k"] == "BO" and p.get("cat") in BUY]


def recall(docs: dict[str, dict[str, Any]], items: list[dict[str, Any]], hits: dict[str, Any], variant: str, *, only_tagged: bool = False) -> tuple[int, int]:
    """(owner buy-breakouts a rule day catches within +-1 session, all owner buy-breakouts)."""
    caught = pos = 0
    for it in items:
        doc = docs.get(it["id"], {})
        positives = buy_points(doc)
        if only_tagged and not positives and not doc.get("note"):
            continue
        h = hits[it["id"]]
        pos += len(positives)
        caught += sum(any(near(h["sessions"], x, t) for t in h["events"][variant]) for x in positives)
    return caught, pos


def precision(
    docs: dict[str, dict[str, Any]], items: list[dict[str, Any]], keys: Callable[[dict[str, Any]], list[str | None]]
) -> dict[str, tuple[int, int, int]]:
    """Per key: (算 yes, 不算 no, 看不出來 unsure); unanswered items are not counted."""
    agg: dict[str, dict[str, int]] = {}
    for it in items:
        verdict = docs.get(it["id"], {}).get("verdict", "")
        for k in keys(it):
            if k:
                agg.setdefault(k, {}).setdefault(verdict, 0)
                agg[k][verdict] += 1
    return {k: (m.get("yes", 0), m.get("no", 0), m.get("unsure", 0)) for k, m in agg.items()}
