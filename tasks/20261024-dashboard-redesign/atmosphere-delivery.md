# Theme atmosphere, stock focus and map playback

## Owner request and scope

Follow-up to merged C1+C2 (#72): remove the theme explanatory sentence, improve
visual hierarchy and artistic atmosphere, and investigate history-map stuttering.
The owner clarified that a black chart is an optional design direction, not a
requirement. This follow-up explicitly includes the app shell and map rendering.

Built from `origin/main` `07b666c`, on `codex/dashboard-atmosphere`. Reuses this
session's clean `D:/Project/stock-research/.worktrees/dashboard-restyle` checkout
and existing preview. The old PR branch is not extended. No new worktree.

## Presentation

- Removed the requested sentence without replacement copy.
- Original canvas scenery: sakura branches and curled translucent petals, forest
  leaves and fireflies, ocean contours and rising light, plum stars, sand contours
  and dust, soda bubbles, sunset contours and warm light, restrained ink contours.
  Sakura uses an asymmetric notched outline, gradient and vein, depth-dependent
  scale/opacity, flutter and slow shared wind. These are original procedural
  decorations, not assets copied from the referenced video or a photorealistic town.
- Cached particle sprites, static scenery drawn only on resize, bounded particle
  counts and a 30 Hz motion cap. Hidden tabs stop animation; reduced-motion keeps
  only still scenery; the existing background-animation switch removes the layer.
- Individual stock uses a neutral graphite stage as a deliberate focal surface,
  distinct from the decorative page palette. Larger quote, compact title/search/
  basis controls, restrained grid, separate indicator hues and flatter sidebar.
  All prices, indicators, missing-data semantics and overlays are unchanged.

## Playback

- Bounded 24-frame LRU, keyed by catalog and date, with two-frame lookahead and
  shared in-flight promises. Validation precedes cache publication; seek, pause
  and route exit cancel obsolete requests. Cached frames do not skip dates.
- Closed complete table no longer mounts or sorts hidden rows. Map and timeline
  memoization removes unrelated renders; geometry reads precede animation writes.
- Worker results publish one frame instead of an intermediate duplicate SVG
  render. Stock morph starts on the first animation frame, so a React commit
  cannot consume its duration before paint. Existing 260 ms duration is retained.
- Focusing/editing the date pauses playback and protects the draft from the
  automatic date sync; submit still normalizes to a trading day.

## Verification and evidence limits

- Frontend: 445 tests passed, including 8 new cache/cancellation/identity tests.
  TypeScript and staged Vite builds passed. Lint has zero errors and five existing
  hooks warnings. Normal commit hooks and hosted checks remain delivery gates.
- 32 visual cases: eight palettes, light/dark and 375/1440 widths; no document
  horizontal overflow or browser exception. Sakura also verified dynamic canvas,
  runtime reduced-motion change and the off switch. Local screenshots remain
  private in `.tmp/atmosphere-qa/`; they are not published to the public repository.
- Browser interaction checks: complete-table mount/search/unmount, pause stability,
  editing a date during playback, two delayed frame responses followed by a seek,
  and stopping at the final date. No browser exceptions.
- Local 12-second developer-build samples (1440 x 1000, from 2021-01-04): initial
  20,238 DOM nodes / 1,319 hidden table rows; after 4,004 nodes / zero table rows.
  rAF p95 was 366.7 ms before and 283.3 ms after with atmosphere off. These are
  exploratory samples, not a stable FPS guarantee or a same-frame work comparison.
- Separate production-build samples used the same API and initial date. Before:
  11 frame responses / p95 99.9 ms; after: 17 responses / p95 116.8 ms. The after
  count includes lookahead, and different playback progress means different maps.
  They establish reduced serial waiting, not improved p95 or consistent 60 FPS.
  Large SVG frames still show long tasks. A filter-free A/B did not improve the
  measurement, so the existing map shadows are retained.
- Baseline production source was loaded from `07b666c` for just the five changed
  playback components into an ignored staged build, without changing the checkout
  or copying research data. Diagnostics: `.tmp/playback-*.json`,
  `.tmp/playback.cpuprofile`, `.tmp/playback-functional.json`.

## Retention

The task checkout and its existing localhost preview are retained for owner visual
acceptance and PR follow-through. No owner service, data, scheduler or other
session's checkout was changed. Temporary production comparison servers are
task-owned and may be stopped after verification; their builds remain ignored.
