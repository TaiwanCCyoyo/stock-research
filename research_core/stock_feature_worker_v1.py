"""One trusted stock job in a fresh interpreter; never a whole-study writer."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOUND_MODULES = (
    "artifact_store",
    "bounded_parquet",
    "feature_identity_v1",
    "research_measurement_v1",
    "derived_features_selective_v1",
    "stock_feature_contract_v1",
    "prepared_stock_input_v1",
)


def execute(request_path: Path) -> None:
    raw = request_path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError("stock request exceeds protocol limit")
    request = json.loads(raw)
    captures: dict[str, bytes] = {}
    # Capture then execute exact module bytes, rather than trust stale parent/pyc.
    for name, digest in request["implementation"].items():
        path = ROOT / name
        if path.resolve().is_relative_to(ROOT) is False or ".." in Path(name).parts:
            raise ValueError("implementation must be inside this checkout")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("worker implementation changed")
        captures[name] = data
    for name in BOUND_MODULES:
        relative = f"research_core/{name}.py"
        module = types.ModuleType(f"research_core.{name}")
        module.__file__, module.__package__ = str(ROOT / relative), "research_core"
        sys.modules[module.__name__] = module
        exec(compile(captures[relative], module.__file__, "exec"), module.__dict__)
    import numpy as np
    import pandas as pd
    import pyarrow

    from research_core.artifact_store import describe_file, file_digest, safe_path, write_json
    from research_core.derived_features_selective_v1 import compute_selected
    from research_core.feature_identity_v1 import identity_digest, validate_identity
    from research_core.prepared_stock_input_v1 import prepared_calendar, read_prepared
    from research_core.research_measurement_v1 import phase_receipt, resource_sample
    from research_core.stock_feature_contract_v1 import make_feature_identity

    runtime = {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__, "pyarrow": pyarrow.__version__}
    if request["runtime"] != runtime:
        raise ValueError("worker runtime differs")
    before = resource_sample()
    source, output = safe_path(Path(request["prepared_path"])), safe_path(request_path.parent)
    prepared, _ = read_prepared(source, request["prepared_sha256"])
    calendar = prepared_calendar(prepared)
    identities = [validate_identity(identity) for identity in request["identities"]]
    for identity in identities:
        if identity["stock_code"] != request["stock_code"] or identity["scope"] != "stock" or identity["calendar"] != calendar:
            raise ValueError("worker stock/calendar/scope mismatch")
        if (
            identity["implementation"] != request["implementation"]
            or identity["runtime"] != runtime
            or identity["inputs"] != {"prepared": request["prepared_sha256"]}
        ):
            raise ValueError("worker dependency identity mismatch")
        if identity != make_feature_identity(
            identity["feature_id"], request["stock_code"], request["prepared_sha256"], calendar, request["implementation"], runtime, request["price_basis"]
        ):
            raise ValueError("worker feature semantics/configuration mismatch")
    daily, pivots = compute_selected(prepared, [identity["feature_id"] for identity in identities])
    artifacts: list[dict[str, Any]] = []
    for identity in identities:
        feature = identity["feature_id"]
        if feature in daily:
            result = daily[[feature]]
        else:
            k = {"pivots_1p5": 1.5, "pivots_4": 4.0}[feature]
            result = pivots.loc[pivots.k.eq(k)].reset_index(drop=True)
        stream = io.BytesIO()
        result.to_parquet(stream, index=feature in daily)
        name = f"{identity_digest(identity)}.parquet"
        with safe_path(output / name).open("xb") as target:
            target.write(stream.getvalue())
        artifacts.append({**describe_file(output, output / name), "identity_id": identity_digest(identity), "rows": len(result)})
    if file_digest(source) != request["prepared_sha256"]:
        raise ValueError("prepared input changed during calculation")
    for name, digest in request["implementation"].items():
        if file_digest(ROOT / name) != digest:
            raise ValueError("worker source changed during calculation")
    if request_path.read_bytes() != raw:
        raise ValueError("stock request changed during calculation")
    write_json(
        output / "complete.json",
        {
            "schema": "stock-feature-worker.v1",
            "stock_code": request["stock_code"],
            "request_sha256": hashlib.sha256(raw).hexdigest(),
            "artifacts": artifacts,
            "measurement": phase_receipt("stock_calculate_and_serialize", before, resource_sample()),
        },
    )


if __name__ == "__main__":
    if not 1 <= len(sys.argv[1:]) <= 8:
        raise ValueError("worker requires one to eight stock requests")
    for argument in sys.argv[1:]:
        execute(Path(argument))
