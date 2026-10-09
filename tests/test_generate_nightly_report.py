import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from scripts import generate_nightly_report
from scripts.experiment_spec import parse_experiment_spec
from scripts.generate_nightly_report import render_nightly_report

REPO_ROOT = Path(__file__).resolve().parents[1]

VALID_SPEC_DICT: dict[str, Any] = {
    "schema_version": "1.0",
    "hypothesis": "A trend filter on 2B raises expectancy above zero.",
    "strategy": {"path": "two_b_ma_convergence.py"},
    "run": {"codes": "2330,2454", "cash": 1000000, "data_path": "shioaji_stock_prices/data"},
    "dimensions": [{"name": "ma_fast", "kind": "range", "min": 5, "max": 20, "step": 1}],
    "gates": {"min_closed_trades": 1},
    "windows": {
        "train": {"start": "2022-01-01", "end": "2023-12-31"},
        "holdout": {"start": "2024-01-01", "end": "2024-06-30"},
    },
    "stop_conditions": {"max_iterations": 5, "no_improvement_rounds": 3, "wall_clock_minutes": 480},
}


def spec():
    return parse_experiment_spec(VALID_SPEC_DICT)


def test_generate_nightly_report_is_importable_as_invoked_by_the_skill() -> None:
    """The historical reader remains runnable as a module without the retired harness."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.generate_nightly_report", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def run_entry(
    iteration: int,
    decision: str,
    *,
    train_expectancy: float = 100.0,
    holdout_expectancy: float | None = 100.0,
    holdout_passed: bool | None = True,
    rationale: str = "widen the fast MA",
    ma_fast: int = 10,
) -> dict[str, Any]:
    holdout_gate = (
        None
        if holdout_expectancy is None
        else {
            "passed": holdout_passed,
            "reasons": [] if holdout_passed else ["expectancy -5.0 does not exceed gates.min_expectancy 0.0"],
            "metrics": {"expectancy": holdout_expectancy, "payoff_ratio": 3.0, "profit_factor": 2.0},
        }
    )
    return {
        "kind": "run",
        "iteration": iteration,
        "move": {"dimension_values": {"ma_fast": ma_fast}, "rationale": rationale},
        "train_gate": {
            "passed": decision != "train_failed",
            "reasons": [],
            "metrics": {"expectancy": train_expectancy, "payoff_ratio": 3.0, "profit_factor": 2.0},
        },
        "holdout_gate": holdout_gate,
        "decision": decision,
    }


def rejected_entry(reason: str = "move.dimension_values.ma_fast: 999 outside declared range [5, 20]") -> dict[str, Any]:
    return {
        "kind": "rejected",
        "iteration": None,
        "move": {"dimension_values": {"ma_fast": 999}, "rationale": "try something wild"},
        "reasons": [reason],
    }


def stopped_entry(reason: str = "max_iterations reached (5)") -> dict[str, Any]:
    return {"kind": "stopped", "iteration": None, "reason": reason}


def test_report_lists_exactly_the_journaled_iterations() -> None:
    entries = [
        run_entry(1, "train_failed", train_expectancy=-10.0, holdout_expectancy=None),
        run_entry(2, "candidate_failed_holdout", train_expectancy=50.0, holdout_expectancy=-5.0, holdout_passed=False),
        run_entry(3, "accepted", train_expectancy=80.0, holdout_expectancy=90.0, holdout_passed=True),
    ]

    report = render_nightly_report(spec(), entries)

    assert "| 1 | train_failed |" in report
    assert "| 2 | candidate_failed_holdout |" in report
    assert "| 3 | accepted |" in report
    log_section = report.split("## Iteration Log", 1)[1].split("## ", 1)[0]
    table_rows = [line for line in log_section.splitlines() if line.startswith("| ") and "---" not in line and "Iteration" not in line]
    assert len(table_rows) == len(entries)


def test_report_holdout_count_matches_journal() -> None:
    entries = [
        run_entry(1, "train_failed", train_expectancy=-10.0, holdout_expectancy=None),
        run_entry(2, "candidate_failed_holdout", train_expectancy=50.0, holdout_expectancy=-5.0, holdout_passed=False),
        run_entry(3, "accepted", train_expectancy=80.0, holdout_expectancy=90.0, holdout_passed=True),
    ]

    report = render_nightly_report(spec(), entries)

    # Only iterations 2 and 3 spent a holdout run; iteration 1 (train_failed) did not.
    assert "Holdout evaluations: 2" in report


def test_report_never_claims_train_failed_iteration_ran_holdout() -> None:
    entries = [run_entry(1, "train_failed", train_expectancy=-10.0, holdout_expectancy=None)]

    report = render_nightly_report(spec(), entries)

    assert "Holdout evaluations: 0" in report


def test_report_includes_hypothesis_verbatim() -> None:
    report = render_nightly_report(spec(), [])

    assert VALID_SPEC_DICT["hypothesis"] in report


def test_report_with_empty_journal_makes_no_iteration_claims() -> None:
    report = render_nightly_report(spec(), [])

    assert "Iterations run: 0" in report
    assert "No iterations have run yet." in report
    assert "Holdout evaluations: 0" in report


def test_report_lists_rejected_move_reasons() -> None:
    entries = [rejected_entry("move.dimension_values.ma_fast: 999 outside declared range [5, 20]")]

    report = render_nightly_report(spec(), entries)

    assert "Rejected moves (out of declared bounds): 1" in report
    assert "outside declared range [5, 20]" in report


def test_report_states_stop_reason_when_stopped() -> None:
    entries = [run_entry(1, "accepted"), stopped_entry("max_iterations reached (5)")]

    report = render_nightly_report(spec(), entries)

    assert "Stopped: max_iterations reached (5)" in report


def test_report_only_honors_a_trailing_stop_entry() -> None:
    """A stop line earlier in the journal (e.g. before a spec-mutation resume) is stale, not current."""
    entries = [stopped_entry("max_iterations reached (5)"), run_entry(1, "accepted")]

    report = render_nightly_report(spec(), entries)

    assert "Stopped: not yet stopped" in report


def test_report_picks_best_accepted_candidate_even_when_expectancy_is_zero() -> None:
    """A falsy-but-valid expectancy of 0.0 must still beat a genuinely worse candidate."""
    entries = [
        run_entry(1, "accepted", train_expectancy=0.0, holdout_expectancy=0.0, holdout_passed=True, ma_fast=7),
        run_entry(2, "accepted", train_expectancy=-100.0, holdout_expectancy=-100.0, holdout_passed=True, ma_fast=15),
    ]

    report = render_nightly_report(spec(), entries)

    assert "Iteration 1 passed gates on both train and holdout windows" in report


def test_report_recommends_reviewing_accepted_candidate() -> None:
    entries = [run_entry(1, "accepted", ma_fast=12)]

    report = render_nightly_report(spec(), entries)

    assert "passed gates on both train and holdout windows" in report
    assert "'ma_fast': 12" in report


def test_report_recommends_caution_for_overfit_candidate_when_none_accepted() -> None:
    entries = [run_entry(1, "candidate_failed_holdout", train_expectancy=50.0, holdout_expectancy=-5.0, holdout_passed=False)]

    report = render_nightly_report(spec(), entries)

    assert "failed on holdout" in report
    assert "Treat as overfit" in report


def test_report_cli_reads_historical_journal_without_changing_inputs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    experiment = json.dumps(VALID_SPEC_DICT)
    journal = json.dumps(run_entry(1, "accepted", ma_fast=12)) + "\n\n"
    (tmp_path / "experiment.json").write_text(experiment, encoding="utf-8")
    (tmp_path / "journal.jsonl").write_text(journal, encoding="utf-8")
    monkeypatch.setattr(generate_nightly_report, "resolve_task_root", lambda _: tmp_path)
    monkeypatch.setattr(sys, "argv", ["generate_nightly_report", "--task", "historical"])

    generate_nightly_report.main()

    report = (tmp_path / "nightly_report.md").read_text(encoding="utf-8")
    assert "Iterations run: 1" in report
    assert "Holdout evaluations: 1" in report
    assert (tmp_path / "experiment.json").read_text(encoding="utf-8") == experiment
    assert (tmp_path / "journal.jsonl").read_text(encoding="utf-8") == journal
