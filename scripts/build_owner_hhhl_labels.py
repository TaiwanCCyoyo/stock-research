"""Build the `owner-hhhl-labels` archive from a fresh export of the owner's labelling pages.

Inputs (under the primary checkout's .tmp, which is not tracked):
  --export  a re-export of every labelling page's database
            (one sub-directory per page, documents saved verbatim by the artifact tool)
  --source  the working directory that produced the pages: chart sets shown to the owner,
            earlier dumps, page sources and the early chat rulings in owner_labels.py
  --out     a directory that must not exist yet; the archive is published there whole

Every input is checked before anything is written: each page's export folder and each earlier dump
must exist, hold exactly the expected number of documents, and carry only ids of the chart set that
page showed; every other archived file must exist. The committed v1 archive is never replaced: a new
export becomes a new dataset version, verified by `scripts/verify_owner_hhhl_labels.py`.

Outputs:
  owner_labels.json  every label/judgment/review document, verbatim, grouped by page
  chart_sets.zip     what was shown: chart sets with bars and the rule/control `kind`
  history.zip        early example sets, the earlier local dumps, page sources, owner_labels.py
  rule_sources.zip   the frozen rule sources capture_owner_hhhl_rule_hits.py runs
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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.artifact_store import publish_new_directory
from research_core.owner_hhhl_labels import EXPECTED_DOCS, KNOWN_DUMP_DIFFS, KNOWN_DUMP_DIGESTS, PAGES, RULE_SOURCES, contract_digest

log = logging.getLogger("build_owner_hhhl_labels")

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
HISTORY_DUMPS = {"labels_dump": ("r1", 10)}  # first 10-chart snapshot of page r1, superseded by labels_dump2


class Inputs:
    """Each input is read once; validation and packing then use the very same bytes."""

    def __init__(self) -> None:
        self._bytes: dict[Path, bytes] = {}

    def bytes(self, path: Path) -> bytes:
        if path not in self._bytes:
            self._bytes[path] = path.read_bytes()
        return self._bytes[path]

    def json(self, path: Path) -> Any:
        return json.loads(self.bytes(path).decode("utf-8"))


def packed(inputs: Inputs, members: list[tuple[Path, str]]) -> bytes:
    """A zip of the members plus a manifest of their SHA-256, verified before it is returned."""
    manifest = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in members:
            data = inputs.bytes(src)
            z.writestr(arc, data)
            manifest[arc] = hashlib.sha256(data).hexdigest()
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        if z.testzip() is not None or json.loads(z.read("manifest.json")) != manifest:
            raise SystemExit("a freshly built archive failed its own verification; nothing written")
    return buf.getvalue()


def read_pages(inputs: Inputs, export: Path, source: Path) -> dict[str, dict[str, Any]]:
    pages = {}
    for pid, (url, coll, sub, _dump, cset) in PAGES.items():
        folder = export / sub / coll
        if not folder.is_dir():
            raise SystemExit(f"{pid}: export folder {folder} is missing")
        docs = [inputs.json(p) for p in sorted(folder.glob("*.json"))]
        items = inputs.json(source / f"{cset}.json")
        shown_ids = {it["id"] for it in items}
        if len(shown_ids) != len(items):
            raise SystemExit(f"{cset}: {len(items)} items but {len(shown_ids)} distinct ids")
        ids = {d.get("id") for d in docs}
        stray = sorted(str(i) for i in ids - shown_ids)
        if len(docs) != EXPECTED_DOCS[pid] or len(ids) != EXPECTED_DOCS[pid] or stray:
            raise SystemExit(f"{pid}: {len(docs)} documents / {len(ids)} distinct ids (expected {EXPECTED_DOCS[pid]}), ids not in {cset}: {stray}")
        pages[pid] = {"artifact": url, "collection": coll, "chart_set": f"sets/{cset}.json", "documents": docs}
    log.info("export verified: %d pages, %d documents", len(pages), sum(len(p["documents"]) for p in pages.values()))
    return pages


def read_dumps(inputs: Inputs, source: Path, pages: dict[str, dict[str, Any]]) -> list[tuple[Path, str]]:
    """Earlier local dumps: same page, so same expected count and chart-set ids, and only documented differences."""
    dumps = {page[3]: (pid, EXPECTED_DOCS[pid]) for pid, page in PAGES.items()} | HISTORY_DUMPS
    members: list[tuple[Path, str]] = []
    for dump, (pid, expected) in dumps.items():
        folder = source / dump
        files = sorted(folder.rglob("*.json")) if folder.is_dir() else []
        ids = {inputs.json(p).get("id") for p in files}
        shown_ids = {it["id"] for it in inputs.json(source / f"{PAGES[pid][4]}.json")}
        if len(files) != expected or len(ids) != expected or not ids <= shown_ids:
            raise SystemExit(f"{dump}: {len(files)} files / {len(ids)} ids (expected {expected}), ids not in {PAGES[pid][4]}: {sorted(ids - shown_ids)}")
        fresh = {d["id"]: d for d in pages[pid]["documents"]}
        for p in files:
            d = inputs.json(p)
            d = d.get("data", d)
            f = fresh[d["id"]]
            changed = {k for k in set(d) | set(f) if (k in d) != (k in f) or d.get(k) != f.get(k)}
            allowed = KNOWN_DUMP_DIFFS.get((dump, d["id"]), set())
            if changed != allowed:
                raise SystemExit(f"{dump}/{d['id']}: fields {sorted(changed)} differ from the fresh export, documented {sorted(allowed)}")
            if allowed and contract_digest(d) != KNOWN_DUMP_DIGESTS[d["id"]]:
                raise SystemExit(f"{dump}/{d['id']}: historical values differ from the pinned digest")
        members += [(p, f"earlier_dumps/{dump}/{p.relative_to(folder).as_posix()}") for p in files]
    log.info("earlier dumps verified: %d", len(dumps))
    return members


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build an owner-hhhl-labels archive into a new directory.")
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="new directory; refused if it already exists")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if a.out.exists():
        raise SystemExit(f"{a.out} already exists; an archive is published only into a new directory")

    inputs = Inputs()
    pages = read_pages(inputs, a.export, a.source)
    history = [(a.source / f"{s}.json", f"sets/{s}.json") for s in EXTRA_SETS]
    history += [(a.source / f, f"pages/{f}") for f in EXTRA_FILES]
    history += read_dumps(inputs, a.source, pages)
    shown = [(a.source / f"{page[4]}.json", f"sets/{page[4]}.json") for page in PAGES.values()]
    sources = [(a.source / f, f"rules/{f}") for f in RULE_SOURCES]
    missing = [str(src) for src, _ in shown + history + sources if not src.is_file()]
    if missing:
        raise SystemExit(f"missing inputs: {missing}")
    for src, _ in shown + history + sources:  # capture every remaining input before building anything
        inputs.bytes(src)

    doc = {
        "schema": "owner-hhhl-labels.v1",
        "exported_on": "2026-10-08",
        "note": "Documents are verbatim database rows written by the owner through the labelling pages.",
        "pages": pages,
    }
    publish_new_directory(
        a.out,
        {
            "owner_labels.json": json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"),
            "chart_sets.zip": packed(inputs, shown),
            "history.zip": packed(inputs, history),
            "rule_sources.zip": packed(inputs, sources),
        },
    )
    sys.stdout.write(f"{sum(len(p['documents']) for p in pages.values())} documents, {len(shown) + len(history) + len(sources)} archived files\n")


if __name__ == "__main__":
    main()
