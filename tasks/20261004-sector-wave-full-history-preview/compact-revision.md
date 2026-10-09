# Compact continuity correction registered before re-export

Registered 2026-10-04 after a synthetic boundary review, before evaluating the
revised compact export. Native method code, settings, source prices, six saved
method results and the original catalog-v1 are preserved. No strategy acceptance
criterion is introduced or changed.

The original producer commit 37cb418 uses both a Python log-ratio gain guard and
saved JavaScript run separation. The source detector determines fit/wave runs by
subtracting individual JavaScript logarithms; its separate log-ratio jump warning
does not block numeric fitting. These expressions can disagree at a floating-point
threshold. Synthetic quotes 6.02 to 8.127 have saved run IDs [0,0] but a log-ratio
warning, making the original day-gain guard unnecessarily report an unknown gain.
The reverse synthetic case 4 to 5.4 has saved [0,1] and must remain blocked.

The new `exact_pinned_js_run.preview.v2` gain policy uses the saved JavaScript
run identities as its jump criterion when present, alongside existing null,
invalid-quote, dated numeric flag and action-barrier checks. Source method jump
warnings remain diagnostics. Explicitly marked Python fallback uses individual
log differences; it is not claimed to reproduce JavaScript bit-level boundaries.

Export compact records into a new catalog-v2 using unchanged, hash-verified saved
native artifacts and physical copies of the identical series. Never call the
analysis runner, modify source inputs/native results, overwrite catalog-v1 or
rename this revision as an independent strategy validation. Record the original
manifest/producer identity and separate new compact adapter/export identities.
The website and CLI should consume catalog-v2 together.
