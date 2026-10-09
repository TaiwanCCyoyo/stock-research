# Eight-case classification display correction

## Result

Yang Ming (2609) on 2021-07-23 now displays `航運／貨櫃航運（年報回溯）` with a disclosure linking its 2021 annual report. The existing catalog already retained `航運業` as an official classification snapshot; the old presentation adapter discarded that reference when the historical effective interval was unknown. This was a presentation/projection defect, not evidence that the company had no known industry.

The classification session supplied commit `75a4c59` from `codex/sector-classification-eight-case-20261004`. Its packet is preserved byte-for-byte in `research_web/fixtures/classification-v1/`: 48 official value-chain nodes, four research-group references and 11 company assertions across eight issuers. The adapter retains all 63 references and the known broad classifications without treating current references as historical memberships.

Explicit reviewed selections enable three 2021 document-period groups: Yang Ming shipping/container shipping, TSMC foundry, and HTC phone/connected-device/VR businesses. These are retrospective annual-report interpretations, not exchange classification effective intervals or claims about information available on each historical trading day. HTC's multiple roles remain visible. Oneness event chronology is not promoted into full-year membership; undated profiles remain references. KNH's known `其他業` is preserved rather than interpreted as missing.

## Evidence and boundaries

Yang Ming's official source is <https://e-solution.yangming.com/files/Investor_Relations/110Annual.pdf>, physical PDF page 91 / printed page 85, corroborated by physical page 101 / printed page 95. The producer checked the original bytes and pages; the web disclosure exposes the source and the distinction between document coverage, snapshot retrieval date, and unknown publication/effective dates.

The base presentation is preserved in `research_web/fixtures/opportunity-explorer.before-classification.v1.json.gz`. `selections.json` records explicit group choices; `export-receipt.json` binds input, classification sources, selections and output hashes. Price snapshots, wave rules, chosen waves/launches, account histories, saved strategy results and prior receipts remain unchanged. Reproduction is documented in `docs/en/opportunity-presentation.md`.

This completes the eight-case website supplement only. The outstanding 200-issuer evidence queue, full historical classification coverage, official effective intervals and first-available/publication dates remain incomplete. No full catalog recomputation, market-price download or research rerun was performed.

## Verification

- 131 frontend tests pass; production build (324 modules) and lint pass. Regression cases include packet/source binding, real-fixture CLI integration, annual-period boundaries, ambiguous memberships, retained snapshots, multiple reference roles and readable source/price explanations.
- Compared all eight portfolio calculations at six dates spanning 2020-12-31 through 2022-01-03. All numeric results are identical. Only the explicitly labelled industry allocation partition changes; prices, wave choices and account histories are unchanged.
- Operated the live browser at 2021-07-23: Yang Ming displays the new group and the same +663.8% from 2021-02-01, 19.05 to 145.50. Expanded evidence displays the official annual-report link and 2021 document coverage.
- Browser checks at 2020-12-31 and 2022-01-03 retain `航運業（分類快照）` for identification while leaving the unsupported historical group unknown. Returned the preview to 2021-07-23. No browser console errors were captured.
- Independent read-only check confirmed every source/selection/output receipt hash and the three 2021-only document groups. Screenshot and test log are retained in the worktree `.tmp/` for review.

Normal commit hooks and current-head hosted CI/review are reported in the PR and the worktree handoff after delivery; they are not inferred from these local checks.

## Presentation follow-up

The owner also identified the raw price-basis description as inappropriate user-facing copy. Price explanations now translate recognized adjustment/dividend assumptions into plain Traditional Chinese in the stock card and wave detail. Unknown descriptions remain explicitly unconfirmed rather than inheriting another source's assumptions. Source paths, hashes, claim IDs and internal rule identifiers remain in the underlying evidence records and exports; the web view presents readable descriptions, report pages and source links.

Normal hooks identified 37 checksum false positives, restricted to audited digest/commit fields in the preserved producer packet and delivery receipt. Only those exact values were added to the existing baseline. The four receipt-bound JSON artifacts are excluded from formatting so their verified original bytes stay intact; all other checks remain active.

## Hosted-review follow-up

The subsequent review found a map-to-detail wave mismatch and additional validation gaps. Wave detail now retains the selected wave/launch evidence and requires exact date boundaries rather than borrowing the first result or an analysis-local ID. Timeline clicks and keyboard movement resolve the target date's representative; an imported two-wave Yang Ming case was operated in the browser to verify the transition.

Header price summaries now share the detail's supported-basis interpretation. The same imported case with an unfamiliar price basis displays unconfirmed wording consistently. Classification export requires all six named producer checks to be present, unique and passed, and rejects extra failed checks. Re-exporting the valid packet remains byte-identical to the recorded output JSON.

Research NAV endpoints must match the declared period. Legacy atlas quality findings must contain valid dates and nonempty kinds, so malformed entries fail validation instead of crashing the page. The two saved research runs remain valid and unchanged.

Final review-fix validation: 142 frontend tests pass, including real saved Yang Ming and AVC wave selection, boundary/launch mismatch handling and feedback isolation. In the browser, Yang Ming's detail retains the map's 2021-02-01 start, 2021-02-02 launch, 2021-07-06 peak and +663.8% at 2021-07-23. The original historical source and observation date were restored after import testing.

The next review tightened two additional boundaries: timeline selection now requires an explicit representative at the requested date, including gaps before a wave starts; without one it asks the reader to choose a catalog entry instead of taking the first row. Preview export independently verifies the declared peak against the complete clean start-to-observed interval, accepting any date tied for the true maximum rather than accepting arithmetic consistency alone.

The tightened peak validation accepts all 110 source waves; the selected 86-wave export has the same serialized hash before and after the change. Final suite: 145 tests pass; build (325 modules) and lint pass.
