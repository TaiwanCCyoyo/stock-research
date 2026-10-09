# Dividend statements and linking evidence — 2026-09-09

Status: **source interpretation and offline projection only**, not an executable
cash model or strategy approval. This extends the [MOPS source evidence](research-mops-source-evidence.md).
The source code is local uncommitted data-submodule work; no gitlink update is
implied. Existing raw captures, market caches, seals and strategy results remain
unchanged.

## Verified statement projection

`shioaji_stock_prices/shp_utils/mops_dividend_statements.py` now projects one
ordinary detail body, after raw SHA-256 and company/serial/subject/route checks.
It retains source blocks and exposes five separately qualified fields. It does
not fetch data, write caches, merge announcements or create entitlements/payments.

Six retained official details were checked against their saved list rows and
manifests, then compared with manually read source values:

| Source statement                | Stated ordinary cash/share | Dividend period       | Stated ex-date | Announced payment date | Interpretation boundary                                                        |
| ------------------------------- | -------------------------- | --------------------- | -------------- | ---------------------- | ------------------------------------------------------------------------------ |
| 6509 original, key 1130710      | 1.25000000                 | 112 annual            | 2024-07-25     | 2024-08-21             | One source statement, not a separate entitlement per announcement              |
| 6509 supplement, key 1130717    | 1.25000000                 | 112 annual            | 2024-07-25     | 2024-08-21             | Same cash terms; subscription-price supplement remains a distinct announcement |
| 6465 dividend, key 1150526      | 0.20000000                 | 114 annual            | 2026-06-16     | 2026-07-13             | Later material disclosure conditionally references this payment date           |
| 6465 cash increase, key 1150609 | null / blank               | null / not_applicable | 2026-06-29     | null / blank           | Do not turn subscription activity or empty templates into dividend cash        |
| 2330, key 1130301               | 3.49978969                 | 112 Q3                | 2024-03-18     | 2024-04-11             | Income period is not payment year                                              |
| 5511, key 1050624               | 0.60000000                 | null / missing        | 2016-07-11     | 2016-07-29             | Older template does not state the labelled dividend period                     |

All 30 selected field results matched the source expectations: 26 stated, two
blank, one not-applicable and one missing. This deliberately chosen six-statement
check is not a population coverage estimate. Decimal strings preserve the source's
precision; these are not personal net cash amounts or independently verified
trading/receipt dates. In particular, the previously identified typhoon/calendar
issues are not repaired merely by parsing the source's ex-date.

## Linking conclusions and what they do not authorize

The two 6509 details have different lookup keys and announcement identities but
matching ordinary-share dividend amount, income period, record/ex/payment dates.
The supplement specifically adds the cash-subscription price. Together with the
full source wording, this supports the recorded **sample-specific interpretation**
that they describe one cash distribution. Summing them as two payments would be
wrong. This is not a universal deduplication key, nor proof that the revision chain
is complete. The projector intentionally leaves both records unlinked.

The 6465 material disclosure has matching company and explicitly references
original payment 2026-07-13. It is a candidate amendment association to the cash
statement, not to the separate cash-increase template. Its explanation names
2026-07-14 for affected regions and keeps 2026-07-13 for unaffected regions.
The association remains non-final: complete distribution/revision context and
investor applicability have not been resolved. No unconditional revised payment
or investor credit date is produced.

The missing 5511 period is a real linking limitation, not an invitation to infer
income year from announcement year. Same company/serial is insufficient; the
examples repeatedly reuse serial 1. Dates/amounts alone are matching evidence,
not authenticated economic event IDs. Preserve ambiguity instead of silently
choosing the latest announcement or summing apparent duplicates.

## Reproducible local evidence

Inspector: `.tmp/inspect-mops-statements-20260909.py`.
Output: `.tmp/codex-dividend-statements-20260909-8024a94100a443fabb7cd16db36ac103/inspection.json`.
It records six source statements, original capture-manifest/list/detail hashes,
projector/script identities and the two explicitly qualified sample associations.
All records retain `event_link_status=unlinked`, `payment_resolution=unresolved`;
zero cash events were created. No new source request or market backtest ran.

- Inspector SHA-256: `f2dbfb1afe889f4ab888ac8be6e99b5837d554d30666cb7cc2ee73c348397ab2`
- Projector SHA-256: `3ce0aed2e282a23cb1d18a1f109232f4cdd1b69b78bf2cee9a055dd6358eadca`
- Inspection SHA-256: `03edec26b8129ecdabb695bce118befbb06fcde7b837e804ef64c19e49c87e8e`

Hashes establish local consistency, not tamper-proof issuer authentication or
historical PIT. Retrospective response timestamps/body hashes also do not prove
that an economic amendment occurred; a new server timestamp can change bytes.

## Verification and next dependency

29 projector tests passed; Ruff and changed-file pre-commit passed. Tests cover
decimals, zero versus blank, missing periods, duplicate labels, reordered titles,
distinct statement/response identities, invalid/qualified dates, body size/hash,
source identity and caller-mutation isolation. Existing collectors were not
modified; their prior 97-test verification remains reusable.

Scoped implementation review identified one cash-placeholder boundary: malformed
nonblank text after `元` could be classified as a known blank, while whitespace-only
values were unsupported. This is corrected with an explicit delimiter/end boundary
and regression tests. The final six-source replay and hashes above include the fix.

Next, define an explicit evidence-backed distribution/amendment link record with
unresolved states, then a predeclared cash-timing treatment that cannot spend
unpaid receivables. Do not interpret this projection as completing calendar,
entitlement, investor charges, liquidity, confirmation-period or owner-threshold
requirements. No strategy acceptance condition has changed.
