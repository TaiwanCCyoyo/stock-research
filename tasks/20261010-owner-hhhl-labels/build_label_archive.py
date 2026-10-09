"""Build the Git-tracked archive of the owner's HH/HL labels from a fresh database export.

Inputs (both under the primary checkout's .tmp, which is not tracked):
  --export  the 2026-10-08 re-export of every labelling page's database
            (one sub-directory per page, documents saved verbatim by the artifact tool)
  --source  the working directory that produced the pages: chart sets shown to the owner,
            earlier dumps, page sources and the early chat rulings in owner_labels.py

Every input is checked before anything is written: each page's export folder and each earlier dump
must exist, hold exactly the expected number of documents, and carry only ids of the chart set that
page showed; every other archived file must exist.

Outputs:
  data/owner_labels.json  every label/judgment/review document, verbatim, grouped by page
  data/chart_sets.zip     what was shown: chart sets with bars and the rule/control `kind`
  data/history.zip        early example sets, the earlier local dumps, page sources, owner_labels.py
  data/rule_sources.zip   the frozen rule sources capture_rule_hits.py ran (SHA-256 in its manifest)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from archive_io import swap_in  # noqa: E402

log = logging.getLogger("build_label_archive")

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
EXTRA_SETS = (
    "label_set_b5x",
    "examples",
    "examples_d",
    "examples_e",
    "examples_e_red_close",
    "examples_e_red_close_green_close",
    "examples_e_red_or_median",
    "review21",
    "review21_z",
)
EXTRA_FILES = (
    "owner_labels.py",
    "label_template.html",
    "label_body.html",
    "review_body.html",
    "review_template.html",
    "page_template.html",
    "lines_body.html",
    "missed_body.html",
)
# documents per page in the 2026-10-08 export; a different count means a missing or wrong export
EXPECTED_DOCS = {"r1": 30, "b2": 30, "b3a": 30, "b3b": 32, "b4a": 30, "b4b": 32, "b5a": 30, "b5b": 38, "reviews": 30, "lines": 24, "missed": 17}
# The only documented differences between an earlier dump and the fresh export: (dump, id) -> the
# differing fields, and the SHA-256 of the dump document's canonical JSON, so the historical values
# themselves are pinned. b2-14: the owner cleared the chart verdict after the dump (report.md).
# labels_dump: the first 10-chart snapshot of page r1; seven charts were re-labelled later.
DOC_FIELDS_R1 = {"points", "saved_at", "schema"}
KNOWN_DUMP_DIFFS = {("labels_b2_dump", "b2-14-3015-2025-09-11"): {"saved_at", "verdict"}} | {
    ("labels_dump", i): DOC_FIELDS_R1
    for i in (
        "c02-6591-2019-09-27",
        "c03-5215-2019-09-23",
        "c04-6152-2023-03-06",
        "c06-1459-2023-09-19",
        "c07-6275-2021-03-15",
        "c08-6185-2025-03-27",
        "c09-2114-2020-11-25",
    )
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


def canonical_digest(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


RULE_SOURCES = ("detect.py", "hhhl_rule_v1.py", "hhhl_rule_v2.py", "hhhl_rule_v3.py", "bigrange.py", "adjprice.py")
HISTORY_DUMPS = {"labels_dump": ("r1", 10)}  # first 10-chart snapshot of page r1, superseded by labels_dump2


_BLOBS: dict[Path, bytes] = {}


def blob(path: Path) -> bytes:
    """Read an input once; validation and packing then use the very same bytes."""
    if path not in _BLOBS:
        _BLOBS[path] = path.read_bytes()
    return _BLOBS[path]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=HERE / "data")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    pages = {}
    for pid, (url, coll, sub, _dump, cset) in PAGES.items():
        folder = a.export / sub / coll
        if not folder.is_dir():
            raise SystemExit(f"{pid}: export folder {folder} is missing")
        docs = [json.loads(blob(p).decode("utf-8")) for p in sorted(folder.glob("*.json"))]
        items = json.loads(blob(a.source / f"{cset}.json").decode("utf-8"))
        shown_ids = {it["id"] for it in items}
        if len(shown_ids) != len(items):
            raise SystemExit(f"{cset}: {len(items)} items but {len(shown_ids)} distinct ids")
        ids = {d.get("id") for d in docs}
        stray = sorted(str(i) for i in ids - shown_ids)
        if len(docs) != EXPECTED_DOCS[pid] or len(ids) != EXPECTED_DOCS[pid] or stray:
            raise SystemExit(f"{pid}: {len(docs)} documents / {len(ids)} distinct ids (expected {EXPECTED_DOCS[pid]}), ids not in {cset}: {stray}")
        pages[pid] = {"artifact": url, "collection": coll, "chart_set": f"sets/{cset}.json", "documents": docs}
    log.info("export verified: %d pages, %d documents", len(pages), sum(len(p["documents"]) for p in pages.values()))
    # earlier local dumps: same page, so same expected count and chart-set ids (labels_dump is a 10-chart subset)
    dumps = {d: (pid, EXPECTED_DOCS[pid]) for pid, (_u, _c, _s, d, _cs) in PAGES.items()} | HISTORY_DUMPS
    history = [(a.source / f"{s}.json", f"sets/{s}.json") for s in EXTRA_SETS]
    history += [(a.source / f, f"pages/{f}") for f in EXTRA_FILES]
    for dump, (pid, expected) in dumps.items():
        folder = a.source / dump
        files = sorted(folder.rglob("*.json")) if folder.is_dir() else []
        ids = {json.loads(blob(p).decode("utf-8")).get("id") for p in files}
        shown_ids = {it["id"] for it in json.loads(blob(a.source / f"{PAGES[pid][4]}.json").decode("utf-8"))}
        if len(files) != expected or len(ids) != expected or not ids <= shown_ids:
            raise SystemExit(f"{dump}: {len(files)} files / {len(ids)} ids (expected {expected}), ids not in {PAGES[pid][4]}: {sorted(ids - shown_ids)}")
        fresh = {d["id"]: d for d in pages[pid]["documents"]}
        for p in files:
            d = json.loads(blob(p).decode("utf-8"))
            d = d.get("data", d)
            f = fresh[d["id"]]
            changed = {k for k in set(d) | set(f) if (k in d) != (k in f) or d.get(k) != f.get(k)}
            allowed = KNOWN_DUMP_DIFFS.get((dump, d["id"]), set())
            digest = KNOWN_DUMP_DIGESTS.get(d["id"]) if allowed else None
            if changed != allowed:
                raise SystemExit(f"{dump}/{d['id']}: fields {sorted(changed)} differ from the fresh export, documented {sorted(allowed)}")
            if digest is not None and canonical_digest(d) != digest:
                raise SystemExit(f"{dump}/{d['id']}: historical values differ from the pinned digest")
        history += [(p, f"earlier_dumps/{dump}/{p.relative_to(folder).as_posix()}") for p in files]
    shown = [(a.source / f"{cset}.json", f"sets/{cset}.json") for *_, cset in PAGES.values()]
    sources = [(a.source / f, f"rules/{f}") for f in RULE_SOURCES]
    missing = [str(src) for src, _ in shown + history + sources if not src.is_file()]
    if missing:
        raise SystemExit(f"missing inputs: {missing}")
    for src, _ in shown + history + sources:  # capture every remaining input before building anything
        blob(src)
    log.info("inputs verified: %d dumps, %d archive members", len(dumps), len(shown) + len(history) + len(sources))

    doc = {
        "schema": "owner-hhhl-labels.v1",
        "exported_on": "2026-10-08",
        "note": "Documents are verbatim database rows written by the owner through the labelling pages.",
        "pages": pages,
    }

    def packed(members: list[tuple[Path, str]]) -> bytes:
        manifest = {}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for src, arc in members:
                data = blob(src)
                z.writestr(arc, data)
                manifest[arc] = hashlib.sha256(data).hexdigest()
            z.writestr("manifest.json", json.dumps(manifest, indent=1))
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:  # verify the finished archive before use
            if z.testzip() is not None or json.loads(z.read("manifest.json")) != manifest:
                raise SystemExit("a freshly built archive failed its own verification; nothing written")
        return buf.getvalue()

    # every output is built and verified in memory first, then all four replace the old ones together
    out = a.out
    out.mkdir(exist_ok=True)
    outputs = {
        out / "owner_labels.json": json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"),
        out / "chart_sets.zip": packed(shown),
        out / "history.zip": packed(history),
        out / "rule_sources.zip": packed(sources),
    }
    swap_in(outputs)
    n = len(shown) + len(history) + len(sources)
    print(f"{sum(len(p['documents']) for p in pages.values())} documents, {n} archived files")


if __name__ == "__main__":
    main()
