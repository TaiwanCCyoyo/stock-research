import assert from "node:assert/strict";
import test from "node:test";
import {
    currentStudyHash,
    pendingCard,
    readingState,
    readingLink,
    studiesBack,
    withReading,
    type ReadingRecord,
} from "./reading.ts";
import { cardsFromStudies } from "./v2.ts";
import { filterStudies } from "./model.ts";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("card links name the reading edition separately from its acceptance state", async () => {
    const server = await createServer({
        logLevel: "silent",
        server: { middlewareMode: true, hmr: false },
    });
    try {
        const { StudyCardView } = await server.ssrLoadModule(
            "/src/features/studies/StudyCardView.tsx",
        );
        const original = {
            ...pendingCard("20260906-five-slot-confirmation", "待整理"),
            reportHref: readingLink("20260906-five-slot-confirmation"),
        };
        for (const [card, label] of [
            [original, "查看原文"],
            [
                withReading(original, { ...record, state: "history" }),
                "查看閱讀版",
            ],
            [withReading(original, record), "讀報告"],
        ] as const) {
            const html = renderToStaticMarkup(
                createElement(StudyCardView, { card }),
            );
            const link = html.match(
                /<a\b[^>]*href="[^"]*view=reading[^"]*"[^>]*>([^<]*)<\/a>/,
            );
            assert.ok(link, "the readable document remains reachable");
            assert.equal(link[1], label);
            assert.ok(
                !link[0].includes("aria-label="),
                "visible link text remains its accessible name",
            );
        }
    } finally {
        await server.close();
    }
});

test("server rendering has a safe default research route without window", () => {
    assert.equal(currentStudyHash(), "");
    assert.equal(studiesBack(currentStudyHash()), "#studies");
});

const record: ReadingRecord = {
    schema: "report-reading.v1",
    task_id: "20260906-five-slot-confirmation",
    state: "ready",
    reason: "閱讀版核對完成",
    updated_at: "2026-11-02",
    edition: "reading-report.md",
    question: "候選通過確認了嗎？",
    answer: "沒有通過。",
    limitation: "限本次設定。",
    data_period: null,
    sources: [
        { label: "原報告", path: "20260906-five-slot-confirmation/report.md" },
    ],
};
test("readability does not follow a favorable verdict or mere report existence", () => {
    const old = {
        ...pendingCard(record.task_id, "待整理"),
        verdict: "promising" as const,
        reportHref: "#report/x",
    };
    assert.equal(readingState(old), "history");
    const accepted = withReading(old, record);
    assert.equal(readingState(accepted), "ready");
    assert.equal(accepted.answer, "沒有通過。");
    assert.equal(accepted.verdict, null);
    assert.deepEqual(accepted.keyNumbers, []);
});
test("unverifiable records remain identifiable without exposing their unverified claims", () => {
    const cards = cardsFromStudies({
        cards: [],
        warnings: [
            {
                task_id: record.task_id,
                code: "legacy_unavailable",
                message: "來源未保存",
            },
        ],
    });
    assert.equal(cards.length, 1);
    assert.equal(cards[0]?.id, record.task_id);
    assert.equal(cards[0]?.reportHref, null);
    assert.equal(readingState(cards[0]!), "history");
    assert.equal(filterStudies(cards, "all", "five-slot").length, 1);
});
test("an independently registered edition does not require repairing legacy card hashes", () => {
    const cards = cardsFromStudies({
        cards: [],
        warnings: [
            {
                task_id: record.task_id,
                code: "invalid_card",
                message: "old source unavailable",
            },
        ],
        readings: [record],
    });
    assert.equal(cards.length, 1);
    assert.equal(cards[0]?.reading?.state, "ready");
    assert.match(cards[0]?.reportHref ?? "", /view=reading/);
});
test("history gets an original link only when the service validates its readable path", () => {
    const [card] = cardsFromStudies({
        cards: [],
        warnings: [
            {
                task_id: record.task_id,
                code: "legacy_unavailable",
                message: "舊來源待核對",
            },
        ],
        original_reports: [record.task_id],
    });
    assert.equal(card?.reading?.state, "history");
    assert.match(card?.reportHref ?? "", /view=reading/);
    assert.equal(card?.verdict, null);
    assert.deepEqual(card?.keyNumbers, []);
});
test("return navigation preserves study filters but rejects external destinations", () => {
    const back = "#studies?collection=history&q=五檔";
    assert.equal(studiesBack(readingLink(record.task_id, back)), back);
    assert.equal(
        studiesBack("#report/x?back=https%3A%2F%2Fevil.invalid"),
        "#studies",
    );
});
