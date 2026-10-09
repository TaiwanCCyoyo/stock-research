# Industry-role comparison contract v1

Definitions and prospective promotion rules are in [mission.md](mission.md).
Producer: scripts/run_industry_role_comparison.py and
research_core/industry_role_comparison.py. These consume pinned atlas/context
packages; they do not download, normalize prices or update a data pipeline.

## Discovery and obtaining evidence

Start at docs/en/research-program.md, then this task's report and manifest.
Original JSON output and execution receipt live in runs/registered/<job-id>/,
ignored locally. Exact packet bytes are retained under preregistration/_.json.gz;
params/_.json is the uncompressed local execution copy.

publication-v1/manifest.json will identify an industry-role-publication.v1 package:
XZ-compressed summary/results/input-audit/packet/receipt JSON plus source-inputs.zip.
Use scripts.publish_method_environment_interactions.read_publication(path) to
verify all hashes, task/schema binding, receipt outputs, source code/contracts
and original packet before returning saved evidence. It neither executes archived
code nor requires live source/runtime/data. Absence or corruption is an error,
never a successful empty result. The old method-environment package remains readable.

This package contains ALL compact positive/negative/unknown comparisons, not only
the selected conclusion. It does not contain atlas bulk, per-row roles or an
offsite backup. Atlas bulk and exact input archives remain at the locations in
the atlas data contract; do not replace them with today's producer cache.

## Result semantics

results uses industry-role-results.v1. Collections: comparisons, path_summaries,
paired_rows, triage and role_audit. Comparison keys are panel, arm, label,
context_column/context_value; null context means pooled. Panels daily/grid126;
labels label_63/label_126. Industry, year and market_state are separate cuts, not
a Cartesian product. An absent group is not zero risk or zero failure probability.
All seven arms share role/rank-known support, while availability retains the
base-eligible denominator. Counts are dependent stock/date rows, not trades.

Precision, coverage, return, drawdown and differences are fractions, not percentages.
Drawdown is a positive price-path loss; minimum return can be negative. Path
distributions retain count/missing/mean/p10/median/p90, using pandas' linear
quantiles. Known nonwinners may earn small positive price returns and remain
nonwinners. Waiting time is slots to the saved target among known winners only.
These quantities exclude execution costs and do not describe captured account PnL.

Paired winner retention is actual shared winners / control winners. A zero
denominator yields null. Selected-known distinct issuers/dates are separate from
group-wide eligible distinct counts. Triage is a provisional account-design
nomination, not strategy approval or an automatically authorized next run.

role_audit records missing/support counts. The reusable build_roles(frame) returns
all input rows with role, role_missing_reason, peer_strength, peer_count,
peer_mean_ret20/60 and peer_positive60_fraction. It requires frozen saved input
columns as defined by mission, computes no outcomes, and does not mutate inputs.
This API can derive rows for another authorized study; the current package does
not pretend those large row-level outputs were separately persisted.

input-audit binds source IDs/manifests, original date window, projection and exact
0050 join counts. Current-reference industries and cohort are not historical PIT
or survivorship certification. Source versions differ and remain explicit.

## Replay and correction

Prepare a fresh packet with --prepare <job-id>; preparation is not execution
authority. Run only through run_registered_job with the parent's approved digest.
Never overwrite an old run/package. Publication archives the code/contracts as
they were before appending the new exposure event. Full replay additionally needs
separately retained bulk and the pinned environment; offline compact reading does not.
Future correction requires a new version/run and explicit correction record.
