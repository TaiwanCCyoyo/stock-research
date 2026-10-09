# Execution record: interactions-v1

2026-10-05. Parent approval recorded before execution, under the active owner
research goal and this task's fixed mission. This is one exploratory run only.

- Code, mission and consumer contract sealed at `7183118` after 44 synthetic
  tests passed and normal commit hooks passed. Earlier hook findings concerned
  formatting and pandas type annotations, not observed market results.
- Packet preparation enumerated and hashed 1,980 code/data/contract files without
  loading market observations or calculating new comparisons.
- Exact packet is `preregistration/interactions-v1.json.gz`; the execution copy
  is `params/interactions-v1.json`. It must decompress to identical bytes.
- Approved packet digest: `0e298709150dd19665049912dcb31a4c34a512377cc96ac1bf8557a8a523d48b`. <!-- pragma: allowlist secret -->
- Authorize ONE invocation through `scripts/run_registered_job.py --execute`
  with that exact digest, 1,800-second subprocess timeout, existing output-root
  refusal, no sweep, no new stock dates, and no confirmation / holdout.
- No output exists at approval time. Completion, diagnostics and scientific
  judgment will be appended below without changing the approved inputs.

Runtime and per-file identities are in the compressed packet. This approval
record is intentionally outside its read-set, so later completion notes do not
change what was approved. Source/definition changes require a new job identity;
the mission permits at most one implementation-only diagnosed retry.

## Completion

The packet was committed at `6f59919` before the one approved invocation.
`interactions-v1` completed without retry in 70.531 seconds, starting at
2026-10-05T02:12:00.747779+00:00. Input identity checks passed before and after
execution. Output: 624 comparisons, 1,872 path summaries, six triage candidates,
no nomination. This is a completed experiment with failed candidate promotion,
not a data blockage or invalid measurement. All rows, not just favorable results,
were published in `publication-v1` with the original receipt and packet.

Publication verified reuse twice, copied exact code/contracts (including the
pre-append exposure registry) and checked saved receipt bindings before writing
its completion manifest. The registry append after publication is expected to
change the active registry hash; do not alter the sealed packet to fit it.
See `report.md` for evidence, scientific limits and the next bounded direction.
