# Opportunity explorer delivery

The Claude prototype has been implemented as a maintainable React feature in
`research_web`, with a shared browser/CLI comparison model and validated static
artifacts. The main routes are the opportunity map, saved research and ETF field
guide. The existing readers remain accessible. See
`docs/en/opportunity-presentation.md` for the data and visual contracts.

## Preserved evidence

- The sector-wave preview from commit `fac041c` contains eight historical and
  eight synthetic cases. The committed presentation selection uses only the
  eight historical cases, with explicit fixed wave/launch IDs. It is a review
  slice, not the full 2010-onward catalog or an accepted detector.
- The research chat supplied two native account reconstructions: normal-v1
  remains exploratory, cap-v1 remains failed. Each has 1,216 dated account states;
  all 2,432 reconcile with reported maximum difference zero TWD. The saved-run
  library preserves 736 + 281 original events, parameters and limitations.
- The exact hashes of the joined packages are in `export-receipt.json`. A physical
  producer preview is committed under `research_web/fixtures/`; compressed browser
  packages are under `research_web/public/data/`. No strategy was rerun and no
  historical mission/result or market cache was changed.

## Verification

Frontend tests: 108 passed (including annotation identity, case/catalog provenance, import boundaries and ledger accounting regressions). Production build passed; lint passed without warnings
after pure format helpers were separated from React components. Coverage includes
fixed area ratios, packing across 823 layouts, interval boundaries, incomplete
holdings, cash/claim allocation, cutoff censoring, adapter source hashes and
preservation of failed research verdicts. Hosted review found a same-ID custom-case annotation collision; feedback now uses the actual case-content SHA-256 plus rule version, with stale async results guarded and old entries retained.

The ledger exporter also requires the final daily state's event prefix to cover
every source event. A regression for both ledger types reproduces and rejects an
unaccounted trailing trade even when receipt counts and hashes agree. Re-exporting
the two real ledgers after this fix produced identical JSON and gzip hashes.

The map-to-detail adapter now selects the case and catalog sources by their
explicit IDs. Five regressions cover source ordering, custom bundles and missing
bindings. Browser inspection of Yang Ming confirmed both displayed hashes match
the package; absent historical hashes are labelled unknown rather than synthetic.

Packet identities must match a native source from the same verified ledger, not
an unrelated receipt entry or another run. Both real packages still reproduce
identical hashes. Empty-price imports retain their unknown directory rows and
disable detail navigation with a visible reason; this was confirmed through the
browser file chooser and restored to the historical source afterward. A single
price point remains safe under both methods and all three existing scales.
Unspecified source-hash algorithms receive a generic label.

Every daily event prefix must exactly match the source events at or before its
20:00 Asia/Taipei checkpoint. Regressions reject early/late inclusion, invalid or
unordered timestamps and other checkpoint times; equal-time events retain their
source order. Both real packages remain byte-identical after re-export.

Legacy-map quality checks now include the gain interval's first day. The
regression covers endpoint/peak returns and both area modes, while proving that
a finding before the interval does not invalidate it. Opportunity selection
retains both stock and wave IDs; it never silently substitutes another wave
after a date change. A browser import with multiple Yang Ming waves and no
representative confirmed that the second directory row opens its own start
(2021-02-01), peak (2021-05-10) and end (2021-05-14). The saved historical package
was restored after inspection.

Native browser checks on the local server covered date entry, three successive
forward/backward timeline drags, stock selection, date/gain evidence, entry into
and return from the wave detail page, multiple comparisons, ETF unknowns, pins,
NAV cursor, trade search/action filter and original event inspection. Light/dark
and alternate color theme changes were inspected at desktop and 390px viewport.
Viewport overrides were restored. A mobile-only 7px decorative overflow was corrected and rechecked (375px page / 375px content viewport). Review JSON was displayed and parsed from the
UI. The in-app download event did not return a local download path, so saving a
browser download to disk is not counted as verified.

At 2021-04-29, browser and shared CLI both report six active historical cases;
normal-v1 holds one. Known capital in those cases is 8.5902030091%; other stocks
outside the slice remain unclassified, not falsely counted as missed/ordinary
stocks. Mean positive-return overlap is 9.0469375720%, and Yang Ming's is
54.2816254323%. These are date-overlap diagnostics, not investment returns.

The interval sweep reduced the two real comparisons from 82.99ms to 2.45ms
(seven-run median after warm-up, six active cases, 2021-04-29). Before/after
comparison output was identical. This is a model timing, not a measured browser
frame-rate guarantee.

## Remaining research scope

Full historical holdings for ETFs, reliable dated market caps, historical
industry evidence and an approved lifecycle phase mapping remain unavailable.
Unknowns stay visible. Rich colored interactions can be inspected separately in
the explicitly synthetic mode. The full catalog's 2010–2012 adjustment checks,
official-first source policy, delisting/universe coverage and evidence queue
remain with the sector-wave workstream. Completion of this UI does not complete
that queue or authorize full recomputation.

The research workstream identified signal-to-proposal-to-execution delay and
capital priority between new probes and additions as future hypotheses. No new
test was run; evaluation requires a separate preregistered mission. The new CLI
provides the same descriptive comparisons used by the website.
