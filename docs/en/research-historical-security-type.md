# Historical security identity — bounded source evidence

Date: 2026-09-09. No performance result or full-universe certification.

## Reusable code rules, not present-day membership

The [2016 coding rules](https://twse-regulation.twse.com.tw/TW/law/DAT06_print.aspx?FLCODE=FL033103&FLDATE=20160802&LSER=001)
assign four numeric digits to public-company stock; preferred shares and
convertible/right instruments add characters. The
[2022 version](https://twse-regulation.twse.com.tw/tw/law/DAT06_print.aspx?FLCODE=FL033103&FLDATE=20220124&LSER=001)
explicitly gives innovation-board shares the same basic code convention.
Thus the code does not prove board identity.

The original [B.11 manual](https://www.twse.com.tw/docs1/data01/market/public_html/1040202-1040600224-1.pdf),
printed pages 86-87 (PDF pages 90-91), was downloaded and visually inspected,
resolving the earlier flattened-table limitation. Ordinary shares use four
digits beginning 1-9. The table places funds/ETFs in zero-leading families and
TDRs in the 91 family; its footnote preserves older four-digit instruments and
the 9201-9299 TDR range. A four-digit-only filter is therefore insufficient.
These rule vintages support type screening, not an all-date classifier or a
complete inventory of listing, transfer and termination events.

The smallest proposed input rule combines a dated exchange roster with the
ordinary-code convention, excludes TDR/fund/suffixed-instrument families, then
joins dated board-event evidence. Do not require today's symbol_meta membership,
infer industry from code, or label an unmatched type/board as ordinary.

## Historical quote names are not a board-history source

The captured TWSE 2023-12-29 `ALLBUT0999` response contains the following names:
6757 `台灣虎航`, 6869 `雲豹能源`, 6873 `泓德能源`, 6902 `GOGOLOOK`.
They lack the innovation-board name tag. The official listing-event register
instead retains their innovation-board entry names/dates below. For a direct
boundary check, the [2024-06-18 transfer notice](https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d6901a64ae01902ad7af4f0045.pdf)
states that 6869 transfers from the innovation board on 2024-06-19, after the
queried daily date. The daily name is not sufficient historical board evidence;
this finding does not show that its OHLC or date is wrong.

Stop using name suffix absence to admit historical main-board shares. Presence
of a name in a dated roster and historical accuracy of every metadata field are
different claims. The [2021 naming notice](https://twse-regulation.twse.com.tw/tw/int/DAT01_print.aspx?FLCODE=FE348909)
confirms special innovation-board naming was introduced; it does not certify
that a modern historical-price API preserves those old names.

## Ten dated innovation-board entry records

The [official listing-event register](https://www.twse.com.tw/company/newlisting?response=html)
captured as JSON contains these ten entries with 2022-2023 listing dates and
explicit innovation-board remarks. This is a useful event-source extraction,
not proof of complete board intervals or original announcement availability.

| Code | Entry date | Entry name    |
| ---- | ---------- | ------------- |
| 6854 | 2022-08-18 | 錼創科技-KY創 |
| 6873 | 2023-03-06 | 泓德能源-創   |
| 6869 | 2023-03-14 | 雲豹能源-創   |
| 2432 | 2023-05-31 | 倚天酷碁-創   |
| 6902 | 2023-07-13 | 走著瞧-創     |
| 6757 | 2023-08-15 | 台灣虎航-創   |
| 2254 | 2023-10-20 | 巨鎧精密-創   |
| 2258 | 2023-11-20 | 鴻華先進-創   |
| 6534 | 2023-12-21 | 正瀚-創       |
| 6645 | 2023-12-21 | 金萬林-創     |

Use entry/effective transfer events, not future endpoint labels. A known future
transfer does not make earlier sessions ordinary-board sessions. Do not hard-code
a permanent exclusion of the ten names as a substitute for their dated status.
The event register is a reconstruction source retrieved today, not a vintage
snapshot; original timing must remain distinguishable from retrieval time.

## Local evidence and next action

`.tmp/security-code-evidence-20260909/twse-b11.pdf` SHA-256:
`ef263ad32a370f490668a4f8d9a3a65235877ebe1e1b09f5889935469cd56f2e`.
The two rendered appendix pages are in the same directory.
`newlisting.json` SHA-256:
`c45549cd8c749bab1aa41d65ae81ea5415ecf1e9876da373bafef174fb56ba9b`.
The raw quote response and its hash remain in the
[membership evidence](research-stock-membership-evidence.md).

Next, extract dated entry/transfer rows needed by the selected 2019-2023 window
and build the required code/month seed from historical exchange rosters. Reuse
the existing TWSE monthly and TPEx dated-market parsers and the additive export.
No full company-name history crawler is required. TPEx all-securities data is
also not a security-type label; apply verified type evidence, not current metadata.

No cache, schedule, existing result or strategy outcome was changed or produced.

## Completed monthly seed capture

One predeclared source-only batch captured the last observed 2330 trading date
of every month from 2018-01 through 2023-12: 72 requests, 72 valid dated rosters,
zero failures. The explicit dates were fixed in `capture-plan.json` before the
first request; budgets were 72 requests, 300 seconds, no retries, 2 MiB per response.
The read-only indexed 2330 date query supplies a calendar seed, not a membership
filter. No prices, rankings or account returns were calculated.

Independent inspection verified all 72 raw hashes and parsed code lists against
their receipts. Their union contains **1,304 instruments**. The nonzero four-digit
screen excluding 91/92 prefixes leaves **1,039 code-shaped candidates**, not a
certified pure-stock population. Of these, 51 have no TWSE rows anywhere in the
current official database, based on indexed read-only queries. Forty-one appear
in at least one 2019-2023 monthly roster; ten appear only in the 2018 captured
rosters. That last distinction is not proof of no trading in early 2019, and is
not permission to drop them. Existing Shioaji fallback coverage is a separate
question, so 51 missing official histories does not mean 51 wholly missing series.

Evidence directory:
`.tmp/monthly-roster-seed-20260909-31e6268852714f6ea64b3565b11cc379/`.
It holds the raw rosters, per-date receipts, capture plan/result and
`seed-audit.json` (all missing-code observations plus the ten board-entry records).
Capture and independent inspection scripts are respectively
`.tmp/capture-monthly-roster-seed-20260909.py` and
`.tmp/audit-monthly-roster-seed-20260909.py`.

| Artifact               | SHA-256                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| Capture plan           | `cdb1e7fd2ede69e512a1f2b51f054e1a3973df94dee15a66ae0e76c2a995ee8c` |
| Capture result         | `04cd52d897ad3aefb00bc683de3450567a98fe76613a6ff82c1e601d7b8d20ea` |
| Independent seed audit | `37e270f57c830c50a0ba719d2e817e1475ba7be740012c72545e4bec876a2d43` |

Monthly samples discover acquisition work; they do not themselves establish
daily listing/tradability or prove that no between-snapshot instrument was missed.
Retain known entry/exit events, dates and the candidate's trailing-history rule
when checking seed sufficiency. Do not use a code's future last appearance to
decide when to liquidate it. Next, reconcile/recover the explicit missing histories
with original monthly responses and the existing parser, in a separate artifact;
do not rerun the unchanged automatic code seed or rebuild the daily downloader.
