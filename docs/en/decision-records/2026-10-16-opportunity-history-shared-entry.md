# Decision record: opportunity-history web bundle in the shared research_data entry

Date: 2026-10-16. Owner request: rescue the one surviving copy of the frozen
opportunity-history web bundle and make the dashboard read it from the shared
`research_data` entry. Decisions below were made by the implementing session from
measurements, per the owner's preference for technical defaults.

## Situation

- The bootstrap (2026-10-09) migrated code, tracked evidence and pins but not the
  ignored 1 GB bundle that used to sit under
  `tasks/20261005-market-full-history-web/inputs/producer-preview/`. The dashboard's
  default path therefore did not exist in this repository.
- The only surviving copy was the predecessor's worktree
  `<legacy-checkout>/.worktrees/strategy-presentation/tasks/20261005-market-full-history-web/inputs/producer-preview`:
  `catalog-v2` and `runs/native`, 10,330 files, 987,601,358 bytes, no symlinks,
  junctions or hardlinks (checked before copying).

## Measured: which manifest pin the bytes satisfy

| Check on the surviving bytes                       | Result                                                              |
| -------------------------------------------------- | ------------------------------------------------------------------- |
| SHA-256 of `catalog-v2/manifest.json`              | `c7848ae7…0dfe140` (the predecessor's original bytes)               |
| `HistoryStore(source, "238e7e4a…")` (old code pin) | rejected, `Configured catalog manifest hash mismatch`               |
| `HistoryStore(source, "c7848ae7…")` (full reader)  | accepted: 1,970 stocks, 105 excluded, 2010-01-04..2026-10-02, 612 s |

The tracked `238e7e4a…` manifest (rebuilt from
`tasks/20261004-sector-wave-full-history-preview/catalog-v2/manifest.part-*.json.gz`)
differs from the surviving manifest in provenance fields only: `source_manifest`,
`series_manifest`, `extras.sources`, `input_receipt` and the matching
`producer_identity` / `compact_export_identity` digests plus path text. Every
`calendar`, `series`, `native` and `tables` reference is identical.

## Decision: keep the original bytes and pin `c7848ae7…` (option 1)

Option 2 (rewrite the files so they hash to `238e7e4a…`) was rejected. Each native
receipt stores `context.producer_identity`, which still carries the original
`input_receipt_sha256` (`584add41…`); the `238e7e4a…` manifest carries the rewritten
`ddef1c66…`. `HistoryStore.detail()` requires the two to be equal, so a
`238e7e4a…` manifest over these bytes would load at startup and fail on every stock
detail page (all 1,970 receipts carry `584add41…`, checked). Making them consistent would mean rewriting 1,970 receipts and
re-deriving digests with no original left to compare against. The bytes are kept
verbatim, registered as status `legacy`.

Unchanged on purpose: `REGISTERED_MANIFEST_SHA256` in
`scripts/query_opportunity_history.py`, every receipt and report citing `238e7e4a…`,
and all SHA-pinned evidence code. The dashboard's pin moves to
`ORIGINAL_MANIFEST_SHA256` (`research_core/opportunity_history_bundle.py`), also
exported as `opportunity_history_store.DEFAULT_SHA`. The studio re-export command in
`tasks/20261008-strategy-studio/data-contract.md` now names the original pin; a
re-export names its benchmark source `benchmark-catalog:c7848ae7…` instead of
`238e7e4a…` while reading identical series.

## Placement and registration

- Location: `research_data/patterns/opportunity-history-web/<c7848ae7…>/` with
  `catalog-v2/`, `runs/native/` as siblings (the manifest addresses
  `../runs/native/...`) and `copy-receipt.json` (inventory of all 10,330 paths with
  SHA-256, source, timings).
- Catalog reader `metadata_only`, status `legacy`, manifest pin `c7848ae7…` (also the
  version id). `HistoryStore` stays the content authority and hashes every member at
  each startup, so a `bundle` wrapper listing 10,330 files would only add a second
  ~1 GB hash pass to every `DataCatalog.get`.
- Coverage declared honestly: prices and saved stocks 2010-01-04..2026-10-02, 1,970
  eligible saved stocks of 2,075 catalogued; not every issuer ever listed; the label
  period is not certified complete. Limitations are listed in the entry.

## Copy method and verification

`scripts/restore_opportunity_history.py` (thin over
`research_core/opportunity_history_bundle.restore_bundle`):

1. Reject links, reparse points and hardlinks, then hash every source file before any write.
2. Refuse unless the source manifest equals the pin and the destination is absent.
3. Copy to a sibling `.staging-*` directory with exclusive create, hashing while
   writing; any difference from the pre-copy hash fails (a test changes a source
   file mid-run).
4. Re-read the whole copy and compare the file set and every SHA-256.
5. Run the full `HistoryStore` gate on the staged copy, publish with no-replace rename,
   register in the catalog. A failure leaves the staging directory in place.

Measured on this machine: hash 3.5 s (warm), copy 46 s, verify copy 87 s, reader gate
486 s. An independent comparison afterwards found 0 mismatching files among 10,330 and
only `copy-receipt.json` extra; no destination file has a link count above one.

## Dashboard resolution

`LazyHistoryStore()` resolves the bundle inside its first `get()`, not at import time:
a missing environment value or catalog entry becomes the existing failed state
(`/status` failed, data routes 503, other pages keep working). The root comes from
`STOCK_RESEARCH_DATA_ROOT` in the process environment, else the same key in the primary
checkout's ignored `.env.local` (the producer-root pattern); there is no guess and no
fallback. `DataCatalog.get` pins `data_id`, `version_id` and manifest SHA-256 together.
Resolution costs about 9 s (catalog read plus path checks over 10,330 members) on top
of the reader gate.

## Follow-ups not done here

- The old `tasks/20261005-market-full-history-web/report.md` and
  `presentation-manifest.json` still describe `inputs/producer-preview/`; they are stored
  results and are left as written. This record and `opportunity-presentation.md`
  carry the current location.
- The source copy in the predecessor worktree remains; deleting it is the owner's call.
  The shared `research_data` is covered by the existing backup sources, but no backup
  run was made for this entry.
