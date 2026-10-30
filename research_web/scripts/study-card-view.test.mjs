import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

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
