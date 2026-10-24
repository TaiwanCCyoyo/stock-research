import assert from "node:assert/strict";
import test from "node:test";
import { CLOSED, TIP_NAVIGATION_EVENTS, tipReducer } from "./tipState.ts";

const run = (...events: Parameters<typeof tipReducer>[1][]) =>
    events.reduce(tipReducer, CLOSED);

test("a keyboard-pinned tip closes on hash, back and forward navigation", () => {
    // Focus, then Enter (a click on the button) pins it.
    const pinned = run("focus", "toggle");
    assert.deepEqual(pinned, { open: true, pinned: true });
    assert.deepEqual(tipReducer(pinned, "blur"), pinned);
    assert.deepEqual(tipReducer(pinned, "navigate"), CLOSED);
    assert.deepEqual([...TIP_NAVIGATION_EVENTS], ["hashchange", "popstate"]);
});

test("hover and focus preview without pinning; Escape and outside close", () => {
    assert.deepEqual(run("enter", "leave"), CLOSED);
    assert.deepEqual(run("focus", "blur"), CLOSED);
    assert.deepEqual(run("enter", "toggle", "leave"), {
        open: true,
        pinned: true,
    });
    assert.deepEqual(run("enter", "toggle", "toggle"), CLOSED);
    assert.deepEqual(run("focus", "toggle", "escape"), CLOSED);
    assert.deepEqual(run("focus", "toggle", "outside"), CLOSED);
});
