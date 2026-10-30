# stock-research PR Review

The implementing agent owns [PR follow-through](git-workflow.md#pr-follow-through): assess findings, fix and verify valid issues within scope, push the fixes, and promptly resolve addressed threads before waiting for current-head CI and renewed review. Resolution does not guarantee that a new review will start; verify its actual status before reporting completion. The owner retains merge authority.

Target repository: `TaiwanCCyoyo/stock-research`, base `main`. Branch protection has not been
verified for this repository; see [PR setup](pr-setup.md).

## Current workflow

- The upstream sync and its policy-review follow-ups may publish task branches
  and PRs using the configured owner identity; see
  [Git workflow](git-workflow.md).
- Local commits and `repository-checks` run the same hooks, including both mypy
  and Pyright; the hosted job runs them on Windows. Formatting,
  whitespace, YAML, large-file, secret, encoding and Ruff checks remain enabled.
- `scripts/ci_scope.py` selects Python tests by domain from
  `scripts/ci_test_domains.json`. New files route like modified ones, by the
  domain that owns their location. A changed test file runs itself and every test that directly or
  indirectly imports it, retaining their frontend build prerequisites without
  treating the test as a source change to every domain it verifies. Study-card
  records select their reader, API and dashboard contracts plus frontend checks;
  other task owners still contribute their tests. Scratch changes include the
  study-card progress consumer. An unmapped
  `tasks/` or `docs/` record selects the record contracts plus the tests and owned
  code that mention its task id or file name; a task `web-report/` adds frontend
  checks. Shared and configuration paths, unowned code, and records read by unowned
  code fall back to the full suite. The producer gitlink selects only its link
  contracts, because CI never checks out or runs producer code.
  Legacy files outside the change are not newly subjected to targeted type checks.
  It does not download market data, initialize the data submodule or run studies.
- PR title/body edits produce only a separately named skipped metadata check,
  with a separate concurrency group. They neither replace `repository-checks`
  nor cancel an in-flight validation. Base-branch edits still validate, as do
  new commits and ready-for-review events. Manual dispatch retains full validation.
- Hooks and selected tests use the same merge-base/head diff. A base branch
  advancing does not by itself add unrelated files to the hook invocation.
- Reviews check placement as well as behavior: AGENTS.md
  [Project Layout And Ownership](../../AGENTS.md#project-layout-and-ownership) says
  where code, tests, data and records belong, and which placement findings to raise.
- Internal reviewer reports do not count as hosted review or GitHub approval.
- Hosted Codex review reports actionable findings;
  its comments do not grant approval or merge authority. Confirm it reviewed the
  current head and address unresolved findings before owner integration.
- Merging stays with the owner, through the PR after its current checks pass.
  Never bypass checks, weaken rules or push directly to `main`.

## Intended protection

Require a PR, resolved conversations and a successful `repository-checks` from
GitHub Actions; require the branch to be current, block deletion and force pushes,
and leave bypass actors empty. With one owner identity, require zero approving
reviews because the author cannot approve their own PR. This is the observed
upstream model, not a claim that stock-research already enforces it.

Observed evidence (2026-09-20): [PR #5 review](https://github.com/TaiwanCCyoyo/Stock/pull/5#issuecomment-5747122478), [main CI](https://github.com/TaiwanCCyoyo/Stock/actions/runs/35485837491). A passing CI job does not prevent a direct push without branch protection.
