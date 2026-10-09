# Retrospective sector-wave catalog

The catalog connects a business cohort to a historical wave, qualifying stock
ascents and all available peers over a common comparison window. It supports the
market timeline and later K-line studies without inventing selection decisions.
The first definition is in `tasks/20261002-sector-wave-catalog/mission.md`.
Producer market artifacts remain read-only in `shioaji_stock_prices`.

## Bundle: sector-wave-catalog.v1

`manifest.json` records run, definition, window, units, limitations, input/code/
mission/grouping hashes and each chunk's relative path, table, count and SHA-256.
Consumers verify hashes and references. The manifest is reproducibility evidence,
not approval of a stock-selection strategy.

Chunks are UTF-8 JSON arrays compressed with gzip. Their gzip timestamps are fixed
for deterministic bytes. Consumers can stream them from an API with gzip content
encoding or decode with the standard Python `gzip` module. The readable manifest
and completion receipt remain JSON. Table chunks, unlike disposable backtest runs,
are retained in Git as the portable historical catalog.

| Table            | Identity                      | Principal relationships and facts                                                                                 |
| ---------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| securities       | security_id (`TW:code`)       | Name, market, industry, official memberships, group IDs and coverage                                              |
| groups           | group_id                      | Kind, qualified source nodes, version, snapshot, member IDs                                                       |
| episodes         | episode_id                    | Security, definition, trough/qualification/peak/confirmation, price multiple, appreciation, censoring and quality |
| waves            | wave_id                       | Group, comparison window, qualifying episodes, winner, earliest qualifying 25% milestone and peer IDs             |
| peers            | peer_id                       | Wave, security, aligned dates, endpoint/peak appreciation, liquidity, quality and null reasons                    |
| taxonomy_nodes   | chain_code + node_code        | Original hierarchy, direct source codes and expanded ordinary-stock membership                                    |
| quality_findings | code + optional date + reason | Exclusions, unresolved identities and affected price/action observations                                          |

Appreciation is a fraction: `1.0` means +100%, while `price_multiple=2.0` means
twice the starting price. Dates are ISO; timestamps UTC. Prices are TWD; liquidity
is thousands of TWD. Official chain/node labels remain separate from research
cohorts. Keep multiple memberships and unknown labels visible. Membership uses
the identified current snapshot for hindsight labeling, not historical availability.

Web consumers can index episode/wave intervals for date-range queries. ETF and
strategy participation attach by security/episode IDs in separate evidence tables.
Future predictive research may use this bundle as a known historical label set
and derive daily features under a separate preregistered evaluation design.

`winner_security_id` means the greatest observed peak appreciation over the
wave's common window. `earliest_qualifying_25pct` identifies a different timing
descriptor: the first qualifying member to reach 25% above its own trough. A
consumer should label both meanings explicitly rather than collapse them into
one leader. Single-member waves and dependent family/subgroup views remain
visible. The catalog does not certify pure business exposure.
New builds carry dated adapter findings into the requested peer interval, even
when a removed invalid endpoint would otherwise fall outside the sliced bars.
Unusable action factors are excluded from the adjustment adapter while their
original rows remain available as quality/evidence records.

## Reproduction and validation

Run from a physical task worktree with the manifest's producer snapshot and
recorded code/config identities. A new output directory is required; the builder
refuses to overwrite an existing run.

```powershell
uv run --no-sync python -m scripts.build_sector_wave_catalog --output-dir tasks/20261002-sector-wave-catalog/runs/reproduction-01 --run-id reproduction-01
uv run --no-sync python -c "from pathlib import Path; from scripts.build_sector_wave_catalog import validate_bundle; validate_bundle(Path('tasks/20261002-sector-wave-catalog/catalog-v1')); print('bundle validation: PASS')"
```

The validator checks chunk hashes, counts, identities, foreign references,
complete peer membership, dated quality-finding propagation and winner selection.
Quality flags are required even when a peer has no comparable return. The completion receipt hashes
canonical manifest JSON, so whitespace formatting does not invalidate evidence.
Source data is not embedded in Git; the committed bundle remains readable
without the producer databases, while reproduction requires the identified
inputs. Dates and return definitions must be preserved when adapting this bundle
to the presentation site's contract.

New builds declare `input_identity_policy`: tracked source text is hashed after
normalizing CRLF/CR to LF (`sha256-universal-newlines.v1`); price Parquet, SQLite
databases, producer taxonomy JSON and compressed output chunks retain byte hashes.
The original published catalog preserves its physical `input_identities_sha256`
as `raw-bytes.legacy`. Its additive `canonical_text_identities_sha256` identifies
the original preregistered Git source at `c98fa50`, after verifying each recorded
raw identity against LF or CRLF content. `identity_amendments` records the prior
manifest and commit. These metadata additions do not recalculate outcomes or
replace the source code that originally produced them.

An audited display-label correction may be recorded under `metadata_amendments`.
It preserves original calculation input identities and the prior artifact commit
and hashes. The current group chunk already contains the corrected label; no
consumer overlay is needed. The v1 memory correction changes one label and its
chunk hash, leaving membership, all 279 other chunks and calculated outcomes
unchanged. Rebuilding with the corrected config naturally emits the new label.

`quality_amendments` records an additional correction of 17 unavailable peer
records from four securities. Their requested intervals contain already-recorded
extreme-jump findings, so the published records now expose those flags even though
they lack comparable returns. All measurements, statuses and winners are unchanged.
The amendment preserves prior peer/chunk identities and manifest hash; 12 peer
chunks changed and 268 other chunks remained byte-identical. The original catalog
at `76f1b22` remains available in Git. No source prices were read or recalculated.

`.secrets.baseline` contains exact audited checksum false positives for these
two catalog JSON files. New suspect values remain blocked, as exercised by the
functional secret-hook regression; neither file is excluded from scanning.
The scanner runs with Python UTF-8 mode so Windows locale decoding cannot
silently skip a UTF-8 file containing Chinese labels.
