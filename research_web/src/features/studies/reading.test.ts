import assert from "node:assert/strict";
import test from "node:test";
import {
    currentStudyHash,
    reportView,
    pendingCard,
    readingState,
    studyCollection,
    withReportEntry,
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

test("a pending private API never blocks a registered native report or guesses an unknown edition", () => {
    assert.equal(reportView(null, undefined, true, true), "html");
    assert.equal(reportView(null, undefined, false, true), "loading");
    assert.equal(reportView("reading", "html", true, true), "reading");
    assert.equal(reportView(null, "markdown", false, false), "reading");
});

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
                "查看報告",
            ],
            [withReading(original, record), "查看報告"],
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
    assert.equal(readingState(old), "in_progress");
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
    assert.equal(cards[0]?.question, "原始報告待補");
    assert.equal(cards[0]?.reportKind, "summary");
    assert.match(cards[0]?.reportHref ?? "", /view=summary/);
    assert.equal(readingState(cards[0]!), "in_progress");
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
    assert.equal(card?.reading?.state, "in_progress");
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

test("collections preserve explicit archival without equating editorial history with archive", () => {
    const base = pendingCard(record.task_id, "Source unavailable");
    assert.equal(studyCollection(base), "in_progress");
    assert.equal(withReportEntry(base).reportKind, "summary");
    for (const verdict of ["running", "not_evaluated"] as const) {
        assert.equal(
            studyCollection({ ...base, sourceVerdict: verdict }),
            "in_progress",
        );
    }
    const archived = withReading({ ...base, verdict: "archived" }, record);
    assert.equal(archived.verdict, null);
    assert.equal(studyCollection(archived), "history");
    assert.equal(
        withReportEntry({ ...base, sourceVerdict: "archived" }).reportHref,
        null,
    );
});

test("a native HTML report remains the default when an editorial edition exists", () => {
    const original = {
        ...pendingCard(record.task_id, "Unreviewed"),
        reportKind: "html" as const,
        reportHref: "#report/existing",
    };
    const card = withReading(original, record);
    assert.equal(card.reportKind, "html");
    assert.equal(card.reportHref, "#report/existing");
    assert.equal(studyCollection(card), "ready");
    assert.equal(card.reading?.edition, "reading-report.md");
});
