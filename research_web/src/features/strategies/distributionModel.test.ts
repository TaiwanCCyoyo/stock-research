import assert from "node:assert/strict";
import { test } from "node:test";
import { savedReturnDistribution } from "./distributionModel.ts";

const closed = (value: number | null | undefined) => ({
    closeDate: "2026-01-01",
    return: value,
});

test("saved returns enter exactly one interval at every boundary and tail", () => {
    const cases = [
        [-2, 0],
        [-0.500001, 0],
        [-0.5, 1],
        [-0.200001, 1],
        [-0.2, 2],
        [-0.100001, 2],
        [-0.1, 3],
        [-0.050001, 3],
        [-0.05, 4],
        [-Number.EPSILON, 4],
        [0, 5],
        [-0, 5],
        [Number.EPSILON, 6],
        [0.049999, 6],
        [0.05, 7],
        [0.099999, 7],
        [0.1, 8],
        [0.199999, 8],
        [0.2, 9],
        [0.499999, 9],
        [0.5, 10],
        [0.999999, 10],
        [1, 11],
        [5, 11],
    ];
    for (const [value, expectedIndex] of cases) {
        const result = savedReturnDistribution([closed(value)]);
        assert.equal(
            result.buckets[expectedIndex].count,
            1,
            `boundary ${value}`,
        );
        assert.equal(
            result.buckets.reduce((sum, bucket) => sum + bucket.count, 0),
            1,
        );
        assert.equal(result.excluded, 0);
    }
});

test("true zero has a neutral bin separate from nearby wins and losses", () => {
    const result = savedReturnDistribution([
        closed(-0.001),
        closed(0),
        closed(0.001),
    ]);
    assert.equal(result.buckets[4].tone, "loss");
    assert.equal(result.buckets[5].tone, "neutral");
    assert.equal(result.buckets[6].tone, "gain");
    assert.deepEqual(
        result.buckets.slice(4, 7).map((bucket) => bucket.count),
        [1, 1, 1],
    );
});

test("all closed rows are accounted for while open trades and invalid returns are excluded", () => {
    const rows = [
        closed(-0.2),
        closed(0),
        closed(0.05),
        closed(1),
        ...[null, undefined, NaN, Infinity, -Infinity].map(closed),
        { closeDate: null, return: 10 },
        { closeDate: null, return: null },
    ];
    const before = rows.map((row) => ({ ...row }));
    const result = savedReturnDistribution(rows);
    assert.equal(result.total, 9);
    assert.equal(result.included, 4);
    assert.equal(result.excluded, 5);
    assert.equal(
        result.buckets.reduce((sum, bucket) => sum + bucket.count, 0) +
            result.excluded,
        result.total,
    );
    assert.deepEqual(rows, before);
});

test("empty runs and runs without valid closed returns have empty bins", () => {
    for (const rows of [
        [],
        [closed(null)],
        [{ closeDate: null, return: 0.1 }],
    ]) {
        const result = savedReturnDistribution(rows);
        assert.equal(result.included, 0);
        assert.ok(result.buckets.every((bucket) => bucket.count === 0));
    }
});
