import assert from "node:assert/strict";
import test from "node:test";
import {
    BURST_FADE_BY,
    BURST_GROWTH,
    JOIN_OVERSHOOT,
    POP_FADE_BY,
    burstPose,
    delayed,
    groupWobble,
    joinScale,
    mixTo,
} from "./bubbleMotion.ts";

const samples = Array.from({ length: 1001 }, (_, i) => i / 1000);

test("a joining bubble overshoots by at most 8% and lands exactly on 1", () => {
    const peak = Math.max(...samples.map((t) => joinScale(t)));
    assert.ok(peak > 1.02, `peak ${peak} should be visible`);
    assert.ok(peak <= 1 + JOIN_OVERSHOOT, `peak ${peak} exceeds the bound`);
    assert.equal(joinScale(0), 0);
    assert.equal(joinScale(1), 1);
    assert.equal(joinScale(1.2), 1);
});

test("a joining bubble starts small and never shrinks below 0", () => {
    for (const t of samples) assert.ok(joinScale(t) >= 0);
    assert.ok(joinScale(0.2) > 0 && joinScale(0.2) < 1);
});

test("a burst fades to 0 by 40% of the glide and stays gone", () => {
    assert.equal(burstPose(0).opacity, 1);
    assert.equal(burstPose(BURST_FADE_BY).opacity, 0);
    for (const t of samples.filter((t) => t >= BURST_FADE_BY))
        assert.equal(burstPose(t).opacity, 0);
    for (const t of samples.filter((t) => t < BURST_FADE_BY))
        assert.ok(burstPose(t).opacity > 0);
});

test("a burst swells 15-25% while it fades", () => {
    const final = burstPose(BURST_FADE_BY).scale - 1;
    assert.ok(final >= 0.15 && final <= 0.25, `grows ${final}`);
    assert.ok(Math.abs(BURST_GROWTH - final) < 1e-9);
    for (const t of samples)
        assert.ok(burstPose(t).scale <= 1 + BURST_GROWTH + 1e-12);
});

test("a wider fade window (the scrub pop) still ends at 0 opacity", () => {
    assert.equal(burstPose(POP_FADE_BY, false, POP_FADE_BY).opacity, 0);
    assert.ok(burstPose(0.3, false, POP_FADE_BY).opacity > 0);
});

test("with reduced motion nothing overshoots or swells", () => {
    for (const t of samples) {
        assert.ok(joinScale(t, true) <= 1);
        assert.equal(joinScale(t, true), t);
        assert.equal(burstPose(t, true).scale, 1);
        assert.equal(groupWobble(t, true), 1);
    }
    assert.equal(burstPose(BURST_FADE_BY, true).opacity, 0);
});

test("a wobble is small and exactly neutral at both ends", () => {
    assert.equal(groupWobble(0), 1);
    assert.equal(groupWobble(1), 1);
    for (const t of samples)
        assert.ok(Math.abs(groupWobble(t) - 1) <= 0.02 + 1e-12);
});

test("mixTo lands exactly on the target and delayed spreads starts", () => {
    assert.equal(mixTo(0.1, 0.3, 1), 0.3);
    assert.equal(mixTo(2, 4, 0.5), 3);
    assert.equal(delayed(0.2, 0.4), 0);
    assert.equal(delayed(1, 0.4), 1);
    assert.ok(Math.abs(delayed(0.7, 0.4) - 0.5) < 1e-9);
    assert.equal(delayed(0.5, 0), 0.5);
});
