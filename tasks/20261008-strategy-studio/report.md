# Strategy studio implementation and verification

The website now provides a latest-day home, saved strategy overview, comparison,
nine-section detail and discoverable research history. Every holding cycle opens
its original modeled fills, raw candles and cash-flow calculation. Daily account
audits include holdings, cash and separately identified receivables/share claims.
The market adds a sorted allocation comparison and soft industry backgrounds.

Subsequent Claude review fixes are documented separately in
[the partial-evidence follow-up](review-followup-20261008.md); the delivery and
verification below retain their original scope.

Base: refreshed local `main` and task branch at `f9d67e2`, in the retained
`D:/Project/Stock/.worktrees/strategy-presentation` checkout. Task branch:
`codex/strategy-studio-next-20261008`. No original mission, source prices, saved
run, wave rule, scheduler or producer data was changed. Unrelated
`.claude/launch.json` remains unstaged.

## Delivered contracts and maintenance

- [Data contract](data-contract.md) defines the additive Git-portable
  `saved-research-studio.v1` package, read-only routes and reproduction limits.
- [Publication manifest](publication.json) records the package bytes and SHA-256.
  The old `saved-research-runs.v1` package remains intact.
- Domain calculations, API access, pages and chart renderers are separate modules.
  New report discovery uses the existing task catalog/registry, with optional
  presentation metadata; frontend pages do not maintain a handwritten task list.
- CLI `/membership` consumers and the browser share the same saved daily map
  projection. Strategy participation uses +100%, launched only. Changing a map
  filter does not silently change the strategy comparison's definition.
- Preserved unknown daily ranks, classification/date gaps and draft summaries
  remain visible. Research screening and owner adoption are separate states.

## Review follow-up

| Claude ID | Result                                                                                                                          |
| --------- | ------------------------------------------------------------------------------------------------------------------------------- |
| C-1       | Retained +100% default, 60/80/100/200 options; no new wave fitting                                                              |
| C-2       | Retained launched-only default and labelled alternate catalog view                                                              |
| C-3       | Retained whole-market overview and readable industry callouts; new default date is latest covered day                           |
| C-4       | Restored controls plus sorted known allocation ranking; unknown portfolios remain distinct                                      |
| C-5       | Added soft organic industry territory shading; no replacement of the approved stock sizing formula                              |
| C-6       | Owner accepted retaining saved Yang Ming start; no issuer-specific rule changes                                                 |
| C-7       | Retained provisional phase colors; Taiwan gain/loss convention now red/green                                                    |
| C-8       | Removed specified development copy; simplified account values and explanation; detailed provenance stays in expandable evidence |
| C-9       | Compact query projection, verified local startup memo and background initialization implemented; measurements below             |
| D-1..D-4  | Existing approved threshold, launch mode, phase meanings and time-based sizing retained                                         |

## Verification

- 364 targeted Python tests passed across the implementation and follow-up regressions: checksum exception controls, verified split transport, original-source binding (including offsetting
  corrupt cash flows), partial exits/company actions, exact candidate joins,
  concurrent single-flight, daily membership/unknowns, memo tamper/size limits,
  compact projection, fixed adapter-version registration, full catalog verification and API loading protocol.
- 312 frontend tests passed; production build succeeded. A 680 kB entry chunk
  still produces a build-size advisory; route splitting remains an improvement.
- Independent Decimal audit sampled seven closed cycles and six account days
  across both runs (fixed seed 20261008): every difference was zero.
- Browser checks opened five sampled cycles (2358, 5483, 2305 on 2022-08-26,
  2457 on 2021-04-07, 4167), plus the best profitable 1325 cycle. Cash-flow
  formulas reconciled with saved PNL. Three clicked account days (2021-05-21,
  2019-10-03, 2020-10-30) reconciled holdings + cash + other assets with saved NAV.
- Four-step walkthrough completed automatic playback, and best/median/worst
  choices worked. Desktop and 375px checks covered light/dark layouts, home,
  strategy detail/audit, comparison and history without body horizontal overflow.
- Home and market on 2026-10-02 both showed 114 stocks, 21 industries. Three rapid
  timeline drags caught up to the final requested date, with the older display
  explicitly labelled while loading. Browser FPS and full-load animation quality
  were not benchmarked; no 60 FPS claim is made.

Both saved runs span 2019-01-02..2023-12-29, 1,216 account dates, initial capital
2,000,000. Add/retry: 303 cycles, final 4,968,993.15; closed PNL 2,817,221.15 + open
PNL 151,772 = account increase 2,968,993.15, difference zero. Extension cap:
120 cycles, final 2,401,796.20; closed PNL 402,027.20 + open PNL -231 = account
increase 401,796.20, difference zero. These are stored modeled accounts.

## Startup evidence

The previous full-reader baseline was 859.56 seconds; Claude separately observed
about 11 minutes. The compact projection took 185.31 seconds on the unchanged
local snapshot without the new startup memo. The final working memo restored the
core in 17.77 seconds, and a fresh owned API returned its first latest-date frame
in 20.00 seconds from the initial request. These measure initialization, not the
entire browser animation pipeline, and depend on this machine's local cache/I/O.
The submitted `be54a32` revision was measured again: full validation/first frame
209.81 seconds; the same-version restart/first frame 18.57 seconds. These are
measurements of that source revision, not a guarantee for later revisions.

An intermediate 181.38-second repeat was a memo miss because the original decoded
size bound was too low; it is not a successful warm measurement. The corrected
memo holds 23,319,142 compressed bytes, with explicit 96 MiB compressed and
512 MiB decoded bounds. Absent, invalid or changed identities cause full background
validation. Source bytes are rehashed on every restart; original scientific
validation gates remain unchanged. Scratch timing/audit receipts are retained in
`.tmp/claude-codex/` and are not the formal data producer location.

## External follow-up and limits

The owner approved future daily holdings-rank recording. This request, and the
request to confirm Claude's plain-language summaries, were sent to K-line research;
implementation/wording acknowledgement is still pending. Old ranks are not
reconstructed and no new study is started by this delivery. Draft summaries are
marked pending and cannot override formal outcomes or owner adoption.

0050 is a separately pinned raw-price comparison without dividends. Daily
participation means overlapping saved holding days, not complete-wave capture.
Unknown historical ETF holdings, excluded/delisted issuers and early adjustment
limitations remain outside the supported evidence. The preliminary market catalog
is not a complete census or a predictive signal.

Local preview: `http://127.0.0.1:8518/#home`, serving the built frontend and new
read-only API together. Existing 5177/8517 services were preserved. Hosted CI and
current-head review status are recorded in the task's `.tmp` handoff after PR
delivery; owner merge remains separate.

## Hosted review repairs

Four MEDIUM findings were fixed with regressions: optional memo cleanup errors
cannot poison verified history; missing resources return 404 while corrupt
evidence returns a path-free, identifiable 503; split exports reject non-JSON
manifest paths before source reads or writes; recovery to an equal high ends a
drawdown period consistently in browser and backend. The CI failure also exposed
an unregistered compact adapter revision. Its audited SHA was added to the fixed
V2 registry, with LF checkout bytes pinned; unknown revisions, old V1 rejection,
source hashes and full receipt-context checks remain enforced. Existing data
packages were not regenerated for these code repairs.

A final browser check found this implementation report among the investment
research cards. An optional, explicit `research`/`infrastructure` presentation
category now filters the HTTP research-history projection. Missing categories
preserve legacy entries, including failures; original package rows and outcomes
remain intact. Invalid or missing specified policies return 503. The maintained
presentation policy and its publication checksum were updated without rewriting
either saved strategy part.

Renewed review added package-shape and Windows read-access failures. Required
v1 containers, every row, dates and IDs are now validated before caching;
malformed structures return integrity 503 and filesystem OSError returns
unavailable 503. No partially validated package is cached, and a repaired file
can be retried in the same service. Missing evidence and extension fields remain
intact. Nonpositive recorded equity stays readable, with undefined portfolio
weights retained as null. The two actual saved packages passed this validation.

All 53 report/mission records were checked for purpose. Nine explicit tooling or
website infrastructure records have presentation categories; descriptive studies,
failures and mixed method/planning work remain in investment history. First visits
open the latest day, valid visits restore the same catalog's saved date, and an
explicit market URL date has precedence. Storage-access failure falls back to the
latest day. These follow-ups do not change original research results.

A final bounded contract check found that opaque run IDs such as `__proto__`
could pick up inherited object properties in the display description lookup and
crash strategy cards. The helper now checks only registered own properties;
unregistered IDs retain their saved description. Prototype-name fallback and
registered-override regressions passed without restricting valid IDs.

The subsequent hosted MEDIUM review found encoded slashes were decoded before
path-route matching, making valid opaque IDs unreachable. Four query-ID routes
now share the original handlers and preserve path-safe compatibility aliases.
Frontend hooks, capture and comparison use a central URLSearchParams helper;
comparison selection identities use JSON instead of newline delimiters.
Nineteen additional Python cases verify real split-package ID round trips,
missing query fields, 404/422 behavior and legacy aliases, including slash,
Unicode, whitespace, punctuation and newline IDs. Three frontend regressions
verify single encoding and selection identity. No saved package was modified.

The next review found that incomplete allocation rows were painted as zero.
Allocation areas now retain each unknown date as a grey gap and never connect
known regions across it; the expanded allocation line uses the same mask. Known
zero remains zero, and original weights are neither clamped nor filled. Name-only
fallback upgrades now update both name provenance fields from the verified
catalog identity; missing provenance preserves the original code label. Sixteen
Python cases cover both holdings and trades, original-package immutability,
missing provenance and preservation of existing names. Saved-run amounts also
honor their recorded currency, and the documented comparison/history routes
match the actual pages.

Saved-participation and home market links now explicitly specify the shared
100%/launched definition. The map applies valid explicit mode and threshold
overrides, while partial links preserve unspecified controls. Four regressions
cover previous catalog/threshold settings and supported manual links. Walkthrough
picks carry explicit roles and distinct original trade IDs: one complete cycle
is the only example, two are best/worst, and larger sets retain the original
middle-rank choice. Five cases cover empty, one, two, many and repeated inputs.
