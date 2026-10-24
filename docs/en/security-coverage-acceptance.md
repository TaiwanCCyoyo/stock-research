# Security coverage acceptance — 2026-10-24

The maintained summary and HTTP API were exercised against canonical sources;
ordinary tests used synthetic inputs. The frontend delivery has its own
`stock-discovery-acceptance.md` and synthetic screenshots in PR-B.

## Published generation

- Integrated base: `cf3b4ac` (includes the catalog migration in PR #88).
- Build code: `155f94aa1df050d6d3efc9a28d725905911b00ab`, clean working tree.
- Generation: `20261024T145327-4d9efa304de7`, under the configured shared root's
  `derived/security-coverage-v1/`; no private source copy or new schedule.
- 157,592 source-observed security identity keys and 1,103,144 cells. These are
  not 157,592 companies or a complete historical listing universe.
- 1,988 ordinary-share identities; 1,979 satisfy the recent-observation filter.
  ETF and unknown kinds remain separate. 1,572 ordinary-share identities have
  the supported institutional history limitation.
- All seven source scans succeeded. TWSE and TPEx institutional floors were
  independently observed at 2019-01-02. The concurrent pre-2019 staging backfill
  was not read or imported. A later canonical import requires this maintenance
  command to be run again.
- The indexed summary is 235,966,464 bytes. Small metadata, SQLite payload and
  status are published together with digest pins and an atomic pointer switch.

The first integration attempt exceeded the whole-JSON candidate's 128 MB limit
and published nothing. A later real-source check found that canonical metadata
uses Chinese market labels; normalizing 上市, 上櫃 and the innovation-board label
fixed the identity join before the delivery generation above was published.
Superseded generations are retained; their bytes are not rewritten.

## Build cost and bounds

Selected-code preflight used 2330, the metadata-confirmed 2023 listing 2645, and
the absent fictional control X123: 25.27 s wall, 1.33 s CPU, 144,687,104-byte
process lifetime peak. Its first official-price probe detected an input identity
change and correctly excluded that source; it is not a successful all-source
measurement. Subsequent full builds rechecked stable source/WAL identities.

The final full command used one worker and one in-flight source, with a 180 s
budget per source. The writer guard confirmed both `StockProject-*` tasks Ready;
it also retains the weekday 18:00–18:45 exclusion. The unrelated institutional
download wrote only its own staging location.

| Measurement                                                                  | Final observation                   |
| ---------------------------------------------------------------------------- | ----------------------------------- |
| Whole command, including startup, serialization and publication              | 104.48 s wall                       |
| Source reads, projection and code identity, before serialization/publication | 86.25 s wall; 59.00 s CPU           |
| Process lifetime peak observed at that phase end                             | 1,558,667,264 bytes                 |
| Process read/write transfer counters for that phase                          | 8,727,220,391 / 3,148,840,754 bytes |

The OS file cache was not flushed and earlier integration scans had run. Native
I/O counts include cached and library temporary I/O; they are not physical disk
throughput. The memory number is a process lifetime peak, not an isolated phase
peak. CPU, I/O and peak memory for serialization/publication were not separately
sampled. No stock-level parallelism was enabled on the strength of these results.

## Real HTTP measurement

Loopback Uvicorn HTTP, sequential standard-library requests, 50 rows per page.
Each endpoint had one first request and 20 warm samples. The first endpoint
missed the new-generation application cache; later endpoints shared that cache.
OS cache was not flushed. Numbers include HTTP, filtering, row decompression and
JSON serialization, and are distinct from the candidate's synthetic benchmark.

| Request                                       | Filtered identities | First request ms | Warm median ms | Warm p95 ms |
| --------------------------------------------- | ------------------: | ---------------: | -------------: | ----------: |
| Recent ordinary shares                        |               1,979 |           504.77 |         308.96 |      355.30 |
| Substring name/code search `q=2330`           |                  50 |           500.49 |         460.17 |      560.67 |
| Ordinary shares with institutional known gaps |               1,572 |           336.84 |         320.61 |      350.23 |
| Unresolved identities                         |             150,390 |           217.71 |         226.81 |      244.11 |
| Complete source-observed universe             |             157,592 |           216.00 |         224.34 |      240.28 |

The 2330 resolver returned one candidate and its opaque-key detail returned the
same code. An absent control returned zero candidates. The 50-row pagination
keeps the large historical/unknown population out of an unbounded browser render.

## Correctness and compatibility

Synthetic tests cover new listings versus known history gaps, per-market floors,
code reuse and long-gap segments, no-price revenue observations, explicit
delisting evidence, failed/missing summaries, all-source failure retention,
immutable publication, corruption, warm-cache mutation, full-set filtering and
counts, and public-synthetic isolation. The latest focused new suite passed 35
cases; the existing metadata reader tests were also exercised during integration.
Normal commit hooks passed without disabling checks.

`scripts.verify_published_artifacts` passed all 17 checks before the change,
after the reader changes, and after rebasing onto the catalog migration. All 17
rows, including detail strings, were identical. Catalog discovery continues
through its resolver; this task performed no physical relocation.

## Limits and rollout

Current metadata cannot prove delisting or reconstruct historical identity. The
real-data acceptance therefore does not claim a confirmed delisted example or
a proven code-reuse crosswalk; those branches were checked synthetically. Old
segments suppress latest names, aggregate periods/counts and code-only viewers.
Presence is not full-history completeness. Required-but-missing and not-applicable
marks remain reserved for evidence-backed obligations; a zero event count or
failed read is not automatically a confirmed gap.

Deploy PR-A's API and this family first, then PR-B's navigation and stock browser.
An unavailable API produces a retryable read error; an available API without a
built family produces an explicit summary-unavailable notice. Owner merge
and the separate Claude visual review remain independent from this evidence.
No producer schema, precise missing-session audit or complete identity-history
work is included.

Task-local diagnostics are under `.worktrees/security-coverage/.tmp/`:
`coverage-measure.json`, `coverage-update-delivery.json`,
`coverage-command-timing-delivery.json`, `coverage-http-benchmark.json`, and the
before/after published-artifact JSON. They are disposable evidence; the published
generation, source fingerprints and this record are the durable handoff.
