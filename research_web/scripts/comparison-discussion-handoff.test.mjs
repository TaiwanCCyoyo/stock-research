import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { before, test } from "node:test";
import { comparisonDiscussionFeedback } from "../src/features/condition-comparison/discussionHandoff.ts";

const taskId = "20261103-demo";
const revision = "a".repeat(40);
const draftPath = `tasks/${taskId}/direction-draft.md`;
let demoModel;

before(async () => {
    const html = await readFile(
        new URL("../discussion-kit/v1/index.html", import.meta.url),
        "utf8",
    );
    const json = html.match(
        /<script id="discussion-data" type="application\/json">([\s\S]*?)<\/script>/,
    )?.[1];
    assert.ok(json, "discussion demo model exists");
    demoModel = JSON.parse(json);
});

function setup(overrides = {}) {
    const model = structuredClone(demoModel);
    model.demo = false;
    model.source = { taskId, draftPath, revision };
    const detail = {
        schema: "direction-draft.v1",
        mode: "local-private",
        taskId,
        status: "ready",
        revision,
        message: null,
        title: "Synthetic test",
        draftMarkdown: "Synthetic-only discussion fixture.",
        model,
        ...overrides.detail,
    };
    const selected = {
        taskId,
        status: "ready",
        revision,
        ...overrides.selected,
    };
    const request = {
        intent: "discussion-only",
        question: "Synthetic comparison question?",
        source: {
            studyId: "synthetic-study",
            resultId: "synthetic-result",
            settingsVersion: "synthetic-v1",
            outcomeDefinition: "synthetic definition",
            inputVersion: "no-market-data",
            priceBasis: "synthetic",
            population: "synthetic only",
            source: "synthetic fixture",
        },
        synthetic: true,
        selection: {
            resultId: "synthetic-result",
            horizon: 126,
            group: "all",
            filter: "all",
            page: 0,
            sort: "date-desc",
        },
    };
    return { request, selected, detail, model };
}

test("handoff pins exact task, draft path and 40-character revision", () => {
    const x = setup();
    const before = structuredClone(x);
    const feedback = comparisonDiscussionFeedback(
        x.request,
        x.selected,
        x.detail,
    );
    assert.deepEqual(feedback.source, { taskId, draftPath, revision });
    assert.deepEqual(x, before);
});

test("same revision produces proposed feedback with preserved synthetic provenance and all-null selections", () => {
    const x = setup();
    const feedback = comparisonDiscussionFeedback(
        x.request,
        x.selected,
        x.detail,
    );
    assert.equal(feedback.schema, "direction-feedback.v1");
    assert.equal(feedback.status, "proposed");
    assert.ok(feedback.selections.length > 0);
    assert.ok(feedback.selections.every((item) => item.optionId === null));
    assert.match(feedback.notes, /synthetic/i);
    assert.match(feedback.notes, /synthetic-result/);
    assert.match(feedback.notes, /Synthetic comparison question\?/);
});

test("revision race, unavailable status and incorrect task are rejected", () => {
    for (const overrides of [
        { selected: { revision: "b".repeat(40) } },
        { selected: { status: "unavailable" } },
        { detail: { status: "unavailable" } },
        { selected: { taskId: "20261104-other" } },
    ]) {
        const x = setup(overrides);
        assert.throws(() =>
            comparisonDiscussionFeedback(x.request, x.selected, x.detail),
        );
    }
});

test("different result identity is rejected", () => {
    const x = setup();
    x.request.source.resultId = "other-result";
    assert.throws(() =>
        comparisonDiscussionFeedback(x.request, x.selected, x.detail),
    );
});

test("draft-path mismatch, incomplete SHA and malformed question cannot hand off", () => {
    for (const field of ["taskId", "draftPath", "revision"]) {
        const x = setup();
        x.detail.model.source[field] += "-other";
        assert.throws(() =>
            comparisonDiscussionFeedback(x.request, x.selected, x.detail),
        );
    }
    const short = setup({ selected: { revision: "aaaa" } });
    assert.throws(() =>
        comparisonDiscussionFeedback(
            short.request,
            short.selected,
            short.detail,
        ),
    );
    const blank = setup();
    blank.request.question = " ";
    assert.throws(() =>
        comparisonDiscussionFeedback(
            blank.request,
            blank.selected,
            blank.detail,
        ),
    );
});
