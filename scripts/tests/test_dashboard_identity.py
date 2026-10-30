from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from research_core.dashboard_identity import CONFIG_VERSION, PRIVATE_PATH_KEYS, ROOT_KEYS, dashboard_identity


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


@pytest.mark.parametrize("key", (*ROOT_KEYS, *PRIVATE_PATH_KEYS))
@pytest.mark.parametrize("mode", ["local-private", "public-synthetic"])
def test_every_effective_source_path_changes_configuration_identity(tmp_path: Path, key: str, mode: str) -> None:
    environment = {"STOCK_RESEARCH_DATA_MODE": mode, key: str(tmp_path / "source-a")}
    original = dashboard_identity(environment)
    assert original["configVersion"] == CONFIG_VERSION
    assert original["configId"] != dashboard_identity({**environment, key: str(tmp_path / "source-b")})["configId"]
    assert original["configId"] != dashboard_identity({"STOCK_RESEARCH_DATA_MODE": mode})["configId"]


def test_identity_fallback_uses_primary_file_and_process_precedence(tmp_path: Path) -> None:
    values = {key: str(tmp_path / f"file-{index}") for index, key in enumerate((*ROOT_KEYS, *PRIVATE_PATH_KEYS))}
    (tmp_path / ".env.local").write_text("\n".join(f'{key}="{value}"' for key, value in values.items()), encoding="utf-8")
    with patch("research_core.dashboard_identity.primary_checkout", return_value=tmp_path):
        assert dashboard_identity({}, repo_root=tmp_path / "worktree") == dashboard_identity(values)
        process = {ROOT_KEYS[0]: str(tmp_path / "process-root")}
        assert dashboard_identity(process, repo_root=tmp_path / "worktree") == dashboard_identity({**values, **process})
        # An explicit unconfigured root prevents a later file fallback.
        assert dashboard_identity({ROOT_KEYS[0]: ""}, repo_root=tmp_path) == dashboard_identity({**values, ROOT_KEYS[0]: ""})


def test_explicit_mapping_without_repo_root_never_discovers_workstation_configuration() -> None:
    with patch("research_core.dashboard_identity.primary_checkout", side_effect=AssertionError("must remain deterministic")):
        assert dashboard_identity({}) == dashboard_identity({key: "" for key in (*ROOT_KEYS, *PRIVATE_PATH_KEYS)})


def test_api_identity_is_startup_snapshot_and_does_not_load_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_api.main import create_app

    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    monkeypatch.setenv("STOCK_PRIVATE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", str(tmp_path / "first.json"))
    for key in ROOT_KEYS:
        monkeypatch.setenv(key, str(tmp_path / key / "first"))
    with (
        patch("research_api.main.HistoryCapture") as capture,
        patch("research_core.saved_research_studio.SavedResearchStudio._load", side_effect=AssertionError("no studio load")),
    ):
        application = create_app()
        expected = application.state.dashboard_identity.copy()
        monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", str(tmp_path / "second.json"))
        for key in ROOT_KEYS:
            monkeypatch.setenv(key, str(tmp_path / key / "second"))
        with TestClient(application) as client:
            payload = client.get("/__research_service__").json()
        assert payload["configId"] == expected["configId"]
        assert payload["configVersion"] == CONFIG_VERSION
        assert payload["dataMode"] == "local-private"
        capture.return_value.assert_not_called()
