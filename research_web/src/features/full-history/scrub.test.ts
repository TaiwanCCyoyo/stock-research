import assert from "node:assert/strict";
import test from "node:test";
import { SCRUB_JUMP, isFastSeek, scrubStillActive } from "./scrub.ts";

test("a drag (targets arriving in quick succession) is a fast scrub", () => {
    assert.equal(isFastSeek({ elapsed: 16, from: 100, to: 101 }), true);
    assert.equal(isFastSeek({ elapsed: 120, from: 100, to: 102 }), true);
});

test("a single slow small step is not", () => {
    assert.equal(isFastSeek({ elapsed: 800, from: 100, to: 101 }), false);
    assert.equal(isFastSeek({ elapsed: Infinity, from: 0, to: 5 }), false);
});

test("a long jump is fast even after a pause", () => {
    assert.equal(
        isFastSeek({ elapsed: 5000, from: 100, to: 100 + SCRUB_JUMP + 1 }),
        true,
    );
    assert.equal(
        isFastSeek({ elapsed: 5000, from: 100, to: 100 + SCRUB_JUMP }),
        false,
    );
});

test("the fastest playback speed (40 trading days a step) is not a long jump", () => {
    assert.ok(40 <= SCRUB_JUMP);
});

test("the pop lasts until the date is quiet and its own frame is shown", () => {
    const base = {
        flagged: true,
        quiet: true,
        frameDate: "2020-01-02",
        desiredDate: "2020-01-02",
        loading: false,
        failed: false,
    };
    assert.equal(scrubStillActive(base), false);
    assert.equal(scrubStillActive({ ...base, quiet: false }), true);
    assert.equal(scrubStillActive({ ...base, loading: true }), true);
    assert.equal(scrubStillActive({ ...base, frameDate: "2020-01-01" }), true);
    assert.equal(scrubStillActive({ ...base, flagged: false }), false);
    assert.equal(
        scrubStillActive({ ...base, quiet: false, failed: true }),
        false,
    );
});
