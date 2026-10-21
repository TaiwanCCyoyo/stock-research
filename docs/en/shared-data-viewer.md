# Shared-data viewer v1

The local-private dashboard's `/#data` page reads the maintained
`adjusted-daily-v1` family and the existing research-data catalog in place.
`/#data/<code>` opens a stock. No market values are bundled in Git or synthetic
mode; the latter displays a local-data requirement.

## Read-only API

`/shared-data/v1` and `/api/shared-data/v1` expose the same router:

- `families`: current generation/status summary plus verified catalog discovery
  metadata. A missing catalog is explicit and does not hide the maintained family.
- `adjusted-daily-v1/symbols`: code, optional name/market and first/last stored dates.
  Live producer names use idle-window guards and a stable read-only SQLite read;
  unavailable/busy metadata falls back to codes. Names arrive independently of
  price warmup, while generation identity is resolved on every request.
- `adjusted-daily-v1/series/{code}?basis=&from=&to=`: aligned date and OHLCV
  column arrays, quality flags/reasons, daily technical columns and pivots.
  Null values stay null; invalid bars and indicators render whitespace.
  Date filters select a current-generation display window, **not** an as-of
  reconstruction or point-in-time strategy evaluation.

Responses carry generation and status SHA. All prices/technicals use the existing
`read_adjusted_daily`/`read_technical` readers with the same explicit generation.
One background task warms their per-process hash checks; warming returns
503 with Retry-After. Missing/pruned/invalid evidence returns explicit 503,
unknown symbols 404 and invalid basis/date ranges 422. No writer or maintenance
command is invoked. A new generation triggers a new warmup, with no unbounded
queue or retained whole-market price tables.
After warmup, at most three workers read one symbol's independent price/daily/pivot
files concurrently; other requests wait for that bounded projection. A comparison
on 2330/2603/2882 found identical frames and reduced file reads from 166–188 ms
to 85–87 ms. This excludes JSON transport and chart rendering.

Only reference-factor-adjusted prices have attached technical values. Other
bases hide those layers; no browser indicator calculations are used. Volume is
stored in lots, including fractions (rounded to whole lots for display);
`atr14_pct` is a ratio displayed as a percentage. Prices show at most two decimals.
The legend compares against the previous valid close across missing dates.
Only 4 ATR pivots are enabled initially. All indicator colors use theme CSS tokens.
Pivots draw on their extreme
date and display `confirmed_at` separately.

Verified codes and series become available without waiting for optional stock
names. A separate single-worker executor handles names; even across repeated
generation changes it retains at most one in-flight read, with no replacement
queue. Completed results apply only to the generation/status identity that
requested them; obsolete work drains before a fresh read starts. Current-identity
empty results retry on demand after a 60-second cooldown. Busy producers still
return codes immediately through the guarded metadata reader. One five-second
deadline bounds its scheduler probes, SQLite lock waits and query progress; a
timeout fails closed to codes without disabling producer guards.
The page receives that recovery through a serial symbols-only request loop while
names are unavailable: one initial request, then at most 60 retries spaced 60
seconds apart. Success stops it. Leaving the page, retrying or changing the
observed generation cancels the request and timer; mismatched generations are
never applied. A separate manual name retry restarts that bounded loop without
reloading prices or catalog metadata. Exhaustion and generation changes explain
the next action on screen. Restored names update both suggestions and lookup.

## Catalog and scope

The existing `DataCatalog.read()` owns catalog verification and metadata.
No current-version preference is inferred from a version name or date.
Entries without an explicit recommendation say 未標示現行版. Existing immutable
manifests and catalog entries are unchanged. Coverage is the catalog's declared
scope; presence does not certify research validity. Contract and asset-index
links explain column definitions and access locations.
Chinese names and purposes come from the marked discovery-label table in
`docs/en/research-program.md`, maintained beside the authoritative definitions.
The API reads it without editing catalog snapshots or frozen manifests; missing
labels are explicit. Versions of one data ID share a card with a version selector;
hashes and manifest details are collapsed, and maintained families appear first.
Each catalog card also projects the pinned JSON manifest (bounded to 2 MB),
without opening or verifying payload members. Declared security counts, analyzed
security counts and manifest member counts remain distinct. Missing physical
column schemas and counts are labeled unavailable; feature definitions and event
counts are never substituted for them. A missing or mismatched manifest affects
only its card. These metadata checks do not certify member validity.

The legacy `?legacy=1` workbench remains a separate archived-task viewer.
Use the new shared-data page for maintained indicators. The strategy detail
deep link is deferred while PR #39 owns that file; the market detail link is
included. This change does not claim a saved trade's execution price equals a
current restated chart price.
