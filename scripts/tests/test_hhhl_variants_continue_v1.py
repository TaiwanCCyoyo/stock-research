"""Cache continuation refuses incomplete, changed or unrelated invented inputs."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core.artifact_store import write_json
from research_core.hhhl_variants_continue_v1 import OWNER, TASK, cache_seal, verified_cache


def cache_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, Any, dict[str, Any]]:
    source = tmp_path / TASK / "datasets/.staging-hhhl-v4-variants-01-invented"
    (source / "daily").mkdir(parents=True)
    pd.DataFrame({"value": [1.0, 2.0]}).to_parquet(source / "daily/0001.parquet", index=False)
    write_json(source / "execution-start.json", {"code_commit": "invented", "code_sha256": {}})
    pins = tmp_path / "pins.json"
    write_json(pins, {"invented": True})
    fake = SimpleNamespace(tables=[{"security_id": "TW:0050"}], pins={"calendar": {"rows": 2}}, verify_after=lambda: None)
    monkeypatch.setattr("research_core.hhhl_variants_continue_v1.FrozenInputs", lambda *_: fake)
    stopped = {"owner": OWNER, "code_commit": "invented", "pid": 123, "verified_stopped": True}
    return tmp_path, source, pins, fake, stopped


def test_cache_seal_and_verification_then_changed_bytes_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary, source, pins, fake, stopped = cache_fixture(tmp_path, monkeypatch)
    seal = cache_seal(primary, source, pins, stopped)
    assert len(seal["artifacts"]) == 1 and seal["artifacts"][0]["code"] == "0050"
    assert verified_cache(source, source / "daily-cache-seal.json", pins, fake) == seal
    with (source / "daily/0001.parquet").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="hash/size"):
        verified_cache(source, source / "daily-cache-seal.json", pins, fake)


@pytest.mark.parametrize("invalid", ["owner", "not_stopped", "code_commit", "rows", "missing", "extra", "outside"])
def test_cache_seal_rejects_invalid_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str) -> None:
    primary, source, pins, fake, stopped = cache_fixture(tmp_path, monkeypatch)
    if invalid == "owner":
        stopped["owner"] = "other session"
    elif invalid == "not_stopped":
        stopped["verified_stopped"] = False
    elif invalid == "code_commit":
        stopped["code_commit"] = "other implementation"
    elif invalid == "rows":
        fake.pins["calendar"]["rows"] = 3
    elif invalid == "missing":
        (source / "daily/0001.parquet").unlink()
    elif invalid == "extra":
        (source / "daily/unexpected.bin").write_bytes(b"invented")
    else:
        primary = tmp_path / "unrelated"
    with pytest.raises(ValueError):
        cache_seal(primary, source, pins, stopped)
    assert not (source / "daily-cache-seal.json").exists()


def test_cache_seal_cannot_replace_and_pins_cannot_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary, source, pins, fake, stopped = cache_fixture(tmp_path, monkeypatch)
    cache_seal(primary, source, pins, stopped)
    with pytest.raises(FileExistsError):
        cache_seal(primary, source, pins, stopped)
    pins.write_bytes(b"different pins")
    with pytest.raises(ValueError, match="pins"):
        verified_cache(source, source / "daily-cache-seal.json", pins, fake)
