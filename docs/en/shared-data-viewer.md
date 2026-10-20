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
  unavailable/busy metadata falls back to codes. Cached names describe startup,
  while generation identity is resolved on every request.
- `adjusted-daily-v1/series/{code}?basis=&from=&to=`: aligned date and OHLCV
  column arrays, quality flags/reasons, daily technical columns and pivots.
  Null values stay null; invalid bars and indicators render whitespace.
  Date filters select a current-generation display window, **not** an as-of
  reconstruction or point-in-time strategy evaluation.

Responses carry generation and status SHA. All prices/technicals use the existing
`read_adjusted_daily`/`read_technical` readers with the same explicit generation.
A single background worker warms their per-process hash checks; warming returns
503 with Retry-After. Missing/pruned/invalid evidence returns explicit 503,
unknown symbols 404 and invalid basis/date ranges 422. No writer or maintenance
command is invoked. A new generation triggers a new warmup, with no unbounded
queue or retained whole-market price tables.

Only reference-factor-adjusted prices have attached technical values. Other
bases hide those layers; no browser indicator calculations are used. Volume is
in lots, including fractions; `atr14_pct` is a ratio. Pivots draw on their extreme
date and display `confirmed_at` separately.

## Catalog and scope

The existing `DataCatalog.read()` owns catalog verification and metadata.
No current-version preference is inferred from a version name or date.
Entries without an explicit recommendation say 未標示現行版. Existing immutable
manifests and catalog entries are unchanged. Coverage is the catalog's declared
scope; presence does not certify research validity. Contract and asset-index
links explain column definitions and access locations.

The legacy `?legacy=1` workbench remains a separate archived-task viewer.
Use the new shared-data page for maintained indicators. The strategy detail
deep link is deferred while PR #39 owns that file; the market detail link is
included. This change does not claim a saved trade's execution price equals a
current restated chart price.
