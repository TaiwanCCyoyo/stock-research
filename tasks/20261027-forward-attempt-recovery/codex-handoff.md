# O2a deployment handoff

Implementation owner: Codex O2a session, isolated worktree
`D:/Project/stock-research/.worktrees/forward-attempt-recovery`, branch
`codex/forward-attempt-recovery`, initially based on fetched `origin/main` 735cd724
and subsequently normally merged with main 39991b45 (PR100).
Keep this worktree for its open draft PR. Other worktrees, primary dirty submodule,
untracked production forward-log, and unknown thread 01a17bce remain unowned by
this session; the inventory is not a claim that all concurrent work is conflict-free.

**Production: pending deployment.** This change does not alter a task action,
run a production root, populate historical attempts, or start an actual study.
See [data contract](data-contract.md) for physical journal/ledger compatibility,
recovery, uncertainty and corruption stop behavior.

## Unmet publication-deadline acceptance

Switching to v2 improves invocation traceability and crash recovery only.
It does not repair v1's publication-deadline gap. Production remains pending
deployment; green CI is not evidence that a day/cohort was published before 09:00.

| Synthetic case                                                                     | Evidence and acceptance status                                                                                                            |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Calculation itself crosses Taipei 09:00                                            | Existing v1/v2 calculation-crossing tests pass: the last v1 clock check observes the crossing and records late.                           |
| `day_frame` completes at 08:59:59; serialization/publication completes at 09:00:01 | Astra reproduced `recorded_late=False`, v2 `on_time` and cohort creation. The intended complete-publication deadline is **failed/unmet**. |

The [original Astra review record](https://github.com/TaiwanCCyoyo/stock-research/pull/102#issuecomment-6435304921)
retains the serialization-crossing failure and direct-v1/scheduled-v2 diagnostic
results. This patch leaves the original reviewer-owned failing test/log untouched.
It does not rewrite the assertion to expect the incorrect `on_time`, mark that
case repaired, or treat successful reproduction of the defect as a passing fix.

V1's public `record_day` performs computation, serialization, day publication and
cohort creation in one call, without a prepare/publish hook. An outer adapter
cannot enforce a complete-publication deadline after that call returns. A full
deadline protocol is a separately scoped versioned integration gap. This PR does
not copy v1, install a runtime monkeypatch, call private helpers as a workaround,
or rewrite frozen day/cohort artifacts.

The timestamps must keep their stage meanings: `recorded_at_utc` and the copied
`first_frozen_at_utc` precede serialization; `finished_at_utc` marks entry into v2
finalization, before metadata/terminal/ledger fsync. A normal `run` return guarantees
terminal persistence and ledger projection; there is no precise durability-finish
timestamp. Recovered interrupted attempts remain completion-unknown with a null
`finished_at_utc`.

## Proposed action after owner review and merge

The candidate command, from the approved production checkout at the reviewed
merged commit, is:

```powershell
uv run python -m scripts.record_momentum_forward_day_v2 --scheduled --workers 4 --root D:/Project/stock-research/tasks/20261021-momentum-only-doubling/forward-log
```

This is a proposed future replacement for the recorder invocation, **not executed**
by this PR. Preserve the existing task's triggers, principal, settings and enabled
state; task changes require the separately authorized deployment. Do not run both
versions together. Do not run a real-root smoke test as part of code verification.
The initial deployment must also account for any pre-existing invocation without
a v2 durable start: it cannot be reconstructed or deemed successful by this code.

Before switching, the deployment owner must verify:

1. The exact Windows recorder task name, current action/launcher/working directory,
   enabled state and all manual/child v1 writers. Wait for current writers to exit
   naturally and prevent new starts through the authorized deployment procedure.
2. The producer's `StockProject-*` writers and weekday 18:00–18:45 Taipei exclusion,
   the shared generation updater's current status/path and the intended recorder
   start/wait relationship. This PR changes none of those schedules.
3. The actual approved checkout/commit and external producer/shared-data resolvers,
   the exact forward root above, filesystem no-replace and local OS locking support,
   and permissions for new journal/lock/ledger files. V2 locks coordinate only v2.
4. Existing `attempts.jsonl`, `days/`, `cohort.json` and any v2 remnants: preserve
   bytes. Inspect corrupt/partial records manually; never delete lock files or
   truncate a ledger to make a recorder start. Foreign/unknown owners stay pending.
5. The actual first future on-time frozen day under v1 timing/evidence rules. No
   promised start date, fabricated cohort, historical success, or F1 activation.

To inspect records after an authorized switch, use the public
`research_core.momentum_forward_attempts_v2.read_attempts(Path(root))` adapter;
`physical_ledger` distinguishes legacy rows. There is no new production recovery
command to run casually: each accepted v2 recorder invocation reconciles abandoned
local attempts before market work and records its own terminal.

## Validation and retained boundaries

Only temporary synthetic roots and explicitly created test children are used.
The focused test invocation is:

```powershell
uv run --group dev python -m pytest scripts/tests/test_momentum_forward_attempts_v2.py scripts/tests/test_momentum_forward_run_v2.py scripts/tests/test_momentum_forward_v1.py
```

Normal commit hooks and CI scope selection remain enabled. V1 module, CLI, mission,
roadmap, E1/S7 documents and all production data remain byte-identical. If code
review identifies a required v1 adapter, stop and obtain that bounded scope rather
than editing frozen code or changing research semantics.

The CI follow-up adds `momentum_forward_v2` consumers to `research_data` and
`momentum_only`. Exact A/M selection assertions cover `momentum_forward_v1.py`,
`maintained_adjusted_daily.py` and `live_producer.py`, including both v2 suites and
the v1 suite. Existing exact domain/test-set assertions remain exact, and unknown
forward paths retain full fallback. `test_ci_scope.py`: **219 passed**; this is CI
coverage evidence, separate from the unresolved serialization/publication case.
