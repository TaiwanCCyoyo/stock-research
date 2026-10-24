"""Explicit, serialized maintenance command for security coverage."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from research_core.artifact_store import release_os_lock, try_os_lock
from research_core.live_producer import PRODUCER_TZ
from research_core.producer_data import producer_data_root
from research_core.run_receipt import code_identity
from research_core.security_coverage import project_security_coverage
from research_core.security_coverage_sources import collect_sources
from research_core.security_coverage_store import family_path, publish_coverage

LOGGER = logging.getLogger(__name__)


@contextmanager
def _maintenance_guard() -> Iterator[None]:
    family = family_path()
    family.mkdir(parents=True, exist_ok=True)
    with (family / ".maintenance.lock").open("a+b") as handle:
        if not (family / ".maintenance.lock").stat().st_size:
            handle.write(b"0")
            handle.flush()
        if not try_os_lock(handle):
            raise RuntimeError("another security coverage maintenance is running")
        try:
            yield
        finally:
            release_os_lock(handle)


def measure_coverage(codes: Sequence[str], *, seconds_per_source: float = 180) -> dict[str, Any]:
    """Profile selected source reads without building or publishing a generation."""
    normalized = tuple(code.strip() for code in codes)
    if any(not code for code in normalized):
        raise ValueError("measurement codes must be non-empty after trimming")
    selected = tuple(dict.fromkeys(normalized))
    if not selected or len(selected) > 100:
        raise ValueError("measurement requires 1 to 100 non-empty stock codes")
    if not 1 <= seconds_per_source <= 1800:
        raise ValueError("source budget must be between 1 and 1800 seconds")

    from research_core.research_measurement_v1 import phase_receipt, resource_sample

    before = resource_sample()
    sources, _metadata = collect_sources(
        producer_data_root(),
        seconds_per_source=seconds_per_source,
        codes=selected,
        measure_resources=True,
    )
    after = resource_sample()
    total = phase_receipt("security_coverage_selected_source_measurement", before, after)
    total.update(
        selected_codes=list(selected),
        workers=1,
        max_in_flight=1,
        publication="none",
    )
    return {
        "status": "measured",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selected_codes": list(selected),
        "sources": sources,
        "measurement": total,
    }


def update_coverage(*, seconds_per_source: float = 180) -> dict[str, Any]:
    """One bounded source scan at a time, no acquisition and no disk intermediates."""
    from research_core.research_measurement_v1 import phase_receipt, resource_sample

    with _maintenance_guard():
        measurement_before = resource_sample()
        sources, metadata = collect_sources(producer_data_root(), seconds_per_source=seconds_per_source, measure_resources=True)
        if not any(source.get("status") == "ok" for source in sources.values()):
            raise RuntimeError("No usable coverage source; retaining the previously published generation")
        moment = datetime.now(timezone.utc)
        document = project_security_coverage(
            sources, metadata, built_at=moment.isoformat(timespec="seconds"), as_of=moment.astimezone(PRODUCER_TZ).date().isoformat()
        )
        document["code"] = code_identity()
        build_metrics = phase_receipt("security_coverage_build_before_publication", measurement_before, resource_sample())
        build_metrics.update(
            workers=1,
            max_in_flight=1,
            memory_bytes=None,
            io_bytes=None,
            measurement_scope=("source reads, coverage projection, and code identity; ends before artifact serialization and publication"),
        )
        document["build_metrics"] = build_metrics
        pointer = publish_coverage(document)
        LOGGER.info("Published security coverage generation=%s securities=%d", pointer["generation"], len(document["securities"]))
        return {**pointer, "metrics": document["build_metrics"]}
