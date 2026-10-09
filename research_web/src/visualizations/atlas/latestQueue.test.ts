import assert from "node:assert/strict";
import test from "node:test";
import { LatestQueue } from "./latestQueue.ts";

test("keeps one active request and replaces queued work with the latest value", () => {
    const queue = new LatestQueue<number>();

    assert.equal(queue.offer(1), 1);
    assert.equal(queue.offer(2), null);
    assert.equal(queue.offer(3), null);
    assert.equal(queue.complete(), 3);
    assert.equal(queue.complete(), null);
    assert.equal(queue.offer(4), 4);
});

test("reset discards active and pending work", () => {
    const queue = new LatestQueue<number>();

    queue.offer(1);
    queue.offer(2);
    queue.reset();
    assert.equal(queue.complete(), null);
    assert.equal(queue.offer(3), 3);
    queue.reset();
    assert.equal(queue.offer(4), 4);
});
