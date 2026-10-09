import assert from "node:assert/strict";
import test from "node:test";
import { syntheticCases } from "./synthetic.ts";

test("synthetic cases are deterministic and include the slow tenfold counterexample", () => {
    const secondImport = structuredClone(syntheticCases);
    assert.deepEqual(syntheticCases, secondImport);
    const slow = syntheticCases.find((item) => item.id === "smooth-slow-10x")!;
    assert.ok(slow.points.length >= 750);
    assert.ok(slow.points.at(-1)!.adjusted! / slow.points[0].adjusted! > 9.8);
});

test("synthetic null gaps and isolated jumps are not smoothed", () => {
    const gap = syntheticCases.find(
        (item) => item.id === "missing-quotes-null-gap",
    )!;
    assert.ok(
        gap.points.some(
            (point) => point.adjusted === null && point.raw === null,
        ),
    );
    const jump = syntheticCases.find(
        (item) => item.id === "legitimate-isolated-jump",
    )!;
    assert.deepEqual(
        jump.points.slice(0, 100).map((point) => point.adjusted),
        Array(100).fill(100),
    );
    assert.equal(jump.points[100].adjusted, 170);
});

test("synthetic labels do not become quality flags", () => {
    for (const item of syntheticCases)
        assert.ok(item.points.every((point) => point.flags.length === 0));
});
