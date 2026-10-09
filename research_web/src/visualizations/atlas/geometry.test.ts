import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";
import test from "node:test";
import { layoutCells } from "./geometry.ts";
import type { CellInput, CellLayout, Point } from "./geometry.ts";

function polygonArea(points: Point[]): number {
    let signed = 0;
    points.forEach((a, index) => {
        const b = points[(index + 1) % points.length];
        signed += a[0] * b[1] - a[1] * b[0];
    });
    return Math.abs(signed) / 2;
}

/** Parse the actual rendered path independently of the reported numeric area. */
function sampledPath(path: string): Point[] {
    const tokens = path.match(/[MLCZ]|[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi)!;
    const points: Point[] = [];
    let position = 0;
    while (position < tokens.length) {
        const command = tokens[position++];
        if (command === "Z") break;
        if (command === "M" || command === "L") {
            points.push([
                Number(tokens[position++]),
                Number(tokens[position++]),
            ]);
        } else {
            assert.equal(command, "C");
            const a = points[points.length - 1];
            const b: Point = [
                Number(tokens[position++]),
                Number(tokens[position++]),
            ];
            const c: Point = [
                Number(tokens[position++]),
                Number(tokens[position++]),
            ];
            const d: Point = [
                Number(tokens[position++]),
                Number(tokens[position++]),
            ];
            for (let sample = 1; sample <= 40; sample++) {
                const t = sample / 40;
                const s = 1 - t;
                points.push([
                    s ** 3 * a[0] +
                        3 * s ** 2 * t * b[0] +
                        3 * s * t ** 2 * c[0] +
                        t ** 3 * d[0],
                    s ** 3 * a[1] +
                        3 * s ** 2 * t * b[1] +
                        3 * s * t ** 2 * c[1] +
                        t ** 3 * d[1],
                ]);
            }
        }
    }
    return points;
}

function verify(
    cells: CellLayout[],
    items: CellInput[],
    width: number,
    height: number,
): void {
    assert.equal(cells.length, items.length);
    const total = cells.reduce((sum, cell) => sum + cell.area, 0);
    const totalWeight = items.reduce((sum, item) => sum + item.weight, 0);
    for (const cell of cells) {
        assert.ok(Number.isFinite(cell.area) && cell.area > 0);
        assert.ok(Number.isFinite(cell.x) && Number.isFinite(cell.y));
        const expected =
            (total * items.find((item) => item.id === cell.id)!.weight) /
            totalWeight;
        assert.ok(
            Math.abs(cell.area / expected - 1) < 0.02,
            `${cell.id}: area ${cell.area}, expected ${expected}`,
        );
        assert.ok(Math.abs(cell.area / cell.targetArea - 1) < 0.02);
        assert.ok(
            Math.abs(polygonArea(cell.points) / cell.area - 1) < 1e-7,
            "reported area measures the final warped polygon",
        );
        assert.ok(
            Math.abs(polygonArea(sampledPath(cell.path)) / cell.area - 1) <
                1e-7,
            "rendered path preserves measured area",
        );
        for (const [x, y] of sampledPath(cell.path)) {
            assert.ok(Number.isFinite(x) && Number.isFinite(y));
            assert.ok(
                x >= 0 && x <= width && y >= 0 && y <= height,
                "path stays inside canvas",
            );
        }
    }
    const whole = layoutCells(
        [{ id: "whole", group: "whole", weight: 1 }],
        width,
        height,
    )[0];
    assert.ok(
        total / whole.area > 0.99 && total / whole.area < 1.0004,
        "inward foam corners leave bounded white junctions; no hidden area inflation",
    );
}

const input = Array.from({ length: 12 }, (_, index) => ({
    id: `stock-${index}`,
    group: `group-${index % 3}`,
    weight: index + 1,
}));

test("empty, missing and zero values are omitted without invented minimum weights", () => {
    assert.deepEqual(layoutCells([], 800, 600), []);
    assert.deepEqual(
        layoutCells(
            [
                { id: "zero", weight: 0, group: "g" },
                { id: "missing", weight: NaN, group: "g" },
            ],
            800,
            600,
        ),
        [],
    );
    assert.deepEqual(layoutCells(input, 0, 600), []);
    assert.deepEqual(layoutCells(input, 800, Infinity), []);
    assert.throws(() => layoutCells([input[0], input[0]], 800, 600), /unique/);
});

test("one cell is a finite organic outline with its complete assigned area", () => {
    const items = [{ id: "only", weight: 1, group: "single" }];
    const cells = layoutCells(items, 900, 530);
    verify(cells, items, 900, 530);
    assert.ok(cells[0].points.length > 30);
    assert.ok(Math.abs(cells[0].area / cells[0].targetArea - 1) < 0.0002);
});

test("one-cell outer frame remains a near-symmetric irregular oval", () => {
    const [cell] = layoutCells(
        [{ id: "only", weight: 1, group: "single" }],
        900,
        530,
    );
    assert.equal(cell.points.length % 2, 0);
    const half = cell.points.length / 2;
    cell.points.forEach((point, index) => {
        const opposite = cell.points[(index + half) % cell.points.length];
        assert.ok(
            Math.abs(point[0] + opposite[0] - 900) < 1e-7 &&
                Math.abs(point[1] + opposite[1] - 530) < 1e-7,
            "opposite outline points remain mirrored around the canvas centre",
        );
    });
});

test("layout is deterministic and identity positions do not depend on input order", () => {
    const first = layoutCells(input, 1000, 700);
    assert.deepEqual(layoutCells(input, 1000, 700), first);
    assert.deepEqual(
        layoutCells([...input].reverse(), 1000, 700).reverse(),
        first,
    );
    verify(first, input, 1000, 700);
    assert.ok(
        first.every((cell) => cell.points.length > 30),
        "curved walls are densely sampled before rendering",
    );
});

test("low-amplitude global warp rounds a shared wall for both cells", () => {
    const cells = layoutCells(
        [
            { id: "left", group: "g", weight: 1 },
            { id: "right", group: "g", weight: 1 },
        ],
        1000,
        700,
    );
    const key = ([x, y]: Point) => `${x.toFixed(7)},${y.toFixed(7)}`;
    const rightPoints = new Set(cells[1].points.map(key));
    const shared = cells[0].points.filter((point) =>
        rightPoints.has(key(point)),
    );
    assert.ok(
        shared.length > 30,
        "both cells share the dense transformed boundary",
    );
    const start = shared[0];
    const end = shared[shared.length - 1];
    const length = Math.hypot(end[0] - start[0], end[1] - start[1]);
    const deviation = Math.max(
        ...shared.map(
            (point) =>
                Math.abs(
                    (point[0] - start[0]) * (end[1] - start[1]) -
                        (point[1] - start[1]) * (end[0] - start[0]),
                ) / length,
        ),
    );
    assert.ok(
        deviation > 4,
        `shared wall visibly curves: maximum chord distance ${deviation.toFixed(2)}px`,
    );
    verify(
        cells,
        [
            { id: "left", group: "g", weight: 1 },
            { id: "right", group: "g", weight: 1 },
        ],
        1000,
        700,
    );
});

test("inward rounded foam junctions are smooth, leave gaps and do not overlap", () => {
    const items = Array.from({ length: 4 }, (_, index) => ({
        id: `round-${index}`,
        group: "g",
        weight: 1,
    }));
    const cells = layoutCells(items, 800, 600);
    verify(cells, items, 800, 600);
    const whole = layoutCells(
        [{ id: "whole", group: "g", weight: 1 }],
        800,
        600,
    )[0];
    assert.ok(
        cells.reduce((total, cell) => total + cell.area, 0) <
            whole.area * 0.9999,
        "rounded junctions visibly remove a small measured amount of area",
    );
    for (const cell of cells) {
        let largestTurn = 0;
        cell.points.forEach((point, index) => {
            const previous =
                cell.points[
                    (index + cell.points.length - 1) % cell.points.length
                ];
            const next = cell.points[(index + 1) % cell.points.length];
            const incoming = [point[0] - previous[0], point[1] - previous[1]];
            const outgoing = [next[0] - point[0], next[1] - point[1]];
            const lengths = Math.hypot(...incoming) * Math.hypot(...outgoing);
            if (lengths <= 1e-12) return;
            const cosine =
                (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) /
                lengths;
            largestTurn = Math.max(
                largestTurn,
                Math.acos(Math.max(-1, Math.min(1, cosine))),
            );
        });
        assert.ok(
            largestTurn < 0.9,
            `rounded boundary has no sharp vertex: ${largestTurn.toFixed(3)}rad`,
        );
    }
    const contains = (point: Point, polygon: Point[]): boolean => {
        let inside = false;
        polygon.forEach((a, index) => {
            const b = polygon[(index + 1) % polygon.length];
            if (
                a[1] > point[1] !== b[1] > point[1] &&
                point[0] <
                    ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0]
            )
                inside = !inside;
        });
        return inside;
    };
    for (let y = 17; y < 600; y += 17) {
        for (let x = 13; x < 800; x += 19) {
            assert.ok(
                cells.filter((cell) => contains([x, y], cell.points)).length <=
                    1,
                `cells overlap at ${x},${y}`,
            );
        }
    }
});

test("19:1 and severe skew retain area ratios without enlarging tiny cells", () => {
    for (const weights of [
        [19, 1],
        [10000, 1, 2, 3],
        [1, 1, 100, 1, 0.01, 1],
    ]) {
        const items = weights.map((weight, index) => ({
            id: String(index),
            weight,
            group: String(index % 2),
        }));
        verify(layoutCells(items, 960, 600), items, 960, 600);
    }
});

test("responsive dimensions preserve proportions and remain bounded", () => {
    for (const [width, height] of [
        [320, 640],
        [1400, 420],
        [64, 64],
    ]) {
        verify(layoutCells(input, width, height), input, width, height);
    }
});

test("36 cells meet area constraints within an interactive calculation budget", () => {
    const items = Array.from({ length: 36 }, (_, index) => ({
        id: `id-${index}`,
        group: `g-${Math.floor(index / 6)}`,
        weight: 1 + ((index * 19) % 43),
    }));
    const started = performance.now();
    const cells = layoutCells(items, 1280, 800);
    const elapsed = performance.now() - started;
    verify(cells, items, 1280, 800);
    assert.ok(elapsed < 2000, `36 cells took ${elapsed.toFixed(1)}ms`);
    console.info(
        `36-cell geometry: ${elapsed.toFixed(1)}ms; maximum area error ${(Math.max(...cells.map((cell) => Math.abs(cell.area / cell.targetArea - 1))) * 100).toFixed(4)}%`,
    );
    assert.throws(
        () =>
            layoutCells(
                [...items, { id: "37", group: "g", weight: 1 }],
                1280,
                800,
            ),
        /36/,
    );
});
