import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { StudyCaveats } from "./StudyCaveats.ts";
import test from "node:test";
import type { StudioHistoryItem } from "../../domain/strategies/types.ts";
import {
    cardFromHistory,
    cardFromReport,
    mergeStudyCards,
    filterStudies,
    groupByMonth,
    historyVerdict,
    plainSummary,
} from "./model.ts";

const item = (over: Partial<StudioHistoryItem> = {}): StudioHistoryItem => ({
    id: "20261013-annual-winner-rotation",
    date: "2026-10-13",
    title: "前一年領先股輪動",
    status: "已保存報告",
    conclusion: "",
    originalSummary: "",
    reportPath: "tasks/x/report.md",
    reviewConfirmed: true,
    evidenceState: "published_report_not_owner_adoption",
    registryEventIds: [],
    ...over,
});

test("a saved report without a recorded outcome gets no verdict badge", () => {
    assert.equal(historyVerdict(item()), null);
    assert.equal(
        historyVerdict(item({ outcome: "candidate_failed" })),
        "failed",
    );
    assert.equal(historyVerdict(item({ status: "研究中" })), "running");
});

test("summaries drop Markdown and keep only the first paragraph", () => {
    assert.equal(
        plainSummary(
            "這次研究的摘要：**核心結果。** 見 [HTML 報告](web-report/index.html)。\n\n第二段",
        ),
        "核心結果。 見 HTML 報告。",
    );
});

test("filters by verdict, report availability and search text", () => {
    const cards = [
        cardFromHistory(item({ outcome: "candidate_failed" })),
        cardFromHistory(
            item({
                id: "b",
                title: "強勢條件",
                webReportHref: "#report/b",
            }),
        ),
    ];
    assert.equal(filterStudies(cards, "failed", "").length, 1);
    assert.equal(filterStudies(cards, "report", "")[0]!.id, "b");
    assert.equal(filterStudies(cards, "all", "強勢")[0]!.id, "b");
});

test("timeline groups newest month first", () => {
    const groups = groupByMonth([
        cardFromHistory(item({ id: "a", date: "2026-09-30" })),
        cardFromHistory(item({ id: "b", date: "2026-10-02" })),
    ]);
    assert.deepEqual(
        groups.map((group) => group.label),
        ["2026 年 10 月", "2026 年 9 月"],
    );
});

test("unconfirmed plain summaries keep their caveat and original text", () => {
    const card = cardFromHistory(
        item({
            summarySource: "presentation-metadata",
            reviewConfirmed: false,
            originalSummary: "原文摘要",
            sharedData: ["adjusted-daily-v1"],
        }),
    );
    assert.equal(card.details.summaryUnconfirmed, true);
    assert.equal(card.details.originalSummary, "原文摘要");
    assert.deepEqual(card.details.sharedData, ["adjusted-daily-v1"]);
});

test("web reports stay listed without the history service and are not duplicated", () => {
    const report = cardFromReport({
        id: "20261021-momentum-only-doubling",
        title: "只看強勢條件的翻倍機率",
        summary: "摘要",
        date: "2026-10-21",
        status: "descriptive",
        period: "2010-01-04..2026-10-12",
        kit: "v1",
        tags: [],
    });
    assert.equal(report.reportHref, "#report/20261021-momentum-only-doubling");
    assert.deepEqual(
        mergeStudyCards(null, [report])?.map((card) => card.id),
        [report.id],
    );
    const history = cardFromHistory(item({ id: report.id }));
    assert.deepEqual(mergeStudyCards([history], [report]), [history]);
    assert.equal(mergeStudyCards(null, null), null);
});

test("retained old conclusions and unverified summaries warn beside the answer", () => {
    const stale = cardFromHistory(
        item({
            status: "登錄需更新",
            conclusion: "保留的舊結論。",
            summarySource: "presentation-metadata",
            reviewConfirmed: false,
        }),
    );
    assert.equal(stale.answer, "保留的舊結論。");
    assert.deepEqual(stale.caveats, [
        "目前顯示舊版，內容待核對",
        "摘要尚未核對，以原文為準",
    ]);
    const unavailable = cardFromHistory(
        item({
            status: "登錄需更新",
            evidenceState: "registration_unavailable",
        }),
    );
    assert.deepEqual(unavailable.caveats, ["內容待核對"]);
    const html = renderToStaticMarkup(
        createElement(StudyCaveats, { caveats: stale.caveats }),
    );
    assert.match(html, /role="note"/);
    assert.ok(html.includes("目前顯示舊版，內容待核對"));
});

test("confirmed or formal summaries show no warning", () => {
    const normal = cardFromHistory(
        item({ summarySource: "formal-report", reviewConfirmed: false }),
    );
    assert.deepEqual(normal.caveats, []);
    assert.deepEqual(
        cardFromHistory(
            item({
                summarySource: "presentation-metadata",
                reviewConfirmed: true,
            }),
        ).caveats,
        [],
    );
    assert.equal(
        renderToStaticMarkup(createElement(StudyCaveats, { caveats: [] })),
        "",
    );
});

test("compact and full cards both render the caveats", async () => {
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(
        new URL("./StudyCardView.tsx", import.meta.url),
        "utf8",
    );
    const view = source.slice(source.indexOf("export function StudyCardView"));
    const tag = "<StudyCaveats caveats={card.caveats} />";
    const at = view.indexOf(tag);
    assert.ok(at > 0, "StudyCardView renders StudyCaveats");
    const lineStart = view.lastIndexOf("{", at);
    assert.ok(
        !view.slice(lineStart, at).includes("compact"),
        "caveats are not gated by compact",
    );
});
