/** Deterministic, capacity-constrained cells. All areas are SVG user units squared. */
export type CellInput = { id: string; weight: number; group: string };
export type Point = [number, number];
export type CellLayout = {
    id: string;
    points: Point[];
    path: string;
    x: number;
    y: number;
    area: number;
    targetArea: number;
};

const EPSILON = 1e-12;
const AREA_TOLERANCE = 0.005;

function hash(text: string): number {
    let value = 2166136261;
    for (let index = 0; index < text.length; index++) {
        value = Math.imul(value ^ text.charCodeAt(index), 16777619);
    }
    return (value >>> 0) / 4294967296;
}

function area(points: Point[]): number {
    // Translating to one vertex avoids cancellation for very small cells.
    const origin = points[0];
    if (!origin) return 0;
    let sum = 0;
    for (let index = 1; index + 1 < points.length; index++) {
        const a = points[index];
        const b = points[index + 1];
        sum +=
            (a[0] - origin[0]) * (b[1] - origin[1]) -
            (a[1] - origin[1]) * (b[0] - origin[0]);
    }
    return Math.abs(sum) / 2;
}

function centroid(points: Point[]): Point {
    const origin = points[0];
    let mass = 0;
    let x = 0;
    let y = 0;
    for (let index = 1; index + 1 < points.length; index++) {
        const a = points[index];
        const b = points[index + 1];
        const cross =
            (a[0] - origin[0]) * (b[1] - origin[1]) -
            (a[1] - origin[1]) * (b[0] - origin[0]);
        mass += cross;
        x += cross * (a[0] - origin[0] + (b[0] - origin[0]));
        y += cross * (a[1] - origin[1] + (b[1] - origin[1]));
    }
    return mass === 0
        ? origin
        : [origin[0] + x / (3 * mass), origin[1] + y / (3 * mass)];
}

/** Retain nx*x + ny*y <= offset; intersections belong to both adjacent cells. */
function clip(
    points: Point[],
    nx: number,
    ny: number,
    offset: number,
): Point[] {
    const result: Point[] = [];
    for (let index = 0; index < points.length; index++) {
        const a = points[index];
        const b = points[(index + 1) % points.length];
        const da = a[0] * nx + a[1] * ny - offset;
        const db = b[0] * nx + b[1] * ny - offset;
        if (da <= 0) result.push(a);
        if ((da < 0 && db > 0) || (da > 0 && db < 0)) {
            const fraction = da / (da - db);
            result.push([
                a[0] + (b[0] - a[0]) * fraction,
                a[1] + (b[1] - a[1]) * fraction,
            ]);
        }
    }
    return result;
}

function outline(width: number, height: number): Point[] {
    // Even radial harmonics keep an irregular, near-symmetric oval convex.
    // Convexity allows an exact, gap-free half-plane partition.
    return Array.from({ length: 96 }, (_, index): Point => {
        const angle = (index / 96) * Math.PI * 2;
        const radius =
            1 +
            0.018 * Math.cos(4 * angle + 0.2) +
            0.008 * Math.cos(8 * angle - 0.5);
        return [
            width * (0.5 + 0.445 * radius * Math.cos(angle)),
            height * (0.5 + 0.445 * radius * Math.sin(angle)),
        ];
    });
}

type Region = { key: string; weight: number; indexes: number[] };

/** Exact-area oblique cuts supply clustered seeds and a numerical fallback. */
function partition(
    points: Point[],
    regions: Region[],
    result: Map<string, Point[]>,
    depth = 0,
): void {
    if (regions.length === 1) {
        result.set(regions[0].key, points);
        return;
    }
    const midpoint = Math.floor(regions.length / 2);
    const left = regions.slice(0, midpoint);
    const right = regions.slice(midpoint);
    const total = regions.reduce((sum, region) => sum + region.weight, 0);
    const wanted =
        (area(points) * left.reduce((sum, region) => sum + region.weight, 0)) /
        total;
    const xs = points.map((point) => point[0]);
    const ys = points.map((point) => point[1]);
    const wider =
        Math.max(...xs) - Math.min(...xs) >= Math.max(...ys) - Math.min(...ys);
    const tilt =
        (hash(`${depth}:${regions.map((region) => region.key).join("|")}`) -
            0.5) *
        0.28;
    const angle = (wider ? 0 : Math.PI / 2) + tilt;
    const nx = Math.cos(angle);
    const ny = Math.sin(angle);
    const projections = points.map((point) => point[0] * nx + point[1] * ny);
    let low = Math.min(...projections);
    let high = Math.max(...projections);
    for (let iteration = 0; iteration < 64; iteration++) {
        const middle = (low + high) / 2;
        if (area(clip(points, nx, ny, middle)) < wanted) low = middle;
        else high = middle;
    }
    const offset = (low + high) / 2;
    partition(clip(points, nx, ny, offset), left, result, depth + 1);
    partition(clip(points, -nx, -ny, -offset), right, result, depth + 1);
}

function initialRegions(items: CellInput[], boundary: Point[]): Point[][] {
    const groups = new Map<string, Region>();
    items.forEach((item, index) => {
        const group = groups.get(item.group) ?? {
            key: item.group,
            weight: 0,
            indexes: [],
        };
        group.weight += item.weight;
        group.indexes.push(index);
        groups.set(item.group, group);
    });
    const groupRegions = new Map<string, Point[]>();
    partition(boundary, [...groups.values()], groupRegions);
    const cellRegions = new Map<string, Point[]>();
    for (const group of groups.values()) {
        partition(
            groupRegions.get(group.key)!,
            group.indexes.map((index) => ({
                key: items[index].id,
                weight: items[index].weight,
                indexes: [index],
            })),
            cellRegions,
        );
    }
    return items.map((item) => cellRegions.get(item.id)!);
}

function diagram(
    boundary: Point[],
    sites: Point[],
    potentials: number[],
): Point[][] {
    return sites.map((site, index) => {
        let polygon = boundary;
        for (let other = 0; other < sites.length && polygon.length; other++) {
            if (other === index) continue;
            const next = sites[other];
            polygon = clip(
                polygon,
                2 * (next[0] - site[0]),
                2 * (next[1] - site[1]),
                next[0] ** 2 +
                    next[1] ** 2 -
                    site[0] ** 2 -
                    site[1] ** 2 +
                    potentials[index] -
                    potentials[other],
            );
        }
        return polygon;
    });
}

function solveLinear(matrix: number[][], rhs: number[]): number[] | null {
    const augmented = matrix.map((row, index) => [...row, rhs[index]]);
    const count = rhs.length;
    for (let column = 0; column < count; column++) {
        let pivot = column;
        for (let row = column + 1; row < count; row++) {
            if (
                Math.abs(augmented[row][column]) >
                Math.abs(augmented[pivot][column])
            )
                pivot = row;
        }
        if (Math.abs(augmented[pivot][column]) < EPSILON) return null;
        [augmented[column], augmented[pivot]] = [
            augmented[pivot],
            augmented[column],
        ];
        for (let row = column + 1; row < count; row++) {
            const factor = augmented[row][column] / augmented[column][column];
            for (let k = column; k <= count; k++)
                augmented[row][k] -= factor * augmented[column][k];
        }
    }
    const result = Array<number>(count).fill(0);
    for (let row = count - 1; row >= 0; row--) {
        let value = augmented[row][count];
        for (let column = row + 1; column < count; column++)
            value -= augmented[row][column] * result[column];
        result[row] = value / augmented[row][row];
    }
    return result;
}

function capacityCells(
    boundary: Point[],
    sites: Point[],
    targets: number[],
): Point[][] | null {
    const count = sites.length;
    let potentials = Array<number>(count).fill(0);
    let cells = diagram(boundary, sites, potentials);
    for (let iteration = 0; iteration < 48; iteration++) {
        const areas = cells.map(area);
        if (areas.some((value) => value <= 0)) return null;
        const error = areas.map((value, index) => targets[index] - value);
        if (
            Math.max(
                ...error.map(
                    (value, index) => Math.abs(value) / targets[index],
                ),
            ) < AREA_TOLERANCE
        )
            return cells;
        const jacobian = Array.from({ length: count }, () =>
            Array<number>(count).fill(0),
        );
        for (let index = 0; index < count; index++) {
            for (let other = index + 1; other < count; other++) {
                const nx = 2 * (sites[other][0] - sites[index][0]);
                const ny = 2 * (sites[other][1] - sites[index][1]);
                const norm = Math.hypot(nx, ny);
                const offset =
                    sites[other][0] ** 2 +
                    sites[other][1] ** 2 -
                    sites[index][0] ** 2 -
                    sites[index][1] ** 2 +
                    potentials[index] -
                    potentials[other];
                let length = 0;
                const polygon = cells[index];
                for (let edge = 0; edge < polygon.length; edge++) {
                    const a = polygon[edge];
                    const b = polygon[(edge + 1) % polygon.length];
                    if (
                        Math.abs(a[0] * nx + a[1] * ny - offset) <
                            1e-8 * norm &&
                        Math.abs(b[0] * nx + b[1] * ny - offset) < 1e-8 * norm
                    ) {
                        length += Math.hypot(b[0] - a[0], b[1] - a[1]);
                    }
                }
                const derivative = length / norm;
                jacobian[index][index] += derivative;
                jacobian[other][other] += derivative;
                jacobian[index][other] -= derivative;
                jacobian[other][index] -= derivative;
            }
        }
        // Potentials are defined up to a constant; anchor the last one at zero.
        const delta = solveLinear(
            jacobian.slice(0, -1).map((row) => row.slice(0, -1)),
            error.slice(0, -1),
        );
        if (!delta || delta.some((value) => !Number.isFinite(value)))
            return null;
        delta.push(0);
        const previousError = error.reduce(
            (sum, value) => sum + Math.abs(value),
            0,
        );
        let accepted = false;
        for (let step = 1; step >= 1 / 4096; step /= 2) {
            const nextPotentials = potentials.map(
                (value, index) => value + step * delta[index],
            );
            const candidate = diagram(boundary, sites, nextPotentials);
            const candidateAreas = candidate.map(area);
            const nextError = candidateAreas.reduce(
                (sum, value, index) => sum + Math.abs(value - targets[index]),
                0,
            );
            if (
                candidateAreas.every((value) => value > 0) &&
                nextError < previousError
            ) {
                cells = candidate;
                potentials = nextPotentials;
                accepted = true;
                break;
            }
        }
        if (!accepted) return null;
    }
    return null;
}

function pointKey(point: Point): string {
    return `${point[0].toFixed(12)},${point[1].toFixed(12)}`;
}

/**
 * Round sharp corners inward before the shared bijective warp. Quadratic control
 * points all lie inside the original convex cell, so rounding cannot overlap a
 * neighbour. The small corner gaps are intentional foam junctions, not exact-area
 * geometry: halve the cutback until the measured loss is <= 0.8% of target area.
 */
function roundCorners(
    points: Point[],
    targetArea: number,
    maximumCutback: number,
): Point[] {
    const originalArea = area(points);
    for (let reduction = 0; reduction < 16; reduction++) {
        const radius = maximumCutback / 2 ** reduction;
        const rounded = points.flatMap((vertex, index): Point[] => {
            const previous =
                points[(index + points.length - 1) % points.length];
            const next = points[(index + 1) % points.length];
            const previousLength = Math.hypot(
                previous[0] - vertex[0],
                previous[1] - vertex[1],
            );
            const nextLength = Math.hypot(
                next[0] - vertex[0],
                next[1] - vertex[1],
            );
            if (previousLength <= EPSILON || nextLength <= EPSILON)
                return [vertex];
            const cosine =
                ((vertex[0] - previous[0]) * (next[0] - vertex[0]) +
                    (vertex[1] - previous[1]) * (next[1] - vertex[1])) /
                (previousLength * nextLength);
            // The already-dense organic outline needs no extra corner treatment.
            if (Math.acos(Math.max(-1, Math.min(1, cosine))) < 0.18)
                return [vertex];
            const cutback = Math.min(
                radius,
                previousLength * 0.2,
                nextLength * 0.2,
            );
            const entry: Point = [
                vertex[0] +
                    ((previous[0] - vertex[0]) * cutback) / previousLength,
                vertex[1] +
                    ((previous[1] - vertex[1]) * cutback) / previousLength,
            ];
            const exit: Point = [
                vertex[0] + ((next[0] - vertex[0]) * cutback) / nextLength,
                vertex[1] + ((next[1] - vertex[1]) * cutback) / nextLength,
            ];
            return Array.from({ length: 13 }, (_, sample): Point => {
                const t = sample / 12;
                const s = 1 - t;
                return [
                    s * s * entry[0] + 2 * s * t * vertex[0] + t * t * exit[0],
                    s * s * entry[1] + 2 * s * t * vertex[1] + t * t * exit[1],
                ];
            });
        });
        const loss = originalArea - area(rounded);
        if (loss >= -targetArea * 1e-10 && loss <= targetArea * 0.008)
            return rounded;
    }
    // Preserve the valid original cell if a radius cannot be represented safely.
    return points;
}

/** Include T junctions before sampling so both sides share identical subedges. */
function splitSharedEdges(polygons: Point[][]): Point[][] {
    const vertices = [
        ...new Map(
            polygons.flat().map((point) => [pointKey(point), point]),
        ).values(),
    ];
    return polygons.map((polygon) =>
        polygon.flatMap((a, index) => {
            const b = polygon[(index + 1) % polygon.length];
            const dx = b[0] - a[0];
            const dy = b[1] - a[1];
            const squaredLength = dx * dx + dy * dy;
            if (squaredLength < EPSILON * EPSILON) return [];
            const inside = vertices.flatMap((point) => {
                const t =
                    ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) /
                    squaredLength;
                const cross = (point[0] - a[0]) * dy - (point[1] - a[1]) * dx;
                return t > 1e-9 &&
                    t < 1 - 1e-9 &&
                    Math.abs(cross) < 1e-11 * Math.sqrt(squaredLength)
                    ? [{ t, point }]
                    : [];
            });
            return [
                a,
                ...inside
                    .sort((left, right) => left.t - right.t)
                    .map((entry) => entry.point),
            ];
        }),
    );
}

/**
 * A composition of two low-amplitude sinusoidal shears has Jacobian determinant
 * exactly one: x' = x + a sin(ky*y), y' = y + b sin(kx*x').
 * Its inverse just subtracts those shears in reverse order. Thus every cell and
 * every shared boundary undergo the same continuous, bijective area-preserving
 * deformation. Dense polylines approximate that curve; their area error is checked.
 */
function organicWarp(
    polygons: Point[][],
    boundary: Point[],
    width: number,
    height: number,
): { polygons: Point[][]; areaScale: number } {
    const warp = ([x, y]: Point): Point => {
        const shearedX =
            x +
            width * 0.018 * Math.sin((4 * Math.PI * (y - height / 2)) / height);
        return [
            shearedX,
            y +
                height *
                    0.014 *
                    Math.sin((4 * Math.PI * (shearedX - width / 2)) / width),
        ];
    };
    const sample = (regions: Point[][], step: number): Point[][] => {
        const edges = new Map<string, Point[]>();
        return regions.map((polygon) =>
            polygon.flatMap((a, index) => {
                const b = polygon[(index + 1) % polygon.length];
                const aKey = pointKey(a);
                const bKey = pointKey(b);
                const reversed = aKey > bKey;
                const key = reversed ? `${bKey}|${aKey}` : `${aKey}|${bKey}`;
                let samples = edges.get(key);
                if (!samples) {
                    const from = reversed ? b : a;
                    const to = reversed ? a : b;
                    const distance = Math.hypot(
                        (to[0] - from[0]) / width,
                        (to[1] - from[1]) / height,
                    );
                    const segments = Math.max(1, Math.ceil(distance / step));
                    samples = Array.from({ length: segments + 1 }, (_, part) =>
                        warp([
                            from[0] + ((to[0] - from[0]) * part) / segments,
                            from[1] + ((to[1] - from[1]) * part) / segments,
                        ]),
                    );
                    edges.set(key, samples);
                }
                return reversed
                    ? [...samples].reverse().slice(0, -1)
                    : samples.slice(0, -1);
            }),
        );
    };
    const joined = splitSharedEdges(polygons);
    const originalAreas = polygons.map(area);
    let warped: Point[][] = [];
    let accepted = false;
    for (let refinement = 0; refinement < 6; refinement++) {
        warped = sample(joined, 1 / (256 * 2 ** refinement));
        if (
            warped.every(
                (polygon, index) =>
                    Math.abs(area(polygon) / originalAreas[index] - 1) < 0.0002,
            )
        ) {
            accepted = true;
            break;
        }
    }
    if (!accepted)
        throw new RangeError(
            "Curved cell sampling cannot preserve area within 0.02%",
        );

    // Reframe once for the entire island, never independently for each cell.
    // A fixed outline sample keeps this frame independent of item count/order.
    const outlineSamples = sample([boundary], 1 / 2048)[0];
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const [x, y] of outlineSamples) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
    }
    // Margin also covers the bounded chord error between outline samples.
    minX -= width * 0.00001;
    maxX += width * 0.00001;
    minY -= height * 0.00001;
    maxY += height * 0.00001;
    const scaleX = (width * 0.94) / (maxX - minX);
    const scaleY = (height * 0.94) / (maxY - minY);
    return {
        polygons: warped.map((polygon) =>
            polygon.map(([x, y]): Point => [
                width * 0.03 + (x - minX) * scaleX,
                height * 0.03 + (y - minY) * scaleY,
            ]),
        ),
        areaScale: scaleX * scaleY,
    };
}

function path(points: Point[]): string {
    return `M ${points.map(([x, y]) => `${x} ${y}`).join(" L ")} Z`;
}

/**
 * Positive finite weights only; no minimum-area or hidden weight correction.
 * Missing/zero weights remain a caller's list-access concern and are omitted.
 * Identity sorting removes input-order jitter; group partitions keep seeds close.
 * Returned paths are the returned dense polygons: measured areas include the
 * global warp and inward corner rounding. Solver tolerance is 0.5%; rounding
 * removes <= 0.8% of target area and warp sampling adds at most 0.02%. Final
 * coloured-area shares must stay within 2% of their requested weight shares.
 */
export function layoutCells(
    items: CellInput[],
    width: number,
    height: number,
): CellLayout[] {
    if (
        !Number.isFinite(width) ||
        !Number.isFinite(height) ||
        width <= 0 ||
        height <= 0
    )
        return [];
    const eligible = items.filter(
        (item) => Number.isFinite(item.weight) && item.weight > 0,
    );
    if (!eligible.length) return [];
    if (eligible.length > 36)
        throw new RangeError(
            "layoutCells supports at most 36 positive-weight cells",
        );
    if (new Set(eligible.map((item) => item.id)).size !== eligible.length)
        throw new TypeError("Cell IDs must be unique");
    const ordered = [...eligible].sort((a, b) =>
        a.group < b.group
            ? -1
            : a.group > b.group
              ? 1
              : a.id < b.id
                ? -1
                : a.id > b.id
                  ? 1
                  : 0,
    );
    const maximum = Math.max(...ordered.map((item) => item.weight));
    const normalized = ordered.map((item) => ({
        ...item,
        weight: item.weight / maximum,
    }));
    const sum = normalized.reduce((total, item) => total + item.weight, 0);
    // Unit-scale solving keeps precision consistent across responsive dimensions.
    const scale = Math.max(width, height);
    const boundary = outline(width / scale, height / scale);
    const totalArea = area(boundary);
    const targets = normalized.map((item) => (totalArea * item.weight) / sum);
    if (targets.some((value) => value <= 0 || !Number.isFinite(value)))
        throw new RangeError("Weight ratio exceeds floating-point precision");
    const initial = initialRegions(normalized, boundary);
    let polygons = initial;
    if (ordered.length > 1) {
        // Bounded Lloyd relaxation: preserve identities and improve compactness.
        for (let round = 0; round < 4; round++) {
            const candidate = capacityCells(
                boundary,
                polygons.map(centroid),
                targets,
            );
            if (!candidate) break;
            polygons = candidate;
        }
    }
    if (
        polygons.some(
            (polygon, index) =>
                Math.abs(area(polygon) / targets[index] - 1) > 0.05,
        )
    ) {
        throw new RangeError(
            "Cell areas cannot be represented within 5% of the requested weights",
        );
    }
    const rounded = polygons.map((polygon, index) =>
        roundCorners(polygon, targets[index], 18 / scale),
    );
    const warped = organicWarp(
        rounded,
        boundary,
        width / scale,
        height / scale,
    );
    const scaled = warped.polygons.map((polygon) =>
        polygon.map(([x, y]): Point => [x * scale, y * scale]),
    );
    const measuredAreas = scaled.map(area);
    const measuredTotal = measuredAreas.reduce(
        (total, value) => total + value,
        0,
    );
    const results = new Map<string, CellLayout>();
    scaled.forEach((points, index) => {
        const [x, y] = centroid(points);
        const targetArea = targets[index] * warped.areaScale * scale * scale;
        const measuredArea = measuredAreas[index];
        const requestedShare = normalized[index].weight / sum;
        if (
            Math.abs(measuredArea / (measuredTotal * requestedShare) - 1) >=
                0.02 ||
            Math.abs(measuredArea / targetArea - 1) >= 0.02
        ) {
            throw new RangeError(
                "Rounded cell area exceeds the 2% weight tolerance",
            );
        }
        results.set(ordered[index].id, {
            id: ordered[index].id,
            points,
            path: path(points),
            x,
            y,
            area: measuredArea,
            targetArea,
        });
    });
    return eligible.map((item) => results.get(item.id)!);
}
