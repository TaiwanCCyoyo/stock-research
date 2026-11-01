# Dashboard UX and report readability delivery

## Decision and purpose

Owner discussion: 2026-11-02 (Asia/Taipei). The owner accepts the audit direction,
wants the discussion and PR rationale recorded, and intends to assess the finished
experience rather than supervise implementation details. This record prepares
the implementation slices; it does not claim they are already implemented or
that planned PRs have been opened. Merge remains with the owner. Normal checks,
current-head review and applicable visual-acceptance holds remain in force.

The dashboard currently makes it difficult to distinguish the original research
question, what was actually evaluated, what was answered, and what later studies
changed. The owner cannot reliably use the report collection to discuss the next
research direction. This is both an information-design problem and, in some
reports, a substantive wording problem. Reformatting alone is insufficient.

The intended experience is a clear default report collection, with explicit
access to work in progress and historical material. Research with negative
results belongs in the default collection when it is readable and supported.
Readiness is independent of research success, execution progress and provenance.

### Ownership and boundaries

- Codex owns the whole-dashboard UX work and other legacy report reading editions.
- Another Claude session owns the current PR113 strength-weakening report and
  PR17/pattern-scan report revision. It is also considering a research-direction
  draft interface and links to earlier research. Do not independently build that
  draft interface or rewrite its owned reports. The owner will relay coordination
  if needed; do not send messages to that session without authorization.
- Existing report navigation can be improved, but shared lineage/draft metadata
  needs coordination with Claude's proposal before introducing a competing model.
- No research execution, data refresh, producer changes, input snapshots,
  scheduler changes, predecessor-checkout access, or historical-data deletion is
  part of this effort. Do not stop or repurpose other sessions' previews.
- Keep frozen evidence and result bytes/pins intact. New reading editions cite
  existing evidence; source gaps remain explicit. No mass rehashing, intermediate
  manifests, source sealing or research reruns to make prose editable. Follow
  [artifact integrity](../artifact-integrity.md): new reports/prose use Git.
- Before changing a legacy report, identify whether it is pinned. Prefer a new
  reading edition if editing it would invalidate retained evidence. Do not hide a
  real result change inside a presentation update. An unresolved numerical
  contradiction requires a disclosed correction or a pending status, not a guess.

## Proposed delivery: eight PRs total

P0 is [PR #136](https://github.com/TaiwanCCyoyo/stock-research/pull/136), merged at
`f005d8ce`. All eight planned PRs now exist. Current-head checks and review remain
authoritative on GitHub; implementation and editorial readiness are not owner
acceptance.

| Slice | Delivery                                                         | Current handoff                                                                |
| ----- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| P0    | [PR136](https://github.com/TaiwanCCyoyo/stock-research/pull/136) | Merged: decisions and PR rationale requirements                                |
| P1    | [PR142](https://github.com/TaiwanCCyoyo/stock-research/pull/142) | Reading API, visibility, Markdown and return context; SSR review fix delivered |
| P2    | [PR139](https://github.com/TaiwanCCyoyo/stock-research/pull/139) | Shell/home; browser focus-loop follow-up delivered                             |
| P3    | [PR140](https://github.com/TaiwanCCyoyo/stock-research/pull/140) | Data/stock; complete versions available on demand                              |
| P4    | [PR141](https://github.com/TaiwanCCyoyo/stock-research/pull/141) | Map/ETF/account interactions                                                   |
| P5    | [PR145](https://github.com/TaiwanCCyoyo/stock-research/pull/145) | 15 reading editions: 12 ready, 3 history pending source contradictions         |
| P6    | [PR143](https://github.com/TaiwanCCyoyo/stock-research/pull/143) | 17 reading editions, corrected interpretation and explicit period gaps         |
| P7    | [PR144](https://github.com/TaiwanCCyoyo/stock-research/pull/144) | 20 reading editions including completion-v2 and HHHL corrections               |

P5-P7 depend on P1. They were opened against its branch, but normal CI only runs
for PRs targeting main. Their delivery base therefore becomes main after bringing
in the P1 review fix; the parent diff remains visible until P1 merges. Review the
batch commits separately, and do not merge around the dependency or owner hold.
All report PRs retain the owner's final reading/acceptance hold.

Content review checked all 52 editions independently against declared sources.
It corrected a partial signal gate mistaken for overall passage, ambiguous
contribution denominators and baseline amounts, and clarified later corrections.
Three early editions remain history (smoke, ranking-horizon, runner-retention);
they are readable but their unresolved source differences are not a ready result.
The three original missing-source tasks remain history without reconstruction.

These are delivery identifiers, not GitHub PR numbers. Split further only when a
slice cannot be reviewed or accepted coherently; update this record with the
reason and actual count. The initial budget was five worktrees. This session
reported a temporary increase to seven before creating the last two batches:
three UI PRs still needed their review/preview checkouts, P1 needed its reader
checkout and P6 reused P0's checkout. P5 and P7 needed isolated writers while
those reviews continued. No unrelated worktree was removed to meet the budget.

| ID  | Proposed PR                                            | Reader-visible result and scope                                                                                                                                                                                                                           | Dependency                                     | State                   |
| --- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----------------------- |
| P0  | Record UX decisions and require useful PR descriptions | This record, AGENTS pointer, workflow guidance and PR template                                                                                                                                                                                            | None                                           | Prepared in this branch |
| P1  | Make report readiness and reading access explicit      | Default readable reports; separate in-progress and historical/pending lists; clear reason for exclusion; Markdown reading entry; question/answer/limitations, periods, truthful dates and return context; heterogeneous metrics cease sharing a bar scale | P0; coordinate shared metadata with Claude     | Planned                 |
| P2  | Repair dashboard navigation and home semantics         | Skip link, theme focus behavior, mobile navigation, correct stock entry, historical-market wording, useful empty/error states                                                                                                                             | P0                                             | Planned                 |
| P3  | Clarify datasets, coverage and stock views             | Distinguishable dataset versions and source links, explicit count scopes and snapshot dates, stock page hierarchy, price-basis explanations, human-readable quality labels                                                                                | P0                                             | Planned                 |
| P4  | Make map, ETF and account comparisons operable         | Named holding badges, selection semantics, ETF search/selection and basket removal, keyboard-accessible chart values and retry without losing selections                                                                                                  | P0; avoid concurrent shared-shell writes       | Planned                 |
| P5  | Publish May-August legacy reading editions             | Early pattern/stop/ranking/turnover research, with question coverage and bounded conclusions                                                                                                                                                              | P1                                             | Planned                 |
| P6  | Reconcile September candidate and execution reports    | Baseline-to-confirmation-to-executable-fill sequence, corrected risk wording and current interpretation without overwriting historical verdicts                                                                                                           | P1; highest report-content priority            | Planned                 |
| P7  | Publish remaining October reading editions             | Entry/exit diagnostics, descriptive datasets, environment/HHHL studies and three existing reading pages; explicit unanswered questions                                                                                                                    | P1; wait for relevant Claude report interfaces | Planned                 |

P2-P4 may proceed independently with assigned file ownership. P6 should precede
other report batches because its contradictions most directly affect decisions.
Treat a research series as one acceptance unit even across calendar batches; the
calendar grouping is scheduling, not permission to separate a result from its
later correction. If P4 requires a shared-chart architectural change rather than
local interaction repairs, split that change into its own PR.
Each report PR must include a per-report disposition list; a batch that is too
large for meaningful review must be split and the total updated here. Publication
is incremental, so completed editions can become visible before every old report
has been rewritten. A planned task is not a completed report.

## Report collection policy

The proposed primary entry is **Reports**, showing only editions that meet the
reading acceptance criteria below. **In progress** contains planning, execution,
revision and pending acceptance. **History and pending cleanup** retains source
gaps, unreviewed editions and unresolved contradictions, searchable by known task
name/ID with an explicit reason and a way to restore visibility after acceptance.
These are reversible presentation states, never deletion or research verdicts.

Do not infer readiness from HTML existence, a passing hash, a positive result or
an execution-complete flag. No existing complete-source report has been judged
impossible to present clearly. The three missing-source tasks below cannot be
turned into substantiated results with the evidence currently available.

### Complete research inventory at audit time

Primary checkout audit baseline: `659b846` on 2026-11-02. The planning branch starts
from fetched `origin/main` `d12ebd9f`. The audit counted 82 dated task cards: 61
research and 21 tooling. Of the research cards, 49 lack a data period and 44 lack
key numbers; these counts identify review needs, not a requirement to invent
numbers or declare every card defective. Four task web reports exist on that
baseline. Live PR17 preview already contains newer report content than main.

| Disposition                             | Count | Tasks                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| --------------------------------------- | ----: | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude-owned report revisions           |     2 | `20261013-pattern-scan`, `20261024-strength-weakening-flags`                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Planning, not result rewriting          |     4 | `20260814-2b-false-break-structure`, `20261024-tenbagger-drivers`, `20261027-entry-window`, `20261027-multi-timeframe-ma`                                                                                                                                                                                                                                                                                                                                                                    |
| Missing source; history only            |     3 | `20260921-evening-pilot`, `20261002-momentum-probe`, `20261002-small-probe`                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Existing web reports, P7                |     3 | `20261012-hhhl-v4-variants`, `20261013-annual-winner-rotation`, `20261021-momentum-only-doubling`                                                                                                                                                                                                                                                                                                                                                                                            |
| Descriptive/data/literature outputs, P7 |     4 | `20261002-sector-wave-catalog`, `20261004-feature-discrimination-atlas`, `20261004-method-environment-map`, `20261004-sector-wave-full-history-preview`                                                                                                                                                                                                                                                                                                                                      |
| Legacy result editions, P5              |    15 | `20260510-two-b-template-smoke`, `20260812-loop-explore-v2`, `20260816-kline-strategy-category-fit`, `20260820-kline-archetype-extension`, `20260821-2b-entry-decomposition`, `20260821-stop-mechanism-isolation`, `20260822-ratchet-generalization`, `20260823-rank-profile`, `20260823-regime-overlay`, `20260823-selection-vs-random`, `20260823-turnover-mechanism`, `20260824-ranking-horizon`, `20260824-value-chain-ignition`, `20260826-runner-retention`, `20260826-tail-selection` |
| Legacy result editions, P6              |    17 | `20260903-entry-window`, `20260904-book-size`, `20260904-execution-delay`, `20260904-swap-rule`, `20260905-add-trigger`, `20260905-min-hold`, `20260905-weekly-structure`, `20260905-wide-giveback`, `20260906-absolute-entry-bar`, `20260906-equal-risk-sizing`, `20260906-exchange-rate`, `20260906-execution-reality`, `20260906-five-slot-baseline`, `20260906-five-slot-confirmation`, `20260906-loss-anatomy`, `20260906-three-slot-equal-risk`, `20260908-executable-fills`           |
| Legacy result editions, P7              |    13 | `20261002-add-retry`, `20261002-add-stage-diagnostic`, `20261002-catalog-participation`, `20261002-entry-extension-cap`, `20261002-entry-persistence`, `20261002-failed-confirmation-exit`, `20261002-one-lot-delay-resumption`, `20261002-pool-breadth-admission`, `20261002-weekly-rank-exit`, `20261005-industry-role-comparison`, `20261005-method-environment-interactions`, `20261009-hhhl-pattern-probability`, `20261010-hhhl-v4-probability`                                        |

The 21 tooling cards remain engineering records, outside report rewriting. Never
turn `small-probe` into an automatic reconstruction backlog. Current work may
advance after this snapshot; recheck the specific task before assigning a writer.

## Audit findings and implementation acceptance

Severity distinguishes defects from preferences; priority is driven by the
owner's ability to understand and discuss research. No CRITICAL finding was
established. Static findings are not claims of completed browser validation.

### P1: reading and classification (MEDIUM)

- `StudiesPage.tsx` uses abstract copy and mixes unfinished, negative and
  unverifiable material. Use a concrete heading and separate readiness/progress/
  outcome/source status. `study_cards.py` currently warns about missing sources
  even when a report has simply not been produced.
- `v2.ts` retains answer/verdict on a report hash mismatch; explain content-review
  state rather than either silently trusting it or treating every mismatch as
  invalid science. Preserve legacy checks without expanding them to new prose.
- `StudyCardView.tsx` omits periods, displays Markdown paths without reading
  links, and uses one bar scale for different units. `studies.css` clips answers
  without expansion and the home variant hides limitations.
- Task creation dates masquerade as latest updates. Hidden records show only a
  count (nine in the observed preview). Generic duplicate questions, search that
  omits IDs, and loss of filter/scroll context on return obstruct discussion.
- `ReportViewer.tsx` needs distinct loading/not-found/service-failure recovery.
  Keep report access usable without inventing missing source material.
- Accept with ready/in-progress/history examples, a negative readable result,
  a missing-source record, a source-mismatch record, search by ID, Markdown read
  and return, empty/error handling and an accessible mixed-unit metrics display.
  Apply the visibility policy consistently to the homepage and search; direct
  links to pending/history items retain their status, reason and original source.

### P2: shell and home (MEDIUM; minor layout/empty states LOW)

- `Studio.tsx` skip link changes the hash and routes to home; theme overlay lacks
  complete focus handling. Mobile navigation has four items in five CSS columns.
- `HomePage.tsx` labels retrospective data as currently rising and sends its
  stock entry to the dataset tab; empty research/market sections need meaning.
- Accept via keyboard-only navigation, focus restoration, desktop and narrow
  viewport checks, correct stock destination and dated retrospective wording.

### P3: datasets and stock detail (MEDIUM; headings/loading semantics LOW)

- Dataset cards can have identical titles without visible version distinctions;
  the live preview showed three annual-winner delivery cards. Catalog guidance
  points to source research without a link. Counts need population/unit context
  instead of implying every instrument code is an ordinary stock.
- Coverage list counts use different scopes without sufficiently local labels.
  It lacks a heading; indeterminate loading is exposed as zero-percent progress.
- Live stock 1240 showed coverage through October 22 and a chart through October
  30 without a local freshness explanation. It also showed a known name above a
  numeric-only chart with name-retry text, duplicate top-level headings and raw
  `missing_official_quote`. Preserve identity protections and unknown-vs-zero.
- `SharedDataPage.tsx` needs price-basis explanations and unambiguous indicator
  availability messages. Do not change price definitions to simplify the UI.
- Accept dataset-to-source and stock-filter-detail-return flows, version and
  freshness explanations, unknown identity, partial coverage, empty/error states,
  and keyboard/narrow-viewport readability using existing safe reader paths.

### P4: map, ETF and account interaction (MEDIUM; minor semantics LOW)

- `HistoryRanking.tsx` needs strategy names beside holding states, not color
  alone, and an accessible selected state. Keep the map's existing historical
  warning, date controls, keyboard map interaction and reduced-motion behavior.
- `FundsPage.tsx`: a search with no matches still shows the prior 0050 details
  without identifying the retained selection (browser-confirmed). The basket
  needs direct removal; mobile selection-to-detail navigation needs acceptance.
- `StrategyCharts.tsx` comparison values rely on hover with no keyboard date
  control in this mode. `StrategyComparePage.tsx` needs retry preserving the
  selected accounts; account loading/error states need appropriate announcements.
- Accept multi-strategy state identification without color, ETF empty search and
  basket removal, keyboard/touch-equivalent chart reading and failed-fetch retry.
  Preserve common-period alignment, cost/dividend limitations and missing data.

### P5-P7: report content

- HIGH: `20260906-five-slot-baseline/report.md` says capital never fell below its
  initial value while showing initial TWD 2m and minimum TWD 1.84m; it also turns
  average loss into an assertion about every loss. Correct the reader edition
  with cited evidence, not a cosmetic paraphrase.
- HIGH: baseline's promising/waiting-for-confirmation summary does not expose
  the subsequent failed confirmation and executable-fill limitation. Keep the
  historical verdict and show the later interpretation and source links.
- MEDIUM: feature-atlas has descriptive comparisons but its card says only data
  organization/not evaluated. Momentum explicitly leaves the incremental pattern
  contribution unanswered; its reading summary must retain that scope gap.
- MEDIUM: titles such as closing an entire research direction or dismissing the
  owner's concern overgeneralize a fixed configuration or random missed-day
  experiment. State the tested population, comparison and remaining question.
- MEDIUM: receipt-first reports, legacy summaries substituted for full results,
  and ambiguous demo labels impede reading. Distinguish real-result presentation
  examples from synthetic data, and descriptive events from simulated accounts.
- LOW: remove chat-dependent titles and unexplained metaphors from reading
  editions. Preserve uncertainty rather than inventing a decisive conclusion.

Every accepted reading edition must show: original question; actual comparison;
answer with its period, denominator/baseline and relevant assumptions; unanswered
parts; what decision the evidence supports; material later corrections; and a
working path to original evidence. These are content criteria, not a requirement
to impose the same chart on every study. A clear partial or negative result can
pass. Source-insufficient records cannot be promoted by polished prose.
Record each report's source, question coverage, disposition and acceptance in the
batch PR. Check every headline number, comparison, period and denominator against
the cited existing source without rerunning research. Recheck Claude-owned final
merged content at handoff instead of relying on today's preview snapshot.

## Verification and handoff

The audit read all dated cards and existing report openings, with deeper mission
comparison for the concrete findings above; it was not a numerical re-audit of
every study. Browser observations used the PR17 development preview at port 20002.
Its report already improves Q1-Q6 answers, denominator explanations and lineage.
Fresh connections to formal port 5177 and PR113 port 20000 failed during the audit;
open tab snapshots are not proof of currently served versions. Market loaded
progress but its complete interaction was not accepted. All-theme contrast,
narrow-screen layout, long-report printing and account interactions remain
implementation acceptance work. Do not report these as completed tests.

Run normal hooks and relevant CI; use focused tests for behavioral defects and
browser validation for reader-facing flows. If a change affects evidence readers,
follow the before/after published-artifact verification requirement. Do not run
market research as a UI test. An independent reviewer checks current-head scope,
wording and evidence preservation; the implementing agent handles valid findings
and hosted review follow-through. Owner assesses the integrated finished preview
and retains merge authority. No particular review service or setting is added by
the owner's phrase “dot review”; use the configured review workflow unless clarified.

Each PR body records why it exists, the chosen change, its P-number and dependency,
what the reader can now do, actual verification, and remaining limitations. Link
it here after creation. Do not claim all past PRs met this standard: recent PRs
include both clear problem/solution narratives and change-list-heavy descriptions.
Do not retroactively rewrite other sessions' or merged PRs as part of this work.

Session-owned checkouts retained for their open PRs and previews:
`report-reading-readiness` (P1), `dashboard-shell-ux` (P2), `dashboard-data-ux`
(P3), `dashboard-interaction-ux` (P4), `legacy-early-reading` (P5),
`dashboard-ux-delivery-plan` reused on `codex/legacy-september-reading` (P6),
and `legacy-october-reading` (P7), all under primary `.worktrees/`.
No session-owned checkout has been removed; the old P0 branch is retained while
its checkout serves P6. Other inventoried worktrees remain untouched. Cleanup
requires verified owner merge and the normal preservation/process/data gates.
