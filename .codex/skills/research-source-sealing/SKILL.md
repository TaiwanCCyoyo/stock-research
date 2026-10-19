---
name: research-source-sealing
description: Prepare source code for an already authorized stock-research study before execution, sealing or publication. Use when formatting research runners, freezing source snapshots, recording raw-byte hashes, or preparing source pins and execution receipts. Do not use an environment or line-ending request as permission to run research.
---

# Research Source Sealing

The repository-wide rules for hashes, pins and verification cost are in
[the artifact integrity standard](../../../docs/en/artifact-integrity.md); this skill
covers fixing the source identity before a run. The 2026-10-15 owner policy
distinguishes new run receipts from historical byte-sealed packets.

Format before fixing the executed source identity. New studies use the Git commit
and dirty flag in `research_core/run_receipt.py`; do not hash or copy loaded
modules, lock files or producer inputs into a private source/input snapshot.
Historical packets keep their existing byte-level verification contract.

## Before execution

1. Confirm the study is authorized and follow its mission and preregistration.
   Start with [the research program](../../../docs/en/research-program.md) and
   [the owner contract](../../../docs/en/research-owner-contract.md). This skill
   supplies no authority to evaluate markets, acquire data or reopen sealed work.
2. Use the repository's existing pre-commit configuration for the study's new or
   changed sources and dependencies. Keep the check scoped to those files; do not
   format unrelated or frozen evidence. When files are not staged, pass an
   explicit file list to the same existing pre-commit entry point.
3. If a formatter changes files, inspect the complete diff for unintended logic
   or evidence changes, then rerun the configured checks. Continue until they
   pass and no longer change files. Resolve failures before execution; never
   disable a hook or alter its exclusions to make a study run.
4. After formatting is stable, commit the selected source and preregistration.
   For a new run, record that commit, definition and parameters with the existing
   run-receipt API, and describe the inputs actually read (`fingerprint_inputs`, no
   file hashes). Pass the runner, strategy and study modules the run executes as
   `write_run_receipt(..., sources=[...])`: the receipt's dirty flag does not see
   untracked files, so it refuses a source that is untracked or differs from the
   commit. An input that changed during the run is listed in the receipt, not a reason
   to discard the result; hash results, not sources.
5. Execute the authorized study using those fixed files. If code changes during
   the run, stop publication and investigate; a dirty flag must not be presented
   as a clean committed implementation. A historical byte-sealed packet is the
   exception: use its original raw-byte hashes and verification rules without
   changing or re-pinning them. That exception does not authorize sealing a new
   study with the retired workflow.

## Frozen evidence and line endings

Ordinary maintained text follows `.gitattributes` LF defaults. Its later CRLF and
`-text` exceptions preserve previously sealed bytes and take precedence. Check
the effective attributes before making a source snapshot; never bulk-renormalize
the repository or treat a formatter-only diff as harmless for byte-pinned files.

Do not format a completed run's sources afterward and re-pin its old packet or
receipt to the new hash. Keep the original files, snapshots, receipts and results
byte-identical. When later work needs a formatted or changed implementation,
create a separately versioned source and evidence identity under the existing
placement contract, recording incompatibility and lineage. Execute it only under
the authorization and preregistration for that new work; preserve the old result's
readability under [the research foundation](../../../docs/en/research-foundation.md).
