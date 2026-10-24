import assert from "node:assert/strict";
import test from "node:test";
import {
    cardFromV2,
    hiddenCount,
    readStudies,
    runProgress,
    taskDate,
    type StudyCardV2,
} from "./v2.ts";

const card = (over: Partial<StudyCardV2> = {}): StudyCardV2 => ({
    schema: "study-card.v2",
    task_id: "20261021-momentum-only-doubling",
    kind: "study",
    question: "只看強勢條件，翻倍與下跌風險有多高？",
    answer: "強勢條件翻倍比例較高，但沒翻倍又收低的也更多。",
    verdict: "mixed",
    data_period: { from: "2010-01-04", to: "2026-10-12" },
    key_numbers: [
        {
            label: "半年翻倍率",
            value: 14.5,
            unit: "percent",
            highlight: true,
            source_excerpt: "半年翻倍 14.5%",
        },
    ],
    limitation: "事後描述，不是可交易報酬。",
    report: { web_report: "web-report/index.html", markdown: "report.md" },
    account_run: null,
    delivery_state: "delivered",
    scratch_run: null,
    provenance: {
        answer_source: "原文摘要",
        shared_data: ["adjusted-daily-v1"],
    },
    ...over,
});

test("a v2 card keeps its plain question, verdict, numbers and limitation", () => {
    const view = cardFromV2(card());
    assert.equal(view.date, "2026-10-21");
    assert.equal(view.verdict, "mixed");
    assert.equal(view.reportHref, "#report/20261021-momentum-only-doubling");
    assert.equal(view.keyNumbers[0]!.value, 14.5);
    assert.equal(view.limitation, "事後描述，不是可交易報酬。");
    assert.deepEqual(view.details.numberSources, [
        { label: "半年翻倍率", excerpt: "半年翻倍 14.5%" },
    ]);
    assert.deepEqual(view.caveats, []);
    assert.equal(view.progress, null);
});

test("a markdown-only report gets no web link and old account runs keep their note", () => {
    const view = cardFromV2(
        card({
            report: { web_report: null, markdown: "report.md" },
            account_run: {
                run_id: "stock:20261002-add-retry:normal-v1",
                period_note: "帳戶模擬 2019–2023（舊資料）",
            },
            verdict: "archived",
        }),
    );
    assert.equal(view.reportHref, null);
    assert.deepEqual(view.accountRun, {
        runId: "stock:20261002-add-retry:normal-v1",
        note: "帳戶模擬 2019–2023（舊資料）",
    });
});

test("only this card's source and run warnings become visible caveats", () => {
    const view = cardFromV2(card(), [
        {
            task_id: "20261021-momentum-only-doubling",
            code: "report_sha256_mismatch",
            message: "x",
        },
        {
            task_id: "20261021-momentum-only-doubling",
            code: "unknown",
            message: "x",
        },
        { task_id: "other", code: "source_unavailable", message: "x" },
    ]);
    assert.deepEqual(view.caveats, ["報告內容與登錄時不同，內容待核對"]);
});

test("run progress reads numeric steps and tolerates other shapes", () => {
    assert.deepEqual(
        runProgress({ progress: { step: 2, total: 5, label: "Q3" } }),
        { step: 2, total: 5, label: "Q3" },
    );
    assert.deepEqual(runProgress({ progress: { label: "整理中" } }), {
        step: null,
        total: null,
        label: "整理中",
    });
    assert.equal(runProgress({ progress: { done: true } }), null);
    assert.equal(runProgress({}), null);
    assert.equal(taskDate("bad"), "");
});

test("hidden tasks are counted once and shown cards are not", () => {
    assert.equal(
        hiddenCount({
            cards: [card()],
            warnings: [
                { task_id: "a", code: "legacy_unavailable", message: "" },
                { task_id: "a", code: "invalid_card", message: "" },
                {
                    task_id: "20261021-momentum-only-doubling",
                    code: "report_sha256_mismatch",
                    message: "",
                },
                { task_id: "", code: "tasks_unavailable", message: "" },
            ],
        }),
        1,
    );
});

test("studies are read with the data-mode header and other shapes are rejected", async () => {
    let seen: RequestInit | undefined;
    let url = "";
    const fetcher = (async (input: string, init?: RequestInit) => {
        url = input;
        seen = init;
        return new Response(
            JSON.stringify({ cards: [card(), { schema: "x" }], warnings: [] }),
            { headers: { "content-type": "application/json" } },
        );
    }) as unknown as typeof fetch;
    const result = await readStudies(new AbortController().signal, fetcher);
    assert.equal(url, "/history-api/studies");
    assert.ok(
        new Headers(seen?.headers).has("X-Research-Data-Mode"),
        "mode header sent",
    );
    assert.equal(result.cards.length, 1);
    const bad = (async () =>
        new Response(JSON.stringify({ cards: [] }))) as unknown as typeof fetch;
    await assert.rejects(readStudies(new AbortController().signal, bad));
});
