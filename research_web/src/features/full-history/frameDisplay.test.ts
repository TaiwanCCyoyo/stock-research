import assert from "node:assert/strict";
import { test } from "node:test";
import { historyFrameDisplay } from "./frameDisplay.ts";

test("initial and failed reads have unknown counts, never a successful empty frame", () => {
    const input = {
        frame: null,
        desiredDate: "2026-01-02",
        loading: false,
        error: "",
    };
    for (const loading of [true, false]) {
        const state = historyFrameDisplay({ ...input, loading });
        assert.equal(state.status, "loading");
        assert.equal(state.rowCount, null);
        assert.equal(state.renderedDate, null);
        assert.equal(state.hasFrame, false);
    }
    const failed = historyFrameDisplay({ ...input, error: "HTTP 503" });
    assert.equal(failed.status, "failed");
    assert.equal(failed.hasFrame, false);
    assert.equal(failed.rowCount, null);
});

test("a successful zero-row frame is known empty and belongs to its saved date", () => {
    const state = historyFrameDisplay({
        frame: { date: "2026-01-02", rows: [] },
        desiredDate: "2026-01-02",
        loading: false,
        error: "",
    });
    assert.equal(state.status, "ready");
    assert.equal(state.hasFrame, true);
    assert.equal(state.rowCount, 0);
    assert.equal(state.renderedDate, "2026-01-02");
});

test("date changes retain the previous frame before and during the request", () => {
    const frame = { date: "2026-01-02", rows: [{}, {}] };
    for (const loading of [true, false]) {
        const state = historyFrameDisplay({
            frame,
            desiredDate: "2026-01-05",
            loading,
            error: "",
        });
        assert.equal(state.status, "updating");
        assert.equal(state.renderedDate, frame.date);
        assert.equal(state.requestedDate, "2026-01-05");
        assert.equal(state.rowCount, 2);
    }
    assert.equal(frame.rows.length, 2);
});

test("failed updates retain saved zero or nonzero counts without claiming the requested date succeeded", () => {
    for (const rows of [[], [{}]]) {
        const state = historyFrameDisplay({
            frame: { date: "2026-01-02", rows },
            desiredDate: "2026-01-05",
            loading: false,
            error: "network",
        });
        assert.equal(state.status, "failed");
        assert.equal(state.hasFrame, true);
        assert.equal(state.renderedDate, "2026-01-02");
        assert.equal(state.rowCount, rows.length);
    }
});

test("a retry starts loading even when the hook still holds the previous error", () => {
    const input = {
        frame: null,
        desiredDate: "2026-01-02",
        loading: true,
        error: "previous failure",
    };
    assert.equal(historyFrameDisplay(input).status, "loading");
    assert.equal(
        historyFrameDisplay({
            ...input,
            frame: { date: "2026-01-02", rows: [{}] },
        }).status,
        "updating",
    );
});
