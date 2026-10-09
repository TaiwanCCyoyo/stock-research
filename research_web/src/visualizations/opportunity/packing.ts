/** World units have one scale across dates; callers must not fit each day separately. */
export type PackingNode = { id: string; groupId: string; weight: number };
export type PackingPoint = { x: number; y: number };
export type PreviousPackingPosition = PackingPoint & { id: string };
export type PackingInput = {
    nodes: readonly PackingNode[];
    globalRadiusScale: number;
    previous?: readonly PreviousPackingPosition[];
    gap?: number;
    groupGap?: number;
    outlinePadding?: number;
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
    // A deterministic node centroid can be reconstructed from next day's previous positions.
    const center = point(
        nodes.reduce((s, p) => s + p.x / nodes.length, 0),
        nodes.reduce((s, p) => s + p.y / nodes.length, 0),
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
    const groups = [...byGroup]
        .map(([id, nodes]) =>
            localGroup(id, nodes, previous, scale, gap, padding),
        )
        .sort(
            (a, b) =>
                Number(b.previous) - Number(a.previous) ||
                b.weight - a.weight ||
                compareId(a, b),
        );
    // Compact, strength-ordered targets supply a fixed origin. Previous positions
    // remain the majority of each survivor's initial position before collision repair.
    const canonical: Disk[] = [];
    for (const group of [...groups].sort(
        (a, b) => b.weight - a.weight || compareId(a, b),
    )) {
        const disk = { id: group.id, x: 0, y: 0, r: group.r };
        Object.assign(disk, placeDisk(disk, canonical, groupSeparation));
        canonical.push(disk);
    }
    const targets = new Map(canonical.map((group) => [group.id, group]));
    const placed: Disk[] = [];
    const hadPreviousGroups = groups.some((group) => group.previous);
    for (const group of groups) {
        if (group.previous) {
            const target = targets.get(group.id)!;
            group.x += (target.x - group.x) * ANCHOR_ATTRACTION;
            group.y += (target.y - group.y) * ANCHOR_ATTRACTION;
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
