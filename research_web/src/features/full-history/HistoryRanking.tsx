import { useLayoutEffect, useRef, useState } from "react";
import { percent, phaseLabel } from "./model.ts";
import { growthBasisLabel } from "./growthDisplay.ts";
import type { HistoryRow } from "./types.ts";
import type { PortfolioComparison } from "../../domain/opportunities/types.ts";
import { frameStatusMessage, type FrameDisplay } from "./frameDisplay.ts";

export function PriceSparkline({ row }: { row: HistoryRow }) {
    const points = row.sparkline ?? [];
    const values = points.flatMap((p) =>
        p.adjusted === null ? [] : [p.adjusted],
    );
    if (values.length < 2)
        return <span className="fh-spark-empty">走勢待讀取</span>;
    const min = Math.min(...values),
        max = Math.max(...values);
    let pen = false,
        path = "";
    points.forEach((point, i) => {
        if (point.adjusted === null) {
            pen = false;
            return;
        }
        path += `${pen ? "L" : "M"}${(i / Math.max(1, points.length - 1)) * 120},${36 - ((point.adjusted - min) / (max - min || 1)) * 30}`;
        pen = true;
    });
    return (
        <svg
            className="fh-spark"
            viewBox="0 0 120 40"
            role="img"
            aria-label={`${row.name}，${row.start} 至最後顯示日的走勢`}
        >
            <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
    );
}

export function HistoryRanking({
    rows,
    date,
    selectedId,
    onSelect,
    comparisons,
    display,
}: {
    rows: HistoryRow[];
    date: string;
    selectedId: string | null;
    onSelect: (id: string) => void;
    comparisons: PortfolioComparison[];
    display: FrameDisplay;
}) {
    const [query, setQuery] = useState("");
    const [limit, setLimit] = useState(30);
    const elements = useRef(new Map<string, HTMLButtonElement>());
    const positions = useRef(new Map<string, number>());
    const filtered = rows
        .filter((row) =>
            `${row.code} ${row.name} ${row.industry.label}`.includes(
                query.trim(),
            ),
        )
        .sort(
            (a, b) =>
                (b.growth?.sizingGainPct ?? -Infinity) -
                    (a.growth?.sizingGainPct ?? -Infinity) ||
                a.code.localeCompare(b.code),
        );
    const shown = filtered.slice(0, limit);
    useLayoutEffect(() => {
        const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
        const next = new Map<string, number>();
        for (const row of shown) {
            const element = elements.current.get(row.securityId);
            if (!element) continue;
            const top = element.offsetTop;
            const before = positions.current.get(row.securityId);
            if (!reduce && before !== undefined && before !== top)
                element.animate(
                    [
                        { transform: `translateY(${before - top}px)` },
                        { transform: "translateY(0)" },
                    ],
                    { duration: 300, easing: "ease-out" },
                );
            next.set(row.securityId, top);
        }
        positions.current = next;
    }, [date, query, limit, rows]);
    return (
        <div className="fh-ranking">
            {display.status !== "ready" && (
                <p role={display.status === "failed" ? "alert" : "status"}>
                    {frameStatusMessage(display)}
                </p>
            )}
            {display.hasFrame && (
                <>
                    <label className="fh-search-label">
                        <span>找股票</span>
                        <input
                            placeholder="名稱、代碼或產業"
                            value={query}
                            onChange={(e) => {
                                setQuery(e.target.value);
                                setLimit(30);
                            }}
                        />
                    </label>
                    <div className="fh-ranking-list">
                        {shown.map((row) => (
                            <button
                                key={row.securityId}
                                ref={(element) => {
                                    if (element)
                                        elements.current.set(
                                            row.securityId,
                                            element,
                                        );
                                    else
                                        elements.current.delete(row.securityId);
                                }}
                                className={`fh-rank-row ${selectedId === row.securityId ? "is-selected" : ""}`}
                                onClick={() => onSelect(row.securityId)}
                            >
                                <span className="fh-rank-name">
                                    <b>
                                        {row.name}
                                        <small>{row.code}</small>
                                    </b>
                                    <span>{row.industry.label}</span>
                                    <em
                                        className={`fh-state fh-phase-${row.phase ?? "unknown"}`}
                                    >
                                        {row.launchCandidate?.date === date
                                            ? "剛開始大漲"
                                            : row.phase == null
                                              ? "尚未判斷"
                                              : phaseLabel(row.phase)}
                                    </em>
                                </span>
                                <PriceSparkline row={row} />
                                <span
                                    className="fh-rank-gain"
                                    data-return={
                                        row.growth?.sizingGainPct == null
                                            ? "unknown"
                                            : row.growth.sizingGainPct < 0
                                              ? "loss"
                                              : row.growth.sizingGainPct > 0
                                                ? "profit"
                                                : "flat"
                                    }
                                >
                                    {percent(row.growth?.sizingGainPct ?? null)}
                                    <small>
                                        {growthBasisLabel(row.growth)}
                                    </small>
                                    <small>起漲日 {row.start}</small>
                                    {comparisons.map((comparison, i) => {
                                        const stock = comparison.stocks.find(
                                            (s) =>
                                                s.securityId === row.securityId,
                                        );
                                        return (
                                            <small
                                                key={comparison.portfolio.id}
                                                style={{
                                                    color: `var(--compare-${i + 1})`,
                                                }}
                                            >
                                                {stock?.held === "held"
                                                    ? "有持有"
                                                    : stock?.held === "not-held"
                                                      ? "未持有"
                                                      : "持股未知"}
                                            </small>
                                        );
                                    })}
                                </span>
                            </button>
                        ))}
                        {!shown.length && (
                            <p className="fh-empty">
                                {date} 沒有符合{query.trim() ? "搜尋與" : ""}
                                顯示條件的股票。完整行情仍在下方時間帶與目錄。
                            </p>
                        )}
                    </div>
                    {limit < filtered.length && (
                        <button onClick={() => setLimit((v) => v + 30)}>
                            再顯示 30 檔
                        </button>
                    )}
                </>
            )}
        </div>
    );
}
