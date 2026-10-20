import assert from "node:assert/strict";
import { test } from "node:test";
import { readShared } from "./api.ts";

test("explicit warmup retries then returns JSON", async () => {
    let calls = 0;
    const fetcher = (async () =>
        ++calls === 1
            ? Response.json(
                  { detail: "正在核對" },
                  { status: 503, headers: { "Retry-After": "1" } },
              )
            : Response.json({ code: "SYNTH" })) as typeof fetch;
    assert.deepEqual(
        await readShared(
            "fixture",
            new AbortController().signal,
            fetcher,
            async () => {},
        ),
        { code: "SYNTH" },
    );
    assert.equal(calls, 2);
});
test("warmup retries are bounded and show the backend error", async () => {
    let calls = 0;
    const fetcher = (async () => {
        calls++;
        return Response.json(
            { detail: "正在核對" },
            { status: 503, headers: { "Retry-After": "1" } },
        );
    }) as typeof fetch;
    await assert.rejects(
        readShared(
            "fixture",
            new AbortController().signal,
            fetcher,
            async () => {},
        ),
        /正在核對/,
    );
    assert.equal(calls, 21);
});
test("permanent errors do not retry and HTML fallback is explicit", async () => {
    const controller = new AbortController();
    await assert.rejects(
        readShared("fixture", controller.signal, (async () =>
            Response.json(
                { detail: "unknown symbol" },
                { status: 404 },
            )) as typeof fetch),
        /unknown symbol/,
    );
    await assert.rejects(
        readShared(
            "fixture",
            controller.signal,
            (async () => new Response("<html/>")) as typeof fetch,
        ),
        /本機私有資料 API/,
    );
});
test("aborted requests cannot return stale JSON", async () => {
    const controller = new AbortController();
    const fetcher = (async () => {
        controller.abort();
        return Response.json({ code: "old" });
    }) as typeof fetch;
    await assert.rejects(readShared("fixture", controller.signal, fetcher), {
        name: "AbortError",
    });
});
