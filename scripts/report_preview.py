"""Gate, package and reconcile the label-driven static report preview site.

Subcommands:
  check      gate the reports a local branch changes (index + working tree), no output written
  reconcile  list eligible PRs now, read each head as git objects, gate and write the whole site
  verify     re-list PRs right before deployment; fail if any built entry went stale
  comment    after a successful deployment, update each affected PR's single marker comment
"""

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_core import report_preview as rp

LOGGER = logging.getLogger("report_preview")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _api() -> rp.UrllibGitHubApi:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise rp.ReconcileError("GH_TOKEN is not set")
    return rp.UrllibGitHubApi(token)


def _current_pulls(api: rp.GitHubApi, repository: str, base_branch: str) -> list[rp.PullRequest]:
    pulls = rp.eligible_pulls(rp.list_open_pulls(api, repository, base_branch), repository, base_branch)
    LOGGER.info("eligible PRs now: %s", ", ".join(f"#{p.number}@{p.head_sha[:7]}" for p in pulls) or "(none)")
    return pulls


def cmd_check(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    ids = rp.report_ids(rp.changed_files(repo, args.base, args.head))
    LOGGER.info("changed report ids: %s", ", ".join(ids) or "(none)")
    if not ids:
        return 3
    try:
        planned = rp.gate_reports(repo, "INDEX" if args.head == "HEAD" else args.head, ids)
    except rp.PreviewGateError as error:
        LOGGER.error("preview gate failed (%d violation(s)); rule and masked path only:", len(error.violations))
        for violation in error.violations:
            LOGGER.error("  %s", violation)
        return 1
    LOGGER.info("gate passed: %d file(s) from %d report(s)", len(planned), len({p.report_id for p in planned}))
    return 0


def cmd_reconcile(args: argparse.Namespace, api: rp.GitHubApi | None = None) -> int:
    repo = args.repo.resolve()
    site: Path = args.site
    if site.exists() and any(site.iterdir()):
        LOGGER.error("site folder is not empty")
        return 2
    try:
        pulls = _current_pulls(api or _api(), args.repository, args.base_branch)
    except rp.ReconcileError as error:
        LOGGER.error("cannot determine PR state; nothing will be deployed: %s", error)
        return 1
    built_at = _now()

    def fetch(sha: str) -> None:
        rp.git(repo, "fetch", "--no-tags", "--quiet", "origin", sha)

    def build(pull: rp.PullRequest) -> rp.PrOutcome:
        outcome = rp.build_pull(repo, site, pull, args.base_ref, built_at, fetch)
        LOGGER.info("PR #%d@%s: %s", pull.number, pull.head_sha[:7], outcome.status)
        for violation in outcome.violations:
            LOGGER.warning("  %s", violation)
        return outcome

    plan = rp.plan_site(pulls, build, drop=lambda number: rp.remove_pull_output(site, number))
    rp.write_site_root(site, plan, built_at, args.gate_commit)
    previous = rp.read_previous(args.previous_url) if args.previous_url else None
    if args.previous_url and previous is None:
        LOGGER.warning("live preview list unreadable; removal comments will be skipped")
    state = {**plan.to_json(), "built_at": built_at, "previous": None if previous is None else sorted(previous)}
    args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("site: %d included, %d rejected, %d without report changes", len(plan.included), len(plan.rejected), len(plan.no_reports))
    return 0


def _load_state(path: Path) -> tuple[rp.SitePlan, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return rp.SitePlan.from_json(raw), raw


def cmd_verify(args: argparse.Namespace, api: rp.GitHubApi | None = None) -> int:
    plan, _ = _load_state(args.state)
    try:
        pulls = _current_pulls(api or _api(), args.repository, args.base_branch)
    except rp.ReconcileError as error:
        LOGGER.error("cannot re-check PR state; not deploying: %s", error)
        return 1
    problems = rp.stale_entries(plan.included, pulls)
    for problem in problems:
        LOGGER.error("stale build: %s", problem)
    if problems:
        LOGGER.error("not deploying; the queued or scheduled run rebuilds from the new state")
        return 1
    LOGGER.info("built set still matches the current PR state")
    return 0


def cmd_comment(args: argparse.Namespace, api: rp.GitHubApi | None = None) -> int:
    plan, raw = _load_state(args.state)
    previous_raw = raw.get("previous")
    previous = None if previous_raw is None else {int(n) for n in previous_raw}
    bodies = rp.comment_plan(plan, previous, _now(), args.page_url, args.run_url)
    try:
        for line in rp.apply_comments(api or _api(), args.repository, bodies):
            LOGGER.info(line)
    except rp.ReconcileError as error:
        LOGGER.error("comment update failed (the deployment itself succeeded): %s", error)
        return 1
    if plan.rejected:
        LOGGER.error("%d PR(s) were rejected by the gate and are not published", len(plan.rejected))
        return 4
    return 0


def parser() -> argparse.ArgumentParser:
    main_parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = main_parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="gate the reports a local branch changes")
    check.add_argument("--repo", type=Path, default=Path.cwd())
    check.add_argument("--base", default="origin/main")
    check.add_argument("--head", default="HEAD", help="HEAD gates the index and working tree; any other ref gates that commit")

    for name in ("reconcile", "verify", "comment"):
        command = sub.add_parser(name)
        command.add_argument("--repository", required=True, help="owner/name")
        command.add_argument("--base-branch", default="main")
        command.add_argument("--state", type=Path, required=True, help="site state JSON written by reconcile")
        if name == "reconcile":
            command.add_argument("--repo", type=Path, default=Path.cwd(), help="checkout of the base branch (trusted gate code)")
            command.add_argument("--site", type=Path, required=True, help="empty output folder for the whole site")
            command.add_argument("--base-ref", default="origin/main")
            command.add_argument("--gate-commit", required=True)
            command.add_argument("--previous-url", help="live previews.json, read best-effort for removal comments")
        if name == "comment":
            command.add_argument("--page-url", required=True)
            command.add_argument("--run-url", required=True)
    return main_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    handlers = {"check": cmd_check, "reconcile": cmd_reconcile, "verify": cmd_verify, "comment": cmd_comment}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
