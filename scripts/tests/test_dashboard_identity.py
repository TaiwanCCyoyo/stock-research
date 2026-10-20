from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from research_core.dashboard_identity import dashboard_identity


def test_identity_normalizes_paths_without_reading_files(tmp_path: Path) -> None:
    environment = {
        "STOCK_RESEARCH_DATA_MODE": "local-private",
        "STOCK_PRIVATE_ARTIFACT_ROOT": str(tmp_path),
        "STOCK_SAVED_STUDIO_PACKAGE": str(tmp_path / "folder" / ".." / "package.json"),
    }
    expected = {**environment, "STOCK_SAVED_STUDIO_PACKAGE": str(tmp_path / "package.json")}
    with patch.object(Path, "read_bytes", side_effect=AssertionError("must not load evidence")):
        assert dashboard_identity(environment) == dashboard_identity(expected)
    assert str(tmp_path) not in str(dashboard_identity(environment))
    assert dashboard_identity(environment) != dashboard_identity({**environment, "STOCK_PRIVATE_ARTIFACT_ROOT": str(tmp_path / "other")})


def test_api_identity_is_startup_snapshot_and_does_not_load_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_api.main import create_app

    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    monkeypatch.setenv("STOCK_PRIVATE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", str(tmp_path / "first.json"))
    with (
        patch("research_api.main.HistoryCapture") as capture,
        patch("research_core.saved_research_studio.SavedResearchStudio._load", side_effect=AssertionError("no studio load")),
    ):
        application = create_app()
        expected = application.state.dashboard_identity.copy()
        monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", str(tmp_path / "second.json"))
        with TestClient(application) as client:
            payload = client.get("/__research_service__").json()
        assert payload["configId"] == expected["configId"]
        assert payload["dataMode"] == "local-private"
        capture.return_value.assert_not_called()
