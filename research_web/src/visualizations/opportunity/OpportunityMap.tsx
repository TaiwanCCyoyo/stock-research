import {
    useEffect,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import type { PortfolioComparison } from "../../domain/opportunities/types.ts";
import {
    sameSource,
    hasMapIndustry,
    mapGroupId,
    mapIndustries,
    endedBurst,
    gainColorBand,
    groupLabelFits,
    overviewIndustryLabels,
    industryMetricLabel,
    metricLabel,
    showPeakAreaReference,
    visiblePackingPositions,
} from "./mapTypes.ts";
import type { MapView, MapRow, GroupingMode, ColorBasis } from "./mapTypes.ts";
import { LatestQueue } from "../atlas/latestQueue.ts";
import { classificationLabel } from "../../features/opportunities/classificationDisplay.ts";
import {
    DEFAULT_CAMERA,
    WORLD_WIDTH as BASE_WIDTH,
    WORLD_HEIGHT as BASE_HEIGHT,
    gestureCamera,
    fitBoundsCamera,
    initialOverview,
    isDefaultCamera,
    wheelZoomFactor,
    zoomCameraAt,
    type Camera,
    type ScreenPoint,
} from "./camera.ts";
import type { PackedGroup, PackedNode, PackingLayout } from "./packing.ts";
import type { PackingRequest, PackingResponse } from "./packing.worker.ts";
import "./OpportunityMap.css";

/** One fixed world scale, calibrated against the full synthetic calendar; never fitted per date. */
export const OPPORTUNITY_RADIUS_SCALE = 30;
const DURATION = 260;
const phaseLabel = {
    slow: "持續上漲",
    rising: "持續上漲",
    resting: "漲多休息",
    retreat: "從高點拉回",
};
const gainLabel = (value: number | null) =>
    value === null ? "不知道" : `${value >= 0 ? "+" : ""}${value.toFixed(0)}%`;
const shareLabel = (value: number | null) =>
    value === null ? "無法計算" : `${(value * 100).toFixed(0)}%`;
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const angleFor = (id: string) =>
    ([...id].reduce(
        (sum, letter) => (sum * 31 + letter.charCodeAt(0)) >>> 0,
        0,
    ) /
        0x100000000) *
    Math.PI *
    2;
const stockFont = (radius: number, minimum: number) =>
    Math.min(minimum * 1.25, Math.max(minimum, radius / 3.5));
const labelFits = (row: MapRow, radius: number, fontSize: number) => {
    const letters = [...row.security.name].reduce(
        (width, letter) => width + (letter.charCodeAt(0) <= 255 ? 0.6 : 1),
        0,
    );
    return radius >= fontSize * Math.max(2.2, letters / 2 + 0.5);
};

export interface OpportunityMapProps {
    view: MapView;
    comparisons: PortfolioComparison[];
    selectedSecurityId: string | null;
    selectedWaveId?: string | null;
    onSelect: (id: string) => void;
    reducedMotion: boolean;
    showComparisonDots?: boolean;
    groupingMode?: GroupingMode;
    colorBasis?: ColorBasis;
}

type Snapshot = {
    requestId: number;
    view: MapView;
    comparisons: PortfolioComparison[];
    groupingMode: GroupingMode;
};
type Result = { snapshot: Snapshot; layout: PackingLayout };
type Pose = { x: number; y: number; r: number; opacity: number };
type StockTransition = {
    node: PackedNode;
    row: MapRow;
    from: Pose;
    to: Pose;
    body: PackedNode;
    exiting: boolean;
    burst: boolean;
};
type GroupTransition = {
    group: PackedGroup;
    from: Pose;
    to: Pose;
    exiting: boolean;
    decorative: boolean;
};
type Frame = Result & { stocks: StockTransition[]; groups: GroupTransition[] };
type StockRefs = {
    root: SVGGElement | null;
    body: SVGPathElement | null;
    label: SVGGElement | null;
};

function description(row: MapRow, date: string): string {
    const growth =
        row.displayMetric === undefined
            ? ""
            : `；${metricLabel(row.displayMetric)}`;
    return `${row.security.name}（${row.security.code}），${classificationLabel(row)}。${date}：總漲幅 ${gainLabel(row.gain)}${growth}${row.phase === null ? "" : `，${phaseLabel[row.phase]}`}。這波開始：${row.wave.start}；開始大漲：${row.wave.launch?.date ?? "不知道"}；${row.wave.endConfirmedAt ? `事後確認結束：${row.wave.endConfirmedAt}` : `尚未確認結束，資料觀察至 ${row.wave.observedThrough}`}。`;
}

function rowGainColor(row: MapRow): ReturnType<typeof gainColorBand> {
    return row.displayMetric === undefined
        ? gainColorBand(row.gain)
        : gainColorBand(row.displayMetric.gain);
}

function makeFrame(
    result: Result,
    previous: Frame | null,
    current: Map<string, Pose>,
    groupCurrent: Map<string, Pose>,
): Frame {
    const related = sameSource(previous?.snapshot.view, result.snapshot.view);
    const old = new Map(
        (related
            ? (previous?.stocks.filter((item) => !item.exiting) ?? [])
            : []
        ).map((item) => [item.node.id, item]),
    );
    const rows = new Map(
        result.snapshot.view.active.map((row) => [row.security.id, row]),
    );
    const groups = new Map(
        result.layout.groups.map((group) => [group.id, group]),
    );
    const stocks: StockTransition[] = result.layout.nodes.flatMap((node) => {
        const row = rows.get(node.id);
        if (!row) return [];
        const existing = old.get(node.id);
        const group = groups.get(node.groupId)!;
        const angle = angleFor(node.id);
        const to = { x: node.x, y: node.y, r: node.r, opacity: 1 };
        const from = existing
            ? (current.get(node.id) ?? existing.to)
            : {
                  x: group.x + Math.cos(angle) * (group.r + 12),
                  y: group.y + Math.sin(angle) * (group.r + 12),
                  r: 0,
                  opacity: 0,
              };
        return [
            {
                node,
                row,
                from,
                to,
                body: node.r === 0 && existing ? existing.node : node,
                exiting: false,
                burst: false,
            },
        ];
    });
    const present = new Set(result.layout.nodes.map((node) => node.id));
    for (const [id, item] of old) {
        if (present.has(id)) continue;
        const from = current.get(id) ?? item.to;
        const burst = endedBurst(
            previous!.snapshot.view,
            result.snapshot.view,
            item.row,
        );
        stocks.push({
            ...item,
            from,
            to: { ...from, r: 0, opacity: 0 },
            exiting: true,
            burst,
        });
    }
    const oldGroups = new Map(
        (related
            ? (previous?.groups.filter((item) => !item.exiting) ?? [])
            : []
        ).map((item) => [item.group.id, item]),
    );
    const groupTransitions: GroupTransition[] = result.layout.groups.map(
        (group) => {
            const previousGroup = oldGroups.get(group.id);
            const to = { x: group.x, y: group.y, r: group.r, opacity: 1 };
            return {
                group,
                decorative: group.nodeIds.some((id) => {
                    const row = rows.get(id);
                    return row
                        ? hasMapIndustry(row, result.snapshot.groupingMode)
                        : false;
                }),
                to,
                from: previousGroup
                    ? (groupCurrent.get(group.id) ?? previousGroup.to)
                    : { ...to, r: group.r * 0.8, opacity: 0 },
                exiting: false,
            };
        },
    );
    for (const [id, item] of oldGroups) {
        if (groups.has(id)) continue;
        const from = groupCurrent.get(id) ?? item.to;
        groupTransitions.push({
            ...item,
            from,
            to: { ...from, opacity: 0 },
            exiting: true,
        });
    }
    return { ...result, stocks, groups: groupTransitions };
}

export function OpportunityMap({
    view,
    comparisons,
    selectedSecurityId,
    selectedWaveId,
    onSelect,
    reducedMotion,
    showComparisonDots = false,
    groupingMode = "historical",
    colorBasis = "phase",
}: OpportunityMapProps) {
    const uid = `opportunity-${useId().replace(/:/g, "")}`;
    const [result, setResult] = useState<Result | null>(null);
    const [frame, setFrame] = useState<Frame | null>(null);
    const [busy, setBusy] = useState(true);
    const [error, setError] = useState(false);
    const [systemReduced, setSystemReduced] = useState(false);
    const [animating, setAnimating] = useState(false);
    const [camera, setCamera] = useState<Camera>({ ...DEFAULT_CAMERA });
    const overviewState = useRef({
        camera: { ...DEFAULT_CAMERA } as Camera,
        initialized: false,
    });
    const [pixelWidth, setPixelWidth] = useState(1000);
    const surface = useRef<HTMLDivElement | null>(null);
    const mapElement = useRef<SVGSVGElement | null>(null);
    const worker = useRef<Worker | null>(null);
    const queue = useRef(new LatestQueue<Snapshot>());
    const active = useRef<Snapshot | null>(null);
    const completed = useRef<Result | null>(null);
    const sequence = useRef(0);
    const comparisonRef = useRef(comparisons);
    const frameRef = useRef<Frame | null>(null);
    const poses = useRef(new Map<string, Pose>());
    const groupPoses = useRef(new Map<string, Pose>());
    const stockElements = useRef(new Map<string, StockRefs>());
    const groupElements = useRef(new Map<string, SVGGElement>());
    const groupLabelElements = useRef(new Map<string, SVGTextElement>());
    const particleElements = useRef(new Map<string, SVGCircleElement>());
    const pointers = useRef(new Map<number, ScreenPoint>());
    const suppressClick = useRef(false);
    const dispatch = useRef<(snapshot: Snapshot) => void>(() => {});
    comparisonRef.current = comparisons;
    const motionOff = reducedMotion || systemReduced;

    useEffect(() => {
        const media = window.matchMedia("(prefers-reduced-motion: reduce)");
        const update = () => setSystemReduced(media.matches);
        update();
        media.addEventListener("change", update);
        return () => media.removeEventListener("change", update);
    }, []);

    useEffect(() => {
        if (!surface.current) return;
        const observer = new ResizeObserver((entries) =>
            setPixelWidth(entries[0]?.contentRect.width || 1000),
        );
        observer.observe(surface.current);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        const element = mapElement.current;
        if (!element) return;
        const wheel = (event: WheelEvent) => {
            const rect = element.getBoundingClientRect();
            const factor = wheelZoomFactor(event, rect.height);
            if (factor === null) return;
            event.preventDefault();
            setCamera((old) =>
                zoomCameraAt(old, factor, rect, {
                    x: event.clientX - rect.left,
                    y: event.clientY - rect.top,
                }),
            );
        };
        element.addEventListener("wheel", wheel, { passive: false });
        return () => element.removeEventListener("wheel", wheel);
    }, []);

    useEffect(() => {
        const requests = queue.current;
        const geometryWorker = new Worker(
            new URL("./packing.worker.ts", import.meta.url),
            { type: "module" },
        );
        worker.current = geometryWorker;
        dispatch.current = (snapshot) => {
            active.current = snapshot;
            const old = completed.current;
            const knownGroups = new Set(
                snapshot.view.active
                    .filter((row) => hasMapIndustry(row, snapshot.groupingMode))
                    .map((row) => row.industry.id),
            );
            const request: PackingRequest = {
                requestId: snapshot.requestId,
                date: snapshot.view.date,
                input: {
                    nodes: snapshot.view.active.map((row) => ({
                        id: row.security.id,
                        groupId: mapGroupId(
                            row,
                            snapshot.groupingMode,
                            knownGroups,
                        ),
                        weight: row.weight,
                    })),
                    globalRadiusScale: OPPORTUNITY_RADIUS_SCALE,
                    previous:
                        old && sameSource(old.snapshot.view, snapshot.view)
                            ? visiblePackingPositions(old.layout.nodes)
                            : [],
                    gap: 2,
                    groupGap: 12,
                    outlinePadding: 8,
                },
            };
            geometryWorker.postMessage(request);
        };
        geometryWorker.onmessage = (event: MessageEvent<PackingResponse>) => {
            const snapshot = active.current;
            if (
                !snapshot ||
                event.data.requestId !== snapshot.requestId ||
                event.data.date !== snapshot.view.date
            )
                return;
            if ("error" in event.data) setError(true);
            else {
                const accepted = { snapshot, layout: event.data.layout };
                completed.current = accepted;
                setResult(accepted);
                setError(false);
            }
            const next = requests.complete();
            active.current = null;
            setBusy(next !== null);
            if (next) dispatch.current(next);
        };
        geometryWorker.onerror = () => {
            requests.reset();
            active.current = null;
            setBusy(false);
            setError(true);
        };
        return () => {
            requests.reset();
            geometryWorker.terminate();
            worker.current = null;
            active.current = null;
        };
    }, []);

    useEffect(() => {
        const snapshot = {
            requestId: ++sequence.current,
            view,
            comparisons: comparisonRef.current,
            groupingMode,
        };
        setBusy(true);
        setError(false);
        const ready = queue.current.offer(snapshot);
        if (ready && worker.current) dispatch.current(ready);
    }, [view, groupingMode]);

    useLayoutEffect(() => {
        if (!result) return;
        const next = makeFrame(
            result,
            frameRef.current,
            poses.current,
            groupPoses.current,
        );
        frameRef.current = next;
        setFrame(next);
    }, [result]);

    useLayoutEffect(() => {
        if (!frame) return;
        const next = initialOverview(
            overviewState.current,
            frame.layout.bounds,
            frame.layout.nodes.some((node) => node.r > 0),
        );
        if (next !== overviewState.current) {
            overviewState.current = next;
            setCamera(next.camera);
        }
    }, [frame]);

    const worldFont = Math.max(
        12,
        (12 * BASE_WIDTH) / (pixelWidth * camera.zoom),
    );
    const labelFontRef = useRef(worldFont);
    labelFontRef.current = worldFont;
    useLayoutEffect(() => {
        if (!frame) return;
        let raf = 0;
        const start = performance.now();
        const apply = (fraction: number) => {
            const eased = 1 - (1 - fraction) ** 3;
            for (const item of frame.stocks) {
                const { node, from, to, body } = item;
                const pose = {
                    x: mix(from.x, to.x, eased),
                    y: mix(from.y, to.y, eased),
                    r: mix(from.r, to.r, eased),
                    opacity: mix(from.opacity, to.opacity, eased),
                };
                poses.current.set(node.id, pose);
                const refs = stockElements.current.get(node.id);
                refs?.root?.setAttribute(
                    "transform",
                    `translate(${pose.x - node.x} ${pose.y - node.y})`,
                );
                refs?.root?.setAttribute(
                    "opacity",
                    String(
                        item.burst
                            ? pose.opacity * (1 - fraction)
                            : pose.opacity,
                    ),
                );
                if (refs?.body) {
                    const scale = body.r > 0 ? pose.r / body.r : 1;
                    refs.body.setAttribute(
                        "transform",
                        `translate(${node.x} ${node.y}) scale(${scale}) translate(${-body.x} ${-body.y})`,
                    );
                    if (fraction === 1) {
                        refs.body.setAttribute("d", node.path);
                        refs.body.removeAttribute("transform");
                    }
                }
                refs?.label?.setAttribute(
                    "opacity",
                    labelFits(
                        item.row,
                        pose.r,
                        stockFont(node.r, labelFontRef.current),
                    )
                        ? "1"
                        : "0",
                );
                if (item.burst) {
                    for (let i = 0; i < 5; i++) {
                        const particle = particleElements.current.get(
                            `${node.id}-${i}`,
                        );
                        if (!particle) continue;
                        const angle = angleFor(node.id) + (i * Math.PI * 2) / 5;
                        const travel =
                            (8 + Math.min(30, from.r) + i * 2) * eased;
                        particle.setAttribute(
                            "cx",
                            String(from.x + Math.cos(angle) * travel),
                        );
                        particle.setAttribute(
                            "cy",
                            String(from.y + Math.sin(angle) * travel),
                        );
                        particle.setAttribute(
                            "opacity",
                            String(Math.sin(Math.PI * fraction) * 0.55),
                        );
                    }
                }
            }
            for (const item of frame.groups) {
                const { from, to, group } = item;
                const pose = {
                    x: mix(from.x, to.x, eased),
                    y: mix(from.y, to.y, eased),
                    r: mix(from.r, to.r, eased),
                    opacity: mix(from.opacity, to.opacity, eased),
                };
                groupPoses.current.set(group.id, pose);
                const scale = group.r > 0 ? pose.r / group.r : 1;
                const element = groupElements.current.get(group.id);
                const transform = `translate(${pose.x} ${pose.y}) scale(${scale}) translate(${-group.x} ${-group.y})`;
                element?.setAttribute("transform", transform);
                element?.setAttribute("opacity", String(pose.opacity));
                groupLabelElements.current
                    .get(group.id)
                    ?.setAttribute("transform", transform);
                groupLabelElements.current
                    .get(group.id)
                    ?.setAttribute("opacity", String(pose.opacity));
            }
        };
        const finish = () => {
            setAnimating(false);
            const keptStocks = new Set(
                frame.stocks
                    .filter((item) => !item.exiting)
                    .map((item) => item.node.id),
            );
            const keptGroups = new Set(
                frame.groups
                    .filter((item) => !item.exiting)
                    .map((item) => item.group.id),
            );
            for (const id of poses.current.keys())
                if (!keptStocks.has(id)) poses.current.delete(id);
            for (const id of groupPoses.current.keys())
                if (!keptGroups.has(id)) groupPoses.current.delete(id);
            for (const [id, refs] of stockElements.current)
                if (!refs.root) stockElements.current.delete(id);
        };
        if (motionOff) {
            apply(1);
            finish();
            return;
        }
        setAnimating(true);
        apply(0);
        const tick = (now: number) => {
            const fraction = Math.min(1, (now - start) / DURATION);
            apply(fraction);
            if (fraction < 1) raf = requestAnimationFrame(tick);
            else finish();
        };
        raf = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(raf);
    }, [frame, motionOff]);

    const renderedView = frame?.snapshot.view;
    const stale =
        !renderedView ||
        renderedView.date !== view.date ||
        !sameSource(renderedView, view) ||
        frame?.snapshot.groupingMode !== groupingMode;
    const locked = busy || stale || error;
    const shownComparisons = useMemo(() => {
        if (!frame) return [];
        const values = !stale ? comparisons : frame.snapshot.comparisons;
        return values
            .filter(
                (comparison) => comparison.date === frame.snapshot.view.date,
            )
            .slice(0, 4);
    }, [frame, stale, comparisons]);
    const participation = useMemo(
        () =>
            shownComparisons.map(
                (comparison) =>
                    new Map(
                        comparison.stocks.map((stock) => [
                            stock.securityId,
                            stock,
                        ]),
                    ),
            ),
        [shownComparisons],
    );
    const industries = useMemo(
        () =>
            new Map(
                (renderedView
                    ? mapIndustries(renderedView, frame!.snapshot.groupingMode)
                    : []
                ).map((industry) => [industry.id, industry]),
            ),
        [renderedView, frame],
    );
    const overviewLabels = useMemo(() => {
        if (!frame || !overviewState.current.initialized) return [];
        const baselineZoom = overviewState.current.camera.zoom;
        if (camera.zoom > baselineZoom * 1.25) return [];
        return overviewIndustryLabels(
            frame.layout.groups,
            industries,
            camera,
            worldFont,
        );
    }, [frame, industries, camera, worldFont]);
    const stockRef = (id: string) => {
        let refs = stockElements.current.get(id);
        if (!refs) {
            refs = { root: null, body: null, label: null };
            stockElements.current.set(id, refs);
        }
        return refs;
    };
    const select = (id: string) => {
        if (!locked) onSelect(id);
    };
    const zoom = (factor: number) => {
        const viewport = mapElement.current?.getBoundingClientRect();
        if (viewport) setCamera((old) => zoomCameraAt(old, factor, viewport));
    };
    const pan = (x: number, y: number) =>
        setCamera((old) => ({
            ...old,
            x: old.x + x / old.zoom,
            y: old.y + y / old.zoom,
        }));
    const mapKey = (event: KeyboardEvent<SVGSVGElement>) => {
        const directions: Record<string, [number, number]> = {
            ArrowLeft: [-70, 0],
            ArrowRight: [70, 0],
            ArrowUp: [0, -70],
            ArrowDown: [0, 70],
        };
        if (directions[event.key]) {
            event.preventDefault();
            pan(...directions[event.key]);
        }
        if (event.key === "+" || event.key === "=") {
            event.preventDefault();
            zoom(1.25);
        }
        if (event.key === "-") {
            event.preventDefault();
            zoom(0.8);
        }
    };
    const pointerDown = (event: PointerEvent<SVGSVGElement>) => {
        if (event.button !== 0) return;
        if (pointers.current.size === 0) suppressClick.current = false;
        else suppressClick.current = true;
        pointers.current.set(event.pointerId, {
            x: event.clientX,
            y: event.clientY,
        });
        // Capture on the original stock/path so a stationary tap still selects it.
        (event.target as Element).setPointerCapture(event.pointerId);
    };
    const pointerMove = (event: PointerEvent<SVGSVGElement>) => {
        const previousPoint = pointers.current.get(event.pointerId);
        if (!previousPoint) return;
        if (
            !suppressClick.current &&
            Math.hypot(
                event.clientX - previousPoint.x,
                event.clientY - previousPoint.y,
            ) < 4
        )
            return;
        suppressClick.current = true;
        const rect = event.currentTarget.getBoundingClientRect();
        const local = (point: ScreenPoint) => ({
            x: point.x - rect.left,
            y: point.y - rect.top,
        });
        const before = [...pointers.current.values()].map(local);
        pointers.current.set(event.pointerId, {
            x: event.clientX,
            y: event.clientY,
        });
        const after = [...pointers.current.values()].map(local);
        setCamera((old) => gestureCamera(old, before, after, rect));
    };
    const pointerEnd = (event: PointerEvent<SVGSVGElement>) => {
        pointers.current.delete(event.pointerId);
        const target = event.target as Element;
        if (target.hasPointerCapture(event.pointerId))
            target.releasePointerCapture(event.pointerId);
    };
    const overflow =
        !!frame &&
        (frame.layout.bounds.minX < camera.x - 500 / camera.zoom ||
            frame.layout.bounds.maxX > camera.x + 500 / camera.zoom ||
            frame.layout.bounds.minY < camera.y - 310 / camera.zoom ||
            frame.layout.bounds.maxY > camera.y + 310 / camera.zoom);
    const selectedRow = renderedView?.active.find(
        (row) =>
            row.security.id === selectedSecurityId &&
            (selectedWaveId === undefined || row.wave.id === selectedWaveId),
    );

    return (
        <section
            className="opportunity-map"
            aria-label="股票地圖"
            data-reduced-motion={motionOff || undefined}
        >
            <div className="opportunity-map-surface" ref={surface}>
                {!error && (locked || animating) && (
                    <p className="opportunity-map-updating" role="status">
                        {frame && frame.snapshot.view.date !== view.date
                            ? `版圖仍為 ${frame.snapshot.view.date}，正在畫出 ${view.date}`
                            : "更新中"}
                    </p>
                )}
                <svg
                    ref={mapElement}
                    className="opportunity-map-svg"
                    viewBox={`${camera.x - 500 / camera.zoom} ${camera.y - 310 / camera.zoom} ${BASE_WIDTH / camera.zoom} ${BASE_HEIGHT / camera.zoom}`}
                    role="group"
                    aria-label="可選取股票的地圖；拖曳平移，Ctrl 或 Command 加滾輪及雙指縮放；方向鍵平移，加減鍵縮放"
                    aria-busy={locked}
                    tabIndex={0}
                    onKeyDown={mapKey}
                    onPointerDown={pointerDown}
                    onPointerMove={pointerMove}
                    onPointerUp={pointerEnd}
                    onPointerCancel={pointerEnd}
                    onLostPointerCapture={pointerEnd}
                    onClickCapture={(event) => {
                        if (!suppressClick.current || event.detail === 0)
                            return;
                        event.preventDefault();
                        event.stopPropagation();
                    }}
                >
                    <defs>
                        {(
                            [
                                ["strong", "var(--cell-deep)"],
                                ["medium", "var(--cell-mid)"],
                                ["light", "var(--cell-light)"],
                                ["unknown", "var(--muted)"],
                            ] as const
                        ).map(([band, color]) => (
                            <radialGradient
                                key={band}
                                id={`${uid}-gain-${band}`}
                                cx=".32"
                                cy=".25"
                                r=".9"
                            >
                                <stop
                                    offset="0"
                                    stopColor={
                                        band === "unknown"
                                            ? "var(--surface)"
                                            : "var(--cell-light)"
                                    }
                                />
                                <stop offset=".7" stopColor={color} />
                                <stop offset="1" stopColor={color} />
                            </radialGradient>
                        ))}
                        <radialGradient
                            id={`${uid}-rising`}
                            cx=".32"
                            cy=".25"
                            r=".9"
                        >
                            <stop offset="0" stopColor="var(--cell-light)" />
                            <stop offset=".7" stopColor="var(--cell-mid)" />
                            <stop offset="1" stopColor="var(--cell-deep)" />
                        </radialGradient>
                        <radialGradient
                            id={`${uid}-slow`}
                            cx=".32"
                            cy=".25"
                            r=".9"
                        >
                            <stop offset="0" stopColor="var(--surface)" />
                            <stop offset="1" stopColor="var(--cell-light)" />
                        </radialGradient>
                        <radialGradient id={`${uid}-resting`} cx=".3" cy=".2">
                            <stop stopColor="var(--cell-light)" />
                            <stop offset="1" stopColor="var(--cell-warm)" />
                        </radialGradient>
                        <radialGradient id={`${uid}-retreat`} cx=".3" cy=".2">
                            <stop stopColor="var(--cell-light)" />
                            <stop offset="1" stopColor="var(--muted)" />
                        </radialGradient>
                        <radialGradient id={`${uid}-unmarked`} cx=".3" cy=".2">
                            <stop stopColor="var(--surface)" />
                            <stop
                                offset="1"
                                stopColor="var(--muted)"
                                stopOpacity=".5"
                            />
                        </radialGradient>
                        <pattern
                            id={`${uid}-unknown`}
                            width="8"
                            height="8"
                            patternUnits="userSpaceOnUse"
                            patternTransform="rotate(35)"
                        >
                            <rect
                                width="8"
                                height="8"
                                fill="var(--cell-light)"
                                fillOpacity=".35"
                            />
                            <path
                                d="M0 0V8"
                                stroke="var(--muted)"
                                strokeWidth="2"
                                opacity=".55"
                            />
                        </pattern>
                    </defs>
                    <g className="opportunity-industries" aria-hidden="true">
                        {frame?.groups
                            .filter((item) => item.decorative)
                            .map((item) => {
                                const group = item.group;
                                const territoryColor = [
                                    "var(--cell-deep)",
                                    "var(--cell-mid)",
                                    "var(--cell-warm)",
                                ][
                                    Math.floor(
                                        (angleFor(group.id) / (Math.PI * 2)) *
                                            3,
                                    )
                                ];
                                return (
                                    <g
                                        key={group.id}
                                        ref={(element) => {
                                            if (element)
                                                groupElements.current.set(
                                                    group.id,
                                                    element,
                                                );
                                            else
                                                groupElements.current.delete(
                                                    group.id,
                                                );
                                        }}
                                    >
                                        <path
                                            className="opportunity-industry-ground"
                                            d={group.path}
                                            fill={territoryColor}
                                            fillOpacity=".38"
                                            stroke={territoryColor}
                                            strokeOpacity=".18"
                                            strokeWidth="18"
                                            vectorEffect="non-scaling-stroke"
                                        />
                                        <path
                                            className="opportunity-industry-boundary"
                                            d={group.path}
                                            fill="none"
                                            stroke="var(--membrane)"
                                            strokeOpacity=".56"
                                            strokeWidth="1.5"
                                            vectorEffect="non-scaling-stroke"
                                        />
                                    </g>
                                );
                            })}
                    </g>
                    <g className="opportunity-stocks">
                        {frame?.stocks.map((item) => {
                            const { node, row } = item;
                            const selected =
                                selectedSecurityId === node.id &&
                                (selectedWaveId === undefined ||
                                    row.wave.id === selectedWaveId) &&
                                !item.exiting;
                            const singleShare =
                                participation[0]?.get(node.id)
                                    ?.positiveMoveShare ?? null;
                            const held =
                                participation[0]?.get(node.id)?.held ??
                                "unknown";
                            const phase =
                                row.phase === null ? "unmarked" : row.phase;
                            const fill =
                                shownComparisons.length === 1
                                    ? singleShare === null
                                        ? held === "held"
                                            ? "var(--compare-1)"
                                            : held === "not-held"
                                              ? "var(--surface)"
                                              : `url(#${uid}-unknown)`
                                        : "var(--compare-1)"
                                    : `url(#${uid}-${colorBasis === "gain" ? `gain-${rowGainColor(row)}` : phase})`;
                            const opacity =
                                shownComparisons.length === 1 &&
                                singleShare !== null
                                    ? 0.18 +
                                      0.82 *
                                          Math.max(0, Math.min(1, singleShare))
                                    : 0.9;
                            const label = description(
                                row,
                                frame.snapshot.view.date,
                            );
                            const peakR =
                                !showPeakAreaReference(row) ||
                                row.peakGain === null
                                    ? null
                                    : (Math.max(0, row.peakGain) / 100) *
                                      OPPORTUNITY_RADIUS_SCALE;
                            const fontSize = stockFont(node.r, worldFont);
                            return (
                                <g
                                    key={node.id}
                                    ref={(element) => {
                                        stockRef(node.id).root = element;
                                    }}
                                    className={`opportunity-stock${selected ? " is-selected" : ""}`}
                                    role={item.exiting ? undefined : "button"}
                                    tabIndex={item.exiting ? -1 : 0}
                                    aria-hidden={item.exiting || undefined}
                                    aria-label={label}
                                    aria-pressed={selected}
                                    aria-disabled={locked || undefined}
                                    onClick={() => {
                                        if (!item.exiting) select(node.id);
                                    }}
                                    onKeyDown={(event) => {
                                        if (
                                            event.key === "Enter" ||
                                            event.key === " "
                                        ) {
                                            event.preventDefault();
                                            event.stopPropagation();
                                            if (!item.exiting) select(node.id);
                                        }
                                    }}
                                >
                                    <title>
                                        {label}
                                        {shownComparisons
                                            .map((comparison, i) =>
                                                participation[i]?.get(node.id)
                                                    ?.positiveMoveShare === null
                                                    ? ` ${comparison.portfolio.name}：${participation[i]?.get(node.id)?.held === "held" ? "當日有持有證據" : participation[i]?.get(node.id)?.held === "not-held" ? "當日未持有" : "持股資料未知"}；完整行情收益尚待核對。`
                                                    : ` ${comparison.portfolio.name}：持股日上漲占比 ${shareLabel(participation[i]?.get(node.id)?.positiveMoveShare ?? null)}；不代表實際報酬。`,
                                            )
                                            .join("")}
                                    </title>
                                    <path
                                        ref={(element) => {
                                            stockRef(node.id).body = element;
                                        }}
                                        d={item.body.path}
                                        fill={fill}
                                        fillOpacity={opacity}
                                        stroke={
                                            selected
                                                ? "var(--ink)"
                                                : "var(--membrane)"
                                        }
                                        strokeWidth={selected ? 2.2 : 1.1}
                                        strokeDasharray={
                                            shownComparisons.length === 1 &&
                                            singleShare === 0
                                                ? "4 3"
                                                : undefined
                                        }
                                        vectorEffect="non-scaling-stroke"
                                    />
                                    {node.r < 2 && !item.exiting && (
                                        <circle
                                            cx={node.x}
                                            cy={node.y}
                                            r={worldFont * 0.32}
                                            className="opportunity-zero-marker"
                                        >
                                            <title>
                                                漲幅面積太小，以虛線標記位置；標記不代表面積。
                                            </title>
                                        </circle>
                                    )}
                                    {selected && peakR !== null && (
                                        <circle
                                            cx={node.x}
                                            cy={node.y}
                                            r={peakR}
                                            className="opportunity-peak-ring"
                                        >
                                            <title>
                                                {row.wave.rightCensored
                                                    ? "截至快照最高"
                                                    : "事後參考：這波最高"}{" "}
                                                {gainLabel(row.peakGain)}
                                                ，虛線是等效面積參考。
                                            </title>
                                        </circle>
                                    )}
                                    <g
                                        ref={(element) => {
                                            stockRef(node.id).label = element;
                                        }}
                                        className="opportunity-stock-label"
                                        opacity={
                                            labelFits(row, node.r, fontSize)
                                                ? 1
                                                : 0
                                        }
                                        fontSize={fontSize}
                                    >
                                        <text
                                            x={node.x}
                                            y={node.y - fontSize * 0.14}
                                            textAnchor="middle"
                                        >
                                            {row.security.name}
                                        </text>
                                        <text
                                            x={node.x}
                                            y={node.y + fontSize * 1.1}
                                            textAnchor="middle"
                                            className="opportunity-stock-gain"
                                        >
                                            {row.displayMetric === undefined
                                                ? gainLabel(row.gain)
                                                : metricLabel(
                                                      row.displayMetric,
                                                  )}
                                        </text>
                                    </g>
                                    {shownComparisons.length > 1 &&
                                        showComparisonDots &&
                                        !item.exiting && (
                                            <g className="opportunity-comparison-dots">
                                                {shownComparisons.map(
                                                    (comparison, index) => {
                                                        const share =
                                                            participation[
                                                                index
                                                            ]?.get(node.id)
                                                                ?.positiveMoveShare ??
                                                            null;
                                                        const held =
                                                            participation[
                                                                index
                                                            ]?.get(node.id)
                                                                ?.held ??
                                                            "unknown";
                                                        return (
                                                            <circle
                                                                key={
                                                                    comparison
                                                                        .portfolio
                                                                        .id
                                                                }
                                                                cx={
                                                                    node.x +
                                                                    (index -
                                                                        (shownComparisons.length -
                                                                            1) /
                                                                            2) *
                                                                        worldFont *
                                                                        0.75
                                                                }
                                                                cy={
                                                                    node.y -
                                                                    node.outerRadius -
                                                                    worldFont *
                                                                        0.5
                                                                }
                                                                r={
                                                                    worldFont *
                                                                    0.23
                                                                }
                                                                fill={
                                                                    share ===
                                                                        null &&
                                                                    held !==
                                                                        "held"
                                                                        ? "none"
                                                                        : `var(--compare-${index + 1})`
                                                                }
                                                                fillOpacity={
                                                                    share ===
                                                                    null
                                                                        ? held ===
                                                                          "held"
                                                                            ? 0.9
                                                                            : 0
                                                                        : 0.25 +
                                                                          0.75 *
                                                                              share
                                                                }
                                                                stroke={`var(--compare-${index + 1})`}
                                                                strokeDasharray={
                                                                    share ===
                                                                        null &&
                                                                    held ===
                                                                        "unknown"
                                                                        ? "2 2"
                                                                        : undefined
                                                                }
                                                            >
                                                                <title>
                                                                    {
                                                                        comparison
                                                                            .portfolio
                                                                            .name
                                                                    }
                                                                    {share ===
                                                                    null
                                                                        ? `：${held === "held" ? "當日有持有證據" : held === "not-held" ? "當日未持有" : "當日持股未知"}；整波收益尚未比較`
                                                                        : `：持股日上漲占比 ${shareLabel(share)}`}
                                                                </title>
                                                            </circle>
                                                        );
                                                    },
                                                )}
                                            </g>
                                        )}
                                </g>
                            );
                        })}
                    </g>
                    <g
                        className="opportunity-industry-labels"
                        aria-hidden="true"
                    >
                        {frame?.groups
                            .filter((item) => item.decorative && !item.exiting)
                            .map(({ group }) => {
                                const industry = industries.get(group.id);
                                if (!industry || overviewLabels.length > 0)
                                    return null;
                                if (
                                    renderedView?.catalogId &&
                                    !groupLabelFits(
                                        industryMetricLabel(industry),
                                        group.r,
                                        worldFont,
                                        shownComparisons.length + 1,
                                    )
                                )
                                    return null;
                                const bottom = Math.max(
                                    ...group.points.map((p) => p.y),
                                );
                                return (
                                    <text
                                        key={group.id}
                                        ref={(element) => {
                                            if (element)
                                                groupLabelElements.current.set(
                                                    group.id,
                                                    element,
                                                );
                                            else
                                                groupLabelElements.current.delete(
                                                    group.id,
                                                );
                                        }}
                                        x={group.x}
                                        y={bottom + worldFont * 1.25}
                                        textAnchor="middle"
                                        fontSize={worldFont}
                                    >
                                        <tspan x={group.x}>
                                            {industryMetricLabel(industry)}
                                        </tspan>
                                        {shownComparisons.map(
                                            (comparison, i) => {
                                                const known =
                                                    group.nodeIds.flatMap(
                                                        (id) => {
                                                            const share =
                                                                participation[
                                                                    i
                                                                ]?.get(
                                                                    id,
                                                                )?.positiveMoveShare;
                                                            return share ===
                                                                null ||
                                                                share ===
                                                                    undefined
                                                                ? []
                                                                : [share];
                                                        },
                                                    );
                                                const average = known.length
                                                    ? known.reduce(
                                                          (sum, value) =>
                                                              sum + value,
                                                          0,
                                                      ) / known.length
                                                    : null;
                                                return (
                                                    <tspan
                                                        key={
                                                            comparison.portfolio
                                                                .id
                                                        }
                                                        x={group.x}
                                                        dy={worldFont * 1.3}
                                                        className="opportunity-industry-share"
                                                        style={{
                                                            fill: `var(--compare-${i + 1})`,
                                                        }}
                                                    >
                                                        {shownComparisons.length >
                                                        1
                                                            ? `${comparison.portfolio.name} `
                                                            : ""}
                                                        持股日上漲占比平均{" "}
                                                        {shareLabel(average)}
                                                        {known.length <
                                                        group.nodeIds.length
                                                            ? "（部分無法計算）"
                                                            : ""}
                                                    </tspan>
                                                );
                                            },
                                        )}
                                    </text>
                                );
                            })}
                    </g>
                    {overviewLabels.length > 0 && (
                        <g
                            className="opportunity-overview-labels"
                            aria-hidden="true"
                        >
                            {overviewLabels.map((label) => {
                                const toWorld = (x: number, y: number) => ({
                                    x: camera.x + (x - 500) / camera.zoom,
                                    y: camera.y + (y - 310) / camera.zoom,
                                });
                                const box = toWorld(label.x, label.y);
                                const anchor = toWorld(
                                    label.anchorX,
                                    label.anchorY,
                                );
                                const width = label.width / camera.zoom;
                                const height = label.height / camera.zoom;
                                const edgeX =
                                    label.side === "left"
                                        ? box.x + width
                                        : box.x;
                                const edgeY = box.y + height / 2;
                                const bend = (anchor.x - edgeX) * 0.42;
                                const gain =
                                    label.displayMetric === undefined
                                        ? `漲 ${gainLabel(label.maxGain)}`
                                        : `最高：${metricLabel(label.displayMetric)}${label.displayMetric.leaderName ? ` · ${label.displayMetric.leaderName}` : ""}`;
                                return (
                                    <g
                                        key={label.id}
                                        className="opportunity-overview-label"
                                    >
                                        <path
                                            className="opportunity-overview-leader"
                                            d={`M${edgeX},${edgeY} C${edgeX + bend},${edgeY} ${anchor.x - bend},${anchor.y} ${anchor.x},${anchor.y}`}
                                        />
                                        <circle
                                            className="opportunity-overview-anchor"
                                            cx={anchor.x}
                                            cy={anchor.y}
                                            r={3 / camera.zoom}
                                        />
                                        <rect
                                            x={box.x}
                                            y={box.y}
                                            width={width}
                                            height={height}
                                            rx={6 / camera.zoom}
                                            className="opportunity-overview-label-backdrop"
                                        />
                                        <text
                                            x={box.x + 10 / camera.zoom}
                                            y={box.y + 12 / camera.zoom}
                                            fontSize={worldFont}
                                        >
                                            <tspan className="opportunity-overview-name">
                                                {label.label}
                                            </tspan>
                                            <tspan
                                                x={box.x + 10 / camera.zoom}
                                                dy={worldFont * 1.15}
                                                className="opportunity-overview-gain"
                                            >
                                                {gain}
                                            </tspan>
                                        </text>
                                    </g>
                                );
                            })}
                        </g>
                    )}
                    <g
                        className="opportunity-exit-particles"
                        aria-hidden="true"
                    >
                        {!motionOff &&
                            frame?.stocks
                                .filter((item) => item.burst)
                                .flatMap((item) =>
                                    Array.from({ length: 5 }, (_, index) => (
                                        <circle
                                            key={`${item.node.id}-${index}`}
                                            ref={(element) => {
                                                const id = `${item.node.id}-${index}`;
                                                if (element)
                                                    particleElements.current.set(
                                                        id,
                                                        element,
                                                    );
                                                else
                                                    particleElements.current.delete(
                                                        id,
                                                    );
                                            }}
                                            cx={item.from.x}
                                            cy={item.from.y}
                                            r={1.8 + index * 0.3}
                                            opacity="0"
                                        />
                                    )),
                                )}
                    </g>
                </svg>
                {!frame && !error && (
                    <p className="opportunity-map-message">
                        正在畫出這天的股票…
                    </p>
                )}
                {error && (
                    <p className="opportunity-map-message" role="alert">
                        股票地圖暫時無法完成，請重新整理。
                    </p>
                )}
                {frame && !frame.layout.nodes.length && !busy && (
                    <p className="opportunity-map-message">
                        這天沒有符合條件的大漲股票。
                    </p>
                )}
                {overflow && (
                    <p className="opportunity-map-overflow">
                        還有股票在畫面外，可平移或縮小。
                    </p>
                )}
                {selectedRow?.peakGain !== null && selectedRow && (
                    <p className="opportunity-map-ghost-note">
                        虛線：
                        {selectedRow.wave.rightCensored
                            ? "截至快照最高"
                            : "事後最高"}{" "}
                        {gainLabel(selectedRow.peakGain)}
                    </p>
                )}
                {view.catalogId && frame && (
                    <button
                        type="button"
                        className="opportunity-map-reset"
                        style={{ left: 12, right: "auto" }}
                        disabled={locked}
                        onClick={() => {
                            const fitted = fitBoundsCamera(frame.layout.bounds);
                            overviewState.current = {
                                camera: fitted,
                                initialized: true,
                            };
                            setCamera(fitted);
                            mapElement.current?.focus();
                        }}
                    >
                        看全市場
                    </button>
                )}
                {!isDefaultCamera(camera, overviewState.current.camera) && (
                    <button
                        type="button"
                        className="opportunity-map-reset"
                        onClick={() => {
                            setCamera({ ...overviewState.current.camera });
                            mapElement.current?.focus();
                        }}
                    >
                        回到預設視野
                    </button>
                )}
            </div>
        </section>
    );
}
