# Mission: preserve the owner's HH/HL labels

Owner decision 2026-10-08: item 1 of the research-data architecture first batch, executed by
Claude because only Claude can read the labelling pages' databases.

## Scope

- Re-export every labelling page database and compare with the earlier local dumps.
- Store the documents verbatim, together with what was shown, the blind `kind` mapping,
  and the preregistrations and results.
- Make every published batch 2-5 number recomputable from Git-tracked files alone.

## Not in scope

- No new labelling, scoring rule or rule version.
- No market computation beyond re-running the frozen rule versions on the labelled charts,
  which is needed to record the rule days already used by the published scores.
- No change to the published results.

## Done when

`recompute.py --check` reproduces every number in `batch2..5-result.md`, and the archive is indexed
from `docs/en/research-program.md`.
