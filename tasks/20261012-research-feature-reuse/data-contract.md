# Feature blocks and bounded stock execution v1

This infrastructure is independent of the completed HHHL publication. It creates no market-derived cache, changes no producer or scheduler, and does not redirect historical consumers. Numerical feature definitions remain `derived-features.v1`; selective calculation is a new API version.

## Identity and discovery

`research_core.feature_identity_v1.validate_identity` validates complete JSON identities under `research-feature-block.v1`. Required fields bind the feature and definition metadata, original string stock code, stock/cross-sectional scope, all declared input and implementation SHA-256 values, explicit calendar hash/rows/start/end, price basis, gap/warmup/pivot availability/calendar/quality policies, parameters and runtime. Cross-sectional context is mandatory for cross-sectional scope. Unknown keys, missing information, nonfinite numbers and implicit coercions are rejected. Identity is a canonical digest, not a scientific equivalence or PIT certificate.

`FeatureBlockStore(Path(absolute_root)).plan(identities)` returns `reusable`, `missing`, `invalid` or `conflict` for each request, with retained invalid-generation reasons. Complete exact matches are reused. Valid generations with different output bytes under one identity are conflicts, never ranked or silently selected. An identity change requires a new block; partial numerical similarity is insufficient.

Future approved market blocks have one canonical home: `D:/Project/stock-research/research_cache/feature-blocks-v1/<identity_digest>/<generation_digest>/`. Each immutable generation contains nonempty declared artifacts and `manifest.json` under `research-feature-publication.v1`. Publication uses exclusive locks and the shared native no-replace primitive. Corrupted generations are retained; recovery adds a generation. Failed locks/staging remain diagnostic evidence and require an ownership audit before any removal. There is no live-data fallback or mutable latest.

Retain the returned reference, including absolute path, identity/version digests, artifacts and external `manifest_sha256`, in the consuming mission/receipt. `store.read(identity, "values.parquet", reference=reference)` verifies path, identity, manifest pin, complete inventory and returned bytes. Generic publication accepts declared byte payloads; the caller owns the scientific definition. The stock adapter independently reconstructs its supported feature contract and actual prepared calendar before reuse and in the worker.

## Supported calculation and execution

`derived_features_selective_v1.compute_selected(prepared, features)` supports the shared SMA5/10/20/60/120, EMA5/10/20/60, ATR14, atr14_pct, BB20 bands and 1.5/4 ATR confirmed pivots. Metadata states exact formula, gap reset and warmup. Only requested outputs and their necessary dependencies are calculated: a missing pivot can require ATR calculation even if an ATR output block exists. This version does not inject unchecked cached intermediate arrays. Extreme dates are retrospective; `confirmed_at` is availability, and unconfirmed endpoints are omitted. Original v4 G/X4 and their missing-price semantics remain frozen and separate.

`stock_feature_pool_v1.make_stock_request` binds an explicit absolute prepared-stock Parquet snapshot and price basis; it does not calculate features. The reader rejects files over 64 MB, over 100,000 rows, over 64 columns, nested schema or footer/expanded-data violations of the public bounded reader (1 MB footer, 32 MB expanded limit). Daily calendars must be nonempty, unique, increasing, timezone-free DatetimeIndex values; invalid-price rows remain in the calendar.

`run_stock_requests(requests, store, fresh_staging, budget=ExecutionBudget(...))` is an execution API, not research authorization. It rejects cross-sectional and mixed-stock work. Source-bound fresh workers compute only missing/invalid requested blocks, with at most eight stocks per process; defaults are two processes, four stocks/process, a 512 MiB per-worker estimate and a 1 GiB total admission budget. Host CPU/available-memory observations can lower admission. These estimates plus post-run observed worker peaks are not hard OS memory limits. Per-stock reader bounds and bounded in-flight processes constrain I/O; no disk-bandwidth guarantee is claimed. Timeout/failure confirms teardown through owned Windows Job Objects; failure keeps diagnosis and prevents a complete barrier receipt.

All workers complete before any feature publication or global consumer proceeds. Stock order is deterministic; `feature_identity_v1.merge_count_batches` merges integer counts and distinct stock sets for one exact slice with unique batch IDs before rates. The scheduler does not implement cross-sectional H/J/K3 ranks, selection, labels, account backtests or a whole-study publisher. Upper layers retain those global barriers and preregistration requirements.

The runtime identity binds Python/numpy/pandas/pyarrow and exact execution source hashes. Numeric dependencies remain the declared installed runtime, not a hermetic environment. The compiled repository modules are trusted source, not an untrusted-code sandbox.

## Access and reproduction

The thin CLI provides metadata planning/query and the fixed **invented-input** benchmark only. See `uv run python -m scripts.feature_blocks --help` and each command's `--help` for arguments. No CLI command runs a market study. Library callers supply approved missions and immutable inputs separately.

The [mission](mission.md) fixes benchmark dimensions and execution bounds before measurement. [Report](report.md) and its portable compressed receipt retain numerical/byte parity, timings, resource observations, negative speedups and partial-reuse counts. Synthetic payloads remain in task-owned scratch; Git contains the reusable implementation, tests, this contract and small measured evidence. Historical HHHL logs retain only observed boundaries; unavailable historical CPU/RAM/I/O are explicitly unknown.
