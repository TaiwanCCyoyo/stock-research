import assert from "node:assert/strict";
import { test } from "node:test";
import { marketCaptureLink, readMarketLink } from "./navigation.ts";

test("capture links override previous thresholds and catalog mode without changing date or stock", () => {
    for (const thresholdPct of [60, 80, 200]) {
        const previous = {
            date: "2023-01-03",
            code: "2330",
            thresholdPct,
            mode: "catalog",
        };
        const applied = readMarketLink(
            marketCaptureLink("2021-04-22", "2609"),
        )!;
        assert.deepEqual(
            { ...previous, ...applied },
            {
                date: "2021-04-22",
                code: "2609",
                thresholdPct: 100,
                mode: "launched",
            },
        );
    }
});
test("latest-market links specify the same definition without selecting a stock", () => {
    assert.deepEqual(readMarketLink(marketCaptureLink("2026-10-02")), {
        date: "2026-10-02",
        code: null,
        thresholdPct: 100,
        mode: "launched",
    });
});
test("ordinary partial links preserve controls without an explicit valid override", () => {
    for (const hash of [
        "#market?date=2021-04-29",
        "#market?mode=invalid&threshold=NaN&date=bad&code=bad",
        "#market?mode=&threshold=",
    ]) {
        const link = readMarketLink(hash)!;
        assert.equal(link.mode, null);
        assert.equal(link.thresholdPct, null);
    }
    assert.equal(readMarketLink("#market"), null);
    assert.equal(readMarketLink("#strategy/example?mode=catalog"), null);
});
test("supported manual deep-link choices remain valid and independent", () => {
    for (const mode of ["catalog", "launched"])
        for (const threshold of [60, 80, 100, 200]) {
            const link = readMarketLink(
                `#market?mode=${mode}&threshold=${threshold}`,
            )!;
            assert.equal(link.mode, mode);
            assert.equal(link.thresholdPct, threshold);
            assert.equal(link.date, null);
            assert.equal(link.code, null);
        }
});
