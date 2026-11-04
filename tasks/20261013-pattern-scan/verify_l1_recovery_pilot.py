"""Verify saved pilot denominators directly; never reads market inputs or computes new features."""

import json
import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import pandas as pd

    from research_core.pattern_scan_parquet_v1 import read_frame
    from research_core.pattern_scan_rates_v1 import summarize_events
    from research_core.research_measurement_v1 import phase_receipt, resource_sample
    from research_core.run_receipt import changed_results

    run = Path(sys.argv[1])
    assert not changed_results(run / "receipt.json")
    audit = json.loads((run / "payload/audit.json").read_text())
    job = json.loads((run / "job-memory.json").read_text())
    before = resource_sample()
    events = pd.concat([read_frame(run / "payload" / f"{c}-events.parquet") for c in audit["selected_codes"]], ignore_index=True)
    conditions = pd.concat([read_frame(run / "payload" / f"{c}-conditions.parquet") for c in audit["selected_codes"]], ignore_index=True)
    joined = events.merge(conditions, on="event_id", validate="many_to_one")
    checked = 0
    q1 = []
    for name in ("q1-summary", "q1-annual", "marginal-summary", "marginal-annual"):
        table = read_frame(run / "payload" / f"{name}.parquet")
        selected = table.loc[table.split.eq("all") & table.era.eq("all") & table.mkt.eq("all")]
        if "row_kind" in selected:
            selected = selected.loc[selected.row_kind.eq("full")]
        for row in selected.to_dict("records"):
            sample = joined.loc[joined.horizon.eq(row["horizon"])]
            if "year" in row:
                sample = sample.loc[sample.t0.str[:4].astype(int).eq(row["year"])]
            if name.startswith("marginal"):
                f = row["feature_id"]
                sample = sample.loc[sample[f + "_status"].eq(row["condition_status"])]
                if row["condition_status"] == "known":
                    sample = sample.loc[sample[f + "_bin"].eq(row["bin_id"])]
            expected = summarize_events(sample)
            for key, value in expected.items():
                actual = row[key]
                if value is None:
                    assert pd.isna(actual), (name, row, key, value)
                else:
                    assert actual == value, (name, row, key, value)
            checked += 1
            if name == "q1-summary":
                q1.append({"horizon": row["horizon"], **expected})
    verification = phase_receipt("post_run_direct_count_parity", before, resource_sample())
    result = {
        "scope": "five-stock recovery correctness; no market four-cell results",
        "run": str(run),
        "code_commit": audit["expected_code"]["commit"],
        "selected_codes": audit["selected_codes"],
        "retained_payloads_verified": audit["retained_l1_payloads_verified"],
        "stocks": audit["stocks"],
        "q1_union": q1,
        "direct_summary_annual_rows_checked": checked,
        "full_q1_parity": "not_run",
        "full_marginal_parity": "not_run",
        "runtime_provenance": audit["runtime_provenance"],
        "inventory": audit["inventory_measurement"],
        "aggregation": audit["aggregation"],
        "serialization": audit["serialization"],
        "artifact_write": audit["artifact_write"],
        "worker": audit["overall"],
        "job": job,
        "verification": verification,
        "total_run_bytes": sum(p.stat().st_size for p in run.rglob("*") if p.is_file()),
        "result_hash_verification": "pass",
        "integrity_scope": audit["integrity_scope"],
    }
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "summary": str(target),
                "checked_rows": checked,
                "q1": q1,
                "job": job,
                "worker": audit["overall"],
                "stocks": [(s["code"], s["event_count"], s["historical_parity_verified"]) for s in audit["stocks"]],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
