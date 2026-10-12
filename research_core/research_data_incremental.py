"""Immutable checkpoint extensions and horizon-tail updates over shared engines."""

from __future__ import annotations

import copy
import io
import logging
import platform
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core import derived_features_chunk_v2 as kernel
from research_core.artifact_store import canonical, file_digest, object_digest, read_json
from research_core.bounded_parquet import read_evidence_parquet
from research_core.hhhl_variants_paths import outcomes_for_closes
from research_core.market_context import compute_context_rows
from research_core.market_context import definition as context_definition
from research_core.research_data_builder import publish_bundle
from research_core.research_data_catalog import DataCatalog, verify_entry

LOGGER = logging.getLogger(__name__)


def _bundle_metadata(catalog: DataCatalog, reference: dict[str, Any]) -> dict[str, Any]:
    entry = catalog.get(reference["data_id"], reference["version_id"], manifest_sha256=reference["manifest"]["sha256"])
    if entry["reader"] != "bundle":
        raise ValueError("incremental reader requires a sealed bundle")
    return {**entry, **verify_entry(entry, catalog.roots)["metadata"]}


def implementation_identity() -> dict[str, Any]:
    from research_core import derived_features_selective_v1, hhhl_variants_paths, market_context

    sources = [
        Path(__file__),
        Path(kernel.__file__),
        Path(derived_features_selective_v1.__file__),
        Path(hhhl_variants_paths.__file__),
        Path(market_context.__file__),
    ]
    return {
        "sources": {path.name: file_digest(path) for path in sources},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "definition": kernel.definition_metadata(),
    }


def _input_identity(prepared: pd.DataFrame) -> str:
    """Logical exact prepared identity, including dtype and invalid float values."""
    kernel.v1.compute_selected(prepared, [])
    selected = prepared.loc[:, [*kernel.v1.OHLC, "Quality"]]
    rows = [
        [*(float(value).hex() for value in values[:4]), None if pd.isna(values[4]) else bool(values[4] == 1)]
        for values in selected.itertuples(index=False, name=None)
    ]
    return object_digest({
        "dates": [day.isoformat() for day in selected.index],
        "index_name": selected.index.name,
        "dtypes": [str(dtype) for dtype in selected.dtypes],
        "rows": rows,
    })


def _frame_bytes(frame: pd.DataFrame) -> bytes:
    stream = io.BytesIO()
    frame.to_parquet(stream, index=True)
    return stream.getvalue()


def _bind(reference: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    if reference.get("same_version") is not True:
        return reference
    return {
        **{key: value for key, value in reference.items() if key != "same_version"},
        "data_id": entry["data_id"],
        "version_id": entry["version_id"],
        "manifest_sha256": entry["manifest"]["sha256"],
    }


def _bound_stocks(entry: dict[str, Any]) -> dict[str, Any]:
    stocks = copy.deepcopy(entry["stocks"])
    for stock in stocks.values():
        for feature in stock["features"].values():
            for key in ("daily_segments", "pivot_segments"):
                feature[key] = [_bind(ref, entry) for ref in feature[key]]
            feature["checkpoint"] = _bind(feature["checkpoint"], entry)
    return stocks


def _read_segment(catalog: DataCatalog, reference: dict[str, Any]) -> pd.DataFrame:
    entry = catalog.get(reference["data_id"], reference["version_id"], manifest_sha256=reference["manifest_sha256"])
    path = catalog.roots.artifact_path(entry["manifest"]["scope"], str(Path(entry["manifest"]["path"]).parent.as_posix()) + "/" + reference["artifact"])
    manifest = verify_entry(entry, catalog.roots)
    if reference["artifact"] not in {row["path"] for row in manifest["artifacts"]}:
        raise ValueError("incremental segment is not declared in its sealed bundle")
    data = path.read_bytes()
    result = read_evidence_parquet(data, reference["rows"], reference["columns"], timestamp_columns=reference["timestamps"])
    verify_entry(entry, catalog.roots)
    if "take_rows" in reference:
        count = reference["take_rows"]
        if type(count) is not int or not 0 <= count <= reference["rows"]:
            raise ValueError("invalid incremental prefix slice")
        result = result.iloc[:count]
    return result


def _materialize(catalog: DataCatalog, references: list[dict[str, Any]], *, pivots: bool = False) -> pd.DataFrame:
    frames = [_read_segment(catalog, reference) for reference in references]
    if not frames:
        raise ValueError("incremental frame requires a retained segment")
    result = pd.concat(frames, ignore_index=pivots)
    if pivots:
        return result.sort_values(["k", "confirmation_index"]).reset_index(drop=True)
    if not result.index.is_unique or not result.index.is_monotonic_increasing:
        raise ValueError("incremental daily segments overlap or are unsorted")
    return result


def load_incremental_feature(catalog: DataCatalog, entry: dict[str, Any], code: str, feature: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sealed = _bundle_metadata(catalog, entry)
    record = _bound_stocks(sealed)[code]["features"][feature]
    daily = _materialize(catalog, record["daily_segments"])
    pivots = _materialize(catalog, record["pivot_segments"], pivots=True)
    return daily, pivots


def build_incremental_features(
    catalog: DataCatalog,
    prepared: dict[str, pd.DataFrame],
    features: list[str],
    *,
    factor_ids: dict[str, str],
    price_basis: str,
    base: dict[str, Any] | None = None,
    calculation_authorized: bool = False,
) -> dict[str, Any]:
    """Append new rows, initialize only new features, or rebuild corrected stocks.

    Full prepared inputs are observed to verify history, not replayed as features.
    Old immutable segments are referenced by pins, never copied or linked. Every
    feature has its own checkpoint so adding another cannot change its values.
    This sequential adapter creates no new scheduler or worker protocol.
    """
    if not calculation_authorized:
        raise PermissionError("explicit calculation authorization required")
    names = [name for name in kernel.ALL_FEATURES if name in kernel.v1._requests(features)]
    if not names or not prepared or set(prepared) != set(factor_ids) or not price_basis:
        raise ValueError("nonempty exact stock/factor identities and features required")
    implementation = implementation_identity()
    old = None if base is None else _bundle_metadata(catalog, base)
    if old is not None and (old["definition_version"] != kernel.DEFINITION_VERSION or old["reader"] != "bundle"):
        raise ValueError("checkpoint extensions cannot reuse a legacy/different numerical definition")
    previous = {} if old is None else _bound_stocks(old)
    if set(previous) - set(prepared):
        raise ValueError("extension cannot remove retained stocks")
    schema_changed = old is not None and (old["implementation"] != implementation or old["parameters"]["price_basis"] != price_basis)
    payloads: dict[str, bytes] = {}
    stocks: dict[str, Any] = {}
    receipt: dict[str, Any] = {"processed_new_rows": 0, "initialized_feature_rows": 0, "reused_features": 0, "stocks": {}}
    for code, frame in sorted(prepared.items()):
        # Validate every publication name before any dataset write.
        catalog.roots.artifact_path("data", f"features/checkpoint-features/stocks/{code}/input.parquet")
        identity = _input_identity(frame)
        if frame.empty or not isinstance(factor_ids[code], str) or not factor_ids[code]:
            raise ValueError("each stock requires a nonempty prepared calendar and factor ID")
        prior = previous.get(code)
        n = 0 if prior is None else prior["rows"]
        unchanged_prefix = prior is not None and len(frame) >= n and _input_identity(frame.iloc[:n]) == prior["input_identity"]
        rebuild = prior is not None and (schema_changed or not unchanged_prefix or factor_ids[code] != prior["factor_id"])
        reason = (
            "new_stock"
            if prior is None
            else "implementation_or_basis_changed"
            if schema_changed
            else "historical_input_or_factor_changed"
            if rebuild
            else "strict_append"
            if len(frame) > n
            else "unchanged"
        )
        feature_records = {}
        for feature in names:
            previous_feature = None if prior is None else prior["features"].get(feature)
            prefix = f"stocks/{code}/{feature}"
            if previous_feature is not None and not rebuild:
                if len(frame) == n:
                    feature_records[feature] = previous_feature
                    receipt["reused_features"] += 1
                    continue
                state_ref = previous_feature["checkpoint"]
                state_entry = catalog.get(state_ref["data_id"], state_ref["version_id"], manifest_sha256=state_ref["manifest_sha256"])
                state_path = catalog.roots.artifact_path("data", str(Path(state_entry["manifest"]["path"]).parent.as_posix()) + "/" + state_ref["artifact"])
                state_manifest = verify_entry(state_entry, catalog.roots)
                if state_ref["artifact"] not in {row["path"] for row in state_manifest["artifacts"]}:
                    raise ValueError("checkpoint not declared in sealed bundle")
                state = read_json(state_path)
                if state["row_count"] != n:
                    raise ValueError("checkpoint rows differ from retained input identity")
                daily, pivots, state = kernel.compute_selected_chunk(frame.iloc[n:], [feature], state=state)
                daily_refs = previous_feature["daily_segments"]
                pivot_refs = previous_feature["pivot_segments"]
                receipt["processed_new_rows"] += len(frame) - n
            else:
                daily, pivots, state = kernel.compute_selected_full(frame, [feature])
                daily_refs, pivot_refs = [], []
                receipt["initialized_feature_rows"] += len(frame)
            payloads[f"{prefix}/daily.parquet"] = _frame_bytes(daily)
            payloads[f"{prefix}/pivots.parquet"] = _frame_bytes(pivots)
            payloads[f"{prefix}/checkpoint.json"] = canonical(state)
            feature_records[feature] = {
                "daily_segments": daily_refs,
                "pivot_segments": pivot_refs,
                "pending": {"daily": daily, "pivots": pivots, "prefix": prefix},
            }
        stocks[code] = {"rows": len(frame), "input_identity": identity, "factor_id": factor_ids[code], "features": feature_records}
        receipt["stocks"][code] = {"reason": reason, "appended_dates": max(0, len(frame) - n), "full_stock_rebuild": rebuild}
    if not payloads and old is not None:
        LOGGER.info("Reused complete checkpoint version=%s", old["version_id"])
        return old
    # New references cannot contain the ID of their own manifest. A same-version
    # marker is stored and expanded to an external pinned reference on reads.
    for stock in stocks.values():
        for record in stock["features"].values():
            pending = record.pop("pending", None)
            if pending is not None:
                for key, frame_key in (("daily_segments", "daily"), ("pivot_segments", "pivots")):
                    part = pending[frame_key]
                    timestamps = [name for name in part.columns if pd.api.types.is_datetime64_ns_dtype(part[name].dtype)]
                    if isinstance(part.index, pd.DatetimeIndex):
                        timestamps.append(part.index.name or "__index_level_0__")
                    record[key] = [
                        *record[key],
                        {
                            "same_version": True,
                            "artifact": f"{pending['prefix']}/{frame_key}.parquet",
                            "rows": len(part),
                            "columns": [*part.columns, part.index.name or "__index_level_0__"],
                            "timestamps": timestamps,
                        },
                    ]
                record["checkpoint"] = {"same_version": True, "artifact": f"{pending['prefix']}/checkpoint.json"}
    start_date = cast(pd.Timestamp, min(frame.index[0] for frame in prepared.values())).date().isoformat()
    end_date = cast(pd.Timestamp, max(frame.index[-1] for frame in prepared.values())).date().isoformat()
    unavailable = {"start": None, "end": None, "reason": "feature-specific warmup/gaps; consult each retained feature"}
    metadata: dict[str, Any] = {
        "data_id": "checkpoint-features",
        "kind": "features",
        "definition_version": kernel.DEFINITION_VERSION,
        "parameters": {"features": names, "price_basis": price_basis},
        "inputs": {"prepared": object_digest({code: stock["input_identity"] for code, stock in stocks.items()}), "factors": object_digest(factor_ids)},
        "coverage": {
            "scope": f"explicit prepared universe of {len(stocks)} stocks; not a whole-market certification",
            "raw_input_period": {"start": start_date, "end": end_date, "reason": None},
            "valid_indicator_period": unavailable,
            "complete_label_period": {"start": None, "end": None, "reason": "no forward labels in this feature bundle"},
        },
        "status": "partial",
        "limitations": ["New checkpoint numerical identity; never concatenate legacy v1 outputs.", "No PIT/full-market or backup certification."],
        "backup": {"status": "not_verified", "off_machine": False},
        "implementation": implementation,
        "stocks": stocks,
        "extension_receipt": receipt,
    }
    entry = publish_bundle(
        catalog,
        metadata,
        payloads,
        lineage=None
        if old is None
        else {"base_version": old["version_id"], "base_manifest_sha256": old["manifest"]["sha256"], "mode": "checkpoint_extension", "receipt": receipt},
    )
    return _bundle_metadata(catalog, entry)


def update_outcome_tail(old_closes: np.ndarray, new_closes: np.ndarray, old_outputs: pd.DataFrame, horizon: int) -> tuple[pd.DataFrame, dict[str, int]]:
    """Use the retained label definition on only the future-dependent tail."""
    if len(new_closes) < len(old_closes) or not np.array_equal(old_closes, new_closes[: len(old_closes)], equal_nan=True):
        raise ValueError("label append requires exact unchanged close history")
    schema = outcomes_for_closes(np.array([], dtype=float), horizon)
    if not old_outputs.index.equals(pd.RangeIndex(len(old_closes))) or not old_outputs.columns.equals(schema.columns):
        raise ValueError("retained outcome output schema/calendar mismatch")
    start = max(0, len(old_closes) - horizon)
    tail = outcomes_for_closes(new_closes[start:], horizon)
    tail.index = pd.RangeIndex(start, len(new_closes))
    prefix = old_outputs.iloc[:start]
    return pd.concat([prefix, tail]), {"tail_start": start, "recalculated_rows": len(new_closes) - start, "retained_rows": start}


def _context_event(state: dict[str, Any], label: str) -> str | None:
    """Continue the retained descriptive event state, without recalculating windows."""
    event = None
    if label in ("unknown", "down"):
        state["had_up"], state["had_consolidation_after_up"] = False, False
    elif label == "up":
        if state["previous_state"] not in ("unknown", "up"):
            event = "resumption" if state["had_up"] and state["had_consolidation_after_up"] else "launch"
        state["had_up"] = True
    elif label == "consolidation":
        if state["had_up"]:
            state["had_consolidation_after_up"] = True
    elif label != "mixed":
        raise ValueError("invalid retained context state")
    state["previous_state"] = label
    return event


def _context_checkpoint(rows: list[dict[str, Any]]) -> dict[str, Any]:
    state = {"previous_state": "unknown", "had_up": False, "had_consolidation_after_up": False}
    for row in rows:
        _context_event(state, row["state"])
    return state


def update_context_tail(
    old_dates: list[str],
    old_closes: list[float | None],
    new_dates: list[str],
    new_closes: list[float | None],
    old_rows: list[dict[str, Any]],
    *,
    layer: str,
    event_checkpoint: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recompute only the future-dependent context tail and bounded warm context."""
    if new_dates[: len(old_dates)] != old_dates or new_closes[: len(old_closes)] != old_closes or len(new_dates) < len(old_dates):
        raise ValueError("context append requires unchanged retained dates/closes")
    if len(old_dates) != len(old_rows) or any(row["asof_date"] != day or row["layer"] != layer for day, row in zip(old_dates, old_rows)):
        raise ValueError("retained context calendar/layer mismatch")
    start = max(0, len(old_dates) - (10 if layer == "retrospective" else 0))
    warm = max(0, start - (10 if layer == "retrospective" else 20))
    state = _context_checkpoint(old_rows[:start]) if event_checkpoint is None else copy.deepcopy(event_checkpoint)
    if (
        set(state) != {"previous_state", "had_up", "had_consolidation_after_up"}
        or state["previous_state"] not in {"unknown", "up", "down", "consolidation", "mixed"}
        or any(type(state[key]) is not bool for key in ("had_up", "had_consolidation_after_up"))
    ):
        raise ValueError("invalid retained context event checkpoint")
    initial = copy.deepcopy(state)
    chunk = compute_context_rows(new_dates[warm:], new_closes[warm:], layer=layer)[start - warm :]
    next_boundary = max(0, len(new_dates) - (10 if layer == "retrospective" else 0))
    next_checkpoint = initial
    for offset, row in enumerate(chunk, start):
        row["event"] = _context_event(state, row["state"])
        if offset < next_boundary:
            next_checkpoint = copy.deepcopy(state)
    return [*old_rows[:start], *chunk], {
        "tail_start": start,
        "recalculated_rows": len(chunk),
        "warm_context_rows": start - warm,
        "checkpoint_before_tail": next_checkpoint,
    }


def publish_forward_series(
    catalog: DataCatalog,
    code: str,
    dates: pd.DatetimeIndex,
    closes: np.ndarray,
    *,
    price_basis: str,
    factor_id: str,
    horizon: int | None = None,
    context_layer: str | None = None,
    base: dict[str, Any] | None = None,
    calculation_authorized: bool = False,
) -> dict[str, Any]:
    """Publish actual label/context tail updates as new immutable versions.

    Original windows/formulas remain in hhhl_variants_paths and market_context.
    Unchanged input and output prefixes reference old pinned files; only new
    input dates and the affected output tail are written. Historical corrections
    use a whole-series rebuild rather than presenting them as date appends.
    """
    if not calculation_authorized:
        raise PermissionError("explicit calculation authorization required")
    if not isinstance(price_basis, str) or not price_basis or not isinstance(factor_id, str) or not factor_id:
        raise ValueError("explicit price basis and factor identity required")
    if context_layer is not None and code != "0050":
        raise ValueError("retained benchmark context definition is specific to 0050")
    if (
        (horizon is None) == (context_layer is None)
        or len(dates) != len(closes)
        or not len(dates)
        or dates.tz is not None
        or dates.hasnans
        or not dates.is_unique
        or not dates.is_monotonic_increasing
    ):
        raise ValueError("one forward definition and a nonempty explicit daily calendar required")
    if any(day != day.normalize() for day in dates):
        raise ValueError("forward series requires daily midnight dates")
    dates = dates.rename("Date")
    input_frame = pd.DataFrame({"Close": closes.astype(float)}, index=dates)
    identity = object_digest({"dates": [day.isoformat() for day in dates], "closes": [float(close).hex() for close in closes]})
    data_id = f"labels-{code}-h{horizon}" if horizon is not None else f"context-{code}-{context_layer}"
    catalog.roots.artifact_path("data", f"labels/{data_id}/manifest.json")
    old = None if base is None else _bundle_metadata(catalog, base)
    parameters = {"code": code, "horizon": horizon, "layer": context_layer, "price_basis": price_basis}
    if old is not None and (old["data_id"] != data_id or any(old["parameters"][key] != parameters[key] for key in ("code", "horizon", "layer"))):
        raise ValueError("forward-series definition differs from pinned base")
    old_inputs = None if old is None else _materialize(catalog, [_bind(ref, old) for ref in old["input_segments"]])
    old_outputs = None if old is None else _materialize(catalog, [_bind(ref, old) for ref in old["output_segments"]])
    n = 0 if old_inputs is None else len(old_inputs)
    implementation = implementation_identity()
    prefix_same = old_inputs is not None and len(input_frame) >= n and old_inputs.equals(input_frame.iloc[:n])
    append = (
        old is not None
        and prefix_same
        and old["implementation"] == implementation
        and old["parameters"]["price_basis"] == price_basis
        and old["inputs"]["factor_id"] == factor_id
    )
    if append and len(input_frame) == n:
        assert old is not None
        return old
    strings = [day.date().isoformat() for day in dates]
    values = [None if not np.isfinite(value) or value <= 0 else float(value) for value in closes]
    receipt: dict[str, Any]
    if horizon is not None:
        if append:
            assert old_inputs is not None and old_outputs is not None
            old_range = old_outputs.set_axis(pd.RangeIndex(n))
            outputs, receipt = update_outcome_tail(old_inputs["Close"].to_numpy(dtype=float), closes, old_range, horizon)
        else:
            outputs = outcomes_for_closes(closes, horizon)
            receipt = {"tail_start": 0, "recalculated_rows": len(closes), "retained_rows": 0}
        definition = "hhhl-variants-outcomes.v1"
        outputs.index = dates
    else:
        assert context_layer is not None
        if append:
            assert old_inputs is not None and old_outputs is not None and old is not None
            rows = old_outputs.reset_index(drop=True).to_dict("records")
            for row in rows:
                for key, value in row.items():
                    if pd.isna(value):
                        row[key] = None
            updated, receipt = update_context_tail(
                [day.date().isoformat() for day in old_inputs.index],
                [None if not np.isfinite(value) or value <= 0 else float(value) for value in old_inputs["Close"]],
                strings,
                values,
                rows,
                layer=context_layer,
                event_checkpoint=old["checkpoint_before_tail"],
            )
        else:
            updated = compute_context_rows(strings, values, layer=context_layer)
            boundary = max(0, len(strings) - (10 if context_layer == "retrospective" else 0))
            receipt = {
                "tail_start": 0,
                "recalculated_rows": len(strings),
                "warm_context_rows": 0,
                "checkpoint_before_tail": _context_checkpoint(updated[:boundary]),
            }
        outputs = pd.DataFrame(updated, index=dates)
        definition = context_definition()["version"]
    start = receipt["tail_start"]
    input_refs = [] if not append or old is None else [_bind(ref, old) for ref in old["input_segments"]]
    output_refs = []
    if append and old is not None:
        # A prefix slice refers to an immutable file; slice bounds never edit it.
        remaining = start
        for reference in old["output_segments"]:
            bound = _bind(reference, old)
            count = min(bound.get("take_rows", bound["rows"]), remaining)
            if count:
                output_refs.append({**bound, "take_rows": count})
                remaining -= count
    input_tail = input_frame.iloc[n:] if append else input_frame
    output_tail = outputs.iloc[start:]

    def ref(artifact: str, frame: pd.DataFrame) -> dict[str, Any]:
        return {"same_version": True, "artifact": artifact, "rows": len(frame), "columns": [*frame.columns, "Date"], "timestamps": ["Date"]}

    input_refs.append(ref("inputs.parquet", input_tail))
    output_refs.append(ref("outputs.parquet", output_tail))
    unavailable = {"start": None, "end": None, "reason": "not an indicator dataset"}
    complete = (
        {"start": cast(pd.Timestamp, dates[0]).date().isoformat(), "end": cast(pd.Timestamp, dates[-horizon - 1]).date().isoformat(), "reason": None}
        if horizon is not None and len(dates) > horizon
        else {"start": None, "end": None, "reason": "context layer or insufficient future calendar; gaps remain explicit"}
    )
    metadata: dict[str, Any] = {
        "data_id": data_id,
        "kind": "labels" if horizon is not None else "market",
        "definition_version": definition,
        "parameters": parameters,
        "inputs": {"prepared_series": identity, "factor_id": factor_id, "calendar": object_digest([day.isoformat() for day in dates])},
        "coverage": {
            "scope": f"explicit {code} series",
            "raw_input_period": {
                "start": cast(pd.Timestamp, dates[0]).date().isoformat(),
                "end": cast(pd.Timestamp, dates[-1]).date().isoformat(),
                "reason": None,
            },
            "valid_indicator_period": unavailable,
            "complete_label_period": complete,
        },
        "status": "partial",
        "limitations": ["Retained descriptive definition; not a pattern-scan strategy or PIT certification."],
        "backup": {"status": "not_verified", "off_machine": False},
        "implementation": implementation,
        "input_segments": input_refs,
        "output_segments": output_refs,
        "extension_receipt": {**receipt, "mode": "tail_update" if append else "full_rebuild"},
    }
    if context_layer is not None:
        metadata["checkpoint_before_tail"] = receipt["checkpoint_before_tail"]
    entry = publish_bundle(
        catalog,
        metadata,
        {"inputs.parquet": _frame_bytes(input_tail), "outputs.parquet": _frame_bytes(output_tail)},
        lineage=None
        if old is None
        else {"base_version": old["version_id"], "base_manifest_sha256": old["manifest"]["sha256"], "mode": "tail_update" if append else "full_rebuild"},
    )
    return _bundle_metadata(catalog, entry)


def load_forward_series(catalog: DataCatalog, entry: dict[str, Any]) -> pd.DataFrame:
    sealed = _bundle_metadata(catalog, entry)
    return _materialize(catalog, [_bind(ref, sealed) for ref in sealed["output_segments"]])
