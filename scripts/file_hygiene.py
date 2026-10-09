"""File hygiene: encoding and corruption checks, deliberately not language checks.

This tool used to enforce that project files were written in English, allowing Traditional
Chinese only under an allow-list of path markers (`.tmp/`, `docs/zh-TW/`, `openspec/`,
`report.md`, and so on). That rule was removed on 2026-08-23 at the repository owner's
request: the allow-list had to be widened every time a legitimately Chinese artifact
appeared in a new place, and the failure mode was always the same -- work finished, then
blocked at commit, then reworded or relocated to satisfy a gate that protected nothing the
owner wanted protected. Prose language is now a matter of judgement, not of tooling.

Two conventions survive as conventions, not as checks, because they are interoperability
requirements rather than style: commit messages and code identifiers stay English, so that
`git log`, diffs and tracebacks stay legible to tools and to contributors who do not read
Chinese. See AGENTS.md.

What is still checked here is language-neutral:

  encoding      the file must decode as UTF-8
  corruption    the file must not contain U+FFFD, which only appears when a decode has
                already failed somewhere upstream and was papered over

The second one matters because mojibake used to be caught as a side effect of the CJK
scan -- the full-width punctuation range it matched is exactly what garbled Chinese
produces. Dropping the language rule without replacing that would have quietly removed a
genuine corruption check along with a style one.
"""

import argparse
import io
import logging
import os
import sys
from typing import Any

RichHandler: Any
try:
    from rich.logging import RichHandler
except ImportError:
    RichHandler = None

LOGGER = logging.getLogger("file_hygiene")

# Written as an escape, not the literal glyph: this file is itself checked, and a literal
# U+FFFD here would make the tool reject its own source.
REPLACEMENT_CHAR = "\ufffd"


def check_file_hygiene(filepath: str) -> bool:
    """Validate that a file is UTF-8 and free of decode corruption. True if valid."""
    if not os.path.exists(filepath):
        return True

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        LOGGER.error("Error: %s is NOT valid UTF-8. Please ensure file encoding is UTF-8 (without BOM).", filepath)
        return False
    except Exception as e:
        LOGGER.error("Error reading %s: %s", filepath, e)
        return False

    for index, line in enumerate(content.splitlines(), start=1):
        if REPLACEMENT_CHAR in line:
            LOGGER.error("Error: replacement character (U+FFFD) found in %s at line %s:", filepath, index)
            LOGGER.error("  > %s", line.strip())
            LOGGER.error(
                "Note: U+FFFD means text was decoded with the wrong codec somewhere upstream. Recover the original bytes rather than deleting the character."
            )
            return False

    return True


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    handler: logging.Handler
    if RichHandler is not None:
        handler = RichHandler(markup=False, show_path=False, show_time=False)
    else:
        handler = logging.StreamHandler()
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[handler])

    parser = argparse.ArgumentParser(description="File Hygiene Tool: validates UTF-8 encoding and decode corruption.")
    parser.add_argument("--file", nargs="+", dest="files", required=True, help="Specific files to check.")
    args = parser.parse_args()

    failed = False
    for f in args.files:
        if not check_file_hygiene(f):
            failed = True

    sys.exit(2 if failed else 0)


if __name__ == "__main__":
    main()
