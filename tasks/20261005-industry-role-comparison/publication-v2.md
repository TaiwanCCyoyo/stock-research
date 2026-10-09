# H03 portable evidence: lossless transport v2

2026-10-05. Start at [report.md](report.md) for findings and limitations, then
[data-contract.md](data-contract.md) for the sealed scientific result semantics.
The original contract describes publication v1. This additive transport version
changes only how its bytes are stored, not its definitions, results or receipt.

## Obtain and read

After this task PR is integrated, a fresh clone contains all nine files under
publication-v2/. Until then, obtain them from branch
codex/method-environment-interactions-20261005 in PR #28; they are not yet on main.
Copy the whole directory, not just manifest.json or one result part.

From the repository root, using its installed Python environment:

```powershell
uv run --no-sync python scripts/publish_method_environment_interactions.py --read tasks/20261005-industry-role-comparison/publication-v2
```

For consumers needing all tables rather than the CLI summary:

```python
from pathlib import Path
from scripts.publish_method_environment_interactions import read_publication

evidence = read_publication(
    Path("tasks/20261005-industry-role-comparison/publication-v2")
)
comparisons = evidence["results"]["comparisons"]
paths = evidence["results"]["path_summaries"]
pairs = evidence["results"]["paired_rows"]
```

The reader returns manifest (v2), source_manifest (original v1), packet, receipt,
summary, results and input-audit. It checks file sets and hashes, reconstructs XZ
in memory, verifies the original manifest and archived source/receipt bindings,
then returns data. Missing or altered parts fail closed. It does not run archived
code, evaluate research or require the original worktree, price cache or bulk.

## Identity and storage

- Transport ID: `industry-role-transport.v2-03dff10e7e7d270ef703560c4233ae320261f74d1ebb0d07ec3c93f5de845785`. <!-- pragma: allowlist secret -->
- Scientific publication ID: `industry-role-publication.v1-d5c256e0f5207587a61a579739a92e902c839d1a203dd6b8067d738f9e0b65f2`. <!-- pragma: allowlist secret -->
- [manifest.json](publication-v2/manifest.json) binds all eight payload files;
  [source-manifest.json](publication-v2/source-manifest.json) is the unchanged v1 manifest.
- Original results.json.xz is 660,188 bytes. Contiguous parts are 350,000 and
  310,188 bytes; concatenating in manifest order reproduces the exact original.
- Reconstructed XZ SHA256: `edbf75001f3be799cab1d7c8fb907e5e5fc3c00b26f03fbca7629f3c88d56ec2`. <!-- pragma: allowlist secret -->
- Total package: 946,693 bytes; largest file: 350,000 bytes. No file-size check
  was weakened, and no scientific result was removed to fit the limit.

The original publication-v1/ remains local and unchanged. Its source-inputs.zip
contains the executed code/contracts and the pre-exposure registry. Subsequent
reader changes and registry appends legitimately differ from that archived
read-set; they are not retroactively included in the original execution packet.
Repacking therefore verifies saved evidence, not reuse against today's source.

## Verification and remaining limits

The 48-case publication suite passed, including existing formats, independent
copied-directory reading, exact byte preservation, tampering, partial files,
overlap/no-overwrite and source-change rejection. A separate physical-copy smoke
read of this actual package verified identical packet, receipt, summary, results
and input-audit against v1: 1,316 comparisons, 3,948 paths, 2,256 paired rows.
The previous method-environment publication also retained its original identity.

The normal secret scanner identified 17 generated SHA256 values in the two
manifests. They were verified as checksums and added as exact path/value baseline
exceptions, without changing payload bytes or disabling scanning. The existing
regression proving known-value acceptance and new-value rejection also passed.

This is complete compact evidence, not a copy of atlas bulk or per-row industry
roles. Full recomputation additionally needs the pinned environment and retained
bulk/input archives linked by the atlas contract. Those physical copies are on
the same drive, not an offsite backup. The package does not certify PIT industry
membership, independent samples, executable account returns or strategy approval.
