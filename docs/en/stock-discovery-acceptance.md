# Stock discovery frontend acceptance — 2026-10-24

PR-B was integrated on `cf3b4ac` and uses PR-A's `security-coverage.v1` API.
Deploy the API and maintained summary first. This record contains synthetic
browser evidence only; no private presentation or market-source file was
included in screenshots or public build assets.

## Observed behavior

| Case                              | Evidence                                                                                                                                                                                 |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Discover without a stock code     | Data overview's 股票 tab opened the list; stock names opened opaque-key detail routes.                                                                                                   |
| Header search                     | Searching 月營收示範 returned the matching fictional security across the full filtered set.                                                                                              |
| Cell navigation                   | Institutional/revenue cells opened detail with `dataset=` and scrolled to the card containing the actual viewer.                                                                         |
| Known history gap and new listing | DEMO showed the partial icon; NEW23 did not inherit the pre-listing gap. Reasons are expandable.                                                                                         |
| No price but revenue available    | REVENUE had no price viewer, yet its independent revenue section displayed 2026-09 / 123 thousand TWD.                                                                                   |
| Identity ambiguity                | Legacy X123 showed two bounded candidates. The old segment had no latest company name; code-only viewers remained gated.                                                                 |
| Legacy resolution                 | DEMO's unique partial-summary candidate redirected; X123 offered a choice; NOFIXTURE999 showed an explicit no-match state.                                                               |
| Summary absent                    | A synthetic-only fault server returned unavailable; the list showed a clear notice/retry, not confirmed-missing counts.                                                                  |
| One source read fails             | One injected institutional HTTP 503 left other cards visible; its retry restored the synthetic 2020-01-02 / 123 row.                                                                     |
| Return state                      | At 800 × 1000, page 2 and all query filters survived four native Back cycles and the explicit return link, together with outer scrollY 283 and matrix scrollTop 2797 / scrollLeft 33.    |
| Expired identity                  | A detail HTTP 404 states that the stock identity is absent from the current summary and offers the list return link; transient read failures retain their independent retry.             |
| Counts and instrument kinds       | Filters use server totals before pagination; ETF is an explicit independent kind and is excluded by the ordinary-share default. Confirmed-delisted and unresolved counts remain visible. |

The ordinary default is labelled recent observations, not confirmed listed.
After PR-A's source-frequency review fix, the revenue-only fixture also appears
in that default view. The four matrix/list screenshots were refreshed against
the corrected API; month-only observations are not compared to daily strings.
There is no reliable live delisting evidence in the present source contract;
retention of explicitly confirmed delisted records was checked with synthetic
data. Unknown, zero rows and confirmed absence remain different meanings.

The implementation reuses the existing cards, chips, InfoTip, CaveatChip,
SkeletonCards and ProgressLine. No FullHistoryPage, OpportunityMap, useHistory or
panelPolicy file was changed; their old links are handled by compatible routes.

## Verification

- Full frontend test run: 506 passed, including two scroll scheduling regressions.
  The earlier full run had
  502 passes and one Windows symlink-permission failure; the same normal suite
  passed after formal permission escalation. No check was disabled.
- Independent integration acceptance exposed a timing-sensitive return failure
  missed by the initial outer-scroll-zero check. Restoration now snapshots both
  offsets before installing listeners, separates window and matrix writes, gates
  restoration events through the next paint and ignores detached/replaced nodes.
  The stronger browser case above used the real local-private production client
  against a wholly fictional same-origin API fixture; no private roots were read.
- TypeScript and the normal production build passed. Focused Oxlint passed on
  the final route, shell and coverage files. Normal commit hooks passed.
- Build publication initially hit a Windows directory-handle conflict while
  this task's Vite dev watcher was active. Stopping that task-owned preview and
  rerunning the normal build succeeded; existing website services were untouched.
- The production frontend was served through the existing FastAPI frontend mount
  with same-origin API routes for browser acceptance. A Vite preview without API
  proxying was not treated as a successful end-to-end check.
- All eight palettes were switched through their UI in light and dark modes.
  Five glyphs and their text labels remained distinct. Computed glyph contrast
  against each palette's paper and surface was at least 4.14:1; color is supported
  by shapes, visible legend text and accessible labels.

## Screenshots

Desktop viewport 1440 × 1000; phone viewport 390 × 844. Phone overview/list images
capture the full page; detail images show the selected data card. Each image is
fictional data from the synthetic build, never a private-data screenshot.

| Combination           | Overview                                                                | Stocks                                                              | Detail                                                                    |
| --------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Phone, sakura light   | [overview](../assets/security-coverage/mobile-sakura-overview.jpg)      | [list](../assets/security-coverage/mobile-sakura-stocks.jpg)        | [institutional](../assets/security-coverage/mobile-sakura-detail.jpg)     |
| Desktop, sakura light | [overview](../assets/security-coverage/desktop-sakura-overview.jpg)     | [matrix](../assets/security-coverage/desktop-sakura-stocks.jpg)     | [institutional](../assets/security-coverage/desktop-sakura-detail.jpg)    |
| Phone, ocean dark     | [overview](../assets/security-coverage/mobile-ocean-dark-overview.jpg)  | [list](../assets/security-coverage/mobile-ocean-dark-stocks.jpg)    | [revenue only](../assets/security-coverage/mobile-ocean-dark-detail.jpg)  |
| Desktop, ocean dark   | [overview](../assets/security-coverage/desktop-ocean-dark-overview.jpg) | [matrix](../assets/security-coverage/desktop-ocean-dark-stocks.jpg) | [revenue only](../assets/security-coverage/desktop-ocean-dark-detail.jpg) |

Task-local browser diagnostics are in `.worktrees/stock-browser/.tmp/`:
`coverage-theme-contrast.json`, `coverage-browser-fault-evidence.json` and
`coverage-browser-scroll.json` and `coverage-browser-regression/after-fix.json`.
The screenshot set and this record are the
durable evidence. Claude's separate visual review has not been substituted by
the implementing agent's acceptance checks.
