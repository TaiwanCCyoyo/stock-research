import { useEffect, useMemo, useRef, useState } from "react";
import type { CellLayout } from "./geometry";
import { LatestQueue } from "./latestQueue";

export interface MapNode {
    id: string;
    weight: number;
    group: string;
    label: string;
    detail: string;
    gain: string;
    count: number;
}
type Point = [number, number];
interface Shape {
    node: MapNode;
    points: Point[];
    path?: string;
    x: number;
    y: number;
    area: number;
    opacity: number;
    exiting: boolean;
    burst?: number;
    space: LabelSpace;
}
type LabelSpace = { x: number; y: number; r: number };
type LayoutResult = {
    requestId: number;
    nodes: MapNode[];
    cells: CellLayout[];
    period: string;
};
type GeometryWorkerMessage =
    LayoutResult | { requestId: number; nodes: MapNode[]; error: string };
function labelSpace(points: Point[], cx: number, cy: number): LabelSpace {
    const xs = points.map((p) => p[0]),
        ys = points.map((p) => p[1]);
    const minX = Math.min(...xs),
        maxX = Math.max(...xs),
        minY = Math.min(...ys),
        maxY = Math.max(...ys);
    const inside = (x: number, y: number) => {
        let hit = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
            const a = points[i],
                b = points[j];
            if (
                a[1] > y !== b[1] > y &&
                x < ((b[0] - a[0]) * (y - a[1])) / (b[1] - a[1]) + a[0]
            )
                hit = !hit;
        }
        return hit;
    };
    const radius = (x: number, y: number) => {
        if (!inside(x, y)) return 0;
        let r = Infinity;
        for (let i = 0; i < points.length; i++) {
            const a = points[i],
                b = points[(i + 1) % points.length],
                dx = b[0] - a[0],
                dy = b[1] - a[1];
            const t = Math.max(
                0,
                Math.min(
                    1,
                    ((x - a[0]) * dx + (y - a[1]) * dy) /
                        (dx * dx + dy * dy || 1),
                ),
            );
            r = Math.min(r, Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy));
        }
        return r;
    };
    let best = { x: cx, y: cy, r: radius(cx, cy) };
    for (let i = 1; i < 7; i++)
        for (let j = 1; j < 7; j++) {
            const x = minX + ((maxX - minX) * i) / 7,
                y = minY + ((maxY - minY) * j) / 7,
                r = radius(x, y);
            if (r > best.r) best = { x, y, r };
        }
    return best;
}
function resample(points: Point[], n = 64): Point[] {
    if (!points.length) return Array.from({ length: n }, () => [500, 260]);
    const lengths = points.map((p, i) =>
        Math.hypot(
            p[0] - points[(i + 1) % points.length][0],
            p[1] - points[(i + 1) % points.length][1],
        ),
    );
    const total = lengths.reduce((a, b) => a + b, 0);
    return Array.from({ length: n }, (_, i) => {
        let d = (i / n) * total,
            j = 0;
        while (j < lengths.length - 1 && d > lengths[j]) d -= lengths[j++];
        const a = points[j],
            b = points[(j + 1) % points.length],
            t = lengths[j] ? d / lengths[j] : 0;
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    });
}
const pathFor = (p: Point[]) =>
    p.length
        ? `M${p.map((x) => x.map((v) => v.toFixed(2)).join(",")).join("L")}Z`
        : "";
function align(a: Point[], b: Point[]): Point[] {
    let best = 0,
        bestScore = Infinity;
    for (let shift = 0; shift < b.length; shift++) {
        let score = 0;
        for (let i = 0; i < a.length; i += 4) {
            const p = b[(i + shift) % b.length];
            score += (a[i][0] - p[0]) ** 2 + (a[i][1] - p[1]) ** 2;
        }
        if (score < bestScore) {
            bestScore = score;
            best = shift;
        }
    }
    return b.map((_, i) => b[(i + best) % b.length]);
}
export function FoamMap({
    nodes,
    selected,
    onSelect,
    motion,
    period,
}: {
    nodes: MapNode[];
    selected: string | null;
    onSelect: (id: string) => void;
    motion: boolean;
    period: string;
}) {
    const [shapes, setShapes] = useState<Shape[]>([]);
    const [layout, setLayout] = useState<LayoutResult | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const current = useRef<Shape[]>([]);
    const worker = useRef<Worker | null>(null);
    const queue = useRef(
        new LatestQueue<{
            requestId: number;
            nodes: MapNode[];
            period: string;
        }>(),
    );
    const requestId = useRef(0);

    useEffect(() => {
        const requests = queue.current;
        const geometryWorker = new Worker(
            new URL("./geometry.worker.ts", import.meta.url),
            { type: "module" },
        );
        worker.current = geometryWorker;
        geometryWorker.onmessage = (
            event: MessageEvent<GeometryWorkerMessage>,
        ) => {
            const result = event.data;
            const next = requests.complete();
            if ("error" in result) {
                setError(result.error);
            } else {
                setLayout(result);
                setError(null);
            }
            setBusy(next !== null);
            if (next) geometryWorker.postMessage(next);
        };
        geometryWorker.onerror = () => {
            requests.reset();
            setError("版圖計算發生錯誤，請稍後再試。");
            setBusy(false);
        };
        return () => {
            geometryWorker.terminate();
            if (worker.current === geometryWorker) worker.current = null;
            requests.reset();
        };
    }, []);
    useEffect(() => {
        const next = { requestId: ++requestId.current, nodes, period };
        setBusy(true);
        setError(null);
        const geometryWorker = worker.current;
        const ready = queue.current.offer(next);
        if (geometryWorker && ready) geometryWorker.postMessage(ready);
    }, [nodes, period]);
    const target = useMemo(() => {
        if (!layout) return [];
        const nodeById = new Map(layout.nodes.map((node) => [node.id, node]));
        return layout.cells.flatMap((cell) => {
            const node = nodeById.get(cell.id);
            if (!node) return [];
            const points = resample(cell.points);
            return [
                {
                    node,
                    points,
                    path: cell.path,
                    x: cell.x,
                    y: cell.y,
                    area: cell.area,
                    opacity: 1,
                    exiting: false,
                    space: labelSpace(points, cell.x, cell.y),
                },
            ];
        });
    }, [layout]);
    useEffect(() => {
        const reduced =
            !motion ||
            window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (!current.current.length || reduced) {
            current.current = target;
            setShapes(target);
            return;
        }
        const previous = current.current.filter((shape) => !shape.exiting);
        const before = new Map(previous.map((s) => [s.node.id, s]));
        const after = new Set(target.map((s) => s.node.id));
        const transitions: { from: Shape; to: Shape }[] = target.map((t) => {
            const old = before.get(t.node.id);
            const neighbor = previous.find(
                (s) => s.node.group === t.node.group,
            );
            const x = neighbor?.x ?? t.x,
                y = neighbor?.y ?? t.y;
            return {
                from: old ?? {
                    ...t,
                    points: t.points.map(() => [x, y] as Point),
                    x,
                    y,
                    opacity: 0,
                    area: 0,
                    space: { x, y, r: 0 },
                },
                to: old ? { ...t, points: align(old.points, t.points) } : t,
            };
        });
        for (const old of previous)
            if (!after.has(old.node.id))
                transitions.push({
                    from: old,
                    to: {
                        ...old,
                        points: old.points.map(() => [old.x, old.y] as Point),
                        area: 0,
                        opacity: 0,
                        exiting: true,
                        space: { x: old.x, y: old.y, r: 0 },
                    },
                });
        let frame = 0,
            start = 0;
        const tick = (now: number) => {
            if (!start) start = now;
            const t = Math.min(1, (now - start) / 180),
                ease = 1 - (1 - t) ** 3;
            const next = transitions.map(({ from: a, to: b }) => ({
                ...b,
                path: undefined,
                points: b.points.map(
                    (p, i) =>
                        [
                            a.points[i][0] + (p[0] - a.points[i][0]) * ease,
                            a.points[i][1] + (p[1] - a.points[i][1]) * ease,
                        ] as Point,
                ),
                x: a.x + (b.x - a.x) * ease,
                y: a.y + (b.y - a.y) * ease,
                space: {
                    x: a.space.x + (b.space.x - a.space.x) * ease,
                    y: a.space.y + (b.space.y - a.space.y) * ease,
                    r: a.space.r + (b.space.r - a.space.r) * ease,
                },
                burst: b.exiting ? t : undefined,
                area: a.area + (b.area - a.area) * ease,
                opacity: a.opacity + (b.opacity - a.opacity) * ease,
            }));
            current.current = next;
            setShapes(next);
            if (t < 1) frame = requestAnimationFrame(tick);
            else {
                current.current = target;
                setShapes(target);
            }
        };
        frame = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(frame);
    }, [target, motion]);
    return (
        <svg
            className="foam-map"
            viewBox="0 0 1000 550"
            role="group"
            aria-label="市場機會細胞版圖，按 Tab 選取細胞並按 Enter 查看"
            aria-busy={busy}
        >
            <defs>
                <radialGradient id="cell-a" cx="28%" cy="20%" r="85%">
                    <stop offset="0" stopColor="var(--cell-light)" />
                    <stop offset=".68" stopColor="var(--cell-mid)" />
                    <stop offset="1" stopColor="var(--cell-deep)" />
                </radialGradient>
                <radialGradient id="cell-b" cx="26%" cy="20%" r="90%">
                    <stop offset="0" stopColor="var(--cell-warm)" />
                    <stop offset="1" stopColor="var(--cell-mid)" />
                </radialGradient>
            </defs>
            {shapes.map((s, i) => {
                const space = s.space,
                    labelLimit = Math.max(2, Math.floor((space.r * 1.65) / 16)),
                    label =
                        s.node.label.length > labelLimit
                            ? s.node.label.slice(0, labelLimit - 1) + "…"
                            : s.node.label;
                return (
                    <g
                        key={s.node.id}
                        className={`foam-cell${selected === s.node.id ? " selected" : ""}${s.exiting ? " exiting" : ""}`}
                        opacity={s.opacity}
                        role="button"
                        tabIndex={s.exiting || busy || error ? -1 : 0}
                        aria-label={`${s.node.label}，${s.node.gain}，${s.node.detail}`}
                        onClick={() =>
                            !s.exiting && !busy && !error && onSelect(s.node.id)
                        }
                        onKeyDown={(e) => {
                            if (
                                !s.exiting &&
                                !busy &&
                                !error &&
                                (e.key === "Enter" || e.key === " ")
                            ) {
                                e.preventDefault();
                                onSelect(s.node.id);
                            }
                        }}
                    >
                        {s.exiting && (
                            <circle
                                cx={s.x}
                                cy={s.y}
                                r={12 + (s.burst ?? 0) * 48}
                                fill="none"
                                stroke="var(--cell-deep)"
                                strokeWidth="1.5"
                                strokeDasharray="5 8"
                                pointerEvents="none"
                            />
                        )}
                        <title>
                            {s.node.label} · {s.node.gain} · {s.node.detail}
                        </title>
                        <path
                            d={s.path ?? pathFor(s.points)}
                            fill={`url(#cell-${i % 4 === 0 ? "b" : "a"})`}
                            stroke="var(--membrane)"
                            strokeWidth="3"
                            strokeLinejoin="round"
                        />
                        {space.r > 58 && (
                            <text
                                x={space.x}
                                y={space.y - 12}
                                textAnchor="middle"
                                pointerEvents="none"
                            >
                                <tspan className="cell-label" x={space.x}>
                                    {label}
                                </tspan>
                                <tspan
                                    className="cell-gain"
                                    x={space.x}
                                    dy="29"
                                >
                                    {s.node.gain}
                                </tspan>
                                {space.r > 80 && (
                                    <tspan
                                        className="cell-detail"
                                        x={space.x}
                                        dy="24"
                                    >
                                        {s.node.detail}
                                    </tspan>
                                )}
                            </text>
                        )}
                        {space.r > 20 && space.r <= 58 && (
                            <text
                                className="cell-small"
                                x={space.x}
                                y={space.y + 5}
                                textAnchor="middle"
                                pointerEvents="none"
                            >
                                {label}
                            </text>
                        )}
                    </g>
                );
            })}
            {!shapes.length && !busy && !error && (
                <text x="500" y="275" textAnchor="middle" className="map-empty">
                    這個區間沒有符合條件的上漲細胞
                </text>
            )}
            <text
                className="map-status"
                x="500"
                y="542"
                textAnchor="middle"
                role="status"
                aria-live="polite"
            >
                {busy
                    ? `更新中${layout ? ` · 圖形目前為 ${layout.period}` : ""}`
                    : error
                      ? `市場版圖無法更新：${error}`
                      : ""}
            </text>
        </svg>
    );
}
