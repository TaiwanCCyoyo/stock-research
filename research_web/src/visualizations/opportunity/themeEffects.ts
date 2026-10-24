/** Decorative particles for the opportunity map, per colour theme.
 *  They mark two moments the map already knows about: a bubble joining a
 *  group (a stock starts its rally) and a bubble bursting (its rally is
 *  confirmed over). They never change a bubble's size or position. */

export type EffectShape =
    | "petal"
    | "heart"
    | "ring"
    | "star"
    | "glitter"
    | "bubble"
    | "ember"
    | "firefly"
    | "dot";

export interface ThemeEffect {
    burst: EffectShape | null;
    join: EffectShape | null;
}

export const THEME_EFFECTS: Record<string, ThemeEffect> = {
    sakura: { burst: "petal", join: "heart" },
    ocean: { burst: "ring", join: "ring" },
    forest: { burst: "firefly", join: "firefly" },
    plum: { burst: "star", join: "star" },
    sand: { burst: "glitter", join: "glitter" },
    soda: { burst: "bubble", join: "bubble" },
    sunset: { burst: "ember", join: "ember" },
    ink: { burst: "dot", join: null },
};

/** Without the decorative switch only the original plain burst remains. */
export const PLAIN_EFFECT: ThemeEffect = { burst: "dot", join: null };

/** At most this many bubbles get an effect per step, largest first, so a busy
 *  day cannot flood the map with particles. */
export const MAX_BURSTS = 8;
export const MAX_JOINS = 6;

export function themeEffect(palette: string | undefined, decorative: boolean) {
    if (!decorative) return PLAIN_EFFECT;
    return THEME_EFFECTS[palette ?? ""] ?? THEME_EFFECTS.forest!;
}

export function particleCount(shape: EffectShape): number {
    return shape === "ring" ? 2 : shape === "heart" ? 2 : 5;
}

/** Path data drawn around the origin; circles are drawn by the caller. */
export const SHAPE_PATH: Partial<Record<EffectShape, string>> = {
    petal: "M0 -4 C3 -3 3 2 0 4 C-3 2 -3 -3 0 -4 Z",
    heart: "M0 2.6 C-4.4 -0.4 -2.6 -4 0 -1.8 C2.6 -4 4.4 -0.4 0 2.6 Z",
    star: "M0 -4 L1 -1 L4 0 L1 1 L0 4 L-1 1 L-4 0 L-1 -1 Z",
    glitter: "M0 -2.4 L1.6 0 L0 2.4 L-1.6 0 Z",
};

export interface ParticlePose {
    x: number;
    y: number;
    scale: number;
    rotate: number;
    opacity: number;
}

/** Where particle `index` of a bubble at (x, y, r) is at `t` in [0, 1]. */
export function particlePose(
    shape: EffectShape,
    kind: "burst" | "join",
    origin: { x: number; y: number; r: number },
    index: number,
    angle: number,
    t: number,
): ParticlePose {
    const count = particleCount(shape);
    const a = angle + (index * Math.PI * 2) / count;
    const fade = Math.sin(Math.PI * Math.min(1, t));
    const out = 1 - (1 - t) ** 2;
    const radius = Math.min(30, origin.r);
    switch (shape) {
        case "ring":
            return {
                x: origin.x,
                y: origin.y,
                scale: (radius + 4) / 4 + out * (2 + index * 1.5),
                rotate: 0,
                opacity: 0.5 * (1 - t),
            };
        case "heart":
            return {
                x: origin.x + (index ? 6 : -4) + Math.sin(t * 6 + index) * 2,
                y: origin.y - (kind === "join" ? origin.r * 0.4 : 0) - out * 22,
                scale: 1.2 + 0.4 * fade,
                rotate: (index ? 1 : -1) * 12,
                opacity: 0.85 * fade,
            };
        case "petal":
            return {
                x: origin.x + Math.cos(a) * (radius + 6) * out,
                y: origin.y + Math.sin(a) * (radius + 6) * out + t * t * 18,
                scale: 1.3,
                rotate: (a * 180) / Math.PI + t * 220,
                opacity: 0.8 * fade,
            };
        case "bubble":
        case "ember":
            return {
                x:
                    origin.x +
                    Math.cos(a) * (radius * 0.6) +
                    Math.sin(t * 7 + index) * 2,
                y:
                    origin.y +
                    Math.sin(a) * radius * 0.4 -
                    out * (18 + index * 3),
                scale:
                    shape === "ember"
                        ? 1.1 * (1 - t * 0.6)
                        : 0.9 + index * 0.12,
                rotate: 0,
                opacity: 0.75 * fade,
            };
        case "firefly":
            return {
                x: origin.x + Math.cos(a + t) * (radius + 10) * out,
                y: origin.y + Math.sin(a + t) * (radius + 10) * out,
                scale: 1,
                rotate: 0,
                opacity: (0.4 + 0.5 * Math.abs(Math.sin(t * 9 + index))) * fade,
            };
        case "glitter":
            return {
                x: origin.x + Math.cos(a) * (radius + 8) * out,
                y: origin.y + Math.sin(a) * (radius + 8) * out + t * t * 14,
                scale: 1.1,
                rotate: t * 180 + index * 30,
                opacity: 0.9 * fade,
            };
        case "star":
            return {
                x: origin.x + Math.cos(a) * (radius + 10) * out,
                y: origin.y + Math.sin(a) * (radius + 10) * out,
                scale: 0.6 + 0.8 * fade,
                rotate: t * 120,
                opacity: fade,
            };
        default:
            return {
                x: origin.x + Math.cos(a) * (8 + radius + index * 2) * out,
                y: origin.y + Math.sin(a) * (8 + radius + index * 2) * out,
                scale: 1,
                rotate: 0,
                opacity: 0.55 * fade,
            };
    }
}

/** Largest first, capped. */
export function pickLargest<T>(
    items: readonly T[],
    size: (item: T) => number,
    limit: number,
): T[] {
    return [...items].sort((a, b) => size(b) - size(a)).slice(0, limit);
}
