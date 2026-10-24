import { useEffect, useRef, useState } from "react";
import {
    ColorType,
    HistogramSeries,
    LineSeries,
    createChart,
    type UTCTimestamp,
} from "lightweight-charts";
import {
    percentLabel,
    revenueBars,
    revenueLabel,
    type RevenueRow,
} from "./overlays";

/** Monthly revenue on its own monthly axis. A bar marks the revenue month,
 *  not the day the figure was published. */
export function RevenueChart({
    rows,
    theme,
}: {
    rows: readonly RevenueRow[];
    theme: string;
}) {
    const host = useRef<HTMLDivElement>(null);
    const bars = revenueBars(rows);
    const [cursor, setCursor] = useState(bars.length - 1);
    useEffect(() => {
        if (!host.current || bars.length === 0) return;
        const css = getComputedStyle(host.current);
        const color = (name: string) => css.getPropertyValue(name).trim();
        const chart = createChart(host.current, {
            autoSize: true,
            layout: {
                background: {
                    type: ColorType.Solid,
                    color: color("--surface"),
                },
                textColor: color("--muted"),
                attributionLogo: false,
            },
            grid: {
                vertLines: { visible: false },
                horzLines: { color: color("--line") },
            },
            rightPriceScale: { borderColor: color("--line") },
            timeScale: { borderColor: color("--line") },
            localization: { locale: "zh-TW" },
        });
        const times = bars.map(
            (bar) =>
                (Date.parse(`${bar.month}-01T00:00:00Z`) /
                    1000) as UTCTimestamp,
        );
        chart
            .addSeries(HistogramSeries, {
                color: color("--cell-deep"),
                priceLineVisible: false,
                title: "月營收",
                priceFormat: {
                    type: "custom",
                    minMove: 1,
                    formatter: (value: number) => revenueLabel(value),
                },
            })
            .setData(
                bars.map((bar, i) => ({
                    time: times[i]!,
                    value: bar.revenueK,
                })),
            );
        chart
            .addSeries(
                LineSeries,
                {
                    color: color("--accent"),
                    lineWidth: 2,
                    priceLineVisible: false,
                    title: "年增率",
                    priceFormat: {
                        type: "custom",
                        minMove: 0.1,
                        formatter: (value: number) => percentLabel(value),
                    },
                },
                1,
            )
            .setData(
                bars.map((bar, i) =>
                    bar.yoy === null
                        ? { time: times[i]! }
                        : { time: times[i]!, value: bar.yoy },
                ),
            );
        chart
            .panes()
            .forEach((pane, i) => pane.setStretchFactor(i === 0 ? 3 : 1.4));
        const index = new Map(times.map((time, i) => [time, i]));
        chart.subscribeCrosshairMove((event) => {
            const i =
                typeof event.time === "number"
                    ? index.get(event.time as UTCTimestamp)
                    : undefined;
            setCursor(i ?? bars.length - 1);
        });
        chart.timeScale().fitContent();
        return () => chart.remove();
        // bars derives from rows; theme forces a repaint with the new colours.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [rows, theme]);
    if (bars.length === 0)
        return <p className="shared-note">這檔股票沒有已保存的月營收。</p>;
    const shown = bars[Math.min(cursor, bars.length - 1)]!;
    return (
        <div className="revenue-block">
            <div className="shared-legend">
                <span>{shown.month.replace("-", " 年 ")} 月</span>
                <span>營收 {revenueLabel(shown.revenueK)}</span>
                <span>年增 {percentLabel(shown.yoy)}</span>
            </div>
            <div
                ref={host}
                className="revenue-chart"
                role="img"
                aria-label="月營收與年增率"
            />
            <p className="shared-note">
                每根長條是該月份的營收，不是公布日；歷史資料多半沒有確切公布時間。
            </p>
        </div>
    );
}
