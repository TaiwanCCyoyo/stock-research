import assert from "node:assert/strict";
import test from "node:test";
import {
    privateReadTransition,
    type PrivateReadState,
} from "./privateReadState.ts";

test("private read failure stays an error, retry returns to loading, and success resolves", () => {
    let state: PrivateReadState = { status: "loading" };
    assert.deepEqual(state, { status: "loading" });
    state = privateReadTransition(state, {
        type: "failed",
        message: "HTTP 503",
    });
    assert.deepEqual(state, { status: "failure", message: "HTTP 503" });
    state = privateReadTransition(state, { type: "retry" });
    assert.deepEqual(state, { status: "loading" });
    state = privateReadTransition(state, { type: "loaded" });
    assert.deepEqual(state, { status: "success" });
});

test("demo state requires the explicit demo selection event", () => {
    const state = privateReadTransition(
        { status: "failure", message: "HTTP 503" },
        { type: "explicit-demo" },
    );
    assert.deepEqual(state, { status: "demo" });
});
