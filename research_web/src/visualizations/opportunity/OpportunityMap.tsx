import {
    useEffect,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import type { KeyboardEvent, PointerEvent, RefObject } from "react";
import type { PortfolioComparison } from "../../domain/opportunities/types.ts";
import {
    sameSource,
    hasMapIndustry,
    mapGroupId,
    mapIndustries,
    endedBurst,
    gainColorBand,
    territoryLabelText,
    planTerritoryLabels,
    comparisonShareLine,
    shareLabel,
    type TerritoryLabelSpot,
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
    frameFor,
    gestureCamera,
    fitBoundsCamera,
    stepZoom,
    wheelZoomFactor,
    zoomCameraAt,
    type Camera,
    type ScreenPoint,
    type WorldFrame,
} from "./camera.ts";
import type { PackedGroup, PackedNode, PackingLayout } from "./packing.ts";
import type { PackingRequest, PackingResponse } from "./packing.worker.ts";
import {
    POP_DURATION,
    POP_FADE_BY,
    POP_STAGGER,
    REGATHER_DURATION,
    REGATHER_STAGGER,
    burstPose,
    delayed,
    groupWobble,
    joinScale,
    mixTo,
} from "./bubbleMotion.ts";
import {
    LAYOUT_CACHE_SIZE,
    LAYOUT_CACHE_STOCKS,
    LayoutCache,
    layoutKey,
} from "./layoutCache.ts";
import {
    MAX_BURSTS,
    MAX_JOINS,
    SHAPE_PATH,
    particleCount,
    particlePose,
    pickLargest,
    themeEffect,
    type EffectShape,
} from "./themeEffects.ts";
import "./OpportunityMap.css";

/** One fixed world scale, calibrated against the full synthetic calendar; never fitted per date. */
export const OPPORTUNITY_RADIUS_SCALE = 30;
const DURATION = 260;
/** Share of the frame the map may use when the camera follows it. */
const FOLLOW_FILL = 0.92;
const LEGEND_STEPS = [10, 20, 50, 100, 200, 300, 500, 1000, 2000];
const viewBoxFor = (camera: Camera, frame: WorldFrame) =>
    `${camera.x - frame.width / 2 / camera.zoom} ${camera.y - frame.height / 2 / camera.zoom} ${frame.width / camera.zoom} ${frame.height / camera.zoom}`;
const phaseLabel = {
    slow: "持續上漲",
    rising: "持續上漲",
    resting: "漲多休息",
    retreat: "從高點拉回",
};
const gainLabel = (value: number | null) =>
    value === null ? "不知道" : `${value >= 0 ? "+" : ""}${value.toFixed(0)}%`;
const mix = mixTo;
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
    /** Fill the parent's height instead of keeping the 1000:620 shape. */
    fill?: boolean;
    /** Glide between frames. During playback a linear glide that outlasts the
     *  step keeps the bubbles moving at an even pace; a new frame picks up from
     *  where each bubble is on screen. */
    glide?: { duration: number; linear: boolean };
    /** The date is being dragged or jumped faster than the map can follow:
     *  bubbles pop and stay gone until this clears, then regather. */
    scrubbing?: boolean;
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
    /** Share of the glide this bubble waits before it starts. */
    delay: number;
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
    /** Members came or went: the group wobbles a little as it settles. */
    pulse: boolean;
};
/** `play`: a normal step. `pop`: every bubble bursts for a fast scrub.
 *  `empty`: nothing shown while the date is still moving. `regather`: bubbles
 *  grow back out of their industries once the date has settled. */
type FrameKind = "play" | "pop" | "empty" | "regather";
type Frame = Result & {
    kind: FrameKind;
    stocks: StockTransition[];
    groups: GroupTransition[];
};
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

/** Which of the three hue families an industry (or stock group) belongs to. */
const familyOf = (groupId: string) =>
    Math.floor((angleFor(groupId) / (Math.PI * 2)) * 3) + 1;
/** Each bubble's highlight sits a little differently: tilt it up to 35 degrees. */
const tiltOf = (id: string) =>
    (angleFor(`${id}:gloss`) / (Math.PI * 2) - 0.5) * 70;
const PHASES = ["rising", "slow", "resting", "retreat", "unmarked"] as const;
/** The rim fades with the phase: strongest while rising, faintest when pulling back. */
const RIM_STRENGTH = {
    rising: 1,
    slow: 0.85,
    resting: 0.7,
    retreat: 0.55,
    unmarked: 0.5,
};
const EMPTY_LAYOUT: PackingLayout = {
    nodes: [],
    groups: [],
    bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0 },
    fillRatio: 0,
};

/** Every visible bubble bursts where it is; the groups fade with them. */
function popFrame(
    previous: Frame,
    current: Map<string, Pose>,
    groupCurrent: Map<string, Pose>,
): Frame {
    return {
        ...previous,
        kind: "pop",
        stocks: previous.stocks
            .filter((item) => !item.exiting)
            .map((item) => {
                const from = current.get(item.node.id) ?? item.to;
                return {
                    ...item,
                    from,
                    to: { ...from, opacity: 0 },
                    exiting: true,
                    burst: true,
                    delay:
                        (angleFor(item.node.id) / (Math.PI * 2)) * POP_STAGGER,
                };
            }),
        groups: previous.groups
            .filter((item) => !item.exiting)
            .map((item) => {
                const from = groupCurrent.get(item.group.id) ?? item.to;
                return {
                    ...item,
                    from,
                    to: { ...from, opacity: 0 },
                    exiting: true,
                    pulse: false,
                };
            }),
    };
}

const emptyFrame = (previous: Frame): Frame => ({
    ...previous,
    kind: "empty",
    layout: EMPTY_LAYOUT,
    stocks: [],
    groups: [],
});

function makeFrame(
    result: Result,
    previous: Frame | null,
    current: Map<string, Pose>,
    groupCurrent: Map<string, Pose>,
    regather: boolean,
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
        // A bubble that is new grows out of its industry's edge, or, when the
        // map regathers after a scrub, out of its centre one after another.
        const from = existing
            ? (current.get(node.id) ?? existing.to)
            : regather
              ? { x: group.x, y: group.y, r: 0, opacity: 0 }
              : {
                    x: group.x + Math.cos(angle) * (group.r + 12),
                    y: group.y + Math.sin(angle) * (group.r + 12),
                    r: 0,
                    opacity: 0,
                };
        return [
            {
                delay:
                    regather && !existing
                        ? (angle / (Math.PI * 2)) * REGATHER_STAGGER
                        : 0,
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
                pulse:
                    !!previousGroup &&
                    previousGroup.group.nodeIds.length !== group.nodeIds.length,
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
            pulse: false,
        });
    }
    return {
        ...result,
        kind: regather ? "regather" : "play",
        stocks,
        groups: groupTransitions,
    };
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
    fill = false,
    glide,
    scrubbing = false,
}: OpportunityMapProps) {
    const glideRef = useRef(glide);
    glideRef.current = glide;
    const uid = `opportunity-${useId().replace(/:/g, "")}`;
    const [frame, setFrame] = useState<Frame | null>(null);
    const [busy, setBusy] = useState(true);
    const [error, setError] = useState(false);
    const [systemReduced, setSystemReduced] = useState(false);
    const [animating, setAnimating] = useState(false);
    const [camera, setCamera] = useState<Camera>({ ...DEFAULT_CAMERA });
    // The camera follows each day's map in steps until the user pans or zooms.
    const [follow, setFollow] = useState(true);
    const followLevel = useRef<number | null>(null);
    const shownCamera = useRef<Camera>({ ...DEFAULT_CAMERA });
    const cameraTween = useRef(0);
    const stopFollowing = useRef(() => {});
    // The legend is rendered for React's camera (a glide's destination); while
    // the SVG glides, scale its circles by shown ÷ destination zoom.
    const legendCircles = useRef<SVGGElement | null>(null);
    // Text is laid out for the destination zoom, so it is hidden while the
    // SVG is still between two zoom levels and shown again once it lands.
    const markRescaling = (on: boolean) =>
        mapElement.current?.classList.toggle("is-rescaling", on);
    const scaleLegend = (factor: number) =>
        legendCircles.current?.style.setProperty(
            "transform",
            Math.abs(factor - 1) < 1e-9 ? "" : `scale(${factor})`,
        );
    const [size, setSize] = useState({ width: 1000, height: 620 });
    const pixelWidth = size.width;
    const worldFrame = useMemo(() => frameFor(size), [size]);
    const aspect = worldFrame.width / worldFrame.height;
    const aspectRef = useRef(aspect);
    aspectRef.current = aspect;
    const packedAspect = useRef(aspect);
    // Re-pack only when the frame shape changes noticeably.
    const aspectKey = Math.round(Math.log(aspect) * 8);
    const surface = useRef<HTMLDivElement | null>(null);
    const mapElement = useRef<SVGSVGElement | null>(null);
    const worker = useRef<Worker | null>(null);
    const queue = useRef(new LatestQueue<Snapshot>());
    const active = useRef<Snapshot | null>(null);
    const completed = useRef<Result | null>(null);
    const sequence = useRef(0);
    // Layouts packed from scratch, so scrubbing back to a date costs no
    // worker round trip. The key says which request, if any, may fill it.
    const layouts = useRef(
        new LayoutCache<PackingLayout>(
            LAYOUT_CACHE_SIZE,
            LAYOUT_CACHE_STOCKS,
            (layout) => layout.nodes.length,
        ),
    );
    const layoutKeyFor = useRef<{ requestId: number; key: string } | null>(
        null,
    );
    // The next layout is the first after a pop: its bubbles regather.
    const regather = useRef(false);
    const comparisonRef = useRef(comparisons);
    const frameRef = useRef<Frame | null>(null);
    const poses = useRef(new Map<string, Pose>());
    const groupPoses = useRef(new Map<string, Pose>());
    const stockElements = useRef(new Map<string, StockRefs>());
    const groupElements = useRef(new Map<string, SVGGElement>());
    const groupLabelElements = useRef(new Map<string, SVGTextElement>());
    const particleElements = useRef(new Map<string, SVGGElement>());
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
        const observer = new ResizeObserver((entries) => {
            const box = entries[0]?.contentRect;
            if (!box || box.width <= 0 || box.height <= 0) return;
            setSize((old) =>
                Math.abs(old.width - box.width) < 0.5 &&
                Math.abs(old.height - box.height) < 0.5
                    ? old
                    : { width: box.width, height: box.height },
            );
        });
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
            stopFollowing.current();
            setCamera((old) =>
                zoomCameraAt(
                    old,
                    factor,
                    rect,
                    {
                        x: event.clientX - rect.left,
                        y: event.clientY - rect.top,
                    },
                    frameFor(rect),
                ),
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
        // Publish a finished layout, then start whatever waited behind it.
        const accept = (snapshot: Snapshot, layout: PackingLayout) => {
            const accepted = { snapshot, layout };
            completed.current = accepted;
            // Publish the geometry and its transition together, rather
            // than committing the entire old SVG before a layout effect
            // schedules another synchronous render with the new frame.
            const nextFrame = makeFrame(
                accepted,
                frameRef.current,
                poses.current,
                groupPoses.current,
                regather.current,
            );
            regather.current = false;
            frameRef.current = nextFrame;
            setFrame(nextFrame);
            setError(false);
        };
        const settle = () => {
            const next = requests.complete();
            active.current = null;
            setBusy(next !== null);
            if (next) dispatch.current(next);
        };
        dispatch.current = (snapshot) => {
            active.current = snapshot;
            const old = completed.current;
            const knownGroups = new Set(
                snapshot.view.active
                    .filter((row) => hasMapIndustry(row, snapshot.groupingMode))
                    .map((row) => row.industry.id),
            );
            const nodes = snapshot.view.active.map((row) => ({
                id: row.security.id,
                groupId: mapGroupId(row, snapshot.groupingMode, knownGroups),
                weight: row.weight,
            }));
            const previous =
                old && sameSource(old.snapshot.view, snapshot.view)
                    ? visiblePackingPositions(old.layout.nodes)
                    : [];
            // A new frame shape re-tightens from the shown layout.
            const reshape =
                Math.round(Math.log(packedAspect.current) * 8) !==
                Math.round(Math.log(aspectRef.current) * 8);
            packedAspect.current = aspectRef.current;
            // Only a layout that carries nothing over is the same every time.
            const key =
                previous.length === 0 && !reshape
                    ? layoutKey({
                          date: snapshot.view.date,
                          aspectKey: Math.round(
                              Math.log(aspectRef.current) * 8,
                          ),
                          radiusScale: OPPORTUNITY_RADIUS_SCALE,
                          nodes,
                      })
                    : null;
            layoutKeyFor.current = key
                ? { requestId: snapshot.requestId, key }
                : null;
            const saved = key ? layouts.current.get(key) : undefined;
            if (saved) {
                accept(snapshot, saved);
                settle();
                return;
            }
            const request: PackingRequest = {
                requestId: snapshot.requestId,
                date: snapshot.view.date,
                input: {
                    nodes,
                    globalRadiusScale: OPPORTUNITY_RADIUS_SCALE,
                    previous,
                    gap: 2,
                    groupGap: 12,
                    outlinePadding: 8,
                    aspect: aspectRef.current,
                    reshape,
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
                const keyed = layoutKeyFor.current;
                // The map never reads a stock's outline points, only its path.
                if (keyed?.requestId === snapshot.requestId)
                    layouts.current.set(keyed.key, {
                        ...event.data.layout,
                        nodes: event.data.layout.nodes.map((node) => ({
                            ...node,
                            points: [],
                        })),
                    });
                accept(snapshot, event.data.layout);
            }
            settle();
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

    // A fast scrub: pop what is shown and drop all work for dates being
    // skipped. Nothing is packed or drawn until the date settles.
    useEffect(() => {
        if (!scrubbing) return;
        queue.current.reset();
        active.current = null;
        completed.current = null;
        setBusy(false);
        const shown = frameRef.current;
        if (!shown || shown.kind === "empty" || shown.kind === "pop") return;
        regather.current = true;
        const popped = popFrame(shown, poses.current, groupPoses.current);
        frameRef.current = popped;
        setFrame(popped);
    }, [scrubbing]);
    useEffect(() => {
        if (scrubbing) return;
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
    }, [view, groupingMode, aspectKey, scrubbing]);

    useLayoutEffect(() => {
        followLevel.current = null;
    }, [size]);
    useLayoutEffect(() => {
        if (!frame || !follow) return;
        if (!frame.layout.nodes.some((node) => node.r > 0)) {
            // Nothing to fit; keep React's camera on whatever is shown.
            setCamera({ ...shownCamera.current });
            return;
        }
        const fit = fitBoundsCamera(
            frame.layout.bounds,
            worldFrame,
            FOLLOW_FILL,
        );
        const zoom = stepZoom(fit.zoom, followLevel.current);
        followLevel.current = zoom;
        const target = { x: fit.x, y: fit.y, zoom };
        const from = { ...shownCamera.current };
        setCamera(target);
        const element = mapElement.current;
        const settled =
            Math.abs(from.zoom - target.zoom) <= target.zoom * 1e-9 &&
            Math.abs(from.x - target.x) * target.zoom < 0.5 &&
            Math.abs(from.y - target.y) * target.zoom < 0.5;
        if (motionOff || settled) {
            // Equal state skips the camera effect, so show the target here.
            cancelAnimationFrame(cameraTween.current);
            cameraTween.current = 0;
            shownCamera.current = target;
            element?.setAttribute("viewBox", viewBoxFor(target, worldFrame));
            scaleLegend(1);
            markRescaling(false);
            return;
        }
        // Zoom-level changes glide; the SVG is updated directly so the stocks
        // are not re-rendered on every animation frame.
        // Start the clock on the first painted frame: a slow React commit must
        // not make the glide begin halfway through.
        let start = 0;
        cancelAnimationFrame(cameraTween.current);
        scaleLegend(from.zoom / target.zoom);
        markRescaling(from.zoom !== target.zoom);
        const tick = (now: number) => {
            if (!start) start = now;
            const t = Math.min(1, (now - start) / (DURATION * 1.6));
            const eased = 1 - (1 - t) ** 3;
            const shown = {
                x: mix(from.x, target.x, eased),
                y: mix(from.y, target.y, eased),
                zoom: Math.exp(
                    mix(Math.log(from.zoom), Math.log(target.zoom), eased),
                ),
            };
            shownCamera.current = shown;
            element?.setAttribute("viewBox", viewBoxFor(shown, worldFrame));
            scaleLegend(shown.zoom / target.zoom);
            cameraTween.current = t < 1 ? requestAnimationFrame(tick) : 0;
            if (t >= 1) markRescaling(false);
        };
        cameraTween.current = requestAnimationFrame(tick);
        return () => {
            // A new frame interrupts the glide where it is on screen; the next
            // run glides on from `shownCamera`, so playback never jumps back.
            cancelAnimationFrame(cameraTween.current);
            cameraTween.current = 0;
        };
    }, [frame, follow, worldFrame, motionOff]);
    useLayoutEffect(() => {
        if (cameraTween.current) return;
        shownCamera.current = camera;
        scaleLegend(1);
        markRescaling(false);
        mapElement.current?.setAttribute(
            "viewBox",
            viewBoxFor(camera, worldFrame),
        );
    }, [camera, worldFrame]);
    // A gesture during a glide continues from the camera on screen, not from
    // the glide's destination, so the map never jumps under the pointer.
    const takeCamera = () => {
        if (cameraTween.current) {
            cancelAnimationFrame(cameraTween.current);
            cameraTween.current = 0;
            setCamera({ ...shownCamera.current });
        }
        setFollow(false);
    };
    stopFollowing.current = takeCamera;

    const worldFont = Math.max(
        12,
        (12 * BASE_WIDTH) / (pixelWidth * camera.zoom),
    );
    const labelFontRef = useRef(worldFont);
    labelFontRef.current = worldFont;
    useLayoutEffect(() => {
        if (!frame) return;
        let raf = 0;
        // Start on the first painted frame, as the camera does. A large React
        // commit must not consume the entire morph before the browser paints.
        let start = 0;
        // Playback steps glide as the page asks; the pop and the regather
        // after a scrub have their own timing and always ease.
        const duration =
            frame.kind === "pop"
                ? POP_DURATION
                : frame.kind === "regather"
                  ? REGATHER_DURATION
                  : (glideRef.current?.duration ?? DURATION);
        const linear =
            frame.kind === "play" && (glideRef.current?.linear ?? false);
        const ease = (t: number) => (linear ? t : 1 - (1 - t) ** 3);
        const apply = (fraction: number) => {
            for (const item of frame.stocks) {
                const { node, from, to, body } = item;
                // A bubble may start late (stagger); it still lands exactly
                // on its data pose when the glide ends.
                const local = delayed(fraction, item.delay);
                const eased = ease(local);
                // New bubbles grow with a small spring; bursting ones swell
                // and fade out early and then stay gone.
                const joining = !item.exiting && from.r === 0;
                let pose: Pose;
                if (item.burst) {
                    const burst = burstPose(
                        local,
                        motionOff,
                        frame.kind === "pop" ? POP_FADE_BY : undefined,
                    );
                    pose = {
                        x: from.x,
                        y: from.y,
                        r: from.r * burst.scale,
                        opacity: burst.opacity,
                    };
                } else {
                    pose = {
                        x: mix(from.x, to.x, eased),
                        y: mix(from.y, to.y, eased),
                        r: joining
                            ? to.r * joinScale(local, motionOff)
                            : mix(from.r, to.r, eased),
                        opacity: joining
                            ? mix(0, to.opacity, Math.min(1, eased * 2.5))
                            : mix(from.opacity, to.opacity, eased),
                    };
                }
                poses.current.set(node.id, pose);
                const refs = stockElements.current.get(node.id);
                refs?.root?.setAttribute(
                    "transform",
                    `translate(${pose.x - node.x} ${pose.y - node.y})`,
                );
                refs?.root?.setAttribute("opacity", String(pose.opacity));
                if (refs?.body) {
                    const scale = body.r > 0 ? pose.r / body.r : 1;
                    const tilt = tiltOf(node.id);
                    refs.body.setAttribute(
                        "transform",
                        `translate(${node.x} ${node.y}) scale(${scale}) translate(${-body.x} ${-body.y}) rotate(${tilt} ${body.x} ${body.y})`,
                    );
                    if (fraction === 1) {
                        refs.body.setAttribute("d", node.path);
                        refs.body.setAttribute(
                            "transform",
                            `rotate(${tilt} ${node.x} ${node.y})`,
                        );
                    }
                }
                // Labels that do not fit leave layout entirely (display:none);
                // transparent text would still be laid out on every frame.
                // Write only when the fit changes.
                if (refs?.label) {
                    const shown = labelFits(
                        item.row,
                        pose.r,
                        stockFont(node.r, labelFontRef.current),
                    );
                    if ((refs.label.dataset.shown === "1") !== shown) {
                        refs.label.dataset.shown = shown ? "1" : "0";
                        refs.label.setAttribute(
                            "display",
                            shown ? "inline" : "none",
                        );
                    }
                }
            }
            for (const effect of effectsRef.current) {
                for (let i = 0; i < effect.count; i++) {
                    const element = particleElements.current.get(
                        `${effect.key}-${i}`,
                    );
                    if (!element) continue;
                    const p = particlePose(
                        effect.shape,
                        effect.kind,
                        effect.origin,
                        i,
                        effect.angle,
                        fraction,
                    );
                    // Shapes are sized for the screen (one label-font unit),
                    // so they stay visible at any zoom.
                    // Rings follow the bubble's own size instead.
                    const unit =
                        effect.shape === "ring"
                            ? 1
                            : (labelFontRef.current / 12) * 1.6;
                    element.setAttribute(
                        "transform",
                        `translate(${p.x} ${p.y}) rotate(${p.rotate}) scale(${p.scale * unit})`,
                    );
                    element.setAttribute("opacity", String(p.opacity));
                }
            }
            const eased = ease(fraction);
            for (const item of frame.groups) {
                const { from, to, group } = item;
                const pose = {
                    x: mix(from.x, to.x, eased),
                    y: mix(from.y, to.y, eased),
                    r: mix(from.r, to.r, eased),
                    opacity: mix(from.opacity, to.opacity, eased),
                };
                groupPoses.current.set(group.id, pose);
                const moved = group.r > 0 ? pose.r / group.r : 1;
                const scale =
                    moved * (item.pulse ? groupWobble(fraction, motionOff) : 1);
                const element = groupElements.current.get(group.id);
                const transform = `translate(${pose.x} ${pose.y}) scale(${scale}) translate(${-group.x} ${-group.y})`;
                element?.setAttribute("transform", transform);
                element?.setAttribute("opacity", String(pose.opacity));
                // Industry labels follow the group's motion but keep their
                // size: scaling text re-rasterises it on every frame.
                const label = groupLabelElements.current.get(group.id);
                if (label) {
                    const spotX = label.x.baseVal[0]?.value ?? group.x;
                    const spotY = label.y.baseVal[0]?.value ?? group.y;
                    const dx = pose.x + moved * (spotX - group.x) - spotX;
                    const dy = pose.y + moved * (spotY - group.y) - spotY;
                    label.setAttribute("transform", `translate(${dx} ${dy})`);
                    const opacity = String(pose.opacity);
                    if (label.getAttribute("opacity") !== opacity)
                        label.setAttribute("opacity", opacity);
                }
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
            // Everything has burst: leave the map empty until the date settles.
            if (frame.kind === "pop") {
                const empty = emptyFrame(frame);
                frameRef.current = empty;
                setFrame(empty);
            }
        };
        if (motionOff || (!frame.stocks.length && !frame.groups.length)) {
            apply(1);
            finish();
            return;
        }
        setAnimating(true);
        apply(0);
        const tick = (now: number) => {
            if (!start) start = now;
            const fraction = Math.min(1, (now - start) / duration);
            apply(fraction);
            if (fraction < 1) raf = requestAnimationFrame(tick);
            else finish();
        };
        raf = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(raf);
    }, [frame, motionOff]);

    const studio = mapElement.current?.closest<HTMLElement>(".studio");
    const fx = themeEffect(
        studio?.dataset.palette,
        studio?.dataset.ambient !== "off",
    );
    const effects = useMemo(() => {
        if (!frame || motionOff) return [];
        const list: {
            key: string;
            shape: EffectShape;
            kind: "burst" | "join";
            origin: { x: number; y: number; r: number };
            angle: number;
            count: number;
        }[] = [];
        if (fx.burst) {
            const shape = fx.burst;
            for (const item of pickLargest(
                frame.stocks.filter((item) => item.burst),
                (item) => item.from.r,
                MAX_BURSTS,
            ))
                list.push({
                    key: `${item.node.id}-burst`,
                    shape,
                    kind: "burst",
                    origin: item.from,
                    angle: angleFor(item.node.id),
                    count: particleCount(shape),
                });
        }
        const joining = frame.stocks.filter(
            (item) => !item.exiting && item.from.r === 0,
        );
        // On a first or re-sourced frame everything "joins"; mark nothing.
        if (fx.join && joining.length < frame.stocks.length / 2) {
            const shape = fx.join;
            for (const item of pickLargest(
                joining,
                (item) => item.to.r,
                MAX_JOINS,
            ))
                list.push({
                    key: `${item.node.id}-join`,
                    shape,
                    kind: "join",
                    origin: item.to,
                    angle: angleFor(item.node.id),
                    count: particleCount(shape),
                });
        }
        return list;
    }, [frame, motionOff, fx.burst, fx.join]);
    const effectsRef = useRef(effects);
    effectsRef.current = effects;
    const renderedView = frame?.snapshot.view;
    const stale =
        !renderedView ||
        renderedView.date !== view.date ||
        !sameSource(renderedView, view) ||
        frame?.snapshot.groupingMode !== groupingMode;
    const locked = busy || stale || error || scrubbing;
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
    const territoryLabels = useMemo(() => {
        if (!frame) return new Map<string, TerritoryLabelSpot>();
        const halfWidth = worldFrame.width / 2 / camera.zoom;
        const halfHeight = worldFrame.height / 2 / camera.zoom;
        const groups = frame.groups
            .filter((item) => item.decorative && !item.exiting)
            .sort((a, b) => b.group.weight - a.group.weight)
            .flatMap(({ group }, rank) => {
                const industry = industries.get(group.id);
                if (!industry || !group.points.length) return [];
                // Small industries are only labelled among the top three.
                if (group.nodeIds.length < 3 && rank >= 3) return [];
                return [
                    {
                        id: group.id,
                        x: group.x,
                        top: Math.min(...group.points.map((p) => p.y)),
                        weight: group.weight,
                        text: territoryLabelText(
                            industry,
                            group.nodeIds.length,
                        ),
                    },
                ];
            });
        return planTerritoryLabels({
            groups,
            comparisonNames: shownComparisons.map(
                (comparison) => comparison.portfolio.name,
            ),
            view: {
                x0: camera.x - halfWidth,
                x1: camera.x + halfWidth,
                y0: camera.y - halfHeight,
                y1: camera.y + halfHeight,
            },
            fontSize: worldFont,
            limit: pixelWidth < 500 ? 5 : 10,
        });
    }, [
        frame,
        industries,
        worldFont,
        pixelWidth,
        shownComparisons,
        camera,
        worldFrame,
    ]);
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
        if (!viewport) return;
        takeCamera();
        setCamera((old) =>
            zoomCameraAt(old, factor, viewport, undefined, frameFor(viewport)),
        );
    };
    const pan = (x: number, y: number) => {
        takeCamera();
        setCamera((old) => ({
            ...old,
            x: old.x + x / old.zoom,
            y: old.y + y / old.zoom,
        }));
    };
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
        takeCamera();
        setCamera((old) =>
            gestureCamera(old, before, after, rect, frameFor(rect)),
        );
    };
    const pointerEnd = (event: PointerEvent<SVGSVGElement>) => {
        pointers.current.delete(event.pointerId);
        const target = event.target as Element;
        if (target.hasPointerCapture(event.pointerId))
            target.releasePointerCapture(event.pointerId);
    };
    const overflow =
        !!frame &&
        frame.layout.nodes.length > 0 &&
        (frame.layout.bounds.minX <
            camera.x - worldFrame.width / 2 / camera.zoom ||
            frame.layout.bounds.maxX >
                camera.x + worldFrame.width / 2 / camera.zoom ||
            frame.layout.bounds.minY <
                camera.y - worldFrame.height / 2 / camera.zoom ||
            frame.layout.bounds.maxY >
                camera.y + worldFrame.height / 2 / camera.zoom);
    const selectedRow = renderedView?.active.find(
        (row) =>
            row.security.id === selectedSecurityId &&
            (selectedWaveId === undefined || row.wave.id === selectedWaveId),
    );

    return (
        <section
            className={`opportunity-map${fill ? " opportunity-map--fill" : ""}`}
            aria-label="股票地圖"
            data-reduced-motion={motionOff || undefined}
        >
            <div className="opportunity-map-surface" ref={surface}>
                {/* Silent while playing: the date control already shows progress. */}
                {!error && !glide?.linear && (locked || animating) && (
                    <p className="opportunity-map-updating" role="status">
                        {frame && frame.snapshot.view.date !== view.date
                            ? `正在畫出 ${view.date}`
                            : "更新中"}
                    </p>
                )}
                <svg
                    ref={mapElement}
                    className="opportunity-map-svg"
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
                                            : "var(--map-gloss)"
                                    }
                                />
                                <stop offset=".7" stopColor={color} />
                                <stop offset="1" stopColor={color} />
                            </radialGradient>
                        ))}
                        {/* Soap bubbles: three hue families times five phases, shared by
                            every stock (colours come from themes.css). The focal point
                            puts a small specular spot at the upper left. */}
                        {[1, 2, 3].flatMap((family) =>
                            PHASES.map((phase) => (
                                <radialGradient
                                    key={`${family}-${phase}`}
                                    id={`${uid}-b${family}-${phase}`}
                                    className={`bubble-fam-${family} bubble-phase-${phase}`}
                                    cx=".5"
                                    cy=".5"
                                    r=".5"
                                    fx=".32"
                                    fy=".28"
                                >
                                    <stop offset="0" className="bubble-s0" />
                                    <stop offset=".09" className="bubble-s0b" />
                                    <stop offset=".2" className="bubble-s1" />
                                    <stop offset=".6" className="bubble-s2" />
                                    <stop offset="1" className="bubble-s3" />
                                </radialGradient>
                            )),
                        )}
                        <linearGradient
                            id={`${uid}-rim`}
                            x1="0"
                            y1="0"
                            x2="1"
                            y2="1"
                        >
                            <stop offset="0" className="bubble-rim-a" />
                            <stop offset=".38" className="bubble-rim-b" />
                            <stop offset=".7" className="bubble-rim-c" />
                            <stop offset="1" className="bubble-rim-a" />
                        </linearGradient>
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
                                const territoryColor = `var(--bubble-${familyOf(group.id)})`;
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
                                    : `url(#${uid}-${colorBasis === "gain" ? `gain-${rowGainColor(row)}` : `b${familyOf(node.groupId)}-${phase}`})`;
                            const opacity =
                                shownComparisons.length === 1 &&
                                singleShare !== null
                                    ? 0.18 +
                                      0.82 *
                                          Math.max(0, Math.min(1, singleShare))
                                    : 0.92;
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
                                        transform={`rotate(${tiltOf(node.id)} ${node.x} ${node.y})`}
                                        stroke={
                                            selected
                                                ? "var(--ink)"
                                                : `url(#${uid}-rim)`
                                        }
                                        strokeOpacity={
                                            selected ? 1 : RIM_STRENGTH[phase]
                                        }
                                        strokeWidth={selected ? 2.2 : 1.3}
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
                                        display={
                                            labelFits(row, node.r, fontSize)
                                                ? "inline"
                                                : "none"
                                        }
                                        data-shown={
                                            labelFits(row, node.r, fontSize)
                                                ? "1"
                                                : "0"
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
                                const spot = territoryLabels.get(group.id);
                                if (!industry || spot === undefined)
                                    return null;
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
                                        x={spot.x}
                                        y={spot.y}
                                        textAnchor="middle"
                                        fontSize={worldFont}
                                    >
                                        <tspan x={spot.x}>
                                            {territoryLabelText(
                                                industry,
                                                group.nodeIds.length,
                                            )}
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
                                                        x={spot.x}
                                                        dy={worldFont * 1.3}
                                                        className="opportunity-industry-share"
                                                        style={{
                                                            fill: `var(--compare-${i + 1})`,
                                                        }}
                                                    >
                                                        {spot.prefixes[i]}
                                                        {comparisonShareLine(
                                                            average,
                                                            known.length <
                                                                group.nodeIds
                                                                    .length,
                                                        )}
                                                    </tspan>
                                                );
                                            },
                                        )}
                                    </text>
                                );
                            })}
                    </g>
                    <g
                        className="opportunity-exit-particles"
                        aria-hidden="true"
                    >
                        {effects.flatMap((effect) =>
                            Array.from({ length: effect.count }, (_, index) => {
                                const id = `${effect.key}-${index}`;
                                const path = SHAPE_PATH[effect.shape];
                                return (
                                    <g
                                        key={id}
                                        className={`opportunity-fx fx-${effect.shape}`}
                                        ref={(element) => {
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
                                        transform={`translate(${effect.origin.x} ${effect.origin.y})`}
                                        opacity="0"
                                    >
                                        {path ? (
                                            <path d={path} />
                                        ) : (
                                            <circle
                                                r={
                                                    effect.shape === "ring" ||
                                                    effect.shape === "bubble"
                                                        ? 4
                                                        : 1.8 + index * 0.3
                                                }
                                            />
                                        )}
                                    </g>
                                );
                            }),
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
                {frame &&
                    !frame.layout.nodes.length &&
                    !busy &&
                    !scrubbing &&
                    (frame.kind === "play" || frame.kind === "regather") && (
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
                {frame && frame.layout.nodes.length > 0 && (
                    <ScaleLegend
                        pixelsPerUnit={(pixelWidth * camera.zoom) / BASE_WIDTH}
                        circlesRef={legendCircles}
                    />
                )}
                {!follow && (
                    <button
                        type="button"
                        className="opportunity-map-reset"
                        onClick={() => {
                            followLevel.current = null;
                            setFollow(true);
                            mapElement.current?.focus();
                        }}
                    >
                        看全部
                    </button>
                )}
            </div>
        </section>
    );
}

/** Two dashed reference circles at the current scale: area grows with gain squared. */
function ScaleLegend({
    pixelsPerUnit,
    circlesRef,
}: {
    pixelsPerUnit: number;
    circlesRef: RefObject<SVGGElement | null>;
}) {
    const radius = (gain: number) =>
        (gain / 100) * OPPORTUNITY_RADIUS_SCALE * pixelsPerUnit;
    const cap = 40;
    // Never shrink a circle to fit: pick a gain whose true size fits instead.
    const big = LEGEND_STEPS.filter((gain) => radius(gain) <= cap).at(-1);
    if (big === undefined) return null;
    const small = LEGEND_STEPS.filter(
        (gain) => gain <= big / 2.5 && radius(gain) >= 5,
    ).at(-1);
    const outer = radius(big);
    const side = outer * 2 + 4;
    return (
        <div className="opportunity-map-legend" aria-hidden="true">
            <svg width={side} height={side} viewBox={`0 0 ${side} ${side}`}>
                <g ref={circlesRef}>
                    <circle cx={side / 2} cy={side - 2 - outer} r={outer} />
                    {small !== undefined && (
                        <circle
                            cx={side / 2}
                            cy={side - 2 - radius(small)}
                            r={radius(small)}
                        />
                    )}
                </g>
            </svg>
            <span>
                <b>圓的大小對照</b>
                {small !== undefined ? `小圈 +${small}%、` : ""}大圈 +{big}%
            </span>
        </div>
    );
}
