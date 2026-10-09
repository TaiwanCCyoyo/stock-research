import assert from "node:assert/strict";
import test from "node:test";
import {
    artifactMode,
    assertArtifactResponseMode,
    readArtifactInMode,
} from "./artifactMode.ts";
import { validateBundle } from "../domain/opportunities/model.ts";
import { validateResearchBundle } from "../domain/opportunities/research.ts";

test("public default is deterministic fictional data with no requests", async () => {
    const signal = new AbortController().signal;
    const noFetch: typeof fetch = async () => {
        throw new Error("must not fetch");
    };
    const bundle = validateBundle(
        await readArtifactInMode(
            "opportunity-explorer",
            signal,
            undefined,
            noFetch,
        ),
    );
    assert.equal(bundle.kind, "synthetic");
    assert.equal(bundle.securities.length, 36);
    assert.deepEqual(
        bundle,
        await readArtifactInMode(
            "opportunity-explorer",
            signal,
            "public-synthetic",
            noFetch,
        ),
    );
    const research = validateResearchBundle(
        await readArtifactInMode(
            "saved-research-runs",
            signal,
            undefined,
            noFetch,
        ),
    );
    assert.equal(research.runs[0].method.parameters.synthetic, true);
    assert.match(research.runs[0].id, /synthetic/);
});

test("local private reads explicit API and never substitutes demo for missing data", async () => {
    const signal = new AbortController().signal;
    const fetcher: typeof fetch = async (url) => {
        assert.equal(url, "/api/private-artifacts/v1/opportunity-explorer");
        return Response.json({
            kind: "private-test",
            dataMode: "local-private",
        });
    };
    assert.deepEqual(
        await readArtifactInMode(
            "opportunity-explorer",
            signal,
            "local-private",
            fetcher,
        ),
        { kind: "private-test", dataMode: "local-private" },
    );
    for (const response of [
        new Response("missing", { status: 503 }),
        new Response("<html>", { headers: { "content-type": "text/html" } }),
    ])
        await assert.rejects(
            readArtifactInMode(
                "opportunity-explorer",
                signal,
                "local-private",
                async () => response,
            ),
            /unavailable/,
        );
    assert.throws(() => artifactMode("typo"), /Unknown/);
    await assert.rejects(
        readArtifactInMode("../secret", signal),
        /Unsupported/,
    );
});

test("mode mismatch never exposes private evidence as a public demonstration", () => {
    assert.throws(
        () => assertArtifactResponseMode({ dataMode: "local-private" }),
        /unavailable/,
    );
    assert.throws(
        () =>
            assertArtifactResponseMode(
                { dataMode: "public-synthetic" },
                "local-private",
            ),
        /unavailable/,
    );
    assert.throws(() => assertArtifactResponseMode({}), /unavailable/);
    assert.doesNotThrow(() =>
        assertArtifactResponseMode({ dataMode: "public-synthetic" }),
    );
    assert.doesNotThrow(() =>
        assertArtifactResponseMode(
            { dataMode: "local-private" },
            "local-private",
        ),
    );
});

test("aborted reads do not return synthetic or private data", async () => {
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
        readArtifactInMode("opportunity-explorer", controller.signal),
        { name: "AbortError" },
    );
});
