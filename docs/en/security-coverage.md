# Security coverage and stock discovery

The data overview has dataset and security views. Source-observed securities are
the union of market/code observations in the official-price, institutional,
revenue, action and metadata artifacts, with code-only price observations assigned
a market only when all available cross-source evidence agrees.

This is not a complete historical listing universe, investable universe or
point-in-time instrument master. An observation's first/last date never becomes a
listing/delisting date.

## Maintained artifact

Family: `security-coverage-v1`; schema: `security-coverage.v1`.

The single maintained home is
`<STOCK_RESEARCH_SHARED_ROOT>/derived/security-coverage-v1/`.

- `current.json` selects an immutable generation and pins its coverage and status.
- `generations/<id>/coverage.json` contains bounded source and build metadata.
- `generations/<id>/coverage.sqlite` contains the full observed security index
  and compressed per-security cells. SQL applies filters and counts before
  pagination; only the requested row payloads are decompressed. This is derived
  coverage metadata, not a second copy of source observations.
- `generations/<id>/status.json` describes the summary's observation date, security
  count and number of coverage cells. These are summary counts, not market rows.
- Maintenance serializes scans with an OS lock; publication uses the existing
  artifact-store primitives and an atomic pointer switch. Prior generations are
  retained; no automatic pruning or additional schedule is introduced. Both the
  metadata and indexed payload file are digest-pinned by the current pointer.

Run `uv run python -m scripts.maintain_security_coverage status` to inspect the
saved summary, or `... update --seconds-per-source 180` to maintain it explicitly.
Before a full build, `... measure --codes 2330 2645 --seconds-per-source 60`
profiles selected observations without publishing. Choose representative codes
from current metadata; the command does not assert their listing status. Parquet
filtering can still read whole row groups. Every scan stays single threaded;
Windows process resource counters include cached I/O and a lifetime memory peak,
not physical disk throughput or an isolated phase peak.
The command acquires no source data and changes no producer artifact. Readers and
HTTP requests never invoke it.

The builder reads only canonical producer filenames, never its `staging/` tree.
Institutional backfill being downloaded to staging therefore does not change the
published coverage until it has been validated, imported and this family updated.

## Maintenance bounds and provenance

The producer resolver, writer-window guard, read-only SQLite and existing
artifact primitives are reused. SQL scans have deadlines; price Parquet is
reduced in bounded Code/Date batches. Sources are processed serially with one
in-flight scan. Source and WAL identities are compared before/after each read and
again across the complete producer scan. A changed producer input aborts the
publication rather than mixing old and new counts.

Adjusted prices are read from one verified existing maintained generation, held
against pruning during the scan. They are not recalculated or privately copied.
A missing source records unknown status, not a measured zero. A failed publication
retains the previous pointer.

Per-source wall/CPU measurements and source fingerprints are saved. Memory/I/O
observations use the shared measurement helper and remain null where unavailable. Production
capacity and API latency must be measured before declaring operational readiness;
synthetic tests alone do not establish them. No numerical feature, label or strategy
result is created by coverage maintenance.

## Identity v1 and conservative differences from the initial handoff

The opaque key hashes market, observed code and a segment boundary. It is a source
observation key, not a guaranteed permanent issuer identifier. Source names and
market codes are retained without inferring identity from name similarity.

Metadata listing dates later than observed daily history, and official-price gaps
longer than 366 calendar days, flag possible reuse. This threshold is a screening
rule, not proof of a new issuer. The reader exposes separate bounded segments,
suppresses aggregate counts whose attribution to the segments is unresolved, and
does not join their charts. A historical segment does not inherit the newest
company name or class.

The current producer metadata has no authoritative delisting/effective-to field.
Consequently missing recent prices are not classified as delisting. The default
filter is **recent observations among ordinary shares**, explicitly labelled
`近期有資料`, with historical and identity-unknown filters. Confirmed listed or
delisted states require separate explicit evidence. This replaces the initial
handoff's unsupported default claim that current metadata proves listed status.

The v1 parent/candidate key may change when new identity evidence creates segments.
Unknown old keys return not found; legacy code links resolve 0/1/many candidates.
No key redirects silently to an unrelated latest issuer. Full historical
crosswalks and permanent alias migration remain a later version.

## Cell meanings

Each cell records dataset, rows, period, checked time, mark and separate
applicability, existence, completeness, freshness and readability.
`period` contains actual first/last observations, while `assessment_period`
identifies the inspected identity/listing interval through the summary date.
Its unknown start remains null. `assessment_scope=presence_and_known_gaps`
explicitly excludes an exact missing-session audit; the interval is not a promise
that data was required on every day. `input_identity` identifies the source
file/WAL observation or adjusted generation. Unresolved segments suppress the
security-level aggregate period as well as their cell counts.

| Mark           | Meaning                                                                                                    |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| present        | There are observations; full historical completeness remains unverified.                                   |
| partial        | A supported known coverage limitation applies.                                                             |
| missing        | Successful inspection establishes applicable, required data is absent. Reserved for supported obligations. |
| not_applicable | A reliable dataset applicability rule excludes the security.                                               |
| unknown        | Inspection, identity or required coverage cannot be established.                                           |

A successful scan finding zero rows does not alone establish that data was owed.
In particular, no corporate-action rows may mean no event. V1 conservatively uses
unknown where there is no supported absence/applicability rule; it never turns
read failures into red missing cells.

Institutional stored history beginning in 2019 or later is a known limitation for
a security known to have listed before 2019. A 2023 listing does not owe prelisting
history. Floors are tracked per market, so extending TWSE alone does not conceal
a remaining TPEx limitation. An earlier floor removes that specific 2019 boundary
notice but does not certify all intervening history as complete.

Metadata dates are observation times; latest name/industry is not effective history.
Revenue remains current-revision and is not a PIT guarantee. Indicator warmup and
price-basis restrictions continue to apply. Frozen study versions do not become
stale because they are old.

## HTTP and library interface

`CoverageStore` is the common metadata-only reader in
`research_core.security_coverage_store`. Routes also exist under `/api`:

- `GET /data-coverage/securities`: market, kind, status, q, dataset, mark, page,
  size; filter before pagination; maximum 200 rows per page. Return total,
  confirmed-missing and unknown counts for the complete filtered set.
- `GET /data-coverage/securities/<key>`: identity, cells and generation context.
- `GET /data-coverage/resolve?code=`: zero, one or several identity candidates.

No summary returns `unavailable`, never an on-demand scan. The reader verifies
bounded immutable content and caches one generation. Unknown modes fail closed;
public-synthetic mode returns fictional DEMO data without resolving private roots.
API payloads never contain absolute producer paths.

The initial whole-document candidate exceeded its 128 MB JSON bound on the real
source-observed universe, so it was never published. The indexed representation
preserves that universe rather than dropping unknown historical securities.
The SQLite image is constructed in memory and published with the existing
no-replace directory primitive; no worktree or producer intermediate is created.
The metadata bound is 1 MB and the database bound is 512 MB. An oversized or
failed build retains the preceding pointer. Readers open the published database
with `mode=ro&immutable=1`; a process verifies digests when selecting a generation
and rechecks file identity before reusing its verified cache.

## Frontend and compatibility

`#overview` is dataset discovery; `#overview/stocks` is the stock matrix.
`#stock/<opaque-key>` opens stock content. Filters/search/page are in the query,
and the return link preserves them. The matrix has text-equivalent marks, keyboard
links, desktop headers and a compact phone layout.

Legacy `#data` opens the stock list. Legacy `#data/<code>` resolves identity before
navigation; multiple candidates require selection. Existing history/map links
therefore remain supported without editing those concurrently maintained pages.

Price-independent revenue/institutional tables can open even when adjusted prices
are unavailable. Unresolved segments do not load unbounded code-only series.
Existing adjusted-price components are reused for their own data basis; source
cards without a matching viewer explicitly offer a summary rather than a
mislabelled chart.

## Validation and operational acceptance

Synthetic cases cover old/new listings, partial backfills by market, code reuse,
long gaps, no-price revenue, missing/unreadable summaries, pointer tampering,
publication/cache switches, filters, mode isolation and routes. These do not prove
true-market completeness.

Before rollout, run normal hooks and affected CI, verify saved-artifact readability
before/after reader changes, measure representative real source scans outside the
writer window, publish the real summary and inspect phone/desktop light/dark
views. Apply changes from a refreshed isolated task branch. Production data moves,
producer summary publication and precise missing-day audits are separate work.
