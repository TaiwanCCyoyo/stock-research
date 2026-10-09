"""Select CI tests conservatively using a complete, NUL-delimited Git diff."""

import argparse
import logging
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

LOGGER = logging.getLogger(__name__)


def needs_tests(paths: Iterable[str]) -> bool:
    """Only root prose and prose under docs are eligible for the fast path."""
    for value in paths:
        path = PurePosixPath(value.replace("\\", "/"))
        known_prose = path.suffix.lower() in {".md", ".rst"} and (len(path.parts) == 1 or path.parts[0] == "docs")
        if not known_prose:
            return True
    return False


def select_scope(base: str, head: str) -> bool:
    if base == "0" * 40:
        # GitHub uses a null before SHA when creating a branch, including a
        # repository's first push. Validate the head without requiring a parent.
        subprocess.run(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{head}^{{commit}}"],
            capture_output=True,
            check=True,
            timeout=60,
        )
        LOGGER.info("Initial push with valid head: running all tests")
        return True
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    paths = [os.fsdecode(value) for value in result.stdout.split(b"\0") if value]
    run_tests = needs_tests(paths)
    LOGGER.info("Classified %s changed paths: run_tests=%s", len(paths), run_tests)
    return run_tests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        run_tests = select_scope(args.base, args.head)
    except (subprocess.SubprocessError, OSError) as exc:
        LOGGER.error("Cannot classify CI scope; refusing to skip tests: %s", exc)
        return 1
    with args.output.open("a", encoding="utf-8") as output:
        output.write(f"run_tests={str(run_tests).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
