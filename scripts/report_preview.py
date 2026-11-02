"""Gate and package changed web-report folders for a label-triggered PR preview."""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from research_core import report_preview

LOGGER = logging.getLogger("report_preview")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="clean checkout of the PR head")
    parser.add_argument("--base", required=True, help="PR base commit")
    parser.add_argument("--head", required=True, help="PR head commit")
    parser.add_argument("--out", type=Path, required=True, help="empty output folder")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    repo = args.repo.resolve()
    ids = report_preview.report_ids(report_preview.changed_files(repo, args.base, args.head))
    LOGGER.info("changed report ids: %s", ", ".join(ids) or "(none)")
    if not ids:
        return 3  # nothing to preview; the workflow treats 3 as a clean skip
    if args.out.exists() and any(args.out.iterdir()):
        LOGGER.error("output folder is not empty")
        return 2
    built_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    try:
        manifest = report_preview.build_preview(repo, args.out, args.pr, args.head, args.branch, built_at, ids)
    except report_preview.PreviewGateError as error:
        LOGGER.error("preview gate failed (%d violation(s)); names only, no content:", len(error.violations))
        for violation in error.violations:
            LOGGER.error("  %s", violation)
        return 1
    LOGGER.info("packaged %d file(s) from %d report(s)", len(manifest["files"]), len(manifest["reports"]))  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    sys.exit(main())
