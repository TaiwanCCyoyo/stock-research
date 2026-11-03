# Saved condition comparison integration

This is a presentation slice for UX-10/11/12, not a research result or a second
persisted comparison schema. The research line owns the formal L1 data contract.
No market inputs are read and no statistics or outcome labels are computed here.

Mount `ConditionComparison` in the study detail owned by the navigation line.
Supply `ReadState` and persist `Selection` in that caller. On return, restore the
same selection with the same immutable result ID. A changed result ID resets the
selection; changing a horizon/group/filter should reset the page and case.
The source's result ID must identify the same snapshot as the view ID.

`adaptSavedComparison(saved, producerAdapter)` accepts an injected adapter; map
the producer's saved eligible hit/known denominator, stock counts, unknown and
censored counts for each horizon into the view. Missing values stay missing.
Do not derive summary counts from the case list or subtract rates. Supply all A,
each B and the producer's disjoint A\\B summaries. Preserve effective event labels
from `research_core/pattern_scan_event_outcomes_v1.py`, eligibility and reasons;
never fall back to the base label. `not-hit` is a display filter over `loss` and
`flat-win`, not a new research outcome. H126 and H252 are separate records.

`onOpenCase(CaseRequest)` carries the opaque reader reference, event identity,
date, horizon, source/input/settings/price-basis context and exact return selection.
Only provide `readerRef` when a real reader exists. No callback means no fake link.
The host must store the return selection before navigation and restore focus to
the selected case's button after return. This component does not own routing.

`onDiscuss(QuestionRequest)` carries the question and same context with literal
`intent: "discussion-only"`; this is not research approval or a computation request.
The host owns loading, request cancellation and matching responses to result IDs.
Render loading while switching saved snapshots; never relabel old data as new.

Local preview: run `npm run dev` in `research_web`, then open
`/condition-comparison-preview.html`. It is a Vite development entry only, not an
app route or production build entry. Every fixture is explicitly synthetic. The
synthetic reader tests navigation callbacks and is not a functioning stock reader.

Verification: `node --experimental-strip-types --test
src/features/condition-comparison/model.test.ts scripts/condition-comparison.test.mjs`.
Component SSR checks do not establish browser usability, keyboard operation or
actual narrow-screen rendering. Those require browser verification and eventual
user acceptance after the navigation and formal research adapters are connected.

Browser verification (Edge, 2026-11-03): Enter activated next-page and case-reader
buttons; returning preserved page 2 and `demo-01`; rapid H252/H126/H252 changes
displayed the final window's denominator. A 375 × 812 viewport produced a single
column (DOM client/scroll width both 360px, no horizontal overflow). Discussion
callback included source/settings, H252 and `discussion-only`. These are synthetic
functional checks, not owner usability acceptance. Host focus restoration and
real-data adapter integration remain to be verified end to end.

Local checks: 5 focused tests, TypeScript build checking and scoped oxlint passed.
The full frontend run had 564/565 passing; its sole failure was a sandbox EPERM
while the existing report test created a synthetic directory link. The approved
focused rerun passed all 6 report tests with directory-junction coverage; that
test explicitly reported file symlinks unavailable on this Windows host.

Approved Library input: `libfile_c2578f2e75bc8191b5b9dac04f555d70`, version 1.
The official materialization helper failed to download in this executor; the
parent's detailed UX-10/11/12 instructions are the implementation input for now.
Document alignment and real-data integration remain pending; no usability
acceptance is claimed by this synthetic slice.
