import assert from "node:assert/strict";
import test from "node:test";
import {
    dataQualityState,
    DATA_QUALITY_STALE_AFTER_MS,
    formatQualityShare,
} from "./dataQualityState.ts";

const NOW = Date.parse("2026-10-19T12:00:00Z");
const report = (generated_at: string) => ({
    available: true,
    report: { generated_at },
});

test("official coverage does not round partial coverage up to complete", () => {
    assert.equal(formatQualityShare(0.9995), "99.95%");
    assert.equal(formatQualityShare(0.99999999), "接近 100%");
    assert.equal(formatQualityShare(1), "100%");
    assert.equal(formatQualityShare(0), "0%");
    assert.equal(formatQualityShare(null), "未知");
});

test("keeps loading, read failure, and missing report distinct", () => {
    assert.deepEqual(dataQualityState({ status: "loading" }), {
        status: "loading",
    });
    assert.deepEqual(dataQualityState({ status: "failure", message: "503" }), {
        status: "failure",
        message: "503",
    });
    assert.deepEqual(
        dataQualityState({
            status: "loaded",
            data: { available: false, report: null },
        }),
        { status: "missing" },
    );
});

test("uses report timestamp and a 72-hour threshold", () => {
    assert.equal(
        dataQualityState(
            { status: "loaded", data: report("2026-10-19T10:26:58+00:00") },
            NOW,
        ).status,
        "fresh",
    );
    assert.equal(
        dataQualityState(
            { status: "loaded", data: report("2026-10-19T11:00:00Z") },
            NOW,
        ).status,
        "fresh",
    );
    assert.equal(
        dataQualityState(
            { status: "loaded", data: report("2026-10-16T12:00:00Z") },
            NOW,
        ).status,
        "fresh",
    );
    assert.equal(DATA_QUALITY_STALE_AFTER_MS, 72 * 60 * 60 * 1000);
    assert.equal(
        dataQualityState(
            { status: "loaded", data: report("2026-10-16T11:59:59Z") },
            NOW,
        ).status,
        "stale",
    );
    assert.equal(
        dataQualityState(
            { status: "loaded", data: report("2026-10-20T12:00:00Z") },
            NOW,
        ).status,
        "fresh",
    );
    assert.equal(
        dataQualityState({ status: "loaded", data: report("unknown") }, NOW)
            .status,
        "failure",
    );
});

test("does not turn unknown source counts into zero", () => {
    const state = dataQualityState(
        { status: "loaded", data: report("2026-10-19T11:00:00Z") },
        NOW,
    );
    assert.equal(state.status, "fresh");
    if (state.status === "fresh")
        assert.equal(state.data.report?.coverage, undefined);
});
