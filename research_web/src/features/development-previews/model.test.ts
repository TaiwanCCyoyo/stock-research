import assert from "node:assert/strict";
import { test } from "node:test";
import {
    loadPreviews,
    localPreviewUrl,
    openMainDashboard,
    readPreviewIndex,
    startPreview,
} from "./model.ts";

const item = {
    id: "report-preview",
    title: "研究報告",
    pr: 113,
    branch: "codex/report",
    head: "12345678",
    status: "ready",
    message: "",
    url: "http://127.0.0.1:15177/#report/example",
};

test("preview navigation accepts only explicit loopback HTTP ports without credentials", () => {
    assert.equal(localPreviewUrl(item.url), item.url);
    for (const url of [
        "javascript:alert(1)",
        "https://example.com",
        "http://127.0.0.1.evil:5177",
        "http://localhost:5177",
        "http://user@127.0.0.1:5177",
        "//127.0.0.1:5177",
        "http://127.0.0.1/",
    ]) {
        assert.equal(localPreviewUrl(url), null, url);
    }
});

test("unsafe ready links become unavailable and unsafe return links are omitted", () => {
    const index = readPreviewIndex({
        items: [{ ...item, url: "https://example.com" }],
        current: {
            id: "a",
            title: "a",
            pr: null,
            mainUrl: "https://example.com",
        },
    });
    assert.equal(index.items[0]?.status, "unavailable");
    assert.equal(index.items[0]?.url, null);
    assert.equal(index.current, null);
});

test("preview index preserves stopped, starting, empty and current context states", () => {
    assert.deepEqual(readPreviewIndex({ items: [], current: null }), {
        items: [],
        current: null,
    });
    const current = {
        id: "report-preview",
        title: "研究報告",
        pr: 113,
        mainUrl: "http://127.0.0.1:5177/",
    };
    const index = readPreviewIndex({
        items: [item, { ...item, id: "other", status: "starting", url: null }],
        current,
    });
    assert.equal(index.items[1]?.status, "starting");
    assert.deepEqual(index.current, current);
    assert.throws(() =>
        readPreviewIndex({ items: [{ ...item, id: "../outside" }] }),
    );
    assert.throws(() =>
        readPreviewIndex({ items: [{ ...item, status: "anything" }] }),
    );
});

test("loading is read-only and forwards cancellation without retrying", async () => {
    const controller = new AbortController();
    let calls = 0;
    const fetcher: typeof fetch = async (_url, options) => {
        calls++;
        assert.equal(options?.method, undefined);
        assert.equal(options?.signal, controller.signal);
        assert.equal(options?.cache, "no-store");
        return Response.json({ items: [item], current: null });
    };
    assert.equal(
        (
            await loadPreviews(
                "/api/development-previews",
                controller.signal,
                fetcher,
            )
        ).items.length,
        1,
    );
    assert.equal(calls, 1);
    await assert.rejects(
        loadPreviews(
            "/api/development-previews",
            controller.signal,
            async () => new Response("bad", { status: 503 }),
        ),
        /暫時無法取得/,
    );
    await assert.rejects(
        loadPreviews(
            "/api/development-previews",
            controller.signal,
            async () => {
                throw new DOMException("Aborted", "AbortError");
            },
        ),
        { name: "AbortError" },
    );
});

test("launch uses explicit protected POST and accepts only ready or starting", async () => {
    const signal = new AbortController().signal;
    const fetcher: typeof fetch = async (_url, options) => {
        assert.equal(options?.method, "POST");
        assert.equal(
            new Headers(options?.headers).get("X-Requested-With"),
            "development-preview",
        );
        assert.equal(options?.signal, signal);
        return Response.json({
            status: "starting",
            url: null,
            message: "正在啟動",
        });
    };
    await startPreview(
        "/api/development-previews/report-preview/open",
        signal,
        fetcher,
    );
    await assert.rejects(
        startPreview(
            "/api/development-previews/report-preview/open",
            signal,
            async () => Response.json({ detail: "來源不符" }, { status: 403 }),
        ),
        /來源不符/,
    );
    await assert.rejects(
        startPreview(
            "/api/development-previews/report-preview/open",
            signal,
            async () =>
                Response.json({ status: "unavailable", message: "目錄不存在" }),
        ),
        /目錄不存在/,
    );
});

test("network and malformed JSON failures explain the next action in Chinese", async () => {
    const signal = new AbortController().signal;
    const network: typeof fetch = async () => {
        throw new TypeError("Failed to fetch");
    };
    const malformed: typeof fetch = async () =>
        new Response("<html>wrong service</html>");
    await assert.rejects(
        loadPreviews("/previews", signal, network),
        /無法連上預覽服務/,
    );
    await assert.rejects(
        loadPreviews("/previews", signal, malformed),
        /預覽清單無法讀取/,
    );
    await assert.rejects(
        startPreview("/previews/open", signal, network),
        /尚未確認是否啟動/,
    );
    await assert.rejects(
        startPreview("/previews/open", signal, malformed),
        /無法確認啟動結果/,
    );
});

test("launch cancellation stays recognizable during fetch and body reading", async () => {
    const signal = new AbortController().signal;
    const abort = new DOMException("Aborted", "AbortError");
    await assert.rejects(
        startPreview("/previews/open", signal, async () => {
            throw abort;
        }),
        { name: "AbortError" },
    );
    const abortedBody: typeof fetch = async () => {
        const response = Response.json({});
        response.json = async () => {
            throw abort;
        };
        return response;
    };
    await assert.rejects(startPreview("/previews/open", signal, abortedBody), {
        name: "AbortError",
    });
    await assert.rejects(loadPreviews("/previews", signal, abortedBody), {
        name: "AbortError",
    });
});

const mainUrl = "http://127.0.0.1:5177/";
const mainStatus = "/api/development-main";

test("return to main starts once and polls without launching again before navigation", async () => {
    const requests: { url: string; method: string }[] = [];
    let waits = 0;
    const fetcher: typeof fetch = async (url, options) => {
        requests.push({ url: String(url), method: options?.method ?? "GET" });
        if (requests.length === 1) {
            assert.equal(
                new Headers(options?.headers).get("X-Requested-With"),
                "development-preview",
            );
        } else assert.equal(options?.headers, undefined);
        return Response.json(
            requests.length < 3
                ? { status: "starting", url: null, message: "" }
                : { status: "ready", url: mainUrl, message: "" },
        );
    };
    assert.equal(
        await openMainDashboard(
            mainStatus,
            mainUrl,
            new AbortController().signal,
            {
                fetcher,
                wait: async () => {
                    waits++;
                },
            },
        ),
        mainUrl,
    );
    assert.deepEqual(requests, [
        { url: `${mainStatus}/open`, method: "POST" },
        { url: mainStatus, method: "GET" },
        { url: mainStatus, method: "GET" },
    ]);
    assert.equal(waits, 2);
});

test("already running main returns immediately without status polling", async () => {
    let calls = 0;
    assert.equal(
        await openMainDashboard(
            mainStatus,
            mainUrl,
            new AbortController().signal,
            {
                fetcher: async () => {
                    calls++;
                    return Response.json({
                        status: "ready",
                        url: mainUrl,
                        message: "",
                    });
                },
                wait: async () => {
                    assert.fail("ready main must not wait");
                },
            },
        ),
        mainUrl,
    );
    assert.equal(calls, 1);
});

test("return to main rejects another loopback service and unsafe or missing URLs", async () => {
    for (const url of [
        "http://127.0.0.1:5178/",
        "http://127.0.0.1:5177/#different",
        "https://example.com/",
        "javascript:alert(1)",
        null,
    ]) {
        await assert.rejects(
            openMainDashboard(
                mainStatus,
                mainUrl,
                new AbortController().signal,
                {
                    fetcher: async () =>
                        Response.json({ status: "ready", url, message: "" }),
                },
            ),
            /網址與預期不同/,
        );
    }
    await assert.rejects(
        openMainDashboard(
            mainStatus,
            "https://example.com",
            new AbortController().signal,
            {
                fetcher: async () => {
                    assert.fail("invalid main URL must not launch");
                },
            },
        ),
        /正式版網址無法確認/,
    );
});

test("stopped, unavailable and malformed main states leave the preview usable", async () => {
    for (const status of ["stopped", "unavailable", "unknown"]) {
        await assert.rejects(
            openMainDashboard(
                mainStatus,
                mainUrl,
                new AbortController().signal,
                {
                    fetcher: async () =>
                        Response.json({ status, url: null, message: "" }),
                    wait: async () => {
                        assert.fail("terminal failure must not poll");
                    },
                },
            ),
            /正式版/,
        );
    }
    await assert.rejects(
        openMainDashboard(mainStatus, mainUrl, new AbortController().signal, {
            fetcher: async () => new Response("<html>wrong service</html>"),
        }),
        /無法確認正式版狀態/,
    );
});

test("main polling failure is readable and does not silently relaunch", async () => {
    let calls = 0;
    await assert.rejects(
        openMainDashboard(mainStatus, mainUrl, new AbortController().signal, {
            fetcher: async () => {
                if (++calls === 1)
                    return Response.json({
                        status: "starting",
                        url: null,
                        message: "",
                    });
                throw new TypeError("Failed to fetch");
            },
            wait: async () => {},
        }),
        /無法連上預覽服務/,
    );
    assert.equal(calls, 2);
});

test("main polling stops at its bound and keeps the current page", async () => {
    let calls = 0;
    await assert.rejects(
        openMainDashboard(mainStatus, mainUrl, new AbortController().signal, {
            fetcher: async () => {
                calls++;
                return Response.json({
                    status: "starting",
                    url: null,
                    message: "",
                });
            },
            wait: async () => {},
            pollLimit: 2,
        }),
        /準備時間較長/,
    );
    assert.equal(calls, 3);
});

test("cancelled main waits cannot return a navigation URL or issue another request", async () => {
    const controller = new AbortController();
    let calls = 0;
    await assert.rejects(
        openMainDashboard(mainStatus, mainUrl, controller.signal, {
            fetcher: async () => {
                calls++;
                return Response.json({
                    status: "starting",
                    url: null,
                    message: "",
                });
            },
            wait: async () => {
                controller.abort();
            },
        }),
        { name: "AbortError" },
    );
    assert.equal(calls, 1);
    await assert.rejects(
        openMainDashboard(mainStatus, mainUrl, controller.signal, {
            fetcher: async () => {
                assert.fail("cancelled request must not start main");
            },
        }),
        { name: "AbortError" },
    );
});

test("main readiness timeout aborts a stalled request after twelve minutes", async (context) => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const pending = openMainDashboard(
        mainStatus,
        mainUrl,
        new AbortController().signal,
        {
            fetcher: async (_url, options) =>
                new Promise((_resolve, reject) => {
                    options?.signal?.addEventListener(
                        "abort",
                        () => reject(options.signal?.reason),
                        { once: true },
                    );
                }),
        },
    );
    const rejected = assert.rejects(pending, /準備時間較長/);
    context.mock.timers.tick(12 * 60 * 1000);
    await rejected;
});
