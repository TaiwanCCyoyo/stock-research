"""Capture, once, what each rule version detected on the charts the owner labelled (batches 2-5).

Recall needs the rule's output on every labelled chart. Running the rules needs the atlas-v2
price tables and the frozen rule sources, which a fresh clone does not have, so this script
records the rule days per chart into data/rule_hits.json. recompute.py then reproduces every
batch result from Git-tracked files alone.

The detection code is the batch scorers' own (score_b2.py .. score_b5.py in the source
directory), copied here without changing what is detected:
  batch 2  T2 / T1.5 / T3 / T2-red on atlas-v2 prices (inline, as score_b2.py)
  batch 3  hhhl_rule_v1 on atlas-v2 prices
  batch 4  hhhl_rule_v2 on adjprice (cash-dividend reference-factor prices)
  batch 5  hhhl_rule_v3 on adjprice

Usage (needs the atlas-v2 tables and the corporate-actions database; --source may be the original
.tmp directory or the `rules/` directory extracted from data/rule_sources.zip, and is refused unless
every file matches that archive byte for byte):
  uv run python tasks/20261010-owner-hhhl-labels/capture_rule_hits.py --source <dir>
      --tables <atlas-v2 tables dir> --actions <corporate_actions.sqlite>
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import importlib
import io
import json
import logging
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from archive_io import swap_in  # noqa: E402

log = logging.getLogger("capture_rule_hits")
MARGIN = 3  # sessions kept on each side of a window, so +-1 matching never falls off the edge
SOURCE_FILES = ("detect.py", "hhhl_rule_v1.py", "hhhl_rule_v2.py", "hhhl_rule_v3.py", "bigrange.py", "adjprice.py")


def chart_sets() -> dict[str, list[dict]]:
    """The labelled chart sets, only after every member and the manifest itself are verified."""
    from recompute import pinned_zip

    members = pinned_zip("chart_sets.zip")  # every member re-hashed, the manifest checked against its pin
    names = ("label_set_b2", "label_set_b3a", "label_set_b4a", "label_set_b5a")
    return {n: json.loads(members[f"sets/{n}.json"].decode("utf-8")) for n in names}


def window(d: list[str], it: dict) -> tuple[int, int]:
    return d.index(it["bars"][0][0]), d.index(it["date"])


def keep(d: list[str], w0: int, w1: int, days: dict[str, list[int]]) -> dict:
    a, b = max(0, w0 - MARGIN), min(len(d), w1 + MARGIN + 1)
    return {"window": [d[w0], d[w1]], "sessions": d[a:b], "events": {k: [d[t] for t in ts if a <= t < b] for k, ts in days.items()}}


def atlas(tables: Path, code: str) -> pd.DataFrame:
    cols = ["asof_date", "Open", "High", "Low", "Close", "VolumeLots", "atr14_pct"]
    return pd.read_parquet(tables / f"{code}.parquet", columns=cols).dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)


def batch2(tables: Path, items: list[dict]) -> dict:
    out = {}
    for it in items:
        df = atlas(tables, it["code"])
        d = df["asof_date"].astype(str).str[:10].tolist()
        o, c = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
        v = df["VolumeLots"].to_numpy(float)
        atr = df["atr14_pct"].to_numpy(float) * c
        w0, w1 = window(d, it)
        days: dict[str, list[int]] = {r: [] for r in ("T2", "T1.5", "T3", "T2-red")}
        for t in range(w0, w1 + 1):
            if t < 20:
                continue
            hi = c[t] > c[t - 20 : t].max()
            m = np.nanmean(v[t - 20 : t])
            vx = v[t] / m if m > 0 else np.nan
            red = (c[t] - o[t]) >= 0.5 * atr[t]
            if hi and vx >= 2.0:
                days["T2"].append(t)
            if hi and vx >= 1.5:
                days["T1.5"].append(t)
            if hi and vx >= 3.0:
                days["T3"].append(t)
            if hi and vx >= 2.0 and red:
                days["T2-red"].append(t)
        out[it["id"]] = keep(d, w0, w1, days)
    return out


def batch_rule(
    load: Callable[[str], pd.DataFrame],
    detect: Callable[[pd.DataFrame], list[dict]],
    items: list[dict],
    variants: dict[str, Callable[[dict], bool]],
) -> dict:
    out = {}
    for it in items:
        df = load(it["code"])
        d = df["asof_date"].astype(str).str[:10].tolist()
        ev = detect(df)
        w0, w1 = window(d, it)
        out[it["id"]] = keep(d, w0, w1, {k: [e["t"] for e in ev if f(e)] for k, f in variants.items()})
    return out


def hits_digest(batches: dict) -> str:
    """SHA-256 of the hits' canonical JSON, independent of how the file is formatted."""
    return hashlib.sha256(json.dumps(batches, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def table_digests(tables: Path, codes: list[str]) -> dict[str, str]:
    return {c: hashlib.sha256((tables / f"{c}.parquet").read_bytes()).hexdigest() for c in codes}


def input_receipt(a: argparse.Namespace, adjprice: object, sets: dict[str, list[dict]], batches: dict, digests: dict[str, str]) -> bytes:
    """Pin the market data the capture read (table digests, factor rows applied) to the hits it produced."""
    codes = sorted({it["code"] for items in sets.values() for it in items})
    adjusted = sorted({it["code"] for name in ("label_set_b4a", "label_set_b5a") for it in sets[name]})
    factors = getattr(adjprice, "_factors")()
    receipt = {
        "schema": "owner-hhhl-rule-hits-inputs.v1",
        "captured_on": "2026-10-08",
        "rule_hits_sha256": hits_digest(batches),
        "atlas_tables": {c: digests[c] for c in codes},
        "corporate_actions_db": a.actions.as_posix(),
        "factor_rows_applied": {
            c: [[str(r.ex_date), str(r.event_type), float(r.price_factor)] for r in factors[factors["code"] == c].sort_values("ex_date").itertuples()]
            for c in adjusted
        },
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("inputs.json", json.dumps(receipt, ensure_ascii=False, indent=1))
    log.info("input receipt: %d tables, %d adjusted codes", len(codes), len(adjusted))
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--tables", type=Path, required=True, help="atlas-v2 per-stock tables directory")
    ap.add_argument("--actions", type=Path, required=True, help="producer corporate_actions.sqlite")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = chart_sets()  # verify what will be run on before anything else
    from recompute import PINNED, canonical, verified_zip

    members = verified_zip("rule_sources.zip")  # every member re-hashed against the manifest
    with zipfile.ZipFile(HERE / "data" / "rule_sources.zip") as z:
        archived = json.loads(z.read("manifest.json"))
    if canonical(archived) != PINNED["rule_sources.zip"]:
        raise SystemExit("rule_sources.zip differs from its pinned digest; nothing run or written")
    if set(members) != {f"rules/{f}" for f in SOURCE_FILES}:
        raise SystemExit(f"rule_sources.zip holds {sorted(members)}, expected exactly the {len(SOURCE_FILES)} rule sources")
    frozen = {f: members[f"rules/{f}"] for f in SOURCE_FILES}
    for f in SOURCE_FILES:
        if hashlib.sha256((a.source / f).read_bytes()).hexdigest() != archived[f"rules/{f}"]:
            raise SystemExit(f"{f} differs from data/rule_sources.zip; rebuild the archive first")
    # run the archived bytes from a private snapshot, so a later change under --source cannot be executed
    scratch = HERE.parents[1] / ".tmp"  # the repository's scratch area, not the OS temp directory
    scratch.mkdir(exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="owner-hhhl-rules-", dir=scratch))
    atexit.register(shutil.rmtree, snapshot, True)
    for f, data in frozen.items():
        (snapshot / f).write_bytes(data)
    sys.path.insert(0, str(snapshot))
    adjprice, v1, v2, v3 = (importlib.import_module(m) for m in ("adjprice", "hhhl_rule_v1", "hhhl_rule_v2", "hhhl_rule_v3"))
    # the frozen adjprice hard-codes its inputs; point it at the paths actually chosen and record them
    setattr(adjprice, "TABLES", a.tables)
    setattr(adjprice, "ACTIONS", a.actions)
    log.info("rule sources %s, atlas tables %s, corporate actions %s", a.source, a.tables, a.actions)

    codes = sorted({it["code"] for items in s.values() for it in items})
    before = table_digests(a.tables, codes)  # the versions the rules are about to read
    hits = {
        "b2": batch2(a.tables, s["label_set_b2"]),
        "b3a": batch_rule(lambda code: atlas(a.tables, code), v1.detect, s["label_set_b3a"], {"v1": lambda e: e["pattern"]}),
        "b4a": batch_rule(adjprice.load, v2.detect, s["label_set_b4a"], {"v2": lambda e: e["pattern"], "clears only": lambda e: e["context"] == "clears"}),
        "b5a": batch_rule(
            adjprice.load,
            v3.detect,
            s["label_set_b5a"],
            {"v3 primary": lambda e: e["pattern"] and e["scale"] == "big_range", "v3 any pattern": lambda e: e["pattern"]},
        ),
    }
    doc = {
        "schema": "owner-hhhl-rule-hits.v1",
        "rule_sources": "data/rule_sources.zip (SHA-256 in its manifest)",
        "atlas_tables": a.tables.as_posix(),
        "corporate_actions": a.actions.as_posix(),
        "corporate_actions_note": "current-reference database read at capture time (2026-10-08); adjprice keeps ex_date <= 2026-08-14",
        "input_receipt": "data/rule_hits_inputs.zip: SHA-256 of every atlas table read and the exact factor rows applied",
        "margin_sessions": MARGIN,
        "batches": hits,
    }
    if table_digests(a.tables, codes) != before:
        raise SystemExit("atlas tables changed while the rules were running; nothing written")
    # build both outputs in memory first, stage them next to the targets, then swap both in
    outputs = {
        HERE / "data" / "rule_hits.json": json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"),
        HERE / "data" / "rule_hits_inputs.zip": input_receipt(a, adjprice, s, hits, before),
    }
    swap_in(outputs)
    print({k: len(v) for k, v in hits.items()})


if __name__ == "__main__":
    main()
