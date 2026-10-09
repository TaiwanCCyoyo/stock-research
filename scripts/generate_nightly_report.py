"""Render historical `nightly_report.md` from a stored journal.jsonl.

The retired iteration runner is not required or invoked.

Every line in the report is derived directly from journal entries and the
experiment spec; nothing here is generated or paraphrased by a model, so the
report can never claim something the journal cannot substantiate.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from scripts.experiment_spec import ExperimentSpec, load_experiment_spec
from scripts.logging_utils import configure_logging
from scripts.run_task_backtest import resolve_task_root

LOGGER = logging.getLogger(__name__)

REPORT_FILENAME = "nightly_report.md"
JOURNAL_FILENAME = "journal.jsonl"
STOPPED = "stopped"
REJECTED = "rejected"
RUN = "run"
DECISION_ACCEPTED = "accepted"
DECISION_CANDIDATE_FAILED_HOLDOUT = "candidate_failed_holdout"
DECISION_TRAIN_FAILED = "train_failed"


def load_journal(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.is_file():
        return []
    entries = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            entries.append(json.loads(stripped))
    return entries


def count_holdout_evaluations(entries: list[dict[str, Any]]) -> int:
    """Number of journaled entries that actually spent a holdout run (train-gate winners only)."""
    return sum(1 for entry in entries if entry.get("holdout_gate") is not None)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _run_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("kind") == RUN]


def _rejected_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("kind") == REJECTED]


def _stopped_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The loop's current stopped state: only the tail entry counts (a resumed loop can outlive an old stop line)."""
    if entries and entries[-1].get("kind") == STOPPED:
        return entries[-1]
    return None


def _train_expectancy_key(entry: dict[str, Any]) -> float:
    value = (entry.get("train_gate") or {}).get("metrics", {}).get("expectancy")
    return value if value is not None else float("-inf")


def _render_summary(entries: list[dict[str, Any]]) -> list[str]:
    runs = _run_entries(entries)
    accepted = [entry for entry in runs if entry.get("decision") == DECISION_ACCEPTED]
    candidates = [entry for entry in runs if entry.get("decision") == DECISION_CANDIDATE_FAILED_HOLDOUT]
    train_failed = [entry for entry in runs if entry.get("decision") == DECISION_TRAIN_FAILED]
    rejected = _rejected_entries(entries)
    stopped = _stopped_entry(entries)

    lines = [
        "## Summary",
        "",
        f"- Iterations run: {len(runs)}",
        f"- Accepted (passed both windows): {len(accepted)}",
        f"- Candidate, failed holdout: {len(candidates)}",
        f"- Train failed: {len(train_failed)}",
        f"- Rejected moves (out of declared bounds): {len(rejected)}",
        f"- Holdout evaluations: {count_holdout_evaluations(entries)}",
        f"- Stopped: {stopped['reason'] if stopped else 'not yet stopped'}",
    ]
    return lines


def _render_iteration_log(entries: list[dict[str, Any]]) -> list[str]:
    runs = _run_entries(entries)
    if not runs:
        return ["## Iteration Log", "", "No iterations have run yet."]

    lines = [
        "## Iteration Log",
        "",
        "| Iteration | Decision | Rationale | Train Expectancy | Train Payoff | Train PF | Holdout Expectancy | Holdout Payoff | Holdout PF |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in runs:
        train_metrics = (entry.get("train_gate") or {}).get("metrics") or {}
        holdout_metrics = (entry.get("holdout_gate") or {}).get("metrics") or {}
        rationale = (entry.get("move") or {}).get("rationale", "")
        lines.append(
            "| {iteration} | {decision} | {rationale} | {t_exp} | {t_pay} | {t_pf} | {h_exp} | {h_pay} | {h_pf} |".format(
                iteration=entry.get("iteration"),
                decision=entry.get("decision"),
                rationale=rationale,
                t_exp=_fmt(train_metrics.get("expectancy")),
                t_pay=_fmt(train_metrics.get("payoff_ratio")),
                t_pf=_fmt(train_metrics.get("profit_factor")),
                h_exp=_fmt(holdout_metrics.get("expectancy")),
                h_pay=_fmt(holdout_metrics.get("payoff_ratio")),
                h_pf=_fmt(holdout_metrics.get("profit_factor")),
            )
        )
    return lines


def _render_rejected_moves(entries: list[dict[str, Any]]) -> list[str]:
    rejected = _rejected_entries(entries)
    if not rejected:
        return []

    lines = ["## Rejected Moves", ""]
    for entry in rejected:
        dimension_values = (entry.get("move") or {}).get("dimension_values", {})
        reasons = "; ".join(entry.get("reasons", []))
        lines.append(f"- {dimension_values}: {reasons}")
    return lines


def _render_recommended_next_step(entries: list[dict[str, Any]]) -> list[str]:
    runs = _run_entries(entries)
    accepted = [entry for entry in runs if entry.get("decision") == DECISION_ACCEPTED]
    candidates = [entry for entry in runs if entry.get("decision") == DECISION_CANDIDATE_FAILED_HOLDOUT]

    lines = ["## Recommended Next Step", ""]
    if accepted:
        best = max(accepted, key=_train_expectancy_key)
        lines.append(
            f"- Iteration {best.get('iteration')} passed gates on both train and holdout windows "
            f"(params {best.get('move', {}).get('dimension_values')}). Review it for daytime promotion."
        )
    elif candidates:
        best = max(candidates, key=_train_expectancy_key)
        lines.append(
            f"- Iteration {best.get('iteration')} passed train gates but failed on holdout "
            f"(params {best.get('move', {}).get('dimension_values')}); reasons: "
            f"{'; '.join((best.get('holdout_gate') or {}).get('reasons', []))}. Treat as overfit; "
            "consider fewer tunable dimensions or a different starting hypothesis."
        )
    elif runs:
        lines.append("- No iteration passed train gates yet. Review the iteration log above before the next run.")
    else:
        lines.append("- No iterations have run yet; check rejected-move reasons above if any moves were proposed.")
    return lines


def render_nightly_report(spec: ExperimentSpec, entries: list[dict[str, Any]]) -> str:
    """Build the full nightly_report.md content from the spec and journal entries."""
    sections: list[list[str]] = [
        ["# Nightly Research Report", "", "## Hypothesis", "", spec.hypothesis],
        _render_summary(entries),
        _render_iteration_log(entries),
        _render_rejected_moves(entries),
        _render_recommended_next_step(entries),
    ]
    lines: list[str] = []
    for section in sections:
        if not section:
            continue
        if lines:
            lines.append("")
        lines.extend(section)
    return "\n".join(lines) + "\n"


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Render nightly_report.md from a task's experiment.json and journal.jsonl.")
    parser.add_argument("--task", required=True, help="Task path under tasks/, such as sample or tasks/sample")
    parser.add_argument("--experiment", default="experiment.json", help="Experiment spec path relative to the task")
    args = parser.parse_args()

    task_root = resolve_task_root(args.task)
    spec = load_experiment_spec(task_root / args.experiment)
    entries = load_journal(task_root / JOURNAL_FILENAME)
    report = render_nightly_report(spec, entries)
    (task_root / REPORT_FILENAME).write_text(report, encoding="utf-8")
    LOGGER.info("wrote %s", task_root / REPORT_FILENAME)


if __name__ == "__main__":
    main()
