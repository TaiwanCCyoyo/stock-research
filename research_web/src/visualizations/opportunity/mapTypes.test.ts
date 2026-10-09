import assert from "node:assert/strict";
import test from "node:test";
import { buildMarketView } from "../../domain/opportunities/model.ts";
import { createOpportunityFixture } from "../../domain/opportunities/fixture.ts";
import { computePacking } from "./packing.ts";
import {
    classificationContext,
    classificationLabel,
} from "../../features/opportunities/classificationDisplay.ts";
import {
    endedBurst,
    gainColorBand,
    territoryLabelText,
    planTerritoryLabels,
    labelWidth,
    comparisonShareLine,
    hasMapIndustry,
    mapGroupId,
    mapIndustries,
    sameSource,
    showPeakAreaReference,
    visiblePackingPositions,
} from "./mapTypes.ts";
import type { MapRow, MapView } from "./mapTypes.ts";

test("zero-area previous nodes do not disperse a jump from 14 stocks to 722 stocks in 40 groups", () => {
    const options = {
        globalRadiusScale: 30,
        gap: 2,
        groupGap: 12,
        outlinePadding: 8,
    };
    const nodes = Array.from({ length: 722 }, (_, i) => ({
        id: `stock-${i}`,
        groupId: `group-${i % 40}`,
        weight: (0.6 + (i % 9) / 10) ** 2,
    }));
    const original = structuredClone(nodes);
    const zero = computePacking({
        ...options,
        nodes: nodes.slice(0, 14).map((node) => ({ ...node, weight: 0 })),
    });
    const zeroBefore = structuredClone(zero);
    const cold = computePacking({ ...options, nodes });
    const jumped = computePacking({
        ...options,
        nodes,
        previous: visiblePackingPositions(zero.nodes),
    });
    assert.equal(jumped.nodes.length, 722);
    assert.equal(jumped.groups.length, 40);
    assert.deepEqual(jumped, cold);
    const weights = new Map(nodes.map((node) => [node.id, node.weight]));
    for (const node of jumped.nodes) {
        assert.equal(node.weight, weights.get(node.id));
        assert.equal(node.r, Math.sqrt(node.weight) * 30);
        const targetArea = Math.PI * node.weight * 30 ** 2;
        assert.ok(Math.abs(node.area - targetArea) <= targetArea * 1e-12);
    }
    assert.deepEqual(nodes, original);
    assert.deepEqual(zero, zeroBefore);
    const positive = jumped.nodes.slice(0, 2);
    assert.deepEqual(
        visiblePackingPositions([...zero.nodes, ...positive]),
        positive.map(({ id, x, y, r }) => ({ id, x, y, r })),
    );
});

function row(id = "one"): MapRow {
    return {
        security: { id, code: id, name: id, industry: [] },
        wave: {
            id: `wave-${id}`,
            start: "2020-01-01",
            launch: null,
            endConfirmedAt: "2020-02-01",
            observedThrough: "2020-03-01",
            rightCensored: false,
        },
        industry: {
            id: "chips",
            label: "半導體",
            basis: "current-snapshot",
            from: "2026-01-01",
            untilExclusive: null,
            sourceId: "snapshot",
        },
        gain: 30,
        peakGain: 40,
        phase: "rising",
        weight: 0.09,
    };
}
function view(
    rows = [row()],
    catalogId: string | undefined = "catalog-one",
    date = "2020-01-31",
): MapView {
    return { catalogId, date, rows, active: rows, ended: [], industries: [] };
}

test("fresh API objects from one catalog retain animation source identity, including empty frames", () => {
    const previous = view();
    const next = structuredClone(previous);
    next.date = "2020-02-01";
    assert.notEqual(previous.rows[0].security, next.rows[0].security);
    assert.equal(sameSource(previous, next), true);
    assert.equal(sameSource(previous, view([], previous.catalogId)), true);
    assert.equal("prices" in next.rows[0].security, false);
});

test("catalog changes invalidate animation even if security objects are reused", () => {
    const previous = view();
    assert.equal(
        sameSource(previous, view(previous.rows, "catalog-two")),
        false,
    );
    const preview = view(previous.rows);
    delete preview.catalogId;
    assert.equal(sameSource(previous, preview), false);
    assert.equal(sameSource(view([], ""), view([], "")), false);
});

test("snapshot mode groups only recorded snapshot industries and labels their time basis", () => {
    const first = row();
    first.security.classificationSnapshot = {
        label: "半導體",
        observedAt: "2026-01-01",
        sourceId: "snapshot",
    };
    const second = row("two");
    second.gain = 50;
    const unknown = row("unknown");
    unknown.industry.basis = "unknown";
    const historical = row("historical");
    historical.industry.basis = "historical";
    const snapshot = view([first, second, unknown, historical]);
    assert.equal(hasMapIndustry(first, "historical"), false);
    assert.equal(hasMapIndustry(historical, "historical"), true);
    assert.equal(hasMapIndustry(historical, "snapshot"), false);
    const groups = mapIndustries(snapshot, "snapshot");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].label, "半導體");
    assert.equal(groups[0].maxGain, 50);
    assert.deepEqual(groups[0].rows, [first, second]);
    const known = new Set(groups.map((group) => group.id));
    assert.equal(mapGroupId(first, "snapshot", known), "chips");
    assert.notEqual(
        mapGroupId(unknown, "snapshot", known),
        mapGroupId(historical, "snapshot", known),
    );
    assert.equal(classificationLabel(first), "半導體");
    assert.equal(classificationContext(first), "參照現有分類，當年歸屬待確認");
    assert.equal(mapIndustries(snapshot, "historical"), snapshot.industries);
});

test("full-history industry leader uses the highest selected metric across bases, while unknown never falls back to raw gain", () => {
    const actual = row("short");
    actual.gain = 900;
    actual.displayMetric = { gain: 100, basis: "actual" };
    const annualized = row("long");
    annualized.gain = 1200;
    annualized.security.name = "長波段領先者";
    annualized.displayMetric = { gain: 145, basis: "annualized" };
    const groups = mapIndustries(view([actual, annualized]), "snapshot");
    assert.equal(groups[0].maxGain, 1200);
    assert.deepEqual(groups[0].displayMetric, {
        gain: 145,
        basis: "annualized",
        leaderName: "長波段領先者",
        leaderCode: "long",
    });
    assert.equal(
        territoryLabelText(groups[0], 2),
        "半導體 2 檔 · 最高 年化 +145%",
    );

    const unknown = row("unknown");
    unknown.gain = 9999;
    unknown.displayMetric = { gain: null, basis: "unknown" };
    const unknownGroup = mapIndustries(view([unknown]), "snapshot")[0];
    assert.equal(unknownGroup.displayMetric?.gain, null);
    assert.match(territoryLabelText(unknownGroup, 1), /最高 尺度未知/);
    assert.doesNotMatch(territoryLabelText(unknownGroup, 1), /9999/);

    const legacy = row("legacy");
    assert.equal(legacy.displayMetric, undefined);
    assert.match(
        territoryLabelText(mapIndustries(view([legacy]), "snapshot")[0], 1),
        /最高 \+30%/,
    );
});

test("raw peak-area reference is limited to legacy preview rows", () => {
    assert.equal(showPeakAreaReference(row("legacy")), true);
    for (const displayMetric of [
        { gain: 115, basis: "actual" as const },
        { gain: 72.5, basis: "annualized" as const },
        { gain: null, basis: "unknown" as const },
    ])
        assert.equal(showPeakAreaReference({ ...row(), displayMetric }), false);
});

for (const { label, gains, expected } of [
    { label: "all unknown", gains: [null, null], expected: null },
    {
        label: "unknown before negative gains",
        gains: [null, -15, -3],
        expected: -3,
    },
    { label: "mixed gains", gains: [null, 20, -10, 60, null], expected: 60 },
]) {
    test(`snapshot maximum preserves known values for ${label} in any input order`, () => {
        for (const ordered of [
            gains,
            [...gains].reverse(),
            [...gains.slice(1), gains[0]],
        ]) {
            const rows = ordered.map((gain, index) => ({
                ...row(`stock-${index}`),
                gain,
            }));
            const input = view(rows);
            const before = structuredClone(input);
            const groups = mapIndustries(input, "snapshot");
            assert.equal(groups.length, 1);
            assert.equal(groups[0].maxGain, expected);
            assert.deepEqual(groups[0].rows, rows);
            assert.deepEqual(input, before);
            if (expected === null)
                assert.equal(gainColorBand(groups[0].maxGain), "unknown");
        }
    });
}

test("empty API ended lists burst only when the previous wave ends during forward travel", () => {
    const previous = view();
    const next = view([], previous.catalogId, "2020-02-01");
    assert.equal(endedBurst(previous, next, previous.rows[0]), true);
    previous.rows[0].wave.endConfirmedAt = "2020-02-02";
    assert.equal(endedBurst(previous, next, previous.rows[0]), false);
    previous.rows[0].wave.endConfirmedAt = null;
    assert.equal(endedBurst(previous, next, previous.rows[0]), false);
    previous.rows[0].wave.endConfirmedAt = previous.date;
    assert.equal(endedBurst(previous, next, previous.rows[0]), false);
    assert.equal(
        endedBurst(previous, view([], "other", next.date), previous.rows[0]),
        false,
    );
    assert.equal(
        endedBurst(
            previous,
            view([], previous.catalogId, "2020-01-01"),
            previous.rows[0],
        ),
        false,
    );
});

test("old preview accepts MarketView and preserves security and wave object identity semantics", () => {
    const fixture = createOpportunityFixture();
    const full = buildMarketView(fixture, fixture.dates[0]);
    const compatible: MapView = full;
    assert.equal(sameSource(compatible, compatible), true);
    assert.equal(sameSource(compatible, { ...compatible }), true);
    assert.equal(sameSource(compatible, structuredClone(compatible)), false);
    const oldRow = row();
    const previous = view([oldRow]);
    delete previous.catalogId;
    const next = {
        ...previous,
        date: "2020-02-01",
        active: [],
        ended: [oldRow],
    };
    assert.equal(endedBurst(previous, next, oldRow), true);
    assert.equal(
        endedBurst(
            previous,
            { ...next, ended: [structuredClone(oldRow)] },
            oldRow,
        ),
        false,
    );
    assert.equal(endedBurst(previous, { ...next, ended: [] }, oldRow), false);
});

test("gain color thresholds distinguish observed gains without inferring phases or changing area", () => {
    for (const [gain, band] of [
        [0, "light"],
        [59.999, "light"],
        [60, "medium"],
        [99.999, "medium"],
        [100, "strong"],
        [9000, "strong"],
        [null, "unknown"],
        [-1, "unknown"],
        [NaN, "unknown"],
    ] as const)
        assert.equal(gainColorBand(gain), band);
    const input = row();
    input.phase = null;
    const before = structuredClone(input);
    assert.equal(gainColorBand(input.gain), "light");
    assert.deepEqual(input, before);
});

test("territory labels keep every drawn line inside a 320px map with 2-4 long comparison names", () => {
    // A 320px-wide map at zoom 1: 1000 world units across, 12px text.
    const view = { x0: -500, x1: 500, y0: -400, y1: 400 };
    const fontSize = (12 * 1000) / 320;
    const longName = "台灣高股息低波動動能精選加碼重試策略第二版";
    const groups = Array.from({ length: 8 }, (_, i) => ({
        id: `industry-${i}`,
        x: -450 + i * 130,
        top: -300 + (i % 3) * 200,
        weight: 10 - i,
        text: territoryLabelText(
            {
                label: "電腦及週邊設備業",
                maxGain: null,
                displayMetric: { gain: 588, basis: "annualized" },
            },
            32,
        ),
    }));
    for (const count of [2, 3, 4]) {
        const names = Array.from(
            { length: count },
            (_, i) => `${longName}${i}`,
        );
        const plan = planTerritoryLabels({
            groups,
            comparisonNames: names,
            view,
            fontSize,
            limit: 5,
        });
        assert.ok(plan.size > 0, `${count} comparisons: some label is placed`);
        // The texts the map really draws, including the longest unknown share.
        const shares = [
            comparisonShareLine(1, false),
            comparisonShareLine(1, true),
            comparisonShareLine(null, false),
            comparisonShareLine(null, true),
        ];
        assert.ok(shares.some((text) => text.includes("100%")));
        assert.ok(
            shares.some((text) => text.includes("無法計算（部分無法計算）")),
        );
        for (const [id, spot] of plan) {
            const group = groups.find((item) => item.id === id)!;
            const rows = [
                group.text,
                ...spot.prefixes.flatMap((prefix) =>
                    shares.map((share) => `${prefix}${share}`),
                ),
            ];
            rows.forEach((row, index) => {
                const line =
                    index === 0
                        ? 0
                        : 1 + Math.floor((index - 1) / shares.length);
                const half = labelWidth(row, fontSize) / 2;
                assert.ok(
                    spot.x - half >= view.x0 - 1e-9 &&
                        spot.x + half <= view.x1 + 1e-9,
                    `${count} comparisons: "${row}" leaves the map horizontally`,
                );
                const baseline = spot.y + fontSize * 1.3 * line;
                assert.ok(
                    baseline - fontSize >= view.y0 - 1e-9 &&
                        baseline + fontSize * 0.3 <= view.y1 + 1e-9,
                    `${count} comparisons: line ${line} leaves the map vertically`,
                );
            });
            for (const prefix of spot.prefixes)
                assert.ok(prefix === "" || prefix.endsWith("… "));
        }
    }
    const roomy = planTerritoryLabels({
        groups,
        comparisonNames: ["0050", "動能策略"],
        view: { x0: -2000, x1: 2000, y0: -1500, y1: 1500 },
        fontSize: 12,
        limit: 10,
    });
    assert.deepEqual(
        [...roomy.values()][0].prefixes,
        ["0050 ", "動能策略 "],
        "names that fit are shown in full",
    );
});
