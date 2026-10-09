import assert from "node:assert/strict";
import { test } from "node:test";
import type {
    StudioExposure,
    StudioSummary,
} from "../../domain/strategies/types.ts";
import {
    capturedTradeLabel,
    capturedTradeNote,
    captureWeightValue,
    captureWeightNote,
    sharedExposureCoverage,
} from "./captureModel.ts";
import { EXPOSURE_KEYS } from "./exposureModel.ts";

const summary = (overrides: Partial<StudioSummary> = {}) => ({
    captureState: "ready" as const,
    capturedClosedTradeCount: null,
    closedTradeCount: 4,
    captureAvgWeight: null,
    ...overrides,
});
const coverage = {
    closedTradeTotal: 4,
    confirmedCapturedClosedTradeCount: 1,
    confirmedNotCapturedClosedTradeCount: 1,
    undeterminedClosedTradeCount: 2,
    completeExposureDays: 2,
    totalExposureDays: 3,
    knownDayAverageWeight: 0.2,
};
const row = (
    date: string,
    overrides: Partial<StudioExposure["rows"][number]> = {},
): StudioExposure["rows"][number] => ({
    date,
    runawayWeight: 0.2,
    otherStockWeight: 0.3,
    unknownStockWeight: 0,
    otherAssetsWeight: 0.1,
    cashWeight: 0.4,
    known: true,
    verifiedAccount: true,
    ...overrides,
});
const exposure = (
    rows: StudioExposure["rows"],
    captureState: StudioExposure["captureState"] = "ready",
): StudioExposure => ({
    runId: "run",
    basis: "saved",
    captureState,
    rows,
});

test("partial evidence shows confirmed lower bound and explicitly separates misses and unknowns", () => {
    const run = summary({ captureCoverage: coverage });
    assert.equal(capturedTradeLabel(run), "至少已確認 1／4 筆");
    assert.match(capturedTradeNote(run), /未持有飆股 1 筆；尚未判定 2 筆/);
    assert.equal(captureWeightValue(run), 0.2);
    assert.match(captureWeightNote(run), /2／3 天；缺資料 1 天/);
});
test("all complete evidence including true zero remains a confirmed result", () => {
    const run = summary({
        captureCoverage: {
            ...coverage,
            confirmedCapturedClosedTradeCount: 0,
            confirmedNotCapturedClosedTradeCount: 4,
            undeterminedClosedTradeCount: 0,
            knownDayAverageWeight: 0,
        },
    });
    assert.equal(capturedTradeLabel(run), "已確認 0／4 筆");
    assert.equal(captureWeightValue(run), 0);
});
test("unavailable legacy, loading and failed enrichment remain unknown", () => {
    assert.equal(capturedTradeLabel(summary()), "待核對");
    assert.equal(captureWeightValue(summary()), null);
    for (const captureState of ["loading", "failed"] as const) {
        const run = summary({
            captureState,
            captureCoverage: coverage,
            capturedClosedTradeCount: 0,
            captureAvgWeight: 0,
        });
        assert.equal(capturedTradeLabel(run), "待核對");
        assert.equal(captureWeightValue(run), null);
        assert.doesNotMatch(capturedTradeNote(run), /尚未判定 2/);
    }
    const legacy = summary({
        capturedClosedTradeCount: 2,
        captureAvgWeight: 0.1,
    });
    assert.equal(capturedTradeLabel(legacy), "2／4 筆");
    assert.equal(captureWeightValue(legacy), 0.1);
});
test("no complete dates and no rows never fabricate allocation zero", () => {
    for (const exposures of [
        [],
        [undefined],
        [exposure([])],
        [exposure([row("a", { known: false })])],
    ]) {
        const result = sharedExposureCoverage(["a"], exposures);
        assert.equal(result.completeDays, 0);
        assert.equal(result.missingDays, 1);
        assert.ok(result.averageWeights.every((value) => value === null));
    }
    const empty = sharedExposureCoverage([], [exposure([])]);
    assert.equal(empty.totalDays, 0);
    assert.deepEqual(empty.averageWeights, [null]);
});
test("fully complete dates average allocations and include zero without mutating rows", () => {
    const exposures = [
        exposure([
            Object.freeze(row("a", { runawayWeight: 0 })),
            Object.freeze(row("b", { runawayWeight: 0.4 })),
        ]),
    ];
    const before = structuredClone(exposures);
    const result = sharedExposureCoverage(Object.freeze(["a", "b"]), exposures);
    assert.deepEqual(result, {
        completeDays: 2,
        totalDays: 2,
        missingDays: 0,
        averageWeights: [0.2],
    });
    assert.deepEqual(exposures, before);
});
test("all strategies use intersection despite different missing dates and unaligned rows", () => {
    const result = sharedExposureCoverage(
        ["a", "b", "c", "d"],
        [
            exposure([
                row("outside", { runawayWeight: 1 }),
                row("a", { known: false }),
                row("b"),
                row("c", { runawayWeight: 0.6 }),
                row("d"),
            ]),
            exposure([
                row("a"),
                row("b", { cashWeight: null }),
                row("c", { runawayWeight: 0 }),
                row("d", { known: false }),
            ]),
        ],
    );
    assert.deepEqual(result, {
        completeDays: 1,
        totalDays: 4,
        missingDays: 3,
        averageWeights: [0.6, 0],
    });
});
test("missing rows and loading or failed compared exposure exclude all dates", () => {
    const ready = exposure([row("a"), row("b")]);
    const missing = sharedExposureCoverage(
        ["a", "b"],
        [ready, exposure([row("b")])],
    );
    assert.equal(missing.completeDays, 1);
    for (const other of [
        undefined,
        exposure(ready.rows, "loading"),
        exposure(ready.rows, "failed"),
    ]) {
        const result = sharedExposureCoverage(["a", "b"], [ready, other]);
        assert.deepEqual(result.averageWeights, [null, null]);
        assert.equal(result.completeDays, 0);
    }
});
test("any null or nonfinite weight fails the same completeness criterion as the area renderer", () => {
    for (const key of EXPOSURE_KEYS) {
        for (const value of [null, NaN, Infinity, -Infinity]) {
            const result = sharedExposureCoverage(
                ["a"],
                [exposure([row("a", { [key]: value })])],
            );
            assert.equal(result.completeDays, 0, `${key}: ${value}`);
            assert.deepEqual(result.averageWeights, [null]);
        }
    }
});
