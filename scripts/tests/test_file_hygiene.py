"""What file hygiene checks now, and what it deliberately no longer checks.

The language rule was removed on 2026-08-23 (see `scripts/file_hygiene.py`). The first test
below pins that removal rather than assuming it: this repository is a fork of
`agent-starter-kit`, whose upstream still enforces English, so a future
`/fork-maintenance-sync` could reintroduce the check silently. A test that fails when
Chinese is rejected turns that into a visible conflict to resolve rather than a quiet
regression.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.file_hygiene import check_file_hygiene


class FileHygieneTests(unittest.TestCase):
    def _write(self, name: str, data: bytes) -> str:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def test_traditional_chinese_is_accepted_anywhere(self) -> None:
        """The language rule is gone; this pins it against an upstream sync restoring it."""
        for name in ("docs/en/guide.md", "StockProject/engine/example.py", "README.md"):
            path = self._write(name, "# 標題\n\n這段是中文，現在應該通過。\n".encode())
            self.assertTrue(check_file_hygiene(path), f"{name} should be accepted")

    def test_non_utf8_is_rejected(self) -> None:
        path = self._write("sample.md", b"\xff\xfe")
        self.assertFalse(check_file_hygiene(path))

    def test_replacement_character_is_rejected(self) -> None:
        """U+FFFD only appears after a decode already failed upstream -- that is corruption."""
        path = self._write("sample.md", ("ok line\nbroken: " + "\ufffd" + " here\n").encode())
        self.assertFalse(check_file_hygiene(path))

    def test_clean_ascii_file_passes(self) -> None:
        path = self._write("sample.md", b"# Title\n\nPlain English content.\n")
        self.assertTrue(check_file_hygiene(path))

    def test_missing_file_is_not_a_failure(self) -> None:
        """Pre-commit can hand over a path that a previous hook deleted."""
        self.assertTrue(check_file_hygiene("does-not-exist-anywhere.md"))

    def test_relative_path_is_resolved_against_cwd(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "nested").mkdir()
        (root / "nested" / "sample.md").write_bytes(b"\xff\xfe")

        current = Path.cwd()
        try:
            os.chdir(root)
            self.assertFalse(check_file_hygiene("nested/sample.md"))
        finally:
            os.chdir(current)


if __name__ == "__main__":
    unittest.main()
