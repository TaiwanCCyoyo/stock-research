"""Immutable, verified read model of a producer-owned historical catalog.

The configured bundle is trusted server configuration, never an HTTP argument.
No market cache, analysis runner, or source artifact is written by this reader.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import threading
from bisect import bisect_left
from collections.abc import Callable
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from research_core.opportunity_history_catalog import RULE, _id
from research_core.opportunity_history_view import GainIndex, build_frame
from research_core.opportunity_startup_cache import StartupCache, canonical
from scripts.opportunity_history_source_runs import expected_source_runs
from scripts.opportunity_native_receipt_cache import semantic_receipt_cache
from scripts.query_opportunity_history import (
    _selected_native,
    _v2_dependency,
    _validate_query_inputs,
    validate_calendar_identity,
    validate_manifest_identity,
    validate_manifest_trust,
    validate_query_tables,
)

SCHEMA = "opportunity-history-web.v1"
DEFAULT_SHA = "c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140"
DEFAULT_BUNDLE = Path(__file__).resolve().parents[1] / "tasks/20261005-market-full-history-web/inputs/producer-preview"
WEB_RECEIPT_CACHE = Path(__file__).resolve().parents[1] / ".tmp/opportunity-native-verification-cache"
WEB_STARTUP_CACHE = Path(__file__).resolve().parents[1] / ".tmp/opportunity-web-startup-cache-v1"
logger = logging.getLogger(__name__)


class HistoryStore:
    """Load once; every date and detail remains bound to this accepted snapshot."""

    def __init__(
        self,
        bundle: Path = DEFAULT_BUNDLE,
        expected_sha: str = DEFAULT_SHA,
        *,
        progress: Callable[[str, int, int], None] | None = None,
        startup_cache: Path | None = None,
    ) -> None:
        report = progress or (lambda _stage, _done, _total: None)
        report("檢查保存資料與版本", 0, 0)
        self.bundle = bundle.resolve()
        self.root = self.bundle / "catalog-v2"
        self.manifest_path = self.root / "manifest.json"
        payload = self.manifest_path.read_bytes()
        try:
            trust = validate_manifest_trust(payload, expected_sha)
        except ValueError as error:
            raise ValueError("Configured catalog manifest hash mismatch") from error
        self.identity = trust["trusted_manifest_sha256"]
        self.manifest = json.loads(payload)
        self.evidence = validate_manifest_identity(self.manifest) | trust
        # Validate every path before invoking the source-run verifier, whose
        # producer helper assumes a trusted manifest.
        self._check_paths(self.manifest)
        self.calendar = self.read(self.manifest["calendar"])
        validate_calendar_identity(self.calendar)
        self.dates = self.calendar["dates"]
        if not self.dates:
            raise ValueError("Empty history calendar")
        securities = self.table("securities")
        intervals = self.table("representative_intervals")
        waves = self.table("baseline_waves")
        classifications = self.read(self.manifest["extras"]["classifications"])["rows"]
        self.securities = self._unique(securities, "code")
        self.waves = self._unique(waves, "id")
        self.classifications = self._unique(classifications, "code")
        self.intervals: dict[str, list[dict[str, Any]]] = {}
        for interval in intervals:
            self.intervals.setdefault(interval["security_id"], []).append(interval)
        cache = StartupCache(startup_cache) if startup_cache is not None else None
        cache_context = self._startup_context(report) if cache is not None else None
        cached = cache.load(cache_context) if cache is not None and cache_context is not None else None
        self.series: dict[str, dict[str, Any]] = {}
        self.gains: dict[str, GainIndex] = {}
        self.native_display: dict[str, dict[tuple[str, str], dict[str, list[dict[str, Any]]]]] = {}
        if cached is not None:
            self.series = cached["series"]
            self.native_display = {code: {(row["method"], row["scale"]): row["value"] for row in records} for code, records in cached["nativeDisplay"].items()}
            self.gains = {code: GainIndex(series, self.dates) for code, series in self.series.items()}
            self._finish_catalog()
            report("已沿用同版本的核對結果", len(self.manifest["series"]), len(self.manifest["series"]))
            return
        # This only recomputes continuity indices with pinned JavaScript, never
        # calls the six saved analysis methods.
        report("核對價格的連續性", 0, len(self.manifest["series"]))
        runs = expected_source_runs(self.manifest_path)
        for completed, (code, reference) in enumerate(self.manifest["series"].items()):
            report("核對各股價格與候選標記", completed, len(self.manifest["series"]))
            series = self.read(reference)
            _validate_query_inputs(self.manifest, code, reference, series, self.calendar)
            if code not in self.securities:
                raise ValueError("Series has no compact security")
            security = self.securities[code]
            owned = {"securities": [security], "representative_intervals": self.intervals.get(series["security_id"], [])}
            native = None
            if security["stock_opportunity_eligible"]:
                native, _, _ = _selected_native(self.manifest, self.root, code, series, reference["sha256"], self.manifest["calendar"]["sha256"])
            validate_query_tables(owned, series, runs.get(code), native=native, calendar=self.calendar)
            if not security["stock_opportunity_eligible"]:
                continue
            assert native is not None
            # The slim projection has no independent series_id assertion: the
            # complete source content was verified before retaining these fields.
            slim = {key: series[key] for key in ("code", "security_id", "series_id", "calendar_id", "raw", "adjusted")}
            slim.update({key: series[key] for key in ("numeric_flags", "action_barriers") if key in series})
            slim["source_run_indices"] = runs[code]
            self.series[code] = slim
            self.gains[code] = GainIndex(slim, self.dates)
            self.native_display[code] = {}
            scope = (native.get("input_identity"), series["series_id"], RULE, series["security_id"])
            representative_intervals = self.intervals.get(series["security_id"], [])
            representative_waves = [self.waves[row["wave_id"]] for row in representative_intervals]
            phase_spans = [
                (wave["start"], wave["end"] - 1 if wave.get("end") is not None else wave["observedThrough"])
                for wave in representative_waves
                if (wave["end"] - 1 if wave.get("end") is not None else wave["observedThrough"]) is not None
            ]
            merged_spans: list[list[int]] = []
            for left, right in sorted(phase_spans):
                if merged_spans and left <= merged_spans[-1][1] + 1:
                    merged_spans[-1][1] = max(merged_spans[-1][1], right)
                else:
                    merged_spans.append([left, right])
            phase_starts = [span[0] for span in merged_spans]
            wanted_candidates = {row["earliest_candidate_id"] for row in representative_intervals if row.get("earliest_candidate_id")}
            for record in native.get("native", []):
                method, scale = record["method"], record["scale"]
                if method != "segments" or scale not in ("balanced", "coarse") or record["status"] != "ok":
                    continue
                result = record["result"]
                launches = []
                launch_indices = []
                for launch in result.get("launches", []):
                    launch_indices.append(launch["index"])
                    if scale == "balanced":
                        catalog_id = _id(*scope, method, scale, "candidate", launch["id"])
                        if catalog_id in wanted_candidates:
                            launches.append({key: launch[key] for key in ("index", "rangeStart", "rangeEnd", "kind", "outcome")} | {"catalogId": catalog_id})
                segments = []
                if scale == "balanced":
                    for segment in result.get("segments", []):
                        position = bisect_left(phase_starts, segment["end"] + 1) - 1
                        if position >= 0 and merged_spans[position][1] >= segment["start"]:
                            segments.append({key: segment[key] for key in ("start", "end", "phase")})
                self.native_display[code][(method, scale)] = {
                    "waves": [{key: wave[key] for key in ("id", "start", "peak", "end", "observedThrough", "scale")} for wave in result.get("waves", [])],
                    "segments": segments,
                    "launches": launches,
                    "launchIndices": launch_indices,
                }
        for interval in intervals:
            wave = self.waves.get(interval["wave_id"])
            if wave is None or wave["security_id"] != interval["security_id"] or wave["start"] != interval["gain_base_index"]:
                raise ValueError("Representative interval baseline identity mismatch")
        self._finish_catalog()
        if cache is not None and cache_context is not None:
            # Authenticate a memo only after all source/semantic/Counter gates.
            cache.save(
                cache_context,
                {
                    "series": self.series,
                    "nativeDisplay": {
                        code: [{"method": method, "scale": scale, "value": value} for (method, scale), value in records.items()]
                        for code, records in self.native_display.items()
                    },
                },
            )
        report("可以開始探索", len(self.manifest["series"]), len(self.manifest["series"]))

    def _finish_catalog(self) -> None:
        self.catalog = {
            "id": self.identity,
            "dates": self.dates,
            "securities": self.securities,
            "series": self.series,
            "intervals": self.intervals,
            "waves": self.waves,
            "classifications": self.classifications,
            "gains": self.gains,
            "native_display": self.native_display,
        }

    def _startup_context(self, report: Callable[[str, int, int], None]) -> dict[str, Any]:
        """Hash CURRENT pinned source bytes; manifest or mtimes alone never suffice."""
        from scripts.opportunity_history_native_validation import _verification_fingerprint

        references: dict[str, dict[str, Any]] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if "path" in value and "sha256" in value:
                    path = self._path(value)
                    references[str(path)] = value
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        # Audit the exact dependency closure read by this viewer. Historical
        # publication links (for example a preserved V1 manifest) are metadata,
        # and need not exist in this physical V2 input snapshot.
        for value in (
            self.manifest["calendar"],
            self.manifest["series"],
            self.manifest["native"],
            *(self.manifest["tables"][name] for name in ("securities", "representative_intervals", "baseline_waves")),
            self.manifest["extras"]["classifications"],
        ):
            visit(value)
        for completed, (path_name, reference) in enumerate(sorted(references.items())):
            report("確認資料與上次核對版本相同", completed, len(references))
            digest = hashlib.sha256()
            with Path(path_name).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != reference["sha256"].lower():
                raise ValueError("Catalog dependency hash mismatch before startup memo")
        repository = Path(__file__).resolve().parents[1]
        implementation = hashlib.sha256(_verification_fingerprint().encode())
        core_names = (
            "opportunity_history_catalog.py",
            "opportunity_history_store.py",
            "opportunity_history_view.py",
            "opportunity_history_display.py",
            "opportunity_startup_cache.py",
            "wave_growth.py",
        )
        paths = (
            {repository / "research_core" / name for name in core_names}
            | set((repository / "scripts").glob("*opportunity*.py"))
            | set((repository / "scripts").glob("*opportunity*.mjs"))
        )
        for path in sorted(paths):
            implementation.update(str(path.relative_to(repository)).encode())
            implementation.update(path.read_bytes())
        return {
            "schema": "opportunity-web-startup-context.v1",
            "manifest": self.identity,
            "implementation": implementation.hexdigest(),
            "sources": hashlib.sha256(canonical({path: reference["sha256"].lower() for path, reference in sorted(references.items())})).hexdigest(),
        }

    def _path(self, reference: dict[str, Any]) -> Path:
        checked = _v2_dependency(reference, "website read dependency")
        path = (self.root / checked["path"]).resolve()
        if not path.is_relative_to(self.bundle) or any(
            parent.is_symlink() or getattr(parent, "is_junction", lambda: False)() for parent in (path, *path.parents) if parent.is_relative_to(self.bundle)
        ):
            raise ValueError("Catalog reference escapes its physical bundle")
        return path

    def _check_paths(self, value: Any) -> None:
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                self._path(value)
            for child in value.values():
                self._check_paths(child)
        elif isinstance(value, list):
            for child in value:
                self._check_paths(child)

    def read(self, reference: dict[str, Any]) -> Any:
        path = self._path(reference)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != reference["sha256"].lower():
            raise ValueError("Catalog dependency hash mismatch")
        result = json.loads(gzip.decompress(payload) if path.suffix == ".gz" else payload)
        if isinstance(result, dict) and "rows" in result and "count" in reference:
            if type(reference["count"]) is not int or reference["count"] != len(result["rows"]):
                raise ValueError("Catalog table descriptor count mismatch")
        return result

    @staticmethod
    def _unique(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        result = {row[key]: row for row in rows}
        if len(result) != len(rows):
            raise ValueError(f"Duplicate catalog {key}")
        return result

    def table(self, name: str) -> list[dict[str, Any]]:
        references = self.manifest["tables"][name]
        references = references if isinstance(references, list) else [references]
        return [row for reference in references for row in self.read(reference)["rows"]]

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "catalogId": self.identity,
            "dates": self.dates,
            "coverage": {"stocks": len(self.series), "excluded": len(self.securities) - len(self.series), "from": self.dates[0], "to": self.dates[-1]},
            "basisLabel": "收盤價經已記錄的公司行動調整；不含股息再投資",
            "ruleLabel": "初步辨識，規則未定",
            "limitations": [
                "事後回看大漲波段，並非當時可提前發現的訊號。",
                "涵蓋本機這份快照的可用股票；下市公司與歷史名單仍有覆蓋限制。",
                "2010–2012 年公司行動與缺價需補核對；有價格不代表調整後漲幅均已可靠。",
                "產業先參照現有分類暫分群，當年歸屬待確認；細分證據仍在補齊。",
                "缺少可靠歷史市值，這版面積只依本波已漲幅計算。",
                "策略比較先使用已保存研究帳本；ETF 與未覆蓋日期保持未知，尚未計算完整波段收益。",
            ],
        }

    def frame(self, date: str) -> dict[str, Any]:
        return deepcopy(self._cached_frame(date))

    @lru_cache(maxsize=24)
    def _cached_frame(self, date: str) -> dict[str, Any]:
        return build_frame(self.catalog, date)

    def directory(self) -> dict[str, Any]:
        return deepcopy(self._cached_directory())

    @lru_cache(maxsize=1)
    def _cached_directory(self) -> dict[str, Any]:
        from research_core.opportunity_history_display import build_directory

        return build_directory(self.catalog)

    def options(self, date: str) -> dict[str, Any]:
        from research_core.opportunity_history_display import build_options

        return build_options(self.catalog, date)

    def detail(self, code: str, date: str) -> dict[str, Any]:
        if code not in self.series:
            raise KeyError(code)
        if date not in self.dates:
            raise ValueError("Date is outside the saved quote calendar")
        reference = self.manifest["series"][code]
        series = self.read(reference)
        _validate_query_inputs(self.manifest, code, reference, series, self.calendar)
        native_ref = self.manifest["native"][code]
        native = self.read(native_ref)
        receipt = self.read(native_ref["receipt"])
        if (
            receipt.get("schema_version") != "opportunity-native-receipt.v1"
            or receipt.get("sha256") != native_ref["sha256"]
            or receipt.get("context") != self.manifest["producer_identity"]
        ):
            raise ValueError("Native receipt producer identity mismatch")
        for field in ("security_id", "series_id", "calendar_id"):
            if native.get(field) != series[field] or (field != "calendar_id" and receipt.get(field) != series[field]):
                raise ValueError("Native detail identity mismatch")
        if (
            native.get("schema", native.get("schema_version")) != "opportunity-native-results.v1"
            or native.get("input_identity") != {"series_sha256": reference["sha256"], "calendar_sha256": self.manifest["calendar"]["sha256"]}
            or native.get("code_identity") != self.manifest["code_identity"]
        ):
            raise ValueError("Native detail input/code identity mismatch")
        records = native.get("native", [])
        pairs = {(method, scale) for method in ("segments", "filter") for scale in ("fine", "balanced", "coarse")}
        if len(records) != 6 or {(record["method"], record["scale"]) for record in records} != pairs:
            raise ValueError("Native detail method/scale mismatch")
        if any(
            record["status"] not in ("ok", "error")
            or (record["status"] == "ok" and not isinstance(record.get("result"), dict))
            or (record["status"] == "error" and not record.get("error"))
            for record in records
        ):
            raise ValueError("Invalid native completion record")
        json.dumps(native, allow_nan=False)
        row = next((row for row in self.frame(date)["rows"] if row["code"] == code), None)
        name = self.securities[code].get("name") or code
        return {
            "schema": SCHEMA,
            "catalogId": self.identity,
            "date": date,
            "row": row,
            "sample": {
                "id": f"{self.identity}:{code}",
                "name": name,
                "code": code,
                "kind": "historical",
                "category": "歷史大漲波段",
                "question": "完整行情與發動候選分開看；整理、回落和失敗候選也保留。",
                "points": [
                    {
                        "date": day,
                        "raw": series["raw"][index],
                        "adjusted": series["adjusted"][index],
                        "flags": series.get("numeric_flags", {}).get(str(index), []),
                    }
                    for index, day in enumerate(self.dates)
                ],
                "source": {
                    "label": "已保存的全歷史價格快照",
                    "from": self.dates[0],
                    "to": self.dates[-1],
                    "priceBasis": self.metadata()["basisLabel"],
                    "hash": reference["sha256"],
                    "catalogHash": self.identity,
                    "limitations": self.metadata()["limitations"],
                },
            },
            "results": [record["result"] for record in records if record["status"] == "ok"],
            "evidence": self.evidence
            | {
                "manifest_sha256": self.identity,
                "calendar_sha256": self.manifest["calendar"]["sha256"],
                "series_sha256": reference["sha256"],
                "series_id": series["series_id"],
                "native_sha256": native_ref["sha256"],
                "native_receipt_sha256": native_ref["receipt"]["sha256"],
                "classification": self.classifications.get(code),
                "native_status": [{"method": r["method"], "scale": r["scale"], "status": r["status"], "error": r.get("error")} for r in records],
            },
        }


class HistoryLoading(RuntimeError):
    """A background snapshot is not yet atomically ready for queries."""


class LazyHistoryStore:
    """One initialized snapshot per server process, including startup failures."""

    def __init__(self, bundle: Path = DEFAULT_BUNDLE, expected_sha: str = DEFAULT_SHA) -> None:
        self.bundle = bundle
        self.expected_sha = expected_sha
        self.store: HistoryStore | None = None
        self.error: Exception | None = None
        self.lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self.progress = {"stage": "等待載入歷史行情", "completed": 0, "total": 0}

    def _progress(self, stage: str, completed: int, total: int) -> None:
        self.progress = {"stage": stage, "completed": completed, "total": total}

    def status(self) -> dict[str, Any]:
        """Nonblocking progress; never starts loading or exposes source paths."""
        return {"schema": SCHEMA, "state": "failed" if self.error else "ready" if self.store else "loading", **self.progress}

    def get(self) -> HistoryStore:
        with self.lock:
            if self.error:
                raise RuntimeError("Saved history snapshot is unavailable") from self.error
            if self.store is None:
                try:
                    # Only the web reader opts in. Every source byte/hash and
                    # structural gate is still checked on each process startup.
                    with semantic_receipt_cache(WEB_RECEIPT_CACHE):
                        self.store = HistoryStore(self.bundle, self.expected_sha, progress=self._progress, startup_cache=WEB_STARTUP_CACHE)
                except Exception as error:
                    self.error = error
                    raise
            return self.store

    def start(self) -> None:
        """Launch once without holding the long-running initialization lock."""
        with self._start_lock:
            if self.store is not None or self.error is not None or self._worker is not None:
                return

            def initialize() -> None:
                try:
                    self.get()
                except Exception:
                    logger.exception("Historical background verification failed")

            self._worker = threading.Thread(target=initialize, name="history-snapshot", daemon=True)
            self._worker.start()

    def get_ready(self) -> HistoryStore:
        if self.error is not None:
            raise RuntimeError("Saved history snapshot is unavailable") from self.error
        if self.store is not None:
            return self.store
        self.start()
        raise HistoryLoading("Historical verification is running")
