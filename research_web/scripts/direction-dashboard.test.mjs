import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { studioRoute } from "../src/app/routes.ts";
import {
    readDirectionIndex,
    readDirectionDetail,
    interactiveModel,
} from "../src/features/direction-discussion/model.ts";
import {
    fetchDirectionIndex,
    fetchDirectionDetail,
} from "../src/features/direction-discussion/api.ts";
import { attachDiscussion } from "../src/features/direction-discussion/adapter.ts";

const taskId = "20261102-direction-test";
const revision = "a".repeat(40);
const page = await readFile(
    new URL("../discussion-kit/v1/index.html", import.meta.url),
    "utf8",
);
const model = JSON.parse(
    page.match(
        /<script id="discussion-data" type="application\/json">([\s\S]*?)<\/script>/,
    )[1],
);
model.demo = false;
model.source = {
    taskId,
    revision,
    draftPath: `tasks/${taskId}/direction-draft.md`,
};
const detail = {
    schema: "direction-draft.v1",
    mode: "local-private",
    taskId,
    status: "ready",
    revision,
    message: null,
    draftMarkdown: "# 方向草稿\n<script>not executable</script>",
    model,
};
const index = {
    schema: "direction-drafts.v1",
    mode: "local-private",
    items: [{ taskId, status: "ready", revision, message: null }],
};
const clone = (value) => structuredClone(value);

test("direction routes reject traversal, malformed escapes and invalid task identifiers", () => {
    assert.deepEqual(studioRoute(`#direction/${taskId}`), {
        page: "direction",
        directionId: taskId,
        runId: null,
    });
    assert.equal(studioRoute("#directions").page, "directions");
    for (const route of [
        "#direction",
        "#direction/",
        "#direction/%zz",
        "#direction/../secret",
        "#direction/20261102-test%2Fsecret",
        "#direction/demo-task",
        "#direction/20261102--bad",
        "#direction/20261102-UPPER",
        "#direction/20261102-good%00",
    ]) {
        assert.deepEqual(
            studioRoute(route),
            { page: "directions", runId: null },
            route,
        );
    }
});

test("list enforces mode identity and does not show private drafts in synthetic mode", () => {
    assert.equal(
        readDirectionIndex(index, "local-private").items[0].taskId,
        taskId,
    );
    assert.throws(
        () => readDirectionIndex(index, "public-synthetic"),
        /模式不一致/,
    );
    assert.throws(
        () =>
            readDirectionIndex(
                { ...index, mode: "public-synthetic" },
                "public-synthetic",
            ),
        /不應載入私人/,
    );
    assert.deepEqual(
        readDirectionIndex(
            { ...index, mode: "public-synthetic", items: [] },
            "public-synthetic",
        ).items,
        [],
    );
    assert.throws(
        () =>
            readDirectionIndex(
                { ...index, items: [...index.items, ...index.items] },
                "local-private",
            ),
        /重複/,
    );
    assert.throws(() =>
        readDirectionIndex(
            { ...index, items: [{ ...index.items[0], revision: "short" }] },
            "local-private",
        ),
    );
});

test("detail enforces requested task and keeps canonical text separate from interactive identity errors", () => {
    const parsed = readDirectionDetail(detail, taskId, "local-private");
    assert.equal(interactiveModel(parsed).source.revision, revision);
    assert.throws(
        () => readDirectionDetail(detail, "20261102-another", "local-private"),
        /目前頁面不同/,
    );
    assert.throws(
        () => readDirectionDetail(detail, taskId, "public-synthetic"),
        /不提供私人/,
    );
    for (const change of [
        (value) => {
            value.model.source.revision = "b".repeat(40);
        },
        (value) => {
            value.model.source.taskId = "20261102-another";
        },
        (value) => {
            value.model.source.draftPath = "../another/direction-draft.md";
        },
        (value) => {
            value.model.demo = true;
        },
    ]) {
        const value = clone(detail);
        change(value);
        const result = readDirectionDetail(value, taskId, "local-private");
        assert.equal(result.draftMarkdown, detail.draftMarkdown);
        assert.throws(() => interactiveModel(result), /版本不一致/);
    }
});

test("full uppercase SHA revisions are accepted without weakening exact model identity", () => {
    const uppercaseRevision = "ABCDEF0123".repeat(4);
    const uppercaseIndex = clone(index);
    uppercaseIndex.items[0].revision = uppercaseRevision;
    assert.equal(
        readDirectionIndex(uppercaseIndex, "local-private").items[0].revision,
        uppercaseRevision,
    );
    const uppercaseDetail = clone(detail);
    uppercaseDetail.revision = uppercaseRevision;
    uppercaseDetail.model.source.revision = uppercaseRevision;
    const parsed = readDirectionDetail(
        uppercaseDetail,
        taskId,
        "local-private",
    );
    assert.equal(interactiveModel(parsed).source.revision, uppercaseRevision);
    uppercaseDetail.model.source.revision = "B".repeat(40);
    assert.throws(
        () =>
            interactiveModel(
                readDirectionDetail(uppercaseDetail, taskId, "local-private"),
            ),
        /版本不一致/,
    );
    uppercaseDetail.model.source.revision = uppercaseRevision.toLowerCase();
    assert.throws(
        () =>
            interactiveModel(
                readDirectionDetail(uppercaseDetail, taskId, "local-private"),
            ),
        /版本不一致/,
    );
});

test("adapter validates before mounting and delegates cleanup for each task revision", () => {
    const calls = [];
    const fakeKit = {
        validateModel(value) {
            calls.push(["validate", value.source.revision]);
        },
        mount(_root, value) {
            calls.push(["mount", value.source.revision]);
            return {
                destroy() {
                    calls.push(["destroy", value.source.revision]);
                },
            };
        },
    };
    const stop = attachDiscussion({}, detail, fakeKit);
    stop();
    const newer = clone(detail);
    newer.revision = "b".repeat(40);
    newer.model.source.revision = newer.revision;
    const stopNewer = attachDiscussion({}, newer, fakeKit);
    stopNewer();
    assert.deepEqual(
        calls.map(([name]) => name),
        ["validate", "mount", "destroy", "validate", "mount", "destroy"],
    );
    const invalid = clone(detail);
    invalid.model.source.revision = "wrong";
    assert.throws(() => attachDiscussion({}, invalid, fakeKit));
    assert.equal(calls.length, 6);
    assert.throws(() =>
        attachDiscussion({}, detail, {
            ...fakeKit,
            validateModel() {
                throw new Error("invalid model");
            },
        }),
    );
    assert.equal(calls.length, 6);
});

test("API requests mode explicitly and rejects non-JSON or mismatched-mode responses", async () => {
    const requests = [];
    const fetcher = async (url, options) => {
        requests.push({ url, options });
        return Response.json(index);
    };
    const signal = new AbortController().signal;
    await fetchDirectionIndex(signal, "local-private", fetcher);
    assert.equal(requests[0].url, "/api/direction-drafts");
    assert.equal(
        requests[0].options.headers["X-Research-Data-Mode"],
        "local-private",
    );
    assert.equal(requests[0].options.cache, "no-store");
    await assert.rejects(
        fetchDirectionIndex(signal, "public-synthetic", fetcher),
        /模式不一致/,
    );
    await assert.rejects(
        fetchDirectionIndex(
            signal,
            "local-private",
            async () =>
                new Response("<html>fallback</html>", {
                    headers: { "Content-Type": "text/html" },
                }),
        ),
        /沒有回傳/,
    );
    await assert.rejects(
        fetchDirectionIndex(
            signal,
            "local-private",
            async () => new Response("", { status: 503 }),
        ),
        /503/,
    );
});

test("detail sends no request for unsafe ID or public mode", async () => {
    let calls = 0;
    const fetcher = async () => {
        calls++;
        return Response.json(detail);
    };
    const signal = new AbortController().signal;
    await assert.rejects(
        fetchDirectionDetail("../secret", signal, "local-private", fetcher),
    );
    await assert.rejects(
        fetchDirectionDetail(taskId, signal, "public-synthetic", fetcher),
    );
    assert.equal(calls, 0);
    const result = await fetchDirectionDetail(
        taskId,
        signal,
        "local-private",
        fetcher,
    );
    assert.equal(result.taskId, taskId);
});

test("a response completing after navigation cancellation cannot return an old draft", async () => {
    const controller = new AbortController();
    let finish;
    const pending = fetchDirectionDetail(
        taskId,
        controller.signal,
        "local-private",
        async () => ({
            ok: true,
            headers: new Headers({ "Content-Type": "application/json" }),
            json: () =>
                new Promise((resolve) => {
                    finish = resolve;
                }),
        }),
    );
    await new Promise((resolve) => setImmediate(resolve));
    controller.abort();
    finish(detail);
    await assert.rejects(pending, { name: "AbortError" });
});

test("rendered states distinguish loading, errors, private-empty and synthetic mode, with safe raw source", async () => {
    const server = await createServer({
        logLevel: "silent",
        server: { middlewareMode: true, hmr: false },
    });
    try {
        const {
            DirectionListContent,
            DirectionDetailContent,
            DirectionEntrance,
        } = await server.ssrLoadModule(
            "/src/features/direction-discussion/DirectionDiscussionPage.tsx",
        );
        const renderList = (state) =>
            renderToStaticMarkup(
                createElement(DirectionListContent, { state, retry() {} }),
            );
        assert.match(
            renderList({ status: "loading" }),
            /role="status".*正在讀取/s,
        );
        const failed = renderList({
            status: "error",
            message: "API 暫時不可用",
        });
        assert.match(failed, /role="alert"/);
        assert.match(failed, /重新讀取/);
        assert.match(
            renderList({ status: "loaded", data: { ...index, items: [] } }),
            /目前還沒有研究方向草稿/,
        );
        assert.match(
            renderList({
                status: "loaded",
                data: { ...index, mode: "public-synthetic", items: [] },
            }),
            /示範模式不顯示私人草稿/,
        );
        assert.match(
            renderList({ status: "loaded", data: index }),
            new RegExp(`#direction/${taskId}`),
        );
        const raw = renderToStaticMarkup(
            createElement(DirectionDetailContent, {
                detail: { ...detail, status: "draft-only", model: null },
            }),
        );
        assert.match(raw, /已有草稿原文/);
        assert.match(raw, /&lt;script&gt;not executable&lt;\/script&gt;/);
        assert.ok(!raw.includes("<script>not executable</script>"));
        assert.match(
            renderToStaticMarkup(createElement(DirectionEntrance)),
            /href="#directions"/,
        );
        const { StudiesPage } = await server.ssrLoadModule(
            "/src/features/studies/StudiesPage.tsx",
        );
        const studies = renderToStaticMarkup(createElement(StudiesPage));
        assert.match(studies, /href="#directions"/);
        assert.match(studies, /正在讀取研究/);
    } finally {
        await server.close();
    }
});
