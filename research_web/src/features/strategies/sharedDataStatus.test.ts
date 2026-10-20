import assert from "node:assert/strict";
import test from "node:test";
import {
    initialSharedDataStatus,
    parseSharedGenerationMetadata,
} from "./sharedGenerationState.ts";

test("public mode explicitly avoids reading the private shared source", () => {
    assert.deepEqual(initialSharedDataStatus("public-synthetic"), {
        status: "synthetic",
    });
    assert.deepEqual(initialSharedDataStatus(undefined), {
        status: "synthetic",
    });
    assert.deepEqual(initialSharedDataStatus("local-private"), {
        status: "loading",
    });
});

test("accepts the safe generation metadata shape and rejects incomplete metadata", () => {
    const metadata = {
        family: "adjusted-daily-v1",
        generation: "g-20261020",
        asof: "2026-10-19",
        built_at_utc: "2026-10-20T01:02:03+00:00",
        status_sha256: "a".repeat(64),
    };
    assert.deepEqual(parseSharedGenerationMetadata(metadata), metadata);
    assert.throws(
        () => parseSharedGenerationMetadata({ generation: "g1" }),
        /family/,
    );
});
