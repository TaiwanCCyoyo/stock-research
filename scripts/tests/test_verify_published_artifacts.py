"""The published-artifact inventory runs each reader and reports failures instead of hiding them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import verify_published_artifacts as inventory


def test_tracked_publication_passes_and_missing_local_input_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "rows.json"
    status = inventory.main(["--only", "owner-hhhl", "hhhl-v1", "--local-root", str(tmp_path / "no-local-artifacts"), "--json", str(out)])
    rows = {row["check"]: row["status"] for row in json.loads(out.read_text(encoding="utf-8"))}
    assert rows == {"owner-hhhl-labels.v1": "pass", "hhhl-v1 publication": "local-missing"}
    assert status == 0
    assert "local-missing" in capsys.readouterr().out


def test_a_failing_reader_fails_the_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def broken(_root: Path, _local: Path) -> tuple[str, str]:
        raise ValueError("synthetic reader failure")

    monkeypatch.setattr(inventory, "CHECKS", [inventory.Check("synthetic", broken)])
    assert inventory.main(["--local-root", str(tmp_path)]) == 1
