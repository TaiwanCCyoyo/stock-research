"""Restore the frozen local web bundle from an existing producer copy.

This copies catalog/native evidence only. It never downloads, runs analysis,
overwrites a destination, or modifies the producer's prices and results.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
from pathlib import Path

from research_core.opportunity_history_store import DEFAULT_BUNDLE, DEFAULT_SHA, HistoryStore

SUBTREES = ("catalog-v2", "runs/native")
LOGGER = logging.getLogger(__name__)


def _physical(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Restore requires physical directories, without links or junctions")


def _identities(root: Path) -> dict[str, str]:
    """Hash all files before validation, then require the copied bytes to match."""
    _physical(root)
    identities: dict[str, str] = {}
    for subtree in SUBTREES:
        directory = root / subtree
        _physical(directory)
        if not directory.is_dir():
            raise ValueError(f"Missing producer subtree: {subtree}")
        for path in directory.rglob("*"):
            _physical(path)
            if path.is_file():
                with path.open("rb") as source:
                    identities[path.relative_to(root).as_posix()] = hashlib.file_digest(source, "sha256").hexdigest()
    return identities


def restore_bundle(source: Path, destination: Path = DEFAULT_BUNDLE) -> Path:
    """Accept this pinned snapshot before copying to a new physical destination."""
    source = source.absolute()
    destination = destination.absolute()
    _physical(source)
    _physical(destination)
    # Inspect the original components before resolve can erase a link/../ prefix.
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError("Restore destination already exists; existing data will not be overwritten")
    # Windows namespace aliases can name the same directory with different
    # resolved strings. Compare existing ancestor identities before any writes.
    if (
        source == destination
        or destination.is_relative_to(source)
        or source.is_relative_to(destination)
        or any(parent.exists() and source.samefile(parent) for parent in destination.parents)
    ):
        raise ValueError("Source and destination must be separate directories")
    before = _identities(source)
    HistoryStore(source, DEFAULT_SHA)
    # Verification is deliberately before the first write. Partial copies from
    # I/O errors stay visible for manual inspection and cannot be overwritten.
    destination.mkdir(parents=True, exist_ok=False)
    for subtree in SUBTREES:
        shutil.copytree(source / subtree, destination / subtree)
    if _identities(destination) != before:
        raise ValueError("Producer bytes changed during restoration; do not start the API with this copy")
    return destination


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing producer task directory containing catalog-v2 and runs/native")
    args = parser.parse_args()
    result = restore_bundle(args.source)
    LOGGER.info("Restored verified frozen evidence to %s. Restart the history API before use.", result)


if __name__ == "__main__":
    main()
