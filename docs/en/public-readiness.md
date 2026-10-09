# Public release preparation

This checklist covers **TaiwanCCyoyo/Stock** and **TaiwanCCyoyo/shioaji-stock-prices**.
It does not authorize changing visibility, permissions, credentials, releases,
research evidence or Git history. CI optimization is a separate task.

The repositories are **not cleared for public release**. A scan provides evidence
about its stated scope, not proof that disclosure is safe or data may be
redistributed. Preserve historical missions, source hashes and stored results.

## Current decision record

The initial audit used Stock main `324bbfc9f2ed520dfa6ce97f4298880aa2dd1e50`
and producer main `f8feec7f124a71073cc18409774d821ad99f2102`. Preparation starts
from Stock main `04a93f77d6eb143bf70c252ae3bc3030b54ebf0c`. These are inspection
snapshots; refresh and record refs before a later release decision.

The owner's disclosure principle permits pure research content when it contains
no personal data or secrets and publication does not violate applicable law.
This resolves willingness to disclose research judgments; it does not establish
third-party market-data redistribution rights, credential safety or authorization
to change repository visibility. Inspect source links and free text for personal
data, secrets and third-party restrictions even when the research itself is approved.

| Severity | Status                                  | Evidence and required next step                                                                                                                                                                                                                                                  |
| -------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CRITICAL | Credential revocation unknown           | A PAT was embedded in historical Stock `.gitmodules`. First affected commit: `9ed6e400f8794eda505c040e9997a316cc89419d`; 27 trees on the old branch contained it. The owner must confirm revocation; do not test or recreate the credential merely for publishing.               |
| CRITICAL | Exposure reduced; retention not cleared | Owner-authorized remote `ai-dev-20260202` deletion at `4777f814fee7e363f11edec93cb6782e6a0257e0` was read back as absent. Cached refs, local objects, other clones and possible retained GitHub refs were preserved. Deletion is not history erasure.                            |
| CRITICAL | Local URL repaired                      | The embedded credential was removed from `.git/modules/user_logger/config`, key `remote.origin.url`; destination and other keys were preserved. Local config is separate from tracked Git content.                                                                               |
| HIGH     | Historical release withdrawn            | Former producer release `v1.0/data.zip` was reported as 1,817,789,646 bytes with data through 2024-03-11. The owner reports the asset, release and tag withdrawn; API read-back on 2026-10-09 found no `v1.0` release/tag. Retained copies/history remain separate review scope. |
| MEDIUM   | Pure research disclosure approved       | The owner permits pure research judgments under the no-personal-data/no-secrets/lawful-publication principle. Owner-label wording, timestamps and Claude artifact links still require privacy and third-party restriction checks.                                                |
| MEDIUM   | Data rights mapping pending             | Stock publishes source/derived market fragments inside compressed evidence. Producer's Apache 2.0 code declaration is not evidence of permission for every upstream dataset.                                                                                                     |
| LOW      | Historic personal metadata remains      | Historical source headers/Git author metadata contain personal contact information. Archived missions/provenance include machine paths. Current generic changelog examples use `<user>`; history is unchanged.                                                                   |

No actual token, account number, certificate, private key or verbatim private
document belongs in this checklist or scan reports.

## Data inventory and rights questions

This inventory is not a license grant. Git objects and release assets can become
public; ignored local data does not automatically become public. Submodule code
is published by its own repository.

Assess records by their actual source and applicable license/terms. Official
open data may be retained and published with the required source attribution
when its terms permit the intended use. Unknown provenance or terms mean review
is pending; they do not establish illegality or require deleting research data.
Shioaji CSV redistribution permission has not been established for the inspected
copies. This is not a finding that all Shioaji records, all market data, or all
derived research are unlawful to publish. Keep source identity and attribution
visible, distinguish official open-data inputs from broker/other inputs, and
evaluate mixed datasets and derived outputs against their actual source terms.

The owner's withdrawal report is recorded as history, not a current asset
inventory. On 2026-10-09, authenticated `gh api` repository lookup succeeded and
resolved the former producer name to `TaiwanCCyoyo/shioaji-stock-prices-legacy`
(private). Both `releases/tags/v1.0` and `git/ref/tags/v1.0` returned HTTP 404.
These checks support absence of that release/tag in the accessible repository;
they do not prove erasure from other clones, caches or retained copies. No
asset was downloaded and no remote state was changed by this follow-up.

| Artifact/location                                                                                                                                                                      | Class and known source                                                                                                                                                                                    | Evidence still needed                                                                                                                                                                                                                                                               |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stock source, tests and agent configuration                                                                                                                                            | Program code, synthetic tests and operational documents                                                                                                                                                   | Review repository/third-party code notices independently of data rights. Test placeholders and synthetic Windows paths are not actual credentials/accounts.                                                                                                                         |
| `research_core/patterns/hhhl/v*/sources.zip`, `tasks/20261009-hhhl-pattern-probability/sources/`, `tasks/20261010-hhhl-v4-probability/sources/`                                        | Owner-supplied HHHL rule code and research handoff prose, versions 1–4                                                                                                                                    | Confirm distribution of owner-supplied text/code and copied third-party content. Preserve hashes; sanitization requires an explicitly authorized new publication version, not rewriting frozen evidence.                                                                            |
| `tasks/20261010-owner-hhhl-labels/data/owner_labels.json` on owner-label branch                                                                                                        | 11 Claude artifact references; 323 verbatim documents with stock identifiers/dates, judgments, reasons, points and `saved_at`                                                                             | Pure research disclosure is approved; check wording, timestamps and links for personal data, secrets and third-party restrictions. No confirmed account/identity numbers or full user/assistant conversation export in the inspected snapshot; future additions require inspection. |
| Owner-label `data/history.zip`, `chart_sets.zip`, `rule_sources.zip`, `rule_hits_inputs.zip`, `timeline_receipt.zip`                                                                   | Old annotation dumps, labelling HTML/Python, OHLC fragments, rule source and provenance. `history.zip`: 351 members, 1,049,707 expanded bytes                                                             | Privacy/secret checks under the approved research-disclosure principle and chart-price sources/rights. History versions were introduced at `c04790719ec8c1d623020633ab6232b785a75ba8` and `54b0da26afa0409e3c8dca5e1b23eb0634da6386`.                                               |
| `tasks/20261002-sector-wave-catalog/catalog-v1/chunks/*.json.gz`, `tasks/20261004-sector-wave-full-history-preview/catalog-*/manifest.part-*.json.gz`                                  | Derived episode/catalog metadata and market comparisons                                                                                                                                                   | Input provenance and permission for derived records. Fractions resembling phone numbers need context, not automatic removal.                                                                                                                                                        |
| `tasks/20261004-feature-discrimination-atlas/publication-v2/`, `tasks/20261005-market-context-handoff/market-context-v2/`                                                              | Feature/event evidence and market/benchmark context                                                                                                                                                       | Source inputs, data permission and privacy/secret checks under the approved research-disclosure principle.                                                                                                                                                                          |
| `tasks/20261005-method-environment-interactions/publication-v1/source-inputs.zip`, `tasks/20261005-industry-role-comparison/publication-v2/source-inputs.zip`, `results.json.xz.part*` | Source snapshots and derived comparison results; reconstructed results JSON: 7,219,794 bytes                                                                                                              | Distinguish code from market records in each member; confirm distribution rights and attribution.                                                                                                                                                                                   |
| `tasks/20261008-research-data-architecture/publication-v*/{bundle,review*}.zip`                                                                                                        | Architecture source snapshots and review/evidence documents                                                                                                                                               | Review prose for copied conversation/private operational details; code permission does not cover all document sources.                                                                                                                                                              |
| `tasks/20261009-hhhl-pattern-probability/publication-v1/bundle.zip`, HHHL v4 publication/preparation/diagnostic/correction ZIPs and `.bin` segments                                    | Research summaries, rule code, audit samples and derived Parquet records                                                                                                                                  | Reassemble segments; trace prices/features to sources, confirm rights and privacy/secret checks for the approved disclosure of methods/results. Preserve historical evidence.                                                                                                       |
| `research_web/public/data/saved-research-studio.part-*.bin`                                                                                                                            | Gzip JSON transport: saved runs and research history; reconstructed size 10,237,631 bytes                                                                                                                 | Sources, record redistribution rights and privacy/secret checks under the approved research-disclosure principle. Binary transport is not an audit exclusion.                                                                                                                       |
| Producer `scripts/`, `shp_utils/`, `config/`, `.env.example`, `LICENSE`                                                                                                                | Code/templates; Apache 2.0 declaration. Login reads environment variables; the legacy API_KEY constant names a local key file                                                                             | No confirmed current embedded credential/actual user-profile path in inspected tracked files. Preserve synthetic security fixtures.                                                                                                                                                 |
| Producer tracked `data/stock_category.json5`, `tests/fixtures/value_chain_{memory,pcb}.html`                                                                                           | Classification data/small company-chain HTML fixtures                                                                                                                                                     | Source attribution and permission for these fragments. Public access does not establish unrestricted redistribution.                                                                                                                                                                |
| Producer ignored `data/*_day.csv`, `*_min.csv`, `official_daily.sqlite`, `raw/`, metadata/corporate-actions/institutional/revenue stores                                               | Acquired Shioaji/TWSE/TPEx/MOPS facts/raw responses, currently local. File metadata: 2,080 day CSVs (304,538,015 bytes), 2,074 minute CSVs (18,409,303,576 bytes), official SQLite (16,240,705,536 bytes) | Per-source inventory and applicable redistribution terms before publishing any copy. No data contents were read for these totals.                                                                                                                                                   |
| Producer ignored `price_daily.parquet`, adjusted prices and `technical_features/`                                                                                                      | Normalized/derived data; price parquet: 205,050,515 observed bytes                                                                                                                                        | Transformation does not establish distribution rights. Trace mixed inputs and acquisition-time terms.                                                                                                                                                                               |
| Former producer `v1.0/data.zip` (withdrawn; historical inventory)                                                                                                                      | Historical release metadata only; contents unverified, independent of Git history; not a current published asset                                                                                          | Review retained copies only if proposed for publication: member inventory, sources/acquisition dates/terms and private-record checks. This task performed no asset download or deletion. Historical yfinance dividend data, if included, needs its own source mapping.              |

Source pointers: producer `README.md` and `docs/pipeline.md`; Stock
[pattern definitions](pattern-definitions.md),
[derived-data ownership](research-derived-data.md), and task source/data
contracts. Current local contents do not establish what was packaged in 2024.

## Repeatable evidence

`scripts/audit_public_readiness.py` reads Git objects in explicitly selected
repositories/refs, not ignored credentials or live data. It does not fetch,
traverse submodules, execute archive code or mutate repositories. JSON output
contains locations/rule identifiers, never matched values or snippets. Archive
members, bounds and gaps are reported. Table bytes are not a semantic table review.
Exit 1 means a critical signature candidate needs contextual review; exit 2 means
failure or incomplete coverage; exit 0 applies only to the stated scope. Synthetic
security fixtures and redaction placeholders can intentionally trigger candidates.

Every known path alias is inspected with its own archive/type semantics, including
paths from reachable history. Historical segments that are not fully reconstructed
remain explicit coverage gaps even when deleted from the selected tips. Matching
uses a reusable line index and a global finding limit; hitting that limit records
a gap. XZ decoding has a memory limit as well as output limits. ZIP LZMA members
are reported as unsupported coverage gaps because their decoder memory is not
bounded by the ZIP reader. Corrupt DEFLATE streams produce safe gaps, not raw
decoder errors. These limits do not resolve semantic privacy or data rights.

ZIP central-directory preflight runs before `ZipFile` creates member objects.
It limits metadata to `--max-zip-metadata` (default 1 MiB), checks actual fixed
headers and lengths instead of trusting the declared member count, and reserves
the global `--max-entries` budget for all records, including directories and
nested archives. Oversized metadata/member counts are coverage gaps. ZIP64 and
multi-disk archives are unsupported coverage gaps; malformed metadata is also
a gap. Bounds can be raised explicitly for a trusted named scope, at increased
memory cost. The preflight preserves ordinary ZIP and concatenated-prefix ZIP
scanning within the limits; it does not certify an archive as safe or licensed.

The preparation scan inspected 3,888 Stock main history blobs, 684 producer main
history blobs and 3,895 owner-label branch history blobs. Stock's four historical
credential-URL candidates were exact redaction placeholders, not a newly found
live token. Producer's two candidates were versions of the URL-rejection fixture
in `tests/test_official_api.py:315`. No fixture or historical evidence was removed
to make these reports pass. Coverage gaps remain for Parquet semantics, historical
segment combinations and two malformed UTF-16 producer history objects.

After the coverage/resource fixes and integration of main
`7f79585da2730fd01075839fbcc973d0090e1ae2`, repeat scans inspected 3,891 Stock
main history blobs (18 gaps), 684 producer history blobs (2 gaps), and 3,895
owner-label history blobs (5 gaps). Their credential-URL candidates were the same
four redaction placeholders and two rejection-test fixtures described above.
Task commit `e127386765ac04a23c9d4e04470f66c56b7cdd97` had no critical signature
candidates in its 1,505 tip blobs, but 9 opaque structured-data gaps. None of
these reports has complete coverage. The scanner's 17 functional tests and 31
integrated CI-scope tests passed locally; the first hosted run could not start
because GitHub reported an account billing/spending restriction, not a code
failure. Local tests do not substitute for a successful hosted run.

```powershell
# From Stock, after an authorized origin refresh.
uv run python scripts/audit_public_readiness.py --repo . --ref origin/main
uv run python scripts/audit_public_readiness.py --repo . --ref origin/main --history
uv run python scripts/audit_public_readiness.py --repo ./shioaji_stock_prices --ref origin/main --history

# Explicitly inspect research content not yet merged to main.
uv run python scripts/audit_public_readiness.py --repo . --ref origin/claude/owner-hhhl-labels-20261010 --history
```

Record selected refs and compare with current GitHub heads/tags. Repeat for every
intended published ref, including tags. Cached remote-tracking refs can include
the deleted old branch; label those findings as **local retained history**, not
as evidence the remote branch still exists. Fetch does not cover GitHub PR refs,
caches, releases, Actions artifacts, issues/comments, other clones or unreachable
objects. Initial Stock Gitleaks failed before complete coverage; it was not a clean
audit result.

Reports belong under `.tmp/`; inspect them before sharing. Never copy actual
`.env`, certificates or credential URLs into reports. Failures, bounds and opaque
formats remain coverage gaps. Review free text locally: signature checks cannot
prove absence of private conversations, trading records or confidential prose.

## Release decision checklist

- [ ] Owner confirms historical PAT revocation, without recording its value.
- [ ] Fresh remote heads/tags and retained PR refs have an inspection record.
- [x] Owner permits pure research disclosure subject to no personal data, no secrets and lawful publication.
- [ ] Research wording, timestamps and source links satisfy that principle; market-data redistribution has its own evidence.
- [ ] Intended market-data publications have source/distribution evidence, including any proposed republication of the withdrawn release ZIP.
- [ ] Archive/segment/table coverage gaps are resolved or explicitly accepted for the named snapshot.
- [ ] Historic email/path disclosure is accepted or separately authorized for cleanup.
- [ ] GitHub PR/issue/release descriptions and workflow artifacts are inspected independently.
- [ ] Owner separately authorizes visibility changes after assessing this evidence.

Do not delete data, rewrite history or silently expand scope to resolve unchecked
items. Preserve unrelated work and source evidence.
