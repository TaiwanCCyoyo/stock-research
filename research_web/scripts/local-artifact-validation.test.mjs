import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { isAtlasData } from "../src/features/market/model.ts";
import { validateLabBundle } from "../src/features/wave-lab/bundle.ts";

// Opt-in checks require the actual local artifacts. Missing files fail with their paths.
test("the retained local market atlas passes validation without rewriting prices", async () => {
    const atlas = JSON.parse(
        await readFile(
            new URL("../public/data/market-atlas.json", import.meta.url),
            "utf8",
        ),
    );
    const original = structuredClone(atlas);
    assert.equal(isAtlasData(atlas), true);
    assert.deepEqual(atlas, original);
});

test("the retained local wave bundle remains readable without filling or rewriting prices", async () => {
    const bundle = JSON.parse(
        await readFile(
            new URL("../public/data/wave-lab-cases.json", import.meta.url),
            "utf8",
        ),
    );
    const original = structuredClone(bundle);
    assert.ok(validateLabBundle(bundle).cases.length);
    assert.deepEqual(bundle, original);
});
