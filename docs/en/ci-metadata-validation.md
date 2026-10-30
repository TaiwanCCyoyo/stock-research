# Required checks after PR edits

PR validation keeps one required job name, `repository-checks`, on Windows.
Title and body edits run the normal selected validation scope, including hooks
and the tests selected from that event's head and base. They do not publish a
no-op or skipped success in place of code validation.

This deliberately costs another scoped run when PR metadata changes. The earlier
`metadata-edit-ignored` path left PR125 waiting for `repository-checks` despite a
successful code run on the same head from the configured GitHub Actions App.
The observed name/suite mismatch motivates the simpler path; it does not establish
GitHub's internal status-selection algorithm or justify relaxing branch protection.

## Event and concurrency behavior

For PRs targeting `main`, all runs share the workflow/PR concurrency group. The event supplies the head
and base used by scope selection; a successful run on an older head is not evidence
for a new head.

| Event                                                   | Validation                   | Active run                   |
| ------------------------------------------------------- | ---------------------------- | ---------------------------- |
| Title/body-only `edited`                                | Normal selected scope        | Continues; the new run waits |
| Base-changing `edited`                                  | Scope from the new base/head | Superseded                   |
| `synchronize`, `opened`, `reopened`, `ready_for_review` | Normal selected scope        | Superseded                   |
| `workflow_dispatch`                                     | Explicit full validation     | Separate run group           |

GitHub's default concurrency policy retains at most one pending run. A newer event
can replace a run that has not started, even when it does not cancel the active
run. The replacement still performs real validation using its event context.
Inspect head, base, draft state and actual steps when diagnosing event ordering;
the job name alone does not prove those inputs were validated.

Keep `edited`: removing it would also remove validation on base retargets.
Retargeting away from `main` is outside this workflow's branch filter; returning
to `main` must start real validation even when the head is unchanged.
Keep `ready_for_review` and the existing draft full-validation failure gate:
limited draft checks must not certify the full validation as passed.

## Hosted acceptance

Use a dedicated CI PR for event testing, without changing other PRs or protection.
Local workflow-contract tests cannot establish GitHub merge eligibility.

1. Record the exact head/base, required context/App binding and current runs.
2. Edit the title or body while validation is running. Verify the original run
   is not cancelled, and the queued metadata run executes the real required job.
3. After success, edit metadata again on the same head. Verify the real run and
   inspect the server's merge state, not just a green check-run conclusion.
4. Push a new head and verify it cannot use the old head's pass. Exercise
   draft-to-ready and retarget/back transitions, checking the new event context.
5. Compare the required context/App binding before and after. Record any missing
   scenario or unresolved state; do not fabricate statuses or attempt a merge to
   claim that protection works.

An eligible merge state is evidence about GitHub checks, not owner acceptance or
merge authority. The owner's separate visual-acceptance holds remain in force.

References:

- [GitHub required-status troubleshooting](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
- [GitHub workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
