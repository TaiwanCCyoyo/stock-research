"""Load named retained adapters without invoking old strategies or market runs.

The execution packet must separately hash every returned local source path.
Module-origin checks are not a substitute for those immutable byte identities.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

ACTIVE_ROOT = Path(__file__).resolve().parents[2]
if str(ACTIVE_ROOT) not in sys.path:
    sys.path.insert(0, str(ACTIVE_ROOT))

import research_core  # noqa: E402

LOGGER = logging.getLogger(__name__)
EVIDENCE_ROOT = ACTIVE_ROOT
PROTOTYPE = "006-artifacts-5fe106d423484ccf959cc4e2e5d6f6d3/prototype"
EXECUTION_SOURCES = (
    ("prototype", "retained_execution/prototype/__init__.py"),
    ("prototype.execution_policy", "retained_execution/prototype/execution_policy.py"),
    ("prototype.providers", "retained_execution/prototype/providers.py"),
    ("modeled_execution", "retained_execution/modeled_execution.py"),
)
EXECUTION_LEAF_NAMES = frozenset({"event_limits", "valuation", "no_trade_execution", "resumption_execution"})
SCRATCH_SOURCES = (
    ("asof_signal_prices", "010-membership-signal/asof_signal_prices.py"),
    ("model", "025-signal-factor-inputs/model.py"),
    ("readset", "026-market-runtime/readset.py"),
    ("prototype.features_bridge", f"{PROTOTYPE}/features_bridge.py"),
    ("dual_price_features", "010-membership-signal/dual_price_features.py"),
    ("feature_panel", "026-market-runtime/feature_panel.py"),
    ("selection", "027-cash-runtime/selection.py"),
    ("cash_terms", "027-cash-runtime/cash_terms.py"),
    ("shares", "018-share-adapters/shares.py"),
    ("capital_returns", "018-share-adapters/capital_returns.py"),
    ("prototype.measurement_bridge", f"{PROTOTYPE}/measurement_bridge.py"),
    ("measurement", "018-share-adapters/measurement.py"),
)
RESTORED_SOURCES = (
    ("event_limits", "20260921-evening-pilot/event_limits.py"),
    ("corporate", "20260921-evening-pilot/corporate.py"),
    ("capital_event", "20260921-evening-pilot/capital_event.py"),
    ("stock_rights", "20260921-evening-pilot/stock_rights.py"),
    ("mixed_rights", "20260921-evening-pilot/mixed_rights.py"),
    ("paid_rights", "20260921-evening-pilot/paid_rights.py"),
    ("odd_lots", "20260921-evening-pilot/odd_lots.py"),
    ("valuation", "20260921-evening-pilot/valuation.py"),
    ("declined_6438", "20261002-small-probe/declined_6438.py"),
    ("declined_2641", "20261002-small-probe/declined_2641.py"),
    ("declined_3680", "20261002-one-lot-delay-resumption/declined_3680.py"),
    ("declined_6443", "20261002-one-lot-delay-resumption/declined_6443.py"),
    ("no_trade_execution", "20261002-momentum-probe/no_trade_execution.py"),
    ("resumption_execution", "20261002-one-lot-delay-resumption/resumption_execution.py"),
    ("source_binding", "20261002-one-lot-delay-resumption/source_binding.py"),
)


class SourceModuleError(ValueError):
    """An adapter resolved outside its declared source or active core."""


def load_exact(name: str, path: Path) -> ModuleType:
    """Reuse the identical module origin, but never replace a conflicting import."""
    path = path.resolve(strict=True)
    previous = sys.modules.get(name)
    if previous is not None:
        origin = getattr(previous, "__file__", None)
        if origin is None or Path(origin).resolve() != path:
            raise SourceModuleError(f"conflicting module origin: {name}: {origin}; expected {path}")
        return previous
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SourceModuleError(f"cannot load declared source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # Do not leave a partially initialized module available after a failure.
        if sys.modules.get(name) is module:
            del sys.modules[name]
        raise
    return module


def check_core_origin(active_root: Path) -> None:
    """Both an already-imported core and later core submodules must be active."""
    expected = (active_root / "research_core").resolve()
    for name, module in tuple(sys.modules.items()):
        if name == "research_core" or name.startswith("research_core."):
            origin = getattr(module, "__file__", None)
            if origin is None or not Path(origin).resolve().is_relative_to(expected):
                raise SourceModuleError(f"research core resolved outside active checkout: {name}: {origin}")


def load_execution_adapters() -> dict[str, ModuleType]:
    """Load the portable native execution closure without any market/source files."""
    check_core_origin(ACTIVE_ROOT)
    task_root = Path(__file__).resolve().parent
    modules = {name: load_exact(name, task_root / relative) for name, relative in EXECUTION_SOURCES}
    modules.update({name: load_exact(name, ACTIVE_ROOT / "tasks" / relative) for name, relative in RESTORED_SOURCES if name in EXECUTION_LEAF_NAMES})
    check_core_origin(ACTIVE_ROOT)
    LOGGER.info("Loaded %d portable execution entries using core %s", len(modules), research_core.__file__)
    return modules


def load_adapters() -> dict[str, ModuleType]:
    """Import the bounded code closure; do not read price tables or run accounts."""
    check_core_origin(ACTIVE_ROOT)
    scratch = EVIDENCE_ROOT / ".tmp/claude-kline"
    modules = load_execution_adapters()
    modules.update({name: load_exact(name, scratch / relative) for name, relative in SCRATCH_SOURCES})
    modules.update({name: load_exact(name, ACTIVE_ROOT / "tasks" / relative) for name, relative in RESTORED_SOURCES})
    # These retained feature-panel dependencies belong to the active checkout.
    # They are declared code, NOT permission to invoke their strategy runner.
    for name in ("eligibility", "features"):
        load_exact(name, ACTIVE_ROOT / "tasks/20260823-rotation-universe" / f"{name}.py")
    check_core_origin(ACTIVE_ROOT)
    LOGGER.info("Loaded %d declared adapter entries using core %s", len(modules), research_core.__file__)
    return modules


def local_source_paths(evidence_root: Path = EVIDENCE_ROOT) -> tuple[Path, ...]:
    """Return imported local code for complete packet closure, including lazy imports."""
    root = evidence_root.resolve()
    paths: set[Path] = set()
    for module in tuple(sys.modules.values()):
        origin = getattr(module, "__file__", None)
        if origin:
            path = Path(origin).resolve()
            if path.suffix == ".py" and path.is_relative_to(root) and ".venv" not in path.parts:
                paths.add(path)
    return tuple(sorted(paths))


def require_declared_imports(declared: Mapping[str, str], *, root: Path = EVIDENCE_ROOT) -> None:
    """Fail on unlisted local imports or bytes different from the sealed packet."""
    root = root.resolve()
    for path in local_source_paths(root):
        relative = path.relative_to(root).as_posix()
        expected = declared.get(relative)
        if expected is None:
            raise SourceModuleError(f"unregistered local import: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SourceModuleError(f"registered local source changed: {relative}")


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    loaded = load_adapters()
    print(json.dumps({"status": "adapter_imports_only", "entries": len(loaded), "local_code_files": len(local_source_paths()), "market_execution": False}))
