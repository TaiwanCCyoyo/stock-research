"""Only existing source-bound single-session halts; no fetch or price mutation."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from resumption_execution import ResumptionCase

TASK = Path(__file__).resolve().parent
PILOT = TASK.parent / "20260921-evening-pilot"
PRICE_SHA = "a494202f244986070b128396108afe830f4307d6779aca10ff33bbe9dc57196a"  # pragma: allowlist secret
PRICE_SOURCE = f"twse-official:{PRICE_SHA}|development-raw-close-effective-evening-v1:assumed"
CASE_SPECS = (
    ("2375", date(2019, 3, 12), date(2019, 3, 13), date(2019, 3, 14), 4985, "halt-source.json"),
    ("5469", date(2019, 7, 29), date(2019, 7, 30), date(2019, 7, 31), 4010, "halt-5469-source.json"),
    ("1760", date(2022, 2, 21), date(2022, 2, 22), date(2022, 2, 23), 11150, "halt-1760-source.json"),
)


def named_cases() -> tuple[ResumptionCase, ...]:
    spec = importlib.util.spec_from_file_location("resumption_saved_halt_validator", PILOT / "valuation.py")
    if spec is None or spec.loader is None:
        raise ImportError("existing exact halt validator unavailable")
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cases = []
    for code, reference, halt, resumed, cents, filename in CASE_SPECS:
        payload = json.loads((PILOT / filename).read_text(encoding="utf-8"))
        expected = f"TWSE:TWTAWU:{code}:{halt.isoformat()}"
        if module.confirmed_halts(payload) != {(halt, code): expected}:
            raise ValueError("saved named full-session halt identity differs")
        if module.APPROVED_HALTS[(halt, code)][:2] != (reference, resumed):
            raise ValueError("saved halt reference/resumption interval differs")
        cases.append(
            ResumptionCase(
                code=code,
                reference_day=reference,
                halt_day=halt,
                resumed_day=resumed,
                reference_close_cents=cents,
                halt_source_id=expected,
                reference_source_id=PRICE_SOURCE,
                halt_price_source_id=PRICE_SOURCE,
                resumed_source_id=PRICE_SOURCE,
            )
        )
    return tuple(cases)


def source_paths() -> set[Path]:
    return {PILOT / "valuation.py", *(PILOT / record[-1] for record in CASE_SPECS)}
