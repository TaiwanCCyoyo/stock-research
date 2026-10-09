import json
from pathlib import Path
from typing import Any

import pytest

from scripts import experiment_spec
from scripts.experiment_spec import (
    ExperimentSpecError,
    Gates,
    load_experiment_spec,
    parse_experiment_spec,
)


def valid_spec_dict() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "hypothesis": "A trend filter on 2B raises expectancy above zero.",
        "strategy": {"path": "two_b_ma_convergence.py"},
        "run": {
            "codes": "2330,2454",
            "cash": 1000000,
            "data_path": "stock-data-downloader/data",
        },
        "dimensions": [
            {"name": "ma_fast", "kind": "range", "min": 5, "max": 20, "step": 1},
            {"name": "filter_mode", "kind": "choice", "choices": ["trend", "none"]},
        ],
        "windows": {
            "train": {"start": "2022-01-01", "end": "2023-12-31"},
            "holdout": {"start": "2024-01-01", "end": "2024-06-30"},
        },
        "stop_conditions": {
            "max_iterations": 20,
            "no_improvement_rounds": 5,
            "wall_clock_minutes": 480,
        },
    }


def test_valid_spec_is_accepted() -> None:
    spec = parse_experiment_spec(valid_spec_dict())

    assert spec.hypothesis.startswith("A trend filter")
    assert spec.strategy.path == "two_b_ma_convergence.py"
    assert spec.run.codes == "2330,2454"
    assert spec.run.cash == 1000000.0
    assert len(spec.dimensions) == 2
    assert spec.windows.train.start == "2022-01-01"
    assert spec.windows.holdout.end == "2024-06-30"
    assert spec.stop_conditions.max_iterations == 20


def test_load_experiment_spec_reads_and_validates_a_file(tmp_path: Path) -> None:
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(json.dumps(valid_spec_dict()), encoding="utf-8")

    spec = load_experiment_spec(spec_path)

    assert spec.hypothesis
    assert spec.run.data_path == "stock-data-downloader/data"


def test_missing_hypothesis_is_rejected() -> None:
    data = valid_spec_dict()
    del data["hypothesis"]

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any("hypothesis" in reason for reason in excinfo.value.reasons)


def test_missing_run_is_rejected() -> None:
    data = valid_spec_dict()
    del data["run"]

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any(reason.startswith("run:") for reason in excinfo.value.reasons)


def test_missing_stop_conditions_is_rejected() -> None:
    data = valid_spec_dict()
    del data["stop_conditions"]

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any(reason.startswith("stop_conditions:") for reason in excinfo.value.reasons)


def test_empty_range_dimension_is_rejected() -> None:
    data = valid_spec_dict()
    data["dimensions"] = [{"name": "ma_fast", "kind": "range", "min": 10, "max": 10, "step": 1}]

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any("range is empty" in reason for reason in excinfo.value.reasons)


def test_range_dimension_preserves_integer_bounds() -> None:
    data = valid_spec_dict()
    data["dimensions"] = [{"name": "ma_fast", "kind": "range", "min": 5, "max": 20, "step": 1}]

    spec = parse_experiment_spec(data)

    dimension = spec.dimensions[0]
    assert dimension.min == 5 and isinstance(dimension.min, int)
    assert dimension.max == 20 and isinstance(dimension.max, int)
    assert dimension.step == 1 and isinstance(dimension.step, int)


def test_holdout_before_train_is_rejected_even_without_overlap() -> None:
    """D3: holdout must be walk-forward (after train), not merely disjoint."""
    data = valid_spec_dict()
    data["windows"] = {
        "train": {"start": "2023-01-01", "end": "2023-12-31"},
        "holdout": {"start": "2022-01-01", "end": "2022-06-30"},
    }

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any("after train ends" in reason for reason in excinfo.value.reasons)


def test_overlapping_windows_are_rejected() -> None:
    data = valid_spec_dict()
    data["windows"] = {
        "train": {"start": "2022-01-01", "end": "2023-12-31"},
        "holdout": {"start": "2023-06-01", "end": "2024-06-30"},
    }

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any("overlap" in reason for reason in excinfo.value.reasons)


def test_invalid_spec_never_touches_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("load_experiment_spec must not launch a subprocess")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    monkeypatch.setattr(subprocess, "Popen", fail_if_called)

    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")

    with pytest.raises(ExperimentSpecError):
        load_experiment_spec(spec_path)


def test_gate_defaults_follow_the_big_wins_small_losses_philosophy() -> None:
    data = valid_spec_dict()
    data.pop("gates", None)

    spec = parse_experiment_spec(data)

    assert spec.gates == Gates(
        min_expectancy=experiment_spec.DEFAULT_MIN_EXPECTANCY,
        min_payoff_ratio=experiment_spec.DEFAULT_MIN_PAYOFF_RATIO,
        min_profit_factor=experiment_spec.DEFAULT_MIN_PROFIT_FACTOR,
        min_closed_trades=experiment_spec.DEFAULT_MIN_CLOSED_TRADES,
    )
    assert spec.gates.min_expectancy == 0.0
    assert spec.gates.min_payoff_ratio == 2.0
    assert spec.gates.min_profit_factor == 1.0


def test_partial_gates_fill_remaining_defaults() -> None:
    data = valid_spec_dict()
    data["gates"] = {"min_closed_trades": 10}

    spec = parse_experiment_spec(data)

    assert spec.gates.min_closed_trades == 10
    assert spec.gates.min_payoff_ratio == experiment_spec.DEFAULT_MIN_PAYOFF_RATIO


def test_strategy_defaults_to_two_b_sample_when_omitted() -> None:
    data = valid_spec_dict()
    del data["strategy"]

    spec = parse_experiment_spec(data)

    assert spec.strategy.path == experiment_spec.DEFAULT_STRATEGY_PATH


def test_strategy_path_traversal_is_rejected() -> None:
    data = valid_spec_dict()
    data["strategy"] = {"path": "../outside.py"}

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any("strategy.path" in reason for reason in excinfo.value.reasons)


def test_non_object_spec_is_rejected() -> None:
    with pytest.raises(ExperimentSpecError):
        parse_experiment_spec(["not", "an", "object"])


def test_duplicate_dimension_names_are_rejected() -> None:
    data = valid_spec_dict()
    data["dimensions"] = [
        {"name": "ma_fast", "kind": "range", "min": 5, "max": 20, "step": 1},
        {"name": "ma_fast", "kind": "choice", "choices": ["a", "b"]},
    ]

    with pytest.raises(ExperimentSpecError) as excinfo:
        parse_experiment_spec(data)

    assert any("duplicate" in reason for reason in excinfo.value.reasons)
