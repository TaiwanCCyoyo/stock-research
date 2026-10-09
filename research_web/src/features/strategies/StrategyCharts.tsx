import { useEffect, useRef, useState } from "react";
import { percentage } from "./format";

/** Keep axes legible on phones instead of shrinking a desktop SVG and its text. */
function useChartWidth(enabled: boolean) {
    const host = useRef<HTMLDivElement>(null);
    const [width, setWidth] = useState(800);
    useEffect(() => {
        if (!enabled || !host.current) return;
        const measure = () =>
            setWidth(Math.max(250, host.current?.clientWidth ?? 800));
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(host.current);
        return () => observer.disconnect();
    }, [enabled]);
    return { host, width };
}

export interface ChartLine {
    name: string;
    color: string;
    values: (number | null)[];
}
export function LineChart({
    dates,
    lines,
    label,
    onPick,
    compact = false,
    format = (v: number) => String(Math.round(v)),
}: {
    dates: string[];
    lines: ChartLine[];
    label: string;
    onPick?: (date: string) => void;
    compact?: boolean;
    format?: (value: number) => string;
}) {
    const [cursor, setCursor] = useState<number | null>(null);
    const values = lines.flatMap((line) =>
        line.values.filter(
            (v): v is number => v !== null && Number.isFinite(v),
        ),
    );
    const size = useChartWidth(dates.length > 0 && values.length > 0);
    if (!dates.length || !values.length)
        return <p className="ss-muted">這段資料尚未保存。</p>;
    const low = Math.min(...values),
        high = Math.max(...values),
        spread = high - low || Math.max(high * 0.02, 1);
    const width = size.width,
        height = compact ? 135 : width < 500 ? 255 : 310,
        left = compact ? 5 : 75,
        right = 15,
        top = 18,
        bottom = compact ? 10 : 35;
    const x = (i: number) =>
        left + (i / Math.max(1, dates.length - 1)) * (width - left - right);
    const y = (v: number) =>
        top + ((high - v) / spread) * (height - top - bottom);
    const pick = (event: React.MouseEvent<SVGSVGElement>) => {
        const rect = event.currentTarget.getBoundingClientRect();
        return Math.max(
            0,
            Math.min(
                dates.length - 1,
                Math.round(
                    ((((event.clientX - rect.left) / rect.width) * width -
                        left) /
                        (width - left - right)) *
                        (dates.length - 1),
                ),
            ),
        );
    };
    return (
        <div
            className={`ss-chart ${compact ? "ss-chart-compact" : ""}`}
            ref={size.host}
        >
            <svg
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label={label}
                onMouseMove={(event) => setCursor(pick(event))}
                onMouseLeave={() => setCursor(null)}
                onClick={(event) => onPick?.(dates[pick(event)])}
                style={{ cursor: onPick ? "pointer" : undefined }}
            >
                {!compact &&
                    [0, 0.5, 1].map((v) => (
                        <g key={v}>
                            <line
                                x1={left}
                                x2={width - right}
                                y1={y(low + v * spread)}
                                y2={y(low + v * spread)}
                                stroke="var(--line)"
                            />
                            <text
                                x={left - 8}
                                y={y(low + v * spread) + 4}
                                textAnchor="end"
                                fill="var(--muted)"
                                fontSize="12"
                            >
                                {format(low + v * spread)}
                            </text>
                        </g>
                    ))}
                {lines.map((line) => {
                    let preceding = false;
                    const path = line.values
                        .map((value, index) => {
                            if (value === null || !Number.isFinite(value)) {
                                preceding = false;
                                return "";
                            }
                            const command = preceding ? "L" : "M";
                            preceding = true;
                            return `${command}${x(index).toFixed(2)},${y(value).toFixed(2)}`;
                        })
                        .join(" ");
                    return (
                        <path
                            key={line.name}
                            d={path}
                            stroke={line.color}
                            fill="none"
                            strokeWidth={compact ? 2.5 : 2.8}
                        />
                    );
                })}
                {!compact && (
                    <>
                        <text
                            x={left}
                            y={height - 6}
                            fill="var(--muted)"
                            fontSize="12"
                        >
                            {dates[0]}
                        </text>
                        <text
                            x={width - right}
                            y={height - 6}
                            textAnchor="end"
                            fill="var(--muted)"
                            fontSize="12"
                        >
                            {dates.at(-1)}
                        </text>
                    </>
                )}
                {cursor !== null && (
                    <line
                        x1={x(cursor)}
                        x2={x(cursor)}
                        y1={top}
                        y2={height - bottom}
                        stroke="var(--muted)"
                        strokeDasharray="4 4"
                    />
                )}
            </svg>
            {
                <div
                    className="ss-legend"
                    style={compact ? { fontSize: 12 } : undefined}
                >
                    {lines.map((line) => (
                        <span key={line.name}>
                            <i style={{ background: line.color }} />
                            {line.name}
                            {!compact &&
                            cursor !== null &&
                            line.values[cursor] != null
                                ? ` ${format(line.values[cursor]!)}`
                                : ""}
                        </span>
                    ))}
                    {!compact && cursor !== null && <b>{dates[cursor]}</b>}
                </div>
            }
            {onPick && !compact && (
                <div className="ss-chart-date">
                    <label>
                        選一天驗算{" "}
                        <input
                            type="range"
                            min="0"
                            max={dates.length - 1}
                            value={cursor ?? dates.length - 1}
                            onChange={(event) =>
                                setCursor(Number(event.target.value))
                            }
                        />
                    </label>
                    <button
                        className="ss-button"
                        onClick={() =>
                            onPick(dates[cursor ?? dates.length - 1])
                        }
                    >
                        {dates[cursor ?? dates.length - 1]} 持股與現金
                    </button>
                </div>
            )}
        </div>
    );
}

export interface CandlePoint {
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
}
export interface CandleMark {
    date: string;
    price: number | null;
    label: string;
    action: string;
}
export function TradeCandles({
    candles,
    marks,
    through,
    threshold,
}: {
    candles: CandlePoint[];
    marks: CandleMark[];
    through?: string | null;
    threshold?: number | null;
}) {
    const visible = through
        ? candles.filter((point) => point.date <= through)
        : candles;
    const size = useChartWidth(visible.length > 0);
    if (!visible.length)
        return (
            <p className="ss-muted">未保存這段日 K 線，不能核對買賣價格。</p>
        );
    const highest = Math.max(
        ...visible.map((point) => point.high),
        ...marks
            .filter((mark) => !through || mark.date <= through)
            .map((mark) => mark.price ?? 0),
        threshold ?? 0,
    );
    const lowest = Math.min(...visible.map((point) => point.low));
    const span = highest - lowest || 1,
        width = size.width,
        height = 310,
        left = 48,
        top = 35,
        bottom = 45;
    const x = (i: number) =>
        left + ((i + 0.5) / visible.length) * (width - left - 12);
    const y = (value: number) =>
        top + ((highest - value) / span) * (height - top - bottom);
    const body = Math.min(
        9,
        Math.max(0.8, ((width - left - 12) / visible.length) * 0.65),
    );
    return (
        <div className="ss-chart" ref={size.host}>
            <svg
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label="未還原日 K 線與實際買賣標記"
            >
                {[lowest, (highest + lowest) / 2, highest].map((value) => (
                    <g key={value}>
                        <text
                            x={left - 7}
                            y={y(value) + 4}
                            textAnchor="end"
                            fill="var(--muted)"
                            fontSize="11"
                        >
                            {value.toFixed(1)}
                        </text>
                        <line
                            x1={left}
                            x2={width - 12}
                            y1={y(value)}
                            y2={y(value)}
                            stroke="var(--line)"
                        />
                    </g>
                ))}
                {threshold != null && (
                    <g>
                        <line
                            x1={left}
                            x2={width - 12}
                            y1={y(threshold)}
                            y2={y(threshold)}
                            stroke="var(--ss-gold)"
                            strokeDasharray="5 5"
                        />
                        <text
                            x={width - 12}
                            y={y(threshold) - 5}
                            textAnchor="end"
                            fill="var(--ss-gold)"
                            fontSize="12"
                        >
                            股價參考 +10%
                        </text>
                    </g>
                )}
                {visible.map((point, i) => (
                    <g key={point.date}>
                        <title>
                            {point.date} 開 {point.open} 高 {point.high} 低{" "}
                            {point.low} 收 {point.close}
                        </title>
                        <line
                            x1={x(i)}
                            x2={x(i)}
                            y1={y(point.high)}
                            y2={y(point.low)}
                            stroke={
                                point.close >= point.open
                                    ? "var(--ss-up)"
                                    : "var(--ss-down)"
                            }
                        />
                        <rect
                            x={x(i) - body / 2}
                            y={Math.min(y(point.open), y(point.close))}
                            width={body}
                            height={Math.max(
                                1,
                                Math.abs(y(point.close) - y(point.open)),
                            )}
                            fill={
                                point.close >= point.open
                                    ? "var(--ss-up)"
                                    : "var(--ss-down)"
                            }
                        />
                    </g>
                ))}
                {marks
                    .filter(
                        (mark) =>
                            (!through || mark.date <= through) &&
                            mark.price !== null,
                    )
                    .map((mark, index) => {
                        const i = visible.findIndex(
                            (point) => point.date === mark.date,
                        );
                        if (i < 0) return null;
                        const isBuy = mark.action === "BUY";
                        return (
                            <g key={`${mark.date}-${index}`}>
                                <circle
                                    cx={x(i)}
                                    cy={y(mark.price!)}
                                    r="4.5"
                                    fill={
                                        isBuy
                                            ? "var(--accent)"
                                            : "var(--ss-gold)"
                                    }
                                    stroke="var(--surface)"
                                />
                                <text
                                    x={Math.max(78, Math.min(width - 80, x(i)))}
                                    y={
                                        isBuy
                                            ? height - 24 - (index % 2) * 13
                                            : 14 + (index % 2) * 14
                                    }
                                    textAnchor="middle"
                                    fill="var(--ink)"
                                    fontSize="11"
                                >
                                    {mark.label} {mark.price}
                                </text>
                                <title>
                                    {mark.date} {mark.label} 成交 {mark.price}{" "}
                                    元
                                </title>
                            </g>
                        );
                    })}
                <text x={left} y={height - 5} fontSize="11" fill="var(--muted)">
                    {visible[0].date}
                </text>
                <text
                    x={width - 12}
                    y={height - 5}
                    textAnchor="end"
                    fontSize="11"
                    fill="var(--muted)"
                >
                    {visible.at(-1)?.date}
                </text>
            </svg>
            <p className="ss-muted ss-small">
                未還原股價；圓點是模擬成交，移到 K 線上可看當日開高低收。
            </p>
        </div>
    );
}

export function MonthlyHeatmap({
    months,
}: {
    months: { month: string; return: number | null }[];
}) {
    const years = [...new Set(months.map((month) => month.month.slice(0, 4)))];
    const byMonth = new Map(months.map((month) => [month.month, month.return]));
    const maximum = Math.max(
        0.01,
        ...months.map((month) => Math.abs(month.return ?? 0)),
    );
    return (
        <div className="ss-heat-scroll">
            <div className="ss-heat">
                <div />
                {Array.from({ length: 12 }, (_, i) => (
                    <span key={i}>{i + 1}月</span>
                ))}
                {years.map((year) => (
                    <div className="ss-heat-year" key={year}>
                        <b>{year}</b>
                        {Array.from({ length: 12 }, (_, index) => {
                            const key = `${year}-${String(index + 1).padStart(2, "0")}`,
                                value = byMonth.get(key);
                            return (
                                <div
                                    key={key}
                                    className="ss-heat-cell"
                                    title={`${key} ${percentage(value)}`}
                                    style={
                                        value == null
                                            ? undefined
                                            : {
                                                  background: `color-mix(in srgb, var(${value >= 0 ? "--ss-up" : "--ss-down"}) ${12 + Math.min(1, Math.abs(value) / maximum) * 58}%, var(--surface))`,
                                              }
                                    }
                                >
                                    {value == null ? "—" : percentage(value, 0)}
                                </div>
                            );
                        })}
                    </div>
                ))}
            </div>
        </div>
    );
}
