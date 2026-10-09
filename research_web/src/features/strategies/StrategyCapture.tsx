import { useStudioResource } from "../../api/strategyStudio";
import { studioExposurePath } from "../../api/strategyPaths";
import type { StudioExposure, StudioRun } from "../../domain/strategies/types";
import { LineChart } from "./StrategyCharts";
import { TradeCard } from "./StrategyTrades";
import { percentage, ratio } from "./format";
import {
    capturedTradeLabel,
    capturedTradeNote,
    captureWeightValue,
    captureWeightNote,
} from "./captureModel";
import { Metric, StudioState } from "./shared";
import { projectExposure, type ExposureWeightKey } from "./exposureModel";

function ExposureArea({
    rows,
    onAccount,
    projection,
}: {
    rows: StudioExposure["rows"];
    onAccount: (date: string) => void;
    projection: ReturnType<typeof projectExposure>;
}) {
    if (!rows.length) return <p className="ss-muted">逐日資金資料尚未提供。</p>;
    const width = 1000,
        height = 200,
        left = 48,
        right = 12,
        top = 10,
        bottom = 30;
    const x = (boundary: number) =>
        left + (boundary / rows.length) * (width - left - right);
    const y = (value: number) => top + (1 - value) * (height - top - bottom);
    const layers: {
        key: ExposureWeightKey;
        label: string;
        color: string;
    }[] = [
        { key: "runawayWeight", label: "飆股", color: "var(--ss-gold)" },
        { key: "otherStockWeight", label: "其他股票", color: "var(--accent)" },
        {
            key: "unknownStockWeight",
            label: "尚未判定的股票",
            color: "var(--muted)",
        },
        {
            key: "otherAssetsWeight",
            label: "其他認列資產",
            color: "var(--ss-bench)",
        },
        { key: "cashWeight", label: "現金", color: "var(--accent-soft)" },
    ];
    return (
        <div className="ss-chart">
            <svg
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label="每日資金在飆股、其他股票、未判定股票、其他資產與現金的分布"
                style={{ cursor: "pointer" }}
                onClick={(event) => {
                    const bounds = event.currentTarget.getBoundingClientRect(),
                        slot = Math.floor(
                            ((((event.clientX - bounds.left) / bounds.width) *
                                width -
                                left) /
                                (width - left - right)) *
                                rows.length,
                        );
                    onAccount(
                        rows[Math.max(0, Math.min(rows.length - 1, slot))].date,
                    );
                }}
            >
                {projection.unknownRanges.map((range) => (
                    <rect
                        key={`unknown-${range.fromIndex}`}
                        x={x(range.fromIndex)}
                        y={top}
                        width={
                            x(range.untilIndexExclusive) - x(range.fromIndex)
                        }
                        height={height - top - bottom}
                        fill="var(--muted)"
                        opacity=".2"
                    >
                        <title>
                            {rows[range.fromIndex].date}—
                            {rows[range.untilIndexExclusive - 1].date}
                            ：資料未齊；點選查看帳戶
                        </title>
                    </rect>
                ))}
                {projection.segments.flatMap((segment) =>
                    layers.map((layer, layerIndex) => {
                        const first = segment.points[0].layers[layerIndex],
                            last = segment.points.at(-1)!.layers[layerIndex];
                        const upper =
                            `M${x(segment.fromIndex)},${y(first.end)} ` +
                            segment.points
                                .map(
                                    (point) =>
                                        `L${x(point.index + 0.5)},${y(point.layers[layerIndex].end)}`,
                                )
                                .join(" ") +
                            ` L${x(segment.untilIndexExclusive)},${y(last.end)}`;
                        const lower =
                            `L${x(segment.untilIndexExclusive)},${y(last.start)} ` +
                            [...segment.points]
                                .reverse()
                                .map(
                                    (point) =>
                                        `L${x(point.index + 0.5)},${y(point.layers[layerIndex].start)}`,
                                )
                                .join(" ") +
                            ` L${x(segment.fromIndex)},${y(first.start)}`;
                        return (
                            <path
                                key={`${segment.fromIndex}-${layer.key}`}
                                d={`${upper} ${lower} Z`}
                                fill={layer.color}
                                opacity={
                                    layer.key === "otherStockWeight"
                                        ? 0.65
                                        : 0.9
                                }
                            />
                        );
                    }),
                )}
                {[0, 0.5, 1].map((value) => (
                    <g key={value}>
                        <line
                            x1={left}
                            x2={width - right}
                            y1={y(value)}
                            y2={y(value)}
                            stroke="var(--line)"
                        />
                        <text
                            x={left - 8}
                            y={y(value) + 3}
                            fontSize="11"
                            textAnchor="end"
                            fill="var(--muted)"
                        >
                            {value * 100}%
                        </text>
                    </g>
                ))}
                <text x={left} y={height - 6} fontSize="11" fill="var(--muted)">
                    {rows[0].date}
                </text>
                <text
                    x={width - right}
                    y={height - 6}
                    textAnchor="end"
                    fontSize="11"
                    fill="var(--muted)"
                >
                    {rows.at(-1)?.date}
                </text>
            </svg>
            <div className="ss-legend">
                {layers.map((layer) => (
                    <span key={layer.key}>
                        <i style={{ background: layer.color, height: 8 }} />
                        {layer.label}
                    </span>
                ))}
                {projection.unknownDays > 0 && (
                    <span>
                        <i
                            style={{
                                background: "var(--muted)",
                                height: 8,
                                opacity: 0.4,
                            }}
                        />
                        資料未齊
                    </span>
                )}
            </div>
        </div>
    );
}
export function StrategyCapture({
    run,
    onAudit,
    onAccount,
}: {
    run: StudioRun;
    onAudit: (id: string) => void;
    onAccount: (date: string) => void;
}) {
    const resource = useStudioResource<StudioExposure>(
            studioExposurePath(run.id),
        ),
        exposure = resource.data;
    const captured = run.positions
        .filter(
            (trade) =>
                trade.closeDate !== null && (trade.capture.days ?? 0) > 0,
        )
        .sort(
            (a, b) =>
                (b.capture.bestMetric ?? -Infinity) -
                (a.capture.bestMetric ?? -Infinity),
        );
    const projection = exposure ? projectExposure(exposure.rows) : null;
    const unknownDays = projection?.unknownDays ?? 0;
    return (
        <section className="ss-card">
            <h2>抓到哪些飆股</h2>
            <p className="ss-muted">
                比較固定採 100%
                門檻，逐個保存的交易日核對持股。開始大漲後，滿一年用年化、未滿一年用實際漲幅。
            </p>
            <p className="ss-small ss-muted">
                地圖可切換 60%、80%、100% 或 200%；這裡的交易數與資金比例固定用
                100%，不隨地圖選項改變。
            </p>
            {run.captureState === "loading" && (
                <p className="ss-warning">
                    飆股資料正在背景核對；交易與帳戶明細可以先看，核對完成後會自動更新。
                </p>
            )}
            {run.captureState === "failed" && (
                <p className="ss-warning">
                    飆股資料核對失敗，重疊結果保留未知；交易與帳戶紀錄仍可查看。
                </p>
            )}
            <div className="ss-kpis">
                <Metric
                    label="持有時是飆股的交易"
                    value={capturedTradeLabel(run)}
                    note={capturedTradeNote(run)}
                />
                <Metric
                    label={
                        run.captureCoverage
                            ? "完整配置日平均飆股資金"
                            : "平均放在飆股上的資金"
                    }
                    value={ratio(captureWeightValue(run))}
                    note={captureWeightNote(run)}
                />
            </div>
            <h3>資金放在哪裡</h3>
            {!exposure ? (
                <StudioState {...resource} />
            ) : (
                <>
                    <ExposureArea
                        rows={exposure.rows}
                        onAccount={onAccount}
                        projection={projection!}
                    />
                    {unknownDays > 0 && (
                        <p className="ss-warning">
                            {unknownDays}{" "}
                            天的配置資料未齊；整天以灰色缺口保留，不能視為零配置，也不接到前後已知日期。
                        </p>
                    )}
                    <details>
                        <summary>逐日飆股資金比例與帳戶驗算</summary>
                        <LineChart
                            dates={exposure.rows.map((row) => row.date)}
                            lines={[
                                {
                                    name: "放在飆股上的資金",
                                    color: "var(--ss-gold)",
                                    values: projection!.runawayValues,
                                },
                            ]}
                            format={ratio}
                            label="逐日飆股资金比例"
                            onPick={onAccount}
                        />
                    </details>
                </>
            )}
            <h3>抱過最兇的飆股</h3>
            {captured.length ? (
                <div className="ss-trade-grid">
                    {captured.slice(0, 6).map((trade) => (
                        <TradeCard
                            key={trade.id}
                            trade={trade}
                            onAudit={onAudit}
                            extra={`已確認 ${trade.capture.days} 個持有日為飆股${trade.capture.bestMetric == null ? "" : ` · 當時最高時間指標 ${percentage(trade.capture.bestMetric)}`}`}
                        />
                    ))}
                </div>
            ) : (
                <p className="ss-muted">
                    {run.captureState !== "ready" ||
                    (run.captureCoverage
                        ? run.captureCoverage.undeterminedClosedTradeCount > 0
                        : run.capturedClosedTradeCount === null)
                        ? "逐日判定尚未完成，先保留未知。"
                        : "這份回測沒有已確認的飆股持有交易。"}
                </p>
            )}
            <p className="ss-small ss-muted">
                這裡衡量持股參與與資金配置；完整行情、發動與主要上漲階段的捕捉率仍須分開研究。
            </p>
        </section>
    );
}
