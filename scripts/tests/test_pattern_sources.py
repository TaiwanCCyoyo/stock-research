"""Source preservation and explicit inert-archive loading, not owner approval."""

import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.patterns.hhhl import source
from research_core.patterns.hhhl.source import load_detector, verify_sources


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4"])
def test_exact_source_versions_are_preserved_and_load_pure_detector(version: str):
    texts = verify_sources(version)
    assert f"hhhl_rule_{version}.py" in texts
    detector = load_detector(version)
    dates = pd.date_range("2020-01-01", periods=50)
    frame = pd.DataFrame({
        "Open": 100.0,
        "High": 101.0,
        "Low": 99.0,
        "Close": 100.0,
        "VolumeLots": 1000.0,
        "RawClose": 100.0,
        "atr14_pct": 0.02,
        "asof_date": dates,
    })
    assert isinstance(detector(frame), list)
    assert np.isfinite(frame.Close).all()


def test_unknown_source_version_is_not_guessed():
    with pytest.raises(ValueError, match="unregistered"):
        verify_sources("v5")


def test_detector_from_captured_sources_never_verifies_again(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = verify_sources("v4")

    def unexpected_read(version: str) -> dict[str, str]:
        raise AssertionError("captured detector must not reread source")

    monkeypatch.setattr(source, "verify_sources", unexpected_read)
    assert callable(source._detector_from_sources("v4", texts))


def test_archive_hash_and_members_use_same_captured_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = verify_sources("v4")
    (tmp_path / "v4").mkdir()
    shutil.copyfile(source.ROOT / "sources.json", tmp_path / "sources.json")
    archive_path = tmp_path / "v4/sources.zip"
    shutil.copyfile(source.ROOT / "v4/sources.zip", archive_path)
    monkeypatch.setattr(source, "ROOT", tmp_path)
    original_zipfile = zipfile.ZipFile
    observed: list[Any] = []

    def replace_disk_before_archive_parse(file: Any, *args: Any, **kwargs: Any) -> zipfile.ZipFile:
        observed.append(file)
        archive_path.write_bytes(b"replacement archive after hash capture")
        return original_zipfile(file, *args, **kwargs)

    monkeypatch.setattr(source.zipfile, "ZipFile", replace_disk_before_archive_parse)

    assert verify_sources("v4") == expected
    assert len(observed) == 1 and isinstance(observed[0], BytesIO)
    assert archive_path.read_bytes() == b"replacement archive after hash capture"


def test_oversized_archive_rejected_before_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "v4").mkdir()
    shutil.copyfile(source.ROOT / "sources.json", tmp_path / "sources.json")
    (tmp_path / "v4/sources.zip").write_bytes(b"x" * 1_000_001)
    monkeypatch.setattr(source, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="HHHL archive exceeds size limit"):
        verify_sources("v4")
