import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import {
    buildMarketView,
    calculateParticipation,
    comparePortfolio,
    getHoldingState,
    POSITIVE_MOVE_SHARE_VERSION,
    validateBundle,
} from "./model.ts";
import type { OpportunityBundle, OpportunityPortfolio } from "./types.ts";

const DAYS = [
    "2026-09-28",
    "2026-09-29",
    "2026-09-30",
    "2026-10-01",
    "2026-10-02",
    "2026-10-05",
];
const UNTIL = "2026-10-06";
function near(actual: number | null, expected: number) {
    assert.notEqual(actual, null);
    assert.ok(Math.abs(actual! - expected) < 1e-10, `${actual} != ${expected}`);
}
function fixture(): OpportunityBundle {
    return {
        schema: "opportunity-explorer.v1",
        id: "fixture",
        label: "Deterministic fixture",
        kind: "synthetic",
        asOf: DAYS[5],
        dates: [...DAYS],
        priceBasis: "adjusted-close",
        catalogCoverage: "declared-universe",
        ruleVersion: "rules.v1",
        selectionPolicy: "explicit-interval.v1",
        classificationVersion: "industry.v1",
        sources: [{ id: "source", label: "Fixture", hash: "fixture-hash" }],
        limitations: [],
        securities: [
            {
                id: "A",
                code: "A",
                name: "A",
                market: "TW",
                currency: "TWD",
                industry: [
                    {
                        id: "tech",
                        label: "Technology",
                        from: DAYS[0],
                        untilExclusive: null,
                        basis: "historical",
                        sourceId: "source",
                    },
                ],
                prices: [100, 110, 121, 110, 132, 145.2].map((close, i) => ({
                    date: DAYS[i],
                    close,
                    flags: [],
                })),
            },
        ],
        waves: [
            {
                id: "wave-A",
                securityId: "A",
                start: DAYS[0],
                launch: {
                    date: DAYS[1],
                    rangeFrom: DAYS[1],
                    rangeUntil: DAYS[1],
                    sourceId: "source",
                },
                launchMissingReason: null,
                peakDate: DAYS[5],
                endConfirmedAt: null,
                observedThrough: DAYS[5],
                leftCensored: false,
                rightCensored: true,
                scale: "large",
                parentId: null,
                sourceId: "source",
                phases: [
                    { from: DAYS[0], untilExclusive: DAYS[1], kind: "slow" },
                    { from: DAYS[1], untilExclusive: DAYS[3], kind: "rising" },
                    { from: DAYS[3], untilExclusive: DAYS[4], kind: "resting" },
                    { from: DAYS[4], untilExclusive: UNTIL, kind: "rising" },
                ],
            },
        ],
        representatives: [
            {
                securityId: "A",
                waveId: "wave-A",
                from: DAYS[0],
                untilExclusive: UNTIL,
            },
        ],
        portfolios: [
            {
                id: "strategy",
                name: "Strategy",
                kind: "strategy",
                description: "Fixture portfolio",
                sourceIds: ["source"],
                coverage: [
                    {
                        from: DAYS[0],
                        untilExclusive: UNTIL,
                        completeness: "full",
                        kind: "event-replay",
                        sourceId: "source",
                    },
                ],
                holdings: [
                    {
                        securityId: "A",
                        from: DAYS[0],
                        untilExclusive: UNTIL,
                        sourceId: "source",
                        quantity: 10,
                    },
                ],
                allocations: [
                    {
                        date: DAYS[4],
                        completeness: "full",
                        nav: 1000,
                        cashWeight: 0.4,
                        positions: [{ securityId: "A", weight: 0.6 }],
                        sourceId: "source",
                    },
                ],
                limitations: [],
            },
        ],
    };
}

test("reserved unknown industry ID prevents real classifications merging with missing memberships", () => {
    const bundle = fixture();
    bundle.securities[0].industry[0].id = "unknown";
    const other = structuredClone(bundle.securities[0]);
    other.id = "B";
    other.code = "B";
    other.industry = [];
    bundle.securities.push(other);
    bundle.waves.push({
        ...structuredClone(bundle.waves[0]),
        id: "wave-B",
        securityId: "B",
    });
    bundle.representatives.push({
        securityId: "B",
        waveId: "wave-B",
        from: DAYS[0],
        untilExclusive: UNTIL,
    });
    // Raw map calculation illustrates the collision that import must reject.
    const view = buildMarketView(bundle, DAYS[4]);
    assert.equal(view.active.length, 2);
    assert.equal(view.industries.length, 1);
    assert.equal(view.industries[0].label, "Technology");
    assert.equal(view.industries[0].rows.length, 2);
    assert.throws(() => validateBundle(bundle), /reserved unknown industry id/);
});
test("reserved unknown industry ID rejects every real classification basis", () => {
    for (const basis of [
        "historical",
        "document-period",
        "current-snapshot",
    ] as const) {
        const bundle = fixture();
        bundle.securities[0].industry[0] = {
            ...bundle.securities[0].industry[0],
            id: "unknown",
            label: "產業資料未知",
            basis,
        };
        assert.throws(
            () => validateBundle(bundle),
            /reserved unknown industry id/,
            basis,
        );
    }
});
test("reserved unknown placeholder remains readable and preserves the synthetic group label", () => {
    const bundle = fixture();
    const membership = bundle.securities[0].industry[0];
    membership.id = "unknown";
    membership.label = "產業資料未知";
    membership.basis = "unknown";
    const validated = validateBundle(bundle);
    assert.equal(validated.securities[0].industry[0], membership);
    const view = buildMarketView(validated, DAYS[4]);
    assert.equal(view.industries[0].id, membership.id);
    assert.equal(view.industries[0].label, membership.label);
    for (const label of ["Other label", " 產業資料未知 "]) {
        membership.label = label;
        assert.throws(
            () => validateBundle(bundle),
            /reserved unknown industry id/,
        );
    }
});
test("unknown basis keeps other source group IDs and labels compatible", () => {
    const bundle = fixture();
    bundle.securities[0].industry[0].basis = "unknown";
    const validated = validateBundle(bundle);
    assert.equal(validated.securities[0].industry[0].id, "tech");
    assert.equal(validated.securities[0].industry[0].label, "Technology");
    assert.equal(
        buildMarketView(validated, DAYS[4]).industries[0].id,
        "unknown",
    );
});
test("shared reader rejects overlapping group label conflicts across stocks", () => {
    for (const reverse of [false, true]) {
        const bundle = fixture();
        const other = structuredClone(bundle.securities[0]);
        other.id = "B";
        other.code = "B";
        other.industry[0].label = "Conflicting technology label";
        bundle.securities.push(other);
        if (reverse) bundle.securities.reverse();
        assert.throws(
            () => validateBundle(bundle),
            /overlapping group label conflict/,
        );
    }
});
test("shared reader validates labels across overlapping bases on the same stock", () => {
    for (const reverse of [false, true]) {
        const bundle = fixture();
        const memberships = bundle.securities[0].industry;
        memberships.push({ ...memberships[0], basis: "document-period" });
        assert.doesNotThrow(() => validateBundle(bundle));
        memberships[1].label = "Conflicting document label";
        if (reverse) memberships.reverse();
        assert.throws(
            () => validateBundle(bundle),
            /overlapping group label conflict/,
        );
    }
});
test("shared reader accepts matching labels for the same or different group IDs", () => {
    for (const groupId of ["tech", "other-tech"]) {
        const bundle = fixture();
        const other = structuredClone(bundle.securities[0]);
        other.id = "B";
        other.code = "B";
        other.industry[0].id = groupId;
        other.industry[0].untilExclusive = DAYS[3];
        bundle.securities.push(other);
        assert.doesNotThrow(() => validateBundle(bundle));
    }
});
test("shared reader allows label changes between nonoverlapping half-open periods", () => {
    for (const reverse of [false, true]) {
        const bundle = fixture();
        const other = structuredClone(bundle.securities[0]);
        other.id = "B";
        other.code = "B";
        bundle.securities[0].industry[0].untilExclusive = DAYS[3];
        other.industry[0].from = DAYS[3];
        other.industry[0].label = "Later technology label";
        bundle.securities.push(other);
        if (reverse) bundle.securities.reverse();
        assert.doesNotThrow(() => validateBundle(bundle));
    }
});
test("explicit representatives determine membership and keep selected-date gain separate from retrospective peak", () => {
    const bundle = validateBundle(fixture());
    assert.equal(buildMarketView(bundle, DAYS[0]).unlaunched.length, 1);
    const view = buildMarketView(bundle, DAYS[3]);
    assert.equal(view.active.length, 1);
    assert.equal(view.active[0].phase, "resting");
    near(view.active[0].gain, 10);
    near(view.active[0].launchGain, 0);
    near(view.active[0].peakGain, 45.2);
    assert.throws(
        () => buildMarketView(bundle, "2026-10-03"),
        /not in bundle calendar/,
    );
});

test("launch and confirmed end are half-open; missing launch remains unlaunched", () => {
    const bundle = fixture();
    bundle.waves[0].phases = bundle.waves[0].phases.slice(0, 3);
    bundle.waves[0].endConfirmedAt = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].observedThrough = DAYS[4];
    bundle.waves[0].rightCensored = false;
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[4]).ended.length,
        1,
    );
    assert.equal(buildMarketView(bundle, DAYS[3]).active.length, 1);
    bundle.waves[0].launch = null;
    bundle.waves[0].launchMissingReason = "not-confirmed";
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[3]).unlaunched.length,
        1,
    );
});

test("end confirmation cannot precede the declared peak, including after launch", () => {
    const bundle = fixture();
    bundle.waves[0].endConfirmedAt = DAYS[4];
    assert.throws(
        () => validateBundle(bundle),
        /wave.endConfirmedAt.*at or after peak/,
    );
    bundle.waves[0].endConfirmedAt = DAYS[5];
    bundle.waves[0].phases.at(-1)!.untilExclusive = DAYS[5];
    assert.doesNotThrow(() => validateBundle(bundle));
});

test("missing or gapped phase evidence remains unknown without inventing a stage", () => {
    const bundle = fixture();
    bundle.waves[0].phases = [];
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[4]).active[0].phase,
        null,
    );
    bundle.waves[0].phases = [
        { from: DAYS[1], untilExclusive: DAYS[3], kind: "rising" },
    ];
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[2]).active[0].phase,
        "rising",
    );
    assert.equal(buildMarketView(bundle, DAYS[3]).active[0].phase, null);
    assert.equal(buildMarketView(bundle, DAYS[0]).unlaunched[0].phase, null);
});

test("phases stay within the inclusive observation day and reject unbounded or future intervals", () => {
    const bundle = fixture();
    const original = structuredClone(bundle);
    assert.strictEqual(validateBundle(bundle), bundle);
    assert.deepEqual(bundle, original);
    assert.equal(buildMarketView(bundle, DAYS[5]).active[0].phase, "rising");
    for (const phase of [
        { from: DAYS[4], untilExclusive: "2099-01-01", kind: "rising" },
        { from: "2026-10-06", untilExclusive: "2026-10-07", kind: "rising" },
        { from: DAYS[4], untilExclusive: null, kind: "rising" },
    ]) {
        const invalid = fixture();
        Object.assign(invalid.waves[0], { phases: [phase] });
        assert.throws(
            () => validateBundle(invalid),
            /phase\.(from|untilExclusive)/,
        );
    }
});

test("confirmed phase ends are exclusive even when later prices remain observed", () => {
    const bundle = fixture();
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].endConfirmedAt = DAYS[5];
    bundle.securities[0].prices[5].close = 120;
    bundle.waves[0].phases.at(-1)!.untilExclusive = DAYS[5];
    const before = structuredClone(bundle);
    assert.strictEqual(validateBundle(bundle), bundle);
    assert.deepEqual(bundle, before);
    assert.equal(buildMarketView(bundle, DAYS[4]).active[0].phase, "rising");
    assert.equal(buildMarketView(bundle, DAYS[5]).ended[0].phase, null);
    for (const phase of [
        { from: DAYS[4], untilExclusive: UNTIL, kind: "rising" },
        { from: DAYS[5], untilExclusive: UNTIL, kind: "retreat" },
    ]) {
        const invalid = structuredClone(bundle);
        Object.assign(invalid.waves[0], { phases: [phase] });
        assert.throws(
            () => validateBundle(invalid),
            /phase\.(from|untilExclusive)/,
        );
    }
});

test("a confirmed end must be an observed calendar date, without inventing a quote for it", () => {
    const bundle = fixture();
    bundle.waves[0].phases = bundle.waves[0].phases.slice(0, 3);
    bundle.waves[0].endConfirmedAt = "2026-10-03";
    assert.throws(
        () => validateBundle(bundle),
        /wave.endConfirmedAt.*calendar/,
    );
    bundle.waves[0].endConfirmedAt = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].observedThrough = DAYS[4];
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[5]).ended.length,
        1,
    );
    bundle.securities[0].prices[4].close = null;
    const row = buildMarketView(validateBundle(bundle), DAYS[5]).unknown[0];
    assert.equal(row.reason, "missing-or-flagged-price");
    assert.equal(row.endGain, null);
});

test("end gain starts at confirmation, remains distinct from D gain, and survives the cutoff", () => {
    const bundle = fixture();
    bundle.waves[0].phases = bundle.waves[0].phases.slice(0, 3);
    assert.equal(buildMarketView(bundle, DAYS[4]).active[0].endGain, null);
    bundle.waves[0].endConfirmedAt = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].observedThrough = DAYS[4];
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[3]).active[0].endGain,
        null,
    );
    let row = buildMarketView(bundle, DAYS[5]).ended[0];
    near(row.endGain, 32);
    assert.equal(row.gain, null);
    bundle.waves[0].observedThrough = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    row = buildMarketView(validateBundle(bundle), DAYS[5]).ended[0];
    assert.equal(row.gain, null);
    near(row.endGain, 32);
    bundle.securities[0].prices[5].close = null;
    near(buildMarketView(bundle, DAYS[5]).ended[0].endGain, 32);
    bundle.securities[0].prices[2].close = null;
    assert.equal(buildMarketView(bundle, DAYS[5]).unknown[0].endGain, null);
});

test("returns and participation never extend a confirmed wave into a later rally", () => {
    const bundle = fixture();
    bundle.waves[0].phases = bundle.waves[0].phases.slice(0, 3);
    bundle.waves[0].endConfirmedAt = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].observedThrough = DAYS[4];
    const atEnd = buildMarketView(validateBundle(bundle), DAYS[4]).ended[0];
    near(atEnd.gain, 32);
    near(atEnd.launchGain, 20);
    near(atEnd.endGain, 32);
    assert.notEqual(
        calculateParticipation(bundle, atEnd, bundle.portfolios[0], DAYS[4])
            .positiveMoveShare,
        null,
    );
    const afterEnd = buildMarketView(bundle, DAYS[5]).ended[0];
    assert.equal(afterEnd.gain, null);
    assert.equal(afterEnd.launchGain, null);
    near(afterEnd.endGain, 32);
    near(afterEnd.peakGain, 32);
    const comparison = calculateParticipation(
        bundle,
        afterEnd,
        bundle.portfolios[0],
        DAYS[5],
    );
    assert.equal(comparison.reason, "outside-wave-observation");
    assert.equal(comparison.positiveMoveShare, null);
    assert.equal(comparison.heldDayShare, null);
});

test("a cross-scale launch range uses the source calendar without being silently cropped to one wave", () => {
    for (const scenario of [
        "before-calendar",
        "after-calendar",
        "off-calendar",
    ]) {
        const bundle = fixture();
        if (scenario === "before-calendar")
            bundle.waves[0].launch!.rangeFrom = "2026-09-25";
        else if (scenario === "after-calendar")
            bundle.waves[0].launch!.rangeUntil = "2026-10-07";
        else bundle.waves[0].launch!.rangeUntil = "2026-10-03";
        assert.throws(() => validateBundle(bundle), /wave.launch/);
    }
    const bundle = fixture();
    bundle.waves[0].phases = [];
    bundle.waves[0].start = DAYS[1];
    bundle.waves[0].observedThrough = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].launch!.rangeFrom = DAYS[0];
    bundle.waves[0].launch!.rangeUntil = DAYS[5];
    const original = structuredClone(bundle.waves[0].launch);
    assert.doesNotThrow(() => validateBundle(bundle));
    assert.deepEqual(bundle.waves[0].launch, original);
});

test("price quality never manufactures an exit; confirmed end survives later censoring", () => {
    const bundle = fixture();
    bundle.waves[0].phases = bundle.waves[0].phases.slice(0, 3);
    bundle.waves[0].endConfirmedAt = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].observedThrough = DAYS[4];
    bundle.securities[0].prices[4].flags = ["suspended"];
    let view = buildMarketView(validateBundle(bundle), DAYS[4]);
    assert.equal(view.ended.length, 0);
    assert.equal(view.unknown[0].reason, "missing-or-flagged-price");
    assert.equal(view.unknown[0].gain, null);
    bundle.securities[0].prices[4].flags = [];
    bundle.waves[0].observedThrough = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    view = buildMarketView(validateBundle(bundle), DAYS[5]);
    assert.equal(view.active.length, 0);
    assert.equal(view.ended.length, 1);
    assert.equal(view.ended[0].gain, null);
    near(buildMarketView(bundle, DAYS[4]).ended[0].gain, 32);
    const participation = calculateParticipation(
        bundle,
        view.ended[0],
        bundle.portfolios[0],
        DAYS[5],
    );
    assert.equal(participation.positiveMoveShare, null);
    assert.equal(participation.heldDayShare, null);
    assert.equal(participation.held, "unknown");
    bundle.waves[0].endConfirmedAt = null;
    view = buildMarketView(bundle, DAYS[5]);
    assert.equal(view.ended.length, 0);
    assert.equal(view.unknown[0].reason, "after-observed-through");
});

test("the observation cutoff hides later prices and phases while preserving confirmed end and retrospective peak", () => {
    for (const confirmed of [false, true]) {
        const bundle = fixture();
        bundle.waves[0].observedThrough = DAYS[4];
        bundle.waves[0].peakDate = DAYS[4];
        bundle.waves[0].endConfirmedAt = confirmed ? DAYS[4] : null;
        // The reader still defends an unvalidated input whose phase outlives its cutoff.
        assert.throws(
            () => validateBundle(bundle),
            /phase\.(from|untilExclusive)/,
        );
        const within = buildMarketView(bundle, DAYS[4]).rows[0];
        near(within.price, 132);
        assert.equal(within.phase, "rising");
        const after = buildMarketView(bundle, DAYS[5]).rows[0];
        assert.equal(after.state, confirmed ? "ended" : "unknown");
        assert.equal(after.price, null);
        assert.equal(after.phase, null);
        assert.equal(after.gain, null);
        near(after.peakGain, 32);
        if (confirmed) near(after.endGain, 32);
        else assert.equal(after.endGain, null);
    }
});

test("retrospective peak stays unknown when any part of its observed interval is missing or flagged", () => {
    const bundle = fixture();
    bundle.waves[0].peakDate = DAYS[2];
    bundle.securities[0].prices[4].close = 115;
    bundle.securities[0].prices[5].close = 115;
    bundle.securities[0].prices[4].flags = ["unknown-adjustment"];
    const row = buildMarketView(validateBundle(bundle), DAYS[4]).unknown[0];
    assert.equal(row.gain, null);
    assert.equal(row.peakGain, null);
    bundle.securities[0].prices[4].flags = [];
    near(
        buildMarketView(validateBundle(bundle), DAYS[4]).active[0].peakGain,
        21,
    );
    bundle.securities[0].prices[5].close = null;
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[4]).active[0].peakGain,
        null,
    );
    bundle.securities[0].prices = [];
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[4]).unknown[0].peakGain,
        null,
    );
});

test("import rejects a nonmaximal peak, accepts ties and ignores quotes after the observation cutoff", () => {
    const bundle = fixture();
    bundle.waves[0].peakDate = DAYS[2];
    assert.throws(() => validateBundle(bundle), /peakDate.*interval maximum/);
    bundle.securities[0].prices[3].close = null;
    assert.throws(() => validateBundle(bundle), /peakDate.*interval maximum/);
    bundle.securities[0].prices[3].close = 110;
    bundle.securities[0].prices[4].close = 121;
    bundle.waves[0].observedThrough = DAYS[4];
    bundle.waves[0].phases.at(-1)!.untilExclusive = "2026-10-03";
    assert.doesNotThrow(() => validateBundle(bundle));
    near(buildMarketView(bundle, DAYS[4]).active[0].peakGain, 21);
    bundle.waves[0].peakDate = DAYS[4];
    assert.doesNotThrow(() => validateBundle(bundle));
});

test("a synthetic saved catalog validates and a forged peak fails browser import", () => {
    const bundle = fixture();
    bundle.waves[0].start = DAYS[1];
    bundle.waves[0].launch!.rangeFrom = DAYS[0];
    bundle.waves[0].phases = [];
    assert.doesNotThrow(() => validateBundle(bundle));
    const steelWave = bundle.waves[0];
    assert.ok(
        steelWave.launch!.rangeFrom < steelWave.start,
        "the preserved cross-scale launch range can precede this wave start",
    );
    const wave = bundle.waves[0];
    wave.peakDate = wave.start;
    assert.throws(() => validateBundle(bundle), /peakDate.*interval maximum/);
});

test("a missing intermediate or observation price makes a row unknown", () => {
    for (const index of [2, 4]) {
        const bundle = fixture();
        bundle.securities[0].prices.splice(index, 1);
        const view = buildMarketView(validateBundle(bundle), DAYS[4]);
        assert.equal(view.active.length, 0);
        assert.equal(view.unknown[0].gain, null);
        assert.equal(
            calculateParticipation(
                bundle,
                view.unknown[0],
                bundle.portfolios[0],
                DAYS[4],
            ).positiveMoveShare,
            null,
        );
    }
});

test("one declared scale wins without daily maximum-return selection", () => {
    const bundle = fixture();
    bundle.waves.push({
        ...structuredClone(bundle.waves[0]),
        id: "small-A",
        start: DAYS[2],
        launch: {
            date: DAYS[2],
            rangeFrom: DAYS[2],
            rangeUntil: DAYS[2],
            sourceId: "source",
        },
        parentId: "wave-A",
        scale: "small",
        phases: [],
    });
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[4]).rows.length,
        1,
    );
    bundle.representatives[0].waveId = "small-A";
    const view = buildMarketView(validateBundle(bundle), DAYS[4]);
    assert.equal(view.active.length, 1);
    assert.equal(view.active[0].wave.id, "small-A");
    near(view.active[0].gain, (132 / 121 - 1) * 100);
    bundle.representatives = [];
    const unknown = buildMarketView(validateBundle(bundle), DAYS[4]);
    assert.equal(unknown.active.length, 0);
    assert.equal(unknown.unknown.length, 2);
    assert.ok(
        unknown.unknown.every(
            (row) => row.reason === "missing-representative-interval",
        ),
    );
    assert.equal(
        buildMarketView(bundle, DAYS[1]).rows.find(
            (row) => row.wave.id === "small-A",
        )!.state,
        "outside",
    );
});

test("area has a fixed cross-date square scale with no positive floor", () => {
    const bundle = fixture();
    bundle.waves[0].launch!.date = DAYS[0];
    bundle.waves[0].launch!.rangeFrom = DAYS[0];
    bundle.waves[0].launch!.rangeUntil = DAYS[0];
    bundle.securities[0].prices[1].close = 150;
    bundle.securities[0].prices[2].close = 200;
    assert.equal(buildMarketView(bundle, DAYS[0]).active[0].weight, 0);
    near(buildMarketView(bundle, DAYS[1]).active[0].weight, 0.25);
    near(buildMarketView(bundle, DAYS[2]).active[0].weight, 1);
    bundle.securities[0].prices[3].close = 90;
    assert.equal(buildMarketView(bundle, DAYS[3]).active[0].weight, 0);
    near(buildMarketView(bundle, DAYS[3]).industries[0].maxGain, -10);
});

test("industry sorting uses sum of returns, preserves max label, and resolves historical intervals", () => {
    const bundle = fixture();
    const second = structuredClone(bundle.securities[0]);
    second.id = "B";
    second.code = "B";
    second.prices[4].close = 150;
    bundle.securities[0].prices[4].close = 200;
    bundle.securities.push(second);
    bundle.waves.push({
        ...structuredClone(bundle.waves[0]),
        id: "wave-B",
        securityId: "B",
    });
    // Both rewritten price paths now peak before the final quote.
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[1].peakDate = DAYS[4];
    bundle.representatives.push({
        securityId: "B",
        waveId: "wave-B",
        from: DAYS[0],
        untilExclusive: UNTIL,
    });
    let view = buildMarketView(validateBundle(bundle), DAYS[4]);
    assert.equal(view.industries[0].gainSum, 150);
    assert.equal(view.industries[0].maxGain, 100);
    assert.equal(
        view.active.reduce((sum, row) => sum + row.weight, 0),
        1.25,
    );
    second.industry[0].untilExclusive = DAYS[4];
    second.industry.push({
        ...second.industry[0],
        id: "new",
        label: "New industry",
        from: DAYS[4],
        untilExclusive: null,
    });
    view = buildMarketView(validateBundle(bundle), DAYS[4]);
    assert.equal(
        view.active.find((row) => row.security.id === "B")!.industry.id,
        "new",
    );
    second.industry[1].basis = "current-snapshot";
    assert.equal(
        buildMarketView(validateBundle(bundle), DAYS[4]).active.find(
            (row) => row.security.id === "B",
        )!.industry.id,
        "unknown",
    );
});

function classificationFixture(): OpportunityBundle {
    const dates = [
        "2020-12-31",
        "2021-01-04",
        "2021-06-01",
        "2021-12-31",
        "2022-01-03",
        "2022-01-04",
    ];
    const replacements = new Map(DAYS.map((day, index) => [day, dates[index]]));
    replacements.set(UNTIL, "2022-01-05");
    const bundle = JSON.parse(
        JSON.stringify(fixture(), (_key, value) =>
            typeof value === "string"
                ? (replacements.get(value) ?? value)
                : value,
        ),
    ) as OpportunityBundle;
    bundle.kind = "historical";
    bundle.securities[0].industry = [];
    return bundle;
}

test("classification snapshots survive validation but never supply historical map membership", () => {
    const bundle = classificationFixture();
    const snapshot = {
        label: "Shipping snapshot",
        observedAt: "2026-07-13T17:54:57+00:00",
        sourceId: "source",
    };
    bundle.securities[0].classificationSnapshot = snapshot;
    const validated = validateBundle(bundle);
    assert.deepEqual(validated.securities[0].classificationSnapshot, snapshot);
    const view = buildMarketView(validated, "2021-06-01");
    assert.equal(view.active[0].industry.basis, "unknown");
    assert.equal(view.industries[0].id, "unknown");
    assert.deepEqual(validated.securities[0].industry, []);
});

test("document periods group only inside their dates and yield to historical evidence", () => {
    const bundle = classificationFixture();
    const security = bundle.securities[0];
    security.industry = [
        {
            id: "shipping-2021",
            label: "Shipping business in 2021",
            from: "2021-01-01",
            untilExclusive: "2022-01-01",
            basis: "document-period",
            sourceId: "source",
        },
    ];
    validateBundle(bundle);
    for (const date of ["2020-12-31", "2022-01-03"])
        assert.equal(
            buildMarketView(bundle, date).rows[0].industry.basis,
            "unknown",
        );
    for (const date of ["2021-01-04", "2021-06-01", "2021-12-31"]) {
        const view = buildMarketView(bundle, date);
        assert.equal(view.active[0].industry.basis, "document-period");
        assert.equal(view.industries[0].id, "shipping-2021");
    }
    security.industry.push({
        id: "exchange-history",
        label: "Dated historical classification",
        from: "2021-06-01",
        untilExclusive: "2021-12-31",
        basis: "historical",
        sourceId: "source",
    });
    validateBundle(bundle);
    assert.equal(
        buildMarketView(bundle, "2021-06-01").active[0].industry.basis,
        "historical",
    );
    assert.equal(
        buildMarketView(bundle, "2021-12-31").active[0].industry.basis,
        "document-period",
    );
    security.industry.push({
        ...security.industry[1],
        id: "ambiguous-history",
    });
    assert.equal(
        buildMarketView(bundle, "2021-06-01").active[0].industry.basis,
        "unknown",
    );
    security.industry = [
        security.industry[0],
        { ...security.industry[0], id: "ambiguous-document" },
    ];
    assert.equal(
        buildMarketView(bundle, "2021-06-01").active[0].industry.basis,
        "unknown",
    );
});

test("classification validation binds snapshot and period sources and rejects same-basis overlap", () => {
    for (const observedAt of [null, "2026-07-13", "2026-07-13T17:54:57.123Z"]) {
        const bundle = fixture();
        bundle.securities[0].classificationSnapshot = {
            label: "Known snapshot",
            observedAt,
            sourceId: "source",
        };
        assert.doesNotThrow(() => validateBundle(bundle));
    }
    for (const changes of [
        { label: "" },
        { observedAt: undefined },
        { observedAt: 2026 },
        { observedAt: "2026-02-30" },
        { observedAt: "2026-07-13T17:54:57" },
        { sourceId: "missing" },
    ]) {
        const bundle = fixture();
        Object.assign(bundle.securities[0], {
            classificationSnapshot: {
                label: "Known snapshot",
                observedAt: null,
                sourceId: "source",
                ...changes,
            },
        });
        assert.throws(() => validateBundle(bundle), /classificationSnapshot/);
    }
    for (const basis of ["historical", "document-period"] as const) {
        const bundle = fixture();
        const membership = bundle.securities[0].industry[0];
        membership.basis = basis;
        membership.untilExclusive = DAYS[3];
        bundle.securities[0].industry.push({
            ...membership,
            from: DAYS[3],
            untilExclusive: UNTIL,
        });
        assert.doesNotThrow(() => validateBundle(bundle));
        bundle.securities[0].industry[1].from = DAYS[2];
        assert.throws(() => validateBundle(bundle), /overlapping intervals/);
        bundle.securities[0].industry.pop();
        membership.sourceId = "missing";
        assert.throws(() => validateBundle(bundle), /industry.sourceId/);
    }
});

test("classification references retain overlapping roles without selecting historical groups", () => {
    const bundle = classificationFixture();
    const security = bundle.securities[0];
    security.classificationReferences = [
        {
            id: "phone-role",
            label: "Phone products",
            layer: "business-role",
            temporalScope: "retrospective-event-context",
            from: "2021-01-01",
            untilExclusive: "2022-01-01",
            sourceIds: ["source"],
        },
        {
            id: "vr-role",
            label: "VR products",
            layer: "business-role",
            temporalScope: "retrospective-period-summary",
            from: "2021-01-01",
            untilExclusive: "2022-01-01",
            sourceIds: ["source"],
        },
        {
            id: "sector-reference",
            label: "Industry reference without dated coverage",
            layer: "business-sector",
            temporalScope: "undated-reference",
            from: null,
            untilExclusive: null,
            sourceIds: ["source"],
        },
    ];
    const before = structuredClone(security.classificationReferences);
    assert.deepEqual(
        validateBundle(bundle).securities[0].classificationReferences,
        before,
    );
    assert.equal(
        buildMarketView(bundle, "2021-06-01").active[0].industry.basis,
        "unknown",
    );
    security.industry = [
        {
            id: "document-business",
            label: "Recorded business grouping",
            from: "2021-01-01",
            untilExclusive: "2022-01-01",
            basis: "document-period",
            sourceId: "source",
        },
    ];
    validateBundle(bundle);
    assert.equal(
        buildMarketView(bundle, "2021-06-01").industries[0].id,
        "document-business",
    );
    security.classificationReferences = [];
    assert.equal(
        buildMarketView(validateBundle(bundle), "2021-06-01").industries[0].id,
        "document-business",
    );
});

test("classification reference validation rejects broken sources, half intervals and duplicate ids", () => {
    const reference = {
        id: "reference",
        label: "Known role",
        layer: "business-role",
        temporalScope: "retrospective-event-context",
        from: "2021-01-01",
        untilExclusive: "2022-01-01",
        sourceIds: ["source"],
    };
    for (const changes of [
        { sourceIds: [] },
        { sourceIds: ["missing"] },
        { sourceIds: "source" },
        { from: null },
        { untilExclusive: null },
        { from: "2021-02-30" },
        { untilExclusive: "2021-01-01" },
        { layer: "primary-business" },
        { temporalScope: "point-in-time" },
        { id: "" },
        { label: "" },
    ]) {
        const bundle = classificationFixture();
        Object.assign(bundle.securities[0], {
            classificationReferences: [{ ...reference, ...changes }],
        });
        assert.throws(() => validateBundle(bundle), /classificationReference/);
    }
    const bundle = classificationFixture();
    Object.assign(bundle.securities[0], {
        classificationReferences: [reference, { ...reference }],
    });
    assert.throws(() => validateBundle(bundle), /duplicate id/);
});

test("positive quantities after partial exits still count as held, then close-date overlap stops", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    portfolio.holdings = [
        {
            securityId: "A",
            from: DAYS[0],
            untilExclusive: DAYS[2],
            quantity: 10,
            sourceId: "source",
        },
        {
            securityId: "A",
            from: DAYS[2],
            untilExclusive: DAYS[4],
            quantity: 5,
            sourceId: "source",
        },
    ];
    assert.equal(getHoldingState(portfolio, "A", DAYS[2]), "held");
    assert.equal(getHoldingState(portfolio, "A", DAYS[4]), "not-held");
    const comparison = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    );
    near(comparison.stocks[0].positiveMoveShare, 0.5);
    near(comparison.stocks[0].heldDayShare, 0.8);
    assert.equal(comparison.stocks[0].knownDays, 5);
    assert.equal(comparison.stocks[0].totalDays, 5);
});

test("holdings evidence requires coverage, full absence differs from partial absence", () => {
    const portfolio = fixture().portfolios[0];
    assert.equal(getHoldingState(portfolio, "B", DAYS[2]), "not-held");
    portfolio.coverage[0].completeness = "partial";
    assert.equal(getHoldingState(portfolio, "B", DAYS[2]), "unknown");
    assert.equal(getHoldingState(portfolio, "A", DAYS[2]), "held");
    portfolio.coverage[0].untilExclusive = DAYS[2];
    assert.equal(getHoldingState(portfolio, "A", DAYS[2]), "unknown");
});

test("participation interval sweeps match single-date queries across overlaps, coverage gaps and quantity boundaries", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    const check = () => {
        for (const [lastIndex, day] of DAYS.entries()) {
            const row = buildMarketView(bundle, day).rows[0];
            const actual = calculateParticipation(bundle, row, portfolio, day);
            const dates = DAYS.slice(0, lastIndex + 1);
            const states = dates.map((date) =>
                getHoldingState(portfolio, "A", date),
            );
            const knownDays = states.filter(
                (state) => state !== "unknown",
            ).length;
            const heldDays = states.filter((state) => state === "held").length;
            let positiveTotal = 0,
                positiveHeld = 0;
            let unknownPositive = false;
            for (let i = 1; i < dates.length; i++) {
                const positive = Math.max(
                    0,
                    bundle.securities[0].prices[i].close! /
                        bundle.securities[0].prices[i - 1].close! -
                        1,
                );
                positiveTotal += positive;
                if (states[i] === "held") positiveHeld += positive;
                if (positive > 0 && states[i] === "unknown")
                    unknownPositive = true;
            }
            assert.equal(actual.held, states.at(-1));
            assert.equal(actual.knownDays, knownDays);
            assert.equal(actual.totalDays, dates.length);
            assert.equal(
                actual.heldDayShare,
                knownDays === dates.length ? heldDays / dates.length : null,
            );
            assert.equal(
                actual.positiveMoveShare,
                !unknownPositive && positiveTotal > 0
                    ? positiveHeld / positiveTotal
                    : null,
            );
            assert.equal(
                actual.reason,
                unknownPositive
                    ? "unknown-holding-on-positive-day"
                    : positiveTotal === 0
                      ? "no-positive-price-moves"
                      : knownDays < dates.length
                        ? "partial-holding-coverage"
                        : null,
            );
        }
    };
    const coverage = (
        from: string,
        untilExclusive: string,
        completeness: "full" | "partial",
    ) => ({
        from,
        untilExclusive,
        completeness,
        kind: "daily" as const,
        sourceId: "source",
    });
    const holding = (
        from: string,
        untilExclusive: string,
        quantity?: number,
        securityId = "A",
    ) => ({ from, untilExclusive, quantity, securityId, sourceId: "source" });

    portfolio.coverage = [
        coverage(DAYS[2], DAYS[4], "full"),
        coverage(DAYS[0], UNTIL, "partial"),
        coverage(DAYS[1], DAYS[3], "full"),
    ];
    portfolio.holdings = [
        holding(DAYS[2], DAYS[4], 5),
        holding(DAYS[0], DAYS[2], 10),
        holding(DAYS[1], DAYS[3], 2),
        holding(DAYS[0], UNTIL, 10, "B"),
    ];
    check();
    // Coverage wins over possession when evidence has a gap; adjacent starts/ends
    // and overlapping holdings must not manufacture an extra holding day.
    portfolio.coverage = [
        coverage(DAYS[4], UNTIL, "full"),
        coverage("2026-09-01", DAYS[2], "full"),
    ];
    portfolio.holdings = [
        holding("2026-09-01", UNTIL),
        holding(DAYS[1], DAYS[4], 1),
    ];
    check();
    portfolio.coverage = [];
    check();
    portfolio.coverage = [
        coverage(DAYS[0], UNTIL, "full"),
        coverage("2024-01-01", "2024-02-01", "partial"),
        coverage("2027-01-01", "2027-02-01", "full"),
    ];
    // Keep the single-date API's defensive quantity semantics for unvalidated
    // calls too; bundle validation separately rejects nonpositive/NaN quantity.
    portfolio.holdings = [
        holding(DAYS[0], UNTIL, 0),
        holding(DAYS[0], UNTIL, -1),
        holding(DAYS[0], UNTIL, NaN),
        holding(DAYS[3], DAYS[4]),
    ];
    check();
    portfolio.holdings[0].quantity = 4;
    check();
    portfolio.holdings[0].quantity = 0;
    check();
});

test("participation keeps the single-date holding query when the requested date is not a calendar observation", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    portfolio.holdings = [
        {
            securityId: "A",
            from: "2026-10-03",
            untilExclusive: "2026-10-04",
            quantity: 1,
            sourceId: "source",
        },
    ];
    const actual = calculateParticipation(
        bundle,
        buildMarketView(bundle, DAYS[4]).active[0],
        portfolio,
        "2026-10-03",
    );
    assert.equal(actual.held, getHoldingState(portfolio, "A", "2026-10-03"));
    assert.equal(actual.held, "held");
    assert.equal(actual.positiveMoveShare, null);
});

test("snapshot ownership never spreads to the next date, including an oversized holding interval", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    portfolio.coverage = [
        {
            from: DAYS[2],
            untilExclusive: DAYS[3],
            completeness: "full",
            kind: "snapshot",
            sourceId: "source",
        },
    ];
    validateBundle(bundle);
    assert.equal(getHoldingState(portfolio, "A", DAYS[2]), "held");
    assert.equal(getHoldingState(portfolio, "A", DAYS[3]), "unknown");
    portfolio.coverage[0].untilExclusive = "2026-10-30";
    assert.throws(() => validateBundle(bundle), /exactly one calendar day/);
});

test("unknown positive-day ownership nulls overlap; unrelated unknown days only null held-day share", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    portfolio.coverage[0].from = DAYS[1];
    let stock = comparePortfolio(
        bundle,
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).stocks[0];
    near(stock.positiveMoveShare, 1);
    assert.equal(stock.heldDayShare, null);
    assert.equal(stock.knownDays, 4);
    portfolio.coverage[0].from = DAYS[2];
    stock = comparePortfolio(
        bundle,
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).stocks[0];
    assert.equal(stock.positiveMoveShare, null);
    assert.equal(stock.knownDays, 3);
});

test("zero positive movement has no percentage and known-only aggregation excludes unknown stocks", () => {
    const bundle = fixture();
    const second = structuredClone(bundle.securities[0]);
    second.id = "B";
    bundle.securities.push(second);
    bundle.waves.push({
        ...structuredClone(bundle.waves[0]),
        id: "wave-B",
        securityId: "B",
    });
    bundle.representatives.push({
        securityId: "B",
        waveId: "wave-B",
        from: DAYS[0],
        untilExclusive: UNTIL,
    });
    bundle.portfolios[0].coverage[0].completeness = "partial";
    let result = comparePortfolio(
        bundle,
        buildMarketView(bundle, DAYS[4]),
        bundle.portfolios[0],
    );
    near(result.averagePositiveMoveShare, 1);
    assert.equal(result.knownCount, 1);
    assert.equal(result.unknownCount, 1);
    bundle.securities[0].prices.forEach((price) => {
        price.close = 100;
    });
    result = comparePortfolio(
        bundle,
        buildMarketView(bundle, DAYS[4]),
        bundle.portfolios[0],
    );
    assert.equal(
        result.stocks.find((stock) => stock.securityId === "A")!
            .positiveMoveShare,
        null,
    );
    assert.equal(
        result.stocks.find((stock) => stock.securityId === "A")!.reason,
        "no-positive-price-moves",
    );
    assert.equal(result.averagePositiveMoveShare, null);
});

test("same-date complete allocation provides capital, while missing days are never filled", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    let result = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    );
    assert.equal(result.capital.status, "known");
    near(result.capital.opportunityWeight, 0.6);
    near(result.capital.cashWeight, 0.4);
    near(result.capital.otherAssetsWeight, 0);
    assert.equal(result.capital.unknownWeight, 0);
    result = comparePortfolio(
        bundle,
        buildMarketView(bundle, DAYS[5]),
        portfolio,
    );
    assert.equal(result.capital.status, "unknown");
    assert.equal(result.capital.opportunityWeight, null);
    assert.equal(result.capital.cashWeight, null);
    assert.equal(result.capital.otherAssetsWeight, null);
    assert.equal(result.stocks[0].held, "held");
});

test("partial capital preserves observed buckets and unclassified residual", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    portfolio.allocations[0] = {
        date: DAYS[4],
        completeness: "partial",
        nav: null,
        cashWeight: 0.1,
        positions: [
            { securityId: "A", weight: 0.3 },
            { securityId: "not-in-catalog", weight: 0.2 },
        ],
        sourceId: "source",
    };
    let capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.status, "partial");
    near(capital.opportunityWeight, 0.3);
    near(capital.otherWeight, 0);
    near(capital.unknownWeight, 0.6);
    assert.equal(capital.otherAssetsWeight, null);
    portfolio.allocations[0].completeness = "full";
    portfolio.allocations[0].positions = [{ securityId: "A", weight: 0.85 }];
    capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.status, "partial");
    near(capital.unknownWeight, 0.05);
    assert.equal(capital.otherAssetsWeight, null);
});

test("full capital keeps receivables separate from stock, cash and unknown assets", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    portfolio.allocations[0].cashWeight = 0.25;
    portfolio.allocations[0].otherAssetsWeight = 0.15;
    const capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.status, "known");
    near(capital.opportunityWeight, 0.6);
    near(capital.otherWeight, 0);
    near(capital.cashWeight, 0.25);
    near(capital.otherAssetsWeight, 0.15);
    assert.equal(capital.unknownWeight, 0);
    near(
        capital.opportunityWeight! +
            capital.otherWeight! +
            capital.cashWeight! +
            capital.otherAssetsWeight! +
            capital.unknownWeight,
        1,
    );
    assert.equal(
        portfolio.holdings[0].quantity,
        10,
        "receivables never increase tradable shares",
    );
});

test("partial allocations preserve known other assets while omitted or null residuals remain unknown", () => {
    const bundle = fixture();
    const portfolio = bundle.portfolios[0];
    const allocation = portfolio.allocations[0];
    allocation.completeness = "partial";
    allocation.cashWeight = 0.1;
    let capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.otherAssetsWeight, null);
    near(capital.unknownWeight, 0.3);
    allocation.otherAssetsWeight = null;
    capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.otherAssetsWeight, null);
    near(capital.unknownWeight, 0.3);
    allocation.otherAssetsWeight = 0.2;
    capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.status, "partial");
    near(capital.otherAssetsWeight, 0.2);
    near(capital.unknownWeight, 0.1);
    allocation.positions = [];
    allocation.cashWeight = null;
    capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.status, "partial");
    assert.equal(capital.cashWeight, null);
    near(capital.otherAssetsWeight, 0.2);
    near(capital.unknownWeight, 0.8);
});

test("case slices keep positive unclassified stock separate from known receivables", () => {
    const bundle = fixture();
    bundle.waves[0].phases = bundle.waves[0].phases.slice(0, 3);
    bundle.catalogCoverage = "case-slice";
    bundle.waves[0].endConfirmedAt = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].observedThrough = DAYS[4];
    const portfolio = bundle.portfolios[0];
    portfolio.allocations[0].cashWeight = 0.25;
    portfolio.allocations[0].otherAssetsWeight = 0.15;
    const capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    ).capital;
    assert.equal(capital.status, "partial");
    near(capital.opportunityWeight, 0);
    near(capital.otherWeight, 0);
    near(capital.otherAssetsWeight, 0.15);
    near(capital.cashWeight, 0.25);
    near(capital.unknownWeight, 0.6);
});

test("explicit full asset buckets must reconcile and reject malformed or excessive other assets", () => {
    for (const value of [-0.1, NaN, Infinity, 0.1]) {
        const bundle = fixture();
        bundle.portfolios[0].allocations[0].otherAssetsWeight = value;
        assert.throws(
            () => validateBundle(bundle),
            /Invalid opportunity bundle/,
        );
    }
    const bundle = fixture();
    const allocation = bundle.portfolios[0].allocations[0];
    allocation.cashWeight = 0.2;
    allocation.otherAssetsWeight = 0.1;
    assert.throws(
        () => validateBundle(bundle),
        /full allocation weights must reconcile/,
    );
    allocation.otherAssetsWeight = 0.1999995;
    const capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        bundle.portfolios[0],
    ).capital;
    assert.equal(capital.status, "known");
    near(capital.otherAssetsWeight, 0.1999995);
    assert.equal(capital.unknownWeight, 0);
});

test("case slices cannot label non-opportunity assets as other stock", () => {
    const bundle = fixture();
    bundle.waves[0].phases = bundle.waves[0].phases.slice(0, 3);
    bundle.waves[0].endConfirmedAt = DAYS[4];
    bundle.waves[0].peakDate = DAYS[4];
    bundle.waves[0].observedThrough = DAYS[4];
    const portfolio = bundle.portfolios[0];
    let result = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    );
    near(result.capital.otherWeight, 0.6);
    assert.equal(result.capital.status, "known");
    bundle.catalogCoverage = "case-slice";
    result = comparePortfolio(
        bundle,
        buildMarketView(bundle, DAYS[4]),
        portfolio,
    );
    assert.equal(result.capital.status, "partial");
    near(result.capital.otherWeight, 0);
    near(result.capital.unknownWeight, 0.6);
});

test("full capital accepts rounding only within tolerance and never infers cash", () => {
    const bundle = fixture();
    bundle.portfolios[0].allocations[0].cashWeight = 0.3999995;
    let capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        bundle.portfolios[0],
    ).capital;
    assert.equal(capital.status, "known");
    bundle.portfolios[0].allocations[0].cashWeight = null;
    capital = comparePortfolio(
        validateBundle(bundle),
        buildMarketView(bundle, DAYS[4]),
        bundle.portfolios[0],
    ).capital;
    assert.equal(capital.status, "partial");
    assert.equal(capital.cashWeight, null);
    near(capital.unknownWeight, 0.4);
});

test("validation rejects malformed numerics, dates, duplicates and broken references", () => {
    const invalid: ((bundle: OpportunityBundle) => void)[] = [
        (bundle) => {
            bundle.securities[0].prices[0].close = NaN;
        },
        (bundle) => {
            bundle.securities[0].prices[0].close = 0;
        },
        (bundle) => {
            bundle.dates[0] = "2026-02-30";
        },
        (bundle) => {
            bundle.dates.reverse();
        },
        (bundle) => {
            bundle.securities.push(structuredClone(bundle.securities[0]));
        },
        (bundle) => {
            bundle.securities[0].prices.push(
                structuredClone(bundle.securities[0].prices[0]),
            );
        },
        (bundle) => {
            bundle.waves[0].securityId = "missing";
        },
        (bundle) => {
            bundle.waves[0].sourceId = "missing";
        },
        (bundle) => {
            bundle.waves[0].peakDate = "2026-10-20";
        },
        (bundle) => {
            bundle.waves[0].endConfirmedAt = DAYS[0];
        },
        (bundle) => {
            bundle.waves[0].parentId = bundle.waves[0].id;
        },
        (bundle) => {
            bundle.waves[0].phases.push(
                structuredClone(bundle.waves[0].phases[0]),
            );
        },
        (bundle) => {
            bundle.representatives.push(
                structuredClone(bundle.representatives[0]),
            );
        },
        (bundle) => {
            bundle.portfolios[0].allocations[0].positions.push({
                securityId: "A",
                weight: 0.1,
            });
        },
        (bundle) => {
            bundle.portfolios[0].allocations[0].positions[0].weight = -0.1;
        },
        (bundle) => {
            bundle.portfolios[0].allocations[0].cashWeight = 0.5;
        },
        (bundle) => {
            bundle.portfolios[0].holdings[0].quantity = 0;
        },
    ];
    for (const change of invalid) {
        const bundle = fixture();
        change(bundle);
        assert.throws(
            () => validateBundle(bundle),
            /Invalid opportunity bundle/,
        );
    }
});

test("CLI shares core values and identities, supports path spaces and portfolio filters, refuses overwrite", async () => {
    const root = resolve(
        dirname(fileURLToPath(import.meta.url)),
        "../../../..",
    );
    const scratch = join(root, ".tmp");
    await mkdir(scratch, { recursive: true });
    const directory = await mkdtemp(join(scratch, "opportunity cli "));
    const input = join(directory, "input bundle.json");
    const output = join(directory, "result comparison.json");
    const script = join(
        root,
        "research_web",
        "scripts",
        "compare-opportunities.mts",
    );
    const bundle = fixture();
    bundle.portfolios.push({
        ...structuredClone(bundle.portfolios[0]),
        id: "second",
    } satisfies OpportunityPortfolio);
    const run = (args: string[]) =>
        spawnSync(
            process.execPath,
            [
                "--experimental-strip-types",
                script,
                "--input",
                input,
                "--date",
                DAYS[4],
                ...args,
            ],
            { encoding: "utf8" },
        );
    try {
        // Also accept the UTF-8 BOM produced by common Windows JSON writers.
        await writeFile(input, `\uFEFF${JSON.stringify(bundle)}`);
        const first = run([
            "--portfolio",
            "strategy,second",
            "--portfolio",
            "strategy",
            "--output",
            output,
        ]);
        assert.equal(first.status, 0, first.stderr);
        const result = JSON.parse(await readFile(output, "utf8"));
        assert.equal(result.bundle.id, bundle.id);
        assert.equal(result.bundle.ruleVersion, bundle.ruleVersion);
        assert.deepEqual(result.bundle.sources, bundle.sources);
        assert.equal(
            result.positiveMoveShareVersion,
            POSITIVE_MOVE_SHARE_VERSION,
        );
        assert.equal(result.comparisons.length, 2);
        assert.deepEqual(
            result.comparisons[0],
            comparePortfolio(
                bundle,
                buildMarketView(bundle, DAYS[4]),
                bundle.portfolios[0],
            ),
        );
        const original = await readFile(output, "utf8");
        const overwrite = run(["--output", output]);
        assert.notEqual(overwrite.status, 0);
        assert.match(overwrite.stderr, /EEXIST|already exists/);
        assert.equal(await readFile(output, "utf8"), original);
        const stdout = run(["--portfolio", "second"]);
        assert.equal(stdout.status, 0, stdout.stderr);
        assert.equal(
            JSON.parse(stdout.stdout).comparisons[0].portfolio.id,
            "second",
        );
        assert.notEqual(run(["--portfolio", "missing"]).status, 0);
        assert.notEqual(run(["--portfolio", ","]).status, 0);
        assert.notEqual(run(["--date", "2026-10-03"]).status, 0);
    } finally {
        // Only remove the unique directory created by this test under repository scratch.
        await rm(directory, { recursive: true, force: true });
    }
});
