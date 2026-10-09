import assert from "node:assert/strict";
import { test } from "node:test";
import {
    filterHistoryItems,
    historyConclusion,
    historyOutcome,
    historySection,
} from "./historyModel.ts";

test("groups default old and unknown records to method, preserving failed cases", () => {
    const items = [
        { title: "failed", outcome: "candidate_failed" },
        { title: "unknown", section: "future" },
        { title: "market", section: "market" },
        { title: "design", section: "design" },
    ];
    const before = structuredClone(items);
    assert.equal(historySection({}), "method");
    assert.deepEqual(
        filterHistoryItems(items, "method", ""),
        items.slice(0, 2),
    );
    assert.deepEqual(filterHistoryItems(items, "market", ""), [items[2]]);
    assert.deepEqual(filterHistoryItems(items, "design", ""), [items[3]]);
    assert.deepEqual(items, before);
});

test("search reads current and saved titles and summaries across groups", () => {
    const item = {
        section: "market",
        title: "白話",
        savedTitle: "Original title",
        legacyPresentationTitle: "Previous display name",
        conclusion: "新摘要",
        originalSummary: "原始摘要",
    };
    for (const query of [
        "白話",
        "original TITLE",
        "新摘要",
        "原始摘要",
        "previous display name",
    ])
        assert.deepEqual(filterHistoryItems([item], "method", query), [item]);
});

test("only formal outcomes determine badges; drafts and report status cannot infer efficacy", () => {
    const item = {
        outcome: "candidate_failed",
        draftStatus: "已结案",
        status: "completed",
    };
    assert.equal(historyOutcome(item), "行不通");
    assert.equal(
        historyOutcome({ outcome: "candidate_passed" }),
        "通過研究門檻，尚未採用",
    );
    assert.equal(
        historyOutcome({
            outcome: null,
            ...{ status: "closed", draftStatus: "行不通" },
        }),
        "尚無正式判定",
    );
    assert.equal(historyOutcome({ outcome: "future" }), "尚無正式判定");
    assert.equal(historyOutcome({ outcome: "toString" }), "尚無正式判定");
});

test("summaries remove filler without truncating numbers or modifying saved evidence", () => {
    const item = {
        conclusion: "這次研究的摘要：報酬 7.86%，對照 7.88%。第二句。",
        originalSummary: "原文",
    };
    const before = structuredClone(item);
    assert.equal(historyConclusion(item), "報酬 7.86%，對照 7.88%。第二句。");
    assert.equal(
        historyConclusion({ conclusion: "**7.86% 對 7.88%。尚未確認。**" }),
        "**7.86% 對 7.88%。尚未確認。**",
    );
    assert.equal(
        historyConclusion({ conclusion: "first 1.5x paragraph\n\nsecond" }),
        "first 1.5x paragraph",
    );
    assert.equal(historyConclusion({ conclusion: null }), "");
    assert.equal(
        historyConclusion({
            conclusion: "通過初步篩選。仍未完成最後驗證，尚未採用。",
        }),
        "通過初步篩選。仍未完成最後驗證，尚未採用。",
    );
    assert.deepEqual(item, before);
});
