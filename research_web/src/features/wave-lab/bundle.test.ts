import assert from "node:assert/strict";
import test from "node:test";
import { validateLabBundle } from "./bundle.ts";
import type { LabBundle } from "./types.ts";

function fixture(): LabBundle {
    return {
        schema: "wave-lab-cases.v1",
        projectionHash: "declared-price-source",
        catalogHash: "declared-catalog",
        cases: [
            {
                id: "case-1",
                name: "Recorded case",
                kind: "historical",
                category: "Shared category",
                question: "Where did the rise begin?",
                points: [
                    "2020-01-02",
                    "2020-01-03",
                    "2020-01-06",
                    "2020-01-07",
                    "2020-01-08",
                ].map((date) => ({ date, raw: 10, adjusted: 8, flags: [] })),
                source: {
                    label: "Recorded source",
                    from: "2020-01-02",
                    to: "2020-01-08",
                    priceBasis: "split-adjusted close",
                    limitations: [],
                },
            },
        ],
    };
}

test("rejects incomplete cases before any points reach the page", () => {
    for (const points of [undefined, null, [], {}, "points"]) {
        const bundle = fixture();
        Object.assign(bundle.cases[0], { points });
        assert.throws(() => validateLabBundle(bundle), /case.points/);
    }
    for (const value of [
        null,
        [],
        {},
        { schema: "wave-lab-cases.v1", cases: [{}] },
    ])
        assert.throws(() => validateLabBundle(value), /案例格式不符/);
    for (const key of ["projectionHash", "catalogHash"]) {
        for (const value of [undefined, null, 1, "", " "]) {
            const bundle = fixture();
            Object.assign(bundle, { [key]: value });
            assert.throws(() => validateLabBundle(bundle), new RegExp(key));
        }
    }
});

test("case IDs are unique while names and categories may legitimately repeat", () => {
    const bundle = fixture();
    bundle.cases.push(structuredClone(bundle.cases[0]));
    assert.throws(() => validateLabBundle(bundle), /duplicate case.id/);
    bundle.cases[1].id = "case-2";
    assert.strictEqual(validateLabBundle(bundle), bundle);
    for (const key of ["id", "name", "category", "question"]) {
        for (const value of [undefined, null, {}, "", " "]) {
            const bad = fixture();
            Object.assign(bad.cases[0], { [key]: value });
            assert.throws(
                () => validateLabBundle(bad),
                new RegExp(`case.${key}`),
            );
        }
    }
    const badKind = fixture();
    Object.assign(badKind.cases[0], { kind: "unknown" });
    assert.throws(() => validateLabBundle(badKind), /case.kind/);
});

test("points require real unique increasing dates and positive finite or null prices", () => {
    for (const date of [
        "2020-02-30",
        "not-a-date",
        "2020-1-02",
        "2020-01-02T00:00:00Z",
    ]) {
        const bundle = fixture();
        bundle.cases[0].points[0].date = date;
        assert.throws(() => validateLabBundle(bundle), /point.date/);
    }
    const duplicate = fixture();
    duplicate.cases[0].points[1].date = duplicate.cases[0].points[0].date;
    assert.throws(() => validateLabBundle(duplicate), /point.date order/);
    const reversed = fixture();
    reversed.cases[0].points.reverse();
    assert.throws(() => validateLabBundle(reversed), /point.date order/);
    for (const key of ["raw", "adjusted"]) {
        for (const value of [undefined, 0, -1, NaN, Infinity, "10", {}]) {
            const bundle = fixture();
            Object.assign(bundle.cases[0].points[0], { [key]: value });
            assert.throws(
                () => validateLabBundle(bundle),
                new RegExp(`point.${key}`),
            );
        }
    }
    for (const flags of [undefined, null, {}, [1], [null]]) {
        const bundle = fixture();
        Object.assign(bundle.cases[0].points[0], { flags });
        assert.throws(() => validateLabBundle(bundle), /point.flags/);
    }
});

test("source fields must be readable and match the point calendar endpoints", () => {
    for (const source of [undefined, null, [], "source"]) {
        const bundle = fixture();
        Object.assign(bundle.cases[0], { source });
        assert.throws(() => validateLabBundle(bundle), /source/);
    }
    for (const key of ["label", "priceBasis", "from", "to"]) {
        const bundle = fixture();
        Object.assign(bundle.cases[0].source, { [key]: {} });
        assert.throws(() => validateLabBundle(bundle), /source/);
    }
    for (const changes of [
        { from: "2020-01-03" },
        { to: "2020-01-07" },
        { from: "2019-12-31" },
        { to: "2020-02-30" },
        { limitations: [1] },
        { hash: {} },
        { catalogHash: null },
    ]) {
        const bundle = fixture();
        Object.assign(bundle.cases[0].source, changes);
        assert.throws(() => validateLabBundle(bundle), /source/);
    }
});

test("single-point synthetic cases preserve null prices, flags and additive fields", () => {
    const bundle = fixture();
    const sample = bundle.cases[0];
    sample.kind = "synthetic";
    sample.points = [
        {
            date: "2020-02-29",
            raw: null,
            adjusted: null,
            flags: ["missing", ""],
        },
    ];
    Object.assign(sample.source, {
        from: "2020-02-29",
        to: "2020-02-29",
        hash: "declared hash",
        catalogHash: "",
        extension: { kept: true },
    });
    Object.assign(bundle, { extension: { kept: true } });
    const original = structuredClone(bundle);
    assert.strictEqual(validateLabBundle(bundle), bundle);
    assert.deepEqual(bundle, original);
});

function selectedFixture(): LabBundle {
    const bundle = fixture();
    bundle.cases[0].selectedOpportunity = {
        securityId: "TW:1111",
        waveId: "wave-1",
        sourceId: "saved-wave",
        start: "2020-01-03",
        peakDate: "2020-01-06",
        observedThrough: "2020-01-07",
        endConfirmedAt: null,
        scale: "large",
        leftCensored: false,
        rightCensored: true,
        launch: {
            date: "2020-01-03",
            rangeFrom: "2020-01-02",
            rangeUntil: "2020-01-08",
            sourceId: "saved-launch",
        },
    };
    return bundle;
}

test("selected opportunities require safe fields, point-calendar references and ordered boundaries", () => {
    for (const changes of [
        { securityId: "" },
        { waveId: {} },
        { sourceId: null },
        { scale: 1 },
        { leftCensored: "false" },
        { rightCensored: undefined },
        { start: "2020-01-04" },
        { peakDate: "2020-01-02" },
        { observedThrough: "2020-01-03" },
        { endConfirmedAt: "2020-01-08" },
        { endConfirmedAt: undefined },
        { launch: undefined },
    ]) {
        const bundle = selectedFixture();
        Object.assign(bundle.cases[0].selectedOpportunity!, changes);
        assert.throws(() => validateLabBundle(bundle), /selectedOpportunity/);
    }
    for (const changes of [
        { sourceId: {} },
        { date: "2020-01-02" },
        { rangeFrom: "2020-01-04" },
        { rangeFrom: "2020-01-06" },
        { rangeUntil: "2020-01-02" },
        { rangeUntil: "2020-01-09" },
    ]) {
        const bundle = selectedFixture();
        Object.assign(bundle.cases[0].selectedOpportunity!.launch!, changes);
        assert.throws(
            () => validateLabBundle(bundle),
            /selectedOpportunity.launch/,
        );
    }
    const noLaunch = selectedFixture();
    noLaunch.cases[0].selectedOpportunity!.launch = null;
    assert.doesNotThrow(() => validateLabBundle(noLaunch));
});

test("cross-scale launch ranges stay intact even outside the selected wave", () => {
    const bundle = selectedFixture();
    const original = structuredClone(bundle);
    assert.strictEqual(validateLabBundle(bundle), bundle);
    assert.deepEqual(bundle, original);
});

test("confirmed ends cannot precede the peak but may coincide with it", () => {
    const earlyEnd = selectedFixture();
    const selected = earlyEnd.cases[0].selectedOpportunity!;
    selected.start = "2020-01-02";
    selected.endConfirmedAt = "2020-01-03";
    selected.launch = null;
    assert.throws(
        () => validateLabBundle(earlyEnd),
        /selectedOpportunity.endConfirmedAt boundaries/,
    );
    for (const end of ["2020-01-06", "2020-01-07", null]) {
        const bundle = selectedFixture();
        bundle.cases[0].selectedOpportunity!.endConfirmedAt = end;
        const original = structuredClone(bundle);
        assert.strictEqual(validateLabBundle(bundle), bundle);
        assert.deepEqual(bundle, original);
    }
});

test("a declared peak rejects any higher valid adjusted price inside the observed interval", () => {
    for (const index of [1, 3]) {
        const bundle = selectedFixture();
        bundle.cases[0].points[index].adjusted = 9;
        assert.throws(
            () => validateLabBundle(bundle),
            /selectedOpportunity.peakDate.*maximum/,
        );
    }
    const partial = selectedFixture();
    partial.cases[0].points[1].adjusted = null;
    partial.cases[0].points[3].adjusted = 9;
    assert.throws(
        () => validateLabBundle(partial),
        /selectedOpportunity.peakDate.*maximum/,
    );
});

test("equal peaks and higher prices outside the selected interval remain valid", () => {
    const bundle = selectedFixture();
    bundle.cases[0].points[0].adjusted = 100;
    bundle.cases[0].points[4].adjusted = 100;
    bundle.cases[0].points[1].raw = 100;
    const original = structuredClone(bundle);
    assert.strictEqual(validateLabBundle(bundle), bundle);
    assert.deepEqual(bundle, original);
});

test("missing or flagged peak prices retain an unknown maximum without filling prices", () => {
    for (const unknownPeak of ["missing", "flagged"]) {
        const bundle = selectedFixture();
        const peak = bundle.cases[0].points[2];
        if (unknownPeak === "missing") peak.adjusted = null;
        else peak.flags = ["unreliable quote"];
        bundle.cases[0].points[3].adjusted = 100;
        const original = structuredClone(bundle);
        assert.strictEqual(validateLabBundle(bundle), bundle);
        assert.deepEqual(bundle, original);
    }
    const partial = selectedFixture();
    partial.cases[0].points[1].adjusted = null;
    partial.cases[0].points[3].adjusted = 100;
    partial.cases[0].points[3].flags = ["unreliable quote"];
    const original = structuredClone(partial);
    assert.strictEqual(validateLabBundle(partial), partial);
    assert.deepEqual(partial, original);
});
