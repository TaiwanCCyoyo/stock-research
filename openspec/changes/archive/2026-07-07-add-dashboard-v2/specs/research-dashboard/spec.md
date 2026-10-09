## ADDED Requirements

### Requirement: The dashboard contract is implementation-agnostic

The `research-dashboard` capability's requirements MUST be satisfied by whichever implementation is currently the primary entry point (Panel or the new frontend), and switching the primary entry point MUST NOT drop any existing requirement.

#### Scenario: Verify parity before switching the primary entry point

- **WHEN** `open_research_dashboard.cmd` is repointed from the Panel implementation to the
  new frontend
- **THEN** every scenario in this capability's existing requirements MUST have a
  demonstrated equivalent in the new frontend
- **AND** the Panel implementation MUST be preserved under `legacy/` rather than deleted,
  so it remains available as a reference or fallback.
