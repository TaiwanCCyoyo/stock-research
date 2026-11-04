import assert from "node:assert/strict";
import { test } from "node:test";
import fixture from "../../../../scripts/tests/fixtures/l1-volume-comparison.synthetic.v1.json" with { type: "json" };
import { adaptL1Comparison } from "./l1Adapter.ts";

test("adapts only the producer L1 contract while preserving aggregate evidence", () => {
    const view = adaptL1Comparison(fixture, "synthetic-l1");
    assert.equal(view.id, "synthetic-l1");
    assert.equal(view.synthetic, true);
    assert.equal(view.producer?.scope, "synthetic");
    assert.equal(view.producer?.schemaVersion, "l1-volume-comparison.v1");
    assert.equal(view.source.priceBasis.includes("Not declared"), true);
    for (const horizon of [126, 252] as const) {
        const w = view.windows[horizon]!;
        assert.equal(w.all.status, "not-evaluated");
        assert.deepEqual(w.cases, []);
        assert.deepEqual(w.complements, {});
        assert.equal(Object.keys(w.cells).length, 4);
        assert.equal(w.unavailable?.length, 8);
        assert.equal(w.all.counts?.known, 4);
        assert.equal(
            w.all.counts?.unknown,
            fixture.horizons.find((h) => h.horizon === horizon)!.cohort
                .unknown_n,
        );
        assert.equal(w.all.saved?.event_n, 8);
        for (const refs of Object.values(w.references ?? {}))
            for (const r of refs ?? []) assert.equal(r.horizon, horizon);
    }
    assert.deepEqual(view.source.inputVersion, fixture.provenance.input_id);
});

test("preserves null rates, overlap semantics and distinct-stock counts without adding stocks", () => {
    const v = adaptL1Comparison(fixture, "x");
    const zero = Object.values(v.windows[126]!.cells).find(
        (s) => s.saved?.hit_rate === null,
    )!;
    assert.equal(zero.saved?.hit_rate, null);
    assert.equal(
        v.producer?.semantics.count_overlap,
        fixture.semantics.count_overlap,
    );
    assert.equal(v.windows[126]!.all.counts?.stocks, 3);
});

test("rejects unknown schema, scope/evaluation contradictions, structural duplicates and broken partitions", () => {
    const mutations = [
        (x: any) => (x.schema_version = "l1-volume-comparison.v2"),
        (x: any) => (x.synthetic = false),
        (x: any) =>
            (x.horizons[0].cells[1].cell_id = x.horizons[0].cells[0].cell_id),
        (x: any) => x.horizons[1].unavailable.pop(),
        (x: any) => x.horizons[0].cells[0].summary.event_n++,
        (x: any) =>
            (x.horizons[0].cells[0].evaluation_status.status = "evaluated"),
        (x: any) => (x.horizons[0].cohort.hit_rate = null),
    ];
    for (const mutate of mutations) {
        const x = structuredClone(fixture);
        mutate(x);
        assert.throws(() => adaptL1Comparison(x, "x"));
    }
});

test("rejects inconsistent horizons, provenance, references, rate denominators and counts", () => {
    const mutations = [
        (x: any) => x.horizons[1].cells[0].summary.event_n++,
        (x: any) => (x.provenance.source_id = "other"),
        (x: any) =>
            (x.horizons[0].cells[0].references[0].security_id = "NOT-SELECTED"),
        (x: any) =>
            x.horizons[0].cells[0].references.push(
                x.horizons[0].cells[0].references[0],
            ),
        (x: any) => (x.horizons[0].cells[0].summary.hit_rate = 0),
        (x: any) => (x.horizons[0].cells[0].summary.known_n = -1),
        (x: any) => (x.provenance.base_label_manifest_sha256 = "A".repeat(64)),
    ];
    for (const mutate of mutations) {
        const x = structuredClone(fixture);
        mutate(x);
        assert.throws(() => adaptL1Comparison(x, "x"));
    }
});

test("does not mutate the saved producer payload", () => {
    const copy = structuredClone(fixture);
    const before = JSON.stringify(copy);
    adaptL1Comparison(copy, "immutable");
    assert.equal(JSON.stringify(copy), before);
});

test("accepts reordered JSON object keys and multiple event references for one stock", () => {
    const copy = structuredClone(fixture);
    copy.semantics = Object.fromEntries(
        Object.entries(copy.semantics).reverse(),
    );
    const evaluation = copy.horizons[0].cells[0].evaluation_status;
    copy.horizons[0].cells[0].evaluation_status = Object.fromEntries(
        Object.entries(evaluation).reverse(),
    );
    const cell = copy.horizons[0].cells.find(
        (c) => c.summary.event_n >= 2 && c.references.length === 1,
    );
    if (cell) {
        cell.references.push({
            ...cell.references[0],
            event_id: `${cell.references[0].event_id}-second`,
        });
    }
    assert.equal(adaptL1Comparison(copy, "reordered").id, "reordered");
});

test("rejects repeated unavailable pairs, duplicate horizons, missing required fields and scope/status contradictions", () => {
    const mutations = [
        (x: any) => {
            x.horizons[0].unavailable[1].G_status =
                x.horizons[0].unavailable[0].G_status;
            x.horizons[0].unavailable[1].VOL_a_status =
                x.horizons[0].unavailable[0].VOL_a_status;
        },
        (x: any) => {
            x.horizons[1].horizon = 126;
        },
        (x: any) => {
            delete x.horizons[0].cells[0].references;
        },
        (x: any) => {
            x.provenance.scope = "pilot";
        },
        (x: any) => {
            x.provenance.scope = "full";
            x.synthetic = false;
            x.provenance.validation_scope.full_q1_parity = true;
            x.provenance.validation_scope.marginal_parity = true;
        },
    ];
    for (const mutate of mutations) {
        const x = structuredClone(fixture);
        mutate(x);
        assert.throws(() => adaptL1Comparison(x, "x"));
    }
});

test("rejects summary subset violations and cohort stocks above selected set", () => {
    const mutations = [
        (x: any) => {
            x.horizons[0].cohort.censored_n = 0;
        },
        (x: any) => {
            x.horizons[0].cohort.full_calendar_n = 0;
        },
        (x: any) => {
            x.horizons[0].cohort.distinct_stock_n =
                x.provenance.actual_selected_stocks.length + 1;
        },
    ];
    for (const mutate of mutations) {
        const x = structuredClone(fixture);
        mutate(x);
        assert.throws(() => adaptL1Comparison(x, "x"));
    }
});

test("rejects a trace event moved to another partition between horizons", () => {
    const x = structuredClone(fixture);
    const source = x.horizons[0].cells.find((c) => c.references.length > 0);
    const moved = x.horizons[1].cells.find(
        (c) => c.cell_id !== source.cell_id && c.summary.event_n > 0,
    );
    if (source.references.length && moved) {
        moved.references = [{ ...source.references[0], horizon: 252 }];
    }
    assert.throws(() => adaptL1Comparison(x, "cross-horizon-partition"));
});
