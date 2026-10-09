import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";
import test from "node:test";
import { computePacking } from "./packing.ts";
import type { PackingLayout, PackingNode, PackingPoint } from "./packing.ts";
import { createOpportunityFixture } from "../../domain/opportunities/fixture.ts";
import { buildMarketView } from "../../domain/opportunities/model.ts";

function polygonArea(points: PackingPoint[]): number {
    // Translate first to retain precision for small shapes far from the origin.
    const origin = points[0];
    return (
        Math.abs(
            points.reduce((sum, p, index) => {
                const next = points[(index + 1) % points.length];
                return (
                    sum +
                    (p.x - origin.x) * (next.y - origin.y) -
                    (next.x - origin.x) * (p.y - origin.y)
                );
            }, 0),
        ) / 2
    );
}

/** Independently sample the rendered SVG, not the layout's reported area or points. */
function pathPoints(path: string): PackingPoint[] {
    const tokens = path.match(/[MCZ]|[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi)!;
    const points: PackingPoint[] = [];
    let index = 0;
    while (index < tokens.length) {
        const command = tokens[index++];
        if (command === "Z") break;
        if (command === "M")
            points.push({
                x: Number(tokens[index++]),
                y: Number(tokens[index++]),
            });
        else {
            assert.equal(command, "C");
            const a = points[points.length - 1];
            const b = {
                x: Number(tokens[index++]),
                y: Number(tokens[index++]),
            };
            const c = {
                x: Number(tokens[index++]),
                y: Number(tokens[index++]),
            };
            const d = {
                x: Number(tokens[index++]),
                y: Number(tokens[index++]),
            };
            for (let sample = 1; sample <= 20; sample++) {
                const t = sample / 20;
                const s = 1 - t;
                points.push({
                    x:
                        s ** 3 * a.x +
                        3 * s ** 2 * t * b.x +
                        3 * s * t ** 2 * c.x +
                        t ** 3 * d.x,
                    y:
                        s ** 3 * a.y +
                        3 * s ** 2 * t * b.y +
                        3 * s * t ** 2 * c.y +
                        t ** 3 * d.y,
                });
            }
        }
    }
    return points;
}

function verify(layout: PackingLayout, scale: number, gap: number): void {
    assert.ok(Object.values(layout.bounds).every(Number.isFinite));
    assert.ok(
        Math.abs(layout.bounds.minX + layout.bounds.maxX) < 1e-7,
        "actual stock bounds are horizontally centered",
    );
    assert.ok(
        Math.abs(layout.bounds.minY + layout.bounds.maxY) < 1e-7,
        "actual stock bounds are vertically centered",
    );
    assert.ok(
        Number.isFinite(layout.fillRatio) &&
            layout.fillRatio >= 0 &&
            layout.fillRatio < 1,
    );
    let measuredTotal = 0;
    const measuredAreas = layout.nodes.map((node) => {
        assert.ok(
            [node.x, node.y, node.r, node.outerRadius, node.area].every(
                Number.isFinite,
            ),
        );
        assert.equal(node.r, Math.sqrt(node.weight) * scale);
        assert.ok(node.path.endsWith("Z"));
        assert.ok(
            node.points.every(
                (p) => Number.isFinite(p.x) && Number.isFinite(p.y),
            ),
        );
        const area = polygonArea(pathPoints(node.path));
        measuredTotal += area;
        if (node.weight === 0 || scale === 0) {
            assert.equal(node.r, 0);
            assert.equal(node.outerRadius, 0);
            assert.equal(node.area, 0);
            assert.equal(area, 0);
        } else {
            const target = Math.PI * scale ** 2 * node.weight;
            assert.ok(
                Math.abs(area / target - 1) < 0.02,
                `${node.id}: SVG area must match its fixed-scale target`,
            );
            assert.ok(
                Math.abs(polygonArea(node.points) / target - 1) < 0.02,
                `${node.id}: points match SVG boundary`,
            );
            for (const p of pathPoints(node.path)) {
                assert.ok(
                    Math.hypot(p.x - node.x, p.y - node.y) <=
                        node.outerRadius * (1 + 1e-10),
                );
                assert.ok(
                    p.x >= layout.bounds.minX - 1e-7 &&
                        p.x <= layout.bounds.maxX + 1e-7,
                );
                assert.ok(
                    p.y >= layout.bounds.minY - 1e-7 &&
                        p.y <= layout.bounds.maxY + 1e-7,
                );
            }
        }
        return area;
    });
    const totalWeight = layout.nodes.reduce(
        (sum, node) => sum + node.weight,
        0,
    );
    for (let i = 0; i < layout.nodes.length; i++) {
        const a = layout.nodes[i];
        if (a.weight > 0 && scale > 0)
            assert.ok(
                Math.abs(
                    measuredAreas[i] /
                        measuredTotal /
                        (a.weight / totalWeight) -
                        1,
                ) < 0.02,
            );
        for (let j = i + 1; j < layout.nodes.length; j++) {
            const b = layout.nodes[j];
            if (a.r === 0 || b.r === 0) continue;
            const separation = Math.hypot(a.x - b.x, a.y - b.y);
            assert.ok(
                separation + 1e-8 >= a.outerRadius + b.outerRadius + gap,
                `${a.id}/${b.id} overlap`,
            );
        }
    }
    for (const group of layout.groups) {
        assert.ok(group.path.endsWith("Z"));
        assert.equal(
            (group.path.match(/M/g) ?? []).length,
            1,
            "one connected industry outline",
        );
        assert.ok(
            group.points.every(
                (p) => Number.isFinite(p.x) && Number.isFinite(p.y),
            ),
        );
        assert.ok(
            [group.x, group.y, group.r, group.area, group.weight].every(
                Number.isFinite,
            ),
        );
        if (group.area > 0) {
            assert.ok(
                group.path.includes("C"),
                "industry envelope has curved walls",
            );
            assert.ok(
                Math.abs(polygonArea(pathPoints(group.path)) / group.area - 1) <
                    0.02,
            );
        }
    }
}

const synthetic = (count: number, groups: number): PackingNode[] =>
    Array.from({ length: count }, (_, i) => ({
        id: `stock-${String(i).padStart(3, "0")}`,
        groupId: `industry-${String(i % groups).padStart(2, "0")}`,
        weight: 10 ** (-3 + ((i * 37) % 91) / 15),
    }));

test("closed organic boundaries preserve fixed target and relative areas without overlaps", () => {
    const nodes = synthetic(60, 9);
    const layout = computePacking({ nodes, globalRadiusScale: 4, gap: 2 });
    verify(layout, 4, 2);
    assert.ok(
        layout.groups.reduce((sum, group) => sum + group.area, 0) >
            layout.nodes.reduce((sum, node) => sum + node.area, 0),
    );
});

test("one to three stocks remain compact rounded shapes", () => {
    for (const count of [1, 2, 3]) {
        const nodes = Array.from({ length: count }, (_, i) => ({
            id: `${i}`,
            groupId: "one",
            weight: 1 + i,
        }));
        const layout = computePacking({ nodes, globalRadiusScale: 10 });
        verify(layout, 10, 1.5);
        for (const node of layout.nodes) {
            const width =
                Math.max(...node.points.map((p) => p.x)) -
                Math.min(...node.points.map((p) => p.x));
            const height =
                Math.max(...node.points.map((p) => p.y)) -
                Math.min(...node.points.map((p) => p.y));
            assert.ok(width / height > 0.8 && width / height < 1.25);
        }
        const group = layout.groups[0];
        const width =
            Math.max(...group.points.map((p) => p.x)) -
            Math.min(...group.points.map((p) => p.x));
        const height =
            Math.max(...group.points.map((p) => p.y)) -
            Math.min(...group.points.map((p) => p.y));
        assert.ok(
            width / height > 0.35 && width / height < 2.85,
            "small group is not a narrow strip",
        );
    }
});

test("another stock growing, entering or leaving never rescales an unchanged stock", () => {
    const fixed = { id: "fixed", groupId: "a", weight: 5 };
    const first = computePacking({
        nodes: [fixed, { id: "other", groupId: "b", weight: 1 }],
        globalRadiusScale: 10,
    });
    const next = computePacking({
        nodes: [fixed, { id: "new", groupId: "c", weight: 10000 }],
        globalRadiusScale: 10,
        previous: first.nodes,
    });
    const a = first.nodes.find((node) => node.id === "fixed")!;
    const b = next.nodes.find((node) => node.id === "fixed")!;
    assert.equal(a.r, b.r);
    assert.equal(a.area, b.area);
    assert.ok(
        next.bounds.width > first.bounds.width * 10,
        "the world grows instead of clamping radii",
    );
    verify(next, 10, 1.5);
});

test("layout is deterministic, order independent and does not mutate inputs", () => {
    const nodes = synthetic(40, 6);
    const before = structuredClone(nodes);
    const first = computePacking({ nodes, globalRadiusScale: 3 });
    assert.deepEqual(
        computePacking({ nodes: [...nodes].reverse(), globalRadiusScale: 3 }),
        first,
    );
    assert.deepEqual(nodes, before);
    const previous = first.nodes.map(({ id, x, y }) => ({ id, x, y }));
    const saved = structuredClone(previous);
    const next = computePacking({ nodes, globalRadiusScale: 3, previous });
    for (const node of next.nodes) {
        const old = first.nodes.find((p) => p.id === node.id)!;
        assert.ok(
            Math.hypot(node.x - old.x, node.y - old.y) < 1e-7,
            `${node.id} moved with unchanged inputs`,
        );
    }
    assert.deepEqual(previous, saved);
});

test("strong initial group is central and newly arriving groups begin on the periphery", () => {
    const nodes = [
        { id: "strong", groupId: "strong", weight: 100 },
        { id: "weak", groupId: "weak", weight: 1 },
    ];
    const first = computePacking({ nodes, globalRadiusScale: 3 });
    const strong = first.groups.find((g) => g.id === "strong")!;
    const weak = first.groups.find((g) => g.id === "weak")!;
    assert.ok(
        Math.hypot(strong.x, strong.y) < Math.hypot(weak.x, weak.y),
        "the stronger group is closer to the composition center",
    );
    const next = computePacking({
        nodes: [...nodes, { id: "new", groupId: "new", weight: 500 }],
        previous: first.nodes,
        globalRadiusScale: 3,
    });
    const newcomer = next.groups.find((g) => g.id === "new")!;
    const keptStrong = next.groups.find((group) => group.id === "strong")!;
    assert.ok(
        Math.hypot(newcomer.x - keptStrong.x, newcomer.y - keptStrong.y) >=
            newcomer.r + keptStrong.r,
        "new groups enter outside the surviving territory",
    );
    for (const node of first.nodes) {
        const kept = next.nodes.find((p) => p.id === node.id)!;
        assert.ok(
            Math.hypot(
                kept.x - keptStrong.x - (node.x - strong.x),
                kept.y - keptStrong.y - (node.y - strong.y),
            ) < newcomer.r,
            "relative surviving positions move gently while making room",
        );
    }
});

test("long playback and reversal keep live strength near a bounded origin without changing the area scale", (t) => {
    const dayNodes = (day: number): PackingNode[] =>
        Array.from({ length: 32 }, (_, group) => {
            const age = day - group * 12;
            if (age < 0 || age >= 36) return [];
            return Array.from({ length: 3 }, (_, stock) => ({
                id: `season-${group}-stock-${stock}`,
                groupId: `season-${group}`,
                weight:
                    ((1 + Math.min(age, 36 - age) / 8) * (1 + stock / 4)) ** 2,
            }));
        }).flat();
    const calendar = [
        ...Array.from({ length: 361 }, (_, i) => i),
        ...Array.from({ length: 281 }, (_, i) => 360 - i),
        ...Array.from({ length: 181 }, (_, i) => 80 + i),
    ];
    let previous: PackingLayout["nodes"] = [];
    let maxCenter = 0;
    let maxReach = 0;
    for (const [index, day] of calendar.entries()) {
        const layout = computePacking({
            nodes: dayNodes(day),
            globalRadiusScale: 30,
            previous,
            gap: 2,
            groupGap: 12,
            outlinePadding: 8,
        });
        const strongest = [...layout.groups].sort(
            (a, b) => b.weight - a.weight || a.id.localeCompare(b.id),
        )[0];
        const others = layout.groups.filter(
            (group) => group.id !== strongest.id,
        );
        if (
            others.length &&
            strongest.weight >=
                others.reduce((sum, group) => sum + group.weight, 0) * 4
        ) {
            assert.ok(
                Math.hypot(strongest.x, strongest.y) <=
                    Math.min(
                        ...others.map((group) => Math.hypot(group.x, group.y)),
                    ),
                "a dominant group stays closer to the composition center",
            );
        }
        assert.ok(Math.abs(layout.bounds.minX + layout.bounds.maxX) < 1e-7);
        assert.ok(Math.abs(layout.bounds.minY + layout.bounds.maxY) < 1e-7);
        const sizeBudget =
            layout.groups.reduce((sum, group) => sum + group.r, 0) * 4 +
            layout.groups.length * 12;
        const reach = Math.max(
            Math.abs(layout.bounds.minX),
            Math.abs(layout.bounds.minY),
            Math.abs(layout.bounds.maxX),
            Math.abs(layout.bounds.maxY),
        );
        assert.ok(
            reach <= sizeBudget,
            `day ${day}: positions must be bounded by current content, not elapsed playback`,
        );
        maxReach = Math.max(maxReach, reach);
        maxCenter = Math.max(
            maxCenter,
            Math.hypot(
                (layout.bounds.minX + layout.bounds.maxX) / 2,
                (layout.bounds.minY + layout.bounds.maxY) / 2,
            ),
        );
        for (const node of layout.nodes) {
            assert.equal(node.r, Math.sqrt(node.weight) * 30);
            assert.ok(
                Math.abs(node.area / (Math.PI * 900 * node.weight) - 1) < 1e-10,
            );
        }
        if (index % 36 === 0 || index === calendar.length - 1)
            verify(layout, 30, 2);
        previous = layout.nodes;
    }
    t.diagnostic(
        `${calendar.length} forward/reverse layouts: maximum world reach ${maxReach.toFixed(1)}, bounding-center distance ${maxCenter.toFixed(1)}; stock bounds stay centered without scaling.`,
    );
});

test("the nine-stock April fixture stays inside the fixed viewport after continuous playback and reversal", () => {
    const bundle = createOpportunityFixture();
    const target = bundle.dates.indexOf("2021-04-30");
    assert.ok(target >= 60);
    const indices = [
        ...Array.from({ length: target + 1 }, (_, i) => i),
        ...Array.from({ length: 60 }, (_, i) => target - 1 - i),
        ...Array.from({ length: 60 }, (_, i) => target - 59 + i),
    ];
    let previous: PackingLayout["nodes"] = [];
    let arrivals = 0;
    for (const index of indices) {
        const view = buildMarketView(bundle, bundle.dates[index]);
        const layout = computePacking({
            nodes: view.active.map((row) => ({
                id: row.security.id,
                groupId: row.industry.id,
                weight: row.weight,
            })),
            globalRadiusScale: 30,
            previous,
            gap: 2,
            groupGap: 12,
            outlinePadding: 8,
        });
        previous = layout.nodes;
        if (index !== target) continue;
        arrivals++;
        assert.equal(layout.nodes.length, 9);
        assert.ok(layout.bounds.minX >= -500 && layout.bounds.maxX <= 500);
        assert.ok(layout.bounds.minY >= -310 && layout.bounds.maxY <= 310);
        verify(layout, 30, 2);
    }
    assert.equal(
        arrivals,
        2,
        "validate both the original arrival and the return after reversal",
    );
});

test("zero weights stay zero without an artificial area floor; empty input is finite", () => {
    const nodes = [
        { id: "zero", groupId: "a", weight: 0 },
        { id: "positive", groupId: "a", weight: 1 },
    ];
    verify(computePacking({ nodes, globalRadiusScale: 10 }), 10, 1.5);
    verify(computePacking({ nodes, globalRadiusScale: 0 }), 0, 1.5);
    assert.deepEqual(computePacking({ nodes: [], globalRadiusScale: 10 }), {
        nodes: [],
        groups: [],
        bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0 },
        fillRatio: 0,
    });
});

test("stock clearance is respected across groups even with no decorative padding", () => {
    const layout = computePacking({
        nodes: synthetic(25, 25),
        globalRadiusScale: 1,
        gap: 30,
        groupGap: 0,
        outlinePadding: 0,
    });
    verify(layout, 1, 30);
});

test("malformed numeric inputs and duplicate identities are rejected explicitly", () => {
    for (const weight of [-1, NaN, Infinity])
        assert.throws(() =>
            computePacking({
                nodes: [{ id: "bad", groupId: "a", weight }],
                globalRadiusScale: 10,
            }),
        );
    assert.throws(() =>
        computePacking({ nodes: [], globalRadiusScale: Infinity }),
    );
    assert.throws(() =>
        computePacking({ nodes: [], globalRadiusScale: 1, gap: -1 }),
    );
    assert.throws(() =>
        computePacking({
            nodes: synthetic(2, 1).map((node) => ({ ...node, id: "same" })),
            globalRadiusScale: 1,
        }),
    );
    assert.throws(() =>
        computePacking({
            nodes: [],
            globalRadiusScale: 1,
            previous: [{ id: "bad", x: NaN, y: 0 }],
        }),
    );
    assert.throws(() =>
        computePacking({
            nodes: [{ id: "huge", groupId: "a", weight: 1e308 }],
            globalRadiusScale: 1e100,
        }),
    );
});

test("250-node synthetic layouts cover wide weights, arrivals, departures and one crowded group", (t) => {
    const nodes = synthetic(250, 20);
    const start = performance.now();
    const first = computePacking({ nodes, globalRadiusScale: 2 });
    const firstMs = performance.now() - start;
    const changed = nodes
        .slice(20)
        .map((node, i) => ({
            ...node,
            weight: node.weight * (i % 5 === 0 ? 3 : 0.8),
        }))
        .concat(
            Array.from({ length: 20 }, (_, i) => ({
                id: `new-${i}`,
                groupId: `new-industry-${i % 3}`,
                weight: 0.01 * 2 ** (i % 18),
            })),
        );
    const changeStart = performance.now();
    const next = computePacking({
        nodes: changed,
        previous: first.nodes,
        globalRadiusScale: 2,
    });
    const changedMs = performance.now() - changeStart;
    const crowdedStart = performance.now();
    const crowded = computePacking({
        nodes: synthetic(250, 1),
        globalRadiusScale: 2,
    });
    const crowdedMs = performance.now() - crowdedStart;
    assert.equal(first.nodes.length, 250);
    assert.equal(next.nodes.length, 250);
    verify(first, 2, 1.5);
    verify(next, 2, 1.5);
    verify(crowded, 2, 1.5);
    t.diagnostic(
        `Synthetic geometry only, 250 nodes: initial ${firstMs.toFixed(2)} ms; arrivals/departures/changed weights ${changedMs.toFixed(2)} ms; one group ${crowdedMs.toFixed(2)} ms. Excludes worker transport, rendering and browser FPS.`,
    );
});

test("long playback with departures stays as tight as a fresh layout and spreads to the frame shape", () => {
    // Rolling membership: each stock lives 60 days, so holes open every day.
    const dayNodes = (day: number): PackingNode[] =>
        Array.from({ length: 80 }, (_, k) => day + k)
            .filter((i) => i % 3 !== 0)
            .map((i) => ({
                id: `roll-${String(i).padStart(4, "0")}`,
                groupId: `industry-${i % 7}`,
                weight: (1 + ((i * 13) % 9) / 3) ** 2,
            }));
    const options = {
        globalRadiusScale: 30,
        gap: 2,
        groupGap: 12,
        outlinePadding: 8,
        aspect: 1.7,
    };
    let previous: PackingLayout["nodes"] = [];
    let worst = 0;
    for (let day = 0; day < 240; day++) {
        const nodes = dayNodes(day);
        const warm = computePacking({
            ...options,
            nodes,
            previous: previous.map(({ id, x, y, r }) => ({ id, x, y, r })),
        });
        previous = warm.nodes;
        if (day % 40 !== 39) continue;
        const cold = computePacking({ ...options, nodes });
        // The zoom a 1.7-wide frame needs to show everything.
        const span = (layout: PackingLayout) =>
            Math.max(layout.bounds.width / 1.7, layout.bounds.height);
        worst = Math.max(worst, span(warm) / span(cold));
        verify(warm, 30, 2);
        assert.ok(
            cold.bounds.width > cold.bounds.height,
            "a wide frame produces a wide composition",
        );
    }
    assert.ok(
        worst <= 1.15,
        `playback spread to ${worst.toFixed(2)}× a fresh layout`,
    );
});

test("extreme frame shapes stay finite and compact instead of diverging", () => {
    const nodes = synthetic(60, 12);
    const cold = computePacking({
        nodes,
        globalRadiusScale: 30,
        gap: 2,
        groupGap: 12,
        outlinePadding: 8,
    });
    for (const aspect of [8, 1 / 8, 3]) {
        const layout = computePacking({
            nodes,
            globalRadiusScale: 30,
            gap: 2,
            groupGap: 12,
            outlinePadding: 8,
            aspect,
        });
        verify(layout, 30, 2);
        const area = layout.bounds.width * layout.bounds.height;
        assert.ok(
            area <= cold.bounds.width * cold.bounds.height * 4,
            `aspect ${aspect} spread to ${area.toExponential(2)}`,
        );
    }
});

test("a zero-area stock does not make an unchanged day re-compact", () => {
    const nodes = [
        ...synthetic(30, 5),
        { id: "flat", groupId: "industry-00", weight: 0 },
    ];
    const options = {
        globalRadiusScale: 30,
        gap: 2,
        groupGap: 12,
        outlinePadding: 8,
    };
    const first = computePacking({ ...options, nodes });
    const visible = first.nodes
        .filter((node) => node.r > 0)
        .map(({ id, x, y, r }) => ({ id, x, y, r }));
    const again = computePacking({ ...options, nodes, previous: visible });
    for (const node of again.nodes.filter((item) => item.r > 0)) {
        const old = first.nodes.find((item) => item.id === node.id)!;
        assert.ok(
            Math.hypot(node.x - old.x, node.y - old.y) < 1e-7,
            `${node.id} moved although nothing visible changed`,
        );
    }
    const grown = computePacking({
        ...options,
        nodes: nodes.map((node) =>
            node.id === "flat" ? { ...node, weight: 1 } : node,
        ),
        previous: visible,
    });
    verify(grown, 30, 2);
});
