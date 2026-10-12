---
name: research-source-sealing
description: Prepare source code for an already authorized stock-research study before execution, sealing or publication. Use when formatting research runners, freezing source snapshots, recording raw-byte hashes, or preparing source pins and execution receipts. Do not use an environment or line-ending request as permission to run research.
---

# Research Source Sealing

Format before fixing the executed source identity. A receipt must describe the
actual bytes used by the run, including line endings and imported project code.

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
4. Only after formatting is stable, fix the selected source version in a commit
   or immutable source snapshot and record SHA-256 of each executed file's raw
   bytes, including the project dependencies required by the study's contract.
   Use binary reads, such as `Path(path).read_bytes()`, without decoding, newline
   replacement or JSON reserialization. A Git commit or blob identity does not
   replace the raw-byte hash of a working-tree file.
5. Execute the authorized study using those fixed files. Verify source hashes
   against that snapshot before execution and again before publishing the receipt.
   Record the actual source paths, raw-byte hashes, source version and required
   input/environment identities in the study's existing packet or receipt format.
   If source bytes change during the run, stop publication and investigate; do not
   claim the changed source produced the existing output.

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
