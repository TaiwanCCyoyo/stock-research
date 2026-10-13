# Annual winner rotation data contract v1

Start with [mission](mission.md) and [report](report.md). This independently
registered study uses `annual-rotation.v1`; it does not consume or alter PR #14.

## Shared ownership and access

The primary `research_data/catalog.json` is the single discovery entry. The
worktree contains only the original physical producer snapshot supplied by its
checkout hook. Prepared immutable inputs and process outputs are published
through PR12 `research_core.research_data_builder.publish_bundle`, verified by
`DataCatalog.get`, and read directly through an external absolute root. There
are no symlinks, junctions, hardlinks, worktree copies of shared versions, new
mutable formula caches or new backup/scheduler code.

`params/input-pin-v1.json` selects the frozen input version. `sweep_results.json`
selects both input and process versions with external manifest SHA256 pins.
The input bundle retains `price_daily.parquet`, `corporate_actions.sqlite`,
`symbol_meta.sqlite` and a reduced seeder provenance record for those files.
Other producer data are never read. The original shared/producer datasets,
metadata vintages and sealed studies are not rewritten. Exact versions are
inside primary `research_data/prices/annual-rotation-inputs/<version>/` and
`research_data/episodes/annual-rotation-process/<version>/`.

Git carries aggregate results, code and contracts. Real quote vectors,
candidate anchor samples, cash estimates and daily paths remain in the local
shared bundle, consistent with the existing public-export boundary. A fresh
clone without those bundles fails closed; it never downloads or substitutes
today's data. The existing research-data backup scope includes these paths;
backup of these exact versions is **unverified**, not promised by scope inclusion.

```powershell
$env:STOCK_RESEARCH_DATA_ROOT = 'D:/Project/stock-research/research_data'
uv run python tasks/20261013-annual-winner-rotation/run_study.py verify --output tasks/20261013-annual-winner-rotation/sweep_results.json
uv run python -m scripts.research_data catalog
```

For replay, use the existing input pin and measured worker setting, and a new
owned output path. Output JSON is created exclusively. Reuse verifies immutable
bytes; it does not rerun market calculations. Source changes require a new
source/version/run; never re-pin old results after formatting.

`verified_result` compares every public value with the process bundle's stored
`results.json`, checks registered input/process/source and archived source member
digests, and rejects a changed verdict, return or otherwise valid swapped input.
Numeric JSON formatting is semantic (0.0 equals 0); booleans remain distinct.
`--reuse-ranked-result` verifies the old bundle, exact inputs/settings/runtime,
unchanged ranking/economic source prefix and dependencies, and the runner's
historical-scope AST before reusing its retained candidates. It recomputes only
held paths, publishes a new process version with `ranking_reuse_entry` lineage,
and records zero newly ranked stocks. The original process version remains
byte-identical. A changed ranking definition or scope cannot use this bridge.

```powershell
uv run python tasks/20261013-annual-winner-rotation/run_study.py run --reuse-ranked-result tasks/20261013-annual-winner-rotation/sweep_results.json --output .tmp/annual-winner-replay.json
```

Initial authorized preparation (already completed in this study) is explicit,
not a reader side effect: `prepare --output NEW_INPUT_PIN` checks the checkout
hook receipt and its consumed file digests, then publishes a new input bundle.
`measure --output NEW_MEASUREMENT` compares identical fixed representative stocks
under serial and two-worker execution. These commands do not download data.

## Process artifacts

| Artifact in the process bundle       | Content                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `candidates.json.gz`                 | Every stock/year observed in that year's official quote history; initial/final raw closes, required/observed quote counts, economic rank or null, quality reasons, reference-factor diagnostic. Later listings do not enter earlier-year denominators. Reasons retain the first ten dates plus full count; original inputs reproduce every omitted date. |
| `holding-paths.json.gz`              | Every arm/year's fixed leaders, raw entry/exit dates and prices, gross/net multipliers or null, applied cash/split events and daily wealth marks, alongside 0050. An unresolved holding is retained and never replaced by a runner-up.                                                                                                                   |
| `results.json`                       | Aggregate yearly selections, candidate denominators, complete/unknown holding periods, YTD and fixed window diagnostics. Public summary omits raw quote vectors.                                                                                                                                                                                         |
| `measurement.json`, `execution.json` | Representative serial/two-worker comparison and full phase/worker receipts: wall/CPU, native memory and transfer counters; startup/serialization isolation explicitly unavailable where not measured.                                                                                                                                                    |
| `study.json`, `implementation/*`     | Exact fixed settings and raw-byte executed sources/dependencies, with runtime/input pins.                                                                                                                                                                                                                                                                |

All JSON wealth/return quantities are fractions or unit multipliers, never
percent-valued legacy engine metrics. `gross_multiplier=1.1` means +10%.
New listings without the initial anchor are retained with `ranking_status=ineligible`,
excluded from the candidate denominator and separately counted in the audit.
Unknown is null plus reasons. Wealth starts at 1; NT$2,000,000 equivalents multiply
by 2,000,000 and do not certify lot-size feasibility.

## API and economic boundaries

- `annual_candidates`: supplied-calendar historical prefix, previous year-end
  close to ranking year-end; first 2010 close is the earliest anchor. Calls
  `price-basis.v2` for quality/factor diagnostics; future quotes/actions cannot
  change the returned previous-year rank.
- `select_leaders`: highest calculable economic estimate, stable code tie order.
  Unknown candidates remain in the audited universe. This selects a known-return
  leader and cannot certify that an unknown candidate was not the true champion.
- `economic_path`: raw-price unit accounting with supplied cash estimates and
  exact split ratios only. Ex-date immediate fractional reinvestment is an
  idealized model. Rights/reductions, unavailable cash or unsupported events are
  unknown; adjusted prices never become transaction prices or inferred shares.
- `first_observed_trade`: next positive-volume valid raw open; optional one-price
  avoidance. Daily OHLC is not order-book, odd-lot or statutory-limit evidence.
- `annual_holding`: preserve the fixed issuer and unresolved position when a
  YTD terminal quote is absent or a full-year suspension produces unordered
  endpoints. `paired_benchmark_path` rejects those endpoints before evaluation.
- `rank_panel`: one stock per task, <=2 admitted workers/in-flight jobs, deterministic
  parent barrier, integer candidate counts before any rates. Synthetic Windows
  serial/two-worker equality is tested; resource receipts are observations, not
  OS memory limits or physical disk counters.
- `summarize_annual_excess`: paired annual log differences, exact one-sided sign
  enumeration (<=20 years), seeded iid annual bootstrap and paired best-year
  removal. Small samples, serial dependence and source/universe bias remain.
  No significance metric is emitted for a cherry-picked subset of unknown years.

The calendar is observed official quote dates, not a certified historical
exchange eligibility census. 0050's verified 2025 1:4 split and five closed
sessions are explicit exceptions: stale marks on those closed dates do not
invent trades. Rounded reference price factors are retained only as diagnostics.
0050 dividends use the same estimate/reinvestment convention as stock holdings;
the old `market-context` adjusted-close series is deliberately not a total-return
benchmark. Continuous benchmark costs are charged once at its first/last trade.
