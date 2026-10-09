# Public synthetic separation — first local stage

Based on origin/main `7f79585da2730fd01075839fbcc973d0090e1ae2`.
Task-owned checkout: `<primary-checkout>/.worktrees/public-synthetic-separation-20261008`,
branch `codex/public-synthetic-separation-20261008`. Retained for review and local-only delivery.

## Preservation and restore

Nine original files (2,120,774 bytes) copied and individually SHA-256/size verified
against both the isolated source and unchanged primary checkout. Canonical local
backup: `<primary-checkout>/StockProject/data/private-presentation/20261008-first-stage/`.
`restore-manifest.json` records original relative paths, sizes and full hashes.
Restore only to an external private root after checking each file; do not copy
them into served public/dist. Original primary files, source hashes and historical
receipts remain unchanged. Only this task's nine isolated copies were removed.

| Original relative path                                                                  |  Bytes | SHA-256                                                            |
| --------------------------------------------------------------------------------------- | -----: | ------------------------------------------------------------------ |
| `research_web/public/data/opportunity-explorer.json.gz`                                 | 286844 | `ebc309927f59c822368079ac1bae2e325af434dc245627124855929ecccb5178` |
| `research_web/public/data/saved-research-runs.json.gz`                                  |  93110 | `fc9bf2386671c67c31e33557c21e5930e34891a7b274b6ccf78c474e42cf6437` |
| `research_web/public/data/research-evidence-v2-classified/opportunity-explorer.json.gz` | 287392 | `e92c1c24b426caf72643ccd8def19136b4f59cc3aa62016a5924082461c3cc71` |
| `research_web/public/data/research-evidence-v2-classified/saved-research-runs.json.gz`  |  93566 | `db18e509045454bda6b0cd70edfa6f2a85fc15f4a0b7694fea18b4151fd4f68d` |
| `research_web/public/data/saved-research-studio.manifest.json`                          |    660 | `eebf83f29c6533da6af96a50cb536494d4fe73a7af3e2106626f62083dc66541` |
| `research_web/public/data/saved-research-studio.part-00000.bin`                         | 460800 | `42d5001afc7f6065801bd55a630e8654c165e46f0e4949f68bfa4b061e57d4d2` |
| `research_web/public/data/saved-research-studio.part-00001.bin`                         | 235157 | `e6d3a725590519322c8ca4a7d575b399002435fb47eba5000db5e64212fa987f` |
| `research_web/fixtures/opportunity-catalog.preview.v1.json.gz`                          | 391803 | `6ee9ee6f30d14e3dbb27e3b20fb4ded4924d2fe46669659c8d40c740feff67b5` |
| `research_web/fixtures/opportunity-explorer.before-classification.v1.json.gz`           | 271442 | `da904cd67ec43ad38a36abfc8859d18520798540aa46c7c5ffff7fdbe8c94a3d` |

## Behavior and verification

Default public-synthetic explorer/saved accounts are deterministic invented
controls. Studio generates independent fictional schema-valid accounting evidence
in memory, without real history metadata or market capture enrichment.
Local-private mode uses absolute external artifact/package paths, read-only
allowlisted API routes, unchanged split-package SHA validation and explicit
unavailable errors. Frontend and API mode mismatches are rejected before private
studio reads and again before rendering. Vite dev and directly served build paths
both support the private artifact route.

- Frontend: 345 tests passed, preserving peak, classification packet hashes,
  receipt checks, provenance, later-wave identity and gap/cutoff assertions.
- Related Python tests: 216 passed; cover synthetic, external private, missing settings/files,
  relative paths, missing split parts, tampering, traversal and mode mismatches.
  Review follow-up covers corrupt DEFLATE with a valid gzip header: both artifact
  names return 503/unavailable without exposing private paths or payloads.
  Related frontend mode/build-guard tests: 5 passed after this follow-up; the
  frontend source and built assets did not change. README now explicitly limits
  the two original native runs to configured local-private viewing.
- Frontend lint/build pass; existing unrelated hook-dependency warnings and large
  JS chunk warning remain. Python lint passes.
- Final verification checks all nine backup/primary hashes again, removed paths
  absent in task checkout, all seven served candidates absent in dist, and no dist
  file equals any of the nine original SHA-256 values.

## Remaining scope

This does not establish public readiness. Git history still contains originals.
Deferred map: sector-wave catalog chunks/episodes, market-context-v2 benchmark
series, HHHL v1/v4 bundles and audit prices, factor datasets, and historical
archives. No visibility/history rewrite/force push, new repository, OpenSpec
migration or producer/starter gitlink update occurred. No market study, data
download or scheduler change occurred. PR #43 remains a separate task.

PR #40 was read back as open, non-draft at `4f9895d458c2991bf1a836344f8e4e3fceda75e0`.
Its map/camera/packing/full-history UI files do not directly overlap this stage's
changed files. The future integration must verify synthetic mode with that UI;
none of its unmerged code was incorporated here. PR #38/#43 gates remain owned by
their existing runs. New repository naming and formal cutover remain owner decisions.
