import { useLayoutEffect, useMemo, useRef, useState } from "react";
import {
    dateIndex,
    percent,
    timelineDateBoundary,
    timelineInclusiveEndBoundary,
    timelineInclusiveRange,
    timelineRows,
} from "./model.ts";
import type {
    HistoryDirectory,
    HistoryFrame,
    HistoryMetadata,
} from "./types.ts";
import type { PortfolioComparison } from "../../domain/opportunities/types.ts";
import { supportedHoldingSegments } from "./comparisons.ts";

export function HistoryTimeline({
    directory,
    metadata,
    frame,
    selectedId,
    onSelect,
    onDate,
    comparisons,
    thresholdPct,
}: {
    directory: HistoryDirectory;
    metadata: HistoryMetadata;
    frame: HistoryFrame | null;
    selectedId: string | null;
    onSelect: (id: string) => void;
    onDate: (date: string) => void;
    comparisons: PortfolioComparison[];
    thresholdPct: number;
}) {
    const [query, setQuery] = useState("");
    const [limit, setLimit] = useState(25);
    const elements = useRef(new Map<string, HTMLDivElement>());
    const previousTops = useRef(new Map<string, number>());
    const rows = useMemo(
        () => timelineRows(directory.rows, frame, query, thresholdPct),
        [directory, frame, query, thresholdPct],
    );
    const bands = useMemo(() => {
        const result = new Map<string, HistoryDirectory["rows"]>();
        for (const row of directory.rows) {
            const group = result.get(row.securityId) ?? [];
            group.push(row);
            result.set(row.securityId, group);
        }
        return result;
    }, [directory]);
    const shown = rows.slice(0, limit);
    const denominator = Math.max(1, metadata.dates.length - 1);
    const lastDate = metadata.dates.at(-1)!;
    const afterLastDate = new Date(
        Date.parse(`${lastDate}T00:00:00Z`) + 86_400_000,
    )
        .toISOString()
        .slice(0, 10);
    const position = (date: string) =>
        timelineDateBoundary(metadata.dates, date);
    const index = frame ? dateIndex(metadata.dates, frame.date) : 0;

    useLayoutEffect(() => {
        const reducedMotion = window.matchMedia(
            "(prefers-reduced-motion: reduce)",
        ).matches;
        const nextTops = new Map<string, number>();
        for (const row of shown) {
            const element = elements.current.get(row.securityId);
            if (!element) continue;
            const top = element.getBoundingClientRect().top;
            const previous = previousTops.current.get(row.securityId);
            if (!reducedMotion && previous !== undefined && previous !== top)
                element.animate(
                    [
                        { transform: `translateY(${previous - top}px)` },
                        { transform: "translateY(0)" },
                    ],
                    { duration: 280, easing: "ease-out" },
                );
            nextTops.set(row.securityId, top);
        }
        previousTops.current = nextTops;
    }, [frame?.date, query, limit, rows, shown]);

    return (
        <section className="fh-card fh-timeline" aria-label="各股上漲期間">
            <div className="fh-section-heading">
                <div>
                    <h2>各股上漲期間</h2>
                    <p>每列是一檔股票。點時間帶前往那天，點名稱看走勢。</p>
                </div>
                <span>依當天產業與個股漲幅排序</span>
            </div>
            <div className="fh-controls">
                <input
                    aria-label="搜尋時間帶"
                    placeholder="找股票或產業"
                    value={query}
                    onChange={(event) => {
                        setQuery(event.target.value);
                        setLimit(25);
                    }}
                />
                <span>
                    {shown.length} / {rows.length} 檔
                </span>
            </div>
            <div className="fh-timeline-scroll">
                <div className="fh-timeline-inner">
                    <div className="fh-band-axis">
                        <span>{metadata.dates[0]}</span>
                        <span>{frame?.date}</span>
                        <span>{metadata.dates.at(-1)}</span>
                    </div>
                    {shown.map((row) => (
                        <div
                            className={`fh-band-row ${selectedId === row.securityId ? "is-selected" : ""}`}
                            key={row.securityId}
                            ref={(element) => {
                                if (element)
                                    elements.current.set(
                                        row.securityId,
                                        element,
                                    );
                                else elements.current.delete(row.securityId);
                            }}
                        >
                            <button
                                className="fh-band-name"
                                onClick={() => onSelect(row.securityId)}
                            >
                                <b>{row.name}</b>
                                <small>{row.industry.label}</small>
                            </button>
                            <div
                                className="fh-band-track"
                                role="slider"
                                tabIndex={0}
                                aria-label={`${row.name}時間帶日期`}
                                aria-valuemin={0}
                                aria-valuemax={denominator}
                                aria-valuenow={index}
                                aria-valuetext={frame?.date}
                                onKeyDown={(event) => {
                                    if (
                                        event.key !== "ArrowLeft" &&
                                        event.key !== "ArrowRight"
                                    )
                                        return;
                                    event.preventDefault();
                                    onSelect(row.securityId);
                                    onDate(
                                        metadata.dates[
                                            Math.max(
                                                0,
                                                Math.min(
                                                    denominator,
                                                    index +
                                                        (event.key ===
                                                        "ArrowLeft"
                                                            ? -1
                                                            : 1),
                                                ),
                                            )
                                        ],
                                    );
                                }}
                                onClick={(event) => {
                                    const rect =
                                        event.currentTarget.getBoundingClientRect();
                                    const next = Math.max(
                                        0,
                                        Math.min(
                                            metadata.dates.length - 1,
                                            Math.floor(
                                                ((event.clientX - rect.left) /
                                                    rect.width) *
                                                    metadata.dates.length,
                                            ),
                                        ),
                                    );
                                    onSelect(row.securityId);
                                    onDate(metadata.dates[next]);
                                }}
                            >
                                {(bands.get(row.securityId) ?? []).map(
                                    (wave, waveIndex) => {
                                        const end =
                                            wave.endConfirmedAt ??
                                            wave.observedThrough;
                                        const left = position(wave.start);
                                        const right = wave.endConfirmedAt
                                            ? position(end)
                                            : timelineInclusiveEndBoundary(
                                                  metadata.dates,
                                                  end,
                                              );
                                        const span = right - left || 1;
                                        return (
                                            <span
                                                key={`${wave.waveId}:${wave.representativeFrom}:${wave.representativeUntilExclusive}:${waveIndex}`}
                                                className={`fh-wave-band ${wave.rightCensored ? "is-open" : ""}`}
                                                style={{
                                                    left: `${left}%`,
                                                    width: `${Math.max(0.15, right - left)}%`,
                                                }}
                                                title={`${row.name}：${wave.start} 至 ${end}；代表區間 ${wave.representativeFrom} 至 ${wave.representativeUntilExclusive} 前；事後最高 ${percent(wave.peakGain)}（${wave.peakDate}）；${wave.rightCensored ? "尚未確認結束" : "已確認結束"}`}
                                            >
                                                {wave.phases.map(
                                                    (phase, phaseIndex) => {
                                                        const interval =
                                                            timelineInclusiveRange(
                                                                metadata.dates,
                                                                phase.from,
                                                                phase.until,
                                                            );
                                                        return (
                                                            <i
                                                                key={phaseIndex}
                                                                className={`fh-phase-${phase.phase}`}
                                                                style={{
                                                                    left: `${(100 * (interval.left - left)) / span}%`,
                                                                    width: `${Math.max(0, (100 * (interval.right - interval.left)) / span)}%`,
                                                                }}
                                                            />
                                                        );
                                                    },
                                                )}
                                                {wave.launchCandidate && (
                                                    <i
                                                        className="fh-launch-mark"
                                                        style={{
                                                            left: `${(100 * (position(wave.launchCandidate.date) - left)) / span}%`,
                                                        }}
                                                        title={`候選開始大漲：${wave.launchCandidate.date}；上攻分段 ${wave.launchCandidate.rangeFrom} 至 ${wave.launchCandidate.rangeUntil}`}
                                                    />
                                                )}
                                            </span>
                                        );
                                    },
                                )}
                                {comparisons.flatMap(
                                    (comparison, comparisonIndex) =>
                                        supportedHoldingSegments(
                                            comparison,
                                            row.securityId,
                                            metadata.dates[0],
                                            afterLastDate,
                                        ).map((segment) => {
                                            const left = position(segment.from);
                                            const right = position(
                                                segment.untilExclusive,
                                            );
                                            const coverageDescription = `${segment.coverage.from} 至 ${segment.coverage.untilExclusive} 前（${segment.coverage.completeness === "full" ? "完整覆蓋" : "部分覆蓋"}）`;
                                            return (
                                                <span
                                                    key={segment.key}
                                                    className="fh-holding-band"
                                                    style={{
                                                        left: `${left}%`,
                                                        width: `${Math.max(0.15, right - left)}%`,
                                                        bottom: `${2 + comparisonIndex * 3}px`,
                                                        background: `var(--compare-${(comparisonIndex % 4) + 1})`,
                                                    }}
                                                    title={`${comparison.portfolio.name}：保存的正數持股 ${segment.holding.from} 至 ${segment.holding.untilExclusive} 前；來源 ${segment.holding.sourceId}；覆蓋 ${coverageDescription}，來源 ${segment.coverage.sourceId}`}
                                                />
                                            );
                                        }),
                                )}
                                <i
                                    className="fh-date-cursor"
                                    style={{
                                        left: `${position(frame?.date ?? metadata.dates[0])}%`,
                                    }}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
            {limit < rows.length && (
                <button onClick={() => setLimit((value) => value + 25)}>
                    再顯示 25 檔
                </button>
            )}
            <p className="fh-caption">
                時間帶保留波段日期與代表區間；持股色帶只在正數持股證據與來源覆蓋重疊時顯示。階段與最高點都是事後標記，尚未定案。
            </p>
        </section>
    );
}
