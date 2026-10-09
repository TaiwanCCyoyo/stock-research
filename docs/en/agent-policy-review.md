# Agent Policy Review — 2026-09-20

Scope: agent instructions, configuration, skills/commands, role descriptions,
hooks, tooling tests and PR delivery. This is not an audit of every trading-engine
algorithm or a new research run. Upstream `119f15e` is a comparison baseline,
not automatic authority over the owner's latest principles.

| Finding                                                                        | Resolution                                                                                                                     |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| Stock retained obsolete push ask/deny settings                                 | Adopt upstream removal; keep PR/main/merge boundaries in the Git contract.                                                     |
| Commit skills and agents ran pre-commit twice                                  | Remove standalone prerequisite; normal commit hooks handle checks and failures.                                                |
| Claude commits always required a specialist; specialists assumed the wrong cwd | Allow direct execution, optional scoped delegation and explicit worktree paths.                                                |
| Sync treated every divergence as permanent                                     | Reassess each against current benefit; preserve data, not obsolete instructions.                                               |
| Tests froze model aliases and policy prose                                     | Remove those assertions; retain config/permission structure and executable hook/research tests.                                |
| Legacy night loop reused holdout results for search                            | Retire the active skill recipe; retain historical harness/data. A train-only replacement remains separate implementation work. |
| Claude runner/diagnosis lacked current research boundaries                     | Require registered scope/fresh output; use preregistered verdicts and train-only hypotheses.                                   |
| OpenSpec selection ignored established user choices                            | Reuse explicit context; ask only for ambiguity or new unaccepted incompleteness.                                               |
| PR docs claimed review was not configured                                      | Record observed CI/review success and the actual private-plan protection limit.                                                |

Retained differences have specific reasons: Stock runtime dependencies and optional
OpenSpec support; UTF-8-only prose policy; read-only batch hook handling; the Claude
root import; targeted CI typing to avoid expanding into legacy runtime cleanup;
and immutable research evidence, writer coordination and physical cache copies.
The upstream AnyIO bump is a runtime dependency update, not an agent setting;
it remains separate from this policy review rather than replacing Stock's lock.
Historical study artifacts, cache data, submodule pins and research computations
were not changed. No global configuration, repository rules or credentials were changed.
