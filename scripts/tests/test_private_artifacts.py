import gzip
import json
import zlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.private_artifacts import create_private_artifact_router, read_private_artifact


@pytest.mark.parametrize("name", ["opportunity-explorer", "saved-research-runs"])
def test_corrupt_deflate_is_unavailable_without_private_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    # Valid gzip header, then a reserved DEFLATE block type (BTYPE=3).
    corrupt = bytes.fromhex("1f8b08000000000002ff07") + b"private-evidence-marker"
    with pytest.raises(zlib.error):
        gzip.decompress(corrupt)
    (tmp_path / f"{name}.json.gz").write_bytes(corrupt)
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    monkeypatch.setenv("STOCK_PRIVATE_ARTIFACT_ROOT", str(tmp_path))
    application = FastAPI()
    application.include_router(create_private_artifact_router())
    response = TestClient(application).get(f"/private-artifacts/v1/{name}")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "unavailable"
    assert response.json() == {"detail": "private data unavailable or invalid"}
    assert str(tmp_path) not in response.text
    assert "private-evidence-marker" not in response.text


def test_private_external_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = FastAPI()
    application.include_router(create_private_artifact_router())
    client = TestClient(application)
    assert client.get("/private-artifacts/v1/opportunity-explorer").status_code == 503
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    monkeypatch.setenv("STOCK_PRIVATE_ARTIFACT_ROOT", str(tmp_path))
    file = tmp_path / "opportunity-explorer.json.gz"
    file.write_bytes(gzip.compress(json.dumps({"kind": "test-private"}).encode()))
    assert client.get("/private-artifacts/v1/opportunity-explorer").json() == {"kind": "test-private", "dataMode": "local-private", "synthetic": False}
    assert client.get("/private-artifacts/v1/saved-research-runs").status_code == 503
    assert client.get("/private-artifacts/v1/other").status_code == 404
    file.write_bytes(b"not-gzip")
    assert client.get("/private-artifacts/v1/opportunity-explorer").status_code == 503


def test_absolute_path_and_allowlist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        read_private_artifact("opportunity-explorer", Path("relative"))
    with pytest.raises(ValueError, match="unknown"):
        read_private_artifact("../secret", tmp_path)


def test_built_frontend_api_alias_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_api.main import create_app

    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    client = TestClient(create_app())
    response = client.get("/api/private-artifacts/v1/opportunity-explorer")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "unavailable"


def test_bounded_decode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("research_api.private_artifacts.MAX_BYTES", 100)
    (tmp_path / "opportunity-explorer.json.gz").write_bytes(gzip.compress(b"x" * 101))
    with pytest.raises(ValueError, match="decoded"):
        read_private_artifact("opportunity-explorer", tmp_path)
