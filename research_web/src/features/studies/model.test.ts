import assert from "node:assert/strict";
import test from "node:test";
import type { StudioHistoryItem } from "../../domain/strategies/types.ts";
import {
    cardFromHistory,
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
