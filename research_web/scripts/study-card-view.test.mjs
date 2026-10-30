import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("report error notices explain partial availability and offer the right user action", async () => {
    const server = await createServer({
        logLevel: "silent",
        server: { middlewareMode: true, hmr: false },
    });
    try {
        const { ReportIndexNotice } = await server.ssrLoadModule(
            "/src/features/report-library/ReportIndexNotice.tsx",
        );
        const descendants = (element) => {
            if (!element || typeof element !== "object") return [];
            return [
                element,
                ...[element.props?.children]
                    .flat(Infinity)
                    .flatMap(descendants),
            ];
        };
        for (const issue of [
            "version_mismatch",
            "invalid_index",
            "http",
            "network",
        ]) {
            let retried = 0,
                reloaded = 0;
            const props = {
                issue,
                error: "synthetic diagnostic",
                loading: false,
                retry: () => retried++,
                reload: () => reloaded++,
            };
            const element = ReportIndexNotice(props);
            const html = renderToStaticMarkup(element);
            assert.match(html, /如果下方已顯示報告/);
            assert.match(html, /查看錯誤詳情/);
            assert.doesNotMatch(html, /資料來源/);
            assert.match(html, /href="#studies"/);
            assert.doesNotMatch(html, /<details[^>]*\bopen/);
            assert.equal(
                retried + reloaded,
                0,
                "no automatic retry or page reload",
            );
            const button = descendants(element).find(
                (node) => node.type === "button",
            );
            button.props.onClick();
            assert.equal(reloaded, issue === "version_mismatch" ? 1 : 0);
            assert.equal(retried, issue === "version_mismatch" ? 0 : 1);
            const loading = ReportIndexNotice({ ...props, loading: true });
            assert.equal(
                descendants(loading).find((node) => node.type === "button")
                    .props.disabled,
                true,
            );
        }
    } finally {
        await server.close();
    }
});

test("study cards keep unlike metrics separate and preserve reading context", async () => {
    const server = await createServer({
        logLevel: "silent",
        server: { middlewareMode: true, hmr: false },
    });
    try {
        const { StudyCardView } = await server.ssrLoadModule(
            "/src/features/studies/StudyCardView.tsx",
        );
        const html = renderToStaticMarkup(
            createElement(StudyCardView, {
                card: {
                    id: "synthetic-study",
                    date: "2025-12-31",
                    question: "合成研究問題",
                    answer: "合成研究結論，條件限制也必須保留。",
                    verdict: "mixed",
                    dataPeriod: null,
                    keyNumbers: [
                        {
                            label: "比較組數",
                            value: 28,
                            unit: "count",
                            highlight: false,
                        },
                        {
                            label: "達標比例",
                            value: 66.04,
                            unit: "percent",
                            highlight: true,
                        },
                        {
                            label: "價格倍數",
                            value: 2,
                            unit: "ratio",
                            highlight: false,
                        },
                    ],
                    limitation: "合成限制：不能推論實際交易績效。",
                    reportHref: "#report/synthetic-study",
                    accountRun: null,
                    caveats: [],
                    progress: null,
                    details: {
                        originalSummary: null,
                        reportPath: null,
                        webReportReason: null,
                        sharedData: ["synthetic-family"],
                        sharedDataReason: null,
                        note: null,
                        numberSources: [],
                    },
                },
            }),
        );
        assert.match(html, /<dt>比較組數<\/dt><dd>28<\/dd>/);
        assert.match(html, /<dt>達標比例<\/dt><dd>66\.04%<\/dd>/);
        assert.match(html, /<dt>價格倍數<\/dt><dd>2 倍<\/dd>/);
        assert.doesNotMatch(html, /u-bars|u-track|style="width/);
        assert.match(html, /2025\/12\/31/);
        assert.match(html, /不能推論實際交易績效/);
        assert.doesNotMatch(html, /is-clamped/);
        assert.match(html, /href="#report\/synthetic-study"/);
        assert.match(html, /href="#data">查看資料總覽/);
        assert.doesNotMatch(html, /<a[^>]*>synthetic-family<\/a>/);
    } finally {
        await server.close();
    }
});
