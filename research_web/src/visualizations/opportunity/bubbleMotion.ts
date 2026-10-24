/** Motion curves for the opportunity map's soap bubbles. Pure functions of
 *  progress `t` in [0, 1] so they stay cheap inside the morph loop and easy to
 *  test. With reduced motion a bubble never overshoots or swells: it only
 *  fades or grows straight, and the map itself skips the glide entirely. */

/** A joining bubble may rise at most this far past its final radius. */
export const JOIN_OVERSHOOT = 0.08;
/** Back-ease strength tuned so the peak stays just under JOIN_OVERSHOOT. */
const JOIN_STRENGTH = 1.4;
/** A bursting bubble swells by this share of its radius while it fades. */
export const BURST_GROWTH = 0.2;
/** The burst has faded out by this share of the glide. */
export const BURST_FADE_BY = 0.4;
/** Popping everything for a fast scrub is a little slower and staggered. */
export const POP_DURATION = 260;
export const POP_FADE_BY = 0.7;
export const POP_STAGGER = 0.3;
/** Regathering after a scrub: bubbles grow back one after another. */
export const REGATHER_DURATION = 720;
export const REGATHER_STAGGER = 0.4;
/** Largest wobble of a group that gained or lost members, as radius share. */
export const GROUP_WOBBLE = 0.02;

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

/** `a` to `b`, landing exactly on `b` at t = 1 (no floating-point residue). */
export const mixTo = (a: number, b: number, t: number) =>
    t >= 1 ? b : a + (b - a) * t;

/** Radius share of a joining bubble: 0 to 1 with a small spring overshoot. */
export function joinScale(t: number, reduced = false): number {
    if (t >= 1) return 1;
    const p = clamp01(t);
    if (reduced) return p;
    const u = p - 1;
    return 1 + (JOIN_STRENGTH + 1) * u * u * u + JOIN_STRENGTH * u * u;
}

export interface BurstPose {
    /** Multiplier on the bubble's radius. */
    scale: number;
    opacity: number;
}

/** A bubble that bursts: swells and fades out within the first `fadeBy` of
 *  the glide, then stays gone. */
export function burstPose(
    t: number,
    reduced = false,
    fadeBy = BURST_FADE_BY,
): BurstPose {
    const u = clamp01(t / fadeBy);
    return {
        scale: reduced ? 1 : 1 + BURST_GROWTH * (1 - (1 - u) ** 2),
        opacity: u >= 1 ? 0 : 1 - u * u,
    };
}

/** Radius multiplier for a group whose membership changed: a damped wobble
 *  that is exactly 1 at both ends. */
export function groupWobble(t: number, reduced = false): number {
    if (reduced || t <= 0 || t >= 1) return 1;
    return 1 + GROUP_WOBBLE * Math.sin(t * Math.PI * 4) * (1 - t);
}

/** Progress of an item that starts `delay` into the glide, in [0, 1]. */
export function delayed(t: number, delay: number): number {
    return t >= 1 ? 1 : clamp01((t - delay) / (1 - delay));
}
