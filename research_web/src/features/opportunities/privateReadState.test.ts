import assert from "node:assert/strict";
import test from "node:test";
import {
    privateReadTransition,
    type PrivateReadState,
} from "./privateReadState.ts";

test("private read failure stays an error, retry clears old data, and success resolves", () => {
    let state: PrivateReadState<string> = {
        status: "loading",
        historical: null,
    };
    state = privateReadTransition(state, {
        type: "failed",
        message: "HTTP 503",
    });
    assert.deepEqual(state, {
        status: "failure",
        message: "HTTP 503",
        historical: null,
    });
    state = privateReadTransition(state, { type: "retry" });
    assert.deepEqual(state, { status: "loading", historical: null });
    state = privateReadTransition(state, {
        type: "loaded",
        historical: "new snapshot",
    });
    assert.deepEqual(state, { status: "success", historical: "new snapshot" });
});

test("success to demo to failed local retry cannot display the old private snapshot", () => {
    let state: PrivateReadState<string> = {
        status: "success",
        historical: "old private snapshot",
    };
    state = privateReadTransition(state, { type: "explicit-demo" });
    assert.equal(state.status, "demo");
    state = privateReadTransition(state, { type: "retry" });
    assert.deepEqual(state, { status: "loading", historical: null });
    state = privateReadTransition(state, {
        type: "failed",
        message: "HTTP 503",
    });
    assert.deepEqual(state, {
        status: "failure",
        message: "HTTP 503",
        historical: null,
    });
    state = privateReadTransition(state, { type: "explicit-demo" });
    assert.deepEqual(state, { status: "demo", historical: null });
});
