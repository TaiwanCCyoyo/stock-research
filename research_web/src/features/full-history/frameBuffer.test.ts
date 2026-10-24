import { test } from "node:test";
import assert from "node:assert/strict";
import { FrameBuffer, playbackLookahead } from "./frameBuffer.ts";
import { HISTORY_SCHEMA, type HistoryFrame } from "./types.ts";

const identity = (date: string, catalogId = "catalog") => ({ catalogId, date });
const frame = (date: string, catalogId = "catalog"): HistoryFrame => ({
    schema: HISTORY_SCHEMA,
    catalogId,
    date,
    rows: [],
});

test("lookahead is bounded, honors speed and includes the exact final day once", () => {
    const dates = ["a", "b", "c", "d", "e", "f"];
    assert.deepEqual(playbackLookahead(dates, 0, 2), ["c", "e"]);
    assert.deepEqual(playbackLookahead(dates, 3, 2), ["f"]);
    assert.deepEqual(playbackLookahead(dates, 5, 2), []);
});

test("foreground consumes the in-flight lookahead without a second request", async () => {
    let resolve!: (value: HistoryFrame) => void;
    let reads = 0;
    const buffer = new FrameBuffer(() => {
        reads++;
        return new Promise((done) => {
            resolve = done;
        });
    });
    const future = buffer.read(identity("a"));
    const foreground = buffer.read(identity("a"));
    assert.equal(future, foreground);
    resolve(frame("a"));
    await foreground;
    assert.equal(reads, 1);
    assert.deepEqual(await buffer.read(identity("a")), frame("a"));
    assert.equal(reads, 1);
});

test("cache uses catalog and date identity and rejects mismatched responses", async () => {
    const buffer = new FrameBuffer(async (date) => frame(date));
    await buffer.read(identity("a"));
    assert.equal(buffer.peek(identity("a", "other")), undefined);
    await assert.rejects(buffer.read(identity("a", "other")), /日期或版本/);
    const wrongDate = new FrameBuffer(async () => frame("wrong"));
    await assert.rejects(wrongDate.read(identity("a")), /日期或版本/);
});

test("LRU keeps a recently read frame and evicts the least recently used", async () => {
    const buffer = new FrameBuffer(async (date) => frame(date), 2);
    await buffer.read(identity("a"));
    await buffer.read(identity("b"));
    buffer.peek(identity("a"));
    await buffer.read(identity("c"));
    assert.equal(buffer.peek(identity("b")), undefined);
    assert.ok(buffer.peek(identity("a")));
});

test("seek cancels obsolete work, keeps adopted lookahead, rejects late aborted results", async () => {
    const pending = new Map<
        string,
        { signal: AbortSignal; resolve: (value: HistoryFrame) => void }
    >();
    const buffer = new FrameBuffer(
        (date, signal) =>
            new Promise((resolve) => {
                pending.set(date, { signal, resolve });
            }),
    );
    const old = buffer.read(identity("a"));
    const adopted = buffer.read(identity("b"));
    buffer.retain([identity("b")]);
    assert.equal(pending.get("a")!.signal.aborted, true);
    assert.equal(pending.get("b")!.signal.aborted, false);
    pending.get("a")!.resolve(frame("a"));
    pending.get("b")!.resolve(frame("b"));
    await assert.rejects(old, { name: "AbortError" });
    await adopted;
    assert.equal(buffer.peek(identity("a")), undefined);
    assert.ok(buffer.peek(identity("b")));
});

test("failed prefetch is retryable rather than retained as a rejected promise", async () => {
    let reads = 0;
    const buffer = new FrameBuffer(async (date) => {
        if (++reads === 1) throw new Error("offline");
        return frame(date);
    });
    await assert.rejects(buffer.read(identity("a")), /offline/);
    await buffer.read(identity("a"));
    assert.equal(reads, 2);
});

test("returning to a canceled date cannot let its old response replace the new request", async () => {
    const resolvers: ((value: HistoryFrame) => void)[] = [];
    const buffer = new FrameBuffer(
        () => new Promise((resolve) => resolvers.push(resolve)),
    );
    const old = buffer.read(identity("a"));
    buffer.retain([]);
    const current = buffer.read(identity("a"));
    resolvers[0](frame("a"));
    await assert.rejects(old, { name: "AbortError" });
    assert.equal(buffer.read(identity("a")), current);
    resolvers[1](frame("a"));
    await current;
    assert.ok(buffer.peek(identity("a")));
});

test("the default buffer keeps at most24 visited dates", async () => {
    const buffer = new FrameBuffer(async (date) => frame(date));
    for (let index = 0; index < 40; index++)
        await buffer.read(identity(String(index)));
    const retained = Array.from({ length: 40 }, (_, index) =>
        buffer.peek(identity(String(index))),
    ).filter(Boolean);
    assert.equal(retained.length, 24);
});
