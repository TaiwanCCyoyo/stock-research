"""Fresh-source boundaries use copied implementations and invented inputs only."""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def execution_checkout(tmp_path: Path) -> Path:
    repository = Path(__file__).resolve().parents[2]
    checkout = tmp_path / "execution-checkout"
    for source in (repository / "research_core").rglob("*"):
        if source.is_file() and source.suffix in {".py", ".zip", ".json"}:
            target = checkout / source.relative_to(repository)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for name in ("StockProject/engine/data_loader.py", "StockProject/engine/__init__.py"):
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / name, target)
    package = repository / "StockProject/__init__.py"
    if package.exists():
        shutil.copyfile(package, checkout / "StockProject/__init__.py")
    else:
        (checkout / "StockProject/__init__.py").write_text("", encoding="utf-8")
    return checkout


CALLER_SETUP = """
import hashlib
import json
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from research_core import research_data_incremental as incremental
from research_core import derived_features_chunk_v2 as kernel
from research_core import hhhl_variants_paths as outcomes
from research_core.artifact_store import file_digest
from research_core.research_data_catalog import DataCatalog, verify_entry
from research_core.research_data_paths import DataRoots

root = Path.cwd()
assert Path(incremental.__file__).resolve().parents[1] == root
primary = root / "primary"
(primary / ".git").mkdir(parents=True)
catalog = DataCatalog(DataRoots(primary, primary / "research_data"))
dates = pd.DatetimeIndex(pd.bdate_range("2010-01-04", periods=40).values, name="Date")
frame = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Quality": True}, index=dates)
closes = np.linspace(100.0, 150.0, len(dates))

def build(base=None):
    return incremental.build_incremental_features(
        catalog, {"INVENTED": frame}, ["SMA20"], factor_ids={"INVENTED": "invented-factor"},
        price_basis="synthetic", base=base, calculation_authorized=True)

def forward(base=None):
    return incremental.publish_forward_series(
        catalog, "INVENTED", dates, closes, price_basis="synthetic", factor_id="invented-factor",
        horizon=10, base=base, calculation_authorized=True)

def bundle_bytes(entry):
    directory = (catalog.roots.data / entry["manifest"]["path"]).parent
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}

def mutate(path, before, after):
    observed = path.stat()
    original = path.read_bytes()
    assert original.count(before) == 1
    updated = original.replace(before, after)
    assert updated != original
    path.write_bytes(updated)
    os.utime(path, ns=(observed.st_atime_ns, observed.st_mtime_ns))
    return hashlib.sha256(updated).hexdigest()

def pinned_source(entry, name):
    discovery = catalog.get(entry["data_id"], entry["version_id"], manifest_sha256=entry["manifest"]["sha256"])
    return verify_entry(discovery, catalog.roots)["metadata"]["implementation"]["sources"][name]
"""


def run_caller(checkout: Path, scenario: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(CALLER_SETUP) + textwrap.dedent(scenario)],
        cwd=checkout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, f"Synthetic caller failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


def test_checkpoint_public_api_uses_new_numerical_source_after_caller_import(execution_checkout: Path) -> None:
    result = run_caller(
        execution_checkout,
        """
        path = Path(kernel.__file__)
        original_hash = file_digest(path)
        first = build()
        original_daily, _ = incremental.load_incremental_feature(catalog, first, "INVENTED", "SMA20")
        assert original_daily.SMA20.iloc[-1] == 100.0
        before = bundle_bytes(first)
        changed_hash = mutate(path,
            b"daily.iat[local_index, daily.columns.get_loc(name)] = value",
            b"daily.iat[local_index, daily.columns.get_loc(name)] = value + 7.0")
        # This caller's already-imported function still computes the original formula.
        stale_daily, _, _ = kernel.compute_selected_full(frame, ["SMA20"])
        assert stale_daily.SMA20.iloc[-1] == 100.0
        second = build(first)
        fresh_daily, _ = incremental.load_incremental_feature(catalog, second, "INVENTED", "SMA20")
        assert fresh_daily.SMA20.iloc[-1] == 107.0
        assert second["extension_receipt"]["stocks"]["INVENTED"]["full_stock_rebuild"] is True
        source = "research_core/derived_features_chunk_v2.py"
        assert pinned_source(first, source) == original_hash
        assert pinned_source(second, source) == changed_hash == file_digest(path)
        assert first["version_id"] != second["version_id"]
        assert bundle_bytes(first) == before
        pd.testing.assert_frame_equal(incremental.load_incremental_feature(catalog, first, "INVENTED", "SMA20")[0], original_daily)
        print(json.dumps({"fresh_values": True, "actual_source_pin": True, "old_bundle_retained": True}))
        """,
    )
    assert result == {"fresh_values": True, "actual_source_pin": True, "old_bundle_retained": True}


def test_forward_public_api_uses_new_outcome_source_despite_stale_caller_and_pyc(execution_checkout: Path) -> None:
    result = run_caller(
        execution_checkout,
        """
        path = Path(outcomes.__file__)
        original_hash = file_digest(path)
        first = forward()
        original = incremental.load_forward_series(catalog, first)
        assert original.label.iloc[0] == "flat-win"
        before = bundle_bytes(first)
        # Same size and timestamp also exercise timestamp-valid stale bytecode.
        changed_hash = mutate(path, b"(ratio >= 2.0)", b"(ratio >= 1.1)")
        assert incremental.outcomes_for_closes(closes, 10).label.iloc[0] == "flat-win"
        second = forward(first)
        fresh = incremental.load_forward_series(catalog, second)
        assert fresh.label.iloc[0] == "hit"
        assert second["extension_receipt"]["mode"] == "full_rebuild"
        source = "research_core/hhhl_variants_paths.py"
        assert pinned_source(first, source) == original_hash
        assert pinned_source(second, source) == changed_hash == file_digest(path)
        assert first["version_id"] != second["version_id"]
        assert bundle_bytes(first) == before
        pd.testing.assert_frame_equal(incremental.load_forward_series(catalog, first), original)
        print(json.dumps({"fresh_values": True, "actual_source_pin": True, "old_bundle_retained": True}))
        """,
    )
    assert result == {"fresh_values": True, "actual_source_pin": True, "old_bundle_retained": True}


@pytest.mark.parametrize("operation", ["features", "forward"])
def test_private_calculation_rejects_source_change_before_any_publication(execution_checkout: Path, operation: str) -> None:
    result = run_caller(
        execution_checkout,
        """
        operation = OPERATION
        # Registry injection lives in this isolated caller only and captures copied bytes.
        captured = {}
        for name, module in tuple(sys.modules.items()):
            location = getattr(module, "__file__", None)
            if name.split(".", 1)[0] in {"research_core", "StockProject", "scripts"} and location:
                path = Path(location).resolve()
                if path.is_relative_to(root) and path.suffix == ".py":
                    captured[path] = file_digest(path)
        incremental.cache_execution._LOADED_SOURCES = captured
        if operation == "features":
            source = Path(kernel.__file__)
            original_compute = kernel.compute_selected_full
        else:
            source = Path(outcomes.__file__)
            original_compute = incremental.outcomes_for_closes

        def changed_during_calculation(*args, **kwargs):
            computed = original_compute(*args, **kwargs)
            source.write_bytes(source.read_bytes() + b"\\n# injected change during synthetic calculation\\n")
            return computed

        assert not catalog.roots.data.exists()
        if operation == "features":
            kernel.compute_selected_full = changed_during_calculation
            calculate = lambda: incremental._build_incremental_features_in_process(
                catalog, {"INVENTED": frame}, ["SMA20"], factor_ids={"INVENTED": "invented-factor"},
                price_basis="synthetic", calculation_authorized=True)
        else:
            incremental.outcomes_for_closes = changed_during_calculation
            calculate = lambda: incremental._publish_forward_series_in_process(
                catalog, "INVENTED", dates, closes, price_basis="synthetic", factor_id="invented-factor",
                horizon=10, calculation_authorized=True)
        try:
            calculate()
        except ValueError as error:
            assert "loaded implementation differs from source" in str(error), str(error)
            assert source.name in str(error)
        else:
            raise AssertionError("changed source was published with stale code")
        assert not catalog.roots.data.exists()
        assert not list(primary.rglob("manifest.json"))
        assert not list(primary.rglob("catalog.json"))
        print(json.dumps({"changed_source_rejected": True, "nothing_published": True}))
        """.replace("OPERATION", repr(operation)),
    )
    assert result == {"changed_source_rejected": True, "nothing_published": True}
