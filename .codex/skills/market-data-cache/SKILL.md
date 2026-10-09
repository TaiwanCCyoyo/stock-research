---
name: market-data-cache
description: Read this repository's Taiwan market cache, universes, liquidity data, and backtest summary metrics with the correct schemas, units, coverage depth, vintages, and survivorship assumptions. Use before querying prices, deciding how far back a study can run, or interpreting study numbers; do not use it as authority to mutate cache data.
---

# Market Data Cache

Use the repository's measured data contract instead of inferring column names, units,
coverage, or metric semantics.

1. Read [references/cache-contract.md](references/cache-contract.md) completely before
   querying cache artifacts, building a universe, calculating liquidity, or interpreting
   a backtest summary.
2. Treat `shioaji_stock_prices/data/` as read-only unless the user has explicitly placed a
   data-shape change in scope. Source acquisition/normalization belong in the
   `shioaji_stock_prices` submodule; research price policies, indicators, patterns and
   immutable derived caches belong in Stock under `docs/en/research-derived-data.md`.
3. Before any authorized data-shape change, follow `AGENTS.md`'s data-safety
   boundary and read `docs/en/price-cache-backup.md`. Prefer additive artifacts; never
   overwrite or delete the existing cache without separate explicit authorization.
4. Preserve exact numeric values and separate measured facts from interpretation when
   reporting results.
