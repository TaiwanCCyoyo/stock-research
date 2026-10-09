## Context

The owner authorized publication/readiness work and 0050 context generation, not a strategy restart. Existing atlas-v2 remains frozen. A separate descriptive catalog contains a hash-pinned 0050 series but deliberately did not analyze it as a stock opportunity.

## Goals / Non-Goals

**Goals:** expose preserved evidence through the shared research index; supply a portable, versioned benchmark context with a reader; demonstrate an independent consumer can read it.

**Non-Goals:** new trading rules, performance comparisons, source acquisition, existing-result replacement, a dashboard page, infrastructure framework, new automation or final market-regime validation.

## Decisions

1. Reuse the fixed catalog-v2 0050 series and calendar, validating descriptor byte hashes and symbol/calendar identities before generating an independent task. Physically retain the consumed input bytes. Do not depend on its still-evolving stock-wave analyzer.
2. Separate daily state from entry events. State is `up`, `down`, `consolidation`, `mixed` or `unknown`; events are provisional `launch` / `resumption` candidates. Mixed is not consolidation. Exact first-version rules are fixed in the new mission before output is calculated; one definition, no tuning or stock-return evaluation.
3. Publish two files: past-only trailing observations, and retrospective centered-window labels with future-information cutoff. Never join the second as a trading feature. Both are conditional on a restated historical source snapshot, not proof of historical publication timestamps or total return.
4. Use a small Git-portable dataset for one benchmark and portable atlas aggregate evidence, while leaving existing large per-stock files immutable in their known physical locations. The handoff manifest distinguishes portable data from local-only bulk evidence and records actual consumer status.
5. Integrate the atlas branch without rewriting sealed commits or parameter packets. New publication metadata can refer to old artifacts; no new winner/loser experiment is performed.

## Risks / Trade-offs

- Arbitrary descriptive thresholds could be mistaken for optimal signals → mark the single fixed rules provisional, retain continuous measurements, and prohibit profitability claims.
- Restated prices and centered windows could leak hindsight → label source vintage, computation timing, required future date and historical availability uncertainty separately; test prefix invariance for past-only output.
- Worktree cleanup could lose ignored artifacts → preserve existing root duplicate, publish exact locators and small portable evidence; do not claim offsite backup.
- Consumer schema drift → supply one reader, enforce identities/hashes, and obtain a read-only downstream smoke result; no independent metric recomputation in the UI.

## Migration Plan

Add new artifacts and indexes only, deliver through a Stock PR, and leave old tasks/inputs untouched. Consumers opt into the new dataset identity. Rollback means stop referencing the new dataset, not delete historic evidence.

## Open Questions

No owner decision blocks this bounded first descriptive version. Final loss budgets, profitable strategy rules, historical PIT reconstruction and full bulk offsite storage remain outside this task.
