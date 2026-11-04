import assert from "node:assert/strict";
import { test } from "node:test";
import { HISTORY_SCHEMA } from "./types.ts";
import {
    HistoryLoadingError,
    readHistory,
    readHistoryWhenReady,
} from "./api.ts";

const pending = () =>
    new Response(JSON.stringify({ detail: { state: "loading" } }), {
        status: 503,
        headers: { "Retry-After": "0.001" },
    });
const status = (state: "loading" | "ready" | "failed") =>
    new Response(
        JSON.stringify({
            schema: HISTORY_SCHEMA,
            state,
            stage: "checking",
            completed: 1,
            total: 2,
        }),
    );

test("background loading waits for ready status before retrying metadata", async (t) => {
    const responses = [
        pending(),
        status("loading"),
        status("ready"),
        new Response('{"catalogId":"verified"}'),
    ];
    const paths: string[] = [];
    t.mock.method(globalThis, "fetch", async (path: string) => {
        paths.push(path);
        return responses.shift()!;
    });
    const states: string[] = [];
    const metadata = await readHistoryWhenReady(
        "/metadata",
        new AbortController().signal,
        (value) => states.push(value.state),
    );
    assert.deepEqual(metadata, { catalogId: "verified" });
    assert.deepEqual(states, ["loading", "ready"]);
    assert.deepEqual(
        paths.map((path) => path.split("/").at(-1)),
        ["metadata", "status", "status", "metadata"],
    );
});

test("failed verification stops polling and fails closed", async (t) => {
    const responses = [pending(), status("failed")];
    const fetch = t.mock.method(globalThis, "fetch", async () =>
        responses.shift()!,
    );
    await assert.rejects(
        readHistoryWhenReady("/metadata", new AbortController().signal),
        /核對未通過/,
    );
    assert.equal(fetch.mock.callCount(), 2);
});

test("ordinary 404 and 503 errors are never treated as background loading", async (t) => {
    for (const code of [404, 503]) {
        const fetch = t.mock.method(
            globalThis,
            "fetch",
            async () =>
                new Response('{"detail":"unavailable"}', { status: code }),
        );
        await assert.rejects(
            readHistoryWhenReady("/metadata", new AbortController().signal),
            (error: unknown) =>
                error instanceof Error &&
                !(error instanceof HistoryLoadingError),
        );
        assert.equal(fetch.mock.callCount(), 1);
        fetch.mock.restore();
    }
});

test("leaving the page cancels the loading delay without another request", async (t) => {
    const fetch = t.mock.method(
        globalThis,
        "fetch",
        async () =>
            new Response(JSON.stringify({ detail: { state: "loading" } }), {
                status: 503,
                headers: { "Retry-After": "30" },
            }),
    );
    const controller = new AbortController();
    const result = readHistoryWhenReady("/metadata", controller.signal);
    const assertion = assert.rejects(result, { name: "AbortError" });
    await new Promise((resolve) => setTimeout(resolve, 5));
    controller.abort();
    await assertion;
    assert.equal(fetch.mock.callCount(), 1);
});

test("only the explicit loading response exposes HistoryLoadingError", async (t) => {
    t.mock.method(globalThis, "fetch", async () => pending());
    await assert.rejects(
        readHistory("/metadata", new AbortController().signal),
        (error: unknown) =>
            error instanceof HistoryLoadingError && error.retryAfterMs === 1,
    );
});

test("malformed readiness status stops polling rather than retrying indefinitely", async (t) => {
    const responses = [
        pending(),
        new Response('{"schema":"wrong","state":"ready"}'),
    ];
    const fetch = t.mock.method(globalThis, "fetch", async () =>
        responses.shift()!,
    );
    await assert.rejects(
        readHistoryWhenReady("/metadata", new AbortController().signal),
        /狀態不完整/,
    );
    assert.equal(fetch.mock.callCount(), 2);
});

const pinA = { versionId: "synthetic/one", manifestSha256: "a".repeat(64) };
const pinB = { versionId: "synthetic/two", manifestSha256: "b".repeat(64) };

test("explicit history pin is carried through metadata, status and retry", async (t) => {
    const paths: string[] = [];
    const bodies = [
        pending(),
        new Response(
            JSON.stringify({
                schema: HISTORY_SCHEMA,
                state: "ready",
                bundleIdentity: pinA,
            }),
        ),
        new Response(
            JSON.stringify({
                catalogId: pinA.manifestSha256,
                bundleIdentity: pinA,
            }),
        ),
    ];
    t.mock.method(globalThis, "fetch", async (path: string) => {
        paths.push(path);
        return bodies.shift()!;
    });
    await readHistoryWhenReady(
        "/metadata",
        new AbortController().signal,
        undefined,
        pinA,
    );
    assert.equal(paths.length, 3);
    for (const path of paths) {
        const query = new URL(path, "https://test.invalid").searchParams;
        assert.equal(query.get("version_id"), pinA.versionId);
        assert.equal(query.get("manifest_sha256"), pinA.manifestSha256);
    }
});

test("wrong or missing response identity never silently becomes the requested version", async (t) => {
    for (const payload of [
        { catalogId: pinA.manifestSha256 },
        { catalogId: pinB.manifestSha256, bundleIdentity: pinB },
        { catalogId: pinB.manifestSha256, bundleIdentity: pinA },
    ]) {
        const mock = t.mock.method(
            globalThis,
            "fetch",
            async () => new Response(JSON.stringify(payload)),
        );
        await assert.rejects(
            readHistory("/metadata", new AbortController().signal, pinA),
        );
        assert.equal(mock.mock.callCount(), 1);
        mock.mock.restore();
    }
});

test("a fetch that ignores cancellation cannot return a stale successful payload", async (t) => {
    const controller = new AbortController();
    t.mock.method(globalThis, "fetch", async () => {
        controller.abort();
        return new Response(
            JSON.stringify({
                bundleIdentity: pinA,
                catalogId: pinA.manifestSha256,
            }),
        );
    });
    await assert.rejects(
        readHistory("/frame?date=2020-01-02", controller.signal, pinA),
        { name: "AbortError" },
    );
});

test("loading status from another version stops retry before a default metadata read", async (t) => {
    const responses = [
        pending(),
        new Response(
            JSON.stringify({
                schema: HISTORY_SCHEMA,
                state: "ready",
                bundleIdentity: pinB,
            }),
        ),
    ];
    const mock = t.mock.method(globalThis, "fetch", async () =>
        responses.shift()!,
    );
    await assert.rejects(
        readHistoryWhenReady(
            "/metadata",
            new AbortController().signal,
            undefined,
            pinA,
        ),
    );
    assert.equal(mock.mock.callCount(), 2);
});
