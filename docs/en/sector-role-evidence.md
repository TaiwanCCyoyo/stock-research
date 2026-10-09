# Sector role evidence supplement

The immutable `sector-wave-catalog.v1` describes price episodes and source-snapshot groups. `sector-classification-evidence.v1` adds reviewed issuer business roles and products without changing that catalog. A security can have several roles. An IC substrate manufacturer, PCB manufacturer, and PCB material supplier are distinct roles; a company's products must not automatically spread to every role.

The first packet is `tasks/20261002-sector-role-evidence/evidence-v1.json`, accompanied by `completion-receipt.json`. `build_packet.py` contains the reviewed short source excerpts and reproduces the packet offline. It reads committed catalog metadata/episodes, performs no acquisition, and never reads raw price caches. Keep source inspection and semantic judgment with the annotation owner; hashes verify retained text and identity, not the truth of a company claim.

`scope_profile_id` selects a preregistered rule set in `research_core/sector_role_review_scopes.v1.json`. Each profile binds its original catalog through `base_manifest_canonical_sha256`; replacing the catalog and packet together cannot change that registered base. Every included group and seed security must exist in that catalog; unknown references fail instead of silently disappearing from the queue. The required nonblank `included_group_reason` registers the reason for that profile's group selection; it is not inferred from another batch's group names and cannot reuse the reserved `source_missing_with_episode` or `registered_issuer_seed` reasons. Validation independently reconstructs the complete queue and each inclusion reason from the fixed catalog's groups, source coverage, derived episode identities, and registered seeds. Omitting a pending security must fail validation before a receipt can be generated. Add a new profile for a changed selection or catalog; keep earlier profiles unchanged.

## Identity and consumption

The builder exclusively creates `.sector-role-publication.lock` in the resolved task directory before staging, validation, backups, replacement, or rollback. A competing publisher fails without modifying the artifacts; retry after the first publisher finishes. Handled exits remove the lock. A process crash leaves it in place: check that no publisher is active and inspect retained recovery files before manually clearing it; never automatically delete an existing lock. The builder stages candidates under `.tmp/`, validates the complete catalog and matching candidate receipt, then uses atomic replacement for each destination file. Python exceptions during replacement trigger rollback; failed rollback retains recovery backups and reports their location. Replacing two files is not a single filesystem transaction: readers must verify the matching receipt, including after a process crash, and recovery backups must be preserved until restored.

Join `security_id` to the original catalog, bound by `base_catalog.schema_version` and `base_catalog.manifest_canonical_sha256`. Keep the original group memberships alongside supplemental roles; do not silently replace membership or recompute wave winners. Deep links to an assertion need the packet's schema version, published canonical hash, and assertion ID. IDs are local to a packet and may recur in another version.

| Collection           | Meaning                                                                                                                                                          |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `role_taxonomy`      | Embedded versioned role and product definitions; canonical authoring copy is `research_core/sector_roles.v1.json`.                                               |
| `scope`              | Full review queue, preserving exact original industry/group metadata. `source_verified` means at least one reviewed role; `pending` requires an unknown reason.  |
| `sources`            | Issuer URL/title/locator, short retained excerpt and its hash, inspection method, time/coverage fields, manually reviewed role/product support.                  |
| `assertions`         | One security/role assertion, role-specific products, evidence references, unknown effective dates and optional separate economic relevance/exposure assessments. |
| `membership_reviews` | A concern about an existing security/group pair with evidence; no automatic addition, deletion, or historical exclusion.                                         |
| `limitations`        | Packet-wide boundaries which belong beside the data in a consumer.                                                                                               |

For the full-market timeline, left-join these annotations onto all catalog securities. A security outside `scope` is `not_in_review_scope`, not a negative role result. A queued security with no assertion is `pending`, not zero exposure. Preserve industry-known/role-unknown securities and deduplicate security identity when summarizing overlapping groups. The web implementation owns its display projection; this packet provides reviewed role evidence, with daily price measures maintained by the consumer's separate data contract.

## Time and evidence semantics

`assertion_status=source_verified` means the retained issuer text supports a role or product. It does not verify exhaustive business coverage, current freshness of an undated page, purity/revenue proportion, a price catalyst, or an effective interval. Every v1 assertion requires `effective_from=null` and `effective_to=null` with reasons. It can be used for retrospective exploration; it cannot be used as historical information available to a trading rule.

Each source's `supported_products_by_role` maps role IDs to the products supported for that role; its union equals `supported_tag_ids`. Every `supported_role_ids` entry needs an explicit mapping key, with an empty list when no product subtype is established. An assertion must have a unique `(security_id, role_id)` and prove its products through the requested role's mapping in its cited sources. A product-only brochure can map products to a role context while leaving `supported_role_ids` empty: it supplements product evidence but cannot establish the business role itself. A flat source-wide product list cannot justify crossing products between diversified roles.

The offline builder requires an explicit reviewed issuer/role product association for every role, including an empty list when no product subtype is established. There is no fallback that assigns all observed products to an unreviewed role. It retains only products both observed in the cited source and allowed by that reviewed association; new issuers or roles require deliberate annotation before assembly.

`retrieved_at` records the batch's source inspection timestamp, using either browser-extracted text (which may have a cached crawl) or direct HTTPS inspection identified in `inspection_method`. It is not first public availability. `published_on` may retain a printed/provided day; do not invent a timestamp/timezone. Reject a day only when even its earliest possible civil-time instant (midnight at UTC+14) follows inspection; an unknown local timezone can legitimately have the next calendar day while UTC inspection is still on the previous day. This bound does not assign a publication timestamp or establish availability. Unknown `published_at`, `available_at`, and `covered_period` need reasons. Annual reports/product brochures may specify a document-year coverage range; that range does not establish a role throughout that year. Full copyrighted reports stay out of tracked deliverables; `retained_excerpt_sha256` hashes the exact saved excerpt, including ellipses between non-contiguous fragments, not an archived full response/PDF.

Validation captures the current UTC time once. `created_at` and every `retrieved_at` may be at most five minutes ahead of that clock, allowing small clock skew while refusing inspections that have not occurred. Source retrieval must also be no later than packet creation. Historical receipts retain their original recorded timestamps.

`business_relevance` is null/core/secondary; `exposure_path` is independently null/direct/indirect. Every assessment evidence reference must belong to its assertion's `evidence_refs`. Populated values require a written basis and nonempty evidence references; unknown values require a null basis and an empty assessment reference list, alongside the unknown reason. The first batch leaves both unknown. Do not turn their absence into zero, infer a revenue allocation, or use a role label as a stock score.

## Reproduction and validation

JSON inputs must use standard finite JSON numbers, including in optional or unknown
metadata. The validator rejects the Python-only `NaN`, `Infinity`, and `-Infinity`
constants; canonical serialization cannot emit non-finite numbers. These names
remain valid inside ordinary strings. This preserves compatibility with strict
JSON readers without changing existing finite-valued packet bytes or identities.

The complete embedded taxonomy must equal the canonical `research_core/sector_roles.v1.json`; matching the schema name alone is insufficient. A changed role meaning requires a new taxonomy version rather than relabeling an existing ID.

Every source URL must use HTTPS with a syntactically valid DNS hostname (including IDNA names) or IP address, a valid optional port, and no control characters. Host percent escapes require valid hex bytes and strict UTF-8 decoding before hostname validation; IPv6 literals require brackets. This follows the host forms described in [RFC 3986 section 3.2.2](https://www.rfc-editor.org/rfc/rfc3986.html#section-3.2.2); [Python's URL parser does not itself validate every component](https://docs.python.org/3/library/urllib.parse.html#url-parsing-security). Validation preserves the stored URL and performs no DNS lookup; live source inspection remains a separate annotation step. Every source needs a nonblank `inspection_method`, and the root `limitations` must be a nonempty list of nonblank strings. A populated `covered_period` needs a nonblank `basis` explaining what the document's dates cover. These are required evidence semantics, not optional presentation notes; a consumer must preserve them alongside the annotations.

Run from the repository root with the repository environment:

```powershell
uv run --no-sync python -X utf8 -m tasks.20261002-sector-role-evidence.build_packet
uv run --no-sync python -X utf8 -m scripts.validate_sector_role_evidence tasks/20261002-sector-role-evidence/evidence-v1.json --catalog tasks/20261002-sector-wave-catalog/catalog-v1 --receipt tasks/20261002-sector-role-evidence/completion-receipt.json
```

`validate_packet(packet_path, catalog_dir, receipt_path)` verifies all original chunk hashes and the original receipt, decompresses securities/groups and derived episodes to reconstruct scope, checks cross references/time/null reasons/role-specific support, and compares the published receipt's complete summary and canonical packet hash. Passing source-hash checks alone does not verify published identity. `--write-receipt` is an explicit authoring operation, mutually exclusive with `--receipt`; it requires a new path outside the catalog and refuses to overwrite the packet or any existing file, using exclusive creation to prevent a concurrent overwrite. Consumers use the existing published receipt.

Review fixes may revise the initial draft before its first release/merge; the final receipt must identify the reviewed content. After release, do not overwrite a published packet to extend coverage or correct it. Create another version/batch bound to its exact catalog and explicit source observations; preserve earlier receipts and historical missions. A later historical-role contract must separately register how dated evidence establishes effective intervals.
