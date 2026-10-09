# MOPS announced-payment evidence — 2026-09-09

Status: **bounded TWSE/TPEx source samples verified; not a production adapter, full backfill,
PIT certification or strategy verdict**. Owner authority is the 2026-09-09
acquisition update. Parent checkout at probe start: `707b83f`; submodule data/code
baseline: `32c1d916`. No existing cache, sealed input or historical result changed.

## Source and bounded acquisition

The official [MOPS ex-right/dividend announcement page](https://mops.twse.com.tw/mops/#/web/t108sb19)
successfully listed 6509's 113-year announcements. Its detail click did not expose
a detail page in the in-app browser. That UI observation is not source unavailability.
Read-only inspection of the public `assets/index.js` and `assets/t108sb19.js`
established the JSON POST transport and the response-provided detail links.
No downloaded JavaScript was executed by the probe.

Use `https://mops.twse.com.tw/mops/api/` with `Content-Type: application/json`.
Observed list route: `t108sb19`; fields match the official form:

```json
{
    "companyId": "6509",
    "dataType": "2",
    "year": "113",
    "month": "all",
    "firstDay": "",
    "lastDay": ""
}
```

For the second existing discrepancy case, change companyId to `5511` and year to
`105`. The response's `recordDateAnnouncement.data` contains the exact `apiName`
and `parameters` for each detail. **Follow these values; do not derive the detail
key by removing slashes from the displayed announcement date.** Observed route
`t108sb19_detail` and selected parameters:

```json
{
    "declarationDate": "1130717",
    "etn_no": "",
    "companyId": "6509",
    "serialNumber": 1,
    "detailReportKind": "A"
}
```

```json
{
    "declarationDate": "1050624",
    "etn_no": "",
    "companyId": "5511",
    "serialNumber": 1,
    "detailReportKind": "A"
}
```

Six explicit list/detail HTTP POST probes succeeded: the first 6509 list/detail
pair was inspected, then repeated once to retain raw response bytes; 5511 needed
one list/detail pair. Four raw JSON files were downloaded to the fresh local
`.tmp/codex-mops-evidence-20260909/` directory. Browser navigation and public
frontend reads are separate from those six POST probes. No broker login, purchase,
market-history sweep, scheduled-writer change or write under the data directory
occurred. Both companies were chosen from existing data-discrepancy examples,
not from candidate profits; their disclosure samples do not make any price period
unseen or independently validated.

## Observed event mapping

Both samples are **TPEx ordinary-share announcements**, not a TWSE coverage test.
Dates below are explicit announcement fields, not inferred actual exchange sessions.

| Company | Displayed announcement date | Detail lookup key | Stated ex-date | Record date | Announced payment date | Stated cash dividend TWD/share |
| ------- | --------------------------- | ----------------- | -------------- | ----------- | ---------------------- | ------------------------------ |
| 6509    | 2024-07-18                  | 1130717           | 2024-07-25     | 2024-07-31  | 2024-08-21             | 1.25000000                     |
| 5511    | 2016-06-28                  | 1050624           | 2016-07-11     | 2016-07-17  | 2016-07-29             | 0.60000000                     |

The list has two rows for 6509 and one for 5511. In both selected rows, the column
`修正後現金股利發放日` is `無`, yet the detail's `（五）權利分派內容：`
explicitly contains `現金股利發放日`. The list's absence of a revised date is not
absence of an original payment date. Both detail responses have 23 titles and 23
cells in one row; this is observed shape, not a parser rule based on field count.

6509's selected record is a supplemental capital-raising-price announcement. It
also contains cash subscription rights and a 37.00 subscription price. Do not
interpret all mentioned dates/amounts as cash dividends or certify the combined
corporate-action accounting from this sample. The earlier 6509 list record was
not downloaded as a detail and the full revision chain has not been reconciled.

Both issuers describe payment by transfer or mailed cheque, whole-dollar rounding,
and shareholder-borne transfer/postage charges. Thus the announced amount/date
does not establish an investor's net credited amount, intraday cash availability,
or personal bank-credit date. No fee amount or payment-lag model is approved here.

## PIT and normalization boundary

- Keep displayed announcement date, response-provided detail key, stated ex-date,
  record date, announced/revised payment date, response-generation time and local
  fetch time separate. Exact historical public-availability time remains unknown.
- `declarationDate` precedes the displayed announcement date by one day for 6509
  and four days for 5511. It is a lookup key in this evidence, **not an established
  public-availability timestamp**. The reason for the discrepancy is unresolved.
- Top-level `datetime` is the server's current response time, not historical
  publication. Recorded files were fetched on 2026-09-09 around 18:41 +08:00.
  Re-querying an endpoint today does not prove its full historical revision state.
- Locate fields by observed titles and explicit semantic labels, retaining original
  text. Blank ROC date templates, special-share sections and multiple event types
  must not become zero dates, ordinary-share amounts or duplicate cash events.
- The stated 6509 ex-date falls on the already-identified disputed closure date.
  This announcement does not settle actual exchange-session/effective-date mapping
  or the two TPEx daily-limit discrepancies.
- Current evidence establishes an obtainable **announced-payment source** for two
  samples, superseding the earlier source-unknown status. It does not yet establish
  coverage, final revisions, historical PIT safety, or captured account cash.

## Raw evidence and local verification

Files are ignored local evidence, not normalized cache rows. SHA-256 identities:

| File in `.tmp/codex-mops-evidence-20260909/` | SHA-256                                                            |
| -------------------------------------------- | ------------------------------------------------------------------ |
| `6509-113-list.json`                         | `26A0B9E3E661FA04F07DEE41CCBEBE1B5D5DC1D8DB8EC582744E9B587BC66049` |
| `6509-1130717-detail.json`                   | `C990F7EEAF2492C5B75A5DFB0B438B5CE02D7C964A4270A722BCD3FFE2DEAAA3` |
| `5511-105-list.json`                         | `8F637F4C609EF349CAB32FA3BCE14495C8A322EDD40A26D170ED819FFC60688C` |
| `5511-1050624-detail.json`                   | `5E1DF38EAEA70206B699F7EACFBCBE1EDC8BE8CEEE3D562FDEF643CDAC2C7B02` |

Offline PowerShell verification parsed all four files, required application code
200, checked one row and matching title/cell lengths in each detail, and required
exactly one explicit `現金股利發放日：` ROC-date label per detail. All passed.
This is sample evidence, not a tested general parser. The retained response times
are `115/09/09 18:41:11` for the first three requests and `18:41:27` for 5511 detail.
Fresh response timestamps mean a future fetch may legitimately have another hash.

The initial next step was a bounded additive raw collector in the submodule;
that implementation is now present but uncommitted, pending the separate owner
decision on a submodule commit and parent gitlink update. It is not a normalized
payment feed. Missing dates remain unavailable, never replaced with immediate
ex-date cash or zero dividend.

## Listed-company collector sample — 2026-09-09

A fixed TWSE company/year sample, 2330 / ROC 113, checks the listed-company
response independently of candidate profitability. The opt-in CLI used
`--max-details 1` and a fresh output directory; it made exactly one list request
and one detail request. Both returned HTTP/application 200. The ordinary list
contains four announcements, of which one was captured and three remain
unprocessed. The manifest status is correctly **partial**, and CLI exit 1 reflects
the declared detail budget, not a failed request. No retry or full-year sweep was
performed. No existing cache or market result was changed.

The first response-provided detail link has company `2330`, serial 1,
`declarationDate=1130301`, `etn_no=""`, and `detailReportKind="A"`. The displayed
announcement day is 2024-03-01. Its subject identifies the 112-year third-quarter
cash dividend, not the quarter containing the later cash payment.

| Explicit detail field        | Observed value           |
| ---------------------------- | ------------------------ |
| Ordinary-share cash dividend | TWD 3.49978969 per share |
| Stated ex-date               | 2024-03-18               |
| Record date                  | 2024-03-24               |
| Announced payment date       | 2024-04-11               |
| List revised-payment field   | `無`                     |

The detail's named rights-distribution field states the payment date; its other
announcements section repeats the expected date and describes transfer or mailed
cheque, whole-dollar truncation, and shareholder-borne transfer/postage costs.
This is announced issuer cash, not observed investor-net cash or a bank-credit
timestamp. This sample again demonstrates that `無` in the revised-payment column
does not mean no original payment date. It does **not** test a nonempty revision.

Raw files are under `.tmp/codex-mops-live-2330-20260909/`. Fetch times span
2026-09-09T11:05:26.710553+00:00 to 2026-09-09T11:05:27.200636+00:00.
Offline `Get-FileHash -Algorithm SHA256` verification matched both manifest hashes:

| File                | SHA-256                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `response-001.json` | `6eb702c5791d84fa1af974184299867491247c1fdf75976c5a7663957b612fc5` |
| `response-002.json` | `1fdc3989a5ce6434ac1a9689d472e290185fa38e30ac0059033ef1a0a52a84a1` |

The manifest retains `historical_coverage`, `historical_public_availability` and
`revision_completeness` as unverified. Thus the raw transport now has one listed
and two OTC source examples, while normalized amount/date extraction, revision
resolution, effective exchange-session mapping and PIT availability remain open.
Before bulk acquisition, choose a bounded revision-bearing source case and fix
the event-matching rules; do not infer coverage from these three issuers.

## Announcement identity versus economic event — 2026-09-09

Two later bounded live captures used the unchanged, uncommitted collector in
submodule baseline `32c1d916`. Its module SHA-256 was
`fe00b8aa9bd33af7d5859e4e0b32b48fced801c802f54e33f7dff60bff8a79c4`;
CLI SHA-256 was
`9b4c24419ef0723a782b70e557bd3d727f7eff3d17e49bf0c5f29354f5bdf6a6`.
No normalized dividend rows, historical results or schedules were changed.

### 6509: an original announcement and its supplement

The already-selected 6509 / ROC 113 case was captured with `--max-details 2`
into `.tmp/codex-mops-live-6509-pair-20260909/`. Three HTTP requests returned
application/HTTP 200; both listed details were captured, with no unprocessed
rows. `complete` describes this returned list only, not all historical revisions.
The UTC request interval was 2026-09-09T11:24:38.277291+00:00 through
2026-09-09T11:24:39.021718+00:00. All three raw hashes matched the manifest.

| Field                                   | Original, key `1130710` | Supplement, key `1130717` |
| --------------------------------------- | ----------------------- | ------------------------- |
| Displayed announcement day              | 2024-07-10              | 2024-07-18                |
| Announcement serial                     | 1                       | 1                         |
| Distribution year/period                | 112 / annual            | 112 / annual              |
| Stated cash dividend per ordinary share | TWD 1.25000000          | TWD 1.25000000            |
| Stated ex-date / record date            | 2024-07-25 / 2024-07-31 | 2024-07-25 / 2024-07-31   |
| Announced payment day                   | 2024-08-21              | 2024-08-21                |
| Cash-subscription price                 | blank                   | TWD 37.00                 |

The later subject explicitly says it supplements the issue price. Matching
distribution fields and that description support treating these as two disclosures
of the same cash distribution, not two cash entitlements. The cash-subscription
price is not cash received by a dividend investor. Keep both raw announcements;
do not sum their dividend amounts or backdate the later subscription price.
This is a measured event-linking example, not a general deduplication key. In
particular, company/year/serial is insufficient even for announcement identity.
The stated ex-date still does not resolve the previously identified closure issue.

| File                | SHA-256                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `response-001.json` | `09c99184ba150e1d161c21d6ea4100e42bf6e5e06eb522b7ad9a26983b1722c8` |
| `response-002.json` | `086a76e50deb4ea7df6dbabbc6e15e2c272f721df3384e1c55b7acb533529f0c` |
| `response-003.json` | `39e12085bda012c4dbd3d6474fed0160969b2e1ea369ec84c6951f82edd1a610` |

### 6465: a cash dividend and a separate cash subscription

A public search-index lead about a conditional July payment postponement selected
6465 / ROC 115 for a fixed source check, not a performance-based stock choice.
Only the resulting official MOPS payloads below establish the observed fields;
the indexed repost is not proof of the postponement or actual payment.

`--max-details 2` wrote `.tmp/codex-mops-live-6465-revision-20260909/` with three
successful HTTP requests. The list has three announcements; two details were
captured and one cash-subscription supplement remains unprocessed. Status is
`partial`, CLI exit 1, with no retry. The directory name describes the probe's
question, not successful verification of a revised payment.

The cash-dividend announcement displays 2026-06-02, has lookup key `1150526`,
and describes ROC 114 annual cash distribution: TWD 0.20000000 per ordinary share,
stated ex-date 2026-06-16, record date 2026-06-22, payment 2026-07-13.
The separate capital-raising announcement displays 2026-06-11, key `1150609`,
with stated ex-date 2026-06-29 and record date 2026-07-05. Its cash-dividend
amount is blank and payment is an unfilled ROC date template. These are not
zero dividend observations, and cannot inherit the prior dividend's payment day.
Both have serial 1. Grouping all company/year rows would merge distinct events.

All three listed revised-payment cells say `無`; the returned list contains no
July conditional-postponement announcement. This negative list observation does
not establish that no later material disclosure exists. Nor does it establish
that the original dividend was paid on schedule. The separate major-announcement
source and any conditional region/payment-method applicability need verification.
An older [TWSE disclosure training document, page 17](https://wwwc.twse.com.tw/staticFiles/news/event/event_download_201409051700_02.pdf)
describes payment-date changes/delays alongside material disclosures and payment-
date updates. It is a source-discovery lead, not a current or historical coverage
certificate for the TPEx issuer. A 2025 TPEx template search result and the
issuer's investor page could not be opened successfully in this check.

| File                | SHA-256                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `response-001.json` | `9085ea359533bed796a75fe715ec5a9ff43b41de05973f29a2572b81c5f0a97e` |
| `response-002.json` | `3454d48d7c53d9a8473c915270e7dfe74d741acb3fcff23bb7b7dd937673cadd` |
| `response-003.json` | `ef66b5be9b45522f87f3a3c5639355d62bf1dafdcd7b2813e41f7c3aa8f397d7` |

All three hashes were recomputed locally. Next: verify one payment-change material
disclosure and its precise applicability before calling a date final. A pure
announcement-level extractor may preserve known values and missing/unsupported
states, but bulk acquisition must not silently become a deduplicated, PIT-safe
cash feed. No new strategy period was opened by this source check.

## Official conditional-payment change obtained — 2026-09-09

The next fixed 6465 check obtained the missing official material disclosure.
This supersedes the preceding source-unverified lead, not the preserved ordinary
announcement list or any historical strategy result. The chosen subject/day came
from the earlier source-discovery lead, not from candidate performance.

Read-only inspection of the official homepage's `assets/index.js` identified
`t05st01` as the historical material-disclosure route and its `assets/t05st01.js`
component. That file declares the form fields and JSON POST operation. These
downloaded scripts were inspected as text, never executed. The successful probe
used the page's exact field names:

```json
{
    "companyId": "6465",
    "year": "115",
    "month": "7",
    "firstDay": "",
    "lastDay": ""
}
```

POST `https://mops.twse.com.tw/mops/api/t05st01` returned nine July rows.
Only the selected dividend-change row was followed. Its response-provided detail
route is `t05st01_detail`, with parameters:

```json
{
    "serialNumber": "2",
    "enterDate": "1150709",
    "marketKind": "otc",
    "companyId": "6465"
}
```

Both list/detail requests returned HTTP 200 and application code 200. The list's
named release-date/time, subject and detail key match the selected detail's
named fields. The detail states release 115/07/09 at 16:43:13 and contains:

- original dividend payment: 2026-07-13;
- changed payment: 2026-07-14;
- applicability: financial processing in regions affected by typhoon-related
  work suspension; regions not affected retain the original 2026-07-13 date.

The explicit changed-date field is therefore **conditional**, not an unconditional
replacement cash date for every investor. Retain the explanation and unaffected-
region exception; regex extraction of the new date alone would discard material
semantics. The actual affected region, whether the contingency occurred, payment
method and individual credit remain unverified. No hypothetical lag or automatic
cash date was approved from this record.

This proves a concrete companion-source requirement: the earlier `t108sb19` list
had all revised-payment cells `無`, yet `t05st01` supplies a relevant later
conditional disclosure. A complete capture of the first list alone cannot certify
a final payment date. It does not prove that either endpoint contains every later
correction or all history. Of the nine material-disclosure rows, eight details were
not captured; they were not silently classified as irrelevant or settled.

Do not use `enterDate` as a publication timestamp. Even within this same July list,
other rows' display dates differ from their detail lookup dates. The selected
row's equality is not a universal rule. Preserve the stated release date and time,
lookup parameters, fact-occurrence date, current server response time and local
fetch time separately. A retrospectively fetched displayed timestamp is not proof
of an immutable historical revision or an authenticated first-publication time.

Local evidence is `.tmp/codex-mops-material-20260909/`, with a manually assembled
`mops-material-probe.v1` manifest, not a production collector receipt. HTTP POST
intervals were 2026-09-09T11:32:15.7893130Z..11:32:17.3525727Z for the list and
11:32:38.6994447Z..11:32:38.9020626Z for the detail. Redirects were disabled,
timeouts bounded at 20 seconds, and no retry, login or paid source was used.
The initial sandbox homepage read failed to connect; the authorized normal-context
read succeeded. The two API requests themselves each succeeded on their first call.

| File                       | SHA-256                                                            |
| -------------------------- | ------------------------------------------------------------------ |
| `index.js`                 | `89d06f206775b0b1d10eef7aaf892be890ff2f9efef7c5915011becdb6bd3280` |
| `t05st01.js`               | `5b0daf3aed6f3d7866b8b12cf9c0e4de8b137bf67193a0d7985d62702dd72452` |
| `6465-11507-list.json`     | `096a62b2c13e36653777fa816d409fa9ee784ed4327e10f4bcf519c1f43ab321` |
| `6465-1150709-detail.json` | `327821fbf44bd7a3f4a2e921b5aeb1e0d08c1ba92c9e6252b4cf5849f7e18315` |

Next implementation scope: a bounded additive companion collector preserving
these exact list/detail fields and explanation text, followed by explicit
announcement-to-distribution links and conditional/unresolved payment states.
Do not silently broaden the current `t108sb19` collector's schema or produce a
single final payment date merely because both endpoints are reachable. Existing
source files, caches, seals, portfolio results and submodule gitlink remain unchanged.

### Companion collector verification — 2026-09-09

The bounded companion collector is now implemented in the local data submodule:
`scripts/fetch_mops_material_evidence.py`, backed by a source-specific parser and
shared raw capture engine. It requires company, ROC year/month and a detail budget.
The existing dividend capture API and `mops-dividend-evidence.v1` remain compatible;
material output has its own `mops-material-evidence.v1` schema. No normalized cash
date, entitlement, personal payment or conditional-applicability decision is made.

The retained official pair was replayed through the new collector, preserving
both byte hashes, all nine list rows, the one captured explanation and eight
unprocessed rows. Final replay output is
`.tmp/codex-mops-material-replay-20260909-c6187b781448451292f4b368893e1f6b/`;
its capture mode is explicitly injected transport, not a fresh source request.

A separate live CLI verification used company 6465, ROC 115/month 7 and
`--max-details 1`, writing only to the new
`.tmp/codex-mops-material-live-6465-20260909/` directory. Two requests returned
HTTP/application 200; both request outcomes validated. The manifest correctly
reports partial, 9 listed, 1 captured and 8 unprocessed. Its exit 1 reflects the
fixed budget, not a failed download. The full conditional explanation was inspected;
both raw hashes were independently recalculated:

- List: `c15ead160eb4c2b005cc74021238edf589a6f804d7ce448db62f9e3ab4ff4da5`
- Detail: `1d86db0fe59380920dda4bcadc78dd911498396125ab69617dbb8679a30ef747`

Capture ran at 2026-09-09T11:52:05.982907+00:00 through
11:52:07.558585+00:00. This is a fresh response, with different current server
timestamps and hashes from the recorded probe; byte identity was not expected.
No bulk acquisition, scheduled job,
official data-area write or new historical strategy evaluation ran.

Affected-component verification: 97 tests passed (new material source/CLI,
existing dividend source/CLI and data paths), plus Ruff, changed-file pre-commit
and strict OpenSpec validation. This is not a whole-pipeline test or proof of
historical coverage. Unsupported material-market values still fail explicitly;
only `otc` has a verified material-detail sample. Neither retrospectively fetched
publication times nor successful capture certify historical PIT/revision completeness.

Scoped implementation review found one low-severity malformed-key case (ROC year
`000`); the material validator now rejects it before any detail request, with a
regression test included in the 97 passes. Existing dividend semantics were not
changed. Security review found no concrete issue. The valid recorded/live key
`1150709` is unaffected; no additional live request was needed for this fix.

Both collectors remain local uncommitted submodule work pending the owner's
explicit submodule-commit/gitlink decision; the parent gitlink remains
`32c1d916039c680f261aad3c23886daaaae00d4e`. This evidence note does not declare those
uncommitted sources reproducible from the parent Git checkout alone.

Next dependency is explicit announcement-to-distribution linking with conditional
and unresolved payment states, followed by source/assumption-qualified account
cash handling. Do not spend receivables or use a later changed date as unconditional
cash merely because both raw endpoints now have working collectors.

The subsequent [statement projection and linking inspection](research-dividend-link-evidence.md)
verifies six retained ordinary announcements, preserving duplicate-disclosure
identity and blank/missing fields. It still does not create cash events or resolve
the conditional material amendment into a universal payment date.
