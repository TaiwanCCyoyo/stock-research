import assert from "node:assert/strict";
import { test } from "node:test";
import {
    MAX_BURSTS,
    PLAIN_EFFECT,
    THEME_EFFECTS,
    particleCount,
    particlePose,
    pickLargest,
    themeEffect,
    type EffectShape,
} from "./themeEffects.ts";
import { THEMES } from "../../app/themes.ts";

test("every theme has effects and the switch falls back to the plain burst", () => {
    for (const theme of THEMES) assert.ok(THEME_EFFECTS[theme.id], theme.id);
    assert.deepEqual(themeEffect("sakura", false), PLAIN_EFFECT);
    assert.equal(themeEffect("sakura", true).join, "heart");
    assert.equal(themeEffect("unknown", true), THEME_EFFECTS.forest);
});

test("particles are invisible at the start and end of a glide and stay finite", () => {
    const shapes = new Set<EffectShape>(
        Object.values(THEME_EFFECTS).flatMap((fx) =>
            [fx.burst, fx.join].filter((s): s is EffectShape => !!s),
        ),
    );
    for (const shape of shapes)
        for (const kind of ["burst", "join"] as const)
            for (let i = 0; i < particleCount(shape); i++) {
                const origin = { x: 100, y: 50, r: 12 };
                for (const t of [0, 0.25, 0.5, 0.75, 1]) {
                    const p = particlePose(shape, kind, origin, i, 1, t);
                    for (const value of Object.values(p))
                        assert.ok(Number.isFinite(value), `${shape} ${t}`);
                }
                assert.ok(
                    particlePose(shape, kind, origin, i, 1, 0).opacity < 0.51,
                );
                assert.ok(
                    particlePose(shape, kind, origin, i, 1, 1).opacity < 0.01,
                );
            }
});

test("only the largest bubbles get effects on a busy step", () => {
    const sizes = Array.from({ length: 20 }, (_, i) => i);
    assert.deepEqual(
        pickLargest(sizes, (n) => n, MAX_BURSTS),
        [19, 18, 17, 16, 15, 14, 13, 12],
    );
});
