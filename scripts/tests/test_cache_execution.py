"""Public cache APIs execute fresh source in isolated synthetic checkouts."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from research_core import cache_execution


def test_loaded_source_guard_rejects_unregistered_or_changed_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "implementation.py"
    path.write_bytes(b"value = 1\n")
    monkeypatch.setattr(cache_execution, "_LOADED_SOURCES", {})
    with pytest.raises(ValueError, match="loaded implementation differs"):
        cache_execution.require_loaded({"implementation.py": path})
    digest = cache_execution.hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(cache_execution, "_LOADED_SOURCES", {path.resolve(): digest})
    cache_execution.require_loaded({"implementation.py": path})
    path.write_bytes(b"value = 2\n")
    with pytest.raises(ValueError, match="loaded implementation differs"):
        cache_execution.require_loaded({"implementation.py": path})


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repository = Path(__file__).resolve().parents[2]
    clone = tmp_path / "checkout"
    for name in (
        "research_core/__init__.py",
        "research_core/derived_cache.py",
        "research_core/price_basis.py",
        "research_core/derived_features.py",
        "research_core/artifact_store.py",
        "research_core/cache_execution.py",
        "StockProject/engine/__init__.py",
        "StockProject/engine/data_loader.py",
        "scripts/__init__.py",
        "scripts/verify_research_cache.py",
        "scripts/validate_hhhl_cache_compatibility.py",
        "research_core/patterns/hhhl/source.py",
        "research_core/patterns/hhhl/sources.json",
        "research_core/patterns/hhhl/v4/sources.zip",
    ):
        destination = clone / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / name, destination)
    package = repository / "StockProject/__init__.py"
    if package.exists():
        shutil.copyfile(package, clone / "StockProject/__init__.py")
    else:
        (clone / "StockProject/__init__.py").write_text("", encoding="utf-8")
    return clone


CALLER_SETUP = """
import json
import os
from pathlib import Path

import pandas as pd

from research_core import artifact_store, derived_cache, derived_features
from scripts.verify_research_cache import recompute

assert Path(derived_cache.__file__).resolve().parent.parent == Path.cwd()
assert derived_features.SMA_PERIODS[0] == 5
dates = pd.date_range("2020-01-01", periods=75)
bars = pd.DataFrame({
    "Code": "2330", "Date": dates, "Open": 100.0, "High": 101.0,
    "Low": 99.0, "Close": 100.0, "Volume": 10.0,
})
events = pd.DataFrame(columns=pd.Index(["code", "ex_date", "event_type", "price_factor"]))
prices, actions, calendar = (Path(name) for name in ("prices.parquet", "actions.parquet", "calendar.json"))
bars.to_parquet(prices, index=False)
events.to_parquet(actions, index=False)
calendar.write_text(json.dumps({"dates": [day.date().isoformat() for day in dates], "basis": "synthetic"}), encoding="utf-8")
arguments = {"prices": prices, "actions": actions, "calendar": calendar, "root": Path("cache"), "cutoff": "2020-03-15"}

def change_source():
    path = Path(derived_features.__file__)
    before = path.stat()
    old = path.read_bytes()
    new = old.replace(b"SMA_PERIODS = (5, 10, 20, 60, 120)", b"SMA_PERIODS = (6, 10, 20, 60, 120)")
    assert old != new and len(old) == len(new)
    path.write_bytes(new)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert derived_features.SMA_PERIODS[0] == 5
    return new

def cache_bytes(version):
    return {path.relative_to(version).as_posix(): path.read_bytes() for path in version.rglob("*") if path.is_file()}
"""


def run_caller(checkout: Path, scenario: str, *, stream_encoding: str | None = None) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(CALLER_SETUP) + textwrap.dedent(scenario)],
        cwd=checkout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": stream_encoding} if stream_encoding else None,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, f"Caller failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


def test_public_build_uses_updated_source_despite_stale_caller_and_pyc(checkout: Path) -> None:
    result = run_caller(
        checkout,
        """
        changed = change_source()
        receipt = derived_cache.build_cache(**arguments)
        version = Path(receipt["manifest_path"]).parent
        daily = derived_cache.read_cached(version, "raw", "2330")
        assert "SMA6" in daily and "SMA5" not in daily
        assert daily.SMA6.iloc[5] == 100.0
        manifest = derived_cache.verify_cache(version)
        assert (version / "implementation/derived_features.py").read_bytes() == changed
        assert manifest["identity"]["implementation"]["derived_features.py"] == artifact_store.file_digest(Path(derived_features.__file__))
        assert recompute(version)["complete"] is True
        print(json.dumps({"fresh_sma": True, "retained_source": True}))
    """,
    )
    assert result == {"fresh_sma": True, "retained_source": True}


def test_public_recompute_rejects_disk_update_after_caller_import(checkout: Path) -> None:
    result = run_caller(
        checkout,
        """
        receipt = derived_cache.build_cache(**arguments)
        version = Path(receipt["manifest_path"]).parent
        before = cache_bytes(version)
        original = derived_cache.read_cached(version, "raw", "2330")
        change_source()
        try:
            recompute(version)
        except ValueError as error:
            assert "current implementation differs from pinned cache" in str(error)
        else:
            raise AssertionError("recompute accepted a changed implementation")
        assert derived_cache.verify_cache(version)["version_id"] == receipt["version_id"]
        pd.testing.assert_frame_equal(derived_cache.read_cached(version, "raw", "2330"), original)
        assert cache_bytes(version) == before
        print(json.dumps({"recompute_rejected": True, "pinned_cache_readable": True}))
    """,
    )
    assert result == {"recompute_rejected": True, "pinned_cache_readable": True}


def test_public_build_reuse_and_recompute_succeed(checkout: Path) -> None:
    result = run_caller(
        checkout,
        """
        first = derived_cache.build_cache(**arguments)
        version = Path(first["manifest_path"]).parent
        before = cache_bytes(version)
        second = derived_cache.build_cache(**arguments)
        assert first["version_id"] == second["version_id"]
        assert first["computed_symbols"] == 1
        assert second["computed_symbols"] == 0 and second["reused_symbols"] == 1
        parity = recompute(version)
        assert parity["complete"] is True and len(parity["checked"]) == 3
        assert parity["version_id"] == first["version_id"]
        assert cache_bytes(version) == before
        print(json.dumps({"build": True, "reuse": True, "recompute": True}))
    """,
    )
    assert result == {"build": True, "reuse": True, "recompute": True}


def test_public_worker_protocol_handles_cp950_and_unicode_paths(checkout: Path) -> None:
    result = run_caller(
        checkout,
        """
        from research_core import cache_execution
        # Simulate a long-lived caller that still holds the pre-fix bootstrap.
        legacy_config = ("for stream in (sys.stdin, sys.stdout, sys.stderr):\\n"
                         "    stream.reconfigure(encoding='utf-8')\\n")
        cache_execution._BOOTSTRAP = cache_execution._BOOTSTRAP.replace(legacy_config, "")
        arguments['root'] = Path('中文快取')
        first = derived_cache.build_cache(**arguments)
        assert '中文快取' in first['manifest_path']
        version = Path(first['manifest_path']).parent
        assert derived_cache.build_cache(**arguments)['reused_symbols'] == 1
        assert recompute(version)['complete'] is True
        try:
            derived_cache.build_cache(**{**arguments, 'prices': Path('缺少報價.parquet')})
        except ValueError as error:
            assert '缺少報價.parquet' in str(error)
        else:
            raise AssertionError('missing input did not fail')
        print(json.dumps({'unicode_receipt': True, 'unicode_diagnostic': True}))
        """,
        stream_encoding="cp950",
    )
    assert result == {"unicode_receipt": True, "unicode_diagnostic": True}


def test_public_compatibility_receipt_uses_fresh_source_and_fixed_inventory(checkout: Path) -> None:
    result = run_caller(
        checkout,
        """
        from scripts.validate_hhhl_cache_compatibility import validate
        Path('cases.json').write_text(json.dumps([{'id':'synthetic','code':'2330','date':'2020-03-15','kind':'rule'}]), encoding='utf-8')
        built = derived_cache.build_cache(**arguments)
        version = Path(built['manifest_path']).parent
        assert validate(inputs=Path('.'), cutoff='2020-03-15', cache_version=version)['cache_version'] == built['version_id']
        change_source()
        receipt = validate(inputs=Path('.'), cutoff='2020-03-15')
        assert receipt['checks']['original_25_case_inventory'] is False
        assert receipt['legacy_passed'] is False
        assert receipt['implementation_sha256']['derived_features.py'] == artifact_store.file_digest(Path(derived_features.__file__))
        try:
            validate(inputs=Path('.'), cutoff='2020-03-15', cache_version=version)
        except ValueError as error:
            assert 'explicit cache implementation differs from current execution' in str(error)
        else:
            raise AssertionError('compatibility accepted stale cache implementation')
        print(json.dumps({'fresh_compatibility': True, 'not_original_inventory': True}))
        """,
    )
    assert result == {"fresh_compatibility": True, "not_original_inventory": True}
