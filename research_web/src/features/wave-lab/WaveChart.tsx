import { useMemo, useRef, type KeyboardEvent } from "react";
import type {
    AnalysisResult,
    LabCase,
    Launch,
    MethodId,
    Phase,
    Wave,
} from "./types";
import "./WaveChart.css";

export interface WaveChartProps {
    sample: LabCase;
    results: AnalysisResult[];
    waves: Wave[];
    cursor: number;
    onCursor: (index: number) => void;
    range: [number, number];
    onRange: (range: [number, number]) => void;
    raw: boolean;
    logarithmic: boolean;
    showPhases: boolean;
    showLaunches: boolean;
    showWaves: boolean;
    selectedLaunch: string | null;
    onLaunch: (id: string, method: MethodId) => void;
    selectedWave: string | null;
    onWave: (id: string) => void;
}

const WIDTH = 1000;
const LEFT = 62;
const RIGHT = 22;
const TOP = 28;
const PRICE_BOTTOM = 310;
const PHASE_TOP = 344;
const PHASE_HEIGHT = 20;
const WAVE_TOP = 415;
const WAVE_HEIGHT = 54;
const HEIGHT = 510;
const phaseColor: Record<Phase, string> = {
    falling: "#b65d53",
    flat: "#8a938c",
    rising: "#438364",
    fast: "#b78037",
};
const methodColor: Record<MethodId, string> = {
    segments: "#438364",
    filter: "#af792d",
};
const phaseLabel: Record<Phase, string> = {
    falling: "回落",
    flat: "整理",
    rising: "緩升",
    fast: "急升",
};
const launchKindLabel: Record<Launch["kind"], string> = {
    reversal: "反轉發車",
    breakout: "整理後上攻",
    acceleration: "加速發車",
};

const finite = (value: number | null | undefined): value is number =>
    value !== null && value !== undefined && Number.isFinite(value);

function linePath(
    values: (number | null)[],
    x: (i: number) => number,
    y: (v: number) => number,
) {
    let path = "";
    let open = false;
    values.forEach((value, index) => {
        if (!finite(value)) {
            open = false;
            return;
        }
        path += `${open ? "L" : "M"}${x(index).toFixed(2)},${y(value).toFixed(2)} `;
        open = true;
    });
    return path;
}

function dateLabel(date: string) {
    return date.slice(0, 10).replaceAll("-", "/");
}

function priceLabel(value: number) {
    return value >= 1000
        ? value.toLocaleString(undefined, { maximumFractionDigits: 0 })
        : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function launchLabel(launch: Launch, points: LabCase["points"]) {
    return `${launchKindLabel[launch.kind]}｜${dateLabel(points[launch.rangeStart]?.date ?? "")} 至 ${dateLabel(points[launch.rangeEnd]?.date ?? "")}`;
}

export function WaveChart(props: WaveChartProps) {
    const {
        sample,
        results,
        cursor,
        onCursor,
        range,
        onRange,
        raw,
        logarithmic,
        showPhases,
        showLaunches,
        showWaves,
        selectedLaunch,
        onLaunch,
        selectedWave,
        onWave,
    } = props;
    const svgRef = useRef<SVGSVGElement>(null);
    const dragging = useRef(false);
    const count = sample.points.length;
    const [start, end] = useMemo(() => {
        if (!count) return [0, 0] as const;
        const low = Math.max(0, Math.min(range[0], count - 1));
        const high = Math.max(low, Math.min(range[1], count - 1));
        return [low, high] as const;
    }, [count, range]);
    const span = Math.max(1, end - start);
    const plotWidth = WIDTH - LEFT - RIGHT;
    const x = (index: number) => LEFT + ((index - start) / span) * plotWidth;
    const visible = sample.points.slice(start, end + 1);
    const priceValues = visible
        .map((point) => (raw ? point.raw : point.adjusted))
        .filter(finite)
        .filter((value) => !logarithmic || value > 0);
    const safeValues = priceValues.length ? priceValues : [1, 2];
    const transformed = safeValues.map((value) =>
        logarithmic ? Math.log10(value) : value,
    );
    const minValue = Math.min(...transformed);
    const maxValue = Math.max(...transformed);
    const pad = Math.max(
        (maxValue - minValue) * 0.08,
        logarithmic ? 0.03 : Math.max(maxValue * 0.015, 0.5),
    );
    const low = logarithmic ? minValue - pad : Math.max(0, minValue - pad);
    const high = maxValue + pad;
    const y = (value: number) => {
        const normalized = logarithmic ? Math.log10(value) : value;
        return (
            TOP +
            ((high - normalized) / Math.max(high - low, 0.001)) *
                (PRICE_BOTTOM - TOP)
        );
    };
    const originals = sample.points.map((point) =>
        raw ? point.raw : point.adjusted,
    );
    const usable = originals.map((value) =>
        finite(value) && (!logarithmic || value > 0) ? value : null,
    );
    const cursorIndex = Math.max(start, Math.min(end, cursor));
    const cursorPoint = sample.points[cursorIndex];
    const tickCount = Math.min(6, span + 1);
    const tickIndexes = Array.from(
        { length: tickCount },
        (_, i) => start + Math.round((span * i) / Math.max(1, tickCount - 1)),
    );
    const priceTicks = Array.from(
        { length: 5 },
        (_, i) => high - ((high - low) * i) / 4,
    );
    const waves = props.waves;

    const nearestIndex = (clientX: number) => {
        const rect = svgRef.current?.getBoundingClientRect();
        if (!rect || !count) return start;
        const relative = Math.max(
            0,
            Math.min(
                1,
                (clientX - rect.left - (LEFT / WIDTH) * rect.width) /
                    ((plotWidth / WIDTH) * rect.width),
            ),
        );
        return Math.max(
            start,
            Math.min(end, start + Math.round(relative * span)),
        );
    };
    const setRange = (nextStart: number, nextEnd: number) =>
        onRange([
            Math.max(0, Math.min(nextStart, count - 1)),
            Math.max(0, Math.min(nextEnd, count - 1)),
        ]);
    const zoom = (direction: 1 | -1) => {
        const length = Math.max(1, end - start + 1);
        const next =
            direction === 1
                ? Math.max(2, Math.round(length * 0.65))
                : Math.min(count, Math.round(length * 1.55));
        const centre = (start + end) / 2;
        setRange(
            Math.round(centre - (next - 1) / 2),
            Math.round(centre + (next - 1) / 2),
        );
    };
    const keyedCursor = (event: KeyboardEvent<SVGSVGElement>) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        onCursor(
            Math.max(
                start,
                Math.min(
                    end,
                    cursorIndex + (event.key === "ArrowLeft" ? -1 : 1),
                ),
            ),
        );
    };

    if (!count)
        return (
            <div className="wave-chart-empty">此案例沒有可繪製的價格資料。</div>
        );

    return (
        <section
            className="wave-chart"
            aria-label={`${sample.name} 波段檢視圖`}
        >
            <div className="wave-chart-toolbar">
                <div className="wave-chart-legend" aria-label="圖例">
                    <span>
                        <i className="wave-swatch wave-swatch-price" />
                        {raw ? "原始價格" : "還原價格"}
                    </span>
                    {raw ? (
                        <span className="wave-fit-note">
                            擬合採還原價格基準，原始價格模式不顯示
                        </span>
                    ) : (
                        results.map((result) => (
                            <span key={result.method}>
                                <i
                                    className={`wave-swatch wave-swatch-${result.method}`}
                                    style={{
                                        background:
                                            result.method === "filter"
                                                ? "repeating-linear-gradient(90deg, #af792d 0 6px, transparent 6px 10px)"
                                                : methodColor[result.method],
                                    }}
                                />
                                {result.method === "segments"
                                    ? "分段擬合"
                                    : "濾波擬合"}
                            </span>
                        ))
                    )}
                    {showPhases &&
                        (Object.keys(phaseLabel) as Phase[]).map((phase) => (
                            <span key={phase}>
                                <i
                                    className="wave-phase-swatch"
                                    style={{ background: phaseColor[phase] }}
                                />
                                {phaseLabel[phase]}
                            </span>
                        ))}
                </div>
                <output className="wave-chart-cursor" aria-live="polite">
                    {dateLabel(cursorPoint?.date ?? "")} · 原始{" "}
                    {finite(cursorPoint?.raw)
                        ? priceLabel(cursorPoint.raw)
                        : "缺值"}{" "}
                    · 還原{" "}
                    {finite(cursorPoint?.adjusted)
                        ? priceLabel(cursorPoint.adjusted)
                        : "缺值"}
                </output>
            </div>
            <div className="wave-chart-scroll">
                <svg
                    ref={svgRef}
                    className="wave-chart-svg"
                    viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                    role="img"
                    tabIndex={0}
                    aria-label={`${sample.name} 價格與波段證據圖，可用左右方向鍵移動日期游標`}
                    onKeyDown={keyedCursor}
                    onPointerDown={(event) => {
                        dragging.current = true;
                        event.currentTarget.setPointerCapture(event.pointerId);
                        onCursor(nearestIndex(event.clientX));
                    }}
                    onPointerMove={(event) => {
                        if (dragging.current)
                            onCursor(nearestIndex(event.clientX));
                    }}
                    onPointerUp={(event) => {
                        dragging.current = false;
                        event.currentTarget.releasePointerCapture(
                            event.pointerId,
                        );
                    }}
                    onPointerCancel={() => {
                        dragging.current = false;
                    }}
                    onLostPointerCapture={() => {
                        dragging.current = false;
                    }}
                >
                    <defs>
                        <clipPath id="wave-price-clip">
                            <rect
                                x={LEFT}
                                y={TOP}
                                width={plotWidth}
                                height={PRICE_BOTTOM - TOP}
                            />
                        </clipPath>
                        <clipPath id="wave-phase-clip">
                            <rect
                                x={LEFT}
                                y={PHASE_TOP}
                                width={plotWidth}
                                height={PHASE_HEIGHT * 2 + 5}
                            />
                        </clipPath>
                        <clipPath id="wave-evidence-clip">
                            <rect
                                x={LEFT}
                                y={WAVE_TOP - 12}
                                width={plotWidth}
                                height={WAVE_HEIGHT + 12}
                            />
                        </clipPath>
                    </defs>
                    {priceTicks.map((tick) => (
                        <g key={tick}>
                            <line
                                x1={LEFT}
                                x2={WIDTH - RIGHT}
                                y1={
                                    TOP +
                                    ((high - tick) / (high - low)) *
                                        (PRICE_BOTTOM - TOP)
                                }
                                y2={
                                    TOP +
                                    ((high - tick) / (high - low)) *
                                        (PRICE_BOTTOM - TOP)
                                }
                                className="wave-grid"
                            />
                            <text
                                x={LEFT - 9}
                                y={
                                    TOP +
                                    ((high - tick) / (high - low)) *
                                        (PRICE_BOTTOM - TOP) +
                                    4
                                }
                                className="wave-axis-label"
                                textAnchor="end"
                            >
                                {priceLabel(logarithmic ? 10 ** tick : tick)}
                            </text>
                        </g>
                    ))}
                    <text x={LEFT} y={16} className="wave-axis-title">
                        價格（{logarithmic ? "對數" : "線性"}）
                    </text>
                    <g clipPath="url(#wave-price-clip)">
                        <path
                            d={linePath(usable, x, y)}
                            className="wave-price-line"
                        />
                        {!raw &&
                            results.map((result) => (
                                <path
                                    key={result.method}
                                    d={linePath(
                                        result.fit.map((value) =>
                                            finite(value) &&
                                            (!logarithmic || value > 0)
                                                ? value
                                                : null,
                                        ),
                                        x,
                                        y,
                                    )}
                                    fill="none"
                                    stroke={methodColor[result.method]}
                                    strokeWidth="2.1"
                                    strokeDasharray={
                                        result.method === "filter"
                                            ? "6 4"
                                            : undefined
                                    }
                                    strokeLinecap="round"
                                />
                            ))}
                        {showLaunches &&
                            results.flatMap((result) =>
                                result.launches.map((launch) => {
                                    const launchKey = `${result.method}:${launch.id}`;
                                    return (
                                        <g
                                            key={launchKey}
                                            className={`wave-launch ${selectedLaunch === launchKey ? "is-selected" : ""}`}
                                            onPointerDown={(event) =>
                                                event.stopPropagation()
                                            }
                                            onClick={(event) => {
                                                event.stopPropagation();
                                                onLaunch(
                                                    launchKey,
                                                    result.method,
                                                );
                                            }}
                                            role="button"
                                            tabIndex={0}
                                            aria-label={`選取 ${launchLabel(launch, sample.points)}`}
                                            onKeyDown={(event) => {
                                                if (
                                                    event.key === "Enter" ||
                                                    event.key === " "
                                                ) {
                                                    event.preventDefault();
                                                    onLaunch(
                                                        launchKey,
                                                        result.method,
                                                    );
                                                }
                                            }}
                                        >
                                            <title>
                                                {launchLabel(
                                                    launch,
                                                    sample.points,
                                                )}
                                            </title>
                                            <rect
                                                x={x(launch.rangeStart) - 4}
                                                y={TOP}
                                                width={Math.max(
                                                    10,
                                                    x(launch.rangeEnd) -
                                                        x(launch.rangeStart) +
                                                        8,
                                                )}
                                                height={PRICE_BOTTOM - TOP}
                                                fill="transparent"
                                                pointerEvents="all"
                                            />
                                            <rect
                                                x={x(launch.rangeStart)}
                                                y={TOP}
                                                width={Math.max(
                                                    2,
                                                    x(launch.rangeEnd) -
                                                        x(launch.rangeStart),
                                                )}
                                                height={PRICE_BOTTOM - TOP}
                                                fill={
                                                    methodColor[result.method]
                                                }
                                                opacity="0.08"
                                            />
                                            <path
                                                d={`M${x(launch.index)},${TOP + 3} l-5,8 h10 z`}
                                                fill={
                                                    methodColor[result.method]
                                                }
                                            />
                                        </g>
                                    );
                                }),
                            )}
                        <line
                            x1={x(cursorIndex)}
                            x2={x(cursorIndex)}
                            y1={TOP}
                            y2={PRICE_BOTTOM}
                            className="wave-cursor-line"
                        />
                    </g>
                    <line
                        x1={LEFT}
                        x2={WIDTH - RIGHT}
                        y1={PRICE_BOTTOM}
                        y2={PRICE_BOTTOM}
                        className="wave-axis"
                    />
                    {tickIndexes.map((index) => (
                        <text
                            key={index}
                            x={x(index)}
                            y={PRICE_BOTTOM + 18}
                            className="wave-axis-label"
                            textAnchor="middle"
                        >
                            {dateLabel(sample.points[index]?.date ?? "")}
                        </text>
                    ))}
                    {showPhases &&
                        results.map((result, row) => (
                            <g key={result.method}>
                                <text
                                    x={LEFT - 9}
                                    y={
                                        PHASE_TOP +
                                        row * (PHASE_HEIGHT + 5) +
                                        15
                                    }
                                    className="wave-axis-label"
                                    textAnchor="end"
                                >
                                    {result.method === "segments"
                                        ? "分段"
                                        : "濾波"}
                                </text>
                                <g clipPath="url(#wave-phase-clip)">
                                    {result.segments.map((segment, index) => (
                                        <rect
                                            key={index}
                                            x={x(segment.start)}
                                            y={
                                                PHASE_TOP +
                                                row * (PHASE_HEIGHT + 5)
                                            }
                                            width={Math.max(
                                                2,
                                                x(segment.end) -
                                                    x(segment.start),
                                            )}
                                            height={PHASE_HEIGHT}
                                            fill={phaseColor[segment.phase]}
                                            opacity="0.46"
                                        >
                                            <title>
                                                {phaseLabel[segment.phase]}｜
                                                {dateLabel(
                                                    sample.points[segment.start]
                                                        ?.date ?? "",
                                                )}{" "}
                                                至{" "}
                                                {dateLabel(
                                                    sample.points[segment.end]
                                                        ?.date ?? "",
                                                )}
                                            </title>
                                        </rect>
                                    ))}
                                </g>
                            </g>
                        ))}
                    {showPhases && (
                        <text
                            x={LEFT}
                            y={PHASE_TOP - 8}
                            className="wave-axis-title"
                        >
                            相位（與價格共用時間軸）
                        </text>
                    )}
                    {showWaves && (
                        <g>
                            <text
                                x={LEFT}
                                y={WAVE_TOP - 9}
                                className="wave-axis-title"
                            >
                                波段證據
                            </text>
                            <g clipPath="url(#wave-evidence-clip)">
                                {waves.map((wave) => {
                                    const lane = wave.scale === "large" ? 0 : 1;
                                    const laneY = WAVE_TOP + lane * 23 + 9;
                                    const isVisible =
                                        (wave.end ?? wave.observedThrough) >=
                                            start && wave.start <= end;
                                    if (!isVisible) return null;
                                    const endIndex =
                                        wave.end ??
                                        Math.min(end, wave.observedThrough);
                                    return (
                                        <g
                                            key={wave.id}
                                            className={`wave-evidence ${selectedWave === wave.id ? "is-selected" : ""}`}
                                            role="button"
                                            tabIndex={0}
                                            aria-label={`選取${wave.scale === "large" ? "大" : "小"}波段，漲幅 ${wave.gain.toFixed(1)}%`}
                                            onPointerDown={(event) =>
                                                event.stopPropagation()
                                            }
                                            onClick={(event) => {
                                                event.stopPropagation();
                                                onWave(wave.id);
                                            }}
                                            onKeyDown={(event) => {
                                                if (
                                                    event.key === "Enter" ||
                                                    event.key === " "
                                                ) {
                                                    event.preventDefault();
                                                    onWave(wave.id);
                                                }
                                            }}
                                        >
                                            <title>{`漲幅 ${wave.gain.toFixed(1)}%｜最大回撤 ${wave.maxDrawdown.toFixed(1)}%${wave.rightCensored ? "｜右側截尾" : ""}`}</title>
                                            <rect
                                                x={x(wave.start)}
                                                y={laneY - 10}
                                                width={Math.max(
                                                    8,
                                                    x(endIndex) - x(wave.start),
                                                )}
                                                height={18}
                                                fill="transparent"
                                                pointerEvents="all"
                                            />
                                            <path
                                                d={`M${x(wave.start)},${laneY} L${x(wave.peak)},${laneY}`}
                                                stroke="currentColor"
                                                strokeWidth="3"
                                                strokeLinecap="round"
                                            />
                                            <path
                                                d={`M${x(wave.peak)},${laneY} L${x(endIndex)},${laneY}`}
                                                stroke="currentColor"
                                                strokeWidth="3"
                                                strokeDasharray="5 4"
                                                opacity={
                                                    wave.end === null
                                                        ? 0.45
                                                        : 0.85
                                                }
                                                strokeLinecap="round"
                                            />
                                            <circle
                                                cx={x(wave.peak)}
                                                cy={laneY}
                                                r="4"
                                                fill="currentColor"
                                            />
                                            <text
                                                x={x(wave.start)}
                                                y={laneY - 7}
                                                className="wave-evidence-label"
                                            >
                                                {wave.scale === "large"
                                                    ? "大"
                                                    : "小"}
                                            </text>
                                        </g>
                                    );
                                })}
                            </g>
                            <text
                                x={LEFT}
                                y={WAVE_TOP + WAVE_HEIGHT}
                                className="wave-axis-label"
                            >
                                實線：起點至峰值　虛線：峰值至終點／觀測截止
                            </text>
                        </g>
                    )}
                </svg>
            </div>
            <figcaption>
                價格曲線保留缺值斷點；發車區間與波段可選取以檢視原始證據。
            </figcaption>
            <div className="wave-range-controls" aria-label="可見日期範圍">
                <label>
                    起點{" "}
                    <input
                        type="range"
                        min="0"
                        max={Math.max(0, count - 1)}
                        value={start}
                        onChange={(event) =>
                            setRange(
                                Math.min(Number(event.target.value), end),
                                end,
                            )
                        }
                    />
                </label>
                <label>
                    終點{" "}
                    <input
                        type="range"
                        min="0"
                        max={Math.max(0, count - 1)}
                        value={end}
                        onChange={(event) =>
                            setRange(
                                start,
                                Math.max(Number(event.target.value), start),
                            )
                        }
                    />
                </label>
                <button type="button" onClick={() => zoom(1)}>
                    放大
                </button>
                <button type="button" onClick={() => zoom(-1)}>
                    縮小
                </button>
                <button type="button" onClick={() => setRange(0, count - 1)}>
                    全段
                </button>
            </div>
        </section>
    );
}
