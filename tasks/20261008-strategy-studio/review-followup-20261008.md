# Studio review follow-up: useful partial evidence

Claude's review identified that a small number of missing classification dates
hid the whole participation answer. The API now adds a ready-provider coverage
projection, while the UI shows confirmed trades and complete-date averages with
their denominators. Saved whole-period fields, modeled financial results and the
compressed package remain unchanged. See the [extended data contract](data-contract.md).

This follow-up starts from updated `origin/main` at
`2bac4afbcbcf10833a7147686366a16f1204eb76` after PR #32 merged, in the retained
`D:/Project/Stock/.worktrees/strategy-presentation` checkout, on
`codex/studio-review-coverage-20261008`. It does not acquire data, run a backtest,
refit waves, modify original research missions/results or alter schedulers.

## Review decisions and behavior

| Concern                            | Result                                                                                                                                                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Missing dates hide capture answers | Any positive known holding date confirms participation; absence requires all nonempty holding dates known. Undetermined cycles remain separate.                                                         |
| Missing allocation dates           | Equal-date mean over complete dates only, with coverage and exclusions. Missing dates stay gaps in plots and retain account drill-down.                                                                 |
| Fair strategy comparison           | All strategies' allocation means use the intersection of complete dates inside the aligned NAV period; performance remains on the full common period.                                                   |
| Proportions look like returns      | Win rate, profit concentration and allocation fractions are unsigned neutral ratios. Actual returns remain signed.                                                                                      |
| Research history mixes purposes    | 38 method records, 3 market/classification records and 3 method-design/tool records. Existing 9 explicitly excluded infrastructure rows remain in the saved package. Search spans groups and originals. |
| Titles and internal copy           | 26 additional plain titles and concise source-grounded summaries. Formal outcome badges only; missing formal outcomes are unjudged. Draft/source details are expandable.                                |
| Strategy names and legends         | Friendly display names plus the saved study names; compact charts label strategy and 0050 price-only lines.                                                                                             |
| Dividend costs                     | Missing transaction-cost cells for dividend recognition/receipt display a dash; numeric values including zero remain visible. Missing trade costs remain unknown.                                       |
| Return distribution                | Saved closed-cycle returns use finer bands around zero, a separate exact-zero band, tails and explicit missing counts; original statistics are not changed.                                             |
| Home and handoff                   | Plain market entry wording; reviewer-facing handoff holds current results, while prior operational chronology is separately retained in `.tmp/claude-codex`.                                            |

## Live evidence

Read-only API on the task-owned localhost preview, using the existing pinned
daily catalog and original saved runs:

| Run                 | Closed cycles | Confirmed participated | Confirmed did not | Undetermined | Complete allocation days | Complete-date mean |
| ------------------- | ------------: | ---------------------: | ----------------: | -----------: | -----------------------: | -----------------: |
| Add retry           |           299 |                    168 |               129 |            2 |            1,183 / 1,216 |     15.4768450588% |
| Entry extension cap |           119 |                     38 |                80 |            1 |            1,197 / 1,216 |      4.7160565336% |

The comparison's shared complete subset contains 1,183 dates. Its means are
15.4768450588% and 4.7025892848% (the UI rounds to 15.5% and 4.7%). These are
conditional allocation means, not estimates of missing dates, account returns or
capture of whole waves. A positive partial holding interval proves participation,
not that every unknown day has the same membership.

## Verification and retained limits

- 265 targeted Python tests passed: partial positive/negative evidence, empty
  intervals, missing/nonfinite weights, loading/failed providers, immutable saved
  statistics/bytes, reversible history overlays, formal outcomes, invalid sections,
  report-title snapshot provenance/binding and Windows/CJK Git export paths.
- 335 frontend tests passed and the production build succeeded. A focused history
  regression also confirms that summary qualification sentences are not silently
  truncated. The existing large entry-chunk advisory remains.
- Browser verification and final PR delivery state are recorded in the current
  `.tmp/claude-codex/current-state-20261008.md` handoff.
- This does not fill unknown daily ranks, prove historical industry roles or
  manufacture missing portfolio membership. Draft wording and formal result
  registration still need research-owner confirmation. Studies whose saved
  discovery contains only a mission do not gain a result from unrelated nightly
  logs. Original summaries, source locators and formal outcomes remain accessible.

Hosted review additionally found that 18 legacy in-package display overlays could
survive metadata deletion. The reader now restores the baseline before applying
current metadata; future exports retain `originalTitle`. For the unchanged legacy
package, a separate Git-portable title snapshot records all 53 report/mission
headings at the base revision. These headings are explicitly not claimed as the
missing original export titles. All 53 source Git-blob digests and the exact saved
history fingerprint were independently checked. Changing or withdrawing an overlay
does not retain its former conclusion, section, draft judgement or review notice.

The publication record updates the presentation metadata receipt and adds the new
report-title snapshot. The binary package parts and transport manifest retain
their original hashes. New code has no authority to mark a strategy adopted or merged.
