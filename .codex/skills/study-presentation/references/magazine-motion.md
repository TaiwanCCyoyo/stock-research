# Magazine layout and motion for reports

Use when a report reads as a wall of text and cards, or when the finding is a
comparison, a sequence or a proportion that a visual can carry. The page is HTML:
editorial layout and brief motion are allowed, but the saved numbers and the
supported claim never depend on them. Derived from the strength-flags review (PR113).

## Layout

- **Front-page answer.** Put the paired values as large type side by side, with the
  adjusted (stratified or controlled) difference at the same size beside the raw
  difference. Denominator and period sit directly under the numbers. Showing only the
  larger raw difference overstates the effect.
- **One protagonist per section.** Demote supporting prose to narrow footnote columns;
  do not give every block the same weight.
- **Counter-evidence is a sidebar, not a sentence under the headline.** A figure with a
  different population or window (for example "most doublers had dipped first") needs
  its population label above the number so it is not read as "selling would miss it".
- **Breadcrumb for lineage.** Prior-study context becomes a thin "previous → this" line
  near the top; the full account moves after the results.
- **Order:** question → answer → one-line main limitation → timeline → self-serve
  exploration → evidence → lineage and limits.

## Encoding

- Encode groups with neutral series tokens, never the market gain/loss colors; those
  mean price direction only. Verdict boxes carry no emotional color.
- Bars start at zero. A capped scale is labelled on the axis ("scale 0–30%"). For a
  single proportion prefer a 100-cell icon array; the exact value is always beside it,
  because rounding hides small differences.
- Show raw and adjusted differences as two coexisting quantities on one scale. Never
  animate one into the other.

## Motion

- Count-up and reveal are decorative: final values are in the DOM text from first
  paint, animated layers are `aria-hidden`, and a screenshot mid-animation must not be
  the only place a wrong number exists.
- Content is visible by default. JavaScript adds a pre-reveal class; CSS never hides
  content on its own. Under `prefers-reduced-motion` show the final state.
- Animate only reader-initiated changes, at most about 250 ms, and never a value
  between two different populations.
- An embedded report sits in a full-height iframe that does not scroll itself, so CSS
  scroll timelines (`animation-timeline`) and sticky scrollytelling fail there. Use
  IntersectionObserver, or add a viewport message from the host viewer (needs a new kit
  version; never edit a frozen kit).
- A footnote mark on a number opens its denominator and interval in place.

## Check before delivery

Every theme in both appearances while embedded, standalone fallback, reduced motion,
375 px width with no horizontal scroll, and a fresh reader explaining the headline
without hints.
