"""Schema and validator for the `experiment.json` autonomous-research-loop contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

DEFAULT_STRATEGY_PATH = "two_b_ma_convergence.py"
DEFAULT_CAPITAL_MODE = "shared"
DEFAULT_BENCHMARK_CODE = "0050"
CAPITAL_MODE_CHOICES = ("shared", "per_stock", "unconstrained", "all")
DIMENSION_KINDS = ("range", "choice")

# Philosophy-aligned gate defaults (proposal.md "What Changes"): expectancy > 0,
# payoff ratio >= 2, profit factor > 1.
DEFAULT_MIN_EXPECTANCY = 0.0
DEFAULT_MIN_PAYOFF_RATIO = 2.0
DEFAULT_MIN_PROFIT_FACTOR = 1.0
DEFAULT_MIN_CLOSED_TRADES = 5


class ExperimentSpecError(ValueError):
    """Raised when an experiment.json fails validation; carries every reason found."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class StrategyRef:
    path: str


@dataclass(frozen=True)
class RunConfig:
    codes: str
    cash: float
    data_path: str
    capital_mode: str = DEFAULT_CAPITAL_MODE
    benchmark_code: str = DEFAULT_BENCHMARK_CODE


@dataclass(frozen=True)
class Dimension:
    name: str
    kind: str
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Gates:
    min_expectancy: float = DEFAULT_MIN_EXPECTANCY
    min_payoff_ratio: float = DEFAULT_MIN_PAYOFF_RATIO
    min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR
    min_closed_trades: int = DEFAULT_MIN_CLOSED_TRADES


@dataclass(frozen=True)
class Window:
    start: str
    end: str


@dataclass(frozen=True)
class Windows:
    train: Window
    holdout: Window


@dataclass(frozen=True)
class StopConditions:
    max_iterations: int
    no_improvement_rounds: int
    wall_clock_minutes: float


@dataclass(frozen=True)
class ExperimentSpec:
    schema_version: str
    hypothesis: str
    strategy: StrategyRef
    run: RunConfig
    dimensions: tuple[Dimension, ...]
    gates: Gates
    windows: Windows
    stop_conditions: StopConditions


def _is_valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _require_number(
    value: Any,
    label: str,
    reasons: list[str],
    *,
    default: float = 0.0,
    minimum: float | None = None,
    exclusive: bool = False,
    preserve_int: bool = False,
) -> float:
    """Validate `value` is a real number (not bool); return `default` and append a reason on failure."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        reasons.append(f"{label}: required number")
        return default
    # Range bounds feed a future harness's --params-json; keep ints as ints (e.g. MA window
    # lengths) instead of forcing 5 -> 5.0, since strategy code may expect int params.
    numeric = value if preserve_int and isinstance(value, int) else float(value)
    if minimum is not None:
        if exclusive and numeric <= minimum:
            reasons.append(f"{label}: must be greater than {minimum}")
            return default
        if not exclusive and numeric < minimum:
            reasons.append(f"{label}: must be at least {minimum}")
            return default
    return numeric


def _require_positive_int(value: Any, label: str, reasons: list[str], *, default: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        reasons.append(f"{label}: required positive integer")
        return default
    return value


def _parse_strategy(value: Any, reasons: list[str]) -> StrategyRef:
    if value is None:
        return StrategyRef(path=DEFAULT_STRATEGY_PATH)
    if not isinstance(value, dict):
        reasons.append("strategy: must be an object")
        return StrategyRef(path=DEFAULT_STRATEGY_PATH)
    path = value.get("path", DEFAULT_STRATEGY_PATH)
    if not isinstance(path, str) or not path.strip():
        reasons.append("strategy.path: required non-empty string")
        return StrategyRef(path=DEFAULT_STRATEGY_PATH)
    if Path(path).is_absolute() or ".." in Path(path).parts:
        reasons.append("strategy.path: must be a relative path without '..' segments")
        return StrategyRef(path=DEFAULT_STRATEGY_PATH)
    return StrategyRef(path=path)


def _parse_run(value: Any, reasons: list[str]) -> RunConfig:
    if not isinstance(value, dict):
        reasons.append("run: required object with codes, cash, data_path")
        return RunConfig(codes="", cash=0.0, data_path="")

    codes = value.get("codes")
    if not isinstance(codes, str) or not codes.strip():
        reasons.append("run.codes: required non-empty comma-separated string")
        codes = ""

    cash = _require_number(value.get("cash"), "run.cash", reasons, minimum=0, exclusive=True)

    data_path = value.get("data_path")
    if not isinstance(data_path, str) or not data_path.strip():
        reasons.append("run.data_path: required non-empty string")
        data_path = ""

    capital_mode = value.get("capital_mode", DEFAULT_CAPITAL_MODE)
    if capital_mode not in CAPITAL_MODE_CHOICES:
        reasons.append(f"run.capital_mode: must be one of {CAPITAL_MODE_CHOICES}")
        capital_mode = DEFAULT_CAPITAL_MODE

    benchmark_code = value.get("benchmark_code", DEFAULT_BENCHMARK_CODE)
    if not isinstance(benchmark_code, str) or not benchmark_code.strip():
        reasons.append("run.benchmark_code: must be a non-empty string")
        benchmark_code = DEFAULT_BENCHMARK_CODE

    return RunConfig(
        codes=codes,
        cash=cash,
        data_path=data_path,
        capital_mode=capital_mode,
        benchmark_code=benchmark_code,
    )


def _parse_dimensions(value: Any, reasons: list[str]) -> tuple[Dimension, ...]:
    if not isinstance(value, list) or not value:
        reasons.append("dimensions: required non-empty array")
        return ()

    parsed: list[Dimension] = []
    seen_names: set[str] = set()
    for index, item in enumerate(value):
        prefix = f"dimensions[{index}]"
        if not isinstance(item, dict):
            reasons.append(f"{prefix}: must be an object")
            continue

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            reasons.append(f"{prefix}.name: required non-empty string")
            continue
        if name in seen_names:
            reasons.append(f"{prefix}.name: duplicate dimension name '{name}'")
            continue

        kind = item.get("kind")
        if kind not in DIMENSION_KINDS:
            reasons.append(f"{prefix}.kind: must be one of {DIMENSION_KINDS}")
            continue

        if kind == "range":
            reasons_before = len(reasons)
            dim_min = _require_number(item.get("min"), f"{prefix}.min", reasons, preserve_int=True)
            dim_max = _require_number(item.get("max"), f"{prefix}.max", reasons, preserve_int=True)
            step = _require_number(item.get("step", 1), f"{prefix}.step", reasons, minimum=0, exclusive=True, preserve_int=True)
            if len(reasons) > reasons_before:
                continue
            if dim_max <= dim_min:
                reasons.append(f"{prefix}: range is empty (max must be greater than min)")
                continue
            seen_names.add(name)
            parsed.append(Dimension(name=name, kind=kind, min=dim_min, max=dim_max, step=step))
        else:
            choices = item.get("choices")
            if not isinstance(choices, list) or not choices:
                reasons.append(f"{prefix}.choices: required non-empty array")
                continue
            seen_names.add(name)
            parsed.append(Dimension(name=name, kind=kind, choices=tuple(choices)))

    return tuple(parsed)


def _parse_gates(value: Any, reasons: list[str]) -> Gates:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        reasons.append("gates: must be an object")
        return Gates()

    def resolve(key: str, default: float) -> float:
        return _require_number(value.get(key, default), f"gates.{key}", reasons, default=default, minimum=0)

    min_expectancy = resolve("min_expectancy", DEFAULT_MIN_EXPECTANCY)
    min_payoff_ratio = resolve("min_payoff_ratio", DEFAULT_MIN_PAYOFF_RATIO)
    min_profit_factor = resolve("min_profit_factor", DEFAULT_MIN_PROFIT_FACTOR)
    min_closed_trades = resolve("min_closed_trades", DEFAULT_MIN_CLOSED_TRADES)

    return Gates(
        min_expectancy=min_expectancy,
        min_payoff_ratio=min_payoff_ratio,
        min_profit_factor=min_profit_factor,
        min_closed_trades=int(min_closed_trades),
    )


def _parse_window(value: Any, label: str, reasons: list[str]) -> Window:
    if not isinstance(value, dict):
        reasons.append(f"{label}: required object with start/end")
        return Window(start="", end="")

    start = value.get("start")
    if not isinstance(start, str) or not _is_valid_date(start):
        reasons.append(f"{label}.start: required date in YYYY-MM-DD format")
        start = ""

    end = value.get("end")
    if not isinstance(end, str) or not _is_valid_date(end):
        reasons.append(f"{label}.end: required date in YYYY-MM-DD format")
        end = ""

    if start and end and end <= start:
        reasons.append(f"{label}: end must be after start (empty or inverted window)")

    return Window(start=start, end=end)


def _parse_windows(value: Any, reasons: list[str]) -> Windows:
    if not isinstance(value, dict):
        reasons.append("windows: required object with train and holdout")
        return Windows(train=Window("", ""), holdout=Window("", ""))

    train = _parse_window(value.get("train"), "windows.train", reasons)
    holdout = _parse_window(value.get("holdout"), "windows.holdout", reasons)

    # D3: holdout is walk-forward (chronologically after train), not just disjoint.
    if train.start and train.end and holdout.start and holdout.end and holdout.start <= train.end:
        reasons.append("windows: holdout must start after train ends (train and holdout may not overlap)")

    return Windows(train=train, holdout=holdout)


def _parse_stop_conditions(value: Any, reasons: list[str]) -> StopConditions:
    if not isinstance(value, dict):
        reasons.append("stop_conditions: required object with max_iterations, no_improvement_rounds, wall_clock_minutes")
        return StopConditions(max_iterations=1, no_improvement_rounds=1, wall_clock_minutes=1.0)

    max_iterations = _require_positive_int(value.get("max_iterations"), "stop_conditions.max_iterations", reasons)
    no_improvement_rounds = _require_positive_int(value.get("no_improvement_rounds"), "stop_conditions.no_improvement_rounds", reasons)
    wall_clock_minutes = _require_number(value.get("wall_clock_minutes"), "stop_conditions.wall_clock_minutes", reasons, default=1.0, minimum=0, exclusive=True)

    return StopConditions(
        max_iterations=max_iterations,
        no_improvement_rounds=no_improvement_rounds,
        wall_clock_minutes=wall_clock_minutes,
    )


def parse_experiment_spec(data: Any) -> ExperimentSpec:
    """Validate a decoded experiment.json payload and build an ExperimentSpec, collecting all failures."""
    if not isinstance(data, dict):
        raise ExperimentSpecError(["experiment spec must be a JSON object"])

    reasons: list[str] = []

    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        reasons.append(f"schema_version: expected {SCHEMA_VERSION!r}, got {schema_version!r}")

    hypothesis = data.get("hypothesis")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        reasons.append("hypothesis: required non-empty string")
        hypothesis = ""

    strategy = _parse_strategy(data.get("strategy"), reasons)
    run = _parse_run(data.get("run"), reasons)
    dimensions = _parse_dimensions(data.get("dimensions"), reasons)
    gates = _parse_gates(data.get("gates"), reasons)
    windows = _parse_windows(data.get("windows"), reasons)
    stop_conditions = _parse_stop_conditions(data.get("stop_conditions"), reasons)

    if reasons:
        raise ExperimentSpecError(reasons)

    return ExperimentSpec(
        schema_version=SCHEMA_VERSION,
        hypothesis=hypothesis,
        strategy=strategy,
        run=run,
        dimensions=dimensions,
        gates=gates,
        windows=windows,
        stop_conditions=stop_conditions,
    )


def load_experiment_spec(path: str | Path) -> ExperimentSpec:
    """Read and validate an experiment.json file. Pure validation: no subprocess, no side effects."""
    spec_path = Path(path)
    try:
        raw_text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExperimentSpecError([f"could not read experiment spec: {exc}"]) from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ExperimentSpecError([f"experiment spec is not valid JSON: {exc}"]) from exc

    return parse_experiment_spec(data)
