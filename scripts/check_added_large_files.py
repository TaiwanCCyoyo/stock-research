"""Apply the exact root-baseline cap inside the upstream hook environment.

Other files retain pre-commit-hooks' added-only and LFS behavior. Secret scanning
is a separate unchanged hook; this rule grants no content or path exclusions.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

from pre_commit_hooks.check_added_large_files import find_large_added_files

BASELINE_LIMIT_BYTES = 1024 * 1024


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args(argv)
    ordinary_files = []
    status = 0
    for filename in args.filenames:
        if filename.replace("\\", "/") != ".secrets.baseline":
            ordinary_files.append(filename)
            continue
        # Always check a supplied baseline, including an existing tracked file.
        # A nested file with the same basename receives no special treatment.
        size = Path(filename).stat().st_size
        if size > BASELINE_LIMIT_BYTES:
            sys.stdout.write(f"{filename} ({math.ceil(size / 1024)} KB) exceeds 1024 KB.\n")
            status = 1
    return status | find_large_added_files(ordinary_files, maxkb=500)


if __name__ == "__main__":
    raise SystemExit(main())
