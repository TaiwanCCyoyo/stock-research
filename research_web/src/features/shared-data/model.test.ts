import assert from "node:assert/strict";
import { test } from "node:test";
import {
    candleRows,
    featureRows,
    qualityCounts,
    versionLabel,
    type SharedSeries,
} from "./model.ts";

const fixture: SharedSeries = {
    code: "SYNTH",
    basis: "reference_factor_adjusted",
    generation: "synthetic",
    status_sha256: "synthetic",
    asof: "2020-01-03",
    dates: ["2020-01-01", "2020-01-02", "2020-01-03"],
    open: [10, 20, null],
    high: [12, 22, null],
    low: [9, 19, null],
    close: [11, 21, null],
    volume: [1.5, 2.5, null],
    quality: [true, false, true],
    quality_reason: ["ok", "missing_quote", ""],
    tech: { SMA5: [10.5, 99, null] },
    pivots: [],
};
test("invalid quality and missing OHLC stay whitespace even if a numeric price exists", () => {
    assert.deepEqual(candleRows(fixture), [
        { time: "2020-01-01", open: 10, high: 12, low: 9, close: 11 },
        { time: "2020-01-02" },
        { time: "2020-01-03" },
    ]);
    assert.deepEqual(qualityCounts(fixture), [
        ["missing_quote", 1],
        ["缺少有效 OHLC", 1],
    ]);
});
test("stored indicators retain values and warmup gaps without recomputation", () => {
    assert.deepEqual(featureRows(fixture, "SMA5"), [
        { time: "2020-01-01", value: 10.5 },
        { time: "2020-01-02" },
        { time: "2020-01-03" },
    ]);
    assert.deepEqual(
        featureRows(fixture, "unavailable"),
        fixture.dates.map((time) => ({ time })),
    );
});
test("catalog does not infer current version from partial status or version id", () => {
    assert.equal(
        versionLabel({
            data_id: "synthetic",
            version_id: "latest",
            status: "partial",
            kind: "bundle",
        }),
        "未標示現行版",
    );
});
