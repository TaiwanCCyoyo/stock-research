# Feature reuse and bounded stock execution: infrastructure v1

Owner-authorized follow-up to the completed HHHL v4 variants run, handed off on 2026-10-12. This is a separate infrastructure change and PR. Preserve the fixed HHHL mission, inputs, cache lineage, receipts, code bytes and results. No restart, market recomputation, downloads, producer/scheduler changes, trading or merge authority.

## Scope fixed before measurement and implementation

- Inventory existing assets and APIs first. Reuse `artifact_store` for paths, digests and no-replace publication, `WindowsProcessJob` for owned process teardown, and the public derived-feature definition for numerical parity. Existing whole-version caches and frozen HHHL semantics remain separate.
- Add an explicit, machine-queryable feature-block identity and immutable store. Identity includes feature/version, exact dependency and input hashes, original stock code, calendar, price basis, warmup/missing/pivot-availability policies, configuration and runtime. Cross-sectional context is mandatory for cross-sectional blocks. Match the complete identity before reuse; compute only missing/invalid requested blocks into new immutable versions. Never repair or overwrite corrupted historical bytes.
- Add a selective version of the shared gap-reset features. It computes only requested feature dependencies; it does not replace frozen v4 G/X4 semantics or automatically redirect old consumers.
- Add bounded stock-level execution with explicit worker/in-flight and memory/I/O budgets, fresh source-bound interpreters, stock-owned staging and confirmed Windows process ownership. Preserve all cross-sectional and global-selection barriers. Merge integer counts and stock sets before rates, in deterministic stock order.
- Thin CLI and public APIs expose plan/query and a synthetic benchmark. Formal market computation is out of scope for this task. No new market-derived cache or study result is created here.
- Update AGENTS.md with asset inventory, recomputation reasons, long-job estimation/measurement and bounded parallelism evaluation. Do not require unconditional no-recomputation or maximum CPU utilization.

## Measurement and acceptance

Before choosing execution bounds, retain the completed run's observed log boundaries and explicitly mark its unavailable CPU/RAM/I/O measurements; a static review is not profiling. Run a bounded deterministic synthetic benchmark with wall/CPU time, Python allocation/native process-memory observations where available, I/O/payload sizes and phase boundaries. Compare serial and bounded stock execution on identical invented inputs; report startup and serialization costs, including negative speedups. No timing threshold is a test gate.

Functional acceptance: selective/full numerical parity including gaps, warmup, equal extrema and confirmation dates; partial cache reuse and invalid/incompatible identity handling; no-replace/race protection; failure/timeout teardown; deterministic serial/parallel parity with no rate averaging; queryable data contract and asset-index row. Use normal hooks and current-head CI/review. Tests remain under scripts/tests, reusable implementation under research_core, CLI under scripts.

Benchmark dimensions fixed before execution: 16 invented stocks ×1,849 weekday rows; Close=100+stock ordinal+20*sin(calendar index/17), valid OHLC range ±1, invalid Quality every 283 rows after the first row. Compare direct full/selected calculation, then identical fresh owned-process barriers with 1 and 2 workers, 4 stocks per process and a 512MiB per-worker admission estimate under a 1GiB total budget. Requested features are SMA20, ATR14 and pivots_1p5; test a subsequent one-stock EMA20 addition to demonstrate partial reuse. No worker-count/feature-parameter sweep or speedup pass threshold. Record the machine's observed resources and both positive/negative timing differences.

Worktree: `D:/Project/stock-research/.worktrees/research-feature-reuse`, owned by chat `01a12bfc-b535-7352-bef7-68fe3a56901e`, branch `codex/research-feature-reuse`, started from origin/main `abd286ee10d447502a965f269224bf9da4ca11db`. The completed HHHL worktree remains retained for open PR #9. Inventory showed only these pre-existing primary/task checkouts; no other checkout was removed.
