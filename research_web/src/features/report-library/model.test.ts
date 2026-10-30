import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { studioRoute } from "../../app/routes.ts";
import {
    filterReports,
    reportFrameSrc,
    reportNavigationHash,
    reportTags,
    statusLabel,
    validateReportIndex,
    readReportIndex,
    ReportIndexError,
    type ReportEntry,
} from "./model.ts";

const entry = (id: string, title: string, tags: string[]): ReportEntry => ({
    id,
    title,
    summary: "",
    date: "",
    status: "",
    period: "",
    kit: "v1",
    tags,
});

test("report loading distinguishes retryable failures without accepting mismatched versions", async () => {
    const signal = new AbortController().signal;
    const responses = [
        new Response("unavailable", { status: 503 }),
        new Response("<html>not an index</html>"),
        Response.json({
            schema: "research-reports.v1",
            version: "development",
            reports: [],
        }),
        Response.json({
            schema: "research-reports.v1",
            version: "release-123",
            reports: [],
        }),
    ];
    let calls = 0;
    const fetcher: typeof fetch = async (url, options) => {
        assert.equal(url, "/reports/index.json");
        assert.equal(options?.signal, signal);
        assert.equal(options?.cache, "no-store");
        return responses[calls++]!;
    };
    for (const code of ["http", "invalid_index", "version_mismatch"]) {
        await assert.rejects(
            readReportIndex(signal, "release-123", fetcher),
            (error: unknown) =>
                error instanceof ReportIndexError && error.code === code,
        );
    }
    assert.deepEqual(
        (await readReportIndex(signal, "release-123", fetcher)).reports,
        [],
    );
    assert.equal(calls, 4);
    const aborted = new AbortController();
    aborted.abort();
    await assert.rejects(
        readReportIndex(
            aborted.signal,
            "release-123",
            async (_url, options) => {
                options?.signal?.throwIfAborted();
                return responses[3]!;
            },
        ),
        { name: "AbortError" },
    );
});

test("search matches every word across title, id and tags, and a tag narrows", () => {
    const reports = [
        entry("20261012-hhhl-v4-variants", "高過高條件", ["HHHL", "型態"]),
        entry("20261020-pattern-scan", "型態寬掃", ["型態"]),
    ];
    assert.deepEqual(
        filterReports(reports, "hhhl 條件", null).map((r) => r.id),
        ["20261012-hhhl-v4-variants"],
    );
    assert.equal(filterReports(reports, "", "型態").length, 2);
    assert.equal(filterReports(reports, "寬掃", "HHHL").length, 0);
    assert.deepEqual(reportTags(reports), ["型態", "HHHL"]);
});

test("index validation rejects other shapes and labels unknown statuses plainly", () => {
    assert.throws(() => validateReportIndex({ reports: [] }));
    assert.equal(
        validateReportIndex({
            schema: "research-reports.v1",
            version: "a1b2c3",
            reports: [],
        }).version,
        "a1b2c3",
    );
    assert.equal(statusLabel("descriptive"), "描述性結果");
    assert.equal(statusLabel(""), "未標示");
});

test("report index version matches the current shell while legacy pages stay compatible", () => {
    const index = {
        schema: "research-reports.v1",
        version: "release-123",
        reports: [],
    };
    assert.equal(
        validateReportIndex(index, "release-123").version,
        "release-123",
    );
    assert.throws(
        () => validateReportIndex(index, "older-release"),
        /請重新載入頁面/,
    );
    assert.equal(
        validateReportIndex({ schema: "research-reports.v1", reports: [] })
            .reports.length,
        0,
    );
});

test("frame source encodes the id and carries the first-paint theme", () => {
    assert.equal(
        reportFrameSrc("a b", "ocean", "dark"),
        "/reports/a%20b/index.html#palette=ocean&appearance=dark",
    );
});

test("only this report frame can request the fixed shared-data route", () => {
    const frame = {};
    const message = { type: "rk:navigate", href: "#data" };
    assert.equal(reportNavigationHash(frame, frame, message), "#data");
    for (const source of [{}, null, undefined])
        assert.equal(reportNavigationHash(source, frame, message), null);
    assert.equal(reportNavigationHash(null, null, message), null);
    for (const data of [
        null,
        [],
        "#data",
        { ...message, type: "other" },
        { ...message, href: "https://example.com" },
        { ...message, href: "#data/2330" },
    ])
        assert.equal(reportNavigationHash(frame, frame, data), null);
    assert.equal(studioRoute("#data").page, "overview");
});

test("the actual report link posts to its host and keeps standalone navigation", () => {
    const script = readFileSync(
        new URL(
            "../../../../tasks/20261024-strength-weakening-flags/web-report/app.js",
            import.meta.url,
        ),
        "utf8",
    );
    const html = readFileSync(
        new URL(
            "../../../../tasks/20261024-strength-weakening-flags/web-report/index.html",
            import.meta.url,
        ),
        "utf8",
    );
    const link = html.match(/<a\b[^>]*\bid="shared-data-link"[^>]*>/)?.[0];
    assert.ok(link);
    assert.match(link, /href="\/#data"/);
    assert.doesNotMatch(link, /target=/);
    for (const embedded of [true, false]) {
        let click: ((event: { preventDefault(): void }) => void) | undefined;
        let start: (() => Promise<void>) | undefined;
        let prevented = false;
        const messages: unknown[] = [];
        const frame = {};
        const parent = {
            postMessage: (data: unknown, target: string) => {
                assert.equal(target, "*");
                messages.push(data);
            },
        };
        const page: Record<string, unknown> = {
            ReportKit: {},
            REPORT_READY: new Promise(() => {}),
        };
        page.parent = embedded ? parent : page;
        runInNewContext(script, {
            window: page,
            document: {
                querySelector: (selector: string) => {
                    assert.equal(selector, "#shared-data-link");
                    return {
                        addEventListener: (
                            type: string,
                            handler: typeof click,
                        ) => {
                            assert.equal(type, "click");
                            click = handler;
                        },
                    };
                },
                addEventListener: (type: string, handler: typeof start) => {
                    assert.equal(type, "DOMContentLoaded");
                    start = handler;
                },
            },
        });
        assert.ok(start);
        void start();
        assert.ok(click);
        click({
            preventDefault: () => {
                prevented = true;
            },
        });
        assert.equal(prevented, embedded);
        assert.equal(messages.length, embedded ? 1 : 0);
        if (embedded)
            assert.equal(
                reportNavigationHash(frame, frame, messages[0]),
                "#data",
            );
    }
});
