import assert from "node:assert/strict";
import { test } from "node:test";
import {
    candleRows,
    groupCatalog,
    selectedCatalogVersion,
    priceChange,
    formatNumber,
    formatFeature,
    formatSigned,
    featureRows,
    qualityCounts,
    qualityReasonLabel,
    versionLabel,
    compactVersionLabel,
    type SharedSeries,
} from "./model.ts";

test("version labels shorten hash tokens while preserving semantic identifiers", () => {
    const hash = "abcdef0123456789".repeat(4);
    assert.equal(compactVersionLabel(hash), "abcdef012345…");
    assert.equal(
        compactVersionLabel(`annual-v2-${hash}`),
        "annual-v2-abcdef012345…",
    );
    assert.equal(
        compactVersionLabel("annual-v2-20261022"),
        "annual-v2-20261022",
    );
    assert.equal(
        compactVersionLabel("releaseabcdef0123456789abcdef0123456789"),
        "releaseabcdef0123456789abcdef0123456789",
    );
    assert.equal(hash.length, 64);
});

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
test("compound quality failures remain distinct and untranslated codes are not presented as valid data", () => {
    assert.equal(
        qualityReasonLabel("missing_official_quote|invalid_ohlc"),
        "缺少官方報價；開高低收價格不合理或缺漏",
    );
    assert.equal(
        qualityReasonLabel("duplicate_date|duplicate_date"),
        "同一日期有重複紀錄",
    );
    assert.equal(
        qualityReasonLabel("future_reason"),
        "其他資料品質問題（詳見來源）",
    );
    assert.equal(qualityReasonLabel(null), "缺少有效開高低收價格");
    assert.equal(fixture.quality_reason[1], "missing_quote");
});
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

test("catalog groups all versions without recommending the first or latest", () => {
    const versions = ["old", "latest"].map((version_id) => ({
        data_id: "one",
        version_id,
        status: "partial",
        kind: "features",
    }));
    const groups = groupCatalog([
        ...versions,
        { ...versions[0], data_id: "two" },
    ]);
    assert.equal(groups.length, 2);
    assert.deepEqual(groups[0][1], versions);
    assert.equal(
        selectedCatalogVersion(versions, "latest").version_id,
        "latest",
    );
    assert.equal(
        versionLabel(selectedCatalogVersion(versions)),
        "未標示現行版",
    );
    assert.equal(
        selectedCatalogVersion([
            versions[0],
            { ...versions[1], recommended: true },
        ]).version_id,
        "latest",
    );
    assert.equal(selectedCatalogVersion(versions, "removed").version_id, "old");
});
test("quote change skips invalid gaps and uses previous valid close", () => {
    const sample = {
        ...fixture,
        open: [10, 20, 13],
        high: [12, 22, 14],
        low: [9, 19, 12],
        close: [11, 21, 13],
    };
    const change = priceChange(sample, 2);
    assert.equal(change.amount, 2);
    assert.equal(change.percent, (2 / 11) * 100);
    assert.equal(change.direction, "gain");
    assert.equal(priceChange(sample, 1).amount, null);
    assert.equal(priceChange(sample, 0).percent, null);
    assert.equal(priceChange(sample, -1).amount, null);
});
test("quote change preserves zero and losses without dividing by non-positive prices", () => {
    const sample = {
        ...fixture,
        open: [10, 20, 10],
        high: [12, 22, 12],
        low: [9, 19, 9],
        close: [11, 21, 10],
    };
    assert.equal(priceChange(sample, 2).direction, "loss");
    assert.equal(priceChange({ ...sample, close: [11, 21, 11] }, 2).amount, 0);
    assert.equal(
        priceChange({ ...sample, close: [0, 21, 10] }, 2).percent,
        null,
    );
    assert.equal(
        priceChange({ ...sample, close: [-1, 21, 10] }, 2).percent,
        null,
    );
});
test("price, volume and indicator display projections keep units and missing values distinct", () => {
    assert.equal(formatNumber(1234.567), "1,234.57");
    assert.equal(formatNumber(-1.235), "-1.24");
    assert.equal(formatNumber(-0.001), "0");
    assert.equal(formatNumber(0), "0");
    assert.equal(formatNumber(null), "—");
    assert.equal(formatNumber(NaN), "—");
    assert.equal(formatNumber(1234.56, 0), "1,235");
    assert.equal(formatFeature("atr14_pct", 0.023456), "2.35%");
    assert.equal(formatFeature("atr14_pct", 0), "0%");
    assert.equal(formatFeature("atr14_pct", null), "—");
    assert.equal(formatFeature("MACDHist", -0.123), "-0.12");
    assert.equal(formatSigned(-2), "-2");
    assert.equal(formatSigned(2), "+2");
    assert.equal(formatSigned(0), "0");
});
