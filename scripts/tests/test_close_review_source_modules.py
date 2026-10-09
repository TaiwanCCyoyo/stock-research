"""Source-origin and packet-closure guards use tiny synthetic modules only."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

LOCATION = Path(__file__).resolve().parents[2] / "tasks/20261005-relative-strength-holding/source_modules.py"
SPEC = importlib.util.spec_from_file_location("h05_source_modules_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
sources = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sources
SPEC.loader.exec_module(sources)


@pytest.mark.parametrize("filename", ["source_modules.py", "source_bindings.py"])
def test_entrypoint_import_without_preexisting_project_path(tmp_path: Path, filename: str) -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import runpy, sys; runpy.run_path(sys.argv[1], run_name='h05_import_smoke')", str(LOCATION.with_name(filename))],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_exact_origin_reuse_and_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, other = tmp_path / "first.py", tmp_path / "other.py"
    first.write_text("value = 7\n", encoding="utf-8")
    other.write_text("value = 9\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "h05_synthetic_leaf", raising=False)
    result = sources.load_exact("h05_synthetic_leaf", first)
    assert result.value == 7
    assert sources.load_exact("h05_synthetic_leaf", first) is result
    with pytest.raises(sources.SourceModuleError, match="conflicting module origin"):
        sources.load_exact("h05_synthetic_leaf", other)
    assert sys.modules["h05_synthetic_leaf"] is result
    monkeypatch.delitem(sys.modules, "h05_synthetic_leaf")


def test_failed_import_cannot_leave_partial_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "bad.py"
    path.write_text("value = 7\nraise ValueError('bad source')\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "h05_failing_leaf", raising=False)
    with pytest.raises(ValueError, match="bad source"):
        sources.load_exact("h05_failing_leaf", path)
    assert "h05_failing_leaf" not in sys.modules


def test_packet_must_declare_import_and_exact_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "leaf.py"
    path.write_text("value = 7\n", encoding="utf-8")
    module = ModuleType("h05_closure_fixture")
    module.__file__ = str(path)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert sources.local_source_paths(tmp_path) == (path,)
    with pytest.raises(sources.SourceModuleError, match="unregistered local import"):
        sources.require_declared_imports({}, root=tmp_path)
    declaration = {"leaf.py": hashlib.sha256(path.read_bytes()).hexdigest()}
    sources.require_declared_imports(declaration, root=tmp_path)
    path.write_text("value = 8\n", encoding="utf-8")
    with pytest.raises(sources.SourceModuleError, match="registered local source changed"):
        sources.require_declared_imports(declaration, root=tmp_path)


def test_wrong_core_submodule_origin_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources.check_core_origin(LOCATION.parents[2])
    wrong = ModuleType("research_core.synthetic_wrong_origin")
    wrong.__file__ = str(tmp_path / "ledger.py")
    monkeypatch.setitem(sys.modules, wrong.__name__, wrong)
    with pytest.raises(sources.SourceModuleError, match="outside active checkout"):
        sources.check_core_origin(LOCATION.parents[2])


def test_execution_closure_is_portable_but_full_sources_still_require_primary_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing_primary = tmp_path / "missing-primary"
    monkeypatch.setattr(sources, "EVIDENCE_ROOT", missing_primary)
    modules = sources.load_execution_adapters()
    assert {"no_trade_execution", "resumption_execution", "event_limits", "valuation"}.issubset(modules)
    for module in modules.values():
        assert module.__file__ is not None
        assert Path(module.__file__).resolve().is_relative_to(sources.ACTIVE_ROOT.resolve())
    assert callable(modules["no_trade_execution"].build_execution)
    assert callable(modules["resumption_execution"].extend_factory)
    assert not missing_primary.exists()
    with pytest.raises((FileNotFoundError, sources.SourceModuleError), match="missing-primary"):
        sources.load_adapters()


def test_retained_features_load_from_isolated_checkout_with_exact_bytes(tmp_path: Path) -> None:
    isolated = tmp_path / "independent checkout with spaces"
    module_path = isolated / "tasks/20261005-relative-strength-holding/source_modules.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_bytes(LOCATION.read_bytes())
    core = isolated / "research_core"
    core.mkdir()
    (core / "__init__.py").write_text("", encoding="utf-8")
    original_root = LOCATION.parents[2]
    # the retained rotation generators resolve their producer inputs through this shared helper
    (core / "producer_data.py").write_bytes((original_root / "research_core/producer_data.py").read_bytes())
    relative_root = Path("tasks/20260823-rotation-universe")
    for name in ("eligibility", "features"):
        relative = relative_root / f"{name}.py"
        target = isolated / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((original_root / relative).read_bytes())
    program = r"""
import hashlib, importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("isolated_h05", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root = path.parents[2]
assert module.ACTIVE_ROOT == root
assert module.EVIDENCE_ROOT == root
# Keep the actual rotation imports, isolating only unrelated private closures.
module.load_execution_adapters = lambda: {}
try:
    module.load_adapters()
except FileNotFoundError as error:
    assert pathlib.Path(error.filename).is_relative_to(root / ".tmp" / "claude-kline")
else:
    raise AssertionError("missing private sources were accepted")
module.SCRATCH_SOURCES = ()
module.RESTORED_SOURCES = ()
module.load_adapters()
declared = {}
for name in ("eligibility", "features"):
    expected = root / "tasks/20260823-rotation-universe" / (name + ".py")
    assert pathlib.Path(sys.modules[name].__file__).resolve() == expected.resolve()
    declared[expected.relative_to(root).as_posix()] = hashlib.sha256(expected.read_bytes()).hexdigest()
assert sys.modules["features"].add_eligibility_columns is sys.modules["eligibility"].add_eligibility_columns
for source in module.local_source_paths(root):
    declared[source.relative_to(root).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
module.require_declared_imports(declared, root=root)
changed = root / "tasks/20260823-rotation-universe/eligibility.py"
changed.write_bytes(changed.read_bytes() + b"\n# synthetic tamper\n")
try:
    module.require_declared_imports(declared, root=root)
except module.SourceModuleError as error:
    assert "registered local source changed" in str(error)
else:
    raise AssertionError("changed source was accepted")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(module_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    for name in ("eligibility", "features"):
        relative = relative_root / f"{name}.py"
        original = (original_root / relative).read_bytes()
        copied = (isolated / relative).read_bytes()
        if name == "eligibility":
            copied = copied.removesuffix(b"\n# synthetic tamper\n")
        assert hashlib.sha256(copied).digest() == hashlib.sha256(original).digest()
