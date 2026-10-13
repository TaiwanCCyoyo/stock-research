// Regression checks for the HHHL v4 variants report's pure rules (web-report/model.js),
// run against the report's own committed data files, exactly as the page loads them.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { runInNewContext } from "node:vm";

const folder = resolve("../tasks/20261012-hhhl-v4-variants/web-report");
// One shared global, as in the page: the data scripts and model.js write to `window`.
const page = {};
page.window = page;
for (const file of ["data/summary.js", "data/single-252.js", "model.js"])
    runInNewContext(readFileSync(join(folder, file), "utf8"), page);
const { REPORT_DATA: data, HhhlReportModel: model } = page;

const records = ({ columns, rows }) =>
    rows.map((row) =>
        Object.fromEntries(columns.map((name, i) => [name, row[i]])),
    );
const candidates = records(data.candidate);
const baseline = records(data.baseline);
const years = records(data.year);
const find = (rows, where) =>
    rows.find((row) =>
        Object.entries(where).every(([key, value]) => row[key] === value),
    );
const close = (actual, expected) =>
    assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);

test("a pattern-only condition uses PR #9's published unfiltered control, not a zero row", () => {
    const id = "hhhl-v4-variants.v1:B=ge20";
    const pattern = find(candidates, {
        cohort_id: "P-all",
        split: "cross",
        horizon: 252,
        candidate_id: id,
    });
    const sameCondition = find(candidates, {
        cohort_id: "C-52w",
        split: "cross",
        horizon: 252,
        candidate_id: id,
    });
    assert.equal(pattern.reference_kind, "pattern_only_unfiltered");
    assert.equal(
        sameCondition.known_n,
        0,
        "controls have no Z2, so the same-condition row is empty",
    );
    const cBase = find(baseline, {
        cohort_id: "C-base",
        split: "cross",
        horizon: 252,
    });
    const args = {
        patternRow: pattern,
        selfBaseline: null,
        cBaseBaseline: cBase,
        sameConditionRow: sameCondition,
    };

    const c52w = model.publishedControl({ ...args, comparator: "C-52w" });
    assert.equal(c52w.kind, "unfiltered");
    close(c52w.r, 3327 / 18522); // the 17.962% published in result-tables-v1.md
    const base = model.publishedControl({ ...args, comparator: "C-base" });
    assert.equal(base.kind, "unfiltered");
    close(base.r, cBase.hit_n / cBase.known_n);
});

test("a matched condition compares with the control cohort's same-condition row", () => {
    const id = "hhhl-v4-variants.v1:C3=ge60";
    const pattern = find(candidates, {
        cohort_id: "P-all",
        split: "cross",
        horizon: 252,
        candidate_id: id,
    });
    const sameCondition = find(candidates, {
        cohort_id: "C-52w",
        split: "cross",
        horizon: 252,
        candidate_id: id,
    });
    const control = model.publishedControl({
        comparator: "C-52w",
        patternRow: pattern,
        selfBaseline: null,
        cBaseBaseline: null,
        sameConditionRow: sameCondition,
    });
    assert.equal(control.kind, "matched");
    close(control.r, sameCondition.hit_n / sameCondition.known_n);
    assert.equal(model.publishedControl({ comparator: "none" }).kind, "none");
});

test("choosing a signal from the chart also moves the menu and redraws once", () => {
    const state = { flag: "X3" };
    const menu = { value: "X3" };
    let redraws = 0;
    model.selectFlag(state, "X2", menu, () => (redraws += 1));
    assert.deepEqual([state.flag, menu.value, redraws], ["X2", "X2", 1]);
});

test("year series keep known parts of incomplete years and mark them, per horizon", () => {
    const half = model.yearSeries(years, "P-all", 126);
    const y2026 = half.find((p) => p.year === 2026);
    assert.deepEqual([y2026.known, y2026.hit, y2026.partial], [978, 235, true]);
    assert.ok(y2026.censored > 0);
    assert.ok(half.filter((p) => p.year < 2026).every((p) => !p.partial));

    const full = model.yearSeries(years, "P-all", 252);
    assert.equal(full.find((p) => p.year === 2025).partial, true);
    assert.equal(
        full.some((p) => p.year === 2026),
        false,
        "no known one-year outcome starts in 2026",
    );
});
