/** World units have one scale across dates; callers must not fit each day separately. */
export type PackingNode = { id: string; groupId: string; weight: number };
export type PackingPoint = { x: number; y: number };
export type PreviousPackingPosition = PackingPoint & {
    id: string;
    /** Equivalent radius last shown; a change means the stock grew or shrank. */
    r?: number;
};
export type PackingInput = {
    nodes: readonly PackingNode[];
    globalRadiusScale: number;
    previous?: readonly PreviousPackingPosition[];
    gap?: number;
    groupGap?: number;
    outlinePadding?: number;
    /** Width ÷ height of the frame the layout is shown in; groups spread to match it. */
    aspect?: number;
    /** The frame shape changed: compact toward `aspect` even if no stock changed. */
    reshape?: boolean;
};
export type PackedNode = PackingNode &
    PackingPoint & {
        /** Equivalent-area radius, exactly sqrt(weight) * globalRadiusScale. */
        r: number;
        /** Conservative radius of the actual organic boundary, used for collisions. */
        outerRadius: number;
        area: number;
        points: PackingPoint[];
        path: string;
    };
export type PackedGroup = PackingPoint & {
    id: string;
    r: number;
    weight: number;
    nodeIds: string[];
    area: number;
    points: PackingPoint[];
    path: string;
};
export type PackingBounds = {
    minX: number;
    minY: number;
    maxX: number;
    maxY: number;
    width: number;
    height: number;
};
export type PackingLayout = {
    nodes: PackedNode[];
    groups: PackedGroup[];
    /** Exact stock-vector bounds; decorative industry envelopes are excluded. */
    bounds: PackingBounds;
    /** Stock vector area divided by the world bounding rectangle; decorations are excluded. */
    fillRatio: number;
};

type Cubic = [PackingPoint, PackingPoint, PackingPoint, PackingPoint];
type Shape = { curves: Cubic[]; area: number; outerRadius: number };
type Disk = PackingPoint & { id: string; r: number };
type LocalNode = PackingNode &
    Disk & { shape: Shape; previous: boolean; equivalentRadius: number };
type LocalGroup = Disk & {
    nodes: LocalNode[];
    weight: number;
    previous: boolean;
};

const TAU = Math.PI * 2;
const RAYS = 40;
const STOCK_SEGMENTS = 24;
const CURVE_SAMPLES = 6;
const ANCHOR_ATTRACTION = 0.28;
const STOCK_COMPACTION_STEPS = 70;
const GROUP_COMPACTION_STEPS = 110;
/**
 * Beyond this many groups (e.g. hundreds of unclassified single-stock groups)
 * group-level compaction costs more than a playback frame allows, so those
 * layouts keep the plain ray-search placement.
 */
const MAX_COMPACTED_GROUPS = 160;
const SETTLE_STEPS = 120;
const REBUILD_STEPS = 8;
/** Wider or taller frames than this get the same composition shape. */
const MAX_ASPECT = 3;
const compareId = (a: { id: string }, b: { id: string }) =>
    a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
const point = (x: number, y: number): PackingPoint => ({ x, y });
const cross = (a: PackingPoint, b: PackingPoint) => a.x * b.y - a.y * b.x;

function hash(value: string): number {
    let result = 2166136261;
    for (let i = 0; i < value.length; i++)
        result = Math.imul(result ^ value.charCodeAt(i), 16777619);
    return result >>> 0;
}

function requireNonnegative(value: number, name: string): number {
    if (!Number.isFinite(value) || value < 0)
        throw new RangeError(`${name} must be finite and nonnegative`);
    return value;
}

/** Integrate x dy - y dx over the actual cubic, rather than its control polygon. */
function curveArea([p0, p1, p2, p3]: Cubic): number {
    const coefficients = [
        p0,
        point(3 * (p1.x - p0.x), 3 * (p1.y - p0.y)),
        point(3 * (p2.x - 2 * p1.x + p0.x), 3 * (p2.y - 2 * p1.y + p0.y)),
        point(
            p3.x - 3 * p2.x + 3 * p1.x - p0.x,
            p3.y - 3 * p2.y + 3 * p1.y - p0.y,
        ),
    ];
    let integral = 0;
    for (let i = 0; i < 4; i++) {
        for (let j = 1; j < 4; j++)
            integral += (cross(coefficients[i], coefficients[j]) * j) / (i + j);
    }
    return integral / 2;
}

function shapeFromCurves(curves: Cubic[]): Shape {
    return {
        curves,
        area: Math.abs(
            curves.reduce((sum, curve) => sum + curveArea(curve), 0),
        ),
        outerRadius: curves.reduce(
            (r, curve) =>
                Math.max(r, ...curve.map((p) => Math.hypot(p.x, p.y))),
            0,
        ),
    };
}

function stockShape(id: string, radius: number): Shape {
    if (radius === 0) return { curves: [], area: 0, outerRadius: 0 };
    const phase = (hash(id) / 0x100000000) * TAU;
    const sample = (angle: number) => {
        const r =
            1 +
            0.045 * Math.sin(3 * angle + phase) +
            0.025 * Math.cos(5 * angle - phase);
        const dr =
            0.135 * Math.cos(3 * angle + phase) -
            0.125 * Math.sin(5 * angle - phase);
        return {
            p: point(r * Math.cos(angle), r * Math.sin(angle)),
            d: point(
                dr * Math.cos(angle) - r * Math.sin(angle),
                dr * Math.sin(angle) + r * Math.cos(angle),
            ),
        };
    };
    const curves: Cubic[] = [];
    const step = TAU / STOCK_SEGMENTS;
    for (let i = 0; i < STOCK_SEGMENTS; i++) {
        const a = sample(i * step);
        const b = sample((i + 1) * step);
        curves.push([
            a.p,
            point(a.p.x + (a.d.x * step) / 3, a.p.y + (a.d.y * step) / 3),
            point(b.p.x - (b.d.x * step) / 3, b.p.y - (b.d.y * step) / 3),
            b.p,
        ]);
    }
    // Close with exactly the same endpoint, including floating-point coordinates.
    curves[curves.length - 1][3] = curves[0][0];
    const normalized = shapeFromCurves(curves);
    const correction = radius * Math.sqrt(Math.PI / normalized.area);
    return shapeFromCurves(
        curves.map(
            (curve) =>
                curve.map((p) =>
                    point(p.x * correction, p.y * correction),
                ) as Cubic,
        ),
    );
}

function translatedShape(
    shape: Shape,
    x: number,
    y: number,
): { points: PackingPoint[]; path: string } {
    if (!shape.curves.length)
        return { points: [point(x, y)], path: `M${x},${y}Z` };
    const points: PackingPoint[] = [];
    const first = shape.curves[0][0];
    let path = `M${first.x + x},${first.y + y}`;
    for (const [a, b, c, d] of shape.curves) {
        path += `C${b.x + x},${b.y + y} ${c.x + x},${c.y + y} ${d.x + x},${d.y + y}`;
        for (let i = 0; i < CURVE_SAMPLES; i++) {
            const t = i / CURVE_SAMPLES;
            const s = 1 - t;
            points.push(
                point(
                    s ** 3 * a.x +
                        3 * s ** 2 * t * b.x +
                        3 * s * t ** 2 * c.x +
                        t ** 3 * d.x +
                        x,
                    s ** 3 * a.y +
                        3 * s ** 2 * t * b.y +
                        3 * s * t ** 2 * c.y +
                        t ** 3 * d.y +
                        y,
                ),
            );
        }
    }
    return { points, path: `${path}Z` };
}

function cubicValue(values: number[], t: number): number {
    const s = 1 - t;
    return (
        s ** 3 * values[0] +
        3 * s ** 2 * t * values[1] +
        3 * s * t ** 2 * values[2] +
        t ** 3 * values[3]
    );
}

/** Actual Bézier extrema avoid fitting an oversized control-point envelope. */
function cubicExtent(values: number[]): [number, number] {
    const [p0, p1, p2, p3] = values;
    const a = -p0 + 3 * p1 - 3 * p2 + p3;
    const b = 2 * (p0 - 2 * p1 + p2);
    const c = p1 - p0;
    const roots: number[] = [];
    if (Math.abs(a) <= Number.EPSILON * Math.max(Math.abs(b), Math.abs(c))) {
        if (b !== 0) roots.push(-c / b);
    } else {
        const discriminant = b * b - 4 * a * c;
        if (discriminant >= 0) {
            roots.push(
                (-b + Math.sqrt(discriminant)) / (2 * a),
                (-b - Math.sqrt(discriminant)) / (2 * a),
            );
        }
    }
    const extremes = [
        p0,
        p3,
        ...roots
            .filter((t) => t > 0 && t < 1)
            .map((t) => cubicValue(values, t)),
    ];
    return [Math.min(...extremes), Math.max(...extremes)];
}

function stockBounds(groups: LocalGroup[]): PackingBounds {
    let minX = Infinity,
        minY = Infinity,
        maxX = -Infinity,
        maxY = -Infinity;
    for (const group of groups) {
        for (const node of group.nodes) {
            const x = group.x + node.x;
            const y = group.y + node.y;
            if (!node.shape.curves.length) {
                minX = Math.min(minX, x);
                minY = Math.min(minY, y);
                maxX = Math.max(maxX, x);
                maxY = Math.max(maxY, y);
            }
            for (const curve of node.shape.curves) {
                const [left, right] = cubicExtent(curve.map((p) => p.x));
                const [top, bottom] = cubicExtent(curve.map((p) => p.y));
                minX = Math.min(minX, x + left);
                minY = Math.min(minY, y + top);
                maxX = Math.max(maxX, x + right);
                maxY = Math.max(maxY, y + bottom);
            }
        }
    }
    if (!groups.length)
        return { minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0 };
    return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
}

function fits(candidate: Disk, placed: readonly Disk[], gap: number): boolean {
    if (candidate.r === 0) return true;
    return placed.every(
        (other) =>
            other.r === 0 ||
            Math.hypot(candidate.x - other.x, candidate.y - other.y) >=
                candidate.r + other.r + gap,
    );
}

/** Find the closest free point on deterministic rays, with no world-size limit. */
function placeDisk(
    candidate: Disk,
    placed: readonly Disk[],
    gap: number,
): PackingPoint {
    if (fits(candidate, placed, gap)) return point(candidate.x, candidate.y);
    let bestDistance = Infinity;
    let best = point(candidate.x, candidate.y);
    const phase = (hash(candidate.id) / 0x100000000) * TAU;
    for (let ray = 0; ray < RAYS; ray++) {
        const angle = phase + (ray * TAU) / RAYS;
        const dx = Math.cos(angle);
        const dy = Math.sin(angle);
        const intervals: [number, number][] = [];
        for (const other of placed) {
            if (other.r === 0) continue;
            const ox = other.x - candidate.x;
            const oy = other.y - candidate.y;
            const projection = ox * dx + oy * dy;
            const perpendicular = Math.abs(ox * dy - oy * dx);
            const exclusion = candidate.r + other.r + gap;
            if (perpendicular >= exclusion) continue;
            const half = Math.sqrt(
                Math.max(0, exclusion ** 2 - perpendicular ** 2),
            );
            if (projection + half >= 0)
                intervals.push([projection - half, projection + half]);
        }
        intervals.sort((a, b) => a[0] - b[0]);
        let distance = 0;
        for (const [start, end] of intervals) {
            if (start > distance) break;
            if (end >= distance)
                distance = end + Math.max(1e-9, Math.abs(end) * 1e-12);
        }
        if (distance < bestDistance) {
            bestDistance = distance;
            best = point(
                candidate.x + dx * distance,
                candidate.y + dy * distance,
            );
        }
    }
    if (!Number.isFinite(best.x) || !Number.isFinite(best.y))
        throw new RangeError("Packing coordinates exceed finite world units");
    return best;
}

/**
 * Pull disks toward the origin while pushing overlaps apart, then settle with
 * push-only passes. Warm starts keep continuity; the pull closes the holes that
 * departures leave, so repeated playback cannot drift outward. `ky > kx` pulls
 * harder vertically, which turns the composition into a wide ellipse.
 */
function compact(
    disks: Disk[],
    gap: number,
    kx: number,
    ky: number,
    steps: number,
): void {
    if (disks.length < 2) return;
    const maxR = Math.max(...disks.map((disk) => disk.r));
    // Overlaps below this are invisible; the exact repair below removes them.
    const tolerance = Math.max(1e-9, gap * 0.02);
    const order = disks.map((_, index) => index);
    // Neighbours drift apart or together only slowly between rebuilds; pairs
    // within this extra distance stay candidates until the next sweep.
    const slack = maxR * 0.5 + gap;
    const pairs: number[] = [];
    for (let step = 0; step < steps + SETTLE_STEPS; step++) {
        const settling = step >= steps;
        if (!settling) {
            const pull = 0.08 * (1 - step / steps) + 0.01;
            for (const disk of disks) {
                disk.x -= disk.x * pull * kx;
                disk.y -= disk.y * pull * ky;
            }
        }
        // Every few steps, sweep along x to list the pairs that can touch, then
        // resolve them in index order (big groups first), as a full pairwise
        // scan would, without paying for it with hundreds of groups.
        if (step % REBUILD_STEPS === 0) {
            order.sort((i, j) => disks[i].x - disks[j].x || i - j);
            pairs.length = 0;
            for (let p = 0; p < order.length; p++) {
                const a = disks[order[p]];
                if (a.r === 0) continue;
                for (let q = p + 1; q < order.length; q++) {
                    const b = disks[order[q]];
                    if (b.x - a.x >= a.r + maxR + gap + slack) break;
                    if (b.r === 0) continue;
                    const dy = Math.abs(b.y - a.y);
                    if (dy >= a.r + b.r + gap + slack) continue;
                    const i = Math.min(order[p], order[q]);
                    const j = Math.max(order[p], order[q]);
                    pairs.push(i * disks.length + j);
                }
            }
            pairs.sort((x, y) => x - y);
        }
        let worst = 0;
        for (let pass = 0; pass < 2; pass++)
            for (const pair of pairs) {
                const a = disks[Math.floor(pair / disks.length)];
                const b = disks[pair % disks.length];
                let dx = b.x - a.x;
                let dy = b.y - a.y;
                const min = a.r + b.r + gap;
                const squared = dx * dx + dy * dy;
                if (squared >= min * min) continue;
                let distance = Math.sqrt(squared);
                if (distance < 1e-9) {
                    // Deterministic separation for coincident centers.
                    const angle = (hash(a.id + b.id) / 0x100000000) * TAU;
                    dx = Math.cos(angle);
                    dy = Math.sin(angle);
                    distance = 1;
                }
                const push = (min - distance) / distance;
                const share = (b.r * b.r) / (a.r * a.r + b.r * b.r);
                worst = Math.max(worst, min - distance);
                a.x -= dx * push * share;
                a.y -= dy * push * share;
                b.x += dx * push * (1 - share);
                b.y += dy * push * (1 - share);
            }
        if (settling && worst <= tolerance) break;
    }
    // Push passes converge slowly when radii differ by orders of magnitude;
    // the exact ray search guarantees clearance for whatever is left.
    const repaired: Disk[] = [];
    for (const disk of disks) {
        if (!fits(disk, repaired, gap))
            Object.assign(disk, placeDisk(disk, repaired, gap));
        repaired.push(disk);
    }
}

function convexHull(points: PackingPoint[]): PackingPoint[] {
    const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
    const turn = (a: PackingPoint, b: PackingPoint, c: PackingPoint) =>
        cross(point(b.x - a.x, b.y - a.y), point(c.x - a.x, c.y - a.y));
    const half = (input: PackingPoint[]) => {
        const result: PackingPoint[] = [];
        for (const p of input) {
            while (
                result.length > 1 &&
                turn(result[result.length - 2], result[result.length - 1], p) <=
                    0
            )
                result.pop();
            result.push(p);
        }
        return result.slice(0, -1);
    };
    return [...half(sorted), ...half(sorted.reverse())];
}

/** A rounded envelope is decorative: its area never contributes to stock weights. */
function groupShape(nodes: LocalNode[], padding: number): Shape {
    const samples = nodes
        .filter((node) => node.r > 0)
        .flatMap((node) =>
            Array.from({ length: 24 }, (_, i) => {
                const angle = (i * TAU) / 24;
                // Circumscribed samples retain clearance after quadratic rounding.
                const radius = (node.r + padding) / Math.cos(TAU / 24);
                return point(
                    node.x + Math.cos(angle) * radius,
                    node.y + Math.sin(angle) * radius,
                );
            }),
        );
    if (!samples.length) return { curves: [], area: 0, outerRadius: 0 };
    const hull = convexHull(samples);
    const midpoint = (a: PackingPoint, b: PackingPoint) =>
        point((a.x + b.x) / 2, (a.y + b.y) / 2);
    const curves: Cubic[] = hull.map((p, i) => {
        const a = midpoint(hull[(i + hull.length - 1) % hull.length], p);
        const b = midpoint(p, hull[(i + 1) % hull.length]);
        return [
            a,
            point(a.x + (2 * (p.x - a.x)) / 3, a.y + (2 * (p.y - a.y)) / 3),
            point(b.x + (2 * (p.x - b.x)) / 3, b.y + (2 * (p.y - b.y)) / 3),
            b,
        ];
    });
    return shapeFromCurves(curves);
}

function localGroup(
    id: string,
    inputs: PackingNode[],
    previous: Map<string, PreviousPackingPosition>,
    scale: number,
    gap: number,
    padding: number,
    tighten: boolean,
): LocalGroup {
    const known = inputs.flatMap((node) =>
        previous.has(node.id) ? [previous.get(node.id)!] : [],
    );
    const anchor = point(
        known.reduce((s, p) => s + p.x / known.length, 0),
        known.reduce((s, p) => s + p.y / known.length, 0),
    );
    const nodes: LocalNode[] = inputs
        .map((node) => {
            const r = requireNonnegative(
                Math.sqrt(node.weight) * scale,
                "derived radius",
            );
            requireNonnegative(Math.PI * r * r, "derived area");
            const shape = stockShape(node.id, r);
            const old = previous.get(node.id);
            return {
                ...node,
                x: old ? old.x - anchor.x : 0,
                y: old ? old.y - anchor.y : 0,
                r: shape.outerRadius,
                shape,
                previous: !!old,
                equivalentRadius: r,
            };
        })
        .sort(
            (a, b) =>
                Number(b.previous) - Number(a.previous) ||
                b.weight - a.weight ||
                compareId(a, b),
        );
    const placed: Disk[] = [];
    for (const node of nodes) {
        Object.assign(node, placeDisk(node, placed, gap));
        placed.push(node);
    }
    const anchorX = nodes.reduce((s, p) => s + p.x / nodes.length, 0);
    const anchorY = nodes.reduce((s, p) => s + p.y / nodes.length, 0);
    for (const node of nodes) {
        node.x -= anchorX;
        node.y -= anchorY;
    }
    if (tighten) compact(nodes, gap, 1, 1, STOCK_COMPACTION_STEPS);
    // A deterministic node centroid can be reconstructed from next day's previous
    // positions, which only carry nodes with area, so zero-area nodes are left out.
    const sized = nodes.some((node) => node.r > 0)
        ? nodes.filter((node) => node.r > 0)
        : nodes;
    const center = point(
        sized.reduce((s, p) => s + p.x / sized.length, 0),
        sized.reduce((s, p) => s + p.y / sized.length, 0),
    );
    for (const node of nodes) {
        node.x -= center.x;
        node.y -= center.y;
    }
    const radius = nodes.reduce(
        (r, node) =>
            Math.max(
                r,
                Math.hypot(node.x, node.y) +
                    (node.r > 0 ? (node.r + padding) / Math.cos(TAU / 24) : 0),
            ),
        0,
    );
    return {
        id,
        x: anchor.x + center.x,
        y: anchor.y + center.y,
        r: radius,
        nodes,
        weight: inputs.reduce((s, node) => s + node.weight, 0),
        previous: known.length > 0,
    };
}

export function computePacking(input: PackingInput): PackingLayout {
    const scale = requireNonnegative(
        input.globalRadiusScale,
        "globalRadiusScale",
    );
    const gap = requireNonnegative(input.gap ?? 1.5, "gap");
    const groupGap = requireNonnegative(input.groupGap ?? 4, "groupGap");
    const groupSeparation = Math.max(gap, groupGap);
    const padding = requireNonnegative(
        input.outlinePadding ?? 5,
        "outlinePadding",
    );
    const previous = new Map<string, PreviousPackingPosition>();
    for (const p of input.previous ?? []) {
        if (!Number.isFinite(p.x) || !Number.isFinite(p.y))
            throw new RangeError("Previous positions must be finite");
        if (previous.has(p.id))
            throw new Error(`Duplicate previous id: ${p.id}`);
        previous.set(p.id, p);
    }
    const byGroup = new Map<string, PackingNode[]>();
    const ids = new Set<string>();
    for (const node of [...input.nodes].sort(compareId)) {
        if (ids.has(node.id))
            throw new Error(`Duplicate packing id: ${node.id}`);
        ids.add(node.id);
        requireNonnegative(node.weight, `weight for ${node.id}`);
        const group = byGroup.get(node.groupId) ?? [];
        group.push(node);
        byGroup.set(node.groupId, group);
    }
    // Compact only when something changed, so an unchanged day never jiggles.
    const tighten =
        input.reshape === true ||
        previous.size === 0 ||
        [...previous.keys()].some((id) => !ids.has(id)) ||
        input.nodes.some((node) => {
            const old = previous.get(node.id);
            const r = Math.sqrt(node.weight) * scale;
            // Zero-area nodes are never carried as previous positions, so a
            // missing entry only counts as an arrival once the node has area.
            if (!old) return r > 0;
            return (
                old.r !== undefined &&
                Math.abs(old.r - r) > 1e-9 * Math.max(1, r)
            );
        });
    const groups = [...byGroup]
        .map(([id, nodes]) =>
            localGroup(id, nodes, previous, scale, gap, padding, tighten),
        )
        .sort(
            (a, b) =>
                Number(b.previous) - Number(a.previous) ||
                b.weight - a.weight ||
                compareId(a, b),
        );
    // Compact, strength-ordered targets supply a fixed origin. Previous positions
    // remain the majority of each survivor's initial position before collision repair.
    // Only surviving groups being re-tightened use them, and building them is
    // the costliest step with hundreds of groups, so skip it otherwise.
    const canonical: Disk[] = [];
    const anchored = tighten && groups.some((group) => group.previous);
    for (const group of anchored
        ? [...groups].sort((a, b) => b.weight - a.weight || compareId(a, b))
        : []) {
        const disk = { id: group.id, x: 0, y: 0, r: group.r };
        Object.assign(disk, placeDisk(disk, canonical, groupSeparation));
        canonical.push(disk);
    }
    const targets = new Map(canonical.map((group) => [group.id, group]));
    const placed: Disk[] = [];
    const hadPreviousGroups = groups.some((group) => group.previous);
    for (const group of groups) {
        if (group.previous) {
            const target = targets.get(group.id);
            if (target) {
                group.x += (target.x - group.x) * ANCHOR_ATTRACTION;
                group.y += (target.y - group.y) * ANCHOR_ATTRACTION;
            }
        } else {
            const edge = hadPreviousGroups
                ? placed.reduce(
                      (r, p) => Math.max(r, Math.hypot(p.x, p.y) + p.r),
                      0,
                  )
                : 0;
            const angle = (hash(group.id) / 0x100000000) * TAU;
            group.x = edge
                ? Math.cos(angle) * (edge + group.r + groupSeparation)
                : 0;
            group.y = edge
                ? Math.sin(angle) * (edge + group.r + groupSeparation)
                : 0;
        }
        Object.assign(group, placeDisk(group, placed, groupSeparation));
        placed.push(group);
    }
    const aspect = input.aspect ?? 1;
    if (!Number.isFinite(aspect) || aspect <= 0)
        throw new RangeError("aspect must be a positive finite number");
    // Pull the short axis harder. The aspect is capped so a pull step never
    // exceeds the distance to the centre (0.09 × 3² < 1); beyond that the
    // update overshoots and the layout diverges.
    const shape = Math.min(MAX_ASPECT, Math.max(1 / MAX_ASPECT, aspect)) ** 2;
    if (tighten && groups.length <= MAX_COMPACTED_GROUPS)
        compact(
            groups,
            groupSeparation,
            Math.max(1, 1 / shape),
            Math.max(1, shape),
            GROUP_COMPACTION_STEPS,
        );
    // Center the composition in world coordinates, never in the camera. The
    // strength anchors above keep large groups near the middle; pinning the largest
    // group's center instead would clip ordinary neighboring groups asymmetrically.
    const uncentered = stockBounds(groups);
    const origin = point(
        (uncentered.minX + uncentered.maxX) / 2,
        (uncentered.minY + uncentered.maxY) / 2,
    );
    for (const group of groups) {
        group.x -= origin.x;
        group.y -= origin.y;
    }
    const nodes: PackedNode[] = groups
        .flatMap((group) =>
            group.nodes.map((node) => {
                const x = group.x + node.x;
                const y = group.y + node.y;
                return {
                    id: node.id,
                    groupId: node.groupId,
                    weight: node.weight,
                    x,
                    y,
                    r: node.equivalentRadius,
                    outerRadius: node.r,
                    area: node.shape.area,
                    ...translatedShape(node.shape, x, y),
                };
            }),
        )
        .sort(compareId);
    const outlines: PackedGroup[] = groups
        .map((group) => {
            const shape = groupShape(group.nodes, padding);
            return {
                id: group.id,
                x: group.x,
                y: group.y,
                r: group.r,
                weight: group.weight,
                nodeIds: group.nodes.map((node) => node.id).sort(),
                area: shape.area,
                ...translatedShape(shape, group.x, group.y),
            };
        })
        .sort(compareId);
    const bounds = stockBounds(groups);
    if (
        ![...Object.values(bounds), ...outlines.map((g) => g.weight)].every(
            Number.isFinite,
        )
    )
        throw new RangeError("Packing exceeds finite world units");
    const area = requireNonnegative(
        nodes.reduce((sum, node) => sum + node.area, 0),
        "total area",
    );
    const rectangleArea = requireNonnegative(
        bounds.width * bounds.height,
        "world area",
    );
    return {
        nodes,
        groups: outlines,
        bounds,
        fillRatio: rectangleArea > 0 ? area / rectangleArea : 0,
    };
}
