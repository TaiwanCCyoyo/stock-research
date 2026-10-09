# Bounded presentation inputs

`opportunity-catalog.preview.v1.json.gz` is a physical copy of the completed
sector-wave chat's bounded preview, from local commit `fac041c`:
`tasks/20261004-sector-wave-web-contract/preview.json.gz`.
It contains eight existing historical cases and eight named synthetic controls;
the website exporter explicitly selects historical or synthetic, never mixes them.
The compressed bytes and original source identities are preserved. This fixture
does not decide the storage/backup policy for the full market catalog or cache.

The fixed display selection is
`tasks/20261004-opportunity-explorer/preview-selections.json`. Its eight named
waves and launch candidates are a visual review slice, not an approved automatic
selection rule. In particular, the no-launch/quality-cutoff case is retained.
Other source waves, phases, relations and failed launches remain in this input.

No new fitting, strategy execution, download or cache write produced this copy.
The source preview's validation and complete hashes are recorded in its own
completion receipt. The presentation exporter records this input's byte hash
again. Dates, coverage and missing values must survive any subsequent adapter.
