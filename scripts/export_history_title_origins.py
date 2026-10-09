"""Snapshot report titles from an explicit Git revision, preserving saved packages.

The sidecar records report-version headings, not a reconstruction of titles lost
from the saved package. Run as ``python -m scripts.export_history_title_origins``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_core.saved_research_studio import StudioError, read_studio_package

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)


def _git_bytes(repo_root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=True,
            capture_output=True,
            shell=False,
        ).stdout
    except subprocess.CalledProcessError as error:
        LOGGER.error("Git report snapshot read failed (%s)", arguments[0])
        raise ValueError(f"Git {arguments[0]} failed for report snapshot") from error


def export_title_origins(
    package_path: Path,
    revision: str,
    output: Path,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    """Create a new sidecar bound to saved history and immutable report bytes."""
    package = read_studio_package(package_path)
    history = package["researchHistory"]
    commit = (
        _git_bytes(
            repo_root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{revision}^{{commit}}",
        )
        .decode("ascii")
        .strip()
    )
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("source revision must resolve to a full 40-character Git SHA")
    LOGGER.info("Reading report-version titles from revision %s", commit)
    titles: dict[str, dict[str, str]] = {}
    for item in history["items"]:
        source_path = item["reportPath"]
        if source_path is None:
            continue
        identity = item["id"]
        if (
            identity in {".", ".."}
            or any(character in identity for character in "/\\\x00")
            or source_path not in {f"tasks/{identity}/report.md", f"tasks/{identity}/mission.md"}
        ):
            raise ValueError(f"invalid report source path for history item {identity}")
        raw = _git_bytes(repo_root, "show", f"{commit}:{source_path}")
        title = next(
            (
                match.group(1).strip()
                for line in raw.decode("utf-8-sig").splitlines()
                if (match := re.fullmatch(r"#\s+(.+?)\s*", line)) and match.group(1).strip()
            ),
            None,
        )
        if title is None:
            raise ValueError(f"report snapshot has no level-one heading: {source_path}")
        titles[identity] = {
            "title": title,
            "sourcePath": source_path,
            "sourceSha256": hashlib.sha256(raw).hexdigest(),
        }
    result = {
        "schema": "research-history-title-origins.v1",
        "historySha256": hashlib.sha256(
            json.dumps(
                history,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "sourceRevision": commit,
        "titles": titles,
    }
    with output.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(result, target, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        target.write("\n")
    LOGGER.info("Wrote %d report-version title snapshots", len(titles))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = export_title_origins(args.package, args.revision, args.output)
    except (OSError, ValueError, StudioError) as error:
        LOGGER.error("Report-version title snapshot export failed: %s", error)
        return 1
    sys.stdout.write(json.dumps({"titles": len(result["titles"]), "revision": result["sourceRevision"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
