import assert from "node:assert/strict";
import test from "node:test";
import {
    STALE_PROGRESS,
    markStale,
    studiesFailed,
    studiesLoaded,
} from "./studiesState.ts";
import { cardFromV2, type StudiesResponse } from "./v2.ts";

const response = (step: number): StudiesResponse => ({
    cards: [
        {
            schema: "study-card.v2",
            task_id: "20261013-pattern-scan",
            kind: "study",
            question: "型態掃描完成了嗎？",
            answer: "還在進行。",
            verdict: "running",
            data_period: null,
            key_numbers: [],
            limitation: "尚未完成。",
            report: { web_report: null, markdown: null },
            account_run: null,
            delivery_state: null,
            scratch_run: { run: "q2-q6" },
            provenance: { answer_source: null, shared_data: [] },
            progress: { step, total: 10, label: "Q3" },
            run_state: "running",
        },
    ],
    warnings: [],
});

test("a failed refresh keeps the cards but marks them stale; a retry clears it", () => {
    const first = studiesLoaded(response(3));
    const failed = studiesFailed(first, "HTTP 503");
    assert.equal(failed.stale, true);
    assert.equal(failed.data, first.data);
    assert.equal(failed.error, "HTTP 503");
    // A second failure stays stale with the same cards.
    assert.equal(studiesFailed(failed, "HTTP 503").stale, true);
    const recovered = studiesLoaded(response(4));
    assert.deepEqual([recovered.stale, recovered.error], [false, ""]);
});

test("a first failure with nothing cached is an error, not stale data", () => {
    const failed = studiesFailed(
        { data: null, error: "", stale: false },
        "HTTP 503",
    );
    assert.deepEqual([failed.data, failed.stale], [null, false]);
});

test("stale cards warn where they show live progress, once", () => {
    const card = cardFromV2(response(3).cards[0]!);
    const marked = markStale(markStale([card]));
    assert.deepEqual(
        marked[0]!.caveats.filter((text) => text === STALE_PROGRESS),
        [STALE_PROGRESS],
    );
    const still = cardFromV2({ ...response(3).cards[0]!, progress: null });
    assert.deepEqual(markStale([still])[0]!.caveats, []);
});
