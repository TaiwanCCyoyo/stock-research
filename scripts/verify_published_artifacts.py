"""Verify every published research artifact with its own reader, and report one pass/fail row each.

Git-tracked publications are read from `--root` (a checkout). Local-only artifacts (datasets, full
transports) are read from `--local-root` (default: the primary checkout); a missing local-only input is
reported as `local-missing`, never as a pass. The full test suite does not read these real artifacts,
so run this after any change that rewrites stored evidence or the code that reads it.

    uv run python -m scripts.verify_published_artifacts [--only NAME ...] [--json OUT]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = Path("D:/Project/stock-research")
LOG = logging.getLogger("verify_published_artifacts")
HEX = re.compile(r"[0-9a-f]{64}")
V4 = "tasks/20261010-hhhl-v4-probability"


@dataclass(frozen=True)
class Check:
    name: str
    run: Callable[[Path, Path], tuple[str, str]]


def _cli(root: Path, *args: str, timeout: int = 1800) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
    return ("pass" if result.returncode == 0 else "fail"), tail[0][:200]


def _local(path: Path) -> tuple[str, str] | None:
    return None if path.exists() else ("local-missing", str(path))


def _zip_descriptors(data: bytes, label: str) -> list[str]:
    """Every {path|name|file: member, sha256} descriptor inside a zip that names a sibling member must match it."""
    problems = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = {n: z.read(n) for n in z.namelist()}
    for name, body in members.items():
        if not name.endswith(".json"):
            continue
        try:
            value = json.loads(body)
        except ValueError:
            continue
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                ref = next((item[k] for k in ("path", "name", "file", "member") if isinstance(item.get(k), str)), None)
                digest = item.get("sha256")
                if ref in members and isinstance(digest, str) and HEX.fullmatch(digest) and hashlib.sha256(members[ref]).hexdigest() != digest:
                    problems.append(f"{label}!{name}: {ref}")
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return problems


def owner_labels(root: Path, _local_root: Path) -> tuple[str, str]:
    return _cli(root, "scripts/verify_owner_hhhl_labels.py", "--check")


def v4_public(root: Path, _local_root: Path) -> tuple[str, str]:
    return _cli(
        root,
        "-m",
        "scripts.publish_hhhl_v4_probability",
        "--publication",
        f"{V4}/publication-v2-public",
        "--noise-first-correction",
        f"{V4}/noise-first-correction-v2",
        "--family",
        "noise",
    )


def v4_full(root: Path, local_root: Path) -> tuple[str, str]:
    full = local_root / V4 / "publication-v2"
    return _local(full) or _cli(
        root,
        "-m",
        "scripts.publish_hhhl_v4_probability",
        "--publication",
        str(full),
        "--noise-first-correction",
        f"{V4}/noise-first-correction-v2",
        "--family",
        "noise",
    )


def v4_supplements(root: Path, local_root: Path) -> tuple[str, str]:
    full = local_root / V4 / "publication-v2"
    audit = local_root / V4 / "landmark-audit-v1.zip"  # local-only: holds real closes
    missing = _local(full) or _local(audit)
    if missing:
        return missing
    code = (
        "from pathlib import Path\n"
        "from scripts.supplement_hhhl_v4_diagnostics import verify_supplement as d\n"
        "from scripts.supplement_hhhl_v4_audit import verify_supplement as a\n"
        f"d(Path('{V4}/diagnostics-supplement-v2.zip'), Path(r'{full}'))\n"
        f"a(Path(r'{audit}'), Path(r'{full}'))\n"
    )
    return _cli(root, "-c", code)


def feature_atlas_publication(root: Path, _local_root: Path) -> tuple[str, str]:
    return _cli(
        root, "-m", "scripts.query_feature_atlas_publication", "--publication", "tasks/20261004-feature-discrimination-atlas/publication-v2", "--verify"
    )


def atlas_dataset(root: Path, local_root: Path) -> tuple[str, str]:
    dataset = local_root / "tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2"
    return _local(dataset) or _cli(root, "-m", "scripts.query_feature_discrimination_atlas", str(dataset), "--verify")


def market_context(root: Path, local_root: Path) -> tuple[str, str]:
    relative = "tasks/20261005-market-context-handoff/market-context-v2"
    private = local_root / relative / "inputs/0050.json.gz"
    if not private.exists():
        return ("local-missing", str(private))
    with tempfile.TemporaryDirectory(dir=root / ".tmp") as scratch:
        copy = Path(scratch) / "market-context-v2"
        shutil.copytree(root / relative, copy)
        shutil.copyfile(private, copy / "inputs/0050.json.gz")
        return _cli(root, "-m", "scripts.query_market_context", "--dataset", str(copy), "--verify")


def method_environment(root: Path, _local_root: Path) -> tuple[str, str]:
    return _cli(root, "scripts/publish_method_environment_interactions.py", "--read", "tasks/20261005-method-environment-interactions/publication-v1")


def industry_role(root: Path, _local_root: Path) -> tuple[str, str]:
    return _cli(root, "scripts/publish_method_environment_interactions.py", "--read", "tasks/20261005-industry-role-comparison/publication-v2")


def sector_wave_catalog(root: Path, _local_root: Path) -> tuple[str, str]:
    code = (
        "from pathlib import Path\n"
        "from scripts.build_sector_wave_catalog import validate_bundle\n"
        "validate_bundle(Path('tasks/20261002-sector-wave-catalog/catalog-v1'))\n"
    )
    return _cli(root, "-c", code)


def sector_role_evidence(root: Path, _local_root: Path) -> tuple[str, str]:
    return _cli(
        root,
        "-m",
        "scripts.validate_sector_role_evidence",
        "tasks/20261002-sector-role-evidence/evidence-v1.json",
        "--catalog",
        "tasks/20261002-sector-wave-catalog/catalog-v1",
        "--receipt",
        "tasks/20261002-sector-role-evidence/completion-receipt.json",
    )


def _opportunity(version: str) -> Callable[[Path, Path], tuple[str, str]]:
    """Restore the root metadata from its Git mirrors; a full audit also needs the local runs and trust registry."""

    def check(root: Path, _local_root: Path) -> tuple[str, str]:
        catalog = f"tasks/20261004-sector-wave-full-history-preview/{version}"
        with tempfile.TemporaryDirectory(dir=root / ".tmp") as scratch:
            return _cli(
                root,
                "scripts/publish_opportunity_history.py",
                "restore",
                "--bundle-index",
                f"{catalog}/bundle-index.json",
                "--target-root",
                str(Path(scratch) / version),
            )

    return check


def _zip_self_consistency(*paths: str) -> Callable[[Path, Path], tuple[str, str]]:
    def check(root: Path, _local_root: Path) -> tuple[str, str]:
        problems = []
        for relative in paths:
            problems += _zip_descriptors((root / relative).read_bytes(), relative)
        return ("pass", f"{len(paths)} bundles") if not problems else ("fail", "; ".join(problems[:3]))

    return check


def hhhl_v1_publication(root: Path, local_root: Path) -> tuple[str, str]:
    base = "tasks/20261009-hhhl-pattern-probability/publication-v1"
    manifest = json.loads((root / base / "manifest.json").read_text(encoding="utf-8"))
    bundle = local_root / base / "bundle.zip"
    if not bundle.exists():
        return ("local-missing", str(bundle))
    data = bundle.read_bytes()
    text = json.dumps(manifest)
    if hashlib.sha256(data).hexdigest() not in text:
        return ("fail", "bundle.zip SHA-256 not named by manifest.json")
    problems = _zip_descriptors(data, "hhhl-v1 bundle.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        missing = [n for n in z.namelist() if hashlib.sha256(z.read(n)).hexdigest() not in text and not n.endswith("/")]
    if missing:
        problems.append(f"members not named by manifest: {missing[:3]}")
    return ("pass", "bundle and members match") if not problems else ("fail", "; ".join(problems[:3]))


CHECKS = [
    Check("owner-hhhl-labels.v1", owner_labels),
    Check("hhhl-v4 public transport + correction", v4_public),
    Check("hhhl-v4 full transport (local)", v4_full),
    Check("hhhl-v4 diagnostics + landmark audit (local)", v4_supplements),
    Check("hhhl-v1 publication", hhhl_v1_publication),
    Check("feature-atlas-publication.v2", feature_atlas_publication),
    Check("atlas-v2 dataset (local)", atlas_dataset),
    Check("market-context-manifest.v2", market_context),
    Check("method-environment-publication.v1", method_environment),
    Check("industry-role-transport.v2", industry_role),
    Check("sector-wave-catalog.v1", sector_wave_catalog),
    Check("sector-role-evidence", sector_role_evidence),
    Check("opportunity catalog-v1", _opportunity("catalog-v1")),
    Check("opportunity catalog-v2", _opportunity("catalog-v2")),
    Check(
        "research-data-architecture bundles",
        _zip_self_consistency(
            "tasks/20261008-research-data-architecture/publication-v1/bundle.zip",
            "tasks/20261008-research-data-architecture/publication-v1/review2.zip",
            "tasks/20261008-research-data-architecture/publication-v2/bundle.zip",
            "tasks/20261008-research-data-architecture/publication-v2/review8.zip",
        ),
    ),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify every published research artifact with its own reader.")
    ap.add_argument("--root", type=Path, default=ROOT, help="checkout whose tracked publications and code are verified")
    ap.add_argument("--local-root", type=Path, default=PRIMARY, help="where local-only artifacts live")
    ap.add_argument("--only", nargs="*", help="run only checks whose name contains one of these words")
    ap.add_argument("--json", type=Path, help="write the result table as JSON")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    (a.root / ".tmp").mkdir(exist_ok=True)
    rows = []
    for check in CHECKS:
        if a.only and not any(word in check.name for word in a.only):
            continue
        try:
            status, detail = check.run(a.root.resolve(), a.local_root)
        except Exception as error:  # noqa: BLE001 - one broken reader must not hide the others
            status, detail = "fail", f"{type(error).__name__}: {error}"[:200]
        rows.append({"check": check.name, "status": status, "detail": detail})
        sys.stdout.write(f"{status:14s} {check.name:45s} {detail}\n")
        sys.stdout.flush()
    if a.json:
        a.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if any(r["status"] == "fail" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
