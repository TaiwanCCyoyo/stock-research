import assert from "node:assert/strict";
import { test } from "node:test";
import { apiUrl } from "../../api/base.ts";
import { readShared, recoverSymbolNames } from "./api.ts";
import { resolveSymbolInput } from "./model.ts";

test("default API root preserves shared discovery, symbols and series paths", () => {
    for (const path of [
        "families",
        "adjusted-daily-v1/symbols",
        "adjusted-daily-v1/series?code=SYNTH&basis=raw",
    ]) {
        assert.equal(
            apiUrl(`/shared-data/v1/${path}`),
            `/api/shared-data/v1/${path}`,
        );
    }
    assert.equal(apiUrl("/tasks"), "/api/tasks");
});

test("configured remote API root applies to shared endpoints without changing queries", () => {
    for (const base of [
        "https://api.example.test/research",
        "https://api.example.test/research/",
    ]) {
        for (const path of [
            "families",
            "adjusted-daily-v1/symbols",
            "adjusted-daily-v1/series?code=SYNTH&basis=raw",
        ]) {
            assert.equal(
                apiUrl(`/shared-data/v1/${path}`, base),
                `https://api.example.test/research/shared-data/v1/${path}`,
            );
        }
        assert.equal(
            apiUrl("/tasks", base),
            "https://api.example.test/research/tasks",
        );
    }
});

test("same-origin custom and empty API roots remain supported", () => {
    assert.equal(
        apiUrl("shared-data/v1/families", "/custom-api/"),
        "/custom-api/shared-data/v1/families",
    );
    assert.equal(
        apiUrl("/shared-data/v1/families", ""),
        "/shared-data/v1/families",
    );
});

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

function symbolResponse(available: boolean, generation = "synthetic-v1") {
    return {
        generation,
        status_sha256: "synthetic-sha",
        namesAvailable: available,
        symbols: [
            {
                code: "SYNTH",
                name: available ? "合成公司" : "",
                market: "TEST",
                first: "2020-01-01",
                last: "2020-01-03",
            },
        ],
    };
}
test("names recover in place on minute intervals and stop immediately on success", async () => {
    const waits: number[] = [];
    let calls = 0;
    let active = 0;
    let symbols = symbolResponse(false).symbols;
    const result = await recoverSymbolNames(
        new AbortController().signal,
        "synthetic-v1",
        (data) => {
            symbols = data.symbols;
        },
        (async (path) => {
            assert.equal(path, "/api/shared-data/v1/adjusted-daily-v1/symbols");
            assert.equal(++active, 1);
            calls++;
            active--;
            return Response.json(symbolResponse(calls === 3));
        }) as typeof fetch,
        async (ms) => {
            waits.push(ms);
            assert.equal(resolveSymbolInput("合成公司", symbols), null);
        },
    );
    assert.equal(result, "available");
    assert.equal(calls, 3);
    assert.deepEqual(waits, [60_000, 60_000]);
    assert.equal(symbols[0].name, "合成公司");
    assert.equal(resolveSymbolInput("合成公司", symbols), "SYNTH");
    assert.equal(resolveSymbolInput("SYNTH 合成公司", symbols), "SYNTH");
});
test("names stop after exactly sixty low-frequency retries and a fresh pump restarts", async () => {
    let calls = 0;
    let waits = 0;
    const fetcher = (async () => {
        calls++;
        return Response.json(symbolResponse(false));
    }) as typeof fetch;
    assert.equal(
        await recoverSymbolNames(
            new AbortController().signal,
            "synthetic-v1",
            () => {},
            fetcher,
            async (ms) => {
                assert.equal(ms, 60_000);
                waits++;
            },
        ),
        "exhausted",
    );
    assert.equal(calls, 61);
    assert.equal(waits, 60);
    assert.equal(
        await recoverSymbolNames(
            new AbortController().signal,
            "synthetic-v1",
            () => {},
            (async () => Response.json(symbolResponse(true))) as typeof fetch,
        ),
        "available",
    );
});
test("aborting a real pending retry timer prevents another request", async () => {
    const controller = new AbortController();
    let calls = 0;
    const pending = recoverSymbolNames(
        controller.signal,
        "synthetic-v1",
        () => {
            queueMicrotask(() => controller.abort());
        },
        (async () => {
            calls++;
            return Response.json(symbolResponse(false));
        }) as typeof fetch,
    );
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(calls, 1);
});
test("aborted in-flight names cannot update options even when fetch ignores cancellation", async () => {
    const controller = new AbortController();
    let release!: (value: Response) => void;
    let updates = 0;
    const pending = recoverSymbolNames(
        controller.signal,
        "synthetic-v1",
        () => {
            updates++;
        },
        (() =>
            new Promise<Response>((resolve) => {
                release = resolve;
            })) as typeof fetch,
    );
    controller.abort();
    release(Response.json(symbolResponse(true)));
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(updates, 0);
});
test("generation mismatch never applies and initial unpinned pump pins first generation", async () => {
    let updates = 0;
    assert.equal(
        await recoverSymbolNames(
            new AbortController().signal,
            "synthetic-v2",
            () => {
                updates++;
            },
            (async () => Response.json(symbolResponse(true))) as typeof fetch,
        ),
        "generation-changed",
    );
    assert.equal(updates, 0);
    let calls = 0;
    assert.equal(
        await recoverSymbolNames(
            new AbortController().signal,
            "",
            () => {
                updates++;
            },
            (async () =>
                Response.json(
                    symbolResponse(
                        ++calls > 1,
                        calls === 1 ? "synthetic-v1" : "synthetic-v2",
                    ),
                )) as typeof fetch,
            async () => {},
        ),
        "generation-changed",
    );
    assert.equal(updates, 1);
    assert.equal(calls, 2);
});
