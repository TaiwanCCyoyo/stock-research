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

test("playback can prefetch deeper without passing the last date", () => {
    const dates = ["a", "b", "c", "d", "e", "f", "g"];
    assert.deepEqual(playbackLookahead(dates, 0, 1, 4), ["b", "c", "d", "e"]);
    assert.deepEqual(playbackLookahead(dates, 4, 1, 4), ["f", "g"]);
});

const versionA = { versionId: "synthetic-a", manifestSha256: "a".repeat(64) };
const versionB = { versionId: "synthetic-b", manifestSha256: "b".repeat(64) };
function versionedFrame(pin: typeof versionA, price: number): HistoryFrame {
    return {
        ...frame("2020-01-02", pin.manifestSha256),
        bundleIdentity: pin,
        rows: [
            {
                securityId: "SYNTH-ONE",
                code: "SYNTH-ONE",
                name: "Synthetic only",
                seriesId: "series",
                waveId: "wave",
                start: "2020-01-01",
                peakDate: "2020-01-02",
                endConfirmedAt: null,
                observedThrough: "2020-01-02",
                leftCensored: false,
                rightCensored: true,
                scale: "balanced",
                gain: 1,
                peakGain: 1,
                raw: price,
                adjusted: price,
                reason: null,
                industry: {
                    id: "synthetic",
                    label: "Synthetic",
                    basis: "unknown",
                    snapshotAt: null,
                },
                earliestCandidateId: null,
                phase: null,
            },
        ],
    };
}
const versionIdentity = (pin: typeof versionA) => ({
    catalogId: pin.manifestSha256,
    date: "2020-01-02",
    bundleIdentity: pin,
});

test("two saved versions keep the same stock's distinct prices isolated", async () => {
    const calls: string[] = [];
    const buffer = new FrameBuffer(async (_date, _signal, pin) => {
        assert.ok(pin);
        calls.push(pin.versionId);
        return versionedFrame(
            pin,
            pin.manifestSha256 === versionA.manifestSha256 ? 10 : 20,
        );
    });
    const a = await buffer.read(versionIdentity(versionA));
    const b = await buffer.read(versionIdentity(versionB));
    assert.equal(a.rows[0].code, b.rows[0].code);
    assert.equal(a.rows[0].adjusted, 10);
    assert.equal(b.rows[0].adjusted, 20);
    assert.equal(
        (await buffer.read(versionIdentity(versionA))).rows[0].adjusted,
        10,
    );
    assert.deepEqual(calls, ["synthetic-a", "synthetic-b"]);
    const alias = { ...versionA, versionId: "registered-alias" };
    await buffer.read(versionIdentity(alias));
    assert.equal(
        calls.length,
        3,
        "same manifest still requires its requested registered version",
    );
});

test("explicit versions reject missing or mismatched identities rather than caching current data", async () => {
    const wrong = new FrameBuffer(async () => versionedFrame(versionA, 10));
    await assert.rejects(wrong.read(versionIdentity(versionB)));
    assert.equal(wrong.peek(versionIdentity(versionB)), undefined);
    const missing = new FrameBuffer(async () =>
        frame("2020-01-02", versionB.manifestSha256),
    );
    await assert.rejects(missing.read(versionIdentity(versionB)));
    const otherVersion = { ...versionA, versionId: "other-registration" };
    await assert.rejects(wrong.read(versionIdentity(otherVersion)));
});

test("switching versions cancels old work and late responses cannot seed either cache", async () => {
    const pending = new Map<
        string,
        { signal: AbortSignal; resolve: (frame: HistoryFrame) => void }
    >();
    const buffer = new FrameBuffer(
        (_date, signal, pin) =>
            new Promise((resolve) =>
                pending.set(pin!.versionId, { signal, resolve }),
            ),
    );
    const old = buffer.read(versionIdentity(versionA));
    const fresh = buffer.read(versionIdentity(versionB));
    buffer.retain([versionIdentity(versionB)]);
    assert.equal(pending.get(versionA.versionId)!.signal.aborted, true);
    pending.get(versionB.versionId)!.resolve(versionedFrame(versionB, 20));
    await fresh;
    pending.get(versionA.versionId)!.resolve(versionedFrame(versionA, 10));
    await assert.rejects(old, { name: "AbortError" });
    assert.equal(buffer.peek(versionIdentity(versionA)), undefined);
    assert.equal(buffer.peek(versionIdentity(versionB))!.rows[0].adjusted, 20);
});
