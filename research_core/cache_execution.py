"""Fresh-source process boundary for evidence-producing cache operations."""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import json
import subprocess
import sys
from io import TextIOWrapper
from pathlib import Path
from types import CodeType
from typing import Any, cast

_LOADED_SOURCES: dict[Path, str] = {}
_BOOTSTRAP = """
import hashlib, sys, types
from pathlib import Path
for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding='utf-8')
path = Path(sys.argv[1])
data = path.read_bytes()
sys.path.insert(0, str(path.parent.parent))
module = types.ModuleType('research_core.cache_execution')
module.__file__ = str(path)
module.__package__ = 'research_core'
module._ENTRY_SOURCE_SHA256 = hashlib.sha256(data).hexdigest()
sys.modules[module.__name__] = module
exec(compile(data, str(path), 'exec', dont_inherit=True), module.__dict__)
module._worker_main()
"""


class _SourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname: str) -> CodeType:
        """Compile observed source bytes, never a timestamp-validated old pyc."""
        path = Path(self.path).resolve()
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if _LOADED_SOURCES.setdefault(path, digest) != digest:
            raise ValueError(f"loaded implementation differs from source: {path}")
        return compile(data, str(path), "exec", dont_inherit=True)


class _SourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname.split(".", 1)[0] not in {"research_core", "StockProject", "scripts"}:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            location = Path(cast(str, spec.origin)).resolve()
            if not location.is_relative_to(Path(__file__).resolve().parents[1]):
                raise ValueError(f"cache execution imported a different checkout: {location}")
            spec.loader = _SourceLoader(fullname, str(location))
        return spec


def require_loaded(paths: dict[str, Path]) -> None:
    """Bind current bytes to what this fresh worker actually compiled."""
    for path in paths.values():
        resolved = path.resolve()
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if _LOADED_SOURCES.get(resolved) != digest:
            raise ValueError(f"loaded implementation differs from source; use fresh cache entry point: {resolved}")


def execute(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run normal APIs in a new interpreter even when the caller is stale."""
    worker = Path(__file__).resolve()
    result = subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP, str(worker)],
        input=json.dumps({"operation": operation, "payload": payload}, allow_nan=False),
        cwd=worker.parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"fresh cache worker failed ({result.returncode}): {result.stderr[-8000:]}")
    receipt = json.loads(result.stdout)
    if not isinstance(receipt, dict):
        raise ValueError("fresh cache worker did not return a receipt")
    return cast(dict[str, Any], receipt)


def _worker_main() -> None:
    # Also configure here: a long-lived caller may retain an older bootstrap.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        cast(TextIOWrapper, stream).reconfigure(encoding="utf-8")
    entry_digest = globals().get("_ENTRY_SOURCE_SHA256")
    if not isinstance(entry_digest, str):
        raise ValueError("source-captured cache bootstrap required")
    _LOADED_SOURCES[Path(__file__).resolve()] = entry_digest
    sys.meta_path.insert(0, _SourceFinder())
    request = json.load(sys.stdin)
    operation, payload = request["operation"], request["payload"]
    if operation == "build":
        from research_core.derived_cache import _build_cache_in_process

        receipt = _build_cache_in_process(
            prices=Path(payload["prices"]),
            actions=Path(payload["actions"]),
            calendar=Path(payload["calendar"]),
            root=Path(payload["root"]),
            cutoff=payload["cutoff"],
            codes=payload["codes"],
        )
    elif operation == "recompute":
        from scripts.verify_research_cache import _recompute_in_process

        receipt = _recompute_in_process(Path(payload["version"]))
    elif operation == "validate":
        from scripts.validate_hhhl_cache_compatibility import _validate_in_process

        receipt = _validate_in_process(
            inputs=Path(payload["inputs"]), cutoff=payload["cutoff"], cache_version=Path(payload["cache_version"]) if payload["cache_version"] else None
        )
    else:
        raise ValueError("unknown cache operation")
    print(json.dumps(receipt, ensure_ascii=False, allow_nan=False))  # noqa: T201 - worker protocol
