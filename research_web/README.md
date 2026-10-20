# STOCK research studio

The Windows dashboard launcher at `scripts/research/open_research_dashboard.cmd`
checks the saved frontend release before starting the API. It compares the built
release identity with the frontend source, production Vite settings, effective
`VITE_ARTIFACT_MODE` and `VITE_API_BASE`, and the completed reports copied into
the release. A stale or missing release is built in a temporary sibling folder;
the launcher switches `dist` only after the frontend shell and report index
carry the same version. A failed build leaves the previous `dist` available.

From `research_web`, `npm run build` performs the same freshness check and staged
publish. If dependencies are missing, it runs `npm ci` before building; no
separate dependency bootstrap is needed. `npm run build:stage` is the internal
raw Vite build used by the release manager and writes only to the configured
staging directory.

For hot reload, use `npm run dev`. The Vite page and `/reports/index.json` both
identify that session as `development`; production builds carry the source
fingerprint in the HTML shell, `release.json`, and the report index.

## Research report library

The report library lists existing task reports from
`tasks/<task-id>/web-report/`. It serves those saved pages and assets without
starting a study or changing its evidence. The index keeps the
`research-reports.v1` schema; its additive `version` field identifies the
frontend release that generated the index.
