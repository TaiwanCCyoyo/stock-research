import test from "node:test";
import assert from "node:assert/strict";
import {
    adaptSavedComparison,
    casePage,
    currentSelection,
    initialSelection,
} from "./model.ts";
import { syntheticComparison as view } from "./fixture.ts";

test("preserves saved counts and overlapping unknown/censored without recomputing", () => {
    const state = adaptSavedComparison(view, (value) => value);
    assert.equal(state.status, "ready");
    if (state.status === "ready") assert.equal(state.value, view);
    assert.deepEqual(view.windows[252]?.all, {
        status: "evaluated",
        counts: { hit: 1, known: 1, stocks: 6, unknown: 5, censored: 5 },
    });
});
test("stable paging, filters and repeated returns preserve the selected case", () => {
    const selected = { ...initialSelection(view), page: 1, eventId: "demo-01" };
    assert.equal(
        casePage(view.windows[126], selected).rows[0].eventId,
        "demo-01",
    );
    assert.deepEqual(currentSelection(view, selected), selected);
    assert.deepEqual(
        currentSelection(view, currentSelection(view, selected)),
        selected,
    );
    const failed = casePage(view.windows[126], {
        ...selected,
        filter: "not-hit",
        page: 0,
    });
    assert.deepEqual(
        failed.rows.map((row) => row.effectiveLabel),
        ["loss", "flat-win", "loss"],
    );
    assert.equal(
        casePage(view.windows[126], { ...selected, filter: "unknown" }).total,
        2,
    );
});
test("rapid horizon selection uses only the selected window; stale result identity resets", () => {
    for (const horizon of [252, 126, 252, 126] as const) {
        const selection = {
            ...initialSelection(view),
            horizon,
            filter: "unknown" as const,
        };
        assert.equal(
            casePage(view.windows[horizon], selection).total,
            horizon === 126 ? 2 : 5,
        );
    }
    assert.equal(
        currentSelection(view, {
            ...initialSelection(view),
            resultId: "old",
            page: 5,
        }).page,
        0,
    );
    assert.equal(casePage(undefined, initialSelection(view)).total, 0);
});
test("adapter errors fail closed and missing count fields remain missing", () => {
    assert.equal(
        adaptSavedComparison(null, () => {
            throw new Error("read failed");
        }).status,
        "error",
    );
    const missing = structuredClone(view);
    missing.windows[126]!.all = { status: "evaluated", counts: {} };
    assert.equal(
        adaptSavedComparison(missing, (value) => value).status,
        "ready",
    );
    missing.windows[126]!.all = {
        status: "evaluated",
        counts: { hit: 2, known: 1 },
    };
    assert.equal(
        adaptSavedComparison(missing, (value) => value).status,
        "error",
    );
});
