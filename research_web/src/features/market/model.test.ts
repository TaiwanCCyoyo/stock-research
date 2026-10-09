import { test } from "node:test";
import assert from "node:assert/strict";
import {
    areaWeight,
    observe,
    nearestDate,
    observationBounds,
    isAtlasData,
    exportObservation,
} from "./model.ts";
import type { AtlasData } from "./model.ts";

function atlasFixture(): AtlasData {
    return {
        schema: "market-atlas.v1",
        catalogHash: "fixture",
        classificationAsOf: "2020-01-03",
        dates: ["2020-01-02", "2020-01-03"],
        groups: [],
        provenance: {},
        limitations: [],
        stocks: [
            {
                code: "A",
                name: "A",
                groupIds: [],
                quality: [],
                raw: [10, 20],
                adjusted: [10, 20],
            },
        ],
    };
}

test("peak returns remain unknown when any price in the selected interval is missing", () => {
    for (const missing of [0, 1, 2]) {
        const atlas = atlasFixture();
        atlas.dates.push("2020-01-06");
        atlas.stocks[0].adjusted = [10, 30, 20];
        atlas.stocks[0].marketCap = [50, 60, 70];
        atlas.stocks[0].adjusted[missing] = null;
        const result = observe(atlas, 0, 2, "return", "peak")[0];
        assert.equal(result.gain, null);
        assert.equal(result.observedEnd, null);
        assert.equal(result.cap, null);
        assert.equal(result.weight, 0);
        assert.match(result.reason!, /期間最高未知/);
    }
});

test("quality-blocked peaks have no verified date or cap while endpoints retain their observation date", () => {
    for (const quality of ["stock", "dated"]) {
        const atlas = atlasFixture();
        atlas.stocks[0].marketCap = [50, 60];
        if (quality === "stock") atlas.stocks[0].quality = ["source-check"];
        else
            atlas.stocks[0].qualityFindings = [
                { date: atlas.dates[1], kind: "source-check" },
            ];
        const original = structuredClone(atlas);
        const peak = observe(atlas, 0, 1, "return", "peak")[0];
        assert.equal(peak.gain, null);
        assert.equal(peak.observedEnd, null);
        assert.equal(peak.cap, null);
        const endpoint = observe(atlas, 0, 1, "return", "endpoint")[0];
        assert.equal(endpoint.gain, null);
        assert.equal(endpoint.observedEnd, 1);
        assert.equal(endpoint.cap, 60);
        assert.deepEqual(atlas, original);
    }
});

test("downloads keep unknown peak dates explicitly null and complete or endpoint dates unchanged", () => {
    for (const missing of [0, 1, 2]) {
        const atlas = atlasFixture();
        atlas.dates.push("2020-01-06");
        atlas.stocks[0].adjusted = [10, 30, 20];
        atlas.stocks[0].adjusted[missing] = null;
        const packet = JSON.parse(
            JSON.stringify(
                exportObservation(
                    atlas,
                    observe(atlas, 0, 2, "return", "peak")[0],
                ),
            ),
        );
        assert.equal(Object.hasOwn(packet, "gainObservedAt"), true);
        assert.equal(packet.gainObservedAt, null);
        assert.equal(packet.gainPercent, null);
    }
    const atlas = atlasFixture();
    atlas.dates.push("2020-01-06");
    atlas.stocks[0].adjusted = [10, 30, 20];
    const peak = exportObservation(
        atlas,
        observe(atlas, 0, 2, "return", "peak")[0],
    );
    assert.equal(peak.gainObservedAt, "2020-01-03");
    assert.equal(peak.gainPercent, 200);
    const missingCap = observe(atlas, 0, 2, "weighted", "peak")[0];
    assert.equal(missingCap.observedEnd, 1);
    assert.equal(
        exportObservation(atlas, missingCap).gainObservedAt,
        "2020-01-03",
    );
    atlas.stocks[0].adjusted[1] = null;
    const endpoint = exportObservation(
        atlas,
        observe(atlas, 0, 2, "return", "endpoint")[0],
    );
    assert.equal(endpoint.gainObservedAt, "2020-01-06");
    assert.equal(endpoint.gainPercent, 100);
    atlas.stocks[0].quality = ["source-check"];
    assert.equal(
        exportObservation(atlas, observe(atlas, 0, 2, "return", "peak")[0])
            .gainObservedAt,
        null,
    );
});

test("complete peak intervals retain their earliest maximum and endpoint returns ignore interior gaps", () => {
    const atlas = atlasFixture();
    atlas.dates.push("2020-01-06");
    atlas.stocks[0].adjusted = [10, 30, 30];
    const peak = observe(atlas, 0, 2, "return", "peak")[0];
    assert.equal(peak.gain, 200);
    assert.equal(peak.observedEnd, 1);
    atlas.stocks[0].adjusted[1] = null;
    const endpoint = observe(atlas, 0, 2, "return", "endpoint")[0];
    assert.equal(endpoint.gain, 200);
    assert.equal(endpoint.reason, null);
    assert.equal(endpoint.observedEnd, 2);
});

test("atlas prices and optional market caps reject coercible and invalid values", () => {
    for (const field of ["raw", "adjusted", "marketCap"] as const) {
        for (const invalid of [
            "100",
            "200",
            {},
            NaN,
            Infinity,
            -Infinity,
            0,
            -1,
            undefined,
        ]) {
            const bundle = atlasFixture();
            Object.assign(bundle.stocks[0], { [field]: [10, invalid] });
            assert.equal(
                isAtlasData(bundle),
                false,
                `${field}: ${String(invalid)}`,
            );
        }
        for (const malformed of [null, "100", {}, [10], [10, 20, 30]]) {
            const bundle = atlasFixture();
            Object.assign(bundle.stocks[0], { [field]: malformed });
            assert.equal(
                isAtlasData(bundle),
                false,
                `${field} malformed series`,
            );
        }
        const bundle = atlasFixture();
        bundle.stocks[0][field] = [10, null];
        const before = structuredClone(bundle);
        assert.equal(isAtlasData(bundle), true);
        assert.deepEqual(bundle, before);
    }
    const missingCap = atlasFixture();
    assert.equal(isAtlasData(missingCap), true);
    assert.equal(observe(missingCap, 0, 1, "return")[0].cap, null);
    assert.equal(Object.hasOwn(missingCap.stocks[0], "marketCap"), false);
});

test("atlas calendar rejects malformed, repeated and reversed observation periods", () => {
    for (const dates of [
        [],
        ["2020-01-03", "2020-01-02"],
        ["2020-01-02", "2020-01-02"],
        ["2020-02-30", "2020-03-01"],
        ["2021-02-29", "2021-03-01"],
        ["2020-13-01", "2021-01-01"],
        ["invalid", "2021-01-01"],
        ["2020-01-02T00:00:00Z", "2020-01-03"],
        [{}, "2020-01-03"],
        [null, "2020-01-03"],
    ]) {
        const atlas = atlasFixture();
        Object.assign(atlas, { dates });
        assert.equal(isAtlasData(atlas), false);
    }
    const leap = atlasFixture();
    leap.dates = ["2020-02-29", "2020-03-01"];
    assert.equal(isAtlasData(leap), true);
    assert.equal(nearestDate(leap.dates, "2020-02-29"), 0);
});

test("classification snapshots require real dates without restricting them to the quote calendar", () => {
    for (const classificationAsOf of [
        "unknown",
        "2026-99-99",
        "2025-02-29",
        "2026-1-04",
        "2026-01-04T00:00:00Z",
        "2026-02-30",
    ]) {
        const atlas = atlasFixture();
        atlas.classificationAsOf = classificationAsOf;
        assert.equal(isAtlasData(atlas), false, classificationAsOf);
    }
    for (const classificationAsOf of ["2024-02-29", "2026-10-04"]) {
        const atlas = atlasFixture();
        atlas.classificationAsOf = classificationAsOf;
        const original = structuredClone(atlas);
        assert.equal(isAtlasData(atlas), true);
        assert.deepEqual(atlas, original);
    }
});

test("atlas rendering and identity lookups require typed labels, metadata and string lists", () => {
    for (const field of ["code", "name"] as const) {
        for (const invalid of [{}, [], null, undefined, 100, "", "   "]) {
            const atlas = atlasFixture();
            Object.assign(atlas.stocks[0], { [field]: invalid });
            assert.equal(isAtlasData(atlas), false, field);
        }
    }
    for (const field of ["groupIds", "quality"] as const) {
        for (const invalid of [[{}], [null], [100], [undefined], null, {}]) {
            const atlas = atlasFixture();
            Object.assign(atlas.stocks[0], { [field]: invalid });
            assert.equal(isAtlasData(atlas), false, field);
        }
    }
    for (const groups of [
        [null],
        [{}],
        [{ id: "group", label: {} }],
        [{ id: {}, label: "group" }],
        [{ id: "", label: "group" }],
        [{ id: "group", label: "" }],
        [
            { id: "group", label: "a" },
            { id: "group", label: "b" },
        ],
    ]) {
        const atlas = atlasFixture();
        Object.assign(atlas, { groups });
        assert.equal(isAtlasData(atlas), false);
    }
    for (const replacement of [
        { catalogHash: {} },
        { catalogHash: "" },
        { classificationAsOf: {} },
        { classificationAsOf: "" },
        { limitations: [{}] },
        { limitations: null },
        { provenance: null },
        { provenance: [] },
    ]) {
        assert.equal(isAtlasData({ ...atlasFixture(), ...replacement }), false);
    }
    const duplicate = atlasFixture();
    duplicate.stocks.push(structuredClone(duplicate.stocks[0]));
    assert.equal(isAtlasData(duplicate), false);
    const valid = atlasFixture();
    valid.groups = [{ id: "group", label: "族群" }];
    valid.stocks[0].groupIds = ["group"];
    valid.stocks[0].quality = ["producer-specific-kind"];
    const before = structuredClone(valid);
    assert.equal(isAtlasData(valid), true);
    assert.equal(valid.stocks[0].code.localeCompare("B") < 0, true);
    assert.equal(
        valid.groups.find((group) => group.id === valid.stocks[0].groupIds[0])
            ?.label,
        "族群",
    );
    assert.deepEqual(valid, before);
});

test("atlas quality findings reject malformed entries before observation", () => {
    for (const qualityFindings of [
        [null],
        [42],
        [[]],
        [{}],
        null,
        "duplicate_date",
        [{ date: "2020-02-30", kind: "duplicate_date" }],
        [{ date: "not-a-date", kind: "duplicate_date" }],
        [{ date: "2020-01-02T00:00:00Z", kind: "duplicate_date" }],
        [{ date: 2020, kind: "duplicate_date" }],
        [{ date: "2020-01-02", kind: null }],
        [{ date: "2020-01-02", kind: "" }],
        [{ date: "2020-01-02", kind: "   " }],
    ]) {
        const bundle = atlasFixture();
        Object.assign(bundle.stocks[0], { qualityFindings });
        assert.equal(isAtlasData(bundle), false);
    }
    assert.equal(isAtlasData({ ...atlasFixture(), stocks: [null] }), false);
});

test("atlas quality validation preserves optional findings and open producer kind strings", () => {
    const bundle = atlasFixture();
    assert.equal(isAtlasData(bundle), true);
    assert.equal(observe(bundle, 0, 1, "return")[0].gain, 100);
    bundle.stocks[0].qualityFindings = [];
    assert.equal(isAtlasData(bundle), true);
    for (const kind of [
        "duplicate_date",
        "invalid_price_or_volume",
        "unsupported_action_factor",
        "unexplained_extreme_jump",
        "missing_or_invalid_volume",
        "additional_producer_quality_kind",
    ]) {
        bundle.stocks[0].qualityFindings = [{ date: "2020-01-02", kind }];
        const original = structuredClone(bundle);
        assert.equal(isAtlasData(bundle), true);
        assert.equal(observe(bundle, 0, 1, "return")[0].gain, null);
        assert.deepEqual(bundle, original);
    }
});
test("observation bounds require calendar lookback through each interval", () => {
    assert.deepEqual(observationBounds(253, 63, 0), {
        min: 63,
        max: 252,
        available: true,
    });
    assert.deepEqual(observationBounds(253, 126, 0), {
        min: 126,
        max: 252,
        available: true,
    });
    assert.deepEqual(observationBounds(253, 252, 0), {
        min: 252,
        max: 252,
        available: true,
    });
});
test("observation bounds retain fixed custom starts and report insufficient data", () => {
    assert.deepEqual(observationBounds(200, 0, 125), {
        min: 126,
        max: 199,
        available: true,
    });
    assert.deepEqual(observationBounds(1, 0, -5), {
        min: 0,
        max: 0,
        available: false,
    });
    assert.deepEqual(observationBounds(126, 126, 0), {
        min: 125,
        max: 125,
        available: false,
    });
    assert.deepEqual(observationBounds(0, 63, 0), {
        min: 0,
        max: 0,
        available: false,
    });
});
test("gain diameter and gentle cap weighting remain separate", () => {
    assert.equal(
        areaWeight(100, 50, "return") / areaWeight(50, 50, "return"),
        4,
    );
    assert.ok(
        Math.abs(
            areaWeight(100, 5000, "weighted") /
                areaWeight(100, 50, "weighted") -
                1.25,
        ) < 1e-12,
    );
    assert.equal(areaWeight(-50, 50, "weighted"), 0);
    assert.equal(areaWeight(100, null, "weighted"), 0);
});
test("common dates do not substitute missing endpoints or future prices", () => {
    const d = {
        schema: "market-atlas.v1",
        catalogHash: "fixture",
        classificationAsOf: "2020-01-03",
        dates: ["2020-01-01", "2020-01-02", "2020-01-03"],
        groups: [],
        provenance: {},
        limitations: [],
        stocks: [
            {
                code: "A",
                name: "A",
                groupIds: [],
                quality: [],
                raw: [10, 20, null],
                adjusted: [10, 20, null],
            },
        ],
    } satisfies AtlasData;
    assert.equal(observe(d, 0, 1, "return")[0].gain, 100);
    assert.equal(observe(d, 0, 2, "return")[0].gain, null);
    assert.equal(observe(d, -1, 1, "return")[0].gain, null);
    assert.equal(nearestDate(d.dates, "2020-01-02"), 1);
    assert.equal(observe(d, 0, 2, "return", "peak")[0].gain, null);
    assert.equal(observe(d, 0, 2, "return", "peak")[0].observedEnd, null);
    d.stocks[0].adjusted[2] = 1000;
    assert.equal(observe(d, 0, 1, "return", "peak")[0].gain, 100);
});
test("dated quality findings affect only windows crossing the flagged jump", () => {
    const d: AtlasData = {
        schema: "market-atlas.v1",
        catalogHash: "fixture",
        classificationAsOf: "2020-01-03",
        dates: ["2020-01-01", "2020-01-02", "2020-01-03"],
        groups: [],
        provenance: {},
        limitations: [],
        stocks: [
            {
                code: "A",
                name: "A",
                groupIds: [],
                quality: [],
                qualityFindings: [
                    { date: "2020-01-03", kind: "unexplained_extreme_jump" },
                ],
                raw: [10, 20, 300],
                adjusted: [10, 20, 300],
            },
        ],
    };
    assert.equal(observe(d, 0, 1, "return")[0].gain, 100);
    assert.equal(observe(d, 0, 2, "return")[0].gain, null);
});

test("duplicate dates block both interval boundaries but not a date before the start", () => {
    const d: AtlasData = {
        schema: "market-atlas.v1",
        catalogHash: "fixture",
        classificationAsOf: "2020-01-04",
        dates: ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"],
        groups: [],
        provenance: {},
        limitations: [],
        stocks: [
            {
                code: "A",
                name: "A",
                groupIds: [],
                quality: [],
                // The exporter retains one price even when the date is duplicated.
                raw: [10, 20, 40, 30],
                adjusted: [10, 20, 40, 30],
                marketCap: [50, 50, 50, 50],
            },
        ],
    };
    for (const flaggedIndex of [0, 1, 3]) {
        d.stocks[0].qualityFindings = [
            { date: d.dates[flaggedIndex], kind: "duplicate_date" },
        ];
        for (const measure of ["endpoint", "peak"] as const) {
            for (const encoding of ["return", "weighted"] as const) {
                const observation = observe(d, 1, 3, encoding, measure)[0];
                if (flaggedIndex === 0) {
                    const gain = measure === "peak" ? 100 : 50;
                    assert.equal(observation.gain, gain);
                    assert.equal(observation.reason, null);
                    assert.equal(
                        observation.weight,
                        areaWeight(gain, 50, encoding),
                    );
                } else {
                    assert.equal(observation.gain, null);
                    assert.equal(
                        observation.observedEnd,
                        measure === "peak" ? null : 3,
                    );
                    assert.notEqual(observation.reason, null);
                    assert.equal(observation.weight, 0);
                }
            }
        }
    }
});
